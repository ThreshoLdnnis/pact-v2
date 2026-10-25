import type { TaskPlan } from "./protocol";

const labels: Record<string, string> = { analyze_bills: "账单分析", subscriptions: "订阅查询", cancel_subscription: "取消会员", transfer: "转账", schedule_transfer: "定时转账", balance: "余额初查", recipients: "收款人查询", commitments: "资金承诺", transactions: "流水查询" };

export function DependencyGraph({ plan }: { plan: TaskPlan }) {
  const depth = new Map<string, number>();
  for (let pass = 0; pass < plan.steps.length; pass++) {
    for (const step of plan.steps) {
      if (!depth.has(step.step_id) && (step.depends_on || []).every(d => depth.has(d)))
        depth.set(step.step_id, Math.max(-1, ...(step.depends_on || []).map(d => depth.get(d)!)) + 1);
    }
  }
  const levels = new Map<number, typeof plan.steps>();
  for (const step of plan.steps) {
    const level = depth.get(step.step_id) || 0;
    levels.set(level, [...(levels.get(level) || []), step]);
  }
  const width = Math.max(360, ...[...levels.values()].map(items => items.length * 190));
  const height = levels.size * 88 + 24;
  const positions = new Map<string, { x: number; y: number }>();
  for (const [level, items] of levels) items.forEach((s, i) => positions.set(s.step_id, { x: width / (items.length + 1) * (i + 1), y: 42 + level * 88 }));
  return <div className="dependency-diagram">
    <svg viewBox={`0 0 ${width} ${height}`} style={{ minWidth: width }} role="img" aria-label="业务依赖图：同层分支相互独立，箭头表示必须核验的前置步骤">
      {plan.steps.flatMap(step => (step.depends_on || []).map(dep => {
        const from = positions.get(dep), to = positions.get(step.step_id);
        if (!from || !to) return null;
        const y = to.y - 25;
        return <g key={`${dep}-${step.step_id}`} stroke="#718579" fill="none"><path d={`M${from.x},${from.y + 25} L${to.x},${y}`} /><path d={`M${to.x - 4},${y - 6} L${to.x},${y} L${to.x + 4},${y - 6}`} /></g>;
      }))}
      {plan.steps.map(step => {
        const p = positions.get(step.step_id)!;
        const title = labels[step.action.tool] || step.action.tool;
        return <g key={step.step_id}>
          <rect x={p.x - 82} y={p.y - 25} width="164" height="50" rx="9" fill={step.status === "succeeded" ? "#e5f2e8" : step.status === "failed" ? "#ffe8e2" : "#f4f6f2"} stroke="#9eb3a4" />
          <text x={p.x} y={p.y - 3} textAnchor="middle" fontSize="12" fill="#163e2a">{title}{"amount_cents" in step.action ? ` · ${step.action.amount_cents / 100}元` : ""}</text>
          <text x={p.x} y={p.y + 14} textAnchor="middle" fontSize="10" fill="#496451">{step.step_id}</text>
        </g>;
      })}
    </svg>
  </div>;
}
