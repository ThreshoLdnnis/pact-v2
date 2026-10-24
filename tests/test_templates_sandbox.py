"""Template composition, isolated controls and independently checked outcomes."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from pact.app import create_app
from pact.common import now
from pact.storage import Account, ApprovalRow, Commitment, FaultRow, Ledger, ReceiptRow, Subscription
from services.sandbox.acceptance import inspect_database
from tests.conftest import login
from tests.test_workflows import API, approve, balance, command, finish, plan, run

ADMIN = {"X-Sandbox-Admin": "independent-synthetic-test-secret-123"}


@pytest.fixture
def controlled(tmp_path, monkeypatch):
    monkeypatch.setenv("PACT_SANDBOX_CONTROLS", "1")
    monkeypatch.setenv("PACT_SANDBOX_ADMIN_TOKEN", ADMIN["X-Sandbox-Admin"])
    monkeypatch.delenv("PACT_OLLAMA_URL", raising=False)
    monkeypatch.delenv("PACT_OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("PACT_MODEL_PROVIDER", "")
    monkeypatch.setenv("PACT_DEMO_PIN", "246810")
    app = create_app("sqlite:///" + (tmp_path / "controlled.db").as_posix(), scheduler=False)
    with TestClient(app) as client:
        yield app, client


def composition(client, auth, serial=False, reverse=False):
    invocations = [
        {"instance_id": "bills", "template_id": "bill_analysis", "action": {"tool": "analyze_bills", "account_id": "acct-alice"}},
        {"instance_id": "membership", "template_id": "subscription_management", "depends_on": ["bills"] if serial else [], "action": {"tool": "cancel_subscription", "account_id": "acct-alice", "subscription_id": "sub-video"}},
        {"instance_id": "payment", "template_id": "smart_transfer", "depends_on": ["bills", "membership"], "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_query": "张三", "amount_cents": 50000}},
    ]
    if reverse:
        invocations.reverse()
    response = client.post(API + "/agent/compositions", headers=auth, json={"title": "分析账单、取消视频会员、再给张三转账500元", "instances": invocations})
    assert response.status_code == 200, response.text
    return response.json()


def oracle(app):
    result = inspect_database(app.state.db.engine.url.database)
    assert result["passed"], result
    return result


def arm(client, p, tool, point):
    step = next(s for s in p["steps"] if s["action"]["tool"] == tool)
    r = client.post(API + "/sandbox/faults", headers=ADMIN, json={"plan_id": p["plan_id"], "plan_version": p["version"], "step_id": step["step_id"], "point": point})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("serial,reverse", [(False, False), (True, False), (False, True)])
def test_composed_templates_have_same_authority_and_balanced_outcome(controlled, serial, reverse):
    app, client = controlled
    auth = login(client)
    before = balance(client, auth)
    p = composition(client, auth, serial, reverse)
    assert {s["template_id"] for s in p["steps"]} == {"bill_analysis", "subscription_management", "smart_transfer"}
    cancellation = next(s for s in p["steps"] if s["action"]["tool"] == "cancel_subscription")
    query = next(s for s in p["steps"] if s["action"]["tool"] == "subscriptions")
    assert cancellation["depends_on"] == [query["step_id"]]
    assert cancellation["template_instance_id"] == query["template_instance_id"] == "membership"
    p = run(client, auth, p)
    assert next(s for s in p["steps"] if s["step_id"] == "bills")["status"] == "succeeded"
    assert next(s for s in p["steps"] if s["step_id"] == "payment")["approval_id"] is None
    assert balance(client, auth) == before
    assert finish(client, auth, p)["status"] == "succeeded"
    assert balance(client, auth) == before - 50000
    with app.state.db.session() as s:
        assert not s.get(Subscription, "sub-video").active
        assert s.get(Commitment, "com-video").status == "cancelled"
        grants = s.scalars(select(ApprovalRow)).all()
        assert sorted(a.document["action"]["tool"] for a in grants) == ["cancel_subscription", "subscriptions", "transfer"]
        assert all(a.document["status"] == "consumed" and a.document["level"] == "yellow" for a in grants)
    oracle(app)


def test_standalone_and_composed_subscription_use_same_internal_template(client, auth):
    standalone = plan(client, auth, "取消视频会员")
    combined = composition(client, auth)
    a = [s["action"]["tool"] for s in standalone["steps"]]
    b = [s["action"]["tool"] for s in combined["steps"] if s["template_id"] == "subscription_management"]
    assert a == b == ["subscriptions", "cancel_subscription"]
    assert len(client.get(API + "/agent/templates", headers=auth).json()["items"]) == 3


def test_direct_execute_cannot_jump_over_composed_dependencies(controlled):
    app, client = controlled
    auth = login(client)
    p = composition(client, auth)
    before = balance(client, auth)
    pay = next(s for s in p["steps"] if s["action"]["tool"] == "transfer")
    assert client.post(API + "/banking/execute", headers=auth, json=command(p, pay)).status_code == 409
    assert balance(client, auth) == before
    assert not client.get(API + "/policy/approvals", headers=auth).json()["items"]
    oracle(app)


@pytest.mark.parametrize("tamper", ["cycle", "unknown", "wrong_template", "forged_gate"])
def test_composition_rejects_invalid_or_model_owned_security_fields(client, auth, tamper):
    body = {"title": "bad", "instances": [{"instance_id": "x", "template_id": "bill_analysis", "action": {"tool": "analyze_bills", "account_id": "acct-alice"}}]}
    if tamper in {"cycle", "unknown"}:
        body["instances"][0]["depends_on"] = ["x" if tamper == "cycle" else "missing"]
    elif tamper == "wrong_template":
        body["instances"][0]["template_id"] = "smart_transfer"
    else:
        body["instances"][0]["approved"] = True
    assert client.post(API + "/agent/compositions", headers=auth, json=body).status_code == 422


def test_independent_branch_progresses_while_query_waits(client, auth):
    p = composition(client, auth, reverse=True)
    p = run(client, auth, p)
    assert next(s for s in p["steps"] if s["step_id"] == "bills")["status"] == "succeeded"
    assert next(s for s in p["steps"] if s["action"]["tool"] == "subscriptions")["status"] == "waiting_approval"


def test_dynamic_daily_limit_invalidates_preapproved_yellow_payment(controlled):
    app, client = controlled
    auth = login(client)
    p = run(client, auth, composition(client, auth))
    for _ in range(2):
        approve(client, auth, p)
        p = run(client, auth, p)
    payment = next(s for s in p["steps"] if s["status"] == "waiting_approval")
    assert payment["action"]["tool"] == "transfer" and payment["risk_level"] == "yellow"
    approve(client, auth, p)
    assert finish(client, auth, plan(client, auth, "给李四转账600元"))["status"] == "succeeded"
    before = balance(client, auth)
    p = run(client, auth, p)
    payment = next(s for s in p["steps"] if s["action"]["tool"] == "transfer")
    assert payment["status"] == "waiting_approval" and payment["risk_level"] == "red"
    assert balance(client, auth) == before
    assert finish(client, auth, p)["status"] == "succeeded"
    oracle(app)


def test_controls_default_disabled_and_regular_bearer_has_no_admin_authority(client, auth, controlled):
    assert client.post(API + "/sandbox/reset", headers=ADMIN, json={"confirmation": "RESET_SYNTHETIC_DATA"}).status_code == 404
    _, c = controlled
    for headers in ({}, login(c), {"X-Sandbox-Admin": "wrong"}):
        assert c.post(API + "/sandbox/reset", headers=headers, json={"confirmation": "RESET_SYNTHETIC_DATA"}).status_code == 403
    assert c.post(API + "/sandbox/reset", headers=ADMIN, json={"confirmation": "yes"}).status_code == 422


def test_reset_revokes_all_old_business_state_and_preserves_audit(controlled):
    app, client = controlled
    auth = login(client)
    p = finish(client, auth, plan(client, auth))
    old_rid = p["steps"][0]["receipt_id"]
    previous_audit_count = oracle(app)["counts"]["audit_events"]
    r = client.post(API + "/sandbox/reset", headers=ADMIN, json={"confirmation": "RESET_SYNTHETIC_DATA", "scenario": "baseline"})
    assert r.status_code == 200 and r.json()["audit_preserved"]
    assert client.get(API + "/banking/accounts", headers=auth).status_code == 401
    fresh = login(client)
    assert client.get(API + "/agent/plans", headers=fresh).json()["items"] == []
    assert client.get(API + "/policy/approvals", headers=fresh).json()["items"] == []
    assert client.get(API + f"/banking/receipts/{old_rid}", headers=fresh).status_code == 404
    assert balance(client, fresh) == 1_553_400
    assert client.post(API + "/banking/execute", headers=fresh, json=command(p)).status_code == 404
    assert oracle(app)["counts"]["audit_events"] > previous_audit_count


def test_tight_budget_only_succeeds_after_verified_future_release(controlled):
    app, client = controlled
    client.post(API + "/sandbox/reset", headers=ADMIN, json={"confirmation": "RESET_SYNTHETIC_DATA", "scenario": "tight_budget"})
    auth = login(client)
    snap = client.get(API + "/banking/accounts/acct-alice/balance", headers=auth).json()["constraints"]
    assert snap["spendable_cents"] == 40200
    p = finish(client, auth, composition(client, auth))
    assert p["status"] == "succeeded" and balance(client, auth) == 150000
    cancelled = next(s for s in p["steps"] if s["action"]["tool"] == "cancel_subscription")
    assert cancelled["result"]["receipt"]["data"]["released_next_commitment_cents"] == 9800
    oracle(app)


@pytest.mark.parametrize("point", ["before_post_reject", "after_mutation_rollback", "verify_timeout"])
@pytest.mark.parametrize("tool,message", [("transfer", "给张三转账500元"), ("cancel_subscription", "取消视频会员")])
def test_faults_preserve_canonical_money_and_approval_state(controlled, point, tool, message):
    app, client = controlled
    auth = login(client)
    p = run(client, auth, plan(client, auth, message))
    if tool == "cancel_subscription":
        approve(client, auth, p)
        p = run(client, auth, p)
    fault = arm(client, p, tool, point)
    step = next(s for s in p["steps"] if s["action"]["tool"] == tool)
    before = balance(client, auth)
    approve(client, auth, p)
    p = run(client, auth, p)
    target = next(s for s in p["steps"] if s["action"]["tool"] == tool)
    if point == "verify_timeout":
        assert p["status"] == "pending_verification" and target["result"] is None
        assert balance(client, auth) == before - (50000 if tool == "transfer" else 0)
        for _ in range(2):
            assert run(client, auth, p)["status"] == "pending_verification"
        p = client.post(API + f"/agent/plans/{p['plan_id']}/reconcile", headers=auth).json()
        assert p["status"] == "succeeded"
        assert balance(client, auth) == before - (50000 if tool == "transfer" else 0)
    else:
        assert target["status"] == "failed" and balance(client, auth) == before
        with app.state.db.session() as s:
            assert s.get(ApprovalRow, step["approval_id"]).document["status"] == "approved"
            if tool == "cancel_subscription":
                assert s.get(Subscription, "sub-video").active
                assert s.get(Commitment, "com-video").status == "active"
    with app.state.db.session() as s:
        assert s.get(FaultRow, fault["fault_id"]).remaining == 0
    oracle(app)


def test_cancel_pending_blocks_dependent_payment_until_explicit_reconcile_and_resume(controlled):
    app, client = controlled
    auth = login(client)
    p = composition(client, auth)
    arm(client, p, "cancel_subscription", "verify_timeout")
    p = run(client, auth, p)
    for _ in range(2):
        approve(client, auth, p)
        p = run(client, auth, p)
    before = balance(client, auth)
    assert p["status"] == "pending_verification"
    assert next(s for s in p["steps"] if s["action"]["tool"] == "transfer")["approval_id"] is None
    reconciled = client.post(API + f"/agent/plans/{p['plan_id']}/reconcile", headers=auth).json()
    assert balance(client, auth) == before and reconciled["status"] == "planned"
    assert finish(client, auth, reconciled)["status"] == "succeeded"
    oracle(app)


def test_fault_targets_expire_and_cannot_be_duplicated_or_widened(controlled):
    app, client = controlled
    auth = login(client)
    p = plan(client, auth)
    fault = arm(client, p, "transfer", "before_post_reject")
    assert client.post(API + "/sandbox/faults", headers=ADMIN, json={k: fault[k] for k in ("plan_id", "plan_version", "step_id", "point")}).status_code == 409
    with app.state.db.session(write=True) as s:
        s.get(FaultRow, fault["fault_id"]).expires_at = (now() - timedelta(seconds=1)).isoformat()
    assert finish(client, auth, p)["status"] == "succeeded"
    body = {"plan_id": "*", "plan_version": 1, "step_id": "*", "point": "verify_timeout", "approved": True}
    assert client.post(API + "/sandbox/faults", headers=ADMIN, json=body).status_code == 422
    oracle(app)


def test_agent_tools_cannot_invoke_reset_fault_or_sql(client, auth):
    for tool in ("sandbox/reset", "reset", "faults", "sql"):
        r = client.post(API + "/agent/candidates", headers=auth, json={"title": "attack", "steps": [{"step_id": "x", "action": {"tool": tool, "account_id": "acct-alice"}}]})
        assert r.status_code == 422


def test_armed_fault_survives_restart_but_controls_off_disable_it(controlled, monkeypatch):
    app, client = controlled
    auth = login(client)
    p = plan(client, auth)
    fault = arm(client, p, "transfer", "before_post_reject")
    monkeypatch.setenv("PACT_SANDBOX_CONTROLS", "0")
    restarted = create_app(str(app.state.db.engine.url), scheduler=False)
    with TestClient(restarted) as c:
        assert c.get(API + "/meta").json()["sandbox_controls_enabled"] is False
        assert c.get(API + "/sandbox/acceptance", headers=ADMIN).status_code == 404
        assert finish(c, auth, p)["status"] == "succeeded"
        with restarted.state.db.session() as s:
            assert s.get(FaultRow, fault["fault_id"]).remaining == 1
    oracle(app)


def test_fault_restarts_and_is_consumed_once(controlled):
    app, client = controlled
    auth = login(client)
    p = plan(client, auth)
    arm(client, p, "transfer", "verify_timeout")
    restarted = create_app(str(app.state.db.engine.url), scheduler=False)
    with TestClient(restarted) as c:
        p = run(c, auth, p)
        approve(c, auth, p)
        p = run(c, auth, p)
        assert p["status"] == "pending_verification"
        assert c.post(API + f"/agent/plans/{p['plan_id']}/reconcile", headers=auth).json()["status"] == "succeeded"
    oracle(app)


def test_fault_cannot_follow_new_plan_version(controlled):
    app, client = controlled
    auth = login(client)
    p = plan(client, auth)
    arm(client, p, "transfer", "before_post_reject")
    r = client.post(API + f"/agent/plans/{p['plan_id']}/replan", headers=auth, json={"message": "给张三转账500元"})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert finish(client, auth, r.json())["status"] == "succeeded"
    oracle(app)


def test_short_admin_secret_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PACT_SANDBOX_CONTROLS", "1")
    monkeypatch.setenv("PACT_SANDBOX_ADMIN_TOKEN", "246810")
    app = create_app("sqlite:///" + (tmp_path / "weak.db").as_posix(), scheduler=False)
    with TestClient(app) as c:
        assert not c.get(API + "/meta").json()["sandbox_controls_enabled"]
        assert c.get(API + "/sandbox/acceptance", headers={"X-Sandbox-Admin": "246810"}).status_code == 404


def test_read_fault_cannot_use_write_rollback_point_and_clear_does_not_change_business(controlled):
    app, client = controlled
    auth = login(client)
    p = plan(client, auth, "分析账单")
    body = {"plan_id": p["plan_id"], "plan_version": p["version"], "step_id": p["steps"][0]["step_id"], "point": "after_mutation_rollback"}
    assert client.post(API + "/sandbox/faults", headers=ADMIN, json=body).status_code == 422
    arm(client, p, "analyze_bills", "before_post_reject")
    assert client.post(API + "/sandbox/faults/clear", headers=ADMIN, json={}).status_code == 200
    assert finish(client, auth, p)["status"] == "succeeded"
    oracle(app)


def test_model_cannot_omit_required_cancel_or_remove_transfer_join(client, auth, monkeypatch):
    monkeypatch.setenv("PACT_OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("PACT_OLLAMA_MODEL", "stub")
    payload = {"title": "candidate", "steps": [
        {"step_id": "b", "action": {"tool": "analyze_bills", "account_id": "acct-alice"}},
        {"step_id": "c", "action": {"tool": "cancel_subscription", "account_id": "acct-alice", "subscription_id": "sub-video"}},
        {"step_id": "t", "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_id": "rcp-zhang", "amount_cents": 50000}},
    ]}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(200, request=httpx.Request("POST", "http://localhost"), json={"message": {"content": json.dumps(payload)}}))
    p = plan(client, auth, "分析账单、取消视频会员、再给张三转账500元")
    assert next(s for s in p["steps"] if s["step_id"] == "t")["depends_on"] == ["b", "c"]
    payload["steps"].pop(1)
    r = client.post(API + "/agent/plans", headers=auth, json={"message": "分析账单、取消视频会员、再给张三转账500元"})
    assert r.status_code == 502


def test_replan_reuses_paid_template_when_name_and_resolved_id_are_same(controlled):
    app, client = controlled
    auth = login(client)
    before = balance(client, auth)
    body = {"title": "partial", "steps": [
        {"step_id": "first", "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_id": "rcp-zhang", "amount_cents": 10000}},
        {"step_id": "second", "depends_on": ["first"], "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_id": "rcp-li", "amount_cents": 9999900}},
    ]}
    p = finish(client, auth, client.post(API + "/agent/candidates", headers=auth, json=body).json())
    assert p["status"] == "partially_completed"
    rid = p["steps"][0]["receipt_id"]
    p = client.post(API + f"/agent/plans/{p['plan_id']}/replan", headers=auth, json={"message": "给张三转账100元，给李四转账50元"}).json()
    assert len(p["steps"]) == 2 and p["steps"][0]["receipt_id"] == rid
    assert finish(client, auth, p)["status"] == "succeeded"
    assert balance(client, auth) == before - 15000
    assert oracle(app)["counts"]["receipts"] == 2


@pytest.mark.parametrize("tamper,expected", [("balance", "ACCOUNT_LEDGER_MISMATCH"), ("receipt", "TRANSFER_LEDGER_BINDING_INVALID"), ("approval", "AUTHORIZATION_MISSING_OR_WRONG"), ("status", "PLAN_SUCCESS_WITHOUT_EVIDENCE")])
def test_independent_oracle_detects_tampering_without_calling_bank_verifier(controlled, monkeypatch, tamper, expected):
    app, client = controlled
    auth = login(client)
    p = finish(client, auth, plan(client, auth))
    oracle(app)
    with app.state.db.session(write=True) as s:
        if tamper == "balance":
            s.get(Account, "acct-alice").balance_cents += 1
        elif tamper == "receipt":
            receipt = s.get(ReceiptRow, p["steps"][0]["receipt_id"])
            doc = deepcopy(receipt.document)
            doc["transaction_id"] = "made-up-tx"
            receipt.document = doc
            receipt.document_hash = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        elif tamper == "approval":
            s.get(ApprovalRow, p["steps"][0]["approval_id"]).document = {**s.get(ApprovalRow, p["steps"][0]["approval_id"]).document, "status": "approved"}
        else:
            from pact.storage import PlanRow
            row = s.get(PlanRow, p["plan_id"])
            doc = deepcopy(row.document)
            doc["steps"][0]["result"]["verified"] = False
            row.document = doc
    from services.banking import service as bank
    monkeypatch.setattr(bank, "verify_receipt", lambda *a: {"verified": True})
    result = client.get(API + "/sandbox/acceptance", headers=ADMIN).json()
    assert not result["passed"]
    assert expected in {x["code"] for x in result["issues"]}
