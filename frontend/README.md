# 安心保前端

使用 React、TypeScript、Ant Design 和 Vite 构建。启动后端后，在本目录运行：

~~~powershell
npm ci
npm run dev
~~~

访问 http://localhost:5173。Vite 默认代理到 http://127.0.0.1:8001。如需覆盖，复制 .env.example 为 .env.local，并填写 VITE_BACKEND_HOST 和 VITE_BACKEND_PORT。

通过 Dockerfile 构建镜像时，可用 BACKEND_HOST 和 BACKEND_PORT 配置 Nginx 代理目标。
