import asyncio
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
from datetime import datetime, timedelta
import os
from pathlib import Path
import secrets
import threading
import time
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select, func
from contracts.models import AccountList, ApprovalDecision, BankingCommand, BankingExecutionResult, CandidatePlan, DemoLogin, ExecutionReceipt, HandoffInput, HandoffRelease, PlanInput, PolicyCommand, PolicyEvaluation, ReadResult, ReceiptVerification, RecipientSelection, TaskPlan
from contracts.models import CompositionInput, FaultInput, SandboxReset
from contracts.models import ClarificationDecision, ConflictDecision, ConversationInput, ConversationResponse, InterruptInput
from pact.audit import record, verify_chain
from pact.common import DomainError, digest, now, stamp, uid
from pact.storage import Account, ApprovalRow, Audit, ClarificationRow, Commitment, ConflictRow, ConversationRow, Database, Ledger, PlanRow, PreferenceRow, SessionRow, Subscription, TurnRow
from pact.settings import load_local_env
from services.agent import conversation, coordination, engine, model_adapter, planner, templates
from services.banking import service as bank
from services.sandbox import acceptance, controls


class BodyLimitMiddleware:
    def __init__(self, app, limit=32768):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        total = 0
        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.limit:
                raise HTTPException(413, "请求过大")
            return message
        await self.app(scope, limited_receive, send)


def create_app(database_url=None, scheduler=True):
    load_local_env()
    db = Database(database_url or os.getenv("PACT_DATABASE_URL", "sqlite:///data/pact.db"))
    with db.session(write=True) as session:
        bank.seed(session)

    async def scheduler_loop():
        def scan():
            with db.session(write=True) as session:
                users = session.scalars(select(Commitment.user_id).where(Commitment.kind == "scheduled_transfer", Commitment.status == "active").distinct()).all()
                for user in users:
                    try:
                        with session.begin_nested():
                            engine.prepare_due(session, user)
                    except DomainError as error:
                        record(session, user, "schedule.deferred", user, {"code": error.code})
        while True:
            await asyncio.sleep(15)
            await asyncio.to_thread(scan)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(scheduler_loop()) if scheduler else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        db.engine.dispose()

    app = FastAPI(title="PACT V2.0 Sandbox", version="0.4.0", lifespan=lifespan, description="仅合成数据的银行 Agent MVP。候选计划与银行工具 API 分离；模型不具备执行权限。")
    app.state.db = db
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
    bearer = HTTPBearer(auto_error=False)
    login_attempts, login_lock = {}, threading.Lock()
    admin_token = os.getenv("PACT_SANDBOX_ADMIN_TOKEN", "")
    controls_enabled = os.getenv("PACT_SANDBOX_CONTROLS") == "1" and len(admin_token) >= 24
    db.sandbox_controls_enabled = controls_enabled

    def sandbox_admin(x_sandbox_admin: str = Header(default="")):
        if not controls_enabled:
            raise DomainError("SANDBOX_CONTROLS_DISABLED", "测试控制入口未启用", 404)
        if not secrets.compare_digest(x_sandbox_admin.encode(), admin_token.encode()):
            raise DomainError("SANDBOX_ADMIN_REQUIRED", "需要独立的沙箱管理员令牌；演示会话不具备此权限", 403)
        return "sandbox_admin"

    @app.middleware("http")
    async def headers(request, call_next):
        request_id = uid("req")
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"error": {"code": "INVALID_LENGTH", "message": "无效请求长度"}}, status_code=400)
        if length > 32768:
            return JSONResponse({"error": {"code": "BODY_TOO_LARGE", "message": "请求过大"}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path in {"/docs", "/redoc"}:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"error": error.as_dict()}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"error": {"code": "INVALID_SCHEMA", "message": "请求未通过严格结构校验", "details": [{"loc": list(x["loc"]), "type": x["type"]} for x in error.errors()]}}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"error": {"code": "HTTP_ERROR", "message": str(error.detail)}}, status_code=error.status_code)

    def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials:
            raise DomainError("UNAUTHENTICATED", "请先登录演示身份", 401)
        with db.session() as session:
            row = session.get(SessionRow, digest(credentials.credentials))
            if not row or datetime.fromisoformat(row.expires_at) <= now():
                raise DomainError("UNAUTHENTICATED", "会话无效或已过期", 401)
            return row.user_id

    def mutate(user, operation):
        error = None
        with db.session(write=True) as session:
            try:
                with session.begin_nested():
                    result = operation(session)
            except DomainError as exc:
                error = exc
                record(session, user, "request.denied", user, {"code": exc.code})
        if error:
            raise error
        return result

    def candidate_for(user, message):
        with db.session() as session:
            account = session.scalars(select(Account).where(Account.user_id == user)).first()
            recipients = bank.read_tool(session, user, {"tool": "recipients", "account_id": account.id})["items"]
            # Only resolve a user-named cancellation target. Never send an unapproved
            # subscription inventory or amounts/status to the optional model.
            subs = [{"subscription_id": x.id, "name": x.name} for x in session.scalars(select(Subscription).where(Subscription.user_id == user, Subscription.account_id == account.id)) if "取消" in message and x.name in message]
        return planner.parse(message, account.id, recipients, subs)

    @app.get("/health", tags=["System"])
    def health():
        return {"status": "ok", "sandbox": True, "version": "0.4.0"}

    @app.get("/api/v1/meta", tags=["System"])
    def meta():
        return {"sandbox": True, "planner": model_adapter.provider() if model_adapter.provider() in {"rules", "ollama", "openai_compatible"} else "unconfigured", "currency": "CNY", "amount_unit": "integer_cents", "timezone": "Asia/Shanghai", "strong_verification": "simulation_only", "sandbox_controls_enabled": controls_enabled}

    @app.post("/api/v1/sandbox/reset", tags=["Sandbox controls"])
    def reset_sandbox(command: SandboxReset, admin=Depends(sandbox_admin)):
        result = mutate(admin, lambda s: controls.reset(s, command.scenario))
        with login_lock:
            login_attempts.clear()
        return result

    @app.post("/api/v1/sandbox/faults", tags=["Sandbox controls"])
    def inject_fault(command: FaultInput, admin=Depends(sandbox_admin)):
        return mutate(admin, lambda s: controls.arm(s, command))

    @app.post("/api/v1/sandbox/faults/clear", tags=["Sandbox controls"])
    def clear_faults(admin=Depends(sandbox_admin)):
        return mutate(admin, controls.clear)

    @app.get("/api/v1/sandbox/acceptance", tags=["Sandbox controls"])
    def independent_acceptance(admin=Depends(sandbox_admin)):
        return acceptance.inspect_database(db.engine.url.database)

    @app.post("/api/v1/auth/demo-session", tags=["Demo auth"])
    def login(command: DemoLogin, request: Request):
        client = request.client.host if request.client else "local"
        with login_lock:
            attempts = [t for t in login_attempts.get(client, []) if time.monotonic() - t < 60]
            if len(attempts) >= 5:
                raise DomainError("RATE_LIMIT", "演示登录尝试过多，请一分钟后重试", 429)
            if not secrets.compare_digest(command.pin, os.getenv("PACT_DEMO_PIN", "246810")):
                login_attempts[client] = attempts + [time.monotonic()]
                raise DomainError("INVALID_PIN", "演示 PIN 不正确", 401)
            login_attempts.pop(client, None)
        token = secrets.token_urlsafe(32)
        with db.session(write=True) as session:
            expiry = (now() + timedelta(hours=8)).isoformat()
            session.add(SessionRow(token_hash=digest(token), user_id=command.user_id, expires_at=expiry))
            record(session, command.user_id, "session.created", command.user_id, {"demo": True})
        return {"access_token": token, "token_type": "bearer", "user_id": command.user_id, "expires_at": expiry, "demo": True}

    @app.post("/api/v1/auth/logout", tags=["Demo auth"])
    def logout(user=Depends(principal), credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        def revoke(session):
            session.delete(session.get(SessionRow, digest(credentials.credentials)))
            record(session, user, "session.revoked", user)
            return {"logged_out": True}
        return mutate(user, revoke)

    @app.post("/api/v1/agent/plans", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def plan(command: PlanInput, user=Depends(principal)):
        candidate, source = candidate_for(user, command.message)
        return mutate(user, lambda s: engine.create_plan(s, user, candidate, source))

    @app.post("/api/v1/agent/messages", response_model=ConversationResponse, tags=["Conversation"])
    def message(command: ConversationInput, user=Depends(principal)):
        with db.session() as session:
            cached = conversation.prior(session, user, command)
            if cached:
                return cached
            if command.conversation_id:
                bank.owned(session, ConversationRow, command.conversation_id, user)
            if command.focus_plan_id:
                bank.owned(session, PlanRow, command.focus_plan_id, user)
        # Model calls, if configured, happen before the write lock. State is rechecked.
        prepared, preparation_error = None, None
        if not conversation.contextual(command.message):
            try:
                prepared = candidate_for(user, command.message)
            except DomainError as error:
                preparation_error = error
        return mutate(user, lambda s: conversation.handle(s, user, command, prepared, preparation_error))

    @app.get("/api/v1/agent/conversations/{conversation_id}", tags=["Conversation"])
    def conversation_detail(conversation_id: str, user=Depends(principal)):
        with db.session() as session:
            row = bank.owned(session, ConversationRow, conversation_id, user)
            turns = session.scalars(select(TurnRow).where(TurnRow.user_id == user, TurnRow.conversation_id == row.id).order_by(TurnRow.created_at).limit(100)).all()
            questions = session.scalars(select(ClarificationRow).where(ClarificationRow.user_id == user, ClarificationRow.conversation_id == row.id)).all()
            return {"conversation_id": row.id, "plan_ids": row.document.get("plan_ids", []), "turns": [t.response for t in turns], "clarifications": [q.document for q in questions]}

    @app.post("/api/v1/agent/clarifications/{clarification_id}/decision", response_model=ConversationResponse, tags=["Conversation"])
    def clarification_decision(clarification_id: str, command: ClarificationDecision, user=Depends(principal)):
        return mutate(user, lambda s: conversation.resolve(s, user, clarification_id, command))

    @app.get("/api/v1/agent/conflicts", tags=["Coordination"])
    def conflicts(user=Depends(principal)):
        with db.session() as session:
            items = [c.document for c in session.scalars(select(ConflictRow).where(ConflictRow.user_id == user))]
            return {"items": sorted(items, key=lambda x: x["created_at"], reverse=True)[:100]}

    @app.post("/api/v1/agent/conflicts/{conflict_id}/decision", tags=["Coordination"])
    def conflict_decision(conflict_id: str, command: ConflictDecision, user=Depends(principal)):
        return mutate(user, lambda s: coordination.decide(s, user, conflict_id, command))

    @app.get("/api/v1/agent/intent-preferences", tags=["Coordination"])
    def intent_preferences(user=Depends(principal)):
        with db.session() as session:
            return {"items": [{"preference_id": p.id, "account_id": p.account_id, "subscription_id": p.subscription_id, "created_at": p.created_at, "meaning": "用户明确的保留意图，不代表当前协议已开通"} for p in session.scalars(select(PreferenceRow).where(PreferenceRow.user_id == user, PreferenceRow.active.is_(True)))]}

    @app.post("/api/v1/agent/candidates", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def structured(candidate: CandidatePlan, user=Depends(principal)):
        return mutate(user, lambda s: engine.create_plan(s, user, candidate))

    @app.get("/api/v1/agent/templates", tags=["Agent Task Protocol"])
    def template_catalog(user=Depends(principal)):
        return {"items": templates.CATALOG, "composition": "outer dependencies; inner gates are server enforced"}

    @app.post("/api/v1/agent/compositions", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def composition(command: CompositionInput, user=Depends(principal)):
        candidate = templates.compose(command)
        return mutate(user, lambda s: engine.create_plan(s, user, candidate))

    @app.get("/api/v1/agent/plans", tags=["Agent Task Protocol"])
    def plans(user=Depends(principal)):
        with db.session() as session:
            return {"items": [p.document for p in session.scalars(select(PlanRow).where(PlanRow.user_id == user)).all()][::-1][:100]}

    @app.get("/api/v1/agent/plans/{plan_id}", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def plan_detail(plan_id: str, user=Depends(principal)):
        with db.session() as session:
            return engine.get_plan(session, user, plan_id)[1]

    @app.post("/api/v1/agent/plans/{plan_id}/run", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def run(plan_id: str, user=Depends(principal)):
        return mutate(user, lambda s: engine.run(s, user, plan_id))

    @app.post("/api/v1/agent/plans/{plan_id}/resume", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def resume(plan_id: str, user=Depends(principal)):
        return mutate(user, lambda s: engine.run(s, user, plan_id, resume=True))

    @app.post("/api/v1/agent/plans/{plan_id}/pause", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def pause(plan_id: str, user=Depends(principal)):
        return mutate(user, lambda s: engine.pause_plan(s, user, plan_id))

    @app.post("/api/v1/agent/plans/{plan_id}/interrupt", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def interrupt(plan_id: str, command: InterruptInput, user=Depends(principal)):
        return mutate(user, lambda s: engine.interrupt(s, user, plan_id, command))

    @app.post("/api/v1/agent/plans/{plan_id}/replan", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def replan(plan_id: str, command: PlanInput, user=Depends(principal)):
        candidate, source = candidate_for(user, command.message)
        return mutate(user, lambda s: engine.replan(s, user, plan_id, candidate, source))

    @app.post("/api/v1/agent/plans/{plan_id}/select-recipient", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def select_recipient(plan_id: str, command: RecipientSelection, user=Depends(principal)):
        return mutate(user, lambda s: engine.select_recipient(s, user, plan_id, command))

    @app.post("/api/v1/agent/plans/{plan_id}/reconcile", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def reconcile_plan(plan_id: str, user=Depends(principal)):
        return mutate(user, lambda s: engine.reconcile_plan(s, user, plan_id))

    @app.post("/api/v1/agent/plans/{plan_id}/handoff", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def handoff(plan_id: str, command: HandoffInput, user=Depends(principal)):
        return mutate(user, lambda s: engine.handoff_plan(s, user, plan_id, command))

    @app.post("/api/v1/agent/plans/{plan_id}/handoff/release", response_model=TaskPlan, tags=["Agent Task Protocol"])
    def release_handoff(plan_id: str, command: HandoffRelease, user=Depends(principal)):
        return mutate(user, lambda s: engine.release_handoff(s, user, plan_id, command))

    @app.get("/api/v1/banking/accounts", response_model=AccountList, tags=["Banking Tool API"])
    def accounts(user=Depends(principal)):
        with db.session() as session:
            return {"items": [bank.account_view(a) for a in session.scalars(select(Account).where(Account.user_id == user))]}

    @app.get("/api/v1/banking/accounts/{account_id}/{resource}", response_model=ReadResult, tags=["Banking Tool API"])
    def banking_read(account_id: str, resource: str, receipt_id: str | None = None, user=Depends(principal)):
        if resource not in {"balance", "transactions", "analyze_bills", "subscriptions", "commitments", "recipients"}:
            raise DomainError("NOT_FOUND", "读取工具不存在", 404)
        with db.session() as session:
            if resource == "subscriptions":
                return bank.subscription_snapshot(session, user, account_id, receipt_id)
            return bank.read_tool(session, user, {"tool": resource, "account_id": account_id})

    @app.post("/api/v1/banking/execute", response_model=BankingExecutionResult, tags=["Banking Tool API"])
    def execute(command: BankingCommand, user=Depends(principal)):
        return mutate(user, lambda s: engine.run(s, user, command.plan_id, command=command))

    @app.get("/api/v1/banking/receipts/{receipt_id}", response_model=ExecutionReceipt, tags=["Banking Tool API"])
    def receipt(receipt_id: str, user=Depends(principal)):
        with db.session() as session:
            return bank.owned(session, bank.ReceiptRow, receipt_id, user).document

    @app.get("/api/v1/banking/receipts/{receipt_id}/verify", response_model=ReceiptVerification, tags=["Banking Tool API"])
    def verify(receipt_id: str, user=Depends(principal)):
        with db.session() as session:
            return bank.verify_receipt(session, user, receipt_id)

    @app.get("/api/v1/banking/reconciliation", tags=["Banking Tool API"])
    def reconciliation(user=Depends(principal)):
        with db.session() as session:
            results = []
            for a in session.scalars(select(Account).where(Account.user_id == user)):
                ledger = session.scalar(select(func.coalesce(func.sum(Ledger.amount_cents), 0)).where(Ledger.account_id == a.id))
                results.append({"account_id": a.id, "balanced": a.opening_cents + ledger == a.balance_cents, "difference_cents": a.balance_cents - a.opening_cents - ledger})
            return {"accounts": results, "balanced": all(r["balanced"] for r in results)}

    @app.get("/api/v1/banking/commitment-graph", tags=["Banking Tool API"])
    def graph(user=Depends(principal)):
        with db.session() as session:
            accounts = session.scalars(select(Account).where(Account.user_id == user)).all()
            commitments = session.scalars(select(Commitment).where(Commitment.user_id == user, Commitment.status == "active", Commitment.kind != "subscription")).all()
            nodes = [{"id": a.id, "kind": "account", "label": a.name, "constraints": bank.snapshot(session, user, a.id)} for a in accounts] + [{"id": c.id, "kind": c.kind, "label": c.name, "amount_cents": c.amount_cents, "due_at": c.due_at} for c in commitments]
            edges = [{"from": c.account_id, "to": c.id, "kind": "reserves", "amount_cents": c.amount_cents} for c in commitments]
            for a in accounts:
                amount = session.scalar(select(func.coalesce(func.sum(Commitment.amount_cents), 0)).where(Commitment.account_id == a.id, Commitment.kind == "subscription", Commitment.status == "active"))
                if amount:
                    nodes.append({"id": a.id + "-subscription-reserve", "kind": "subscription_summary", "label": "订阅预留合计（详情需确认查询）", "amount_cents": amount})
                    edges.append({"from": a.id, "to": a.id + "-subscription-reserve", "kind": "reserves", "amount_cents": amount})
            return {"nodes": nodes, "edges": edges}

    @app.post("/api/v1/banking/schedules/prepare-due", tags=["Banking Tool API"])
    def due(user=Depends(principal)):
        return mutate(user, lambda s: engine.prepare_due(s, user))

    @app.post("/api/v1/policy/evaluate", response_model=PolicyEvaluation, tags=["Policy API"])
    def policy(command: PolicyCommand, user=Depends(principal)):
        with db.session() as session:
            _, plan = engine.get_plan(session, user, command.plan_id)
            step = next((s for s in plan.steps if s.step_id == command.step_id), None)
            if not step:
                raise DomainError("NOT_FOUND", "步骤不存在", 404)
            return engine.assess(session, user, plan, step)

    @app.get("/api/v1/policy/approvals", tags=["Policy API"])
    def approvals(user=Depends(principal)):
        with db.session() as session:
            return {"items": [a.document for a in session.scalars(select(ApprovalRow).where(ApprovalRow.user_id == user))][::-1][:100]}

    @app.post("/api/v1/policy/approvals/{approval_id}/challenge", tags=["Policy API"])
    def issue_challenge(approval_id: str, user=Depends(principal)):
        return mutate(user, lambda s: engine.challenge(s, user, approval_id))

    @app.post("/api/v1/policy/approvals/{approval_id}/decision", tags=["Policy API"])
    def decide(approval_id: str, command: ApprovalDecision, user=Depends(principal)):
        result = mutate(user, lambda s: engine.decide(s, user, approval_id, command))
        return JSONResponse(result, status_code=403) if "error" in result else result

    @app.get("/api/v1/audit", tags=["Audit"])
    def audit(user=Depends(principal)):
        with db.session() as session:
            rows = session.scalars(select(Audit).where(Audit.user_id == user).order_by(Audit.id.desc()).limit(100)).all()
            return {"chain_valid": verify_chain(session), "items": [{"id": r.id, "event": r.event, "entity_id": r.entity_id, "details": r.details, "created_at": r.created_at, "event_hash": r.event_hash} for r in rows]}

    dist = Path(__file__).resolve().parents[1] / "apps" / "workbench" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def frontend():
        if (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        return {"message": "PACT API ready. Build apps/workbench, or open /docs.", "docs": "/docs"}

    return app
