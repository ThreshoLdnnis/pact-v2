# 外部模型与本地配置

0.4支持rules、ollama、openai_compatible；密钥由操作者之后在本机配置。没有模型密钥也能演示业务闭环。2026-10-25已在本机配置DeepSeek，deepseek-flash/json_object两项真实候选联测通过（查余额、三业务组合），耗时约1秒和4.6秒。未调用银行执行API；广泛语义评测尚未完成。证据见reports/deepseek-live-candidates.json。

## 本机配置

复制项目根目录 `.env.example` 为 `.env`，仅在自己的编辑器中填写：

```dotenv
PACT_MODEL_PROVIDER=openai_compatible
PACT_LLM_BASE_URL=https://YOUR_PROVIDER_BASE/v1
PACT_LLM_MODEL=YOUR_MODEL_ID
PACT_LLM_API_KEY=
PACT_LLM_FORMAT=json_schema
```

地址应填供应商公布的兼容API根路径，适配器追加 `/chat/completions`，不要再填完整端点。模型标识按该供应商实际可用列表填写，没有写死默认模型。HTTPS必需，本地回环服务允许HTTP；不接受URL中夹带凭据、查询串和重定向。容器环境需通过Compose中的同名变量传入。真实环境变量优先于.env，修改后重启服务。

请求采用Bearer密钥和非流式Chat Completions；响应优先使用 `json_schema` 严格结构，局部对象封闭、所有属性必填、可空目标用null。兼容服务若只支持JSON模式，可手动改为 `json_object`；无论哪种模式，本地都会再次执行同一CandidatePlan结构和DAG校验。接口依据：[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)。第三方“兼容”并不保证支持全部参数，需用其真实服务联测。

## 验证方法

启动脚本准备好环境后，Windows运行：

```powershell
.venv\Scripts\python.exe scripts/check_model.py
```

该脚本直接测试两项合成候选：查余额，以及分析账单、取消会员后转账；不调用银行执行API，不创建付款。通过后仍需在工作台测真实请求、澄清和审批，记录模型、版本、输入集与误差。两项通过不是完整自然语言能力评测。

Ollama用 `PACT_MODEL_PROVIDER=ollama`、`PACT_OLLAMA_URL=http://127.0.0.1:11434` 和自己已经安装的 `PACT_OLLAMA_MODEL`。默认rules只适合文档列出的有限语法。保留旧配置兼容：未显式指定provider且两项Ollama变量齐全时选择Ollama。

## 数据与失败边界

模型收到本次请求、合成账户ID、收款人名册和用户明确提到的取消对象ID/名称，不传密钥进提示词，不发送未经批准的订阅清单、余额、流水或审计。审批、冲突决策、中断和上下文指代由服务端持久状态处理，模型不能写运行状态或授权字段。

超时45秒、HTTP失败、拒答、截断、工具调用、空响应、额外字段、错误DAG或增加/遗漏明确变更动作均停止候选生成，返回通用错误；不回传供应商响应正文或密钥，不自动降级或重试执行。提示注入启发式不是安全保证，真正边界仍是闭合协议、资源归属、用户授权和银行执行校验。

.env与本地数据库不进Git或部署ZIP。密钥不由UI收集，不写会话或审计；请勿放入截图、Issue、群消息和日志。受控假响应测试覆盖请求格式、拒答、截断、额外字段、错误配置、超时与错误脱敏；真实提供商连通性和语义质量待本机配置后验收。
