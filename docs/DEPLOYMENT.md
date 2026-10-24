# 部署、启动与恢复

## 本机

使用部署包时，Windows 双击 start-pact.cmd。脚本在当前项目创建 .venv 并安装 requirements.txt，不写全局 Python 环境。若本机只有 Windows 商店的 python 占位符，请安装 Python 3.12+ 或使用已有的 Codex Python 运行时。

源码首次运行还需 Node 24+ 构建前端；部署包已经包含 dist。Linux/macOS 可运行 python scripts/bootstrap.py，再使用 .venv/bin/python 启动 Uvicorn。

API 与工作台同源监听127.0.0.1:8000。前端开发服务仅绑定127.0.0.1:5173并代理API。生产部署、真实银行和公网暴露不在本版本范围。

## Docker Compose

构建分为 Node 前端阶段和 Python 运行阶段。容器以非root用户10001运行，根文件系统只读、丢弃能力，只把数据卷挂载到 /app/data，主机映射限制为127.0.0.1。健康检查为 /health。

```bash
docker compose up --build -d
docker compose ps
docker compose logs --tail 50 pact
docker compose down
```

本机没有 Docker，因此本机不声称跑过容器。[CI运行40069404218](https://github.com/ThreshoLdnnis/pact-v2/actions/runs/40069404218) 已完成镜像构建、Compose启动、健康检查和真实HTTP烟测，docker-smoke全部步骤成功。证据见reports/ci-verification.json。

## 配置

- PACT_DATABASE_URL：只接受文件型 SQLite；默认 sqlite:///data/pact.db。
- PACT_DEMO_PIN：默认246810，为两个合成身份共用的演示入口。它不是生产认证。
- PACT_OLLAMA_URL / PACT_OLLAMA_MODEL：同时设置才启用本地模型，否则使用规则规划。只配置自己信任的本地推理地址。Ollama API 需要支持结构化输出。
- 容器连接宿主机 Ollama 时，按所用 Docker 平台配置宿主地址。本机模式可用 http://127.0.0.1:11434。

没有模型密钥也能完整演示。不能用 UI 展示模拟验证码的流程替代真实银行的第二认证因子。

## 数据与恢复

首次使用空数据库时写入合成账户、收款人、历史分录和未来承诺，重启不会重复播种。数据库内保存任务、审批、哈希化会话、回执和审计。

建议停止进程后复制数据文件作为演示备份，或使用 SQLite backup API 产生一致性备份。运行时采用 WAL，不应只复制主 .db 而忽略未检查点的日志。Docker 使用持久卷 pact-data。

仅当明确要清空所有合成演示数据时，才删除数据卷或更换新的数据库文件。此版只有初始建表，没有跨版本数据库迁移工具，更新表结构前应备份并计划迁移，不能假设 create_all 会修改已有列。

## 验证命令

启动服务后，使用新的合成数据库运行 python scripts/smoke_http.py。此脚本会取消视频会员并向张三模拟转500元，生成 reports/http-smoke.json。重跑时取消操作安全无操作，累计金额可能要求模拟强验证，脚本会按实际等级处理。

测试：python -m pytest --junitxml=reports/tests.xml。依赖检查：python -m pip_audit -r requirements.txt --no-deps --disable-pip。前端：npm ci、npm run build、npm audit。
