"""Optional live candidate evaluation after LOCAL key configuration; no bank writes."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pact.common import DomainError
from pact.settings import load_local_env
from services.agent import model_adapter, planner

load_local_env()
if model_adapter.provider() == "rules":
    raise SystemExit("Configure a model provider in local .env first. No key is printed.")
recipients = [{"recipient_id": "rcp-zhang", "name": "张三", "account_hint": "synthetic-001"}]
subscriptions = [{"subscription_id": "sub-video", "name": "视频会员"}]
cases = [("查余额", {"balance"}), ("分析账单、取消视频会员、再给张三转账500元", {"analyze_bills", "cancel_subscription", "transfer"})]
passed = []
for message, required in cases:
    try:
        candidate, source = planner.parse(message, "acct-alice", recipients, subscriptions)
        if not required <= {s.action.tool for s in candidate.steps} or any(s.action.account_id != "acct-alice" for s in candidate.steps):
            raise ValueError("candidate does not match the test")
        transfers = [s for s in candidate.steps if s.action.tool == "transfer"]
        if transfers and any(s.action.amount_cents != 50000 or (s.action.recipient_id not in {None, "rcp-zhang"}) or (s.action.recipient_query not in {None, "张三"}) for s in transfers):
            raise ValueError("candidate payment mismatch")
        passed.append({"request": message, "passed": True})
    except (DomainError, ValueError):
        print(json.dumps({"passed": False, "case": message, "message": "Model configuration, response or candidate evaluation failed; no banking API was called."}, ensure_ascii=False))
        raise SystemExit(1)
print(json.dumps({"passed": True, "provider": source, "cases": passed, "scope": "two live candidate checks only; not a broad NLU benchmark; no banking execution"}, ensure_ascii=False, indent=2))
