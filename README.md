# PACT V2.0

Proactive Agent for Commitments & Transactions

当前为 **0.4 本地验收版**。智能转账、账单分析、订阅/代扣管理复用业务 DAG 模板，完成组合执行、用户冲突选择、上下文更正、审批与回执闭环。仅使用合成账户，不连接真实银行。2026-10-25用户已授权整理GitHub，本轮通过feat/pact-mvp与草稿PR #8提交评审；不自动合并main或冻结共享接口。

## 立即运行

解压 `PACT-V2-MVP-0.4.zip`，Windows 双击 `start-pact.cmd`，访问 **http://127.0.0.1:8000**，选择 Alice，演示 PIN **246810**。

部署包含已构建工作台与 Windows x64 / CPython 3.12 的离线依赖；该环境首次安装无需联网、Node 或 Codex。需要本机安装 Python 3.12。Python 其他版本（3.12以上）、Linux/macOS 使用锁定 requirements.txt 在线安装，随后可运行 `sh start-pact.sh`。本轮实际完成 Windows 干净目录、独立环境、断网安装、HTTP 与重启验收，详见 [验收清单](docs/MVP_ACCEPTANCE.md)。

也支持 `docker compose up --build -d`。本机无Docker；0.4已在[GitHub CI](https://github.com/ThreshoLdnnis/pact-v2/actions/runs/40113574011)完成Docker构建、启动及20组HTTP场景，见reports/ci-verification-0.4.json。

## 从GitHub获取源码

团队在本轮评审分支开发，main尚未合并。需要Python 3.12+、Node 24+：

```bash
git clone --branch feat/pact-mvp https://github.com/ThreshoLdnnis/pact-v2.git
cd pact-v2
python scripts/bootstrap.py
```

然后Windows运行 `start-pact.cmd`，Linux/macOS运行 `sh start-pact.sh`，访问127.0.0.1:8000。源码首次安装和前端构建需要联网；Windows离线依赖只随本地交付ZIP提供，未把运行环境或密钥放进Git仓库。

## 六分钟演示

1. 输入“分析账单、取消视频会员、再给张三转账500元”。展示四个执行节点：账单分析，与订阅查询→取消；转账等待账单和取消核验。分别确认黄色查询、取消与付款。
2. 查看后端核验回执和实际余额变化。1001元或日累计超过1000元需模拟强验证；界面明确标记其为模拟。
3. 新会话输入“给王五转账100元”：同名收款人先选择，选择不等于付款授权。
4. 新会话输入“给张三转账500元”，再输入“那个改成300”：修改同一任务版本，旧授权失效。若另有最低留存金额或多个目标，先选择具体字段/任务。
5. 输入“分析账单、取消视频会员、再给张三转账500元”，随后“算了，留着吧”：停止未执行取消，暂停依赖它的付款；已核验动作保留。
6. 独立验收环境用 tight_budget 场景演示两个300元请求竞争402元可用金额：两项等待用户选择，允许选择后来的请求，选中后仍重新确认，不自动付款。

每段演示应使用独立新场景或先明确重置合成数据，避免上段已经取消的会员、已入账付款影响预期。管理员重置默认关闭，见 [沙箱测试](docs/SANDBOX_TESTING.md)。完整讲稿见 [答辩材料](docs/DEFENSE.md)。

## 模型配置

默认 `rules` 为有限语法演示解析器。支持 **OpenAI-compatible Chat Completions** 外部服务及 Ollama。将 `.env.example` 复制为本机 `.env`，填写服务地址、模型标识和密钥后重启；不要将密钥发到聊天或提交仓库。示例密钥为空，部署包不收录 `.env`。配置方法和非执行联测见 [模型接入](docs/MODEL_PROVIDERS.md)。

外部模型只生成闭合 CandidatePlan；后端重新解析字段、编译模板、校验归属、权限和资金。配置错误、拒答、截断或不合规响应停住，显式选择模型后不会静默回退到规则。本机已接入DeepSeek并通过两项真实候选生成联测，证据为reports/deepseek-live-candidates.json；尚未完成广泛语义质量评测。受控响应测试不代表模型实际理解能力。

## 执行边界

- 四对象 TaskPlan / TaskStep / ApprovalRequest / ExecutionReceipt 和 Banking Tool API 从 Pydantic 导出 JSON Schema、OpenAPI 与 TypeScript。
- 订阅查询及取消均黄色；一般只读绿色。转出上海自然日累计含本笔≤1000元黄色，>1000元红色模拟强验证。未实现的退款、挂失等工具拒绝。
- 银行写事务重查授权、余额、最低留存、未来承诺、日累计；双边分录、授权消费和规范回执原子提交，步骤幂等身份唯一。
- 交易结果待核验时冻结后续执行，只查询原交易，不重复付款；部分完成与人工接管保留事实。
- 多请求争用资金或保留/取消矛盾时由用户选择，无先来先到优先。意图协调不等于银行冻结资金；真正付款仍原子校验。
- 中断在当前事务结束后生效；不伪造退款或恢复已取消会员。可撤销尚未付款的定时安排，原登记回执保留。
- “帮我省点钱”仅分析与建议，不默认取消会员或转账。

## 开发与验证

Python 3.12+、源码前端 Node 24+。运行 `python scripts/bootstrap.py` 准备环境；开发测试另装 `requirements-dev.txt`。

```bash
python -m pytest --junitxml=reports/tests.xml
python scripts/export_contracts.py
cd apps/workbench
npm ci
npm run build
```

当前 **158项测试通过**，前端编译构建通过；独立解压部署完成1组主流程、4组业务、6组沙箱、9组上下文/冲突 HTTP 场景及重启恢复，参见 `reports/independent-deployment.json`。浏览器自动化仍因工具初始化故障未完成，不能把构建与HTTP通过称为界面点击验收。

## 文档与目录

| 路径 | 内容 |
| --- | --- |
| services/agent | 模型候选、模板、上下文、冲突、编排 |
| services/banking | 合成账户、原子账务、幂等与回执 |
| services/policy | 独立权限和资金约束逻辑 |
| services/sandbox | 管理员重置、故障注入、独立只读验收器 |
| contracts / apps/workbench | 共享协议 / React工作台 |
| tests / reports | 自动化测试 / 实际验证证据 |

[业务DAG](docs/BUSINESS_DAGS.md) · [跨请求与中断](docs/CONTEXT_COORDINATION.md) · [API](docs/API.md) · [架构](docs/ARCHITECTURE.md) · [状态](docs/STATE_MACHINE.md) · [部署](docs/DEPLOYMENT.md) · [安全自评](docs/SECURITY_SELF_ASSESSMENT.md) · [接口变更模板](docs/INTERFACE_CHANGES.md)

此项目是单进程、SQLite、小规模合成演示沙箱，演示PIN、模拟强验证和本地审计链不代表银行生产认证、核心账务或合规认证。交付目标2026-11-02来自团队要求，最终赛事格式、模型使用和提交规则仍需对照官方文件确认。共享接口需按团队群同步与PR评审流程冻结，当前通过草稿PR评审，尚未合并main。
