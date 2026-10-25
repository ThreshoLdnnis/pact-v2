"""SQLite MVP persistence. Every mutation acquires a database-wide write lock first."""
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from pact.common import stamp


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    opening_cents: Mapped[int] = mapped_column(Integer)
    balance_cents: Mapped[int] = mapped_column(Integer)
    floor_cents: Mapped[int] = mapped_column(Integer, default=100000)
    __table_args__ = (CheckConstraint("balance_cents >= 0"),)


class Recipient(Base):
    __tablename__ = "recipients"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))


class Ledger(Base):
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String)
    memo: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=stamp)
    __table_args__ = (UniqueConstraint("transaction_id", "account_id"),)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    name: Mapped[str] = mapped_column(String)
    amount_cents: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Commitment(Base):
    __tablename__ = "commitments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    name: Mapped[str] = mapped_column(String)
    amount_cents: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")
    kind: Mapped[str] = mapped_column(String, default="bill")
    subscription_id: Mapped[str | None] = mapped_column(ForeignKey("subscriptions.id"), nullable=True)
    recipient_id: Mapped[str | None] = mapped_column(ForeignKey("recipients.id"), nullable=True)
    execution_plan_id: Mapped[str | None] = mapped_column(String, nullable=True)
    minimum_balance_cents: Mapped[int] = mapped_column(Integer, default=0)


class PlanRow(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    document: Mapped[dict] = mapped_column(JSON)
    history: Mapped[list] = mapped_column(JSON, default=list)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    document: Mapped[dict] = mapped_column(JSON)
    challenge_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    challenge_expires: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class ReceiptRow(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"))
    plan_version: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSON)
    document_hash: Mapped[str] = mapped_column(String)
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"), UniqueConstraint("plan_id", "plan_version", "step_id"))


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String)
    expires_at: Mapped[str] = mapped_column(String)


class Guard(Base):
    __tablename__ = "guards"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[str | None] = mapped_column(String, nullable=True)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    event: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=stamp)
    previous_hash: Mapped[str] = mapped_column(String)
    event_hash: Mapped[str] = mapped_column(String)


class FaultRow(Base):
    __tablename__ = "sandbox_faults"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String)
    plan_id: Mapped[str] = mapped_column(String)
    plan_version: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String)
    point: Mapped[str] = mapped_column(String)
    remaining: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[str] = mapped_column(String)


class ConflictRow(Base):
    __tablename__ = "task_conflicts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    document: Mapped[dict] = mapped_column(JSON)


class PreferenceRow(Base):
    __tablename__ = "intent_preferences"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    subscription_id: Mapped[str] = mapped_column(ForeignKey("subscriptions.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String, default=stamp)
    __table_args__ = (UniqueConstraint("user_id", "subscription_id"),)


class ConversationRow(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    document: Mapped[dict] = mapped_column(JSON, default=dict)


class TurnRow(Base):
    __tablename__ = "conversation_turns"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    request_id: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str] = mapped_column(String)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=stamp)
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)


class ClarificationRow(Base):
    __tablename__ = "conversation_clarifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    document: Mapped[dict] = mapped_column(JSON)


class Database:
    def __init__(self, url):
        if not url.startswith("sqlite:///") or url.endswith(":memory:"):
            raise ValueError("MVP requires a file-backed SQLite database")
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA journal_mode=WAL")

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self, write=False):
        with Session(self.engine, expire_on_commit=False, info={"sandbox_controls_enabled": getattr(self, "sandbox_controls_enabled", False)}) as session:
            try:
                session.execute(text("BEGIN IMMEDIATE" if write else "BEGIN"))
                yield session
                if write:
                    session.commit()
            except BaseException:
                session.rollback()
                raise
