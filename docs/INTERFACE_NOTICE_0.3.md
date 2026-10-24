# 0.3 共享接口变更草案

2026-10-24：用户在当前会话明确授权实现可复用业务 DAG、组合依赖、一键重置、故障注入和独立验收。此授权用于本功能分支开发；没有向团队群发送消息，没有成员回复证据，不宣称团队协议已冻结。合并前仍按 INTERFACE_CHANGES.md 做团队同步。

- 新增 GET /api/v1/agent/templates：三个业务模板及强制执行关口。
- 新增 POST /api/v1/agent/compositions：title、minimum_balance_cents、instances（instance_id、template_id、action、depends_on），返回 TaskPlan。
- TaskPlan 升至 0.3；TaskStep 增加服务端生成的 template_id、template_instance_id、template_version；增加 ready_step_ids。模型 CandidatePlan 不可提供这些字段。
- 取消订阅必须先有本计划同账户的已授权、已核验订阅查询；服务端为旧候选自动补齐查询节点。取消与查询是两份独立授权。此行为会增加步骤和确认次数。
- 新增 /api/v1/sandbox/reset、/faults、/acceptance 测试控制接口；默认关闭，需独立 X-Sandbox-Admin 令牌，普通会话及 Agent 工具均不能调用。重置会清空所有合成业务状态与会话，保留审计链；无新增端口。
- 影响 A/B/C/D、共享 Schema、演示脚本和集成测试。更新机器协议、API、DAG和部署说明。本轮不制定多请求的优先级、矛盾消解或撤销策略。

发布状态：尝试创建GitHub接口评审Issue被自动审批拒绝（团队群未先同步、外部写入授权证据不足）；没有创建成功，不存在可引用的新Issue。本轮代码与证据仅保存在本地工作区和0.3部署包，未上传或更新PR #8，未运行本轮远端CI。共享发布需另获明确授权或先补齐团队同步证据，不能绕过该拒绝。
