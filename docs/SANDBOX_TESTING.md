0.4当前验收：保留本文重置与故障接口，新增scripts/smoke_context.py（会重置合成数据）覆盖九组上下文/冲突/中断HTTP场景。独立oracle新增冲突期间禁止变更/黄色查询、停止后不执行、回执事实保留检查。实际独立离线部署与重启证据见reports/independent-deployment.json。以下0.3设计与历史证据按版本阅读。

# 0.3 沙箱重置、故障注入与独立验收

范围：仅合成银行业务。不是完整银行核心、真实支付网关或任意代码执行沙箱。测试控制不是Agent工具，不进入模型上下文，也不能赋予交易权限。

## 开启测试控制

默认关闭。需同时设置PACT_SANDBOX_CONTROLS=1和长度至少24字符的独立随机PACT_SANDBOX_ADMIN_TOKEN，然后重启应用；缺少任一条件均关闭。服务只绑定127.0.0.1，管理员令牌不得提交仓库、写入群消息或放入模型提示。

PowerShell本机示例（先完成依赖安装和前端构建）：

```powershell
$env:PACT_SANDBOX_CONTROLS = '1'
$env:PACT_SANDBOX_ADMIN_TOKEN = .venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.venv/Scripts/python.exe -m uvicorn pact.app:create_app --factory --host 127.0.0.1 --port 8000
```

启动前请在同一终端自行查看并保存生成的令牌；新开终端不会自动继承它，运行验收脚本时须设置同一令牌。Docker Compose读取相同环境变量，或从未提交的.env读取。测试结束后关闭开关并重启；关闭时数据库内尚未触发的故障也不生效。

工作台“沙箱测试”页中填管理员令牌，再选择场景。重置需要勾选确认；令牌仅在该组件内存中保留，离开该页后清除。管理员只能设置有限测试条件，不能调用“强制付款成功”或任意SQL。

## 管理 API

以下路径均以/api/v1开头，全部需要X-Sandbox-Admin请求头。未启用404；已启用但令牌不正确403。

| 方法与路径 | 请求 | 响应/行为 |
| --- | --- | --- |
| POST /sandbox/reset | {confirmation:"RESET_SYNTHETIC_DATA",scenario:"baseline"或"tight_budget"} | reset、scenario、epoch、sessions_revoked、audit_preserved；清空全部合成业务、会话和故障，保留审计链，重播种 |
| POST /sandbox/faults | {plan_id,plan_version,step_id,point} | fault_id、remaining=1、expires_at，最多一个活跃故障/步骤，10分钟失效 |
| POST /sandbox/faults/clear | {} | 清除所有已设置故障，不修改交易或回执 |
| GET /sandbox/acceptance | 无 | passed、checks、issues、counts、source；只读检查，发现问题仍返回200且passed=false |

场景baseline恢复Alice余额1,553,400分、Bob500,000分、正常房租及两个订阅承诺。tight_budget设Alice余额200,000分、最低留存100,000分、其他未来承诺50,000分、视频会员下次扣款9,800分；音乐预留已履约。取消前可新增转账40,200分，核验取消后50,000分；转账后余额150,000分。资金紧张初值通过一组明确标注的配平合成场景流水形成，保留非负期初余额，对账和系统资金总量守恒。取消不退款，只释放未来义务。

重置是全局管理动作：所有演示身份会话撤销、旧计划/审批/回执不可再访问。不是生产银行删除账务功能。不可把验收脚本指向需要保留历史的演示数据库。审计事件保留且记录重置主体和场景；历史引用可能对应已清空对象，这是预期管理记录。

## 单次故障语义

| point | 故障时机 | 验收要求 |
| --- | --- | --- |
| before_post_reject | 授权通过、正式操作之前明确拒绝 | 无业务变更、无新回执、授权不消费 |
| after_mutation_rollback | 写操作已经更改内存并刷入事务后抛错 | 余额、分录、订阅/承诺、回执完整回滚，授权不消费 |
| verify_timeout | 正式操作及回执保存后、结果核验时超时 | 已发生状态保留，result为空、pending_verification，不重付；reconcile恢复原回执 |

故障严格绑定用户、计划、版本、步骤，不能用通配符、切换参数或跨版本触发。单次故障消耗发生在业务保存点之外，业务回滚不会使故障无限重触发。故障不替代审批、不改变权限等级、不伪造成功结果。当前模拟本地确定性故障，不是跨行清算网络的完整仿真。

## 独立验收

services/sandbox/acceptance.py使用Python标准库sqlite3只读快照，不导入Banking/Policy/Agent或复用生产回执核验函数。核对：期初+分录=余额、交易双边守恒、回执哈希及动作归属、幂等身份、前置回执时间证据、查询/取消/转账独立授权及日累计等级、取消协议状态、计划结果与正式回执一致、审计链。发现无法读取或损坏结构时失败关闭。

```bash
python scripts/verify_sandbox.py data/pact.db
# 成功退出0，失败退出1；只读、不修复、不替模型改状态。
```

场景结果还由独立测试用具体预期值核对，包括-50000分余额变化、9800分承诺释放、三份授权、取消失败阻止付款，以及篡改余额/回执/授权/计划结果时验收必须失败。它是本项目不变量验收器，不是外部安全审计或完整银行合规证明。

```bash
python -m pytest --junitxml=reports/tests.xml
python scripts/smoke_sandbox.py http://127.0.0.1:8000
```

HTTP脚本需要在环境中设置同一管理员令牌，会重置目标的全部合成业务。涵盖目标联动、重置、资金紧张、三种故障和取消失败阻止付款，生成reports/sandbox-http-smoke.json。仅使用一次性测试实例。0.2历史数据无完整迁移保证，0.3验收应使用新数据库或明确重置后的合成场景。
