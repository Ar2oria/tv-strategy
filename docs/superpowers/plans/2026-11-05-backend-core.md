# Backend Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI backend with hot JSON configuration, SQLite repositories, extensible indicator and Task registries, standard Cron scheduling, and tested APIs.

**Architecture:** One Uvicorn process owns all runtime state. Synchronous SQLAlchemy sessions are short-lived; CPU or blocking provider work is dispatched outside the event loop. Configuration and registry results are immutable Pydantic objects; all mutating workflows return new models.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite, Alembic, APScheduler 3.11.x, croniter, pandas, pytest, pytest-asyncio, coverage.

**Spec:** `docs/superpowers/specs/2026-11-05-local-stock-indicator-system-design.md`

## Global Constraints

- Create only `backend/` plus the approved `config/settings.json` and `data/` paths; do not reuse or modify existing indicator/validation directories or root dependency/test files.
- Every feature follows RED → GREEN → refactor; backend line coverage is at least 80%.
- Public API envelope is `{success, data, error, meta}`; clients never receive tracebacks.
- Pydantic input models are frozen; calculations do not mutate caller objects.
- Use one Uvicorn worker and bind `127.0.0.1`; no Celery, Redis, authentication, minute bars, backtesting, or indicator hot reload.
- Task classes have one config each and one async `run` entry; indicators have one `calculate` entry and restart-based registration.
- Do not automatically commit or push; Git operations require a separate explicit user request.
- Backend Python commands use `backend/.venv/bin/python` (or an already activated equivalent environment); Task 1 creates that environment without touching the repository root `.venv`.

## Review Focus

1. Invalid or concurrently revised JSON must not overwrite valid configuration: Task 1 and Task 6 test validation, revision conflict, write failure, and listener rollback.
2. Duplicate, unsorted, null, NaN, infinite, or misaligned indicator points must be rejected without affecting other indicators: Task 3 and Task 4 test each case.
3. Sunday `0` and day-of-month/day-of-week OR semantics must match standard Crontab: Task 5 tests both against fixed instants.
4. Manual and scheduled overlap must create a `skipped` run rather than execute twice; restart marks stale runs `interrupted`: Task 5 tests both.
5. Holiday-shortened weeks and visible-range requests must preserve actual bar dates while using earlier history for indicators: Task 4 tests aggregation and warmup trimming.

---

### Task 1: Backend Skeleton and Hot JSON Configuration

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/config/models.py`
- Create: `backend/app/config/store.py`
- Create: `backend/app/config/defaults.py`
- Create: `config/settings.json`
- Test: `backend/tests/config/test_store.py`

**Interfaces:**
- Produces: `Settings`, `MarketSettings`, `TaskSettings`, `CryptoSymbol(exchange: Literal["binance", "okx"], symbol: str)`, `ConfigService.get() -> Settings`, and `ConfigService.update(expected_revision: int, build_next: Callable[[Settings], Settings]) -> Settings`.
- Crypto defaults are `CryptoSymbol("binance", "BTC/USDT")` and `CryptoSymbol("binance", "ETH/USDT")`; `MarketSettings.symbols` stores these structured entries rather than ambiguous strings.
- `ConfigService.subscribe(listener: Callable[[Settings], None]) -> None`; listeners are called with a deep copy after atomic persistence.
- `ConfigService.add_validator(validator: Callable[[Settings], None]) -> None`; validators run before persistence.

- [ ] **Step 1: Create the package/test setup and write failing configuration tests**

Create `pyproject.toml` with runtime/dev dependencies, then run `cd backend && python -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'`. This setup must not install into or modify the root environment.

Test defaults: `schema_version == 1`, `revision == 0`, stock `history_years == 10`, crypto `history_years is None` with structured Binance BTC/ETH defaults, the cleanup Task disabled. Test returned models cannot alter stored state. Test a valid update increments revision once. Test stale revision raises `ConfigConflictError`; invalid timezone/Cron raises `ConfigValidationError`; listener failure restores old file and old runtime value. Assert no temp files remain after write failure.

```python
with pytest.raises(ConfigConflictError):
    service.update(expected_revision=service.get().revision - 1, build_next=lambda old: old)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/config/test_store.py -v`
Expected: FAIL because config modules do not exist.

- [ ] **Step 3: Implement configuration models and store**

Define frozen Pydantic models with `extra="forbid"`. `ConfigService` uses `threading.RLock`, `model_copy(deep=True)`, and atomic `flush + fsync + os.replace`. On listener failure, atomically restore the previous document and best-effort reapply previous listeners; raise `ConfigApplyError` with the original context. `defaults.py` creates a disabled config for `system.purge_task_history`; market Tasks are added by the market-data plan and receive disabled configs when registered.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/config/test_store.py -v`
Expected: all configuration tests PASS.

- [ ] **Step 5: Review the task boundary**

Run: `cd backend && python -m pytest tests/config -v`
Expected: PASS; confirm no root `requirements.txt` or existing config was modified.

### Task 2: SQLite Schema and Repositories

**Files:**
- Create: `backend/app/domain/dto.py`
- Create: `backend/app/db/database.py`
- Create: `backend/app/models/instrument.py`
- Create: `backend/app/models/bar.py`
- Create: `backend/app/models/task_run.py`
- Create: `backend/app/repositories/instruments.py`
- Create: `backend/app/repositories/bars.py`
- Create: `backend/app/repositories/task_runs.py`
- Create: `backend/alembic/versions/0001_initial.py`
- Test: `backend/tests/repositories/test_instruments.py`
- Test: `backend/tests/repositories/test_bars.py`
- Test: `backend/tests/db/test_migration.py`

**Interfaces:**
- Produces: `SessionFactory`, `InstrumentRepository.upsert_catalog(...)`, `InstrumentRepository.replace_universe(...)`, `BarRepository.get_all_until(...)`, `BarRepository.get_range(...)`, `BarRepository.upsert(...)`, `BarRepository.replace_all(...)`, and Task run/log CRUD.
- Shared frozen types: `Market = Literal["a_share", "hk_stock", "us_stock", "crypto"]`, `InstrumentType = Literal["stock", "index", "etf", "crypto_spot"]`, `Adjustment = Literal["qfq", "none"]`, and `Timeframe = Literal["1d", "1w", "1M"]`.
- Shared frozen DTOs: `InstrumentDTO(symbol, name, market, exchange, currency, timezone, instrument_type, provider_symbol)`, `InstrumentRecord(InstrumentDTO)` adding `id` and `active`, `BarDTO(time, open, high, low, close, volume, source, adjustment)`, and `UniverseSnapshot(universe_code: str, source: str, effective_date: date | None, members: tuple[InstrumentDTO, ...], related_instruments: tuple[InstrumentDTO, ...] = ())`.
- `InstrumentRepository.replace_universe(snapshot: UniverseSnapshot) -> tuple[int, int]` returns `(instrument_count, member_count)` and upserts members and related instruments but replaces membership only with `members`; related index/ETF instruments never become their own constituents.

- [ ] **Step 1: Write failing repository and migration tests**

Use a temporary file database. Assert duplicate `(market, symbol)` and `(instrument_id, date)` are impossible; universe replacement is transactional and does not delete instruments, and related index/ETF instruments are queryable but absent from membership; upsert updates a bar without duplication; `replace_all` removes stale dates; `get_all_until` is ascending and excludes later dates. Alembic test upgrades to head and checks foreign keys are enabled.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/repositories tests/db/test_migration.py -v`
Expected: FAIL because models and migrations do not exist.

- [ ] **Step 3: Implement schema and repository methods**

Create `instruments`, `universe_memberships`, `daily_bars`, `task_runs`, and `task_logs` with the spec's unique constraints and indexes. Membership rows retain snapshot source/effective date. Use SQLite WAL, foreign keys, parameterized SQLAlchemy operations, and `INSERT ... ON CONFLICT DO UPDATE` for bars. Every public repository method returns detached DTOs or ORM snapshots rather than mutating input collections.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/repositories tests/db/test_migration.py -v`
Expected: all repository and migration tests PASS.

- [ ] **Step 5: Check migration repeatability**

Run: `cd backend && python -m pytest tests/db/test_migration.py -v`
Expected: two consecutive upgrades in the test PASS without duplicate schema objects.

### Task 3: Indicator Protocol, Registry, Validation, and Examples

**Files:**
- Create: `backend/app/indicators/models.py`
- Create: `backend/app/indicators/base.py`
- Create: `backend/app/indicators/registry.py`
- Create: `backend/app/indicators/discovery.py`
- Create: `backend/app/indicators/validation.py`
- Create: `backend/app/indicators/builtin/donchian.py`
- Create: `backend/app/indicators/builtin/rsi.py`
- Create: `backend/app/indicators/custom/__init__.py`
- Test: `backend/tests/indicators/test_registry.py`
- Test: `backend/tests/indicators/test_validation.py`
- Test: `backend/tests/indicators/test_donchian.py`
- Test: `backend/tests/indicators/test_rsi.py`

**Interfaces:**
- Produces: `Indicator.calculate(context: IndicatorContext, bars: Sequence[BarDTO], params: BaseModel) -> IndicatorResult` and `IndicatorRegistry.get(name: str) -> IndicatorDescriptor`.
- Result models: `PaneDefinition`, `SeriesDefinition`, `SeriesPoint`, `MarkerDefinition`, `ReferenceLine`, `IndicatorResult`.
- Produces: `validate_result(result: IndicatorResult, visible_dates: set[date]) -> None` and `namespace_result(instance_id: str, result: IndicatorResult) -> IndicatorResult`.

- [ ] **Step 1: Write failing protocol and example tests**

Registering duplicate names raises `RegistryConflictError`. Descriptor JSON Schema contains parameter defaults and bounds. Donchian with `window=3` uses the *previous* three bars, emits a below-bar arrow for an upward breakout and an above-bar arrow for a downward breakout. RSI with only gains returns 100 after warmup; only losses returns 0; 30/70 lines are configurable. Validation rejects duplicate IDs, unsorted/duplicate points, NaN/infinity, unknown marker dates, and invalid target series. Namespacing leaves `main` shared and prefixes every other pane/series ID without mutating the input result.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/indicators -v`
Expected: FAIL because indicator modules do not exist.

- [ ] **Step 3: Implement protocol and examples**

Allow line, area, and histogram series; marker shapes `arrowUp`, `arrowDown`, `circle`, `square`; positions `aboveBar`, `belowBar`, `inBar`. Tooltip/text are bounded plain strings. Use pandas for RSI and previous-window rolling extrema. Discovery imports all Python modules under built-in and custom packages at startup; decorator registration rejects invalid classes and duplicate names.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/indicators -v`
Expected: all indicator tests PASS.

- [ ] **Step 5: Run example edge cases**

Run: `cd backend && python -m pytest tests/indicators/test_donchian.py tests/indicators/test_rsi.py -v`
Expected: PASS with empty, shorter-than-window, and constant-price inputs producing no crash and explicit empty/warning output.

### Task 4: Bar Aggregation, Indicator Computation, and Read APIs

**Files:**
- Create: `backend/app/services/bar_service.py`
- Create: `backend/app/services/indicator_service.py`
- Create: `backend/app/api/schemas.py`
- Create: `backend/app/api/responses.py`
- Create: `backend/app/api/instruments.py`
- Create: `backend/app/api/bars.py`
- Create: `backend/app/api/indicators.py`
- Test: `backend/tests/services/test_bar_service.py`
- Test: `backend/tests/services/test_indicator_service.py`
- Test: `backend/tests/api/test_read_apis.py`

**Interfaces:**
- Consumes: repositories from Task 2 and registry/results from Task 3.
- Produces: `BarService.get_visible(...) -> list[BarDTO]`, `BarService.get_history_until(...) -> list[BarDTO]`, `aggregate_daily(bars: Sequence[BarDTO], timeframe: Timeframe) -> list[BarDTO]`.
- Produces: `IndicatorService.compute(request: IndicatorComputeRequest) -> list[IndicatorComputation]`.

- [ ] **Step 1: Write failing aggregation, computation, and API tests**

Weekly and monthly aggregation uses first open, max high, min low, last close, summed volume, and the actual last trading date. A Friday holiday still labels that week with Thursday. A visible Monday request for RSI uses earlier daily history but emits no point before Monday. Two instances of RSI with different parameters have distinct namespaced IDs. One raising indicator returns a sanitized error while the other succeeds. API tests cover instruments search, day/week/month bars, batch compute, empty results, invalid dates, and the response envelope.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/services/test_bar_service.py tests/services/test_indicator_service.py tests/api/test_read_apis.py -v`
Expected: FAIL because services/routes do not exist.

- [ ] **Step 3: Implement aggregation and computation**

Group daily bars by ISO year/week or year/month without writing aggregates to SQLite. Indicator computation reads all stored history through `end`, aggregates once, then calls each indicator with a fresh sequence. Trim outputs to `start..end` before namespacing and validation. Execute synchronous compute through `asyncio.to_thread` in the async route; cap active indicators at 20 and output points at the configured maximum.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/services tests/api/test_read_apis.py -v`
Expected: all service and read API tests PASS.

- [ ] **Step 5: Verify failure isolation**

Run: `cd backend && python -m pytest tests/services/test_indicator_service.py tests/api/test_read_apis.py -v`
Expected: PASS; K-line and successful indicator data remain present when another indicator fails.

### Task 5: Task Registry, Runner, Logs, and Standard Cron Scheduler

**Files:**
- Create: `backend/app/tasks/base.py`
- Create: `backend/app/tasks/registry.py`
- Create: `backend/app/tasks/context.py`
- Create: `backend/app/services/task_runner.py`
- Create: `backend/app/services/resources.py`
- Create: `backend/app/services/cron_scheduler.py`
- Create: `backend/app/services/task_service.py`
- Create: `backend/app/tasks/builtin/purge_history.py`
- Create: `backend/app/api/tasks.py`
- Test: `backend/tests/tasks/test_registry.py`
- Test: `backend/tests/tasks/test_task_runner.py`
- Test: `backend/tests/tasks/test_cron_scheduler.py`
- Test: `backend/tests/api/test_task_apis.py`

**Interfaces:**
- Produces: `Task.run(context: TaskContext, params: BaseModel) -> TaskResult` as the only task execution entry.
- Produces: `async TaskRunner.start(task_name: str, trigger: TriggerType, params_override: dict | None = None) -> TaskRunDTO`.
- `TaskContext` contains `run_id`, frozen `settings`, `log`, `report_progress`, and `resources: RuntimeResources`. `RuntimeResources` exposes instrument/bar repositories plus optional `ProviderRegistry` and `BarSyncService` through `TYPE_CHECKING` forward references; core tests use fakes and market Tasks assert required services are configured.
- Produces: `next_run_after(expression: str, after: datetime, timezone: str) -> datetime` returning a timezone-aware UTC datetime, and `CronScheduler.apply_settings(settings: Settings) -> None`.

- [ ] **Step 1: Write failing Task and Cron tests**

Define test Tasks that block on an event, return partial progress, log, and raise. Starting the same Task while blocked creates one `skipped` run and only one execution. Success/partial/failure persist progress and logs; stale running rows become interrupted at startup. `0 9 * * 0` from a Monday resolves to Sunday, and `0 0 13 * 5` fires on both the 13th and Fridays. Config validation rejects six-field Cron and invalid Task params. API tests cover list, config update, immediate run, run history, and logs.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/tasks tests/api/test_task_apis.py -v`
Expected: FAIL because Task framework does not exist.

- [ ] **Step 3: Implement Task framework and scheduler**

Use an async in-memory running set guarded by a lock; both manual and scheduled calls enter `TaskRunner.start`. Persist params/config snapshots and progress. Use `croniter(..., day_or=True)` for next times and APScheduler `DateTrigger` one-shot jobs; schedule the next occurrence after each due callback. Reconcile enabled jobs only after full validation. Missed downtime is not replayed. `purge_history` deletes logs/runs older than configured retention.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/tasks tests/api/test_task_apis.py -v`
Expected: all Task and Cron tests PASS.

- [ ] **Step 5: Verify scheduler idempotence**

Run: `cd backend && python -m pytest tests/tasks/test_cron_scheduler.py tests/tasks/test_task_runner.py -v`
Expected: repeated `apply_settings` leaves one APScheduler job per enabled Task and overlapping starts remain skipped.

### Task 6: Application Assembly, Settings API, and Security Limits

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/container.py`
- Create: `backend/app/api/settings.py`
- Create: `backend/app/api/errors.py`
- Create: `backend/app/middleware/rate_limit.py`
- Create: `backend/app/middleware/request_limits.py`
- Create: `backend/app/bootstrap.py`
- Test: `backend/tests/api/test_settings_api.py`
- Test: `backend/tests/api/test_security_limits.py`
- Test: `backend/tests/test_application.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: `create_app(settings: AppSettings | None = None) -> FastAPI` and a container exposing registries, repositories, `ConfigService`, `TaskRunner`, and `CronScheduler`.

- [ ] **Step 1: Write failing application integration tests**

Starting the app discovers built-ins, creates missing disabled configs only for registered Tasks, marks stale runs interrupted, and schedules only enabled Tasks. `GET settings` returns the current revision; `PUT settings` hot-applies new timezone/provider values and reschedules without restarting. A listener failure restores both file and scheduler state. Two concurrent revisions produce one 409. Invalid input returns sanitized errors; rate limits return 429; oversized bodies return 413; health and non-API 404 behavior are explicit.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/api/test_settings_api.py tests/api/test_security_limits.py tests/test_application.py -v`
Expected: FAIL because application assembly does not exist.

- [ ] **Step 3: Implement composition root and middleware**

Wire startup/shutdown through lifespan. Add validators before persistence and scheduler/provider listeners after persistence. Use route-aware in-memory fixed-window limits for every endpoint with stricter write/compute buckets. Limit JSON body size and all query ranges. Production static mounting is added by the frontend plan after a build exists; API behavior must not depend on frontend files.

- [ ] **Step 4: Run the complete backend suite**

Run: `cd backend && python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`
Expected: all tests PASS and coverage is at least 80%.

- [ ] **Step 5: Review interfaces for the next plan**

Run: `cd backend && python -m pytest tests/test_application.py tests/api -v`
Expected: PASS; record the exact provider DTO and Task context interfaces for `2026-11-05-market-data.md`.
