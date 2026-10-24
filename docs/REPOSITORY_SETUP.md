# 仓库配置记录

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
| 远程仓库 | 已创建私有仓库；准备材料通过独立准备分支/PR 提交，合并前 main 保留初始 README |
| 默认分支 | 已核验为 main |
| 合并选项 | 已核验：仅 squash，自动删除已合并分支 |
| 主干保护 | GitHub 页面明确提示当前私有仓库规则不会强制生效；未宣告启用 |
| CI 首次运行 | 准备 PR 建立后核验 GitHub Actions；工作流仅作仓库格式检查 |
| A / ThreshoLdnnis | 用户确认负责 A |
| B / Clement-xi | 已发送邀请，GitHub 页面显示 Pending Invite；待本人接受 |
| C / morebadly | 已发送邀请，GitHub 页面显示 Pending Invite；待本人接受 |
| D / 吴晓亦 | 待 GitHub 用户名 |
| GitHub Issues | 已创建 #1 共享评审、#2 A、#3 B、#4 C、#5 D；#1/#2 已分配 A，其余待成员接入 |

## 接入与同步说明

1. GitHub 邮箱二次验证已通过，B/C 邀请已发出；成员接受后核验写权限，再启用具体 CODEOWNERS 规则并分配 Issue。
2. 经用户明确同意，现有 ChatGPT Codex Connector 的“仅选定仓库”范围仅新增 pact-v2；原有选定项保留。连接器已成功读取此私有仓库并核验权限。
3. 本机 Git 尚无可用的非交互式凭据；本批上传通过已授权连接器完成。成员在各自本机用标准 GitHub 登录后克隆，不共享 Token。
4. 准备分支名为 `chore/team-setup`，以 GitHub 远程初始提交为父提交建立 PR，未强推 main。若使用早期本地准备副本，在配置好本机 Git 登录后应先拉取并切换到远程准备分支，不要将未同步的本地根提交直接推到 main。

## 平台限制说明

GitHub 官方说明：私有仓库的分支保护需要相应套餐。若账户不支持，保留私有可见性并记录限制，不自动开通付费计划或改为公开。团队仍按 PR 审核约定协作。

参考：[受保护分支](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[CODEOWNERS 与写权限](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)、[工作流权限](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。
