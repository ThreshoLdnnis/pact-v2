# 开工工作项

阶段更新：用户已明确要求完整实施、不再按分工限制本次工作。当前MVP实现与证据见README、docs/ARCHITECTURE.md、docs/SECURITY_SELF_ASSESSMENT.md和reports/。下表保留原始四人任务边界，便于后续协作，不表示模块仍未实现。

这里只准备任务边界，不代替成员开展全部实现。共享协议未评审前，各模块可以做本地探索，但不要把自行假设的公共接口合入主干。

GitHub 已建立：[共享评审 #1](https://github.com/ThreshoLdnnis/pact-v2/issues/1)、[A #2](https://github.com/ThreshoLdnnis/pact-v2/issues/2)、[B #3](https://github.com/ThreshoLdnnis/pact-v2/issues/3)、[C #4](https://github.com/ThreshoLdnnis/pact-v2/issues/4)、[D #5](https://github.com/ThreshoLdnnis/pact-v2/issues/5)。#1/#2 已分配 A；B/C 邀请已发送但待本人接受，D 待账号，因此 #3/#4/#5 暂不设 GitHub assignee，正文保留明确角色。

| 工作项 | 主负责人 | 协作方 | 验收 |
| --- | --- | --- | --- |
| 共享协议与端口首次评审 | A | B/C/D | 五类对象、Banking Tool API、错误码、金额/时区/累计口径与审批绑定达成一致；群同步有记录；协议 PR 合并 |
| A 开工：候选计划与 DAG 边界 | A | B/C | 明确输入输出和恢复状态；列出解析/校验/DAG 验收用例；随后由 A 自行实施 |
| B 开工：沙箱与账务边界 | B 杨曦 | A/C/D | 明确数据模型、执行事务、幂等和回执协议；随后由 B 自行实施 |
| C 开工：权限与安全边界 | C 郭宇哲 | A/B/D | 明确三级规则、审批/模拟强验证、审计和评测清单；随后由 C 自行实施 |
| D 开工：工作台与联调边界 | D 吴晓亦 | A/B/C | 补账号；确认工作台状态、配置、端口与启动约定；随后由 D 自行实施 |

建议工作顺序：仓库与成员接入 → 共享协议评审 → 四人按目录并行开发 → 第一个转账闭环联调 → 账单/订阅与跨场景联动 → 安全评测与交付材料。

团队内部交付目标为 2026-11-02；此日期来源于用户要求，不冒充赛事官方截止时间。
