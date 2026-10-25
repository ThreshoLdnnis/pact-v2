import type { TaskPlan } from "./protocol";

export type Question = {clarification_id: string; question: string; status: string; options: {option_id: string; label: string}[]};
export type Conflict = {conflict_id: string; status: string; message: string; plans: {plan_id: string; title: string}[]; reasons: {kind: string; available_cents?: number; requested_cents?: number; message?: string}[]};

export function InteractionPanel({question, conflicts, plan, busy, onClarify, onConflict, onInterrupt}: {
  question?: Question; conflicts: Conflict[]; plan?: TaskPlan; busy: boolean;
  onClarify: (id: string, option: string) => void;
  onConflict: (id: string, choice: "execute_plan" | "keep_subscription" | "pause_all", planId?: string) => void;
  onInterrupt: () => void;
}) {
  return <>
    {question?.status === "pending" && <section className="panel clarification-panel" aria-label="任务与意图澄清">
      <h2>需要你明确一下</h2><p>{question.question}</p>
      {question.options.map(o => <button className="recipient-choice" key={o.option_id} disabled={busy} onClick={() => onClarify(question.clarification_id, o.option_id)}>{o.label}</button>)}
      {!question.options.length && <p className="muted">请在聊天框补充完整要求；当前没有新增执行动作。</p>}
    </section>}
    {conflicts.filter(c => c.status === "open").map(c => <section className="panel conflict-panel" key={c.conflict_id} aria-label="由用户选择的任务冲突">
      <h2>这些安排需要你选择</h2><p>{c.message}</p>
      {c.reasons.map((r, i) => <p key={i}>{r.kind === "funds" ? `当前可支出${((r.available_cents || 0) / 100).toFixed(2)}元，相关任务合计${((r.requested_cents || 0) / 100).toFixed(2)}元。` : r.message}</p>)}
      {c.plans.map(p => <button className="recipient-choice" key={p.plan_id} disabled={busy} onClick={() => onConflict(c.conflict_id, "execute_plan", p.plan_id)}>选择这项安排：{p.title}</button>)}
      {c.reasons.some(r => r.kind === "subscription_intent") && <button disabled={busy} onClick={() => onConflict(c.conflict_id, "keep_subscription")}>保留会员，暂停取消任务</button>}
      <button disabled={busy} onClick={() => onConflict(c.conflict_id, "pause_all")}>先全部暂停</button>
      <p className="footnote">选择只决定任务安排；不会自动付款。后端仍检查实时资金和授权，其他任务保持暂停。</p>
    </section>)}
    {plan && <section className="panel interruption-panel">
      <h2>中断与已完成动作</h2>
      <p>停止后续步骤时，先核对哪些动作已经发生。付款不会自动退款，已取消协议不会自动恢复。</p>
      <button disabled={busy || plan.status === "handed_off"} onClick={onInterrupt}>停止未执行部分，并检查已有结果</button>
      {plan.interruption && <div aria-live="polite">
        <p>{plan.interruption.message}</p>
        <p>保留回执 {plan.interruption.retained_receipt_ids?.length || 0} 项 · 停止步骤 {plan.interruption.cancelled_step_ids?.length || 0} 项 · 等待新安排 {plan.interruption.blocked_step_ids?.length || 0} 项 · 结果待核验 {plan.interruption.unknown_receipt_ids?.length || 0} 项</p>
        {(plan.interruption.compensation_items || []).map((item, i) => <p key={i} className="footnote">{item.operation === "withdraw_schedule" ? (item.withdrawn ? "已撤销尚未付款的定时安排；原登记回执保留。" : String(item.reason)) : String(item.message)}</p>)}
      </div>}
    </section>}
  </>;
}
