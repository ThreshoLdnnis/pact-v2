当前协议0.4，本轮在本地实现，尚未团队群同步冻结；本轮提交草稿PR #8评审。完整精确字段以contracts/openapi.json和task-protocol.schema.json为准。

# PACT 协议 0.4 与 API

状态：可运行的评审实现，尚未群同步/冻结。代码唯一来源为 contracts/models.py。运行 python scripts/export_contracts.py 生成完整 OpenAPI、Banking Tool OpenAPI、Task Protocol JSON Schema 和前端 protocol.ts。

## 通用规则

- 基础路径 /api/v1，业务接口需 Authorization: Bearer <演示会话令牌>；/auth/demo-session、/meta、/health为公开演示入口；/sandbox/*需要独立X-Sandbox-Admin，不接受普通会话替代。
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
| TaskStep | step_id, depends_on, action, status, risk_level, approval_id, receipt_id, result, error, clarification | 候选只能提供前三项，运行字段由后端生成 |
| ApprovalRequest | approval_id, plan_id, plan_version, step_id, action_hash, level, status, expires_at, action | Policy 后端 |
| ExecutionReceipt | receipt_id, plan_id, plan_version, step_id, action_hash, operation, status, transaction_id, data, created_at | Banking 后端 |
| BankingCommand | plan_id, plan_version, step_id, idempotency_key, action | 调用方提交，后端与已保存步骤逐字段比对 |

0.3增加TaskStep的template_id、template_instance_id、template_version（仅服务端生成），以及TaskPlan.ready_step_ids（依赖满足的节点，不表示已经授权）。CandidatePlan仍拒绝运行字段和安全字段。取消动作会自动补齐查询节点，因此步骤数量和确认次数与0.2不同。

组合接口示例：两个独立前置业务、转账等待二者核验。每个instance的step_id也是该业务模板的出口；内部查询节点由服务端补齐，不由调用方删除。

```json
{
  "title": "分析账单、取消视频会员、再给张三转账500元",
  "instances": [
    {"instance_id": "bills", "template_id": "bill_analysis", "action": {"tool": "analyze_bills", "account_id": "acct-alice"}},
    {"instance_id": "membership", "template_id": "subscription_management", "action": {"tool": "cancel_subscription", "account_id": "acct-alice", "subscription_id": "sub-video"}},
    {"instance_id": "payment", "template_id": "smart_transfer", "depends_on": ["bills", "membership"], "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_query": "张三", "amount_cents": 50000}}
  ]
}
```

测试管理API见[SANDBOX_TESTING.md](SANDBOX_TESTING.md)。它们不属于Banking Tool API，不得交给模型。审批scope_hash自0.3开始同时绑定depends_on；旧未消费授权在执行时按新绑定检查，不会自动继承。

## 路由目录

| 方法 | 路径 | 请求/结果 |
| --- | --- | --- |
| POST | /auth/demo-session | {user_id:alice或bob,pin}；返回8小时会话令牌，仅保存令牌哈希 |
| POST | /auth/logout | 撤销当前会话 |
| POST | /agent/plans | {message}；生成 TaskPlan，不自动付款 |
| POST | /agent/candidates | 严格 CandidatePlan；校验 DAG、资源归属后保存 |
| GET | /agent/templates | 三个业务模板、版本、强制关口 |
| POST | /agent/compositions | CompositionInput；校验模板类型、别名依赖并展开成TaskPlan |
| GET | /agent/plans | 当前用户计划列表 |
| GET | /agent/plans/{id} | 当前持久化 TaskPlan |
| POST | /agent/plans/{id}/run | 执行到完成、失败或待授权，返回 TaskPlan |
| POST | /agent/plans/{id}/pause | 暂停非终态计划 |
| POST | /agent/plans/{id}/resume | 恢复并重新评估权限/约束 |
| POST | /agent/plans/{id}/replan | {message}；新版本、保留已核验步骤、旧审批失效 |
| POST | /agent/plans/{id}/select-recipient | {plan_version,step_id,clarification_id,recipient_id}；只能选择本人当前候选，产生新版本，仍需付款授权 |
| POST | /agent/plans/{id}/reconcile | 只查询原回执；返回TaskPlan，不变账、不继续后续动作 |
| POST | /agent/plans/{id}/handoff | {plan_version,reason}；持久化人工接管并废止旧审批 |
| POST | /agent/plans/{id}/handoff/release | {plan_version,note}；交还后仍需核验或重新授权，不能伪造执行结果 |
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

读取工具：balance、transactions、analyze_bills、subscriptions、commitments、recipients。读取 action 为 {tool,account_id,period?}，period 默认 month，账单分析可用30d。**subscriptions是黄色查询，其他上述读取为绿色。**

transfer 为 {tool,account_id,recipient_id或recipient_query,amount_cents,commitment_id?}。recipient_id与recipient_query必须且只能提供一个。姓名在后端名册中解析；同名等待澄清，模型不能擅选。schedule_transfer 另需未来且含时区的 due_at。cancel_subscription 为 {tool,account_id,subscription_id}。

定时登记回执 status=scheduled、paid=false，登记不等于付款。成功付款回执 status=succeeded 且有 transaction_id。Agent 只有查验 verified=true 后才能将步骤标为 succeeded。

## 0.2行为变化与兼容

- 0.2时新写入TaskPlan.schema_version=0.2；读取接受0.1历史计划。TaskPlan增加progress及handoff；TaskStep增加clarification；ApprovalRequest增加scope_hash，绑定主体、版本、步骤、动作和最低留存。旧缺失scope_hash的审批需重新发起，不能沿用。
- GET /banking/accounts/{id}/subscriptions未提供receipt_id时403。提供本人/本账户、确有已消费黄色确认的查询回执时，只返回原查询快照（source_receipt_id、snapshot_at），不返回实时数据。新的查询仍走subscriptions候选→确认→执行。旧绿色回执、其他工具回执不适用。
- 绿色commitments接口隐藏单项订阅协议详情，增加subscription_reserved_cents；commitment-graph仅显示合计节点。银行内部约束仍包含完整预留。取消仅释放未到期承诺，不作历史退款。
- 账单结果增加transaction_ids和anomalies；当前非转账消费≥3000元只是待核查提示。
- 新状态waiting_clarification、pending_verification、partially_completed、handed_off见STATE_MACHINE.md。执行响应receipt=null也可能表示待澄清/待核验，请检查plan.status。
- 此前客户端需更新枚举、订阅读取和人工处理交互；/api/v1路径保留不等于冻结的0.1客户端完全兼容。生成协议与工作台已一起更新，尚未完成团队群确认。
- 本次未改变跨场景动作顺序、依赖或跨DAG冲突调度。明确的新业务边界见BUSINESS_DAGS.md。

## 0.4消息、冲突与中断

所有路径均以/api/v1为前缀、使用本人Bearer会话，错误{error:{code,message,details?}}。

| 方法/路径 | 请求及语义 |
| --- | --- |
| POST /agent/messages | ConversationInput：request_id、message；可选conversation_id、focus_plan_id/version、focus_step_id、focus_field。返回ConversationResponse（outcome/message/plan/clarification/recommendations）。同编号同输入复用，异参409 |
| GET /agent/conversations/{id} | 本人持久化turns（最多100）、clarifications和关联plan_ids |
| POST /agent/clarifications/{id}/decision | {option_id}；本人/版本/10分钟有效期绑定，不能提交自由执行参数 |
| GET /agent/conflicts | 本人冲突列表items，open项需选择 |
| POST /agent/conflicts/{id}/decision | {choice:execute_plan,selected_plan_id}或{choice:keep_subscription/pause_all}；不执行业务 |
| GET /agent/intent-preferences | 本人明确保留意图，无实时订阅金额或协议快照 |
| POST /agent/plans/{id}/interrupt | {plan_version,reason,step_id?}；停止未执行部分，返回含interruption的TaskPlan |

TaskPlan.schema_version=0.4，读取兼容0.1/0.2/0.3；新增waiting_conflict、cancelled，progress.cancelled，conflict_ids、activated_until及InterruptionReview。planner增加openai_compatible。运行元数据全部由服务端写入，CandidatePlan不接受这些字段。更正产生新版本；停止依赖后需重规划，不能用resume复活。

同一个/agent/messages响应只表达该消息处理结果，后续任务变化应GET最新计划；重放旧消息不代表返回的是实时任务状态。/banking/execute与/run使用同一协调与授权边界，不能换入口绕过冲突。
