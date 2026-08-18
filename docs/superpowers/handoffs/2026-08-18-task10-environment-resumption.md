# Task 10 Environment Resumption Handoff

**Date:** 2026-08-18  
**Worktree:** `E:\项目\知识库课本\.worktrees\platform-foundation`  
**Branch:** `feature/platform-foundation`  
**Status:** preparation only. Task 10, Milestone 3, and Phase 5 remain `in_progress`.

This document supplements—not replaces—`2026-08-18-task10-verification-blocked.md`. It is deliberately operational: a new session must obtain the missing access information below before it runs any live validation. No credential belongs in this file, Git, chat logs, or a committed `.env`.

## Immutable recovery point

- `a0f6bb7 docs: terminate Task 10 handoff` on `feature/platform-foundation` is the last committed, clean baseline **before the dedicated commit for this supplemental handoff**.
- Before any live new-session execution, this reviewed document must be present in its own dedicated handoff-record commit, and the feature worktree must be clean; record that resulting commit hash in the next handoff.
- If this document is still uncommitted, recovery is only `a0f6bb7` **plus this explicitly uncommitted handoff file**. That state is not clean and must not be described as a clean recovery point.
- Root `E:\项目\知识库课本` intentionally has uncommitted planning records only: `task_plan.md`, `findings.md`, and `progress.md`. Do not reset, stash, stage, or commit them.
- Do not create `docs: record versioned knowledge delivery` until every Task 10 gate below passes.

## Information the user must supply before live validation

Do not guess paths or silently install tools. **Route A is required to complete Task 10 because Gate 2 is a mandatory Docker Compose vertical slice. Route B can unblock only Gate 1 (the real PostgreSQL/pgvector migration round-trip); it can never substitute for Route A or satisfy Gate 2.**

### Route A — local Docker Compose (preferred)

1. Exact Docker CLI entry point: either a command available on `PATH` or an absolute executable path.
2. Confirmation that Docker Desktop is started, plus the command that proves the daemon is ready (for example, a successful `docker version` / `docker info`).
3. Confirmation that Docker Compose v2 is available through `& $DockerCli compose`; every Compose invocation must use the same absolute `$DockerCli` and unique explicit `$ComposeProject`.
4. Permission to create an **isolated local** Compose data set in this feature worktree. It must use the generated `$ComposeProject`, must not share production or irreplaceable development volumes, and must be recorded in the gate evidence.

The repository's Compose topology includes `postgres` (pgvector), `redis`, `minio`, `minio-init`, `api`, `worker`, and `web`. The documented startup entry point is:

```powershell
Set-Location 'E:\项目\知识库课本\.worktrees\platform-foundation'
$DockerCli = 'C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
if (-not (Test-Path -LiteralPath $DockerCli -PathType Leaf)) {
    throw "Docker CLI is unavailable at $DockerCli. Obtain the exact Docker Desktop CLI path before continuing."
}
& $DockerCli version
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop is not ready; do not start Task 10 validation.'
}
$ComposeProject = "task10-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
# Record this exact $ComposeProject value in the gate evidence. Never reuse or attach to a shared project or volumes.
if (Test-Path -LiteralPath '.env') {
    throw '.env already exists. Review it manually; never overwrite local secrets or environment-specific configuration.'
}
git check-ignore --quiet -- .env
if ($LASTEXITCODE -ne 0) {
    throw '.env is not confirmed as Git-ignored. Do not create it until that protection is restored.'
}
Copy-Item -LiteralPath '.env.example' -Destination '.env' -ErrorAction Stop
# Fill every replace-with-long-random-* value in .env locally; never commit it.
& $DockerCli compose --project-name $ComposeProject --env-file .env up --build -d
& $DockerCli compose --project-name $ComposeProject --env-file .env ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

`POSTGRES_PASSWORD` must match `DATABASE_URL`; `REDIS_PASSWORD` must match `REDIS_URL`; the MinIO root and application identities must be distinct. See `README.md` and `.env.example`; do not paste the resulting values into a handoff.

### Route B — separately provisioned PostgreSQL/pgvector (Gate 1 only)

Supply all of the following instead:

- host, port, database name, username, authentication method, SSL requirement, and a secure way to provide the password/connection string to the process;
- proof that the server is a real PostgreSQL instance with pgvector enabled and that the database is isolated for this Task 10 round-trip;
- exact paths or invocations for any required client tools (`psql`, `pg_isready`, `initdb`), if they are part of the selected procedure;
- the owner and safe cleanup rule for the isolated database.

Never point migrations or cleanup at a shared or production database. This route can validate only the migration round-trip. Even if Gate 1 passes through Route B, Task 10 remains incomplete until Route A provides an isolated Docker Compose runtime and the separate Compose vertical slice passes.

## Mandatory gates after access is supplied

### 1. Real PostgreSQL/pgvector migration round-trip

`python -m alembic -c alembic.ini heads` already passed only for the revision graph. It is not a database round-trip and must not be used as a substitute.

For a fresh **isolated** Compose database, first verify the stack is healthy, then run the migration commands inside the API container:

```powershell
& $DockerCli compose --project-name $ComposeProject --env-file .env exec api python -m alembic -c alembic.ini current
& $DockerCli compose --project-name $ComposeProject --env-file .env exec api python -m alembic -c alembic.ini downgrade 0005_reversal_audit_group
& $DockerCli compose --project-name $ComposeProject --env-file .env exec api python -m alembic -c alembic.ini upgrade head
& $DockerCli compose --project-name $ComposeProject --env-file .env exec api python -m alembic -c alembic.ini current
```

The downgrade is schema-destructive unless the database is disposable; it is allowed only after the isolation condition above is met. For a separately provisioned database, use the equivalent verified `DATABASE_URL` procedure and record the exact commands before executing it.

Capture: connection route (without credentials), starting revision, downgrade target, final head, exit status, and a redacted command transcript.

### 2. Compose vertical slice

This gate requires Route A and an isolated Docker Compose environment; a separately provisioned PostgreSQL/pgvector instance from Route B cannot run or replace it. Prove this sequence using the API cookie-auth flow:

```text
register
→ obtain personal space
→ create knowledge base
→ upload deterministic Markdown and PDF
→ poll until the knowledge base is READY
→ search
→ successfully call GET /api/v1/knowledge-bases/{knowledge_base_id}/citations/{citation_id}/page for the deterministic PDF citation
→ optionally retrieve the authorized source preview as additional evidence only
```

Relevant endpoints are:

```text
POST /api/v1/auth/register
GET  /api/v1/spaces
POST /api/v1/spaces/{space_id}/knowledge-bases
GET  /api/v1/knowledge-bases/{knowledge_base_id}
POST /api/v1/knowledge-bases/{knowledge_base_id}/documents
POST /api/v1/knowledge-bases/{knowledge_base_id}/search
GET  /api/v1/knowledge-bases/{knowledge_base_id}/citations/{citation_id}/source
GET  /api/v1/knowledge-bases/{knowledge_base_id}/citations/{citation_id}/page
```

Use deterministic locally generated Markdown and PDF inputs, not external files. Preserve redacted request/response evidence, the READY polling result, search citations, and a successful `GET /api/v1/knowledge-bases/{knowledge_base_id}/citations/{citation_id}/page` response for the deterministic PDF citation. An authorized source preview may be retained as additional evidence only; it never substitutes for opening that cited PDF page. Do not expose session cookies, passwords, access keys, or object-store URLs with secrets.

### 3. Full API coverage gate

This gate remains separate from Docker availability. It previously failed at `88.08%` against the configured `90%` threshold:

```text
590 passed, 3 skipped, 2 failed
```

The failures were:

```text
test_tesseract_timeout_kills_descendant_holding_pipes
test_tesseract_timeout_kills_descendant_inheriting_only_stdin
```

After a targeted root-cause fix and its focused tests—not before—run the complete coverage gate from `apps/api` with the coverage data redirected outside the worktree and pytest cache disabled:

```powershell
$hadCoverageFile = Test-Path Env:COVERAGE_FILE
$previousCoverageFile = if ($hadCoverageFile) { $env:COVERAGE_FILE } else { $null }
try {
    $env:COVERAGE_FILE = Join-Path $env:TEMP 'task10-api-coverage'
    python -m pytest --cov=tutor_api --cov-report=term-missing --cov-fail-under=90 -p no:cacheprovider
}
finally {
    if ($hadCoverageFile) {
        $env:COVERAGE_FILE = $previousCoverageFile
    }
    else {
        Remove-Item Env:COVERAGE_FILE -ErrorAction SilentlyContinue
    }
}
```

Do not lower the coverage threshold or weaken the two Windows OCR timeout tests merely to get a pass.

## Isolated Compose cleanup (opt-in, only after evidence collection)

Do **not** run cleanup before every required command result and redacted evidence have been saved. After evidence collection, and only when the recorded `$ComposeProject` is confirmed to be the unique Task 10 project created above, an operator may intentionally destroy that isolated test stack and its project-owned volumes:

```powershell
& $DockerCli compose --project-name $ComposeProject --env-file .env down -v --remove-orphans
```

`-v` is destructive: it deletes data for that isolated Task 10 project. Never substitute another project name, omit `--project-name`, or use this command against shared, development, or production volumes.
## Evidence already accepted; do not repeat without a concrete reason

```text
pnpm test:web                                      PASS — 7 files / 34 tests
pnpm lint:web                                      PASS
pnpm build:web                                     PASS
python -m ruff check --no-cache src tests          PASS
python -m pytest tests/test_knowledge_ocr.py \
  -p no:cacheprovider -vv                          PASS — 49 tests
python -m alembic -c alembic.ini heads             PASS — 0008_embedding_contract
```

The focused OCR pass does not erase the complete coverage failure. The existing blocker details, supported-format evidence, and application limits remain in `2026-08-18-task10-verification-blocked.md`.

## Separate Milestone 4 preservation

Do not conflate Task 10 acceptance with the subsequent Tutor milestone. The product choice is now **A: a formally billable Tutor model**, but the following still require user confirmation before Milestone 4 can receive an approved implementation design:

```text
specific provider / specific model
server-verifiable real usage response
protocol and streaming requirement
initial price snapshot and FX snapshot owner
```

Until these are confirmed, do not enable production billing or implement a real remote Tutor provider.

## Required closeout update

After each live gate, update the root planning records incrementally and run:

```powershell
git -C 'E:\项目\知识库课本' diff --check -- task_plan.md findings.md progress.md
```

Only after every Task 10 gate passes may a fresh review sequence decide whether the delivery record and completion commit are warranted.

## Skills for the next session

Use `planning-with-files`, `context-restore`, `subagent-driven-development`, `karpathy-guidelines`, and `verification-before-completion`. Use a fresh independent specification reviewer before any fix and a separate quality/security reviewer only after the specification review passes.