# AI 教材家教平台

这是当前平台基础里程碑的本地使用说明。当前版本已经具备 FastAPI 健康服务、Next.js 三栏可调整宽度的学习工作区、PostgreSQL/pgvector、带密码认证的 Redis、MinIO、Docker 服务拓扑，以及自动化测试和 CI。用户可注册、登录、退出，拥有独立个人空间；任意已登录用户可创建班级，并通过邀请码邀请学生加入。当前版本还提供启用模型目录、人民币钱包预留结算，以及空间隔离的知识库创建、上传、异步入库、带引用检索和原页预览界面；真实容器化端到端验收仍必须在可用 Docker/pgvector 运行时完成。

## 使用 Docker 启动

准备 Windows 版 Docker Desktop（包含 Docker Compose），并确保 Docker Desktop 已经启动。首次启动时，在 Windows PowerShell 中运行：

```powershell
Set-Location '<project checkout>'
Copy-Item .env.example .env
```

将 `<project checkout>` 替换为你本机的项目检出目录；其余命令都从该目录运行。

打开 `.env`，将其中每一个 `replace-with-long-random-...` 占位值分别替换为不同的长随机值，并保持以下对应关系：

- `POSTGRES_PASSWORD` 必须与 `DATABASE_URL` 中的 PostgreSQL 密码一致。
- `REDIS_PASSWORD` 必须与 `REDIS_URL` 中的 Redis 密码一致。
- `OBJECT_STORAGE_SECRET_KEY` 是应用身份的密钥；初始化器和 API 使用的是同一个环境变量，因此两处会自动保持一致。
- `OBJECT_STORAGE_SECRET_KEY` 绝不能等于管理员身份的 `MINIO_ROOT_PASSWORD`。
- 应用访问键 `OBJECT_STORAGE_ACCESS_KEY` 必须不同于管理员用户名 `MINIO_ROOT_USER`。
- `CITATION_HMAC_SECRET` 用于签署 AI 家教引用的不透明令牌；必须与 `OBJECT_STORAGE_SECRET_KEY` 不同，轮换它会使旧引用令牌失效。

每个密码或密钥都应使用英文字母、数字、下划线（`_`）和连字符（`-`）生成独立的长随机值。这样可以避免 Docker Compose 变量插值和 URL 内密码编码产生不一致。不要在这里使用需要额外转义或百分号编码的任意特殊字符，也不要让 PostgreSQL、Redis、MinIO 管理员和对象存储应用身份共享密钥。不要提交或分享真实密码；`.env` 已被 Git 忽略，只保留在本机。

MinIO 初始化器只用 `MINIO_ROOT_USER` 和 `MINIO_ROOT_PASSWORD` 执行管理操作，然后为 `OBJECT_STORAGE_BUCKET` 创建专用策略和应用用户。API 只会收到权限限定到该存储桶的 `OBJECT_STORAGE_ACCESS_KEY` 和 `OBJECT_STORAGE_SECRET_KEY`，不会收到 MinIO 管理员凭据。

Faro 默认由 API 和 worker 容器直接访问，正常环境应保持 `FARO_PROXY_URL=` 为空。只有确认 Docker Desktop 的直连网络异常时，才启用仓库自带的受限 CONNECT 中继。这个可选兼容方案需要宿主机安装 Python 3.12；先启动中继，再把 `.env` 中的 `FARO_PROXY_URL` 设为 `http://host.docker.internal:17897`：

```powershell
Start-Process -WindowStyle Hidden `
  -FilePath 'py.exe' `
  -ArgumentList @('-3.12', '.\scripts\faro_relay.py', '17897')
```

该中继只允许连接 `faroapi.com:443`，不会转发任意目标。API 和 worker 共用同一套 Faro 网络客户端：当已配置的中继在**建立连接阶段**不可达时，会安全回退到容器直连；一旦已经收到 HTTP 响应则不会重复发送 POST。这样宿主机中继停止后不会在容器直连可用时同时拖垮 AI 助教和候选生成。若不再需要中继，应清空 `FARO_PROXY_URL`；修改该变量后需要重新创建 API 和 worker 容器。

```powershell
docker compose --env-file .env up --build -d
docker compose --env-file .env ps
```

### 首次拉取或 Python 依赖更新后必须重建镜像

Docker 用户不需要在 Windows 上单独安装 Python 包。API 与 Worker 的 Python 依赖由 `apps/api/requirements.lock` 安装进 `textbook-tutor-api` 镜像；当前版本已经锁定 `httpx==0.28.1`。如果拉取更新后仍复用旧镜像，Worker 可能报告 `ModuleNotFoundError: No module named 'httpx'`。

遇到这种情况，不要在运行中的容器里执行临时 `pip install`，因为容器重建后临时安装会丢失。请从仓库根目录重建并重新创建 API、Worker 和 Web：

```powershell
docker compose --env-file .env build --no-cache api worker
docker compose --env-file .env up -d --force-recreate api worker web
docker compose --env-file .env exec api python -c "import httpx; print(httpx.__version__)"
```

最后一条命令应输出 `0.28.1`。如果 API 日志显示 PostgreSQL `password authentication failed`，那是 `.env` 与既有数据库卷密码不一致，不是 Python 依赖问题；请按本文“首次启动后修改了 PostgreSQL 密码”一节处理，不要用安装依赖或反复重建镜像来掩盖凭据不一致。

启动完成后可访问：

- Web 工作区：`http://localhost:${WEB_PORT}`（默认 `3000`；可在 `.env` 中换成新端口）
- API 健康检查：<http://127.0.0.1:8000/api/v1/health>
- MinIO 管理界面：<http://127.0.0.1:9001>

需要查看启动日志或停止服务时：

```powershell
docker compose --env-file .env logs --tail 200
docker compose --env-file .env down
```

浏览器默认通过同源的 `/api` 服务端代理访问后端（代理目标由 Web 容器的 `API_INTERNAL_URL` 决定），因此不需要设置任何浏览器端变量。`.env.example` 中的 `NEXT_PUBLIC_API_BASE_URL` 仅作为可选覆盖：把它设置为可公开访问的后端地址并重建 Web 后，浏览器会直连该地址而不是走代理。无论哪种方式，修改它以后都必须重建 Web：

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

## 知识库导入与检索

知识库属于当前空间：创建知识库后可上传 PDF、DOCX、UTF-8 Markdown、JPEG（`.jpg`/`.jpeg`）、PNG 或 Obsidian Vault ZIP。上传先显示“处理中”；只有版本为 `READY` 且任务为 `COMPLETED` 时才显示“可搜索”。搜索结果只显示文件名、页码和受限摘录；“打开原页”使用不透明引用令牌，页面不会向学习者展示对象键、OCR、嵌入、任务或存储服务内部信息。

当前安全默认值如下：单个知识库上传最大 **100 MiB**（`KNOWLEDGE_UPLOAD_MAX_BYTES=104857600`）；Vault 最多 **5,000** 个文件、解压总量最多 **500 MiB**（`MAX_VAULT_UNCOMPRESSED_BYTES=524288000`）；默认嵌入为确定性的 `hash / feature-hash-v1 / 384`，维度允许范围为 8–4096。`OCR_BACKEND` 当前唯一允许值为 `disabled`，即本仓库没有已启用的外部 OCR 服务；`OCR_LANGUAGES` 默认值为 `eng,chi_sim`，运行时 OCR helper 仅支持这两个语言标识。同样，仓库没有已配置的远程嵌入服务或真实模型调用凭据。不要把这些本地/确定性适配器当作生产语义检索或 OCR 提供商。

`compose.yaml` 中的 API 和 worker 目前依赖以上应用默认值；它不会将这些知识处理 override 映射到两个容器。因此，仅在 `.env` 新增知识处理变量不会覆盖容器设置；如要在部署中改变限制或适配器，必须在同一次经审核的配置变更中同时更新 API 和 worker 的 Compose 环境映射。DeepTutor 仅作为产品研究参考，不复制其源代码或把它声明为运行时依赖。

确定性测试使用内存构造的有效 PDF、DOCX、Markdown、JPEG、PNG 和 Vault ZIP 输入；上传验证还逐一覆盖 `.jpg` 与 `.jpeg` 扩展名。仓库没有提交二进制教材样本。容器验收仍应使用可重复的 Markdown 和 PDF 样本完成“注册 → 创建知识库 → 上传 → 等待 READY → 搜索 → 打开引用页”流程；不要把仅通过单元测试视为 PostgreSQL/pgvector、Redis、MinIO、worker 和浏览器垂直切片已经通过。

**2026-08-27 验证状态：** 知识候选生成管线（GENERATE_MARKDOWN）与 worker 入口已恢复可导入，此前收集失败的 6 个测试文件全部恢复；中文开放题判分与中文词法检索已修复并有回归测试覆盖。Web 全量测试（117 用例）通过；API Ruff 全仓 0 错误；唯一遗留失败是 compose 安全测试中与 `FARO_API_KEY` 相关的旧断言，已在同批改动中按新密钥策略更新。Docker 引擎可用，但真实 PostgreSQL/pgvector 迁移回环与 Compose 垂直切片仍未执行；覆盖率门槛（90%）需在恢复全量绿色后重新确认。
## 账号与班级的本地验证

先应用数据库迁移，再启动 API：

```powershell
& .\apps\api\.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini upgrade head
```

打开 Web 工作区后，使用“注册”创建用户名、邮箱和至少 12 位密码的账号。注册成功会自动登录并建立“我的空间”；以后可用邮箱和密码登录，退出会让当前浏览器会话立即失效。浏览器只保存 HttpOnly Cookie，不会保存可复制的登录令牌。

已登录用户可以创建班级，创建结果会显示一次邀请码。把邀请码安全地发送给学生；学生登录后使用该邀请码加入。教师可创建受限次数和有效期的邀请码，只有班级创建者能调整成员教师角色或移除其他成员。邀请码和密码都不应写入文档、聊天记录或截图。

## 模型与余额的本地管理

`.env.example` 中的 `PROVIDER_PROFILES_JSON` 只是非机密的示例模型目录，`example-chat-model` 不是可调用的真实模型，也不能当作凭据使用。部署管理员只应在被 Git 忽略的 `.env` 中填入实际服务商密钥；密钥不得提交到仓库、写入 `PROVIDER_PROFILES_JSON`、数据库或发送给浏览器。未配置真实密钥时，模型目录仍可用于本地界面与计费流程演示，但不会调用外部模型服务。

首次配置或调整可用模型前，管理员应审核来源并发布审核后的价格与汇率快照。结算会保存当次使用的价格与汇率版本，因此不要直接改写已有快照；如价格或汇率变更，应新增一个带生效时间与来源的版本。只有可核验用量且启用的模型会展示给普通用户，缺少可换算人民币价格时会显示“价格待公布”。

余额采用账本记录。当前版本不接入自动支付：平台管理员通过后台完成人工充值和冲正，创建人工充值记录；若需要撤销则创建一笔关联原充值的冲正记录，而不修改或删除历史账本。操作前核对用户、金额、外部凭据和原因；同一外部凭据不能重复充值。普通用户只能看到自己的人民币可用余额、已启用模型及账单记录。

## 质量检查

API 检查（从仓库根目录开始）：

```powershell
Set-Location apps/api
& .\.venv\Scripts\python.exe -m ruff check src tests
& .\.venv\Scripts\python.exe -m pytest --cov=tutor_api --cov-report=term-missing --cov-fail-under=90
Set-Location ..\..
```

继续运行 Web 检查：

```powershell
pnpm test:web
pnpm lint:web
pnpm build:web
```

## 常见问题

### Docker 命令无法连接

启动 Docker Desktop，等待其显示引擎已就绪，再重试。

### 本地端口被占用

当前配置默认使用 `3000`、`8000`、`9000` 和 `9001`。停止占用端口的程序后重启；不要只改一个地址而忽略 `.env`、跨域来源和浏览器端 API 地址之间的对应关系。

### 一般环境变量或应用变更没有生效

重新创建并构建容器；涉及 `NEXT_PUBLIC_API_BASE_URL` 时必须重建 Web。

```powershell
docker compose --env-file .env up --build -d --force-recreate
```

### 首次启动后修改了 PostgreSQL 密码

已有 PostgreSQL 数据卷初始化完成后，修改 `.env` 中的 `POSTGRES_PASSWORD` 不会更改数据库中现有角色的密码。建议首次启动后不要再修改该值；如果误改，请恢复原来的 `.env` 值。

示例占位名现在是 `replace-with-long-random-postgres-password`。如果数据卷曾用旧版占位值或其他密码初始化，仅修改 `.env` 或复制新版示例不会重置数据库中的密码；必须恢复初始化时的实际值，或按下方警告在确认数据可丢弃后重建数据卷。

只有在本机数据完全可以丢弃的测试环境中，才可以删除所有数据卷并重新初始化：

> **警告：** 以下操作会永久删除本机由此 Compose 项目保存的 PostgreSQL、Redis 和 MinIO 数据，无法撤销。确认这些数据不再需要后才能执行。

```powershell
docker compose --env-file .env down --volumes
docker compose --env-file .env up --build -d
```

### 检查服务状态

先查看容器健康状态，再直接请求 API 健康端点。

```powershell
docker compose --env-file .env ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

## 镜像维护

容器基础镜像同时固定了可读标签和内容摘要，确保不同机器使用相同镜像。维护者升级镜像时应有意地同时更新标签与摘要，然后重新构建并运行全部检查；普通本地使用者无需修改这些值。
