# PACT工作台

React/TypeScript + Vite。npm ci后npm run build；构建结果由FastAPI同源托管。npm run dev只监听127.0.0.1:5173，API代理到8000。

页面提供聊天、DAG、确认/模拟强验证、资金承诺、回执和审计。protocol.ts由共享Python协议生成，勿手工修改。真实回执来自后端查询，UI不做乐观付款成功提示。
