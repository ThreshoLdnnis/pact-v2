# 协议0.2核心业务变更群同步稿

本次变更已获当前聊天用户明确授权实现；尚未实际发送团队群，不宣称已完成团队评审或协议冻结。保留Draft PR供核对。

用途：订阅查询黄色门禁、同名收款人选择、交易待核验、部分完成与人工接管。

新增POST /api/v1/agent/plans/{id}/select-recipient、/reconcile、/handoff、/handoff/release；入参与响应见docs/API.md。GET subscriptions改为需要已确认查询的receipt_id并返回快照，未确认403；绿色承诺接口隐藏协议明细。新增状态及TaskPlan.progress/handoff、TaskStep.clarification、ApprovalRequest.scope_hash。模型仅允许候选字段。

影响：Agent、Policy、Banking、工作台和测试/生成协议；旧客户端需更新状态枚举和订阅读取方式。没有新增端口。跨场景顺序、depends_on及跨DAG冲突机制不在本次变更范围。

验证：tests/test_business_boundaries.py及原回归测试、生成协议一致性、TypeScript编译和实际浏览器操作。变更文档见BUSINESS_DAGS.md和STATE_MACHINE.md。群消息/负责人回复证据：待补。

---

## 历史：协议0.1首次实现稿

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
