# 安心保 AI 智能保险顾问

面向在线保险商城，提供保险条款问答、保障方案推荐与理赔咨询。LangGraph 按意图分发工作流，FastAPI 和 React 通过 SSE 展示回复及方案确认状态。

## 主要功能

- 保险咨询、理赔咨询与闲聊路由，共享同一会话的上下文。
- Milvus 通过稠密向量与 BM25 检索子块，按产品筛选和重排，PostgreSQL 按父块 ID 返回上下文。
- 保障方案经用户确认后保存，PostgreSQL Checkpointer 持久化会话及待确认状态。

## 本地运行

准备 Python 3.14、uv、Node.js 和 Docker Compose。在仓库根目录启动 PostgreSQL 和 Milvus 等依赖：

~~~powershell
docker compose -f deploy/docker-compose.yml up -d
~~~

进入 agent-service 目录，复制配置示例：

~~~powershell
Copy-Item .env.example .env
~~~

填写 DeepSeek、DashScope 密钥，并设置随机 JWT_SECRET。然后在该目录启动后端：

~~~powershell
uv sync
uv run python -m app.main
~~~

后端默认监听 http://127.0.0.1:8001。在另一个终端进入 frontend 目录运行：

~~~powershell
npm ci
npm run dev
~~~

访问 http://localhost:5173。

## 构建保险条款知识库

启动本地 Ollama 并加载 qwen3-embedding:0.6b。在 agent-service 的 .env 中设置 MINERU_TOKEN，确认产品条款 PDF 可访问，然后在 agent-service 目录运行：

~~~powershell
uv run python -m scripts.ingest_rag
~~~

该脚本将条款父块写入 PostgreSQL、子块写入 Milvus。

## 项目目录

- agent-service/app 包含 FastAPI 接口、Agent 工作流和 RAG 代码。
- frontend 是 React 前端。
- deploy 包含 Docker Compose 和数据库初始化脚本。
