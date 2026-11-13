# Market Proxy and Network Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add isolated per-market HTTP/HTTPS/SOCKS5/SOCKS5h proxy configuration and a saved-configuration network test that returns connectivity, latency, and the latest available daily close.

**Architecture:** Build proxy state into immutable Provider Registry snapshots. Native per-client proxies cover httpx/CCXT; reentrant SDK-specific runtime locks protect AKShare/yfinance/BaoStock global state, with Tasks waiting and network tests refusing to wait. A non-persisting service probes the real `fetch_daily` path and a small AntD modal presents the result.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, httpx[socks], requests[socks], AKShare, yfinance, CCXT, pytest, React, TypeScript, TanStack Query, Ant Design, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-12-task-fixes-proxy-network-test-design.md`

## Global Constraints

- TDD: every behavior starts with a failing focused test and ends with the same test passing.
- Formal Tasks wait for SDK availability; network tests never wait and return `ProviderBusy` immediately.
- No `os.environ` proxy mutation, global socket/request monkey-patching, silent direct fallback, or authenticated proxy URLs.
- Null proxy means direct access and bypasses ambient proxy environment variables.
- `provider=baostock` plus a proxy is rejected; BaoStock without proxy remains supported.
- Network tests use saved registry configuration, never draft provider/proxy values, and never write config/database/Task history.
- Do not commit or push unless the user explicitly asks.

## Review Focus

- A timed-out SDK worker may still own its lock; later tests must return busy and Tasks must continue waiting.
- Reentrant acquisition must let a nonblocking probe enter a provider that internally uses the same runtime lock.
- Different markets must never overlap inside AKShare or Yahoo global proxy configuration.
- Null proxies must not inherit `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY`.
- Modal results must not leak proxy URLs, raw upstream bodies, credentials, or tracebacks.

---

### Task 1: Validate and Persist Market Proxy Configuration

**Files:**
- Modify: `backend/app/config/models.py`
- Modify: `backend/app/providers/registry.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/config/test_market_schema.py`
- Test: `backend/tests/config/test_store.py`
- Test: `backend/tests/api/test_settings_api.py`

**Interfaces:**
- Produces: `MarketSettings.proxy_url: str | None = None` and `ProviderRegistry.market_settings(market: str) -> MarketSettings`, returning a defensive immutable snapshot from the same registry used for provider selection.
- Accepted schemes: exactly `http`, `https`, `socks5`, `socks5h`; explicit hostname and port are required.
- Rejected: userinfo, controls, query, fragment, unsupported schemes, and BaoStock plus non-null proxy.

- [ ] **Step 1: Write failing model and persistence tests**
  Cover default/missing null, blank-to-null normalization, all four schemes, malformed URLs, every rejected input class, BaoStock incompatibility, settings round-trip/hot apply, and defensive registry snapshots.

- [ ] **Step 2: Run focused tests and verify RED**
  Run: `backend/.venv/bin/python -m pytest backend/tests/config/test_market_schema.py backend/tests/config/test_store.py backend/tests/api/test_settings_api.py -q`

- [ ] **Step 3: Implement validation and registry snapshots**
  Use a bounded string and URL parsing without echoing the candidate in errors. Declare `httpx[socks]` and `requests[socks]` dependencies, then install the existing backend project dependency flow so `socksio` and `PySocks` are actually available.

- [ ] **Step 4: Run focused tests and verify GREEN**
  Run the Step 2 command plus import checks for `socks` and `socksio`. Expected: all pass.

### Task 2: Add Native httpx and CCXT Proxy Isolation

**Files:**
- Modify: `backend/app/providers/http.py`
- Modify: `backend/app/providers/ccxt_ohlcv.py`
- Modify: `backend/app/providers/hstech_universe.py`
- Modify: `backend/app/providers/invesco_universe.py`
- Modify: `backend/app/providers/ishares_soxx.py`
- Modify: `backend/app/providers/factory.py`
- Test: `backend/tests/providers/test_http.py`
- Test: `backend/tests/providers/test_ccxt_ohlcv.py`
- Test: `backend/tests/providers/test_timeout_factory.py`

**Interfaces:**
- Consumes: Task 1 `MarketSettings.proxy_url`.
- Produces: `fetch_bytes(..., proxy_url: str | None = None)`; provider constructors accepting optional `proxy_url`; CCXT `proxies={"http": url, "https": url}` with `requests_trust_env=False`.

- [ ] **Step 1: Write failing transport tests**
  Assert explicit proxies reach each client/exchange, both protocol mappings are present, spot-only Binance discovery is retained, no-proxy clients bypass ambient environment, exchanges close, and factory instances for two markets cannot share proxy state.

- [ ] **Step 2: Run focused tests and verify RED**
  Run: `backend/.venv/bin/python -m pytest backend/tests/providers/test_http.py backend/tests/providers/test_ccxt_ohlcv.py backend/tests/providers/test_timeout_factory.py -q`

- [ ] **Step 3: Implement immutable native proxy wiring**
  Pass proxy state alongside timeouts through the factory, including all Universe providers. Use `trust_env=False` for owned httpx clients and CCXT exchanges whether proxy is null or set.

- [ ] **Step 4: Run focused tests and verify GREEN**
  Run the Step 2 command. Expected: all pass.

### Task 3: Coordinate SDK-Global Proxy State and Busy Detection

**Files:**
- Create: `backend/app/providers/sdk_runtime.py`
- Modify: `backend/app/providers/errors.py`
- Modify: `backend/app/providers/akshare_ohlcv.py`
- Modify: `backend/app/providers/a_share_universes.py`
- Modify: `backend/app/providers/yahoo_ohlcv.py`
- Modify: `backend/app/providers/baostock_ohlcv.py`
- Modify: `backend/app/providers/factory.py`
- Create: `backend/tests/providers/test_sdk_runtime.py`
- Modify: `backend/tests/providers/test_akshare_ohlcv.py`
- Modify: `backend/tests/providers/test_a_share_universes.py`
- Modify: `backend/tests/providers/test_yahoo_ohlcv.py`

**Interfaces:**
- Produces: `provider_runtime(provider_name: str, proxy_url: str | None, *, wait: bool) -> AbstractContextManager[None]`.
- Produces: `ProviderBusy(ProviderError)` with fixed detail `Data source is currently in use; retry later` and no proxy data.
- Runtime locks are reentrant per provider family. `wait=False` raises immediately when unavailable; `wait=True` blocks until release.

- [ ] **Step 1: Write failing runtime tests**
  - Task-style `wait=True` calls queue and then run after an earlier call releases.
  - `wait=False` raises `ProviderBusy` immediately and never enters the SDK.
  - A thread continuing after cooperative timeout retains ownership until its SDK call actually exits.
  - Reentrant acquisition succeeds in the same worker thread.
  - AKShare/Yahoo proxy configuration plus the complete SDK call is inside the lock; direct mode cannot inherit ambient proxies.
  - Two markets cannot overlap in the same SDK critical section; different SDK families remain independent.

- [ ] **Step 2: Run focused tests and verify RED**
  Run: `backend/.venv/bin/python -m pytest backend/tests/providers/test_sdk_runtime.py backend/tests/providers/test_akshare_ohlcv.py backend/tests/providers/test_a_share_universes.py backend/tests/providers/test_yahoo_ohlcv.py -q`

- [ ] **Step 3: Implement the shared runtime and migrate every app SDK call**
  Keep AKShare `ProxyContext`, Yahoo `set_config`, and the complete function invocation in the same critical section. Use protocol-to-None mappings for AKShare direct mode. Migrate BaoStock to the same reentrant lock map without allowing a proxy. Pass each market proxy through the factory.

- [ ] **Step 4: Run focused tests and verify GREEN**
  Run the Step 2 command plus BaoStock and factory tests. Expected: all pass without real network access.

### Task 4: Implement the Non-Persisting Network Test API

**Files:**
- Create: `backend/app/services/market_network_test.py`
- Create: `backend/app/api/market_network_test.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/middleware/rate_limit.py`
- Create: `backend/tests/services/test_market_network_test.py`
- Create: `backend/tests/api/test_market_network_test_api.py`
- Modify: `backend/tests/api/test_security_limits.py`

**Interfaces:**
- Consumes: `ProviderRegistry.market_settings`, `get_ohlcv`, and Task 3 `provider_runtime`/`ProviderBusy`.
- Produces: `POST /api/v1/settings/markets/{market}/network-test`, body `{symbol: string}`.
- Produces frozen result fields: `market`, `provider`, `symbol`, `connected`, `latency_ms`, `price`, `price_date`, `currency`, `error_type`, `detail`.
- Service: `MarketNetworkTestService(registry, *, clock=time.monotonic, today=date.today).test(market, symbol) -> NetworkTestResult` (async).

- [ ] **Step 1: Write failing service tests for all four markets**
  Assert canonical instruments and adjustments, a bounded 31-day lookback, latest close/date/currency, monotonic latency, direct and proxy runtime selection, empty bars as `NoDataAvailable`, sanitized provider errors, and no repository/config writes.

- [ ] **Step 2: Write failing busy and API tests**
  Hold each SDK runtime lock and prove the probe returns immediately with `connected=false`, `error_type=ProviderBusy`, the fixed busy detail, and no waiting. Cover malformed symbols/markets, successful and failed envelopes, compute rate limiting, and unexpected-exception sanitization.

- [ ] **Step 3: Run focused tests and verify RED**
  Run: `backend/.venv/bin/python -m pytest backend/tests/services/test_market_network_test.py backend/tests/api/test_market_network_test_api.py backend/tests/api/test_security_limits.py -q`

- [ ] **Step 4: Implement the probe service and route**
  Build validated DTOs for `600519.SH`, `0700.HK`, `AAPL`, or an editable crypto pair; use saved registry settings only. Execute the entire nonblocking runtime guard inside the same synchronous worker as `fetch_daily`, via `call_provider_sync`, so RLock ownership stays on one thread. Return HTTP 200 for expected probe failures and 422 for invalid input.

- [ ] **Step 5: Run focused tests and verify GREEN**
  Run the Step 3 command. Expected: all pass.

### Task 5: Add Proxy Controls and the Network Test Modal

**Files:**
- Modify: `frontend/src/types/settings.ts`
- Modify: `frontend/src/api/decoders/settings.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/features/settings/MarketSettingsForm.tsx`
- Create: `frontend/src/features/settings/NetworkTestModal.tsx`
- Modify: `frontend/src/features/settings/marketOptions.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/test/apiFixtures.ts`
- Modify: `frontend/src/features/settings/SettingsPage.test.tsx`
- Create: `frontend/src/features/settings/NetworkTestModal.test.tsx`
- Modify: `frontend/src/api/endpoints.test.ts`

**Interfaces:**
- Consumes: Task 4 endpoint/result contract.
- Produces: `MarketSettings.proxy_url: string | null`, `testMarketNetwork(market, {symbol})`, defaults `600519.SH`, `0700.HK`, `AAPL`, `BTC/USDT`.

- [ ] **Step 1: Write failing decoder and Group tests**
  Cover proxy string/null/missing decode, save/clear persistence, other-Group draft preservation, provider/timeout on one horizontal row, proxy on its own row, BaoStock warning, and an always-visible Network Test button disabled only for editing/busy.

- [ ] **Step 2: Write failing Modal tests**
  Cover default symbol, editing, blank validation, one pending request, success diagnostics, provider failure, immediate `ProviderBusy` warning, transport error, reset on reopen, and no settings PUT/revision change.

- [ ] **Step 3: Run focused tests and verify RED**
  Run: `npm --prefix frontend run test -- SettingsPage NetworkTestModal endpoints`

- [ ] **Step 4: Implement typed controls and Modal**
  Reuse the existing Group save pipeline and AntD Modal patterns. Use a dedicated dark-theme `rootClassName`, immutable state updates, responsive horizontal alignment, and sanitized result fields only. Do not use SchemaForm for the single symbol input.

- [ ] **Step 5: Run focused tests and verify GREEN**
  Run the Step 3 command. Expected: all pass.

### Task 6: Browser and Full Regression Gate

**Files:**
- Modify: `frontend/e2e/fixtures.ts`
- Modify: `frontend/e2e/tasks-settings.spec.ts`
- Modify documentation only after verified behavior exists.

- [ ] **Step 1: Add deterministic browser journeys**
  Cover proxy save/clear, edit-state gating, default/edited symbol, success/failure/busy diagnostics, no settings PUT during testing, and Task log level/details from the companion plan.

- [ ] **Step 2: Run all automated gates**
  Run backend pytest with coverage, frontend Vitest with coverage, TypeScript/Vite build, and Playwright. Expected: all pass with at least 80% coverage and no console errors.

- [ ] **Step 3: Run bounded real-provider verification**
  Verify Invesco/SOXX Universe parsing, Binance BTC/USDT daily bars, and direct network-test latest prices where the public upstream permits. Do not run the full 2,000+ symbol A-share Task or fabricate success for rate limits/network failures.

- [ ] **Step 4: Restart and inspect the actual application**
  Ensure no Task is active, restart the non-reload backend, and verify the new settings schema and network-test API. Keep frontend Vite running. Review the complete diff and do not commit.
