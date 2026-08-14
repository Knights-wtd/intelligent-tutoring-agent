# Identity, Personal Spaces, and Classrooms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver password registration and login, revocable HttpOnly sessions, automatic personal spaces, classrooms, invitation codes, and server-enforced membership roles.

**Architecture:** Keep identity and tenancy in the FastAPI modular monolith. A PostgreSQL-backed opaque session stores only a random cookie value at the browser; its SHA-256 digest, expiry and revocation state are stored server-side. Every classroom operation resolves the current session and verifies a membership role in the database, so neither page visibility nor a client-provided role grants access.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL 17, argon2-cffi, pytest/httpx, Next.js/React/TypeScript, Vitest/Testing Library.

---

## Locked file structure

```text
apps/api/
├── alembic.ini
├── migrations/{env.py,script.py.mako,versions/0001_identity.py}
├── src/tutor_api/
│   ├── core/{config.py,database.py,security.py}
│   ├── identity/{models.py,repository.py,schemas.py,service.py,router.py}
│   ├── spaces/{models.py,schemas.py,service.py,router.py}
│   ├── classrooms/{models.py,schemas.py,service.py,router.py}
│   └── main.py
└── tests/{conftest.py,test_auth.py,test_spaces.py,test_classrooms.py}
apps/web/src/
├── app/{page.tsx,login/page.tsx,register/page.tsx}
├── components/auth/{auth-form.tsx,auth-form.test.tsx}
└── components/workspace/{workspace-shell.tsx,workspace-shell.test.tsx}
```

The database holds `users`, `spaces`, `classrooms`, `classroom_memberships`, `classroom_invites`, and `sessions`. `spaces.kind` is either `personal` or `classroom`; a personal space has exactly one owner and is created in the same transaction as its user. Class membership is the sole authority for classroom access. `owner`, `teacher`, and `student` are stored roles; only the owner may manage teachers or transfer ownership.

### Task 1: Establish migration, database-session, and password primitives

**Status:** complete

**Files:**
- Modify: `apps/api/pyproject.toml`, `apps/api/requirements.lock`, `apps/api/build-requirements.lock`, `apps/api/src/tutor_api/core/config.py`
- Create: `apps/api/src/tutor_api/core/database.py`, `apps/api/src/tutor_api/core/security.py`, `apps/api/alembic.ini`, `apps/api/migrations/env.py`, `apps/api/migrations/script.py.mako`
- Test: `apps/api/tests/test_security.py`, `apps/api/tests/test_database.py`

- [ ] **Step 1: Write failing password and database URL tests**

```python
from tutor_api.core.security import hash_password, verify_password

def test_password_hash_never_equals_plaintext() -> None:
    password_hash = hash_password("Correct horse battery staple 9")
    assert password_hash != "Correct horse battery staple 9"
    assert verify_password("Correct horse battery staple 9", password_hash)
    assert not verify_password("wrong password", password_hash)
```

```python
from tutor_api.core.database import create_engine_from_url

def test_create_engine_rejects_sqlite_outside_test_mode() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_engine_from_url("sqlite:///local.db", app_env="development")
```

- [ ] **Step 2: Run the targeted tests and verify RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_security.py apps/api/tests/test_database.py -q -p no:cacheprovider`

Expected: collection fails because the `security` and `database` modules do not exist.

- [ ] **Step 3: Add the minimal primitives and exact dependencies**

Add `argon2-cffi==25.1.0` and `alembic==1.16.5` to the API runtime lock files and bounded compatible constraints to `pyproject.toml`. In `security.py`, construct one `argon2.PasswordHasher`, expose `hash_password(password: str) -> str`, and return `False` for an invalid hash or password mismatch. In `database.py`, allow SQLite only when `app_env == "test"`; otherwise require a `postgresql+psycopg` URL, create a SQLAlchemy engine with `pool_pre_ping=True`, and provide a `session_scope` context manager that commits on success and rolls back on errors.

- [ ] **Step 4: Run RED tests plus lint and verify GREEN**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests --no-cache
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_security.py apps/api/tests/test_database.py -q -p no:cacheprovider
```

Expected: both tests pass and Ruff exits 0.

- [ ] **Step 5: Commit the primitives**

```powershell
git add apps/api/pyproject.toml apps/api/requirements.lock apps/api/build-requirements.lock apps/api/src/tutor_api/core apps/api/tests/test_security.py apps/api/tests/test_database.py apps/api/alembic.ini apps/api/migrations
git commit -m "feat: add database and password primitives"
```

### Task 2: Define the tenant schema and apply the initial migration

**Status:** in_progress

**Files:**
- Create: `apps/api/src/tutor_api/identity/models.py`, `apps/api/src/tutor_api/spaces/models.py`, `apps/api/src/tutor_api/classrooms/models.py`, `apps/api/migrations/versions/0001_identity.py`
- Modify: `apps/api/migrations/env.py`
- Test: `apps/api/tests/test_schema.py`

- [ ] **Step 1: Write a failing schema test**

```python
def test_registration_schema_enforces_one_personal_space_per_owner(session) -> None:
    user = User(email="teacher@example.com", username="teacher", password_hash="hash")
    session.add(user)
    session.flush()
    session.add_all([
        Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="我的空间"),
        Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="第二空间"),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run it and verify RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_schema.py -q -p no:cacheprovider`

Expected: collection fails because the tenant models do not exist.

- [ ] **Step 3: Implement the schema and migration**

Use UUID primary keys and UTC timestamps. Add a partial unique index that permits one `personal` space per `owner_id`; add unique lowercase-email and lowercase-username indexes; forbid a classroom membership without a matching classroom space through service creation, and give each classroom a unique `space_id`. A classroom stores `owner_id`, display name and creation timestamp. Membership has unique `(classroom_id, user_id)` and role values `owner`, `teacher`, `student`. An invite stores a SHA-256 code digest, role `student`, expiry, maximum uses, use count and revocation timestamp. A session stores `user_id`, a SHA-256 token digest, expiry, revoked timestamp and creation timestamp. The Alembic migration creates exactly these tables, constraints and indexes; `downgrade()` drops them in reverse dependency order.

- [ ] **Step 4: Verify schema behavior and migration upgrade**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m alembic -c apps/api/alembic.ini upgrade head
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_schema.py -q -p no:cacheprovider
```

Expected: upgrade completes and the duplicate personal-space transaction raises `IntegrityError`.

- [ ] **Step 5: Commit the schema**

```powershell
git add apps/api/src/tutor_api/identity/models.py apps/api/src/tutor_api/spaces/models.py apps/api/src/tutor_api/classrooms/models.py apps/api/migrations apps/api/tests/test_schema.py
git commit -m "feat: add identity and classroom schema"
```

### Task 3: Implement registration, opaque sessions, and logout

**Files:**
- Create: `apps/api/src/tutor_api/identity/{schemas.py,repository.py,service.py,router.py}`
- Modify: `apps/api/src/tutor_api/main.py`, `apps/api/src/tutor_api/core/config.py`
- Test: `apps/api/tests/test_auth.py`

- [ ] **Step 1: Write failing endpoint tests**

```python
def test_register_creates_personal_space_and_session(client) -> None:
    response = client.post("/api/v1/auth/register", json={
        "email": "learner@example.com", "username": "learner", "password": "Correct horse battery staple 9",
    })
    assert response.status_code == 201
    assert response.json()["user"]["username"] == "learner"
    assert "session" in response.headers["set-cookie"]
    assert response.json()["personal_space"]["kind"] == "personal"

def test_logout_revokes_cookie_before_future_requests(client) -> None:
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
```

- [ ] **Step 2: Run the auth tests and verify RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_auth.py -q -p no:cacheprovider`

Expected: 404 responses because the auth router is not registered.

- [ ] **Step 3: Implement the smallest complete authentication flow**

Require a normalized unique email, a 3–32 character username, and a password of at least 12 characters. `POST /api/v1/auth/register` hashes the password, creates the user and `我的空间` in one transaction, then creates a 32-byte URL-safe random session token. Store only `sha256(token)` and set `session=<token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800`; set `Secure` when `app_env == "production"`. `POST /login` verifies the Argon2 hash without revealing whether email or password failed. `GET /me` returns only id, email, username and personal-space summary. `POST /logout` revokes the current record and clears the cookie. A dependency returns 401 for missing, expired or revoked sessions; passwords, raw session tokens and hashes never enter a response or log.

- [ ] **Step 4: Verify GREEN and negative cases**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_auth.py -q -p no:cacheprovider
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests --no-cache
```

Expected: registration, duplicate identity, invalid password, wrong login, logout, expired/revoked session and `me` tests all pass.

- [ ] **Step 5: Commit authentication**

```powershell
git add apps/api/src/tutor_api/identity apps/api/src/tutor_api/main.py apps/api/src/tutor_api/core/config.py apps/api/tests/test_auth.py
git commit -m "feat: add revocable cookie authentication"
```

### Task 4: Expose personal spaces and enforce classroom roles

**Files:**
- Create: `apps/api/src/tutor_api/spaces/{schemas.py,service.py,router.py}`, `apps/api/src/tutor_api/classrooms/{schemas.py,service.py,router.py}`
- Modify: `apps/api/src/tutor_api/main.py`
- Test: `apps/api/tests/test_spaces.py`, `apps/api/tests/test_classrooms.py`

- [ ] **Step 1: Write failing access-control tests**

```python
def test_student_cannot_read_a_classroom_without_membership(client, owner_cookie) -> None:
    classroom = create_classroom(client, owner_cookie, "七年级数学")
    response = client.get(f"/api/v1/classrooms/{classroom['id']}")
    assert response.status_code == 404

def test_only_owner_can_promote_a_teacher(client, owner_cookie, teacher_cookie) -> None:
    classroom = create_classroom(client, owner_cookie, "七年级数学")
    join_classroom(client, teacher_cookie, classroom["invite_code"])
    response = client.patch(f"/api/v1/classrooms/{classroom['id']}/members/{teacher_id}", json={"role": "teacher"})
    assert response.status_code == 403
```

- [ ] **Step 2: Run the access tests and verify RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_spaces.py apps/api/tests/test_classrooms.py -q -p no:cacheprovider`

Expected: 404 because the routes do not exist.

- [ ] **Step 3: Implement space and classroom endpoints**

Add `GET /api/v1/spaces` for the current user’s personal space and enrolled classroom spaces. Add `POST /api/v1/classrooms` for any signed-in user; it creates classroom, classroom space, owner membership and a one-use student invite atomically, returning the plaintext invite code only in this response. Add `POST /api/v1/classrooms/join` which consumes a non-expired non-revoked invite only once, never joins a user twice, and increments use count atomically. Add `GET /api/v1/classrooms/{id}` that returns 404 to non-members. Add `PATCH /members/{user_id}`: owner may promote/demote teachers and remove members; teachers may not change any role; the owner cannot be removed or demoted by this endpoint. Add `POST /invites` for owner or teacher with a bounded expiry and maximum uses. Return 403 for authenticated but unauthorized mutations and 404 for unreadable classroom resources.

- [ ] **Step 4: Verify GREEN including role matrix**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_spaces.py apps/api/tests/test_classrooms.py -q -p no:cacheprovider
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests -q -p no:cacheprovider
```

Expected: owner, teacher, student, outsider, expired invite, reused invite, duplicate join and protected-owner cases pass.

- [ ] **Step 5: Commit spaces and classrooms**

```powershell
git add apps/api/src/tutor_api/spaces apps/api/src/tutor_api/classrooms apps/api/src/tutor_api/main.py apps/api/tests/test_spaces.py apps/api/tests/test_classrooms.py
git commit -m "feat: add personal spaces and classroom permissions"
```

### Task 5: Connect the C3 shell to authenticated space summaries

**Files:**
- Create: `apps/web/src/components/auth/{auth-form.tsx,auth-form.test.tsx}`, `apps/web/src/lib/api.ts`
- Create: `apps/web/src/app/{login/page.tsx,register/page.tsx}`
- Modify: `apps/web/src/app/page.tsx`, `apps/web/src/components/workspace/{workspace-shell.tsx,workspace-shell.test.tsx}`

- [ ] **Step 1: Write failing UI tests**

```tsx
it("redirects an anonymous visitor to the login page", async () => {
  mockApi.me.mockResolvedValue(null);
  render(<HomePage />);
  expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
});

it("renders the authenticated user’s personal and classroom spaces in the left rail", async () => {
  mockApi.me.mockResolvedValue({ user: { username: "learner" } });
  mockApi.spaces.mockResolvedValue([{ id: "p1", kind: "personal", name: "我的空间" }, { id: "c1", kind: "classroom", name: "七年级数学" }]);
  render(<WorkspaceShell />);
  expect(await screen.findByLabelText("个人空间")).toBeInTheDocument();
  expect(screen.getByLabelText("七年级数学")).toBeInTheDocument();
  expect(screen.getAllByRole("separator")).toHaveLength(2);
});
```

- [ ] **Step 2: Run the UI tests and verify RED**

Run: `pnpm --dir apps/web test -- auth-form.test.tsx workspace-shell.test.tsx`

Expected: tests fail because the client and auth components do not exist.

- [ ] **Step 3: Implement the minimal user-facing flow**

Create a same-origin API client with `credentials: "include"`; it must never store a token in localStorage. Render short Chinese registration and login forms, display neutral failure text for rejected login, and redirect a successful user to `/`. `page.tsx` shows login for an anonymous response and passes fetched space summaries into `WorkspaceShell`. Preserve the current two `Separator` elements and all three resizable content panes. Space buttons select the current space and update the second-pane heading; ordinary users see no database, session, OCR, embedding or internal Agent details.

- [ ] **Step 4: Verify GREEN, lint, and production build**

Run:

```powershell
pnpm --dir apps/web test
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: all existing and new UI tests pass, lint exits 0 and the production build succeeds.

- [ ] **Step 5: Commit authenticated workspace UI**

```powershell
git add apps/web/src
git commit -m "feat: connect workspace to authenticated spaces"
```

### Task 6: Verify migrations, API behavior, browser flow, and documentation

**Files:**
- Modify: `README.md`, `.env.example`, `.github/workflows/quality.yml`
- Test: existing API and web suites

- [ ] **Step 1: Write failing configuration documentation assertions**

Add tests that production startup rejects a missing `SESSION_COOKIE_NAME` or an invalid `SESSION_TTL_SECONDS`, and that `.env.example` documents non-secret session settings only.

- [ ] **Step 2: Verify RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_config.py -q -p no:cacheprovider`

Expected: the new configuration tests fail before session settings are added.

- [ ] **Step 3: Add runtime settings and handoff documentation**

Set `SESSION_COOKIE_NAME=session` and `SESSION_TTL_SECONDS=604800` in `.env.example`; validate a cookie-name token and TTL in the range 3600–2592000. Update README with database migration, registration, login, logout, classroom creation and invitation steps. Do not document cookie values, passwords, raw invite codes or internal service details as user-interface content. Update CI to run Alembic migration checks before API tests.

- [ ] **Step 4: Run the clean quality suite**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests --no-cache
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests --cov=tutor_api --cov-fail-under=90 -q -p no:cacheprovider
pnpm --dir apps/web test
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: all commands exit 0; API coverage remains at least 90%.

- [ ] **Step 5: Run the Docker acceptance path without changing existing data**

Run in an isolated Compose project with a newly named project and new volumes:

```powershell
Copy-Item .env.example .env.identity-test
docker compose --env-file .env.identity-test -p textbook-identity-test up --build -d
```

Register two users through the API, create a classroom with the first, join using the returned invite with the second, verify the second cannot promote itself, then run `docker compose -p textbook-identity-test down` without `--volumes`. Do not stop or delete prior project volumes.

- [ ] **Step 6: Commit verified handoff changes**

```powershell
git add README.md .env.example .github/workflows/quality.yml apps/api/tests/test_config.py
git commit -m "docs: document identity and classroom workflow"
```

## Completion boundary

This plan is complete only when migration upgrade succeeds, authentication and role-matrix tests pass, the C3 workspace keeps exactly three resizable panes with live space summaries, the full quality suite is green, and the isolated Docker acceptance flow verifies that an outsider cannot access or mutate a classroom. Provider configuration, wallets, document import, AI answer generation, classroom content review, and long-term memory remain out of scope.
