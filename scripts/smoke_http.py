"""Real HTTP acceptance flow against a running sandbox."""
import json
from pathlib import Path
import sys
import urllib.request

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
token = None


def call(path, payload=None):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


assert call("/health")["sandbox"]
token = call("/api/v1/auth/demo-session", {"user_id": "alice", "pin": "246810"})["access_token"]
before = call("/api/v1/banking/accounts")["items"][0]["balance_cents"]
plan = call("/api/v1/agent/plans", {"message": "分析本月账单，取消视频会员，再给张三转账500元，至少保留1000元"})
for _ in range(10):
    plan = call(f"/api/v1/agent/plans/{plan['plan_id']}/run", {})
    if plan["status"] == "succeeded":
        break
    assert plan["status"] == "waiting_approval", plan
    step = next(s for s in plan["steps"] if s["status"] == "waiting_approval")
    code = None
    if step["risk_level"] == "red":
        code = call(f"/api/v1/policy/approvals/{step['approval_id']}/challenge", {})["demo_code"]
    call(f"/api/v1/policy/approvals/{step['approval_id']}/decision", {"decision": "approve", "challenge_code": code})
assert plan["status"] == "succeeded"
assert call("/api/v1/banking/accounts")["items"][0]["balance_cents"] == before - 50000
assert all(call(f"/api/v1/banking/receipts/{s['receipt_id']}/verify")["verified"] for s in plan["steps"])
assert call("/api/v1/banking/reconciliation")["balanced"]
result = {"workflow": "(analysis || subscription query -> cancellation) -> transfer", "status": "passed", "plan_id": plan["plan_id"], "receipt_ids": [s["receipt_id"] for s in plan["steps"]], "balance_delta_cents": -50000, "verified": True}
Path("reports").mkdir(exist_ok=True)
Path("reports/http-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
