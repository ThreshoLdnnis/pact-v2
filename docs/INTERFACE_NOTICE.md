# 协议0.1首次实现群同步稿

状态：准备好的同步文案，尚未实际发到团队群，不代表团队已经确认。它随实现PR供评审，合并/冻结公共接口前需补充消息与回复证据。

【PACT公共接口新增】候选计划与银行工具协议0.1

用途：打通自然语言/DAG、服务端权限、用户授权、沙箱实际执行和回执核验。金额统一整数分，日累计按Asia/Shanghai自然日。

HTTP方法/路径：

- Agent：POST /api/v1/agent/plans、/candidates；GET /plans、/plans/{id}；POST /plans/{id}/run、/pause、/resume、/replan。
- Banking：GET /api/v1/banking/accounts及本人账户的balance、transactions、analyze_bills、subscriptions、commitments、recipients；POST /banking/execute；GET /banking/receipts/{id}及/verify；GET /banking/commitment-graph、/reconciliation；POST /banking/schedules/prepare-due。
- Policy：POST /api/v1/policy/evaluate；GET /policy/approvals；POST /policy/approvals/{id}/challenge、/decision。
- 演示身份：POST /api/v1/auth/demo-session、/logout；审计GET /api/v1/audit。

参数/响应：TaskPlan、TaskStep、ApprovalRequest、ExecutionReceipt、BankingCommand以contracts/models.py为唯一来源，精确结构见生成的task-protocol.schema.json与openapi.json。详细路由表和JSON示例见docs/API.md。

权限/幂等：模型仅生成CandidatePlan。Policy判级。Banking绑定用户/版本/步骤/参数和固定幂等键，执行时重判日累计与资金约束。回执查询verified=true后才能完成步骤。

端口：统一FastAPI工作台/API 8000；开发前端5173。准备稿8001/8002没有创建，使用模块化同进程的Agent/Banking/Policy边界。

影响模块：A/B/C/D和部署配置全部受影响。此为首次草案实现，没有需要兼容的已上线业务接口。后续任何新增、修改、废弃继续按接口变更流程进行。

需要团队回复：确认字段与状态口径、三级规则来源、接口与端口、模拟认证的演示标识。回复记录和群消息链接：待补充。
