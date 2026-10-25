"""Real HTTP contextual/conflict acceptance. Resets a DISPOSABLE sandbox only."""
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
admin, token, cases = os.environ["PACT_SANDBOX_ADMIN_TOKEN"], "", []


def call(path, body=None, control=False, expected=200):
    headers = {"Content-Type": "application/json", **({"X-Sandbox-Admin": admin} if control else {"Authorization": "Bearer " + token})}
    try:
        with urlopen(Request(base + "/api/v1" + path, data=json.dumps(body).encode() if body is not None else None, headers=headers), timeout=20) as response:
            assert response.status == expected
            return json.load(response)
    except HTTPError as error:
        assert error.code == expected, error.read().decode()
        return json.load(error)


def reset(scenario="baseline"):
    global token
    call("/sandbox/reset", {"confirmation": "RESET_SYNTHETIC_DATA", "scenario": scenario}, True)
    token = call("/auth/demo-session", {"user_id": "alice", "pin": "246810"})["access_token"]


def chat(message, conversation_id=None, **kwargs):
    return call("/agent/messages", {"request_id": "http_" + uuid.uuid4().hex, "message": message, "conversation_id": conversation_id, **kwargs})


def read(p):
    return call(f"/agent/plans/{p['plan_id']}")


def run(p):
    return call(f"/agent/plans/{p['plan_id']}/run", {})


def approve(p):
    step = next(s for s in p["steps"] if s["status"] == "waiting_approval")
    aid = step["approval_id"]
    code = call(f"/policy/approvals/{aid}/challenge", {})["demo_code"] if step["risk_level"] == "red" else None
    call(f"/policy/approvals/{aid}/decision", {"decision": "approve", "challenge_code": code})


def finish(p):
    for _ in range(10):
        p = run(p)
        if p["status"] == "succeeded":
            return p
        assert p["status"] == "waiting_approval", p
        approve(p)
    raise AssertionError("workflow did not finish")


def balance():
    return call("/banking/accounts")["items"][0]["balance_cents"]


def passed(name):
    report = call("/sandbox/acceptance", control=True)
    assert report["passed"], report
    cases.append({"case": name, "passed": True, "oracle": report})


reset()
body = {"request_id": "http-retry", "message": "给张三转账500元"}
a = call("/agent/messages", body)
assert call("/agent/messages", body) == a
b = chat("那个改成300", a["conversation_id"])
assert b["plan"]["plan_id"] == a["plan"]["plan_id"] and b["plan"]["version"] == 2
assert b["plan"]["steps"][0]["action"]["amount_cents"] == 30000 and balance() == 1553400
call(f"/policy/approvals/{a['plan']['steps'][0]['approval_id']}/decision", {"decision": "approve"}, expected=409)
passed("same_request_reused_edit_invalidates_old_approval")

reset()
a = chat("给张三转账500元，至少保留2000元")
b = chat("那个改成300", a["conversation_id"])
assert b["outcome"] == "clarification" and len(b["clarification"]["options"]) == 2
q = b["clarification"]
decision = {"option_id": q["options"][0]["option_id"]}
c = call(f"/agent/clarifications/{q['clarification_id']}/decision", decision)
assert c["outcome"] == "amended"
assert call(f"/agent/clarifications/{q['clarification_id']}/decision", decision) == c
passed("ambiguous_amount_or_floor_requires_version_bound_choice")

reset()
assert chat("那个改成300，然后再给李四100元")["outcome"] == "clarification"
assert balance() == 1553400
passed("unsupported_compound_does_not_execute_partial_intent")

reset()
a = chat("分析账单、取消视频会员、再给张三转账500元")
b = chat("算了，留着吧", a["conversation_id"])
assert b["plan"]["status"] == "paused"
assert next(s for s in b["plan"]["steps"] if s["action"]["tool"] == "cancel_subscription")["status"] == "cancelled"
assert next(s for s in b["plan"]["steps"] if s["action"]["tool"] == "transfer")["status"] == "paused"
assert balance() == 1553400
passed("keep_membership_stops_cancel_and_blocks_dependent_payment")

reset("tight_budget")
a = chat("给张三转账300元")["plan"]
approve(a)
b = chat("给李四转账300元")["plan"]
assert b["status"] == read(a)["status"] == "waiting_conflict"
assert balance() == 200000
cid = b["conflict_ids"][0]
call(f"/agent/conflicts/{cid}/decision", {"choice": "execute_plan", "selected_plan_id": b["plan_id"]})
assert read(a)["status"] == "paused" and balance() == 200000
finish(read(b))
assert balance() == 170000
passed("funds_conflict_user_can_choose_later_request_without_auto_payment")

reset()
chat("保留视频会员")
p = run(call("/agent/plans", {"message": "取消视频会员"}))
assert p["status"] == "waiting_conflict"
call(f"/agent/conflicts/{p['conflict_ids'][0]}/decision", {"choice": "keep_subscription"})
assert read(p)["status"] == "paused"
passed("keep_and_cancel_conflict_applies_to_legacy_entrypoint")

reset()
p = finish(chat("给张三转账100元")["plan"])
before = balance()
stopped = call(f"/agent/plans/{p['plan_id']}/interrupt", {"plan_version": p["version"], "reason": "停止并核对结果"})
assert stopped["interruption"]["retained_receipt_ids"] and balance() == before
assert stopped["steps"][0]["result"]["verified"] is True
passed("interruption_retains_verified_payment_without_fake_refund")

reset()
a = chat("帮我省点钱")
assert [s["action"]["tool"] for s in a["plan"]["steps"]] == ["analyze_bills"] and a["recommendations"]
assert balance() == 1553400 and call("/policy/approvals")["items"] == []
passed("savings_is_analysis_and_recommendations_only")

reset()
p = finish(chat("明天给张三转账200元")["plan"])
stopped = call(f"/agent/plans/{p['plan_id']}/interrupt", {"plan_version": p["version"], "reason": "撤销尚未付款的定时安排"})
assert any(x.get("withdrawn") for x in stopped["interruption"]["compensation_items"])
assert balance() == 1553400
passed("withdraw_unpaid_schedule_keeps_registration_receipt")

report = {"version": "0.4", "status": "passed", "transport": "real_http", "cases": cases}
Path("reports").mkdir(exist_ok=True)
Path("reports/context-http-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
print(json.dumps({"status": "passed", "cases": [c["case"] for c in cases]}))
