# 任务状态协议

| 当前状态 | 允许转移 | 触发条件与责任方 |
| --- | --- | --- |
| planned | executing / waiting_approval / paused / failed | 后端检查依赖、权限和约束，用户可暂停 |
| waiting_approval | executing / paused / failed | 对应审批通过后恢复；拒绝后运行转 failed；过期生成新的待审批请求 |
| executing | succeeded / failed / waiting_approval / planned | 银行变账与查询核验结果决定；后续步骤可再遇审批门 |
| paused | planned | 显式 resume 后重新评估，不沿用过期权限 |
| failed | planned（新版本） | 只能通过 replan 创建新版本，保留已核验完成步骤 |
| succeeded | 无 | 完成计划保持终态，新请求创建新计划 |
| waiting_clarification | planned（新版本）/ handed_off | 同名或未知收款人不发付款授权；选择本人候选后生成新版本 |
| pending_verification | planned / succeeded / handed_off | 原操作可能已发生；只能核验原回执，不能重付或重规划。核验通过不自动执行后续动作 |
| partially_completed | planned（新版本）/ handed_off | 明确失败前已有成功步骤；保留真实回执，不自动逆向转账 |
| handed_off | paused / pending_verification / partially_completed / failed / succeeded | 仅持有人显式交还；结果只能来自银行核验，不能手填成功 |

TaskStep 的 succeeded 表示银行后端回执已查询并核验。TaskPlan 的 succeeded 表示全部步骤完成，但其中 schedule_transfer 的业务结果是已登记、未付款，必须查看 ExecutionReceipt.status，不得将计划完成误解为资金已划出。

审批状态：pending、approved、rejected、consumed、expired。approved 只表示用户完成该请求的授权，执行后端仍需重查；实际执行与 consumed 在同一事务提交。rejected 不自动重试。计划版本、动作哈希、主体、步骤或风险级别改变时，旧授权不再适用。

暂停不撤销已经完成的交易，同步事务中不提供抢占式中断。任务历史与回执跨重启保留；计划重规划不会自动执行反向转账来补偿前序已完成步骤。

0.2补充：executing核验超时/失败转pending_verification；明确失败且已有成功步骤时转partially_completed。progress按completed/failed/pending_verification/remaining分别统计。暂停和接管均作废旧审批；handed_off不能通过/run、/resume、/execute或/replan绕过。人工处理只记录说明、查询原交易和交还，不提供强制成功或改账接口。

旧表为0.1基本路径，新增路径以本段及新增行补充。接管前可以为planned、waiting_approval、waiting_clarification、paused、pending_verification、failed或partially_completed；接管期间核验可更新步骤，但计划仍保持handed_off直到显式交还。
