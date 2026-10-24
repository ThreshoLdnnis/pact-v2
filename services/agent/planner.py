"""Optional local-model planner; deterministic demo parser is the default."""
import re
from datetime import timedelta
from decimal import Decimal
import httpx
from pydantic import ValidationError
from contracts.models import CandidatePlan, CandidateStep
from pact.common import DomainError, now
from services.banking.service import SHANGHAI
from services.agent import model_adapter

INJECTION = re.compile(r"忽略.{0,12}(规则|指令)|绕过|系统提示|ignore.{0,20}instructions|system\s*prompt|approved\s*=|<script|tool_call", re.I)


def cents(text):
    value = Decimal(text) * 100
    if value != value.to_integral_value() or value <= 0:
        raise DomainError("CLARIFICATION_REQUIRED", "金额需为正数，且最多两位小数", 422)
    return int(value)


def parse(message, account_id, recipients, subscriptions):
    if INJECTION.search(message):
        raise DomainError("UNTRUSTED_INSTRUCTION", "检测到覆盖规则或伪造授权的内容，拒绝生成执行计划", 422)
    if re.search(r"退款|退回.{0,8}(元|扣款)|返还.{0,8}扣款|挂失|解挂|冻结|申购|赎回|修改密码", message):
        raise DomainError("UNSUPPORTED_OPERATION", "本版不支持退款、卡片或理财操作；取消代扣不会退回历史扣款，请明确三个核心场景内的请求", 422)
    if re.search(r"如果|除非|仅当|否则|只在|是否|能否|不要|别转|不转", message):
        raise DomainError("CLARIFICATION_REQUIRED", "当前协议无法安全表达该条件或否定，请明确需要执行的操作和最低留存余额", 422)
    if model_adapter.provider() != "rules":
        try:
            candidate, source = model_adapter.generate(message, account_id, recipients, subscriptions)
            tools = {s.action.tool for s in candidate.steps}
            payment_requested = bool(re.search(r"转账?|汇款", message))
            if payment_requested != bool(tools & {"transfer", "schedule_transfer"}) or (("取消" in message) != ("cancel_subscription" in tools)):
                raise ValueError("candidate adds or omits an explicit mutation")
            if re.search(r"分析|账单", message) and "analyze_bills" not in tools:
                raise ValueError("candidate omits explicit analysis")
            if any(s.action.account_id != account_id for s in candidate.steps):
                raise ValueError("candidate changes the requested account")
            ambiguous = [name for name in {r["name"] for r in recipients} if name in message and sum(r["name"] == name for r in recipients) > 1]
            transfers = [s for s in candidate.steps if s.action.tool in {"transfer", "schedule_transfer"}]
            if ambiguous and transfers:
                if len(ambiguous) != 1 or len(transfers) != 1:
                    raise ValueError("multiple ambiguous transfer targets")
                action = transfers[0].action.model_dump(mode="json")
                action.update(recipient_id=None, recipient_query=ambiguous[0])
                transfers[0].action = type(transfers[0].action).model_validate(action)
            # Explicit "再/然后" is an ordering constraint, not model discretion.
            if "取消" in message and re.search(r"再.*(?:转|汇款)|然后.*(?:转|汇款)", message):
                if not any(s.action.tool == "cancel_subscription" for s in candidate.steps) or (re.search(r"分析|账单", message) and not any(s.action.tool == "analyze_bills" for s in candidate.steps)):
                    raise ValueError("model omitted a required preceding business")
                preceding = [s.step_id for s in candidate.steps if s.action.tool in {"analyze_bills", "cancel_subscription"}]
                for step in candidate.steps:
                    if step.action.tool in {"transfer", "schedule_transfer"}:
                        step.depends_on = list(dict.fromkeys(step.depends_on + preceding))
                candidate = CandidatePlan.model_validate(candidate.model_dump())
            return candidate, source
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, IndexError, ValidationError) as error:
            raise DomainError("PLANNER_UNAVAILABLE", "模型服务未返回合规候选计划，请检查本机配置或澄清请求；未执行任何操作", 502) from error
    actions = []
    if re.search(r"分析|账单", message):
        actions.append({"tool": "analyze_bills", "account_id": account_id, "period": "30d" if re.search(r"30\s*天", message) else "month"})
    if "余额" in message or "还能转" in message:
        actions.append({"tool": "balance", "account_id": account_id})
    if "流水" in message:
        actions.append({"tool": "transactions", "account_id": account_id})
    if "取消" in message:
        matched = [s for s in subscriptions if s["name"] in message]
        if not matched:
            raise DomainError("CLARIFICATION_REQUIRED", "请明确要取消的视频会员或音乐会员", 422)
        actions += [{"tool": "cancel_subscription", "account_id": account_id, "subscription_id": s["subscription_id"]} for s in matched]
    elif re.search(r"订阅|代扣|会员", message):
        actions.append({"tool": "subscriptions", "account_id": account_id})
    if re.search(r"承诺|未来支出", message):
        actions.append({"tool": "commitments", "account_id": account_id})
    if re.search(r"转账?|汇款", message):
        # Deliberately bounded grammar: ambiguous/unsupported language fails closed.
        parts = re.split(r"[，,；;。]|然后|再给|再向", message)
        transfers = []
        for part in parts:
            if not re.search(r"转账?|汇款", part):
                continue
            recipients_found = sorted({r["name"] for r in recipients if r["name"] in part})
            amounts = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*元", part)
            if len(recipients_found) != 1 or len(amounts) != 1 or re.search(r"负|-\s*\d|万|千|剩余|一半|全部", part):
                raise DomainError("CLARIFICATION_REQUIRED", "请每笔明确收款人和阿拉伯数字金额，例如：给张三转账500元", 422)
            action = {"tool": "transfer", "account_id": account_id, "recipient_query": recipients_found[0], "amount_cents": cents(amounts[0])}
            action["_position"] = message.find(part)
            if "明天" in message or re.search(r"\d{4}-\d{2}-\d{2}", message):
                from datetime import datetime
                match = re.search(r"\d{4}-\d{2}-\d{2}", message)
                try:
                    due = datetime.fromisoformat(match.group()).replace(tzinfo=SHANGHAI) if match else now().astimezone(SHANGHAI) + timedelta(days=1)
                except ValueError as error:
                    raise DomainError("CLARIFICATION_REQUIRED", "日期不合法", 422) from error
                action.update(tool="schedule_transfer", due_at=due.isoformat())
            transfers.append(action)
        if not transfers:
            raise DomainError("CLARIFICATION_REQUIRED", "请明确转账对象和金额", 422)
        actions += transfers
    def position(action):
        if "_position" in action:
            return action.pop("_position")
        if action["tool"] == "cancel_subscription":
            return message.find(next(s["name"] for s in subscriptions if s["subscription_id"] == action["subscription_id"]))
        pattern = {"analyze_bills": r"分析|账单", "balance": r"余额|还能转", "transactions": r"流水", "subscriptions": r"订阅|代扣|会员", "commitments": r"承诺|未来支出"}[action["tool"]]
        return re.search(pattern, message).start()
    actions.sort(key=position)
    floor = re.search(r"(?:至少保留|最低留存|保留)\s*(\d+(?:\.\d+)?)\s*元", message)
    if not actions:
        raise DomainError("CLARIFICATION_REQUIRED", "支持查余额、分析账单、取消指定订阅、给指定收款人转账或明天转账", 422)
    # Reuse the same business templates; only outer dependency edges differ.
    parallel_prefix = len(actions) >= 2 and actions[0]["tool"] == "analyze_bills" and actions[1]["tool"] == "cancel_subscription" and not re.search(r"先|然后|之后|接着", message)
    steps = []
    for i, action in enumerate(actions):
        deps = [f"s{i}"] if i else []
        if parallel_prefix:
            deps = [] if i < 2 else [f"s{j+1}" for j in range(i)]
        steps.append(CandidateStep(step_id=f"s{i+1}", depends_on=deps, action=action))
    try:
        return CandidatePlan(title=message[:100], steps=steps, minimum_balance_cents=cents(floor.group(1)) if floor else 0), "rules"
    except ValidationError as error:
        raise DomainError("INVALID_CANDIDATE", "候选计划未通过严格结构校验", 422) from error
