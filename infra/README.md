# 部署

根目录Dockerfile和compose.yaml构建并启动统一MVP服务，非root运行，只读根文件系统，数据卷持久化，主机仅映射127.0.0.1。源码/部署包也支持start-pact.cmd。

本机无Docker，容器验收通过CI执行，具体结果见实际工作流。详细说明见docs/DEPLOYMENT.md。
