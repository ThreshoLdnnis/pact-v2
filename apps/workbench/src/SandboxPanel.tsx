import { useEffect, useState } from "react";
import type { TaskPlan } from "./protocol";

export function SandboxPanel({ plan, onReset }: { plan?: TaskPlan; onReset: () => void }) {
  const [secret, setSecret] = useState("");
  const [scenario, setScenario] = useState("baseline");
  const [confirmed, setConfirmed] = useState(false);
  const [step, setStep] = useState("");
  const [point, setPoint] = useState("verify_timeout");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { setStep(plan?.steps.find(s => !["succeeded", "failed", "pending_verification"].includes(s.status || ""))?.step_id || ""); }, [plan]);

  async function call(path: string, payload?: unknown) {
    setBusy(true); setError("");
    try {
      const r = await fetch("/api/v1/sandbox/" + path, {
        method: payload === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json", "X-Sandbox-Admin": secret },
        ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error?.message || "测试控制请求失败");
      setReport(JSON.stringify(body, null, 2));
      if (path === "reset") { onReset(); setConfirmed(false); }
    } catch (e) { setError(e instanceof Error ? e.message : "请求失败"); }
    finally { setBusy(false); }
  }

  return <section className="panel sandbox-controls">
    <h2>合成数据测试控制</h2>
    <p>仅供演示和验收。默认关闭；需要部署时单独设置的管理员令牌，演示登录不能替代。令牌仅保留在当前页面内存中，不交给Agent。</p>
    <label>管理员令牌<input type="password" autoComplete="off" value={secret} onChange={e => setSecret(e.target.value)} /></label>
    {error && <p role="alert" className="danger-text">{error}</p>}
    <h3>恢复场景</h3>
    <label>场景<select value={scenario} onChange={e => setScenario(e.target.value)}><option value="baseline">标准演示账户</option><option value="tight_budget">资金紧张：取消前可转402元，取消后500元</option></select></label>
    <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />确认清空所有合成业务记录和会话，保留审计历史</label>
    <button disabled={busy || !secret || !confirmed} onClick={() => void call("reset", { scenario, confirmation: "RESET_SYNTHETIC_DATA" })}>一键重置并退出演示会话</button>
    <h3>单次故障</h3>
    <p>先在工作台选中未完成计划；故障只绑定该计划版本和步骤，10分钟后失效，不改变权限规则。</p>
    <label>目标步骤<select value={step} onChange={e => setStep(e.target.value)}>{plan?.steps.filter(s => !["succeeded", "failed", "pending_verification"].includes(s.status || "")).map(s => <option key={s.step_id} value={s.step_id}>{s.step_id} · {s.action.tool}</option>)}</select></label>
    <label>故障类型<select value={point} onChange={e => setPoint(e.target.value)}><option value="verify_timeout">执行后核验超时</option><option value="before_post_reject">执行前明确拒绝</option><option value="after_mutation_rollback">业务变更后异常并回滚</option></select></label>
    <div className="approval-buttons">
      <button disabled={busy || !secret || !plan || !step} onClick={() => void call("faults", { plan_id: plan?.plan_id, plan_version: plan?.version, step_id: step, point })}>设置单次故障</button>
      <button disabled={busy || !secret} onClick={() => void call("faults/clear", {})}>清除故障</button>
    </div>
    <h3>独立验收</h3>
    <p>直接读取账务、授权和回执记录，检查余额守恒、交易分录、依赖证据和审计链。不会修改业务状态。</p>
    <button disabled={busy || !secret} onClick={() => void call("acceptance")}>运行独立验收</button>
    <pre aria-live="polite">{report}</pre>
  </section>;
}
