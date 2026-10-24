# 0.4 本地实现与评审范围

当前会话授权：继续按独立部署、参赛演示和验收的MVP口径构建；沿用已讨论的“资金竞争由用户选择、明确更正关联旧任务、含糊表达先澄清、完成动作不伪造撤回”。此前暂停上传；2026-10-25用户明确授权整理GitHub，本轮可提交草稿PR与接口评审Issue，不代发团队群消息，不自动合并main。

已在本地增加：/agent/messages及持久化会话与澄清；/agent/conflicts及用户决策；/agent/plans/{id}/interrupt及已执行动作检查；TaskPlan 0.4状态与运行元数据。业务执行入口、结构化候选和聊天均受相同后端协调约束，不能靠换入口跳过冲突。保留既有权限与资金边界，不宣称已具备完整银行系统或任意语言理解。

影响A/B/C/D、协议、工作台、部署验收和安全自评。完整参数以生成OpenAPI为准。仍需团队同步和评审后才能合并/冻结协议；未取得群同步记录。远端CI以PR #8本轮实际结果为准。

外部候选新增openai_compatible planner标记与本机模型配置；未新增公共监听端口。模型不获银行执行工具或授权。默认协议版本0.4，精确参数以生成OpenAPI为准。

评审入口：[Issue #10](https://github.com/ThreshoLdnnis/pact-v2/issues/10)、[草稿PR #8](https://github.com/ThreshoLdnnis/pact-v2/pull/8)。剩余验收集中在[Issue #11](https://github.com/ThreshoLdnnis/pact-v2/issues/11)。
