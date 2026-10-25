"""HTTP acceptance for a DISPOSABLE synthetic sandbox; resets all demo data.

Requires separately enabled controls and PACT_SANDBOX_ADMIN_TOKEN. It never gets
authority from Agent output. Do not point at a demo whose history you want to keep.
"""
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
admin = os.environ["PACT_SANDBOX_ADMIN_TOKEN"]
token = ""
cases = []


def call(path, body=None, control=False, expected=200):
    headers = {"Content-Type": "application/json", **({"X-Sandbox-Admin": admin} if control else {"Authorization": "Bearer " + token})}
    request = Request(base + "/api/v1" + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            assert response.status == expected
            return json.load(response)
    except HTTPError as error:
        assert error.code == expected, error.read().decode()
        return json.load(error)


def reset(scenario="baseline"):
    global token
    call("/sandbox/reset", {"confirmation": "RESET_SYNTHETIC_DATA", "scenario": scenario}, control=True)
    if token:
        call("/banking/accounts", expected=401)
    token = call("/auth/demo-session", {"user_id": "alice", "pin": "246810"})["access_token"]


def make(message="分析账单、取消视频会员、再给张三转账500元"):
    return call("/agent/plans", {"message": message})


def run(p):
    return call(f"/agent/plans/{p['plan_id']}/run", {})


def approve(p):
    step = next(s for s in p["steps"] if s["status"] == "waiting_approval")
    aid = step["approval_id"]
    code = call(f"/policy/approvals/{aid}/challenge", {})["demo_code"] if step["risk_level"] == "red" else None
    call(f"/policy/approvals/{aid}/decision", {"decision": "approve", "challenge_code": code})
    return step["action"]["tool"]


def balance():
    return call("/banking/accounts")["items"][0]["balance_cents"]


def inspect():
    report = call("/sandbox/acceptance", control=True)
    assert report["passed"], report
    return report


def finish(p):
    grants = []
    for _ in range(12):
        p = run(p)
        if p["status"] == "succeeded":
            return p, grants
        assert p["status"] == "waiting_approval", p
        grants.append(approve(p))
    raise AssertionError("workflow did not finish")


reset()
before = balance()
p = run(make())
assert next(s for s in p["steps"] if s["action"]["tool"] == "analyze_bills")["status"] == "succeeded"
assert next(s for s in p["steps"] if s["action"]["tool"] == "transfer")["approval_id"] is None
p, grants = finish(p)
assert grants == ["subscriptions", "cancel_subscription", "transfer"]
assert balance() == before - 50000
assert all(call(f"/banking/receipts/{s['receipt_id']}/verify")["verified"] for s in p["steps"])
cases.append({"case": "parallel_prefix_then_verified_cancel_then_500_transfer", "passed": True, "approvals": grants, "balance_delta_cents": -50000, "oracle": inspect()})
old_plan = p
reset("tight_budget")
call(f"/agent/plans/{old_plan['plan_id']}", expected=404)
call(f"/banking/receipts/{old_plan['steps'][0]['receipt_id']}", expected=404)
assert call("/policy/approvals")["items"] == []
assert call("/banking/accounts/acct-alice/balance")["constraints"]["spendable_cents"] == 40200
p, _ = finish(make())
assert balance() == 150000
cases.append({"case": "reset_revokes_history_and_402_becomes_500_after_cancel", "passed": True, "oracle": inspect()})

for point in ("before_post_reject", "after_mutation_rollback", "verify_timeout"):
    reset()
    before = balance()
    p = run(make("给张三转账500元"))
    step = p["steps"][0]
    call("/sandbox/faults", {"plan_id": p["plan_id"], "plan_version": p["version"], "step_id": step["step_id"], "point": point}, control=True)
    approve(p)
    p = run(p)
    if point == "verify_timeout":
        assert p["status"] == "pending_verification" and p["steps"][0]["result"] is None
        assert balance() == before - 50000
        for _ in range(3):
            assert run(p)["status"] == "pending_verification"
        p = call(f"/agent/plans/{p['plan_id']}/reconcile", {})
        assert p["status"] == "succeeded" and balance() == before - 50000
    else:
        assert p["status"] == "failed" and balance() == before
        assert p["steps"][0]["receipt_id"] is None
    cases.append({"case": point, "passed": True, "oracle": inspect()})

reset()
before = balance()
p = make()
cancel = next(s for s in p["steps"] if s["action"]["tool"] == "cancel_subscription")
call("/sandbox/faults", {"plan_id": p["plan_id"], "plan_version": p["version"], "step_id": cancel["step_id"], "point": "before_post_reject"}, control=True)
p = run(p)
approve(p)
p = run(p)
approve(p)
p = run(p)
assert p["status"] == "partially_completed" and balance() == before
assert next(s for s in p["steps"] if s["action"]["tool"] == "transfer")["approval_id"] is None
cases.append({"case": "cancel_failure_blocks_payment", "passed": True, "oracle": inspect()})
result = {"version": "0.4", "status": "passed", "transport": "real_http", "cases": cases, "scope": "template composition, reset, faults and independent oracle; see context-http-smoke for request conflicts"}
Path("reports").mkdir(exist_ok=True)
Path("reports/sandbox-http-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": result["status"], "cases": [c["case"] for c in cases]}))
