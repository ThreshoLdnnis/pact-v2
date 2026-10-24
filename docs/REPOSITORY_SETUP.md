# 仓库配置记录

本文记录准备阶段快照。完整MVP已经接续实现，当前运行、协议和验证状态以README及reports/为准。主干保护的套餐限制仍然存在。

更新日期：2026-10-24。这个文件区分目标配置与实际核验，不能把待办当作已开启。

## 目标配置

- 私有仓库：`ThreshoLdnnis/pact-v2`；默认分支 `main`。
- 只启用 squash merge；合并后自动删除任务分支。
- `main` 要求 PR、至少 1 名非作者批准、处理审核讨论、`repo-checks` 通过；禁止强推/删除。账户套餐支持时在平台强制执行。
- Actions 最小权限：工作流声明 `contents: read`；不使用 `pull_request_target` 执行外来代码。
- A 为仓库所有者；B/C 接受协作者邀请后核验写权限；D 待用户名。
- CODEOWNERS 只有核验有效权限的用户才启用具体路径规则。

## 实际核验

| 项目 | 状态 |
| --- | --- |
| 本地仓库基础文件 | 已准备；JSON 格式、Markdown 本地链接与暂存空白检查通过 |
| 远程仓库 | 已创建私有仓库；25 个准备文件已上传至 chore/team-setup，见 [PR #6](https://github.com/ThreshoLdnnis/pact-v2/pull/6)；待非作者审核合并 |
| 默认分支 | 已核验为 main |
| 合并选项 | 已核验：仅 squash，自动删除已合并分支 |
| 主干保护 | GitHub 页面明确提示当前私有仓库规则不会强制生效；未宣告启用 |
| CI 首次运行 | [Repository checks 第 1 次运行](https://github.com/ThreshoLdnnis/pact-v2/actions/runs/40064768137) 成功；仅代表仓库格式检查通过 |
| A / ThreshoLdnnis | 用户确认负责 A |
| B / Clement-xi | 已发送邀请，GitHub 页面显示 Pending Invite；待本人接受 |
| C / morebadly | 已发送邀请，GitHub 页面显示 Pending Invite；待本人接受 |
| D / 吴晓亦 | 待 GitHub 用户名 |
| GitHub Issues | 已创建 #1 共享评审、#2 A、#3 B、#4 C、#5 D；#1/#2 已分配 A，其余待成员接入 |

## 接入与同步说明

1. GitHub 邮箱二次验证已通过，B/C 邀请已发出；成员接受后核验写权限，再启用具体 CODEOWNERS 规则并分配 Issue。
2. 经用户明确同意，现有 ChatGPT Codex Connector 的“仅选定仓库”范围仅新增 pact-v2；原有选定项保留。连接器已成功读取此私有仓库并核验权限。
3. 本机 Git 尚无可用的非交互式凭据；本批上传通过已授权连接器完成。成员在各自本机用标准 GitHub 登录后克隆，不共享 Token。
4. 本地工作分支为 `chore/team-setup`，已按 GitHub 对象哈希核验并同步远程准备分支；早期本地根提交保留在 `local/bootstrap-backup`。PR 基于远程初始提交，未强推 main。成员接受邀请后可克隆此准备分支参与评审；合并后从最新 main 开始自己的任务分支。

```bash
git clone --branch chore/team-setup https://github.com/ThreshoLdnnis/pact-v2.git
```

## 平台限制说明

GitHub 官方说明：私有仓库的分支保护需要相应套餐。若账户不支持，保留私有可见性并记录限制，不自动开通付费计划或改为公开。团队仍按 PR 审核约定协作。

参考：[受保护分支](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[CODEOWNERS 与写权限](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)、[工作流权限](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。
