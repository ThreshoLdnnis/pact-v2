# PACT V2.0

Proactive Agent for Commitments & Transactions

面向 2026 FinTechathon 国内 AI Banking Agent 赛道的四人协作项目。团队目标：2026-11-02 前完成可运行 MVP、技术文档、答辩材料、源码部署包与安全自评报告。

**当前阶段：分工前工程准备。尚未实现银行业务、Agent 或前端。** 本提交提供协作骨架和待评审接口目录，不代表已完成 MVP，也不代表接口已经冻结。赛事细则与报名/提交要求以团队取得的官方文件为准。

## 团队与目录

| 角色 | 负责人 | GitHub | 主要目录 | 责任边界 |
| --- | --- | --- | --- | --- |
| A | 仓库所有者（用户本人） | [ThreshoLdnnis](https://github.com/ThreshoLdnnis) | `services/agent/` | 意图解析、候选 TaskPlan、DAG、暂停恢复、重规划 |
| B | 杨曦 | [Clement-xi](https://github.com/Clement-xi) | `services/banking/` | FastAPI + SQLAlchemy 沙箱、账户与流水、转账、幂等与原子账务 |
| C | 郭宇哲 | [morebadly](https://github.com/morebadly) | `services/policy/`、`tests/security/` | 独立策略判断、审批/强验证、后端授权约束、审计、安全评测 |
| D | 吴晓亦 | 待补充 | `apps/workbench/`、`infra/` | React/TypeScript 工作台、部署、联调与交付集成 |

共享目录 `contracts/` 由 A/B/C/D 共同评审，不能由任一模块单方面修改。详细边界见 [团队协作约定](CONTRIBUTING.md)。

## 每个人开始前

1. 接受仓库邀请，确认自己能访问私有仓库；D 先补充 GitHub 用户名。
2. 克隆仓库，阅读本文件、[协作约定](CONTRIBUTING.md)、[接口变更规则](docs/INTERFACE_CHANGES.md)。
3. 参加共享协议首次评审，核对 [接口草案](contracts/README.md) 与 [端口登记](docs/PORTS.md)。
4. 在对应 Issue 中确认范围与验收标准，从最新 `main` 建自己的任务分支。
5. 通过 PR 合并；不直接向 `main` 推送业务变更。

```bash
git clone https://github.com/ThreshoLdnnis/pact-v2.git
cd pact-v2
git switch -c feat/a-issue-N-short-topic
```

`N` 替换为真实 Issue 编号，A/B/C/D 均采用同一分支命名规则。各成员自行在本机设置自己的 Git 提交身份；不要复制他人邮箱或共享 Token。

## 共同实施边界

- 初赛只做智能转账、账单分析、订阅/代扣管理，并验证跨场景 DAG 联动。
- 大模型只生成候选计划。权限与账务由银行后端强制执行；成功结论必须来自后端核验的回执。
- Financial Constraint Engine / 精简 Commitment Graph 只聚焦最低留存余额、未来资金承诺和失败后的约束重评估。
- 使用合成数据，不连接真实银行，不提交真实客户数据、密钥或个人金融信息。
- 绿/黄/红权限边界按用户提供要求准备，具体计量口径在首次协议评审中确定并与官方文件核对。
- 暂不开发复杂 APP UI、拟人化或大规模人生记忆。

## 准备材料

- [仓库配置与当前状态](docs/REPOSITORY_SETUP.md)
- [首批工作项与依赖](docs/KICKOFF.md)
- [共享协议评审草案](contracts/README.md)
- [接口变更流程与群同步模板](docs/INTERFACE_CHANGES.md)
- [开发端口登记](docs/PORTS.md)
- [安全边界](SECURITY.md)

当前 CI 只检查仓库基础资料格式与提交空白问题，不是业务测试或安全认证。模块测试、集成测试与 Docker Compose 由对应负责人在各自 Issue/PR 中实现。

本阶段未选择开源许可证；对外开源与发布由团队另行决定。
