"""Independent read-only acceptance oracle.

Uses sqlite3 and the public document format only. It deliberately does not call
the planner, executor, policy engine, bank verifier or production digest helper.
It checks accounting/authorization invariants; fixture-specific outcomes belong
to the external acceptance cases, not to a claim of complete bank compliance.
"""
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def inspect_database(path):
    try:
        return _inspect_database(path)
    except (sqlite3.Error, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return {"passed": False, "checks": 0, "issues": [{"code": "ORACLE_READ_OR_SCHEMA_ERROR", "entity_id": "database"}], "source": "independent_sqlite_readonly_oracle"}


def _inspect_database(path):
    issues, checks = [], 0

    def check(condition, code, entity):
        nonlocal checks
        checks += 1
        if not condition:
            issues.append({"code": code, "entity_id": str(entity)})

    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        accounts = {r["id"]: dict(r) for r in db.execute("SELECT * FROM accounts")}
        ledger = [dict(r) for r in db.execute("SELECT * FROM ledger")]
        receipts = {r["id"]: dict(r) for r in db.execute("SELECT * FROM receipts")}
        plans = {r["id"]: {**dict(r), "document": json.loads(r["document"]), "history": json.loads(r["history"])} for r in db.execute("SELECT * FROM plans")}
        approvals = [{**dict(r), "document": json.loads(r["document"])} for r in db.execute("SELECT * FROM approvals")]
        recipients = {r["id"]: dict(r) for r in db.execute("SELECT * FROM recipients")}
        subscriptions = {r["id"]: dict(r) for r in db.execute("SELECT * FROM subscriptions")}
        audit = [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id")]
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if any(p["document"].get("schema_version") == "0.4" for p in plans.values()):
            check({"task_conflicts", "intent_preferences", "conversations", "conversation_turns", "conversation_clarifications"} <= tables, "COORDINATION_SCHEMA_MISSING", "database")
        conflicts = [{**dict(r), "document": json.loads(r["document"])} for r in db.execute("SELECT * FROM task_conflicts")] if "task_conflicts" in tables else []
        # Reconstruct conflict windows independently; authorization is frozen for
        # all mutations and yellow reads while an explicit choice is unresolved.
        for conflict in conflicts:
            cd = conflict["document"]
            end = cd.get("resolved_at") or cd.get("stale_at")
            for pid, version_number in cd["versions"].items():
                p = plans.get(pid)
                check(bool(p) and p["user_id"] == conflict["user_id"], "CONFLICT_OWNER_INVALID", conflict["id"])
                if cd["status"] == "open" and p:
                    check(conflict["id"] in p["document"].get("conflict_ids", []) and p["document"]["status"] == "waiting_conflict", "CONFLICT_NOT_FROZEN", pid)
                for rr in receipts.values():
                    rd = json.loads(rr["document"])
                    if rr["plan_id"] == pid and rr["plan_version"] == version_number and cd["created_at"] <= rd["created_at"] and (not end or rd["created_at"] < end):
                        check(rd["operation"] in {"balance", "transactions", "analyze_bills", "commitments", "recipients"}, "EXECUTION_DURING_CONFLICT", rr["id"])
        transactions = defaultdict(list)
        for item in ledger:
            transactions[item["transaction_id"]].append(item)
        for key, account in accounts.items():
            net = sum(x["amount_cents"] for x in ledger if x["account_id"] == key)
            check(account["balance_cents"] == account["opening_cents"] + net and account["balance_cents"] >= 0, "ACCOUNT_LEDGER_MISMATCH", key)
        for tx, entries in transactions.items():
            check(len(entries) == 2 and len({e["account_id"] for e in entries}) == 2 and sum(e["amount_cents"] for e in entries) == 0, "UNBALANCED_TRANSACTION", tx)
        keys, bound_steps = set(), set()
        for rid, row in receipts.items():
            doc = json.loads(row["document"])
            plan = plans.get(row["plan_id"])
            versions = [p for p in ([plan["document"]] + plan["history"] if plan else []) if p["version"] == row["plan_version"]]
            source = next((s for p in versions for s in p["steps"] if s["step_id"] == row["step_id"] and _hash(s["action"]) == doc["action_hash"]), None)
            binding = (row["user_id"], row["idempotency_key"])
            step_binding = (row["plan_id"], row["plan_version"], row["step_id"])
            check(binding not in keys and step_binding not in bound_steps, "DUPLICATE_EXECUTION", rid)
            keys.add(binding)
            bound_steps.add(step_binding)
            check(_hash(doc) == row["document_hash"], "RECEIPT_HASH_MISMATCH", rid)
            check(bool(source) and plan["user_id"] == row["user_id"] and doc["receipt_id"] == rid and doc["plan_id"] == row["plan_id"] and doc["plan_version"] == row["plan_version"] and doc["step_id"] == row["step_id"], "RECEIPT_BINDING_INVALID", rid)
            if not source:
                continue
            action = source["action"]
            check(doc["operation"] == action["tool"] and accounts.get(action["account_id"], {}).get("user_id") == row["user_id"], "ACTION_OWNER_MISMATCH", rid)
            # Every predecessor must have a canonical earlier receipt, not just a UI flag.
            version = versions[0]
            for dep in source["depends_on"]:
                dep_step = next((s for s in version["steps"] if s["step_id"] == dep), None)
                dep_row = receipts.get(dep_step.get("receipt_id")) if dep_step else None
                check(bool(dep_row) and json.loads(dep_row["document"])["created_at"] <= doc["created_at"], "DEPENDENCY_NOT_EXECUTED", rid)
            tool = action["tool"]
            if tool in {"subscriptions", "cancel_subscription", "transfer", "schedule_transfer"}:
                grants = [a["document"] for a in approvals if a["user_id"] == row["user_id"] and a["document"]["plan_id"] == row["plan_id"] and a["document"]["plan_version"] == row["plan_version"] and a["document"]["step_id"] == row["step_id"] and a["document"]["status"] == "consumed"]
                check(len(grants) == 1 and grants[0]["action_hash"] == doc["action_hash"] and grants[0]["action"] == action, "AUTHORIZATION_MISSING_OR_WRONG", rid)
                if grants:
                    minimum = version["minimum_balance_cents"]
                    scope = {"user_id": row["user_id"], "plan_id": row["plan_id"], "version": row["plan_version"], "step_id": row["step_id"], "minimum_balance_cents": minimum, "depends_on": source["depends_on"], "action": action}
                    check(grants[0].get("scope_hash") == _hash(scope), "APPROVAL_SCOPE_INVALID", rid)
                    expected = "yellow"
                    if tool in {"transfer", "schedule_transfer"}:
                        local = datetime.fromisoformat(doc["created_at"]).astimezone(ZoneInfo("Asia/Shanghai"))
                        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
                        spent = -sum(e["amount_cents"] for e in ledger if e["category"] == "transfer" and e["amount_cents"] < 0 and accounts[e["account_id"]]["user_id"] == row["user_id"] and start <= e["created_at"] <= doc["created_at"] and e["transaction_id"] != doc.get("transaction_id"))
                        expected = "red" if spent + action["amount_cents"] > 100_000 else "yellow"
                    check(grants[0]["level"] == expected, "POLICY_LEVEL_INVALID", rid)
            if tool == "transfer":
                check(doc["data"].get("amount_cents") == action["amount_cents"] and doc["data"].get("recipient_id") == action.get("recipient_id"), "TRANSFER_RESULT_MISMATCH", rid)
                target = recipients.get(action.get("recipient_id"), {})
                entries = transactions.get(doc.get("transaction_id"), [])
                check(target.get("user_id") == row["user_id"] and len(entries) == 2 and any(e["account_id"] == action["account_id"] and e["amount_cents"] == -action["amount_cents"] for e in entries) and any(e["account_id"] == target.get("account_id") and e["amount_cents"] == action["amount_cents"] for e in entries), "TRANSFER_LEDGER_BINDING_INVALID", rid)
                constraint = doc["data"].get("constraints_at_execution", {})
                check(constraint.get("balance_cents", 0) - action["amount_cents"] >= constraint.get("minimum_balance_cents", 0) + constraint.get("committed_cents", 0), "TRANSFER_CONSTRAINT_VIOLATED", rid)
            if tool == "cancel_subscription":
                sub = subscriptions.get(action["subscription_id"], {})
                check(sub.get("user_id") == row["user_id"] and sub.get("account_id") == action["account_id"] and sub.get("active") == 0 and doc["data"].get("active") is False and not doc.get("transaction_id"), "CANCELLATION_STATE_INVALID", rid)
                by_id = {s["step_id"]: s for s in version["steps"]}
                visited, todo = set(), list(source["depends_on"])
                while todo:
                    key = todo.pop()
                    if key not in visited:
                        visited.add(key)
                        todo.extend(by_id.get(key, {}).get("depends_on", []))
                prior_queries = [s for s in version["steps"] if s["step_id"] in visited and s["action"]["tool"] == "subscriptions" and s["action"]["account_id"] == action["account_id"]]
                query_found = False
                for query in prior_queries:
                    qr = receipts.get(query.get("receipt_id"))
                    if qr:
                        qd = json.loads(qr["document"])
                        query_found |= qr["user_id"] == row["user_id"] and qr["plan_id"] == row["plan_id"] and qd["created_at"] <= doc["created_at"] and any(s["subscription_id"] == action["subscription_id"] for s in qd["data"].get("items", []))
                check(query_found, "CANCEL_WITHOUT_QUERY_EVIDENCE", rid)
        for plan in plans.values():
            review = plan["document"].get("interruption")
            if review:
                for rid in review["retained_receipt_ids"] + review["unknown_receipt_ids"]:
                    rr = receipts.get(rid)
                    check(bool(rr) and rr["plan_id"] == plan["id"], "INTERRUPTION_LOST_RECEIPT", plan["id"])
                stopped = set(review["cancelled_step_ids"] + review["blocked_step_ids"])
                for rr in receipts.values():
                    if rr["plan_id"] == plan["id"] and rr["plan_version"] == plan["document"]["version"] and rr["step_id"] in stopped:
                        check(json.loads(rr["document"])["created_at"] < review["created_at"], "EXECUTION_AFTER_INTERRUPTION", rr["id"])
            if plan["document"]["status"] == "succeeded":
                check(all(s["status"] == "succeeded" for s in plan["document"]["steps"]), "PLAN_TERMINAL_STATUS_INVALID", plan["id"])
            for step in plan["document"]["steps"]:
                if step["status"] == "succeeded":
                    row = receipts.get(step.get("receipt_id"))
                    check(bool(row) and row["plan_id"] == plan["id"] and step.get("result", {}).get("verified") is True and step["result"].get("receipt") == json.loads(row["document"]), "PLAN_SUCCESS_WITHOUT_EVIDENCE", plan["id"] + ":" + step["step_id"])
                if step["status"] == "pending_verification":
                    check(step.get("result") is None, "UNVERIFIED_RESULT_EXPOSED", plan["id"])
        previous = "0" * 64
        for event in audit:
            payload = {k: json.loads(event[k]) if k == "details" else event[k] for k in ("user_id", "event", "entity_id", "details", "created_at")}
            check(event["previous_hash"] == previous and event["event_hash"] == _hash({"previous_hash": previous, "event": payload}), "AUDIT_CHAIN_INVALID", event["id"])
            previous = event["event_hash"]
        db.rollback()
    return {"passed": not issues, "checks": checks, "issues": issues, "counts": {"accounts": len(accounts), "transactions": len(transactions), "receipts": len(receipts), "plans": len(plans), "audit_events": len(audit)}, "source": "independent_sqlite_readonly_oracle", "scope": "synthetic accounting, authorization, dependency evidence and audit invariants"}
