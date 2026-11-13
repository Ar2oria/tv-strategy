# Task Sync Fixes and Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the deterministic manual-run failures in market Tasks and make durable run logs show useful, safely sanitized diagnostics with distinct INFO/ERROR styles.

**Architecture:** Keep the existing TaskRunner and provider boundaries. Tighten real-world response compatibility at each adapter, return explicit empty-catalog Task results, and render the existing structured log context instead of adding a parallel logging system.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, AKShare, CCXT 4.4.50, pytest, React, TypeScript, Ant Design, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-12-task-fixes-proxy-network-test-design.md`

## Global Constraints

- TDD: every behavior starts with a failing focused test and ends with the same test passing.
- Do not weaken JSON/CSV body validation, response size limits, or error sanitization.
- Do not add automatic retries, silent provider substitution, or automatic Universe downloads from daily Tasks.
- Do not commit or push unless the user explicitly asks.
- Existing local bars and memberships must remain intact after provider failures.

## Review Focus

- Real `text/plain` responses must parse, while HTML error pages must still fail.
- Binance spot initialization must not call `dapi` or `fapi`, including when proxies are added later.
- Empty default catalogs must produce actionable logs rather than a generic runner exception.
- Rate-limit and network details must be useful without leaking raw upstream text or proxy URLs.
- Log details must wrap on mobile and must not stringify objects as `[object Object]`.

---

### Task 1: Accept Verified Universe Media Types

**Files:**
- Modify: `backend/app/providers/http.py`
- Modify: `backend/app/providers/invesco_universe.py`
- Modify: `backend/app/providers/ishares_soxx.py`
- Test: `backend/tests/providers/test_http.py`
- Test: `backend/tests/providers/test_invesco_universe.py`
- Test: `backend/tests/providers/test_ishares_soxx.py`

**Interfaces:**
- Consumes: existing `fetch_bytes(...) -> bytes` and provider parsers.
- Produces: `expected_content_type: str | tuple[str, ...] | None`; Invesco allows `application/json` and `text/plain`, iShares allows `text/csv` and `text/plain`.

- [ ] **Step 1: Write failing tests**
  - A `text/plain` response succeeds when the caller supplies `("application/json", "text/plain")`.
  - `text/html` still raises `ProviderDataInvalid`.
  - Empty tuples and invalid entries fail before network I/O.
  - Provider-level tests assert the exact two-value allowlists and prove real fixture bodies still parse.

- [ ] **Step 2: Run focused tests and verify RED**
  Run: `backend/.venv/bin/python -m pytest backend/tests/providers/test_http.py backend/tests/providers/test_invesco_universe.py backend/tests/providers/test_ishares_soxx.py -q`
  Expected: new cases fail because only one exact media type is accepted.

- [ ] **Step 3: Implement normalized media-type allowlists**
  Validate and normalize the expectation once, compare the response media type case-insensitively after removing parameters, and leave all streaming/size/parser checks unchanged.

- [ ] **Step 4: Run focused tests and verify GREEN**
  Run the Step 2 command. Expected: all focused tests pass.

### Task 2: Restrict Binance Discovery to Spot Markets

**Files:**
- Modify: `backend/app/providers/ccxt_ohlcv.py`
- Test: `backend/tests/providers/test_ccxt_ohlcv.py`

**Interfaces:**
- Consumes: installed CCXT `options.fetchMarkets`, whose supported value is a list such as `["spot"]`.
- Produces: Binance exchange construction that never requests linear/inverse market discovery.

- [ ] **Step 1: Write failing constructor and discovery tests**
  Assert the Binance constructor receives `options={"fetchMarkets": ["spot"]}` and retains `enableRateLimit=True` and the configured timeout. Add a source-level behavioral fake proving no `dapiPublicGetExchangeInfo`/`fapiPublicGetExchangeInfo` call is needed for `fetch_ohlcv`.

- [ ] **Step 2: Run focused tests and verify RED**
  Run: `backend/.venv/bin/python -m pytest backend/tests/providers/test_ccxt_ohlcv.py -q`
  Expected: existing constructor arguments omit spot-only discovery.

- [ ] **Step 3: Implement the minimal Binance option**
  Add only `options.fetchMarkets=["spot"]`; preserve OKX behavior, pagination, exchange closing, and validation.

- [ ] **Step 4: Run focused tests and verify GREEN**
  Run the Step 2 command. Expected: all CCXT offline tests pass.

- [ ] **Step 5: Run a bounded real spot check**
  Fetch at most 14 recent BTC/USDT daily bars through the project adapter. Expected: success without the previous `dapi...exchangeInfo` failure; if the public network itself fails, record the exact new error rather than claiming success.

### Task 3: Preserve Actionable Task Failure Details

**Files:**
- Modify: `backend/app/providers/akshare_ohlcv.py`
- Modify: `backend/app/providers/ccxt_ohlcv.py`
- Modify: `backend/app/providers/errors.py`
- Modify: `backend/app/tasks/builtin/sync_daily.py`
- Modify: `backend/app/services/task_runner.py`
- Test: `backend/tests/providers/test_akshare_ohlcv.py`
- Test: `backend/tests/providers/test_ccxt_ohlcv.py`
- Test: `backend/tests/tasks/test_market_sync_tasks.py`
- Test: `backend/tests/tasks/test_task_runner.py`

**Interfaces:**
- Consumes: AKShare `Push2RateLimitError`, CCXT exception classes, and existing `ProviderError.public_detail`.
- Produces: `ProviderRateLimited` for Eastmoney push2 limiting; stable safe detail containing provider/operation/exception category; explicit empty-catalog TaskResult; `error_type` on unexpected runner logs.

- [ ] **Step 1: Write failing error-mapping tests**
  - AKShare push2 limiting becomes `ProviderRateLimited` with an Eastmoney wait-and-resume detail.
  - CCXT `NetworkError` detail identifies CCXT, the exchange, and OHLCV operation without raw URLs/body text.
  - SOCKS URL sanitization redacts `socks5://` and `socks5h://` as well as HTTP URLs.

- [ ] **Step 2: Write failing Task diagnostics tests**
  - Empty default US membership returns `status="failed"`, progress 100, an ERROR log, and detail containing `Run Synchronize market universes first`; no provider call occurs.
  - Unexpected runner exceptions log their safe exception class in `context.error_type` without exposing the raw exception message.

- [ ] **Step 3: Run focused tests and verify RED**
  Run: `backend/.venv/bin/python -m pytest backend/tests/providers/test_akshare_ohlcv.py backend/tests/providers/test_ccxt_ohlcv.py backend/tests/tasks/test_market_sync_tasks.py backend/tests/tasks/test_task_runner.py -q`

- [ ] **Step 4: Implement safe diagnostics and empty-catalog results**
  Use fixed, built-in diagnostic messages and the existing sanitizer. Do not copy arbitrary exception strings into public details. Replace only the empty-default-selection exception with a logged failed TaskResult; unresolved explicit selections retain current behavior.

- [ ] **Step 5: Run focused tests and verify GREEN**
  Run the Step 3 command. Expected: all focused tests pass.

### Task 4: Render Structured Log Details and Level Tags

**Files:**
- Modify: `frontend/src/features/tasks/TaskRunHistory.tsx`
- Create: `frontend/src/features/tasks/TaskRunHistory.test.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/e2e/fixtures.ts`
- Modify: `frontend/e2e/tasks-settings.spec.ts`

**Interfaces:**
- Consumes: existing `TaskLogDTO.context`.
- Produces: INFO=`processing`, ERROR=`error`, neutral fallback tags; whitelisted `symbol`/`universe_code`, `error_type`, `detail`, and `bar_count` rendering.

- [ ] **Step 1: Write failing component tests**
  Render one INFO and one ERROR log. Assert distinct AntD tag classes, visible Symbol/Universe, error type and concrete detail, success bar count, `—` for empty context, and no `run_id` duplication or `[object Object]` output.

- [ ] **Step 2: Run focused tests and verify RED**
  Run: `npm --prefix frontend run test -- TaskRunHistory`
  Expected: current raw-level text has no tag styles or details.

- [ ] **Step 3: Implement accessible log rendering**
  Keep the existing table, use small immutable helper functions for scalar whitelist values, and add wrapping CSS for long details. Do not render arbitrary context keys or raw JSON.

- [ ] **Step 4: Run focused tests and verify GREEN**
  Run the Step 2 command. Expected: all TaskRunHistory tests pass.

- [ ] **Step 5: Add deterministic browser coverage**
  Extend log fixtures with both levels and concrete context, then assert the visible tags and details in `tasks-settings.spec.ts`. Run the focused Playwright spec and expect it to pass.

### Task 5: Regression Gate for This Plan

**Files:**
- Modify only files required by failures caused by Tasks 1–4.

- [ ] **Step 1: Run backend regression**
  Run: `backend/.venv/bin/python -m pytest backend/tests --cov=backend/app --cov-report=term-missing -q`
  Expected: all offline tests pass; existing online tests remain skipped without opt-in; coverage stays at least 80%.

- [ ] **Step 2: Run frontend regression**
  Run the project Vitest/coverage command, `npm --prefix frontend run build`, and focused Playwright specs.
  Expected: tests, type checking, production build, and browser journeys pass.

- [ ] **Step 3: Review the complete diff**
  Verify no unrelated research directories were changed, no secrets were introduced, and every new diagnostic is bounded and sanitized. Do not commit.
