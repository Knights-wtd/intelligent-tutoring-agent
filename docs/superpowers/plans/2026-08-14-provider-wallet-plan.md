# Provider Catalog and Wallet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver server-only provider configuration, a user-visible enabled-model catalog, immutable price and exchange-rate snapshots, Decimal-based wallet reservations and settlement, and administrator-issued recharge and reversal entries.

**Architecture:** Provider source configuration remains in environment variables and is parsed into non-secret runtime descriptors; no browser or database row ever receives an API key. A database-backed catalog stores the enabled state and price/FX versions. Each wallet mutation appends ledger entries inside the same transaction, while reservations serialize access to available funds. Real model invocation remains out of scope; the public settlement service accepts verified usage supplied by a future Provider Adapter.

**Tech Stack:** FastAPI, Pydantic Settings, SQLAlchemy 2, Alembic, PostgreSQL, Decimal/NUMERIC, pytest/httpx, Next.js/React/TypeScript, Vitest.

---

## Locked file structure

```text
apps/api/
├── migrations/versions/0002_provider_wallet.py
├── src/tutor_api/
│   ├── core/{config.py,database.py}
│   ├── identity/{models.py,router.py}
│   ├── providers/{models.py,schemas.py,service.py,router.py}
│   ├── billing/{models.py,schemas.py,service.py,router.py}
│   └── main.py
└── tests/{test_config.py,test_provider_catalog.py,test_wallet.py,test_admin_billing.py}
apps/web/src/
├── components/workspace/{workspace-shell.tsx,workspace-shell.test.tsx}
└── lib/api.ts
```

`PLATFORM_ADMIN_EMAILS` is the sole first-version platform-admin authority and is read from server configuration; classroom owners are not platform administrators. `ProviderProfile` records non-secret identifiers and enabled state. `PriceVersion` and `FxVersion` are append-only snapshots. `WalletReservation` carries a unique request id and state (`active`, `settled`, `released`). `LedgerEntry` carries a signed Decimal amount, entry type and immutable JSON snapshot. `RechargeRecord` is an audit link to its positive or reversal ledger entry.

### Task 1: Add validated server-only provider and administrator configuration

**Status:** complete

**Files:**
- Modify: `apps/api/src/tutor_api/core/config.py`, `.env.example`, `compose.yaml`
- Test: `apps/api/tests/test_config.py`, `apps/api/tests/test_compose_security.py`

- [ ] **Step 1: Write failing configuration tests**

```python
def test_settings_parse_provider_profiles_without_exposing_api_keys() -> None:
    settings = Settings(
        provider_profiles_json='[{"id":"openai-gpt","provider":"openai","model":"gpt-test","display_name":"测试模型"}]',
        platform_admin_emails="admin@example.com",
    )
    assert settings.provider_profiles[0].id == "openai-gpt"
    assert "API_KEY" not in repr(settings)

def test_settings_reject_duplicate_provider_profile_ids() -> None:
    with pytest.raises(ValueError, match="PROVIDER_PROFILES_JSON"):
        Settings(provider_profiles_json='[{"id":"same","provider":"a","model":"a","display_name":"A"},{"id":"same","provider":"b","model":"b","display_name":"B"}]')
```

- [ ] **Step 2: Run RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_config.py -q -p no:cacheprovider`

Expected: collection or assertions fail because provider profiles and platform administrators are absent.

- [ ] **Step 3: Implement minimal safe parsing**

Create `ProviderProfileConfig` with `id`, `provider`, `model`, `display_name`, `supports_usage` and `enabled_by_default`; parse `PROVIDER_PROFILES_JSON` only from settings, reject malformed JSON, duplicate ids and blank values. Parse comma-separated `PLATFORM_ADMIN_EMAILS` into normalized addresses. Add illustrative fake model ids and blank secret fields to `.env.example`; pass only non-secret provider profile JSON and administrator email list through Compose. Do not add real provider keys or browser-facing secret values.

- [ ] **Step 4: Run GREEN**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_config.py apps/api/tests/test_compose_security.py -q -p no:cacheprovider`

Expected: provider parsing, duplicate rejection and Compose secret-boundary tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/tutor_api/core/config.py .env.example compose.yaml apps/api/tests/test_config.py apps/api/tests/test_compose_security.py
git commit -m "feat: add provider runtime configuration"
```

### Task 2: Create provider, price, FX and wallet schema

**Status:** complete

**Files:**
- Create: `apps/api/src/tutor_api/providers/{__init__.py,models.py}`, `apps/api/src/tutor_api/billing/{__init__.py,models.py}`, `apps/api/migrations/versions/0002_provider_wallet.py`
- Modify: `apps/api/migrations/env.py`
- Test: `apps/api/tests/test_schema.py`

- [ ] **Step 1: Write failing schema tests**

```python
def test_wallet_ledger_amounts_are_decimal_and_append_only(session) -> None:
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    entry = LedgerEntry(wallet_id=wallet.id, amount=Decimal("10.00"), entry_type=LedgerEntryType.RECHARGE)
    session.add(entry)
    session.commit()
    assert entry.amount == Decimal("10.00000000")

def test_reservation_request_id_is_unique(session) -> None:
    session.add_all([WalletReservation(wallet_id=wallet.id, request_id="request-1", reserved_amount=Decimal("1")), WalletReservation(wallet_id=wallet.id, request_id="request-1", reserved_amount=Decimal("1"))])
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_schema.py -q -p no:cacheprovider`

Expected: imports fail because provider and billing models do not exist.

- [ ] **Step 3: Implement models and migration**

Use UUID keys, UTC timestamps and `Numeric(20, 8)` for all money. Create `provider_profiles`, `price_versions`, `fx_versions`, `wallets`, `wallet_reservations`, `ledger_entries` and `recharge_records`. Make `(provider_profile_id, effective_at)` price-version unique; preserve the source URL, currency, input/cached-input/output unit prices and unit size. Make ledger rows append-only in service code: no update or delete endpoints. Add a wallet per user lazily in the same locking transaction. Generate a reversible Alembic migration.

- [ ] **Step 4: Verify schema and migration**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m alembic -c apps/api/alembic.ini upgrade head --sql
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_schema.py -q -p no:cacheprovider
```

Expected: PostgreSQL static SQL includes all seven tables and schema tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/tutor_api/providers/models.py apps/api/src/tutor_api/billing/models.py apps/api/migrations apps/api/tests/test_schema.py
git commit -m "feat: add provider and wallet schema"
```

### Task 3: Synchronize the enabled model catalog and expose user-safe views

**Status:** complete

**Files:**
- Create: `apps/api/src/tutor_api/providers/{schemas.py,service.py,router.py}`
- Modify: `apps/api/src/tutor_api/main.py`
- Test: `apps/api/tests/test_provider_catalog.py`

- [ ] **Step 1: Write failing catalog tests**

```python
def test_user_sees_only_enabled_usage_capable_models(client) -> None:
    register(client, "learner")
    response = client.get("/api/v1/models")
    assert response.status_code == 200
    assert response.json() == [{"id": "openai-gpt", "display_name": "测试模型", "provider": "openai"}]

def test_model_catalog_never_returns_provider_key_or_base_url(client) -> None:
    response = client.get("/api/v1/models")
    assert "api_key" not in response.text.casefold()
    assert "base_url" not in response.text.casefold()
```

- [ ] **Step 2: Run RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_provider_catalog.py -q -p no:cacheprovider`

Expected: `/api/v1/models` returns 404.

- [ ] **Step 3: Implement synchronization and user endpoint**

On application startup, synchronize configured non-secret profiles by id without deleting historical rows. An enabled profile must have `supports_usage=True`; disabled and usage-unverifiable entries do not appear for users. Return only id, provider, display name and current user-facing RMB pricing summary. Never return key, base URL, timeout or raw environment JSON.

- [ ] **Step 4: Run GREEN and lint**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_provider_catalog.py -q -p no:cacheprovider
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests --no-cache
```

Expected: catalog visibility and secret redaction tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/tutor_api/providers apps/api/src/tutor_api/main.py apps/api/tests/test_provider_catalog.py
git commit -m "feat: expose enabled model catalog"
```

### Task 4: Implement wallet, reservations and usage settlement service

**Status:** complete

**Files:**
- Create: `apps/api/src/tutor_api/billing/{schemas.py,service.py,router.py}`
- Modify: `apps/api/src/tutor_api/main.py`
- Test: `apps/api/tests/test_wallet.py`

- [ ] **Step 1: Write failing settlement tests**

```python
def test_settlement_releases_unused_reservation_and_uses_decimal_snapshots(session) -> None:
    reservation = reserve(session, user.id, "run-1", Decimal("10.00"))
    result = settle(session, reservation.id, Usage(input_units=1000, cached_input_units=0, output_units=500))
    assert result.charged_amount == Decimal("2.50000000")
    assert wallet_balance(session, user.id) == Decimal("7.50000000")

def test_repeated_settlement_request_is_idempotent(session) -> None:
    first = settle(session, reservation.id, usage)
    second = settle(session, reservation.id, usage)
    assert second.ledger_entry_id == first.ledger_entry_id
```

- [ ] **Step 2: Run RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_wallet.py -q -p no:cacheprovider`

Expected: billing service imports fail.

- [ ] **Step 3: Implement transactional wallet service**

Require a positive Decimal reservation amount and acquire the wallet row with `SELECT ... FOR UPDATE`. Available balance is immutable ledger total minus active reservations. Reject insufficient funds before returning a reservation. Settlement only accepts a verified usage record and current immutable price/FX snapshots, calculates using `Decimal`, appends one negative consumption ledger row, marks the reservation settled and stores both snapshots. Releasing a failed call marks the reservation released without a consumption entry. A second settlement or release returns the existing result and never adds a duplicate ledger row.

- [ ] **Step 4: Run GREEN including concurrency behavior**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_wallet.py -q -p no:cacheprovider
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests -q -p no:cacheprovider
```

Expected: Decimal pricing, insufficient funds, release, idempotent settlement and duplicate request tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/tutor_api/billing apps/api/src/tutor_api/main.py apps/api/tests/test_wallet.py
git commit -m "feat: add wallet reservation and settlement"
```

### Task 5: Add administrator recharge, reversal and user billing views

**Status:** complete

**Files:**
- Modify: `apps/api/src/tutor_api/identity/router.py`, `apps/api/src/tutor_api/billing/{schemas.py,service.py,router.py}`
- Test: `apps/api/tests/test_admin_billing.py`

- [ ] **Step 1: Write failing authorization and audit tests**

```python
def test_only_platform_admin_can_recharge_and_reversal_is_new_entry(client) -> None:
    assert client.post("/api/v1/admin/recharges", json={"user_id": learner_id, "amount": "20.00", "reason": "人工充值"}).status_code == 403
    admin_response = admin_client.post("/api/v1/admin/recharges", json={"user_id": learner_id, "amount": "20.00", "reason": "人工充值"})
    reversal = admin_client.post(f"/api/v1/admin/recharges/{admin_response.json()['id']}/reverse", json={"reason": "录入错误"})
    assert reversal.status_code == 201
    assert reversal.json()["amount"] == "-20.00000000"

def test_user_billing_view_hides_usage_implementation_details(client) -> None:
    response = client.get("/api/v1/billing/me")
    assert response.status_code == 200
    assert "token_digest" not in response.text
```

- [ ] **Step 2: Run RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_admin_billing.py -q -p no:cacheprovider`

Expected: administration and billing routes return 404.

- [ ] **Step 3: Implement endpoints**

`POST /api/v1/admin/recharges` requires an email listed in `PLATFORM_ADMIN_EMAILS`, positive amount, external reference and reason, and writes a `RECHARGE` ledger row. `POST /api/v1/admin/recharges/{id}/reverse` can run once and writes the paired negative `REVERSAL` entry; neither endpoint mutates existing entries. `GET /api/v1/billing/me` returns balance and paginated simple entries for the current user. Authentication failure remains 401, non-admin administration mutation is 403, and a user cannot request another user's billing history.

- [ ] **Step 4: Run GREEN**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_admin_billing.py -q -p no:cacheprovider`

Expected: recharge, one-time reversal, authorization and user isolation tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/tutor_api/identity/router.py apps/api/src/tutor_api/billing apps/api/tests/test_admin_billing.py
git commit -m "feat: add auditable manual recharges"
```

### Task 6: Display enabled model choice and simple balance in C3 workspace

**Status:** complete

**Files:**
- Modify: `apps/web/src/lib/api.ts`, `apps/web/src/app/page.tsx`, `apps/web/src/components/workspace/{workspace-shell.tsx,workspace-shell.test.tsx}`
- Test: `apps/web/src/components/workspace/workspace-shell.test.tsx`

- [ ] **Step 1: Write failing UI test**

```tsx
it("shows enabled models and simple balance without internal provider data", async () => {
  mockApi.models.mockResolvedValue([{ id: "openai-gpt", display_name: "测试模型", provider: "openai", price_summary: "按量计费" }]);
  mockApi.billingMe.mockResolvedValue({ balance: "20.00", currency: "CNY", entries: [] });
  render(<WorkspaceShell spaces={spaces} />);
  expect(await screen.findByRole("option", { name: "测试模型" })).toBeInTheDocument();
  expect(screen.getByText("余额 ¥20.00")).toBeInTheDocument();
  expect(screen.queryByText(/API Key|Base URL/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run RED**

Run: `pnpm --dir apps/web test -- workspace-shell.test.tsx`

Expected: the API helpers and model selector do not exist.

- [ ] **Step 3: Implement minimal UI**

Fetch enabled models and the current billing summary through the existing same-origin credentials client. Render a model `<select>` and a two-decimal RMB balance in the right-side tutor pane; preserve three panels and two separators. On unavailable catalog or billing data, show a neutral retry message rather than internal error payloads.

- [ ] **Step 4: Verify production UI**

Run:

```powershell
pnpm --dir apps/web test
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: web tests, lint and build exit 0.

- [ ] **Step 5: Commit**

```powershell
git add apps/web/src
git commit -m "feat: show model choice and wallet balance"
```

### Task 7: Document configuration and run final isolated acceptance

**Status:** complete

**Files:**
- Modify: `README.md`, `.env.example`, `.github/workflows/quality.yml`
- Test: existing API and web suites

- [ ] **Step 1: Add configuration documentation assertions**

Add tests confirming `.env.example` has no real provider key, documents fake provider profiles and never exposes provider secret values through the user model catalog.

- [ ] **Step 2: Verify RED**

Run: `& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_config.py -q -p no:cacheprovider`

Expected: at least one new documentation or secret-boundary assertion fails before the update.

- [ ] **Step 3: Document the safe local workflow**

Document that administrators must insert real keys only into ignored `.env`, publish reviewed price/FX snapshots, and use manual recharge/reversal records. Do not document fake example keys as functional credentials. Add CI migration static-SQL validation and all API/web checks if absent.

- [ ] **Step 4: Run final quality suite and isolated Docker check**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests --cov=tutor_api --cov-fail-under=90 -q -p no:cacheprovider
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src apps/api/tests --no-cache
pnpm --dir apps/web test
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

In a newly named Compose project with separate ports and volumes, register a learner, issue a recharge as a configured platform administrator, verify user balance and enabled model catalog, then stop the project with `down` but without `--volumes`.

- [ ] **Step 5: Commit**

```powershell
git add README.md .env.example .github/workflows/quality.yml apps/api/tests
git commit -m "docs: document provider and wallet workflow"
```

## Completion boundary

This plan is complete only when provider keys remain server-only, users see only enabled usage-capable models, all prices and FX rates used in a settlement are immutable snapshots, amounts use Decimal/NUMERIC, insufficient balance prevents reservation, repeated settlement does not duplicate charges, recharges are reversible only by a new ledger entry, and the C3 UI shows only simple model and RMB balance information. Actual LLM calls, OCR/Embedding work, automatic payment, document upload and Agent answers remain out of scope.
