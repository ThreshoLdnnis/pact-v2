# 测试与复现入口

| 文件 | 覆盖 |
| --- | --- |
| test_workflows.py | DAG、权限阈值、幂等并发、原子回滚、资金承诺与重规划 |
| test_business_boundaries.py | 黄色订阅、收款人消歧、待核验、部分完成与人工接管 |
| test_templates_sandbox.py | 模板组合、动态判级、重置、故障注入和独立验收 |
| test_context_coordination.py | 多请求选择、上下文更正、消息重试与中断事实 |
| test_model_adapter.py | 受控供应商响应、严格候选、错误脱敏与本地配置 |

运行 `python -m pytest --junitxml=reports/tests.xml`；不会使用真实模型密钥完成付款。受控模型测试不代表真实语义质量。真实模型候选联测入口是scripts/check_model.py，只生成候选，不调用银行执行API。

HTTP脚本smoke_http.py、smoke_business.py、smoke_sandbox.py、smoke_context.py分别覆盖主流程、业务、故障与多请求。后两项会清空目标合成数据，必须使用一次性实例和独立管理员令牌。独立只读验收为scripts/verify_sandbox.py；详见[沙箱测试](../docs/SANDBOX_TESTING.md)。CI运行全部测试及Docker HTTP，生成的JUnit和依赖扫描结果作为artifacts保存。
