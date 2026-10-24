# PACT V2.0

Proactive Agent for Commitments & Transactions

可运行的银行 Agent 沙箱 MVP。支持智能转账、账单分析、订阅/代扣管理和跨场景 DAG，使用合成账户，不连接真实银行。

## 立即运行

**Windows 部署包**：解压后双击 `start-pact.cmd`。首次运行自动创建项目内 Python 环境、安装锁定依赖。部署包包含已构建前端，无需 Node。需要 Python 3.12+，或本机已有的 Codex Python 运行时。首次安装依赖需要网络。

浏览器访问 **http://127.0.0.1:8000**，选择 Alice，默认演示 PIN **246810**。

**Docker Compose**（需要已安装 Docker）：

```bash
docker compose up --build -d
# 工作台 http://127.0.0.1:8000
# API 文档 http://127.0.0.1:8000/docs
# 停止并保留合成数据
docker compose down
```

**源码开发**（Python 3.12+，Node 24+）：

```bash
python -m venv .venv
# Windows 使用 .venv\Scripts\python.exe，其他平台使用 .venv/bin/python
.venv/bin/python -m pip install -r requirements-dev.txt
cd apps/workbench
npm ci
npm run build
cd ../..
.venv/bin/python -m uvicorn pact.app:create_app --factory --host 127.0.0.1 --port 8000
```

也可以运行 `python scripts/bootstrap.py` 自动准备项目。开发前端可在另一个终端运行 `npm run dev`，5173 会将 API 请求代理到 8000。

## 三分钟演示

1. 输入：**分析本月账单，取消视频会员，再给张三转账500元，至少保留1000元**。
2. 账单分析自动完成。确认取消视频会员，再确认转账；每个授权只绑定当前步骤和参数。
3. 点击步骤下的回执，查看 `verified: true` 与真实模拟交易引用。
4. 新建“给张三转账1001元”，申请模拟验证码，手动填写后继续。强验证明确标为演示。
5. 打开“资金承诺”，查看房租、下次订阅扣款对可用金额的影响。
6. 演示失败重规划：请求“分析账单，给张三转账99999元”，强验证后触发资金约束失败，再以“分析账单，给张三转账50元”重规划。已核验账单步骤保留。

默认规划器是有限语法的规则演示器。可选本地 Ollama 适配器使用 JSON Schema 生成候选，再由相同后端严格校验。真实模型推理尚未在本环境连测，不能把规则演示的结果当作模型能力评测。

## 已实现的执行边界

- Pydantic 是协议唯一来源，导出 JSON Schema、OpenAPI 与前端 TypeScript 类型。
- 独立 Policy Engine 决定绿/黄/红，模型不能提供风险等级、审批状态或交易结果。
- 只读自动；用户上海自然日转出累计含本笔 ≤1000 元需确认；>1000 元需模拟强验证。取消订阅需确认。未实现的挂失等工具拒绝执行。
- 后端在同一个 SQLite 写事务中重新校验审批绑定、日累计、最低留存和未来承诺，完成双边分录、余额更新、审批消费及回执保存。
- 幂等键和步骤执行身份均唯一。同键异参/改版本拒绝，重复请求复用已核验回执。
- 计划、审批、回执与会话持久化。暂停/恢复和重规划保留已完成步骤，旧审批失效。
- 定时转账先预留承诺并返回 `scheduled`，每 15 秒检查到期并生成新审批任务，到期重新授权后付款。
- 连续 3 次执行异常触发 60 秒熔断。审计哈希链、账户对账与回执查询提供核验入口。

## 目录与协议

| 路径 | 内容 |
| --- | --- |
| `services/agent/` | 候选规划、DAG、暂停恢复、重规划 |
| `services/banking/` | 合成银行数据、账务、幂等、回执 |
| `services/policy/` | 三级决策与资金约束纯逻辑 |
| `pact/` | API、身份演示、持久化与审计 |
| `contracts/` | Python 模型、生成的 JSON Schema/OpenAPI |
| `apps/workbench/` | React/TypeScript 工作台 |
| `tests/` | 端到端、并发和安全场景 |
| `reports/` | 实际测试、扫描、HTTP 验收与界面证据 |

- [技术架构](docs/ARCHITECTURE.md)
- [API 与协议](docs/API.md)
- [状态流转](docs/STATE_MACHINE.md)
- [部署与恢复](docs/DEPLOYMENT.md)
- [安全自评报告](docs/SECURITY_SELF_ASSESSMENT.md)
- [答辩讲稿与演示顺序](docs/DEFENSE.md)
- [接口变更与群同步模板](docs/INTERFACE_CHANGES.md)

## 验证

```bash
python -m pytest --junitxml=reports/tests.xml
python scripts/export_contracts.py
cd apps/workbench
npm run build
npm audit
```

实际验证结果和未验证项见安全自评。扫描零已知漏洞仅表示此次查询结果，不是安全认证。

## 使用限制

此版本是本地单进程模块化 MVP。演示 PIN/身份切换不是生产登录，模拟验证码不是真实 MFA，审计链没有外部防篡改锚点。仅面向合成数据和本机/容器内演示。[CI](https://github.com/ThreshoLdnnis/pact-v2/actions/runs/40069404218) 已通过Docker构建、Compose启动与真实HTTP烟测，本机没有Docker。不要将服务公开部署或接入真实金融数据。

金额统一使用整数分，自然日采用 Asia/Shanghai，存储时间采用带时区 UTC ISO 8601。共享接口版本为 0.1 评审实现，尚未完成团队群同步与协议冻结，不宣称已通过赛事验收。

团队交付目标为 2026-11-02，来源于用户要求。赛事规则与提交格式仍需对照团队取得的官方文件核验。未选择开源许可证。
