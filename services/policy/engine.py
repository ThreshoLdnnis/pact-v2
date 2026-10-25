"""Pure policy/constraint decisions. No model output can override these rules."""
from pact.common import DomainError

DAILY_YELLOW_LIMIT_CENTS = 100_000
READ_TOOLS = {"balance", "transactions", "analyze_bills", "subscriptions", "commitments", "recipients"}


def evaluate(tool, amount_cents=0, spent_today_cents=0):
    if tool == "subscriptions":
        return {"level": "yellow", "reason": "订阅协议查询需要用户明确确认；仅授权本账户本次查询"}
    if tool in READ_TOOLS:
        return {"level": "green", "reason": "只读操作，可自动执行"}
    if tool == "cancel_subscription":
        return {"level": "yellow", "reason": "取消订阅需要用户明确确认"}
    if tool in {"transfer", "schedule_transfer"}:
        total = spent_today_cents + amount_cents
        if total <= DAILY_YELLOW_LIMIT_CENTS:
            return {"level": "yellow", "reason": "本次计入后，用户上海自然日转出累计不超过1000元，需确认"}
        return {"level": "red", "reason": "本次计入后，用户上海自然日转出累计超过1000元，需模拟强验证"}
    raise DomainError("TOOL_NOT_ALLOWED", "未在白名单中的工具，拒绝执行", 422)


def constraint_snapshot(balance, floor, reserved, amount=0):
    available = balance - floor - reserved
    return {"balance_cents": balance, "minimum_balance_cents": floor, "committed_cents": reserved, "spendable_cents": max(0, available), "requested_cents": amount, "remaining_after_cents": balance - amount, "allowed": amount <= available}


def enforce_constraints(snapshot):
    if not snapshot["allowed"]:
        raise DomainError("FINANCIAL_CONSTRAINT", "执行会侵占最低留存余额或已有资金承诺，请减少金额或重规划", details=snapshot)
