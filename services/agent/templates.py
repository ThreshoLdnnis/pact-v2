"""Server-owned business templates. Composition adds edges; it cannot remove gates.

Approval, constraint checks and receipt verification are executor invariants, not
optional model-authored nodes. A succeeded dependency means its receipt was verified.
"""
from contracts.models import CandidatePlan, CandidateStep
from pact.common import DomainError

CATALOG = [
    {"template_id": "bill_analysis", "version": 1, "tools": ["analyze_bills"], "gates": ["ownership", "ledger_read", "receipt_verification"]},
    {"template_id": "subscription_management", "version": 1, "tools": ["subscriptions", "cancel_subscription"], "gates": ["yellow_query_approval", "subscription_snapshot", "separate_cancel_approval", "atomic_cancellation", "receipt_verification"]},
    {"template_id": "smart_transfer", "version": 1, "tools": ["transfer", "schedule_transfer"], "gates": ["recipient_resolution", "live_constraints", "live_daily_limit", "bound_approval", "atomic_idempotent_posting", "receipt_verification"]},
]


def ancestors(steps, step_id):
    by_id = {s.step_id: s for s in steps}
    found, todo = set(), list(by_id[step_id].depends_on)
    while todo:
        key = todo.pop()
        if key not in found:
            found.add(key)
            todo.extend(by_id[key].depends_on)
    return found


def compose(command):
    # CandidatePlan validates unknown aliases, duplicate aliases and cycles.
    return CandidatePlan(title=command.title, minimum_balance_cents=command.minimum_balance_cents,
                         steps=[CandidateStep(step_id=i.instance_id, action=i.action, depends_on=i.depends_on) for i in command.instances])


def compile_candidate(candidate):
    """Expand mandatory query gates, retaining original exit IDs for outer edges."""
    result, metadata = [], {}
    used = {s.step_id for s in candidate.steps}
    for index, original in enumerate(candidate.steps):
        step = original.model_copy(deep=True)
        template = next((x for x in CATALOG if step.action.tool in x["tools"]), None)
        if template:
            metadata[step.step_id] = {"template_id": template["template_id"], "template_version": template["version"], "template_instance_id": step.step_id}
        if step.action.tool == "cancel_subscription":
            preceding = ancestors(candidate.steps, step.step_id)
            queries = [s for s in candidate.steps if s.step_id in preceding and s.action.tool == "subscriptions" and s.action.account_id == step.action.account_id]
            if not queries:
                query_id = f"query_{index}_{step.step_id[:60]}"
                if query_id in used:
                    raise DomainError("TEMPLATE_ID_COLLISION", "步骤名与内部模板节点冲突，请更名", 422)
                used.add(query_id)
                result.append(CandidateStep(step_id=query_id, depends_on=step.depends_on, action={"tool": "subscriptions", "account_id": step.action.account_id}))
                metadata[query_id] = dict(metadata[step.step_id])
                step.depends_on = [query_id]
        result.append(step)
    if len(result) > 12:
        raise DomainError("TEMPLATE_TOO_LARGE", "模板展开后最多12步，请缩小本次请求", 422)
    return CandidatePlan(title=candidate.title, minimum_balance_cents=candidate.minimum_balance_cents, steps=result), metadata
