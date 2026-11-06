# Market Data Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resumable current-universe and front-adjusted daily-bar synchronization for A shares, Hong Kong stocks, US stocks, and crypto spot pairs.

**Architecture:** Provider adapters translate untrusted external responses into the backend's frozen domain DTOs. Universe parsing, OHLCV retrieval, synchronization, and Task orchestration remain separate; network calls run in worker threads and each instrument is persisted only after its complete requested range succeeds.

**Tech Stack:** Existing backend core, AKShare, BaoStock, yfinance, CCXT, httpx, pypdf, pandas, pytest, respx.

**Spec:** `docs/superpowers/specs/2026-11-05-local-stock-indicator-system-design.md` and `docs/superpowers/plans/2026-11-05-backend-core.md`

## Global Constraints

- Complete `2026-11-05-backend-core.md` first; reuse its DTOs, repositories, Task framework, and application container.
- Only daily bars are downloaded; weekly/monthly bars remain local aggregates. Stocks use qfq/adjusted OHLC; crypto and indices use no adjustment.
- Current constituents only; no point-in-time membership or historical constituent claims.
- Official public sources are preferred; no hidden Nasdaq endpoint, region bypass, authentication bypass, or unbounded scraping/retry.
- Default tests never use the public network. Online smoke tests are opt-in and use a small sample per market, never the full boards.
- Do not automatically commit or push; Git operations require a separate explicit user request.

## Review Focus

1. Empty, malformed, oversized, duplicated, unsorted, or non-finite provider responses must fail visibly without deleting prior data: Tasks 1–5 include parser and preservation tests.
2. A qfq change in the overlap window must trigger a complete per-instrument refresh; failed refresh retains old bars: Task 6 pins this behavior.
3. An interrupted multi-instrument run must resume missing instruments without duplicate rows or half-symbol initial histories: Task 6 tests interruption after instrument N.
4. HSTECH/QQQ/SOXX files contain non-equity rows and changing constituent counts: Tasks 3 and 4 test filtering and never hardcode 30/100/101.
5. Crypto pagination must exclude the unfinished UTC day, detect non-advancing pages, and keep exchanges/quote currencies separate: Task 5 tests all three.

---

### Task 1: Provider Contracts, Registry, and Response Validation

**Files:**
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/errors.py`
- Create: `backend/app/providers/registry.py`
- Create: `backend/app/providers/http.py`
- Create: `backend/app/providers/validation.py`
- Test: `backend/tests/providers/test_contracts.py`
- Test: `backend/tests/providers/test_http.py`

**Interfaces:**
- Consumes: `InstrumentDTO`, `InstrumentRecord`, `BarDTO`, and `UniverseSnapshot` from `backend/app/domain/dto.py`.
- Produces: `OhlcvProvider.fetch_daily(instrument: InstrumentDTO, start: date | None, end: date, adjustment: Adjustment) -> list[BarDTO]`.
- Produces: `UniverseProvider.fetch_universe(universe_code: str) -> UniverseSnapshot` and `ProviderRegistry.get_ohlcv(market: str, provider_name: str | None)`.
- Produces: `validate_bars(rows: Iterable[BarDTO]) -> list[BarDTO]` and bounded `fetch_bytes(url: str, *, max_bytes: int, timeout: float) -> bytes`.

- [ ] **Step 1: Write failing contract tests**

Assert validators sort or reject according to one documented rule: duplicate dates and invalid OHLC relationships reject; valid unsorted input returns a new sorted list; NaN/infinity and negative volume reject. HTTP tests use respx to verify status errors, content-length and streamed-byte limits, timeout mapping, and no credentials in error messages. Registry tests reject unknown provider names and incompatible market/provider pairs.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/providers/test_contracts.py tests/providers/test_http.py -v`
Expected: FAIL because provider contracts do not exist.

- [ ] **Step 3: Implement contracts and bounded HTTP helper**

Keep third-party SDK response models outside `app.domain`. Use typed provider exceptions (`ProviderUnavailable`, `ProviderRateLimited`, `ProviderDataInvalid`, `NoDataAvailable`) with sanitized public messages and detailed server logs. Provider methods are synchronous; Task orchestration will use `asyncio.to_thread`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/providers/test_contracts.py tests/providers/test_http.py -v`
Expected: all provider contract tests PASS.

- [ ] **Step 5: Verify no network is implicit**

Run: `cd backend && python -m pytest tests/providers -v`
Expected: PASS with all HTTP/SDK calls mocked; no test performs DNS or public network access.

### Task 2: A-Share and Hong Kong OHLCV Providers

**Files:**
- Create: `backend/app/providers/akshare_ohlcv.py`
- Create: `backend/app/providers/baostock_ohlcv.py`
- Test: `backend/tests/providers/test_akshare_ohlcv.py`
- Test: `backend/tests/providers/test_baostock_ohlcv.py`

**Interfaces:**
- Produces: `AkshareOhlcvProvider` supporting `a_share`, `hk_stock`, and supported index instrument types.
- `YahooOhlcvProvider` in Task 4 is also the registered fallback for HK stocks and HSTECH, so no second HK SDK adapter is required.
- Produces: `BaoStockOhlcvProvider` supporting A-share stocks and CSI300 as an explicitly configured fallback.

- [ ] **Step 1: Write failing SDK translation tests**

Mock `stock_zh_a_hist`, `stock_hk_hist`, `index_zh_a_hist`, and `stock_hk_index_daily_em`. Assert stock calls use qfq, index calls use no adjustment, Chinese columns map to domain fields, volume is null for unavailable index volume, and malformed rows raise `ProviderDataInvalid`. BaoStock tests assert anonymous login/logout, stock `adjustflag="2"`, index `adjustflag="3"`, serial access under a lock, and cursor pagination until no rows.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/providers/test_akshare_ohlcv.py tests/providers/test_baostock_ohlcv.py -v`
Expected: FAIL because adapters do not exist.

- [ ] **Step 3: Implement A/HK adapters**

Call AKShare with explicit daily/date/adjust arguments and BaoStock with explicit fields. Never infer missing volume as zero. A provider returning no rows yields `[]`; a full-refresh caller must treat that as no-data and preserve existing bars. Switching providers never appends to an existing adjusted series; Task 6 enforces full replacement.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/providers/test_akshare_ohlcv.py tests/providers/test_baostock_ohlcv.py -v`
Expected: all A/HK adapter tests PASS.

- [ ] **Step 5: Check provider isolation**

Run: `cd backend && python -m pytest tests/providers -v`
Expected: PASS; one mocked upstream failure does not mutate repository data.

### Task 3: A-Share and HSTECH Universe Providers

**Files:**
- Create: `backend/app/providers/a_share_universes.py`
- Create: `backend/app/providers/hstech_universe.py`
- Create: `backend/app/providers/hstech_parser.py`
- Test: `backend/tests/providers/test_a_share_universes.py`
- Test: `backend/tests/providers/test_hstech_parser.py`

**Interfaces:**
- Produces universe codes `csi300`, `star_market`, `chinext`, and `hstech`; CSI300 and HSTECH snapshots place their index instruments in `related_instruments`, never `members`.
- Produces: `parse_hstech_constituents(text: str, source: str) -> list[InstrumentDTO]`.

- [ ] **Step 1: Write failing universe parser tests**

CSI300 maps official/AKShare codes to canonical instruments; STAR uses the STAR list; ChiNext filters only ChiNext codes from the Shenzhen A-share list. HSTECH fixture text includes a header, full constituents, and declared count. Test whitespace, multi-word company names, four-digit codes, changed declared counts, missing table, and count mismatch. Parser never assumes 30 constituents.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/providers/test_a_share_universes.py tests/providers/test_hstech_parser.py -v`
Expected: FAIL because universe providers do not exist.

- [ ] **Step 3: Implement universe readers**

Use AKShare readers for CSI300 and current board lists. Download the official HSTECH factsheet through bounded `fetch_bytes`, extract text with pypdf from `BytesIO`, and parse the constituents section with explicit industry/share-type boundaries. Empty or structurally invalid output raises `ProviderDataInvalid`; repository membership replacement only occurs after complete success.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/providers/test_a_share_universes.py tests/providers/test_hstech_parser.py -v`
Expected: all A/HK universe tests PASS.

- [ ] **Step 5: Verify failed refresh preserves membership**

Run: `cd backend && python -m pytest tests/providers/test_hstech_parser.py tests/repositories/test_instruments.py -v`
Expected: PASS; parse failure occurs before `replace_universe` and old membership remains.

### Task 4: US OHLCV, Nasdaq-100, and SOXX Providers

**Files:**
- Create: `backend/app/providers/yahoo_ohlcv.py`
- Create: `backend/app/providers/invesco_universe.py`
- Create: `backend/app/providers/ishares_soxx.py`
- Test: `backend/tests/providers/test_yahoo_ohlcv.py`
- Test: `backend/tests/providers/test_invesco_universe.py`
- Test: `backend/tests/providers/test_ishares_soxx.py`

**Interfaces:**
- Produces: `YahooOhlcvProvider` for US/HK stocks, ETFs, and supported Yahoo indices, always emitting normalized adjusted OHLC for stocks/ETFs and unadjusted index bars.
- Produces universe codes `nasdaq100` and `soxx`; their snapshots place `^NDX` and SOXX ETF respectively in `related_instruments`, not in the constituent `members`.
- Produces: `parse_qqq_holdings(payload: dict) -> list[InstrumentDTO]` and `parse_soxx_holdings(content: bytes) -> list[InstrumentDTO]`.

- [ ] **Step 1: Write failing US provider tests**

Yahoo tests assert `auto_adjust=True`, `threads=False`, OHLC date normalization, empty history, invalid numeric rejection, and explicit US/HK/index symbol handling including `0700.HK` and `HSTECH.HK`. QQQ fixture includes COM, ADR, DRNY, cash, collateral, futures, synthetic cash, missing ticker, and two Alphabet share classes; only verified equity codes with tickers survive. SOXX fixture includes metadata before the CSV header and Equity plus non-Equity rows. Neither parser asserts a fixed constituent count.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/providers/test_yahoo_ohlcv.py tests/providers/test_invesco_universe.py tests/providers/test_ishares_soxx.py -v`
Expected: FAIL because US providers do not exist.

- [ ] **Step 3: Implement US providers**

Use the verified Invesco URL from the spec and its `effectiveDate`, `ticker`, and `securityTypeCode` fields. Keep COM/ADR/DRNY; exclude only explicitly known non-equity codes and raise `ProviderDataInvalid` on unknown types so a schema change cannot silently produce an incomplete universe. For SOXX locate the actual CSV header and retain `Asset Class == Equity`. Preserve canonical versus Yahoo provider symbol mappings explicitly.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/providers/test_yahoo_ohlcv.py tests/providers/test_invesco_universe.py tests/providers/test_ishares_soxx.py -v`
Expected: all US provider tests PASS.

- [ ] **Step 5: Verify current-snapshot semantics**

Run: `cd backend && python -m pytest tests/providers/test_invesco_universe.py tests/providers/test_ishares_soxx.py -v`
Expected: PASS; outputs contain source/effective-date metadata for logs and no historical-membership claim.

### Task 5: Binance and OKX Crypto Provider

**Files:**
- Create: `backend/app/providers/ccxt_ohlcv.py`
- Create: `backend/app/providers/crypto_catalog.py`
- Test: `backend/tests/providers/test_ccxt_ohlcv.py`
- Test: `backend/tests/providers/test_crypto_catalog.py`

**Interfaces:**
- Produces: `CcxtOhlcvProvider(exchange_id: Literal["binance", "okx"], clock: Callable[..., datetime] | None = None)` implementing `fetch_daily` with `adjustment="none"`.
- Produces: `crypto_instrument(entry: CryptoSymbol) -> InstrumentDTO`, using canonical `SYMBOL=EXCHANGE:BASE/QUOTE`, `exchange=entry.exchange`, and `provider_symbol=entry.symbol`; Binance and OKX never share an instrument ID.

- [ ] **Step 1: Write failing pagination tests**

Mock the CCXT exchange. Verify ascending UTC-millisecond pages, bounded page count, start/end inclusion, per-page limits, and termination on empty, short, repeated, or non-advancing pages. OKX requests use its history-candles mode. Bars dated on/after the mocked current UTC day are excluded. Duplicate timestamps, non-finite values, 429/418, and exchange errors map to provider errors. Catalog tests assert `BINANCE:BTC/USDT` and `OKX:BTC/USDT` are distinct records with the correct exchange/provider symbol.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/providers/test_ccxt_ohlcv.py tests/providers/test_crypto_catalog.py -v`
Expected: FAIL because the CCXT adapter does not exist.

- [ ] **Step 3: Implement bounded CCXT pagination**

Use `enableRateLimit=True`, explicit `1d`, and provider-specific history parameters. Do not use CCXT's experimental automatic pagination. Convert timestamps to UTC dates, sort and pass through the shared validator so duplicate timestamps reject visibly, and always close SDK resources in `finally`. Retries honor bounded exponential backoff and upstream wait guidance in the sync service, not inside parser functions.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/providers/test_ccxt_ohlcv.py tests/providers/test_crypto_catalog.py -v`
Expected: all crypto pagination tests PASS.

- [ ] **Step 5: Verify unfinished-bar behavior**

Run: `cd backend && python -m pytest tests/providers/test_ccxt_ohlcv.py tests/providers/test_crypto_catalog.py -v`
Expected: PASS with a frozen UTC clock proving today's incomplete bar never reaches SQLite.

### Task 6: Resumable Bar Synchronization and Built-In Market Tasks

**Files:**
- Create: `backend/app/services/bar_sync_service.py`
- Create: `backend/app/services/universe_sync_service.py`
- Create: `backend/app/tasks/builtin/sync_universes.py`
- Create: `backend/app/tasks/builtin/sync_daily.py`
- Modify: `backend/app/container.py`
- Test: `backend/tests/services/test_bar_sync_service.py`
- Test: `backend/tests/services/test_universe_sync_service.py`
- Test: `backend/tests/tasks/test_market_sync_tasks.py`

**Interfaces:**
- Consumes: `TaskContext.resources` containing instrument/bar repositories, `ProviderRegistry`, and `BarSyncService` once the container is finalized.
- Produces: `async BarSyncService.sync_instrument(instrument: InstrumentRecord, provider: OhlcvProvider, config: MarketSettings, full_refresh: bool = False) -> SyncOutcome`.
- Produces Tasks `market.sync_universes`, `market.sync_a_daily`, `market.sync_hk_daily`, `market.sync_us_daily`, and `market.sync_crypto_daily`.

- [ ] **Step 1: Write failing synchronization and Task tests**

Cover initial full load, incremental upsert with overlap, source change, manual full refresh, empty full response, and provider exception. When an overlapping OHLC value changes beyond `1e-6` relative/`1e-8` absolute tolerance, assert a second full-range fetch and `replace_all`; failed second fetch leaves old bars intact. A three-instrument fixture interrupted after instrument two resumes the missing one without duplicates. Mixed success/failure returns partial with counts and per-symbol logs; all failed returns failed.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/services/test_bar_sync_service.py tests/services/test_universe_sync_service.py tests/tasks/test_market_sync_tasks.py -v`
Expected: FAIL because sync services/Tasks do not exist.

- [ ] **Step 3: Implement per-instrument atomic synchronization**

Determine requested start from configured history, latest stored date minus overlap, or explicit full refresh. Download the complete request before any write. Compare overlapping OHLC with the pinned tolerances; refetch and transactionally replace the full configured history on adjustment/source changes. Otherwise upsert. Deduplicate instruments selected through multiple universes. The crypto Task first upserts `crypto_instrument` records for structured `MarketSettings.symbols` and chooses each record's exchange adapter, so provider changes cannot merge exchanges. Daily Task params support universe codes, explicit symbols, and `full_refresh`; execution continues after per-symbol errors and reports total/succeeded/failed/current progress.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/services tests/tasks tests/providers -v`
Expected: all provider, sync, and Task tests PASS.

- [ ] **Step 5: Run the full backend regression gate**

Run: `cd backend && python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`
Expected: all offline tests PASS and total backend coverage remains at least 80%.

### Task 7: Opt-In Online Smoke Tests and Operator Documentation

**Files:**
- Create: `backend/tests/online/test_market_smoke.py`
- Create: `backend/README.md`
- Modify: `config/settings.json` only to supply validated disabled defaults for newly registered Tasks

**Interfaces:**
- Produces repeatable small-sample commands and custom Task/indicator operating instructions for the frontend and final acceptance.

- [ ] **Step 1: Write online tests and prove they skip by default**

Mark tests `@pytest.mark.online` and skip unless `STOCK_LAB_ONLINE=1`. Each market uses one liquid representative instrument and a short bounded date range; universe tests only validate structure, not a fixed count. Default run must report all online tests skipped.

- [ ] **Step 2: Run the default suite and verify no online execution**

Run: `cd backend && python -m pytest -v`
Expected: all offline tests PASS; all online tests SKIP.

- [ ] **Step 3: Document startup and safe full synchronization**

Document environment setup, migration, disabled-by-default Tasks, manual small-sample sync, Cron semantics, provider limitations, qfq replacement behavior, resume/partial semantics, and how to add custom Task files. Do not claim SLA, historical constituents, or commercial redistribution rights.

- [ ] **Step 4: Run opt-in smoke only with explicit environment approval**

Run: `cd backend && STOCK_LAB_ONLINE=1 python -m pytest tests/online -v -s`
Expected: one small sample per available market PASS. If a region/provider is unavailable, record the exact provider error and leave existing data intact; do not bypass restrictions or switch to hidden APIs.

- [ ] **Step 5: Perform final offline verification**

Run: `cd backend && python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`
Expected: all default tests PASS and online tests remain excluded/skipped by default.
