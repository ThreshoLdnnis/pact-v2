# PACT共享协议0.2

本目录已经包含可运行的协议实现，状态为待团队评审，尚未冻结。

- models.py：闭合Pydantic协议唯一来源，包含候选、任务、审批、回执和银行执行命令。
- task-protocol.schema.json：Task Protocol JSON Schema。
- openapi.json：所有API的OpenAPI。
- banking-tool.openapi.json：Banking Tool API独立入口。
- 前端src/protocol.ts由同一生成器导出，不手工维护同名协议。

运行python scripts/export_contracts.py重新生成，提交时同步生成物。API字段与状态含义见docs/API.md和docs/STATE_MACHINE.md。

模型仅可生成CandidatePlan。风险等级由Policy决定，银行后端保存规范回执。公共接口新增、修改、废弃仍需按docs/INTERFACE_CHANGES.md先沟通再合并。
