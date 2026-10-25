# 当前验收证据

只保留与当前业务边界有关的可复查结果；过期测试数量、旧界面图片和旧扫描快照已删除。JUnit与依赖扫描由CI生成并上传artifacts，不重复存入Git。

| 文件 | 含义 |
| --- | --- |
| mvp-acceptance.json | 功能、模型与限制总览，具体测量按各报告来源阅读 |
| ci-verification-0.4.json | 0.4代码对应的已通过CI运行与提交SHA |
| independent-deployment.json | Windows干净目录离线安装、HTTP与重启证明；保留当时源文件哈希 |
| deepseek-live-candidates.json | 两项真实合成候选联测，无银行执行和密钥 |
| http-smoke.json | 三业务组合的真实HTTP主链路 |
| business-http-smoke.json | 订阅、消歧、接管与部分完成 |
| sandbox-http-smoke.json | 重置、资金约束与三类故障 |
| context-http-smoke.json | 九组上下文、冲突与中断场景 |

这些是测量时刻的证据，不会随着文档清理伪造新的测量日期或哈希。当前main/PR运行状态以[GitHub Actions](https://github.com/ThreshoLdnnis/pact-v2/actions)为准。合成演示、测试数量和零已知漏洞均不等于银行合规或安全认证。
