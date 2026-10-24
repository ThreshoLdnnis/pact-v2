"""Core business boundaries over real HTTP; never connects to a real bank."""
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
token = ""


def call(path, body=None, expected=200):
    req = Request(base + "/api/v1" + path, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urlopen(req, timeout=15) as response:
            assert response.status == expected
            return json.load(response)
    except HTTPError as error:
        assert error.code == expected, error.read().decode()
        return json.load(error)


def run(p):
    return call(f"/agent/plans/{p['plan_id']}/run", {})


def approve(p):
    step = next(s for s in p["steps"] if s["status"] == "waiting_approval")
    aid = step["approval_id"]
    code = call(f"/policy/approvals/{aid}/challenge", {})["demo_code"] if step["risk_level"] == "red" else None
    call(f"/policy/approvals/{aid}/decision", {"decision": "approve", "challenge_code": code})


def finish(p):
    for _ in range(8):
        p = run(p)
        if p["status"] in {"succeeded", "failed", "partially_completed"}:
            return p
        assert p["status"] == "waiting_approval", p["status"]
        approve(p)
    raise AssertionError("workflow did not stop")


token = call("/auth/demo-session", {"user_id": "alice", "pin": "246810"})["access_token"]
initial = call("/banking/accounts")["items"][0]["balance_cents"]
call("/banking/accounts/acct-alice/subscriptions", expected=403)
query = run(call("/agent/plans", {"message": "查询订阅"}))
assert query["steps"][0]["risk_level"] == "yellow"
query = finish(query)
snapshot = call("/banking/accounts/acct-alice/subscriptions?receipt_id=" + query["steps"][0]["receipt_id"])
assert snapshot["source_receipt_id"] and snapshot["snapshot_at"]

p = run(call("/agent/plans", {"message": "给王五转账100元"}))
assert p["status"] == "waiting_clarification"
step = p["steps"][0]
assert len(step["clarification"]["options"]) == 2
p = call(f"/agent/plans/{p['plan_id']}/select-recipient", {"plan_version": p["version"], "step_id": step["step_id"], "clarification_id": step["clarification"]["clarification_id"], "recipient_id": "rcp-wang-a"})
assert finish(p)["status"] == "succeeded"

p = run(call("/agent/plans", {"message": "给李四转账100元"}))
approve(p)
p = call(f"/agent/plans/{p['plan_id']}/handoff", {"plan_version": p["version"], "reason": "HTTP验收人工复核"})
call(f"/agent/plans/{p['plan_id']}/resume", {}, expected=409)
p = call(f"/agent/plans/{p['plan_id']}/handoff/release", {"plan_version": p["version"], "note": "交还，重新授权"})
assert p["status"] == "paused"
p = call(f"/agent/plans/{p['plan_id']}/resume", {})
assert p["status"] == "waiting_approval"
assert finish(p)["status"] == "succeeded"

p = call("/agent/candidates", {"title": "转账部分完成验收", "steps": [
    {"step_id": "one", "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_id": "rcp-li", "amount_cents": 10000}},
    {"step_id": "two", "depends_on": ["one"], "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_id": "rcp-zhang", "amount_cents": 9999900}}]})
p = finish(p)
assert p["status"] == "partially_completed" and p["progress"]["completed"] == 1 and p["progress"]["failed"] == 1
assert call("/banking/accounts")["items"][0]["balance_cents"] == initial - 30000
assert call("/banking/reconciliation")["balanced"]
result = {"status": "passed", "version": "0.4", "cases": ["yellow_subscription_query_and_snapshot", "same_name_selection_then_separate_approval", "handoff_blocks_resume_and_requires_new_approval", "partial_completion_preserves_payment"], "balance_delta_cents": -30000, "balanced": True}
Path("reports/business-http-smoke.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result))
