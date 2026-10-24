import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type {
  ApprovalRequest,
  ExecutionReceipt,
  TaskPlan,
  TaskStep,
} from "./protocol";
import "./style.css";

type Constraints = {
  balance_cents: number;
  minimum_balance_cents: number;
  committed_cents: number;
  spendable_cents: number;
};
type Verified = {
  verified: boolean;
  receipt: ExecutionReceipt;
  checked_at: string;
};
type Account = { account_id: string; name: string; balance_cents: number };
type Graph = {
  nodes: {
    id: string;
    kind: string;
    label: string;
    amount_cents?: number;
    due_at?: string;
    constraints?: Constraints;
  }[];
  edges: { from: string; to: string; amount_cents: number }[];
};
type AuditView = {
  chain_valid: boolean;
  items: { id: number; event: string; entity_id: string; created_at: string }[];
};
type Chat = { role: "user" | "agent"; text: string };
const money = (n = 0) =>
  new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(
    n / 100,
  );
const toolNames: Record<string, string> = {
  balance: "查询余额",
  transactions: "查询流水",
  analyze_bills: "分析账单",
  subscriptions: "查看订阅",
  commitments: "查看资金承诺",
  recipients: "查看收款人",
  transfer: "执行转账",
  schedule_transfer: "登记定时转账",
  cancel_subscription: "取消订阅",
};
const stateNames: Record<string, string> = {
  planned: "待执行",
  waiting_approval: "等待授权",
  executing: "执行中",
  succeeded: "已核验完成",
  failed: "执行失败",
  paused: "已暂停",
  waiting_clarification: "等待收款人选择",
  pending_verification: "结果待核验",
  partially_completed: "部分完成 · 已停止",
  handed_off: "人工接管中",
};
const demoPrompts = [
  "分析本月账单，取消视频会员，再给张三转账500元，至少保留1000元",
  "给张三转账1001元",
  "明天给李四转账200元",
  "查看未来支出和余额",
];

function App() {
  const [token, setToken] = useState(
    sessionStorage.getItem("pact-token") || "",
  );
  const [user, setUser] = useState(
    sessionStorage.getItem("pact-user") || "alice",
  );
  const [pin, setPin] = useState("246810");
  const [tab, setTab] = useState("work");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [account, setAccount] = useState<Account>();
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [plans, setPlans] = useState<TaskPlan[]>([]);
  const [plan, setPlan] = useState<TaskPlan>();
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [audit, setAudit] = useState<AuditView>({
    chain_valid: true,
    items: [],
  });
  const [message, setMessage] = useState("");
  const [replanMessage, setReplanMessage] = useState("给张三转账50元");
  const [chats, setChats] = useState<Chat[]>([]);
  const [code, setCode] = useState("");
  const [demoCode, setDemoCode] = useState("");
  const [detail, setDetail] = useState<Verified>();
  const [planner, setPlanner] = useState("rules");
  const [recipients, setRecipients] = useState<{recipient_id: string; name: string; account_hint: string}[]>([]);
  const [handoffNote, setHandoffNote] = useState("请人工检查当前计划，保留真实交易记录");
  const [uncertainPlan, setUncertainPlan] = useState("");

  async function api<T>(
    path: string,
    method = "GET",
    body?: unknown,
    override?: string,
  ): Promise<T> {
    let response: Response;
    try {
    response = await fetch("/api/v1" + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(override || token
          ? { Authorization: "Bearer " + (override || token) }
          : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    } catch (cause) {
      const match = path.match(/^\/agent\/plans\/([^/]+)\/(run|resume)$/);
      if (method === "POST" && match) setUncertainPlan(match[1]);
      throw cause;
    }
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401 && path !== "/auth/demo-session") {
        setToken("");
        sessionStorage.removeItem("pact-token");
      }
      throw new Error(data.error?.message || "请求未成功，请稍后重试");
    }
    return data as T;
  }

  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作未完成");
    } finally {
      setBusy(false);
    }
  }

  async function refresh(auth = token) {
    const [a, g, p, ap, au, meta, rp] = await Promise.all([
      api<{ items: Account[] }>("/banking/accounts", "GET", undefined, auth),
      api<Graph>("/banking/commitment-graph", "GET", undefined, auth),
      api<{ items: TaskPlan[] }>("/agent/plans", "GET", undefined, auth),
      api<{ items: ApprovalRequest[] }>(
        "/policy/approvals",
        "GET",
        undefined,
        auth,
      ),
      api<AuditView>("/audit", "GET", undefined, auth),
      api<{ planner: string }>("/meta", "GET", undefined, auth),
      api<{items: {recipient_id: string; name: string; account_hint: string}[]}>(`/banking/accounts/acct-${user}/recipients`, "GET", undefined, auth),
    ]);
    setAccount(a.items[0]);
    setGraph(g);
    setPlans(p.items);
    setApprovals(ap.items);
    setAudit(au);
    setPlanner(meta.planner);
    setRecipients(rp.items);
  }

  useEffect(() => {
    if (token) void perform(() => refresh(token));
  }, [token]);
  useEffect(() => {
    setCode("");
    setDemoCode("");
  }, [plan?.steps.find((s) => s.status === "waiting_approval")?.approval_id]);
  useEffect(() => {
    if (!detail) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetail(undefined);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [detail]);

  function showPlan(p: TaskPlan) {
    setPlan(p);
    const state = p.status || "planned";
    let text =
      state === "succeeded"
        ? `计划已完成，${p.steps.length} 项后端回执已核验。`
        : state === "waiting_approval"
          ? "计划已检查，等待你授权当前步骤。模型不能替你确认或决定风险等级。"
          : state === "pending_verification"
            ? "原交易结果待核验。不会再次付款；请查询原回执或交人工处理。"
          : state === "waiting_clarification"
            ? "同名或未找到的收款人需要你澄清，尚未产生交易授权。"
          : state === "partially_completed"
            ? "计划部分完成后已停止。已发生的交易保持有效，后续步骤尚未完成。"
          : state === "handed_off"
            ? "已转入人工接管，旧审批失效，自动执行已冻结。"
          : state === "failed"
            ? "执行已停止。已完成步骤会保留，请查看失败原因后重规划。"
            : `计划${stateNames[state]}。`;
    if (
      state === "succeeded" &&
      p.steps.some(
        (s) =>
          (s.result as unknown as Verified)?.receipt?.status === "scheduled",
      )
    )
      text += " 定时转账仅登记了承诺，尚未扣款，到期需要重新授权。";
    setChats((c) => [...c, { role: "agent", text }]);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!message.trim()) return;
    await perform(async () => {
      const text = message;
      setChats((c) => [...c, { role: "user", text }]);
      setMessage("");
      const p = await api<TaskPlan>("/agent/plans", "POST", { message: text });
      setPlan(p);
      showPlan(await api<TaskPlan>(`/agent/plans/${p.plan_id}/run`, "POST"));
      await refresh();
    });
  }

  const waitingStep = plan?.steps.find((s) => s.status === "waiting_approval");
  const pending = approvals.find(
    (a) => a.approval_id === waitingStep?.approval_id && a.status === "pending",
  );
  const constraints = graph.nodes.find(
    (n) => n.kind === "account",
  )?.constraints;
  const receipts = plans.flatMap((p) =>
    p.steps
      .filter((s) => s.receipt_id && s.result)
      .map((s) => ({ p, s, result: s.result as unknown as Verified })),
  );
  const billStep = plan?.steps.find(
    (s) => s.action.tool === "analyze_bills" && s.status === "succeeded",
  );
  const bill = (billStep?.result as unknown as Verified)?.receipt?.data;
  const categories = (bill?.categories || {}) as Record<string, number>;
  const clarificationStep = plan?.steps.find((s) => s.status === "waiting_clarification");
  const subscriptions = (plan?.steps.find((s) => s.action.tool === "subscriptions" && s.status === "succeeded")?.result as unknown as Verified)?.receipt;

  async function planOperation(path: string, body?: unknown) {
    if (!plan) return;
    showPlan(await api<TaskPlan>(`/agent/plans/${plan.plan_id}/${path}`, "POST", body));
    await refresh();
  }

  async function decision(approve: boolean) {
    if (!pending || !plan) return;
    await perform(async () => {
      await api(`/policy/approvals/${pending.approval_id}/decision`, "POST", {
        decision: approve ? "approve" : "reject",
        challenge_code: code || null,
      });
      showPlan(
        await api<TaskPlan>(`/agent/plans/${plan.plan_id}/resume`, "POST"),
      );
      await refresh();
    });
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="PACT 首页">
          <span className="brand-mark">
            P<span>↗</span>
          </span>
          <span>
            PACT<small>Commitments & Transactions</small>
          </span>
        </a>
        <div className="sidebar-caption">你的金融执行工作台</div>
        <nav aria-label="主导航">
          {[
            ["work", "◈", "Agent 工作台"],
            ["graph", "⌁", "资金承诺"],
            ["receipts", "▤", "回执与审计"],
          ].map(([id, icon, text]) => (
            <button
              key={id}
              className={tab === id ? "nav active" : "nav"}
              onClick={() => setTab(id)}
            >
              <span>{icon}</span>
              {text}
              <span className="nav-arrow">↗</span>
            </button>
          ))}
        </nav>
        <div className="side-note">
          <span className="live-dot" />
          安全边界始终在线
          <p>
            模型提出候选计划
            <br />
            策略引擎决定权限
            <br />
            银行后端核验执行结果
          </p>
        </div>
        <div className="sidebar-footer">
          FINTECHATHON 2026<small>V2.0 · 本地演示 MVP</small>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            PACT /{" "}
            <strong>
              {tab === "work"
                ? "Agent 工作台"
                : tab === "graph"
                  ? "资金承诺"
                  : "回执与审计"}
            </strong>
          </div>
          <div className="header-right">
            <span className="sandbox-badge">
              <span />
              纯模拟沙箱
            </span>
            {token && (
              <button
                className="avatar"
                onClick={() =>
                  void perform(async () => {
                    await api("/auth/logout", "POST");
                    setToken("");
                    setPlan(undefined);
                    setPlans([]);
                    setChats([]);
                    sessionStorage.clear();
                  })
                }
                title="退出演示身份"
              >
                {user === "alice" ? "A" : "B"}
              </button>
            )}
          </div>
        </header>
        <div className="page">
          <div className="page-heading">
            <div>
              <div className="eyebrow">COMMIT FIRST. TRANSACT SAFELY.</div>
              <h1>
                {tab === "work"
                  ? "把意图，变成可验证的行动。"
                  : tab === "graph"
                    ? "每一笔支出，都有承诺边界。"
                    : "每一次执行，都能追溯。"}
              </h1>
              <p>理解请求 · 约束先行 · 你来授权 · 回执说话</p>
            </div>
            <div className="date-pill">CNY / Asia·Shanghai</div>
          </div>
          <div className="sandbox-strip">
            <b>演示环境</b>
            <span>
              仅使用合成账户与交易。强验证为模拟流程，不连接真实银行。
            </span>
            <span className="mode">
              {planner === "ollama" ? "本地模型候选规划" : "规则演示规划器"}
            </span>
          </div>
          {error && (
            <div role="alert" className="alert">
              <b>操作未完成</b>
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="关闭错误">
                ×
              </button>
            </div>
          )}
          {notice && (
            <div role="status" className="notice">
              {notice}
            </div>
          )}
          {!token ? (
            <section className="login-card">
              <div className="section-kicker">01 / ENTER THE SANDBOX</div>
              <h2>进入你的模拟账户</h2>
              <p>登录仅用于切换演示身份，不是真实银行身份认证。</p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void perform(async () => {
                    const r = await api<{
                      access_token: string;
                      user_id: string;
                    }>("/auth/demo-session", "POST", { user_id: user, pin });
                    sessionStorage.setItem("pact-token", r.access_token);
                    sessionStorage.setItem("pact-user", r.user_id);
                    setToken(r.access_token);
                  });
                }}
              >
                <label>
                  演示身份
                  <select
                    value={user}
                    onChange={(e) => setUser(e.target.value)}
                  >
                    <option value="alice">Alice · 日常账户</option>
                    <option value="bob">Bob · 对照账户</option>
                  </select>
                </label>
                <label>
                  演示 PIN
                  <input
                    value={pin}
                    onChange={(e) => setPin(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <small>本地默认演示 PIN：246810。可在部署配置中修改。</small>
                <button className="primary" disabled={busy}>
                  {busy ? "正在进入…" : "进入沙箱 →"}
                </button>
              </form>
            </section>
          ) : (
            <>
              <section className="metrics" aria-label="账户概览">
                <div className="metric main-metric">
                  <span>
                    当前账户余额 <i>CNY</i>
                  </span>
                  <strong>{money(account?.balance_cents)}</strong>
                  <small>{account?.name}</small>
                </div>
                <div className="metric">
                  <span>未来资金承诺</span>
                  <strong>{money(constraints?.committed_cents)}</strong>
                  <small>涵盖已登记账单和下次订阅扣款</small>
                </div>
                <div className="metric">
                  <span>账户基础可用金额</span>
                  <strong>{money(constraints?.spendable_cents)}</strong>
                  <small>
                    已扣除账户基础留存 {money(constraints?.minimum_balance_cents)}
                  </small>
                </div>
              </section>
              {tab === "work" && (
                <div className="work-grid">
                  <div className="conversation-column">
                    <section className="panel chat-panel">
                      <div className="panel-heading">
                        <div>
                          <span className="section-kicker">01 / INTENT</span>
                          <h2>与 PACT 对话</h2>
                        </div>
                        <span className="quiet-tag">候选计划 ≠ 执行授权</span>
                      </div>
                      <div className="chat-log" aria-live="polite">
                        {chats.length === 0 ? (
                          <div className="welcome">
                            <span className="welcome-icon">↗</span>
                            <h3>说出你要做的事</h3>
                            <p>
                              我会先拆解步骤、检查资金承诺与权限。
                              <br />
                              需要你确认时，会停下来等待。
                            </p>
                            <div className="prompt-grid">
                              {demoPrompts.map((text, i) => (
                                <button
                                  key={text}
                                  onClick={() => setMessage(text)}
                                >
                                  <span>
                                    {
                                      [
                                        "跨场景联动",
                                        "红级模拟强验证",
                                        "未来资金承诺",
                                        "只读自动执行",
                                      ][i]
                                    }
                                  </span>
                                  {text}
                                  <b>↗</b>
                                </button>
                              ))}
                            </div>
                          </div>
                        ) : (
                          chats.map((c, i) => (
                            <div key={i} className={"chat-message " + c.role}>
                              <span>{c.role === "agent" ? "P" : "我"}</span>
                              <div>{c.text}</div>
                            </div>
                          ))
                        )}
                      </div>
                      <form
                        className="composer"
                        onSubmit={(e) => void submit(e)}
                      >
                        <label className="sr-only" htmlFor="message">
                          输入金融请求
                        </label>
                        <textarea
                          id="message"
                          value={message}
                          onChange={(e) => setMessage(e.target.value)}
                          placeholder="例如：分析本月账单，取消视频会员，再给张三转账500元"
                          maxLength={2000}
                          rows={3}
                          disabled={busy}
                        />
                        <div>
                          <small>
                            仅支持已知收款人；歧义或无法表达的条件会要求澄清。
                          </small>
                          <button
                            className="primary"
                            disabled={busy || !message.trim()}
                          >
                            {busy ? "处理中…" : "生成并检查计划 ↗"}
                          </button>
                        </div>
                      </form>
                    </section>
                    {bill && (
                      <section className="panel bill-panel">
                        <div className="panel-heading">
                          <div>
                            <span className="section-kicker">
                              LEDGER INSIGHT
                            </span>
                            <h2>账单分析</h2>
                          </div>
                          <span className="verified">✓ 来源：银行流水</span>
                        </div>
                        <div className="bill-total">
                          <span>本期消费支出（不含转账）</span>
                          <strong>{money(bill.expense_cents as number)}</strong>
                        </div>
                        {Object.entries(categories).map(([name, amount]) => (
                          <div className="bar-row" key={name}>
                            <span>{name}</span>
                            <div>
                              <i
                                style={{
                                  width:
                                    (amount /
                                      Math.max(
                                        ...Object.values(categories),
                                        1,
                                      )) *
                                      100 +
                                    "%",
                                }}
                              />
                            </div>
                            <b>{money(amount)}</b>
                          </div>
                        ))}
                        <p className="footnote">共 {String(bill.transaction_count)} 笔真实模拟流水；时间区间和来源交易编号见已核验回执。</p>
                        {((bill.anomalies || []) as {transaction_id: string; reason: string}[]).map((item) => <p className="alert" key={item.transaction_id}>{item.transaction_id}：{item.reason}</p>)}
                      </section>
                    )}
                    {subscriptions && <section className="panel">
                      <h2>已获确认的订阅查询快照</h2>
                      <p className="footnote">查询于 {new Date(subscriptions.created_at).toLocaleString("zh-CN")}；取消需另行明确确认，不退回历史扣款。</p>
                      {((subscriptions.data.items || []) as {subscription_id: string; name: string; amount_cents: number; active: boolean}[]).map((item) => <div className="subscription-row" key={item.subscription_id}>
                        <div><b>{item.name}</b><small>{money(item.amount_cents)} · {item.active ? "协议有效（查询时）" : "协议已取消（查询时）"}</small></div>
                        <button disabled={busy || !item.active} onClick={() => void perform(async () => {
                          const p = await api<TaskPlan>("/agent/plans", "POST", {message: `取消${item.name}`});
                          showPlan(await api<TaskPlan>(`/agent/plans/${p.plan_id}/run`, "POST"));
                          await refresh();
                        })}>申请取消</button>
                      </div>)}
                    </section>}
                    {plan && ["failed", "partially_completed", "waiting_clarification"].includes(plan.status || "") && (
                      <section className="panel replan-panel">
                        <h2>根据最新状态重规划</h2>
                        <p>保留已核验步骤，重新检查资金约束，旧审批失效。</p>
                        <label htmlFor="replan">新的请求</label>
                        <input
                          id="replan"
                          value={replanMessage}
                          onChange={(e) => setReplanMessage(e.target.value)}
                        />
                        <button
                          className="primary"
                          disabled={busy}
                          onClick={() =>
                            void perform(async () => {
                              const p = await api<TaskPlan>(
                                `/agent/plans/${plan.plan_id}/replan`,
                                "POST",
                                { message: replanMessage },
                              );
                              showPlan(
                                await api<TaskPlan>(
                                  `/agent/plans/${p.plan_id}/run`,
                                  "POST",
                                ),
                              );
                              await refresh();
                            })
                          }
                        >
                          重规划并检查 →
                        </button>
                      </section>
                    )}
                  </div>
                  <div className="execution-column">
                    <section className="panel dag-panel">
                      <div className="panel-heading">
                        <div>
                          <span className="section-kicker">
                            02 / EXECUTION DAG
                          </span>
                          <h2>可检查的执行路径</h2>
                        </div>
                        <span
                          className={"state " + (plan?.status || "planned")}
                        >
                          {plan
                            ? stateNames[plan.status || "planned"]
                            : "等待请求"}
                        </span>
                      </div>
                      {uncertainPlan && <div className="alert" role="status">执行请求的响应未确认，界面状态可能过期。请先读取原计划，不要重复付款。
                        <button disabled={busy} onClick={() => void perform(async () => { showPlan(await api<TaskPlan>(`/agent/plans/${uncertainPlan}`)); setUncertainPlan(""); await refresh(); })}>刷新原计划结果</button>
                      </div>}
                      {!plan ? (
                        <div className="empty-dag">
                          <div>意图 → DAG → 授权 → 执行 → 回执</div>
                          <p>
                            请求到来后，每个步骤的依赖、风险和结果都会显示在这里。
                          </p>
                        </div>
                      ) : (
                        <>
                          <div className="plan-title">
                            <b>{plan.title}</b>
                            <small>
                              版本 {plan.version} · {plan.plan_id.slice(0, 17)}…
                            </small>
                          </div>
                          <p className="progress-summary" aria-live="polite">已核验 {plan.progress?.completed || 0} · 失败 {plan.progress?.failed || 0} · 待核验 {plan.progress?.pending_verification || 0} · 未完成 {plan.progress?.remaining || 0}</p>
                          <ol className="dag">
                            {plan.steps.map((s, i) => (
                              <li key={s.step_id} className={s.status}>
                                <span className="step-number">
                                  {s.status === "succeeded"
                                    ? "✓"
                                    : String(i + 1).padStart(2, "0")}
                                </span>
                                <div className="step-content">
                                  <div>
                                    <b>{toolNames[s.action.tool]}</b>
                                    {s.risk_level && (
                                      <span className={"risk " + s.risk_level}>
                                        {s.risk_level === "green"
                                          ? "绿 · 自动"
                                          : s.risk_level === "yellow"
                                            ? "黄 · 确认"
                                            : "红 · 强验证"}
                                      </span>
                                    )}
                                  </div>
                                  <p>
                                    {"amount_cents" in s.action
                                      ? money(s.action.amount_cents) +
                                        " → " +
                                        (s.action.recipient_id === "rcp-zhang"
                                          ? "张三"
                                          : s.action.recipient_id === "rcp-li"
                                            ? "李四"
                                            : "Alice")
                                      : s.action.tool === "cancel_subscription"
                                        ? s.action.subscription_id ===
                                          "sub-video"
                                          ? "视频会员"
                                          : "音乐会员"
                                        : "从银行沙箱读取并核验数据"}
                                  </p>
                                  <small>
                                    {stateNames[s.status || "planned"]} ·{" "}
                                    {s.depends_on?.length
                                      ? "依赖 " + s.depends_on.join(", ")
                                      : "起始步骤"}
                                  </small>
                                  {s.error && (
                                    <div className="step-error">
                                      {String(s.error.message)}
                                    </div>
                                  )}
                                  {s.receipt_id && (
                                    <button
                                      className="text-button"
                                      onClick={() =>
                                        void perform(async () =>
                                          setDetail(
                                            await api<Verified>(
                                              `/banking/receipts/${s.receipt_id}/verify`,
                                            ),
                                          ),
                                        )
                                      }
                                    >
                                      查看已查询回执 ↗
                                    </button>
                                  )}
                                </div>
                              </li>
                            ))}
                          </ol>
                          <div className="plan-controls">
                            <button
                              disabled={
                                busy ||
                                ["succeeded", "failed", "paused", "pending_verification", "partially_completed", "handed_off"].includes(
                                  plan.status || "",
                                )
                              }
                              onClick={() =>
                                void perform(async () => {
                                  setPlan(
                                    await api<TaskPlan>(
                                      `/agent/plans/${plan.plan_id}/pause`,
                                      "POST",
                                    ),
                                  );
                                  await refresh();
                                })
                              }
                            >
                              暂停计划
                            </button>
                            <button
                              disabled={
                                busy || Boolean(uncertainPlan) ||
                                ["succeeded", "failed", "pending_verification", "partially_completed", "handed_off", "waiting_clarification"].includes(
                                  plan.status || "",
                                )
                              }
                              onClick={() =>
                                void perform(async () => {
                                  showPlan(
                                    await api<TaskPlan>(
                                      `/agent/plans/${plan.plan_id}/resume`,
                                      "POST",
                                    ),
                                  );
                                  await refresh();
                                })
                              }
                            >
                              恢复 / 继续
                            </button>
                          </div>
                        </>
                      )}
                    </section>
                    {clarificationStep?.clarification && <section className="panel clarification-panel" aria-label="收款人消歧">
                      <h2>请核实同名收款人</h2>
                      <p>“{clarificationStep.clarification.query}”对应下列已保存对象。选择只确定收款人，付款仍需后续授权。</p>
                      {clarificationStep.clarification.options.length === 0 && <p>没有可选收款人，请调整请求或交人工处理。</p>}
                      {clarificationStep.clarification.options.map((option) => <button className="recipient-choice" key={option.recipient_id} disabled={busy} onClick={() => void perform(async () => {
                        const p = await api<TaskPlan>(`/agent/plans/${plan!.plan_id}/select-recipient`, "POST", {plan_version: plan!.version, step_id: clarificationStep.step_id, clarification_id: clarificationStep.clarification!.clarification_id, recipient_id: option.recipient_id});
                        showPlan(await api<TaskPlan>(`/agent/plans/${p.plan_id}/run`, "POST"));
                        await refresh();
                      })}><b>{option.name}</b><span>{option.account_hint}</span><small>选择并继续检查 →</small></button>)}
                    </section>}
                    {plan && (plan.status === "pending_verification" || plan.steps.some((s) => s.status === "pending_verification")) && <section className="panel pending-panel" aria-label="交易待核验">
                      <h2>交易结果待核验</h2><p>执行可能已发生，当前不宣告成功或失败。只查询原交易，不会重新付款，也不会自动继续后续步骤。</p>
                      <button disabled={busy} className="primary" onClick={() => void perform(() => planOperation("reconcile"))}>查询原交易核验结果</button>
                    </section>}
                    {plan && plan.status !== "succeeded" && <section className="panel handoff-panel" aria-label="人工接管">
                      <h2>{plan.status === "handed_off" ? "人工接管中" : "人工接管"}</h2>
                      <p>本地演示由当前账户持有人处理；不会代替银行客服或将交易标记为成功。接管时冻结自动执行、作废旧审批。</p>
                      {plan.handoff && <p className="footnote">接管记录：{plan.handoff.reason} · {plan.handoff.status === "active" ? "处理中" : "已交还"}</p>}
                      <label htmlFor="handoff-note">处理说明</label>
                      <textarea id="handoff-note" value={handoffNote} onChange={(e) => setHandoffNote(e.target.value)} maxLength={500} rows={2}/>
                      <button disabled={busy || !handoffNote.trim()} onClick={() => void perform(() => planOperation(plan.status === "handed_off" ? "handoff/release" : "handoff", plan.status === "handed_off" ? {plan_version: plan.version, note: handoffNote} : {plan_version: plan.version, reason: handoffNote}))}>{plan.status === "handed_off" ? "记录处理说明并交还" : "暂停自动执行并接管"}</button>
                    </section>}
                    {pending && (
                      <section
                        className={"approval-card " + pending.level}
                        aria-label="当前审批"
                      >
                        <div className="section-kicker">
                          03 / YOUR AUTHORIZATION
                        </div>
                        <h2>
                          {pending.level === "red"
                            ? "需要模拟强验证"
                            : "需要你确认"}
                        </h2>
                        <p>{pending.reason}</p>
                        <div className="approval-action">
                          <span>{toolNames[String(pending.action.tool)]}</span>
                          <strong>
                            {pending.action.amount_cents
                              ? money(pending.action.amount_cents as number)
                              : pending.action.tool === "subscriptions" ? "确认查询本账户订阅协议快照"
                              : pending.action.subscription_id === "sub-video"
                                ? "视频会员"
                                : "音乐会员"}
                          </strong>
                        </div>
                        <small>
                          只授权当前版本、当前步骤及其参数。确认后，后端仍会重查日累计和资金约束。
                        </small>
                        {Boolean(pending.action.recipient_id) && (
                          <p>
                            收款人：
                            {(() => {const r = recipients.find((r) => r.recipient_id === pending.action.recipient_id); return r ? `${r.name} · ${r.account_hint}` : String(pending.action.recipient_id);})()}
                          </p>
                        )}
                        {Boolean(pending.action.due_at) && (
                          <p>
                            执行时间（上海）：{new Date(String(pending.action.due_at)).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}
                            <br />登记成功不会立即付款，到期重新授权。
                          </p>
                        )}
                        <p>
                          本请求留存要求：{plan?.minimum_balance_cents ? money(plan.minimum_balance_cents) : "沿用账户基础留存"}，不会降低账户基础留存。
                        </p>
                        {pending.action.tool === "cancel_subscription" && <p>仅取消该代扣协议及其尚未发生的扣款承诺，不代表退款或商户会员退订。</p>}
                        {pending.level === "red" && (
                          <div className="challenge">
                            <button
                              disabled={busy}
                              onClick={() =>
                                void perform(async () => {
                                  const r = await api<{ demo_code: string }>(
                                    `/policy/approvals/${pending.approval_id}/challenge`,
                                    "POST",
                                  );
                                  setDemoCode(r.demo_code);
                                })
                              }
                            >
                              申请模拟验证码
                            </button>
                            {demoCode && (
                              <p>
                                演示码：<b>{demoCode}</b>（2分钟有效；不是真实
                                OTP）
                              </p>
                            )}
                            <label htmlFor="challenge-code">输入演示码</label>
                            <input
                              id="challenge-code"
                              value={code}
                              onChange={(e) => setCode(e.target.value)}
                              inputMode="numeric"
                              autoComplete="off"
                              maxLength={6}
                            />
                          </div>
                        )}
                        <div className="approval-buttons">
                          <button
                            disabled={busy || Boolean(uncertainPlan)}
                            onClick={() => void decision(false)}
                          >
                            拒绝
                          </button>
                          <button
                            className="primary"
                            disabled={
                              busy || Boolean(uncertainPlan) ||
                              (pending.level === "red" && code.length !== 6)
                            }
                            onClick={() => void decision(true)}
                          >
                            {pending.level === "red"
                              ? "验证并继续 →"
                              : "确认此操作 →"}
                          </button>
                        </div>
                      </section>
                    )}
                    <section className="panel history-panel">
                      <div className="panel-heading">
                        <h2>已保存的计划</h2>
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() =>
                            void perform(async () => {
                              await refresh();
                              setNotice("已刷新后端状态");
                            })
                          }
                        >
                          刷新 ↻
                        </button>
                      </div>
                      {plans.length === 0 ? (
                        <p className="muted">暂无计划。发送第一条请求开始。</p>
                      ) : (
                        plans.slice(0, 8).map((p) => (
                          <button
                            key={p.plan_id}
                            className={
                              "history-item " +
                              (p.plan_id === plan?.plan_id ? "selected" : "")
                            }
                            onClick={() => {
                              setPlan(p);
                              setTab("work");
                            }}
                          >
                            <span>{p.title}</span>
                            <small>{stateNames[p.status || "planned"]}</small>
                          </button>
                        ))
                      )}
                    </section>
                  </div>
                </div>
              )}
              {tab === "graph" && (
                <section className="panel graph-panel">
                  <div className="panel-heading">
                    <div>
                      <span className="section-kicker">
                        FINANCIAL CONSTRAINT ENGINE
                      </span>
                      <h2>精简资金承诺图</h2>
                    </div>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void perform(async () => {
                          const r = await api<{
                            created_plan_ids: string[];
                            message: string;
                          }>("/banking/schedules/prepare-due", "POST");
                          await refresh();
                          setNotice(
                            `${r.message}；本次生成 ${r.created_plan_ids.length} 个计划。`,
                          );
                        })
                      }
                    >
                      检查到期任务 ↻
                    </button>
                  </div>
                  <p className="muted">
                    可用金额 = 当前余额 − 最低留存余额 −
                    全部有效未来承诺。每次实际执行时重新校验。
                  </p>
                  <div className="graph-account">
                    <span>◈</span>
                    <div>
                      {account?.name}
                      <strong>{money(account?.balance_cents)}</strong>
                    </div>
                    <b>预留 →</b>
                  </div>
                  <div className="commitment-grid">
                    {graph.nodes
                      .filter((n) => n.kind !== "account")
                      .map((n) => (
                        <article key={n.id}>
                          <span className="commitment-kind">
                            {n.kind === "scheduled_transfer"
                              ? "定时转账 · 尚未付款"
                              : n.kind === "subscription_summary" ? "汇总预留 · 查询详情需确认"
                              : n.kind === "subscription"
                                ? "下次订阅扣款"
                                : "已登记账单"}
                          </span>
                          <h3>{n.label}</h3>
                          <strong>{money(n.amount_cents)}</strong>
                          <small>
                            {n.due_at
                              ? new Date(n.due_at).toLocaleString("zh-CN", {
                                  timeZone: "Asia/Shanghai",
                                })
                              : ""}
                          </small>
                          <span className="reserve-label">已计入资金约束</span>
                        </article>
                      ))}
                  </div>
                  <p className="footnote">
                    订阅只预留下次扣款；定时转账到期后生成新的授权任务，不会把登记回执当作付款回执。
                  </p>
                </section>
              )}
              {tab === "receipts" && (
                <div className="receipt-grid">
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <span className="section-kicker">
                          BANKING SOURCE OF TRUTH
                        </span>
                        <h2>后端回执</h2>
                      </div>
                      <span className="quiet-tag">{receipts.length} 项</span>
                    </div>
                    {receipts.length ? (
                      receipts.map(({ s, result }) => (
                        <button
                          key={s.receipt_id}
                          className="receipt-item"
                          onClick={() =>
                            void perform(async () =>
                              setDetail(
                                await api<Verified>(
                                  `/banking/receipts/${s.receipt_id}/verify`,
                                ),
                              ),
                            )
                          }
                        >
                          <span className="receipt-icon">✓</span>
                          <div>
                            <b>{toolNames[s.action.tool]}</b>
                            <small>{s.receipt_id?.slice(0, 22)}…</small>
                          </div>
                          <span>
                            {result.receipt.status === "scheduled"
                              ? "已登记 / 未付款"
                              : "查看核验 →"}
                          </span>
                        </button>
                      ))
                    ) : (
                      <div className="empty-dag">
                        还没有已查询回执。先完成一个工作流。
                      </div>
                    )}
                  </section>
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <span className="section-kicker">AUDIT TRAIL</span>
                        <h2>执行轨迹</h2>
                      </div>
                      <span
                        className={
                          audit.chain_valid ? "verified" : "danger-text"
                        }
                      >
                        {audit.chain_valid ? "✓ 哈希链完整" : "审计链异常"}
                      </span>
                    </div>
                    <div className="audit-list">
                      {audit.items.slice(0, 30).map((a) => (
                        <div key={a.id}>
                          <span>#{a.id}</span>
                          <div>
                            <b>{a.event}</b>
                            <small>
                              {new Date(a.created_at).toLocaleString("zh-CN", {
                                timeZone: "Asia/Shanghai",
                              })}
                            </small>
                          </div>
                        </div>
                      ))}
                    </div>
                    <p className="footnote">
                      本地哈希链用于发现内容变化，不是独立防篡改存储或第三方安全认证。
                    </p>
                  </section>
                </div>
              )}
            </>
          )}
          <footer>
            PACT V2.0 <span>每一步可检查，每一笔可核验。</span>
            <a href="/docs" target="_blank" rel="noreferrer">
              API 文档 ↗
            </a>
          </footer>
        </div>
      </main>
      {detail && (
        <div className="modal-backdrop" onClick={() => setDetail(undefined)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-label="后端回执核验详情"
            className="receipt-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-heading">
              <h2>后端回执核验</h2>
              <button
                autoFocus
                onClick={() => setDetail(undefined)}
                aria-label="关闭回执详情"
              >
                关闭 ×
              </button>
            </div>
            <div className={detail.verified ? "verification-good" : "alert"}>
              {detail.verified
                ? "✓ 已从银行后端查询并通过核验"
                : "核验未通过，不应视为已确认结果"}
            </div>
            <p>
              {detail.receipt.status === "scheduled"
                ? "这是登记回执，尚未发生付款。"
                : "结果由银行后端保存，模型不能生成或覆盖。"}
            </p>
            <pre>{JSON.stringify(detail, null, 2)}</pre>
          </section>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
