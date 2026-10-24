# 0.4 部署与恢复

## Windows离线包

需要Windows x64与已安装的CPython 3.12。解压后双击start-pact.cmd；脚本在项目内创建.venv，校验离线wheel哈希，以--no-index与--require-hashes安装19个锁定发行物，再启动127.0.0.1:8000。前端已构建，无需Node、Codex或API密钥。不要把整个程序放在受限的只读目录。

其他Python版本（最低3.12）或系统的wheel不匹配时改用requirements.txt在线安装；离线包不包含Python解释器。Linux/macOS可运行sh start-pact.sh。源码开发需要Node24+构建前端。测试依赖requirements-dev.txt未包含在离线运行依赖中。

本轮用干净解压目录、新建venv、PIP_NO_INDEX=1实际完成离线安装，运行全部HTTP脚本并重启服务；报告为reports/independent-deployment.json。不是复用开发venv的结果。

## 配置与启动

本地复制.env.example为.env，真实环境变量优先，文件不执行shell表达式。默认合成PIN246810，规则解析，无测试控制。模型配置见MODEL_PROVIDERS.md；密钥本机填写，重启生效。数据库默认sqlite:///data/pact.db，仅支持文件型SQLite。

```powershell
python scripts/bootstrap.py
.venv\Scripts\python.exe -m uvicorn pact.app:create_app --factory --host 127.0.0.1 --port 8000
```

只运行一个应用进程；多worker、外部任务队列和分布式锁没有验收。Ctrl+C停止。本机与前端开发服务分别监听8000/5173，无新增公网端口。

## Docker

```bash
docker compose up --build -d
docker compose ps
docker compose down
```

Compose主机端口仅127.0.0.1，容器非root、只读根目录、丢弃能力，数据卷挂载/app/data。模型变量由Compose环境传入，不拷贝.env到镜像。0.4本机没有Docker运行证据，历史0.1 CI仅作历史记录；2026-10-25恢复GitHub整理，本轮CI结果需以PR #8实际运行记录为准。

## 数据恢复与升级

会话、任务、审批、冲突、保留意图、澄清、回执和审计存SQLite，重启不重新播种已有数据。WAL模式建议停止进程后备份，或用SQLite backup API；不要运行中只拷贝主.db忽略WAL。

0.4新增独立表，历史计划JSON读取有默认值，旧审批依绑定重新确认。没有通用数据库迁移框架；未知旧库先备份并在副本验证，不声称支持所有历史库无损升级。

管理员一键重置只用于合成沙箱，会清除业务历史和会话，保留审计；默认关闭，故障注入需独立管理员令牌。不要在有需要保留的演示记录的环境运行破坏性验收脚本。具体见SANDBOX_TESTING.md。

独立验收器 `python scripts/verify_sandbox.py data/pact.db` 使用sqlite3只读检查账务、授权、DAG依赖、冲突窗口、中断事实和审计；不调用业务实现来证明自身正确。真实HTTP脚本：smoke_http.py、smoke_business.py、smoke_sandbox.py、smoke_context.py；后两者会重置合成数据。

公网部署、真实用户、真实资金、生产MFA、容灾与银行合规认证均超出本MVP边界。
