# 状态协议 0.4

| 状态 | 含义与出口 |
| --- | --- |
| planned | 候选已由后端编译，尚未代表授权；run后检查依赖、冲突、归属、权限与资金 |
| waiting_clarification | 收款人或上下文不唯一；本人选择有效目标后更新版本，仍需权限检查 |
| waiting_conflict | 请求不能共同满足；允许独立绿色工作，变更与黄色查询冻结；本人决策后选中任务planned，其余paused |
| waiting_approval | 等待当前动作绑定的确认或模拟强验证；过期/风险变化重新确认 |
| executing | 同一数据库事务执行动作并查询核验；不是可持久外部付款成功证明 |
| pending_verification | 原操作可能发生；只查询原规范回执，冻结后续，不允许重付或重规划；核验通过后显式续跑 |
| paused | 用户暂停或依赖停止；普通resume重新检查，含被取消前置时需重规划 |
| cancelled | 未执行目标已停止；不能run/resume复活，需要新版本重规划 |
| partially_completed | 已有成功事实，后续失败/被停止；保留回执，重规划只处理未完成部分 |
| failed | 确定失败且无成功步骤；需重规划新版本 |
| succeeded | 所有步骤有核验结果；不意味着scheduled登记已付款 |
| handed_off | 人工接管冻结自动执行；原回执可核验，显式交还后按事实回到paused/待核验/完成等状态 |

TaskStep.succeeded只由银行回执核验产生。TaskPlan.succeeded表示该计划列出的步骤完成：schedule_transfer的ExecutionReceipt.status=scheduled、paid=false，不能显示为付款已成功。

TaskPlan保存conflict_ids、activated_until和interruption；这些由后端写入，CandidatePlan不可提供。progress统计completed/failed/pending_verification/remaining/cancelled。ready_step_ids只表示依赖满足，不代表通过授权；冲突、暂停和人工接管期间不能作为执行许可。

审批状态pending/approved/rejected/consumed/expired。审批绑定主体、计划、版本、步骤、动作哈希、依赖及最低留存；10分钟有效。消费与银行变更同事务。风险升级、修改、暂停、冲突和接管使旧授权失效；拒绝不会自动继续。

状态汇总优先保留人工接管与待核验事实，再处理中断/冲突，最后根据步骤完成、失败及等待情况展示。中断保留已完成交易；未知状态不当失败处理；不可用自由文本把回执改成成功。同步提交事务不支持抢占式终止。
