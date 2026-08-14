# Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable monorepo with a tested FastAPI service, a tested Next.js C3 workspace shell, environment validation, and Docker Compose infrastructure ready for later identity and knowledge features.

**Architecture:** Keep the first slice intentionally narrow: one Next.js web app and one FastAPI API, backed by PostgreSQL/pgvector, Redis, and MinIO service definitions. The API exposes health/readiness only; the web app renders the approved Obsidian-like four-column shell with three resizable content panes. No account, billing, OCR, or provider behavior is faked in this slice.

**Tech Stack:** Next.js/React/TypeScript/pnpm, react-resizable-panels 4.9, Vitest/Testing Library, FastAPI/Pydantic/Python 3.12/pytest, PostgreSQL 17 + pgvector, Redis 7, MinIO, Docker Compose.

---

## Locked file structure

```text
.
├── .env.example                       # non-secret local configuration contract
├── .github/workflows/quality.yml      # repeatable web/API checks
├── apps/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/tutor_api/
│   │   │   ├── __init__.py
│   │   │   ├── core/config.py
│   │   │   └── main.py
│   │   └── tests/
│   │       ├── test_config.py
│   │       └── test_health.py
│   └── web/
│       ├── Dockerfile
│       ├── package.json
│       ├── src/app/{layout.tsx,page.tsx,globals.css}
│       ├── src/components/workspace/
│       │   ├── workspace-shell.tsx
│       │   ├── workspace-shell.module.css
│       │   └── workspace-shell.test.tsx
│       ├── src/test/setup.ts
│       └── vitest.config.ts
├── compose.yaml
├── package.json
├── pnpm-workspace.yaml
└── README.md
```

The leftmost space rail is fixed. The content tree, center workspace, and AI tutor pane are the three resizable areas required by the approved C3 design.

### Task 1: Create the monorepo contract

**Files:**
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Add the root pnpm scripts**

Create `package.json`:

```json
{
  "name": "textbook-agent-platform",
  "private": true,
  "packageManager": "pnpm@11.19.0",
  "scripts": {
    "dev:web": "pnpm --dir apps/web dev",
    "test:web": "pnpm --dir apps/web test",
    "lint:web": "pnpm --dir apps/web lint",
    "build:web": "pnpm --dir apps/web build"
  }
}
```

Create `pnpm-workspace.yaml`:

```yaml
packages:
  - apps/web
```

- [ ] **Step 2: Define every non-secret local setting**

Create `.env.example`:

```dotenv
APP_ENV=development
API_HOST=0.0.0.0
API_PORT=8000
WEB_ORIGIN=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
DATABASE_URL=postgresql+psycopg://textbook:textbook@postgres:5432/textbook
REDIS_URL=redis://redis:6379/0
OBJECT_STORAGE_ENDPOINT=http://minio:9000
OBJECT_STORAGE_ACCESS_KEY=textbook-local
OBJECT_STORAGE_SECRET_KEY=replace-for-non-local-use
OBJECT_STORAGE_BUCKET=textbook-assets
MINIO_ROOT_USER=textbook-local
MINIO_ROOT_PASSWORD=replace-for-non-local-use
```

Append these lines to `.gitignore`:

```gitignore
apps/api/.pytest_cache/
apps/api/.ruff_cache/
apps/web/coverage/
apps/web/.next/
```

- [ ] **Step 3: Verify the configuration has no real provider secrets**

Run:

```powershell
rg -n "sk-|dashscope|deepseek.*key" .env.example
```

Expected: no matches and exit code 1.

- [ ] **Step 4: Commit the repository contract**

```powershell
git add package.json pnpm-workspace.yaml .env.example .gitignore
git commit -m "chore: define platform workspace contract"
```

### Task 2: Build the FastAPI health slice with tests first

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/tutor_api/__init__.py`
- Create: `apps/api/src/tutor_api/core/__init__.py`
- Create: `apps/api/src/tutor_api/core/config.py`
- Create: `apps/api/src/tutor_api/main.py`
- Create: `apps/api/tests/test_config.py`
- Create: `apps/api/tests/test_health.py`

- [ ] **Step 1: Create the Python package metadata**

Create `apps/api/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "textbook-tutor-api"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.116,<1",
  "pydantic-settings>=2.10,<3",
  "psycopg[binary]>=3.2,<4",
  "redis>=6,<7",
  "sqlalchemy>=2.0,<3",
  "uvicorn[standard]>=0.35,<1"
]

[project.optional-dependencies]
dev = [
  "httpx>=0.28,<1",
  "pytest>=8.4,<9",
  "pytest-cov>=6.2,<7",
  "ruff>=0.12,<1"
]

[tool.hatch.build.targets.wheel]
packages = ["src/tutor_api"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

Create empty `apps/api/src/tutor_api/__init__.py` and `apps/api/src/tutor_api/core/__init__.py`.

- [ ] **Step 2: Write failing configuration tests**

Create `apps/api/tests/test_config.py`:

```python
from tutor_api.core.config import Settings


def test_settings_reject_non_local_default_object_secret() -> None:
    settings = Settings(
        app_env="production",
        object_storage_secret_key="replace-for-non-local-use",
    )
    errors = settings.production_errors()
    assert "OBJECT_STORAGE_SECRET_KEY must be replaced" in errors


def test_settings_accept_local_defaults_in_development() -> None:
    settings = Settings(app_env="development")
    assert settings.production_errors() == []
```

Run:

```powershell
& 'C:\Users\asus\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv apps/api/.venv
& 'apps\api\.venv\Scripts\python.exe' -m pip install -e 'apps/api[dev]'
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_config.py -q
```

Expected: FAIL because `tutor_api.core.config` does not exist.

- [ ] **Step 3: Implement validated settings**

Create `apps/api/src/tutor_api/core/config.py`:

```python
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"
    database_url: str = "sqlite:///./textbook-local.db"
    redis_url: str = "redis://localhost:6379/0"
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_access_key: str = "textbook-local"
    object_storage_secret_key: str = "replace-for-non-local-use"
    object_storage_bucket: str = "textbook-assets"

    def production_errors(self) -> list[str]:
        if self.app_env != "production":
            return []
        errors: list[str] = []
        if self.object_storage_secret_key == "replace-for-non-local-use":
            errors.append("OBJECT_STORAGE_SECRET_KEY must be replaced")
        if self.web_origin.startswith("http://"):
            errors.append("WEB_ORIGIN must use HTTPS")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Run the configuration test again. Expected: 2 passed.

- [ ] **Step 4: Write the failing health endpoint test**

Create `apps/api/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from tutor_api.main import create_app


def test_health_returns_public_status_only() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "textbook-tutor-api"}
    assert "database_url" not in response.text
```

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_health.py -q
```

Expected: FAIL because `tutor_api.main` does not exist.

- [ ] **Step 5: Implement the API factory and health route**

Create `apps/api/src/tutor_api/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tutor_api.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    app = FastAPI(title="Textbook Tutor API", version="0.1.0")
    app.state.settings = active_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[active_settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "textbook-tutor-api"}

    return app


app = create_app()
```

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests -q
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests
```

Expected: 3 passed; Ruff reports no errors.

- [ ] **Step 6: Commit the API slice**

```powershell
git add apps/api
git commit -m "feat: add validated FastAPI foundation"
```

### Task 3: Scaffold the Next.js app and its test runner

**Files:**
- Create: `apps/web/*` through the official scaffold
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Modify: `apps/web/package.json`
- Modify: `apps/web/src/app/page.tsx`

- [ ] **Step 1: Generate the app using the current stable scaffold**

Run:

```powershell
pnpm dlx create-next-app@latest apps/web --ts --eslint --tailwind --app --src-dir --import-alias '@/*' --use-pnpm --yes
pnpm --dir apps/web add react-resizable-panels@4.9.0
pnpm --dir apps/web add -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Expected: `apps/web/package.json`, `src/app`, and `pnpm-lock.yaml` exist; dependency installation succeeds.

- [ ] **Step 2: Add deterministic test scripts**

Add these keys to `apps/web/package.json` under `scripts`:

```json
"test": "vitest run",
"test:watch": "vitest"
```

Create `apps/web/vitest.config.ts`:

```typescript
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig } from "vitest/config";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
  resolve: {
    alias: { "@": path.resolve(rootDir, "./src") },
  },
});
```

Create `apps/web/src/test/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;
```

- [ ] **Step 3: Replace the generated landing page with an explicit temporary entry**

Replace `apps/web/src/app/page.tsx` with:

```tsx
export default function HomePage() {
  return <main>教材知识库工作台</main>;
}
```

Run:

```powershell
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: both commands succeed.

- [ ] **Step 4: Commit the web scaffold**

```powershell
git add apps/web pnpm-lock.yaml package.json pnpm-workspace.yaml
git commit -m "feat: scaffold tested Next.js workspace"
```

### Task 4: Implement the approved C3 shell test first

**Files:**
- Create: `apps/web/src/components/workspace/workspace-shell.test.tsx`
- Create: `apps/web/src/components/workspace/workspace-shell.tsx`
- Create: `apps/web/src/components/workspace/workspace-shell.module.css`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Write the failing structural test**

Create `apps/web/src/components/workspace/workspace-shell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkspaceShell } from "./workspace-shell";

describe("WorkspaceShell", () => {
  it("keeps spaces in the far-left rail and content in the second pane", () => {
    render(<WorkspaceShell />);

    const rail = screen.getByLabelText("空间切换");
    const tree = screen.getByLabelText("当前空间内容");
    expect(rail).toHaveTextContent("个人空间");
    expect(rail).toHaveTextContent("七年级数学");
    expect(tree).toHaveTextContent("教材与练习");
    expect(tree).toHaveTextContent("知识图谱");
    expect(tree).not.toHaveTextContent("个人空间");
  });

  it("renders three keyboard-accessible resizable content panes", () => {
    render(<WorkspaceShell />);
    expect(screen.getByLabelText("当前空间内容")).toBeInTheDocument();
    expect(screen.getByLabelText("知识工作区")).toBeInTheDocument();
    expect(screen.getByLabelText("AI 家教")).toBeInTheDocument();
    expect(screen.getAllByRole("separator")).toHaveLength(2);
  });
});
```

Run:

```powershell
pnpm --dir apps/web test -- workspace-shell.test.tsx
```

Expected: FAIL because `workspace-shell.tsx` does not exist.

- [ ] **Step 2: Implement the four-column shell**

Create `apps/web/src/components/workspace/workspace-shell.tsx`:

```tsx
"use client";

import { Group, Panel, Separator } from "react-resizable-panels";

import styles from "./workspace-shell.module.css";

const treeItems = ["教材与练习", "数学上册.pdf", "同步练习.pdf", "知识图谱", "AI 笔记", "错题集", "题库"];

export function WorkspaceShell() {
  return (
    <main className={styles.shell}>
      <nav aria-label="空间切换" className={styles.spaceRail}>
        <button className={styles.brand} aria-label="平台首页">知</button>
        <button className={styles.spaceButton} aria-label="个人空间">我</button>
        <button className={`${styles.spaceButton} ${styles.active}`} aria-label="七年级数学">七</button>
        <button className={styles.spaceButton} aria-label="创建或加入班级">+</button>
      </nav>

      <Group className={styles.panelGroup} defaultLayout={{ tree: 22, center: 50, tutor: 28 }}>
        <Panel id="tree" minSize="16%" maxSize="34%">
          <aside aria-label="当前空间内容" className={styles.treePane}>
            <header><span>七年级数学</span><button aria-label="空间设置">•••</button></header>
            <ul>{treeItems.map((item) => <li key={item}>{item}</li>)}</ul>
          </aside>
        </Panel>
        <Separator className={styles.separator} />
        <Panel id="center" minSize="30%">
          <section aria-label="知识工作区" className={styles.centerPane}>
            <div className={styles.tabs}><button className={styles.selectedTab}>知识图谱</button><button>教材原页</button><button>AI 笔记</button></div>
            <div className={styles.emptyState}><strong>知识工作区</strong><span>选择教材、笔记、题目或关系节点后在这里查看。</span></div>
          </section>
        </Panel>
        <Separator className={styles.separator} />
        <Panel id="tutor" minSize="20%" maxSize="42%">
          <aside aria-label="AI 家教" className={styles.tutorPane}>
            <header><strong>AI 家教</strong><button>完整解答</button></header>
            <div className={styles.answer}>选择教材内容或直接提出问题。回答将在这里显示来源与费用。</div>
            <label>提问<textarea aria-label="向 AI 家教提问" placeholder="输入你的问题…" /></label>
          </aside>
        </Panel>
      </Group>
    </main>
  );
}
```

- [ ] **Step 3: Apply the approved dark Obsidian-like visual hierarchy**

Create `apps/web/src/components/workspace/workspace-shell.module.css`:

```css
.shell { display: flex; height: 100dvh; overflow: hidden; background: #111318; color: #e8e9ef; }
.spaceRail { width: 64px; flex: 0 0 64px; padding: 12px 9px; border-right: 1px solid #2d3038; background: #17191f; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.brand, .spaceButton { width: 40px; height: 40px; border: 1px solid #353944; border-radius: 12px; background: #23262e; color: #d9dbe3; cursor: pointer; }
.brand { background: linear-gradient(135deg, #6f63d8, #49b7ad); color: white; font-weight: 700; }
.spaceButton.active { border-color: #877ae6; background: #393550; color: white; }
.spaceButton:last-child { margin-top: auto; }
.panelGroup { flex: 1; min-width: 0; }
.separator { width: 5px; background: #242730; outline: none; transition: background .15s; }
.separator:hover, .separator[data-resize-handle-active] { background: #776bd8; }
.treePane, .centerPane, .tutorPane { height: 100%; min-width: 0; }
.treePane { padding: 15px 12px; background: #1b1e25; }
.treePane header, .tutorPane header { display: flex; align-items: center; justify-content: space-between; min-height: 34px; }
.treePane header button, .tutorPane header button, .tabs button { border: 0; border-radius: 7px; background: #2a2d36; color: #cfd1da; padding: 7px 9px; }
.treePane ul { list-style: none; margin: 12px 0 0; padding: 0; }
.treePane li { padding: 9px 10px; border-radius: 8px; color: #c7c9d1; }
.treePane li:nth-child(4) { background: #3a3652; color: white; }
.centerPane { display: flex; flex-direction: column; background: #12151b; }
.tabs { height: 49px; border-bottom: 1px solid #2e323c; display: flex; align-items: center; gap: 6px; padding: 0 12px; }
.tabs .selectedTab { background: #3a3652; color: white; }
.emptyState { flex: 1; display: grid; place-content: center; gap: 8px; text-align: center; color: #8f95a2; padding: 24px; }
.emptyState strong { color: #d9dce5; font-size: 20px; }
.tutorPane { display: flex; flex-direction: column; gap: 14px; padding: 15px; background: #191c23; }
.answer { flex: 1; border: 1px solid #303540; border-radius: 12px; background: #20242c; padding: 14px; color: #aeb3bf; line-height: 1.6; }
.tutorPane label { display: grid; gap: 7px; color: #9ea3af; font-size: 12px; }
.tutorPane textarea { min-height: 92px; resize: none; border: 1px solid #3a3f4c; border-radius: 12px; background: #11141a; color: white; padding: 12px; }
@media (max-width: 900px) { .spaceRail { width: 54px; flex-basis: 54px; } }
```

- [ ] **Step 4: Make the workspace the application entry**

Replace `apps/web/src/app/page.tsx` with:

```tsx
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export default function HomePage() {
  return <WorkspaceShell />;
}
```

Replace `apps/web/src/app/globals.css` with:

```css
@import "tailwindcss";

* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body { font-family: Inter, "Microsoft YaHei", system-ui, sans-serif; }
button, textarea { font: inherit; }
```

Run:

```powershell
pnpm --dir apps/web test -- workspace-shell.test.tsx
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: 2 tests pass; lint and production build succeed.

- [ ] **Step 5: Commit the C3 shell**

```powershell
git add apps/web/src
git commit -m "feat: add resizable C3 learning workspace"
```

### Task 5: Add container definitions without hiding missing Docker

**Files:**
- Create: `apps/api/Dockerfile`
- Create: `apps/web/Dockerfile`
- Create: `compose.yaml`

- [ ] **Step 1: Create the API image**

Create `apps/api/Dockerfile`:

```dockerfile
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "tutor_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create the web image**

Create `apps/web/Dockerfile`:

```dockerfile
FROM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /app
COPY --from=build /app ./
EXPOSE 3000
CMD ["pnpm", "start"]
```

- [ ] **Step 3: Define the local service graph**

Create `compose.yaml`:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: textbook
      POSTGRES_USER: textbook
      POSTGRES_PASSWORD: textbook
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U textbook -d textbook"]
      interval: 5s
      timeout: 3s
      retries: 20
    volumes:
      - postgres-data:/var/lib/postgresql/data

  redis:
    image: redis:7.4-alpine
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20
    volumes:
      - redis-data:/data

  minio:
    image: quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z
    command: server /data --console-address :9001
    env_file: .env
    ports:
      - "9001:9001"
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 3s
      retries: 20
    volumes:
      - minio-data:/data

  api:
    build: ./apps/api
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  web:
    build: ./apps/web
    env_file: .env
    ports:
      - "3000:3000"
    depends_on:
      - api

volumes:
  postgres-data:
  redis-data:
  minio-data:
```

- [ ] **Step 4: Validate according to actual Docker availability**

Run:

```powershell
docker compose version
```

Expected on the currently checked machine: command not found. Record this as an external prerequisite; do not claim Docker verification. After Docker Desktop is installed, run:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose build api web
```

Expected after installation: configuration validation and both builds succeed. Delete `.env` only if it contains no user-supplied values; otherwise leave it untouched and untracked.

- [ ] **Step 5: Commit container definitions**

```powershell
git add apps/api/Dockerfile apps/web/Dockerfile compose.yaml
git commit -m "chore: add local container topology"
```

### Task 6: Add automated quality gates

**Files:**
- Create: `.github/workflows/quality.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/quality.yml`:

```yaml
name: quality
on:
  push:
  pull_request:
jobs:
  api:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e "apps/api[dev]"
      - run: python -m ruff check apps/api/src apps/api/tests
      - run: python -m pytest apps/api/tests --cov=tutor_api --cov-fail-under=90
  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with: { version: 11.19.0 }
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm --dir apps/web test
      - run: pnpm --dir apps/web lint
      - run: pnpm --dir apps/web build
```

- [ ] **Step 2: Run the same gates locally**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests --cov=tutor_api --cov-fail-under=90
pnpm --dir apps/web test
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: every command exits 0; API coverage is at least 90%.

- [ ] **Step 3: Commit quality gates**

```powershell
git add .github/workflows/quality.yml
git commit -m "ci: enforce API and web quality gates"
```

### Task 7: Document exact local startup paths

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the local handoff**

Create `README.md`:

````markdown
# AI 教材家教平台

当前交付为平台基础骨架：FastAPI 健康接口、Next.js C3 可拖动工作台，以及 PostgreSQL/pgvector、Redis、MinIO 的本机容器定义。账号、班级、计费和知识库将在后续里程碑加入。

## 不使用 Docker 的开发检查

```powershell
& 'C:\Users\asus\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv apps/api/.venv
& 'apps\api\.venv\Scripts\python.exe' -m pip install -e 'apps/api[dev]'
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests
pnpm install
pnpm --dir apps/web test
pnpm --dir apps/web dev
```

访问 `http://localhost:3000` 查看工作台。

## Docker 本机启动

安装并启动 Docker Desktop 后：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

- Web：`http://localhost:3000`
- API 健康检查：`http://localhost:8000/api/v1/health`
- MinIO 管理页：`http://localhost:9001`

`.env` 只保存在本机。不要把真实 API Key 提交到 Git。
````

- [ ] **Step 2: Check that user-facing documentation does not expose internal workflow noise**

Run:

```powershell
rg -n "Agent Loop|Embedding 步骤|OCR 步骤|API_KEY=" README.md apps/web/src
```

Expected: no matches and exit code 1.

- [ ] **Step 3: Commit the handoff**

```powershell
git add README.md
git commit -m "docs: add local foundation startup guide"
```

### Task 8: Final foundation verification

**Files:**
- Modify only files required to fix failures discovered by the commands below.

- [ ] **Step 1: Run the clean quality suite**

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests --cov=tutor_api --cov-fail-under=90
pnpm --dir apps/web test
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: all checks pass.

- [ ] **Step 2: Verify the API without Docker**

Start the API in a background terminal:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m uvicorn tutor_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000
```

In another terminal run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Expected: `status` is `ok` and `service` is `textbook-tutor-api`. Stop the foreground API with Ctrl+C.

- [ ] **Step 3: Verify the web workspace manually**

Run:

```powershell
pnpm --dir apps/web dev
```

Open `http://localhost:3000`. Expected: the far-left rail contains personal/class spaces; the second pane contains the current-space tree; both separators resize the tree, center, and tutor areas; no internal ingestion or Agent steps are shown. Stop the dev server with Ctrl+C.

- [ ] **Step 4: Inspect repository state and commit only verified fixes**

```powershell
git status --short
git diff --check
```

Expected: no accidental `.env`, virtual environment, build output, or provider secret is tracked. If verification required code changes, commit them with:

```powershell
git add apps/api apps/web README.md compose.yaml .github/workflows/quality.yml
git commit -m "fix: complete foundation verification"
```

If no fixes were needed, do not create an empty commit.

## Completion boundary

This plan is complete only when API tests, web tests, lint, and web build pass; the local API health endpoint responds; and the approved C3 shell is visible and resizable. Docker build verification remains explicitly pending until Docker Desktop is installed and running. The next detailed plan adds opaque-session authentication, personal-space bootstrap, classroom membership, invitation codes, and server-enforced permissions on top of this verified foundation.
