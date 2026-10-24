"""Versioned, closed-world protocol. Models may only author CandidatePlan."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Money = Annotated[StrictInt, Field(ge=1, le=100_000_000)]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
State = Literal["planned", "waiting_approval", "waiting_clarification", "waiting_conflict", "executing", "pending_verification", "partially_completed", "handed_off", "succeeded", "failed", "paused", "cancelled"]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountAction(Closed):
    account_id: Identifier


class ReadAction(AccountAction):
    tool: Literal["balance", "transactions", "analyze_bills", "subscriptions", "commitments", "recipients"]
    period: Literal["month", "30d"] = "month"


class RecipientTarget(AccountAction):
    recipient_id: Identifier | None = None
    recipient_query: Annotated[str, Field(min_length=1, max_length=80)] | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def one_target(self):
        if (self.recipient_id is None) == (self.recipient_query is None):
            raise ValueError("exactly one recipient_id or recipient_query is required")
        return self


class TransferAction(RecipientTarget):
    tool: Literal["transfer"]
    amount_cents: Money
    commitment_id: Identifier | None = None


class ScheduleAction(RecipientTarget):
    tool: Literal["schedule_transfer"]
    amount_cents: Money
    due_at: datetime

    @model_validator(mode="after")
    def aware(self):
        if self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return self


class CancelAction(AccountAction):
    tool: Literal["cancel_subscription"]
    subscription_id: Identifier


Action = Annotated[ReadAction | TransferAction | ScheduleAction | CancelAction, Field(discriminator="tool")]


class CandidateStep(Closed):
    step_id: Identifier
    depends_on: list[Identifier] = Field(default_factory=list, max_length=12)
    action: Action


class CandidatePlan(Closed):
    title: str = Field(min_length=1, max_length=120)
    minimum_balance_cents: Annotated[StrictInt, Field(ge=0, le=100_000_000)] = 0
    steps: list[CandidateStep] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def dag(self):
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate step_id")
        done = set()
        for _ in self.steps:
            ready = [s for s in self.steps if s.step_id not in done and set(s.depends_on) <= done]
            if not ready:
                break
            done.update(s.step_id for s in ready)
        if done != set(ids):
            raise ValueError("DAG has a cycle or unknown dependency")
        return self


class RecipientOption(Closed):
    recipient_id: Identifier
    name: str
    account_hint: str


class RecipientClarification(Closed):
    clarification_id: str
    query: str
    options: list[RecipientOption]
    expires_at: str


class HandoffRecord(Closed):
    handoff_id: str
    requested_by: str
    reason: str
    created_at: str
    prior_status: State
    status: Literal["active", "released"] = "active"
    released_at: str | None = None
    resolution_note: str | None = None


class PlanProgress(Closed):
    completed: int = 0
    failed: int = 0
    pending_verification: int = 0
    remaining: int = 0
    cancelled: int = 0


class InterruptionReview(Closed):
    reason: str
    created_at: str
    cancelled_step_ids: list[str] = Field(default_factory=list)
    blocked_step_ids: list[str] = Field(default_factory=list)
    retained_receipt_ids: list[str] = Field(default_factory=list)
    unknown_receipt_ids: list[str] = Field(default_factory=list)
    compensation_items: list[dict] = Field(default_factory=list)
    message: str


class TaskStep(CandidateStep):
    template_id: str | None = None
    template_instance_id: str | None = None
    template_version: int | None = None
    status: State = "planned"
    risk_level: Literal["green", "yellow", "red"] | None = None
    approval_id: str | None = None
    receipt_id: str | None = None
    result: dict | None = None
    error: dict | None = None
    clarification: RecipientClarification | None = None


class TaskPlan(Closed):
    schema_version: Literal["0.1", "0.2", "0.3", "0.4"] = "0.4"
    plan_id: str
    version: int = 1
    title: str
    planner: Literal["rules", "ollama", "openai_compatible", "structured", "schedule"]
    minimum_balance_cents: int = 0
    status: State = "planned"
    steps: list[TaskStep]
    created_at: str
    progress: PlanProgress = Field(default_factory=PlanProgress)
    handoff: HandoffRecord | None = None
    ready_step_ids: list[str] = Field(default_factory=list)
    activated_until: str | None = None
    conflict_ids: list[str] = Field(default_factory=list)
    interruption: InterruptionReview | None = None


class InterruptInput(Closed):
    plan_version: Annotated[StrictInt, Field(ge=1)]
    reason: str = Field(min_length=1, max_length=500)
    step_id: Identifier | None = None


class ConflictDecision(Closed):
    choice: Literal["execute_plan", "keep_subscription", "pause_all"]
    selected_plan_id: Identifier | None = None

    @model_validator(mode="after")
    def selection(self):
        if (self.choice == "execute_plan") != (self.selected_plan_id is not None):
            raise ValueError("execute_plan requires exactly one selected_plan_id")
        return self


class ConversationInput(Closed):
    request_id: Identifier
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: Identifier | None = None
    focus_plan_id: Identifier | None = None
    focus_plan_version: Annotated[StrictInt, Field(ge=1)] | None = None
    focus_step_id: Identifier | None = None
    focus_field: Literal["amount_cents", "minimum_balance_cents"] | None = None


class ClarificationDecision(Closed):
    option_id: Identifier


class ConversationResponse(Closed):
    conversation_id: str
    turn_id: str
    outcome: Literal["planned", "amended", "clarification", "interrupted", "reused", "informational"]
    message: str
    plan: TaskPlan | None = None
    clarification: dict | None = None
    recommendations: list[str] = Field(default_factory=list)


class TemplateInstance(Closed):
    instance_id: Identifier
    template_id: Literal["bill_analysis", "subscription_management", "smart_transfer"]
    action: Action
    depends_on: list[Identifier] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def compatible_action(self):
        allowed = {"bill_analysis": {"analyze_bills"}, "subscription_management": {"subscriptions", "cancel_subscription"}, "smart_transfer": {"transfer", "schedule_transfer"}}
        if self.action.tool not in allowed[self.template_id]:
            raise ValueError("action does not belong to the selected template")
        return self


class CompositionInput(Closed):
    title: str = Field(min_length=1, max_length=120)
    minimum_balance_cents: Annotated[StrictInt, Field(ge=0, le=100_000_000)] = 0
    instances: list[TemplateInstance] = Field(min_length=1, max_length=6)


class SandboxReset(Closed):
    confirmation: Literal["RESET_SYNTHETIC_DATA"]
    scenario: Literal["baseline", "tight_budget"] = "baseline"


class FaultInput(Closed):
    plan_id: Identifier
    plan_version: Annotated[StrictInt, Field(ge=1)]
    step_id: Identifier
    point: Literal["before_post_reject", "after_mutation_rollback", "verify_timeout"]


class ApprovalRequest(Closed):
    approval_id: str
    plan_id: str
    plan_version: int
    step_id: str
    action_hash: str
    level: Literal["yellow", "red"]
    status: Literal["pending", "approved", "rejected", "consumed", "expired"]
    expires_at: str
    reason: str
    action: dict
    scope_hash: str | None = None


class ExecutionReceipt(Closed):
    receipt_id: str
    plan_id: str
    plan_version: int
    step_id: str
    action_hash: str
    operation: str
    status: Literal["succeeded", "scheduled"]
    transaction_id: str | None = None
    data: dict
    created_at: str


class PlanInput(Closed):
    message: str = Field(min_length=1, max_length=2000)


class DemoLogin(Closed):
    user_id: Literal["alice", "bob"] = "alice"
    pin: str = Field(min_length=1, max_length=64)


class ApprovalDecision(Closed):
    decision: Literal["approve", "reject"]
    challenge_code: str | None = Field(default=None, max_length=16)


class BankingCommand(Closed):
    plan_id: str
    plan_version: StrictInt
    step_id: str
    idempotency_key: str = Field(min_length=1, max_length=160)
    action: Action


class PolicyCommand(Closed):
    plan_id: str
    step_id: str


class RecipientSelection(Closed):
    plan_version: StrictInt
    step_id: Identifier
    clarification_id: str
    recipient_id: Identifier


class HandoffInput(Closed):
    plan_version: StrictInt
    reason: str = Field(min_length=1, max_length=500)


class HandoffRelease(Closed):
    plan_version: StrictInt
    note: str = Field(min_length=1, max_length=500)


class ConstraintSnapshot(Closed):
    balance_cents: int
    minimum_balance_cents: int
    committed_cents: int
    spendable_cents: int
    requested_cents: int
    remaining_after_cents: int
    allowed: bool


class PolicyEvaluation(Closed):
    level: Literal["green", "yellow", "red"]
    reason: str
    spent_today_cents: int
    constraints: ConstraintSnapshot | None = None


class ReceiptVerification(Closed):
    verified: bool
    receipt_id: str
    source: Literal["banking_backend"]
    checked_at: str
    receipt: ExecutionReceipt


class BankingExecutionResult(Closed):
    receipt: ExecutionReceipt | None
    plan: TaskPlan


class AccountView(Closed):
    account_id: str
    name: str
    currency: Literal["CNY"]
    balance_cents: int
    minimum_balance_cents: int


class BalanceView(AccountView):
    constraints: ConstraintSnapshot


class AccountList(Closed):
    items: list[AccountView]


class TransactionView(Closed):
    transaction_id: str
    amount_cents: int
    category: str
    memo: str
    created_at: str


class TransactionList(Closed):
    items: list[TransactionView]


class RecipientView(Closed):
    recipient_id: str
    name: str
    account_hint: str


class RecipientList(Closed):
    items: list[RecipientView]


class SubscriptionView(Closed):
    subscription_id: str
    name: str
    amount_cents: int
    active: bool


class SubscriptionList(Closed):
    items: list[SubscriptionView]
    source_receipt_id: str | None = None
    snapshot_at: str | None = None


class CommitmentView(Closed):
    commitment_id: str
    name: str
    account_id: str
    amount_cents: int
    due_at: str
    status: Literal["active", "cancelled", "fulfilled"]
    kind: str
    execution_plan_id: str | None


class CommitmentList(Closed):
    items: list[CommitmentView]
    constraints: ConstraintSnapshot
    subscription_reserved_cents: int = 0


class BillsView(Closed):
    period_start: str
    period_end: str
    timezone: Literal["Asia/Shanghai"]
    income_cents: int
    expense_cents: int
    transfer_out_cents: int
    categories: dict[str, int]
    transaction_count: int
    source: Literal["banking_ledger"]
    transaction_ids: list[str] = Field(default_factory=list)
    anomalies: list[dict[str, str]] = Field(default_factory=list)


ReadResult = BalanceView | TransactionList | RecipientList | SubscriptionList | CommitmentList | BillsView
