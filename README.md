# AI 教材家教平台

这是当前平台基础里程碑的本地使用说明。当前版本已经具备 FastAPI 健康服务、Next.js C3 可调整大小工作区、PostgreSQL/pgvector、带密码认证的 Redis、MinIO、Docker 服务拓扑，以及自动化测试和 CI。账号、班级、计费和知识入库属于后续里程碑，当前版本尚未提供。

## 使用 Docker 启动

准备 Windows 版 Docker Desktop（包含 Docker Compose），并确保 Docker Desktop 已经启动。首次启动时，在 Windows PowerShell 中运行：

```powershell
Set-Location '<project checkout>'
Copy-Item .env.example .env
```

将 `<project checkout>` 替换为你本机的项目检出目录；其余命令都从该目录运行。

打开 `.env`，将其中所有 `replace-for-non-local-use` 占位值替换为你自己的本地密码，并同步修改引用这些密码的连接地址。不要提交或分享真实密码；`.env` 已被 Git 忽略，只保留在本机。

```powershell
docker compose --env-file .env up --build -d
docker compose --env-file .env ps
```

启动完成后可访问：

- Web 工作区：<http://127.0.0.1:3000>
- API 健康检查：<http://127.0.0.1:8000/api/v1/health>
- MinIO 管理界面：<http://127.0.0.1:9001>

需要查看启动日志或停止服务时：

```powershell
docker compose --env-file .env logs --tail 200
docker compose --env-file .env down
```

`NEXT_PUBLIC_API_BASE_URL` 是构建 Web 镜像时写入浏览器端的值。修改它以后必须重新构建 Web，例如：

```powershell
docker compose --env-file .env up --build -d web
```

## 不使用 Docker 的开发方式

需要 Python 3.12、满足项目要求的 Node.js（推荐 22.22.2）和 Corepack。下面的命令使用仓库内的 `apps/api/.venv`，不会依赖机器上的特殊运行时缓存路径。

在仓库根目录准备 API：

```powershell
py -3.12 -m venv apps/api/.venv
& .\apps\api\.venv\Scripts\python.exe -m pip install --requirement apps/api/build-requirements.lock
& .\apps\api\.venv\Scripts\python.exe -m pip install --requirement apps/api/requirements.lock
& .\apps\api\.venv\Scripts\python.exe -m pip install --requirement apps/api/dev-requirements.lock
& .\apps\api\.venv\Scripts\python.exe -m pip install --editable apps/api --no-deps --no-build-isolation
& .\apps\api\.venv\Scripts\python.exe -m pip check
```

启动 API：

```powershell
Set-Location apps/api
& .\.venv\Scripts\python.exe -m uvicorn tutor_api.main:app --reload
```

另开一个位于仓库根目录的 PowerShell 窗口，准备并启动 Web：

```powershell
corepack enable
corepack prepare pnpm@11.19.0 --activate
pnpm install --frozen-lockfile
pnpm dev:web
```

本地直接运行时，API 的默认配置适合健康服务开发；PostgreSQL、Redis 和 MinIO 的完整联调请使用上面的 Docker 拓扑。

## 质量检查

API 检查（从仓库根目录开始）：

```powershell
Set-Location apps/api
& .\.venv\Scripts\python.exe -m ruff check src tests
& .\.venv\Scripts\python.exe -m pytest --cov=tutor_api --cov-report=term-missing --cov-fail-under=90
```

Web 检查（从仓库根目录运行）：

```powershell
pnpm test:web
pnpm lint:web
pnpm build:web
```

## 常见问题

- Docker 命令无法连接：启动 Docker Desktop，等待其显示引擎已就绪，再重试。
- 本地端口被占用：当前配置默认使用 `3000`、`8000`、`9000` 和 `9001`。停止占用端口的程序后重启；不要只改一个地址而忽略 `.env`、跨域来源和浏览器端 API 地址之间的对应关系。
- 修改 `.env` 后没有生效：重新创建容器；涉及 `NEXT_PUBLIC_API_BASE_URL` 时还要重建 Web。

```powershell
docker compose --env-file .env up --build -d --force-recreate
```

- 检查服务状态：先查看容器健康状态，再直接请求 API 健康端点。

```powershell
docker compose --env-file .env ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

## 镜像维护

容器基础镜像同时固定了可读标签和内容摘要，确保不同机器使用相同镜像。维护者升级镜像时应有意地同时更新标签与摘要，然后重新构建并运行全部检查；普通本地使用者无需修改这些值。
