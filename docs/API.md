# PACT 协议 0.1 与 API

状态：可运行的评审实现，尚未群同步/冻结。代码唯一来源为 contracts/models.py。运行 python scripts/export_contracts.py 生成完整 OpenAPI、Banking Tool OpenAPI、Task Protocol JSON Schema 和前端 protocol.ts。

## 通用规则

- 基础路径 /api/v1，除 /auth/demo-session、/meta、/health 外均需 Authorization: Bearer <演示会话令牌>。
- 金额 amount_cents/minimum_balance_cents 为整数分，拒绝浮点/负数/布尔金额。币种 CNY。
- 存储时间为带时区 UTC ISO 8601；日累计按 Asia/Shanghai 自然日，按用户所有账户成功转出汇总，包含本次拟转金额。
- 只接受白名单工具和闭合字段。模型无权设置风险等级、审批状态、执行状态或结果。
- Domain 错误为 {error:{code,message,details}}。422 表示结构/意图需澄清，401 未登录，404 资源不存在或非本人，409 状态/绑定/约束不满足，429 限速或熔断，502 模型输出不合规或不可用。
- 32 KiB 请求体上限，包括分块传输。读取列表最多返回最近100项；本版尚无分页。

## 两套协议与核心对象

Task Protocol 负责候选、DAG 与状态。Banking Tool Protocol 负责规范执行命令和真实模拟回执。Policy API 决定等级并收集授权，不能以模型传入等级为依据。

| 对象 | 核心字段 | 谁可以产生权威值 |
| --- | --- | --- |
| CandidatePlan | title, minimum_balance_cents, steps | 模型/规则/手工输入，只有候选效力 |
| TaskPlan | schema_version, plan_id, version, title, planner, status, steps, created_at | Agent 后端 |
| TaskStep | step_id, depends_on, action, status, risk_level, approval_id, receipt_id, result, error | 候选只能提供前三项，运行字段由后端生成 |
| ApprovalRequest | approval_id, plan_id, plan_version, step_id, action_hash, level, status, expires_at, action | Policy 后端 |
| ExecutionReceipt | receipt_id, plan_id, plan_version, step_id, action_hash, operation, status, transaction_id, data, created_at | Banking 后端 |
| BankingCommand | plan_id, plan_version, step_id, idempotency_key, action | 调用方提交，后端与已保存步骤逐字段比对 |

## 路由目录

| 方法 | 路径 | 请求/结果 |
| --- | --- | --- |
| POST | /auth/demo-session | {user_id:alice或bob,pin}；返回8小时会话令牌，仅保存令牌哈希 |
| POST | /auth/logout | 撤销当前会话 |
| POST | /agent/plans | {message}；生成 TaskPlan，不自动付款 |
| POST | /agent/candidates | 严格 CandidatePlan；校验 DAG、资源归属后保存 |
| GET | /agent/plans | 当前用户计划列表 |
| GET | /agent/plans/{id} | 当前持久化 TaskPlan |
| POST | /agent/plans/{id}/run | 执行到完成、失败或待授权，返回 TaskPlan |
| POST | /agent/plans/{id}/pause | 暂停非终态计划 |
| POST | /agent/plans/{id}/resume | 恢复并重新评估权限/约束 |
| POST | /agent/plans/{id}/replan | {message}；新版本、保留已核验步骤、旧审批失效 |
| GET | /banking/accounts | 本人账户及余额 |
| GET | /banking/accounts/{id}/{resource} | resource 为 balance、transactions、analyze_bills、subscriptions、commitments、recipients |
| POST | /banking/execute | BankingCommand；返回 {receipt,plan}，未授权时 receipt 为 null，plan 等待授权 |
| GET | /banking/receipts/{id} | 本人规范回执 |
| GET | /banking/receipts/{id}/verify | 查询持久化回执、动作绑定及分录，返回 {verified,receipt_id,source,checked_at,receipt} |
| GET | /banking/reconciliation | 本人余额与期初/分录一致性 |
| GET | /banking/commitment-graph | 精简账户、承诺节点与预留边 |
| POST | /banking/schedules/prepare-due | 幂等生成到期授权计划，不扣款；后台也每15秒扫描 |
| POST | /policy/evaluate | {plan_id,step_id}；根据后端事实返回 level、reason、spent_today_cents、可选约束快照，不等于授权 |
| GET | /policy/approvals | 本人审批列表 |
| POST | /policy/approvals/{id}/challenge | 红级申请2分钟模拟挑战，返回演示码，绝非真实 MFA |
| POST | /policy/approvals/{id}/decision | {decision:approve或reject,challenge_code?}；红级需正确挑战，3次错误拒绝 |
| GET | /audit | 本人审计事件与全局哈希链一致性布尔值 |

全部精确字段、必填约束与示例结构见生成的 JSON Schema/OpenAPI。计划审批有效期10分钟。交易后端在真正执行前重判日累计，原黄级批准不会绕过升级后的红级强验证。

## 候选示例

```json
{"title":"取消会员后转账","minimum_balance_cents":100000,"steps":[{"step_id":"cancel","depends_on":[],"action":{"tool":"cancel_subscription","account_id":"acct-alice","subscription_id":"sub-video"}},{"step_id":"pay","depends_on":["cancel"],"action":{"tool":"transfer","account_id":"acct-alice","recipient_id":"rcp-zhang","amount_cents":50000}}]}
```

执行时 action 使用已保存的完整值，包括默认字段；幂等键固定为 plan_id:v版本:step_id。请先 GET 计划再构造 BankingCommand，不能把不同参数配同一授权。普通前端应使用 /run 与 /resume，由编排器构造执行命令。

## 工具动作

读取工具：balance、transactions、analyze_bills、subscriptions、commitments、recipients。读取 action 为 {tool,account_id,period?}，period 默认 month，账单分析可用30d。

transfer 为 {tool,account_id,recipient_id,amount_cents,commitment_id?}。schedule_transfer 另需未来且含时区的 due_at。cancel_subscription 为 {tool,account_id,subscription_id}。

定时登记回执 status=scheduled、paid=false，登记不等于付款。成功付款回执 status=succeeded 且有 transaction_id。Agent 只有查验 verified=true 后才能将步骤标为 succeeded。
