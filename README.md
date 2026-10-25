# PACT V2.0

Proactive Agent for Commitments & Transactions：仅用合成数据的银行Agent MVP，支持智能转账、账单分析、订阅/代扣管理，以及可复用DAG、审批、冲突选择和后端回执核验。

仓库统一以 **main** 为集成入口。源代码、共享协议、工作台和当前文档保存在同一分支；过期开工稿、旧截图和旧PPT已移除，历史变更可查Git与PR记录。

## 启动

源码需要Python 3.12+、Node 24+，首次准备依赖需联网：

```bash
git clone --branch main https://github.com/ThreshoLdnnis/pact-v2.git
cd pact-v2
python scripts/bootstrap.py
```

随后Windows运行 `start-pact.cmd`，Linux/macOS运行 `sh start-pact.sh`。访问 **http://127.0.0.1:8000**，选择Alice，默认演示PIN **246810**。开发前端端口5173；其余模块在同一8000服务中运行，没有8001/8002独立服务。

安装Docker后也可运行 `docker compose up --build -d`。本地交付ZIP包含已构建前端和Windows x64 / CPython3.12离线依赖；这些运行环境文件不存入Git仓库。

## 模型

默认rules是有限语法演示解析器。支持外部OpenAI兼容接口与Ollama。复制 `.env.example` 为本机 `.env` 后填写地址、模型与密钥，重启生效。

本机DeepSeek已通过“查余额”和三业务组合的两项真实候选联测；广泛语义质量仍待评测。模型只能生成候选计划，不能授权、付款或报告未经核验的交易。[配置方法](docs/MODEL_PROVIDERS.md)

## 演示

输入“分析账单、取消视频会员、再给张三转账500元”。账单分析与订阅查询可独立推进，查询确认后取消，转账等待账单与取消结果核验。订阅查询、取消与小额付款分别确认；上海自然日转出累计含本笔超过1000元需模拟强验证。

随后可分别演示“那个改成300”（唯一目标更正，歧义先澄清）、“算了，留着吧”（停止取消并暂停依赖付款）、“帮我省点钱”（只分析和建议）。资金竞争或保留/取消矛盾由用户选择，不默认FIFO；中断保留已发生事实，不自动退款或恢复已取消会员。

## 验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest --junitxml=reports/tests.xml
python scripts/export_contracts.py
python scripts/check_repository.py
cd apps/workbench
npm ci
npm run build
```

现有业务基准为158项自动化测试、20组真实HTTP场景、Windows独立离线部署及重启恢复。[CI](https://github.com/ThreshoLdnnis/pact-v2/actions)运行仓库检查、测试/构建/依赖检查和Docker内四组HTTP脚本；JUnit与依赖扫描结果保存在CI artifacts，避免重复提交生成文件。[验收口径](docs/MVP_ACCEPTANCE.md)

## 文档

| 需要了解 | 文档 |
| --- | --- |
| 模块与可信执行边界 | [架构](docs/ARCHITECTURE.md) |
| 三业务模板与组合顺序 | [业务DAG](docs/BUSINESS_DAGS.md) |
| 多请求、上下文、中断 | [上下文与协调](docs/CONTEXT_COORDINATION.md) |
| 对象、HTTP与状态 | [API](docs/API.md)、[状态协议](docs/STATE_MACHINE.md) |
| 启动、模型和恢复 | [部署](docs/DEPLOYMENT.md)、[模型](docs/MODEL_PROVIDERS.md) |
| 重置、故障与独立验收 | [沙箱测试](docs/SANDBOX_TESTING.md)、[测试目录](tests/README.md) |
| 答辩与安全证据 | [讲稿](docs/DEFENSE.md)、[安全自评](docs/SECURITY_SELF_ASSESSMENT.md)、[报告索引](reports/README.md) |
| 团队与共享接口变更 | [协作](CONTRIBUTING.md)、[变更模板](docs/INTERFACE_CHANGES.md) |

仅合成账户、模拟认证和模拟交易；单进程SQLite、本地审计链及演示验证码不代表完整银行系统或生产合规认证。浏览器点击、广泛模型语义评测和最终赛事提交规则仍有待验收，统一跟踪于[Issue #11](https://github.com/ThreshoLdnnis/pact-v2/issues/11)。团队交付目标2026-11-02来自用户要求。
