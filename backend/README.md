# Local market-data backend

The FastAPI backend is a single-operator, single-process application. It stores
instruments, daily bars, indicator results, Task configuration, and run history
in SQLite. It has no authentication, Celery, Redis, or remote-access design.
Keep it on loopback unless access control has been designed separately.

## 1. Setup, migration, and startup

Python 3.12 or newer is required. From `backend/`:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

The process-owned `AppSettings` defaults are:

- hot JSON document: `../config/settings.json`;
- SQLite database: `../data/backend.sqlite3`;
- listener: `127.0.0.1:8000`, exactly one Uvicorn worker;
- maximum streamed request body: 1 MiB;
- fixed 60-second local-client rate windows: 120 reads, 30 writes, and 10
  compute/immediate-execution requests.

Startup applies Alembic migrations, discovers indicators and Tasks, adds only
missing **disabled** Task configurations, recovers stale runs, and recreates
future Cron jobs. It never starts a market download. To run the same migration
explicitly against the application database before startup:

```bash
.venv/bin/python -c \
  "from app.bootstrap import migrate_database; from app.config.application import DEFAULT_DATABASE_PATH; migrate_database(DEFAULT_DATABASE_PATH)"
```

Start the service from `backend/`:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

**Keep exactly one worker.** Scheduler jobs, revision locking, Task overlap
guards, and rate-limit counters are process-local. More workers would duplicate
schedules and weaken those guarantees. Check readiness with:

```bash
curl -sS http://127.0.0.1:8000/health
```

The response is `{"status":"ok"}`. API responses otherwise use the
`{success,data,error,meta}` envelope. Shutdown stops scheduling and waits for
active Tasks only up to the configured deadline.

## 2. Configuration and disabled-by-default Tasks

`config/settings.json` is a complete, strictly validated document. Provider,
timezone, indicator, and Task changes made through the API are hot-applied with
optimistic revision checks. Prefer the API while the server is running; edit the
JSON directly only while stopped, then restart. A stale revision returns 409,
and a failed post-persistence listener rolls back the file and runtime state.
Each market retains only `provider` and `request_timeout_seconds` (greater
than 0 and at most 300 seconds), both editable through the data-source settings
page. Market settings contain no crypto pairs. The Hong Kong Yahoo fallback is
canonically named `yfinance`, matching its bar source metadata. Crypto Task
`spot_pairs` accept only exact uppercase `BASE/QUOTE` spot pairs; lowercase,
derivative, malformed, or whitespace-padded entries are rejected before the
JSON is saved.

On read, a legacy market's `history_years`, `overlap_days`, and `concurrency`
are copied into its corresponding daily Task only when that Task does not
already define the parameter. Legacy `markets.crypto.symbols` is validated and
migrated to `market.sync_crypto_daily.params.spot_pairs`; an existing Task
`spot_pairs` key, including an explicit empty array, takes precedence. If a
legacy document has no `tasks` section, the required daily Task entries are
created during migration. Existing Task values take precedence; `max_retries`
is discarded and never migrated. This compatibility migration returns a new
validated document without changing `schema_version` or the stored revision.
New writes contain only the current schema.

Useful endpoints are:

```text
GET /api/v1/settings
PUT /api/v1/settings                         # complete document + expected_revision
GET /api/v1/tasks
GET /api/v1/tasks/{task_name}/config
PUT /api/v1/tasks/{task_name}/config         # expected_revision + changes
```

All built-in Tasks ship disabled with `cron: "0 0 * * *"`. Parameters otherwise
use the defaults below; the crypto daily Task starts with the same default
BTC/ETH `spot_pairs` that older versions kept in market settings. Disabling
prevents scheduled execution; it does **not** prevent an explicit manual run.

| Task | Default selection or behavior |
| --- | --- |
| `market.sync_universes` | Current `csi300`, `star_market`, `chinext`, `hstech`, `nasdaq100`, and `soxx` snapshots |
| `market.sync_a_daily` | Members of `csi300`, `star_market`, and `chinext` already stored locally |
| `market.sync_hk_daily` | Members of `hstech` already stored locally |
| `market.sync_us_daily` | Members of `nasdaq100` and `soxx` already stored locally |
| `market.sync_crypto_daily` | Structured entries in its own `spot_pairs` parameter |
| `system.purge_task_history` | Delete runs and cascading logs older than `retention_days` (default 30) |

Universe snapshots also add their related index/ETF instrument to the catalog;
related instruments are not universe members. Daily stock Tasks accept
`universe_codes`, `symbols`, `full_refresh`, `history_years`, `overlap_days`,
`concurrency`, and `adjustment`. Crypto accepts the same fields, with canonical
exchange-qualified symbols. Stock history defaults to 10 years; crypto defaults
to all available history (`history_years: null`). Overlap defaults to 45 days,
concurrency to 1 (bounded to 1–8), and adjustment to `auto` (`qfq` for ordinary
stocks, `none` for indices and crypto spot). Explicit `qfq` and `none` are also
supported. These are per-Task parameters, not market settings. Crypto also
accepts structured `spot_pairs`. With no explicit `symbols`, all Task
`spot_pairs` are registered and selected. With explicit `symbols`, only those
canonical IDs are selected; if `spot_pairs` is empty, they must already exist
as active local instruments. No market-level fallback is read. Empty
`spot_pairs` plus empty `symbols` fails before any Provider call. Universe sync
accepts only `universe_codes`. Explicit missing or inactive symbols and unknown
daily universe codes remain visible as failed items: mixed selections finish as
`partial`, and wholly unresolved selections finish as `failed` before provider
access. A default selection with no stored active instruments also fails.

## 3. Manual small sample, then full synchronization

Do not begin with schedules or an entire market. The safest first check is the
bounded online smoke suite in section 7. Then try one universe and one
instrument through the real API.

### 3.1 Limit the first real Task trial

A one-symbol Task is a small **instrument** sample, not a bounded-date request.
On a new instrument, stocks download the Task's `history_years` (10 by default),
and crypto downloads from the earliest available day because its default is
`null`. For a smaller initial trial, set `history_years: 1` in that daily Task's
configuration or manual-run `params`; optionally configure only one crypto
`spot_pairs` entry in that Task. Persisted Task changes use optimistic revision checks, while run
parameters apply only to that run. Record the original values so they can be
restored for production.

Run one current-universe refresh, for example:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/v1/tasks/market.sync_universes/runs \
  -H 'Content-Type: application/json' \
  -d '{"params":{"universe_codes":["nasdaq100"]}}'
```

The 202 response contains a run ID. Inspect terminal status and structured logs:

```bash
curl -sS \
  'http://127.0.0.1:8000/api/v1/tasks/market.sync_universes/runs?limit=10'
curl -sS \
  http://127.0.0.1:8000/api/v1/task-runs/RUN_ID/logs
```

Replace `RUN_ID` with the numeric ID. A universe request is `success`, `partial`,
or `failed`; inspect per-universe details rather than assuming that HTTP 202
means the download succeeded.

Find an exact stored symbol before running a stock daily Task:

```bash
curl -sS -G http://127.0.0.1:8000/api/v1/instruments \
  --data-urlencode 'universe_code=nasdaq100' \
  --data-urlencode 'limit=1'
```

If Apple is in the returned snapshot, its canonical symbol is `AAPL`. Run only
that instrument:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/v1/tasks/market.sync_us_daily/runs \
  -H 'Content-Type: application/json' \
  -d '{"params":{"symbols":["AAPL"],"history_years":1}}'
```

Equivalent one-instrument selections are:

| Market | Prerequisite | Example `symbols` value |
| --- | --- | --- |
| A-share | Refresh a universe containing the stock | `600519.SH`, if present |
| Hong Kong | Refresh `hstech` | `0700.HK`, if present; HSTECH uses four digits |
| US | Refresh `nasdaq100` | `AAPL`, if present |
| Crypto | Configure the Binance pair in the crypto Task's `spot_pairs` | `BINANCE:BTC/USDT` |

Use the exact symbol returned by `/instruments`; a symbol absent from the local
catalog is not downloaded implicitly for stocks. Crypto Tasks first upsert only
their own structured `spot_pairs`, then select only the requested canonical
symbol.

### 3.2 Promote to a full sync deliberately

1. Restore the desired production providers, per-Task `history_years`, and
   crypto Task `spot_pairs`.
2. If the trial used a shorter history, run the sampled instrument again with
   `"full_refresh": true`; an ordinary incremental run does not backfill the
   years omitted by the trial.
3. Refresh the required current universes and inspect every failure.
4. Run each daily Task without `symbols` or `universe_codes` to select its full
   default set. Use `full_refresh: true` only when intentional complete history
   replacement is required for the selected set.
5. Inspect run histories, per-symbol failures, and `/instruments`/`/bars` before
   enabling any Cron schedule. Run markets one at a time and respect upstream
   rate limits.

Full-market history can be large and slow. No command in this guide should be
interpreted as permission to bypass a provider restriction, use credentials or
hidden APIs, or ignore regional terms.

## 4. Replacement, resume, and partial-run semantics

- With the default `adjustment: "auto"`, ordinary stocks and ETFs use `qfq`;
  indices and crypto spot use `none`. A Task can explicitly select `qfq` or
  `none` instead.
- An initial load, explicit full refresh, or source/adjustment change requires a
  complete non-empty response. The response is normalized and validated before
  one transaction replaces that instrument's entire series.
- Ordinary incremental sync begins at the latest stored date minus
  `overlap_days` (45 by default) and upserts by `(instrument_id, date)`.
- Adjusted (`qfq`) history can change old OHLC values. If an overlapping OHLC
  value differs beyond the explicit tolerance, the incremental response is not
  written; a second full-history request is made and the whole series is
  replaced only if that response is complete and valid. Volume-only changes do
  not trigger this full replacement.
- Empty initial/full responses raise `NoDataAvailable` and preserve old bars.
  Empty ordinary incremental responses are successful up-to-date no-ops.
  Provider failures, malformed rows, and failed second full fetches never expose
  a partial response as a complete replacement.
- Each instrument finishes independently. Mixed results produce `partial`; all
  failures produce `failed`; all successes produce `success`. Other instruments
  continue after a safe per-symbol failure.
- Rerunning after interruption resumes through incremental overlap and unique
  database keys, without duplicate dates. It is not a run-ID checkpoint: selected
  instruments can be requested again, so provider failures and no-op outcomes
  must still be inspected. Startup marks stale queued/running rows interrupted.
- A universe is replaced only after its complete current snapshot validates.
  Failure preserves that universe's previous membership and does not prevent
  other requested universes from continuing.
- Starting the same Task while it is active creates a durable `skipped` overlap
  run rather than a second concurrent execution.

Every provider fetch is a single attempt: availability, rate-limit, timeout,
and schema failures are surfaced as real errors without an automatic retry.
`Retry-After` metadata may remain in diagnostics but never schedules another
request. Native HTTP, CCXT, and Yahoo requests receive the market's editable
timeout snapshot. SDKs without a common native timeout use a cooperative
`asyncio.wait_for` bound around their worker call; this cannot force socket
cancellation, and a timed-out late result is never written. Each daily Task
uses its own `concurrency` parameter and an `asyncio.Semaphore`; downloads are
bounded to 1–8 concurrent instruments, each instrument retains an independent
transaction, and final per-instrument results are aggregated in the original
selection order. Parent cancellation or a logging/progress failure cancels and
awaits all remaining symbol children before the run's overlap guard is released.

## 5. Standard Cron operation

Cron expressions have exactly five standard fields, in this order:

```text
minute hour day-of-month month day-of-week
```

There is no seconds field and no per-Task timezone. Expressions use the global
IANA `timezone` (`UTC` by default); stored next-run timestamps are UTC. Examples:

- `0 0 * * *`: every day at 00:00 in the configured timezone;
- `30 18 * * 1-5`: 18:30 Monday through Friday;
- `0 */6 * * *`: every six hours at minute zero.

Only enable a schedule after manual validation. Read the current Task config,
use its returned `revision`, and submit the intended fields, for example:

```bash
curl -sS -X PUT \
  http://127.0.0.1:8000/api/v1/tasks/market.sync_us_daily/config \
  -H 'Content-Type: application/json' \
  -d '{"expected_revision":CURRENT_REVISION,"enabled":true,"cron":"0 18 * * 1-5","params":{}}'
```

Replace `CURRENT_REVISION` with the integer from the GET response; the literal
placeholder is not valid JSON. Configuration changes rebuild future in-memory
jobs without restarting. Startup also recreates future jobs. Missed downtime is
not replayed, and a missed/misfired occurrence does not cancel future Cron
occurrences. Manual runs and scheduled runs share the same overlap guard and
history. Stop the single process to stop all scheduling.

## 6. Provider, universe, volume, and identifier limitations

- **AKShare/BaoStock/Yahoo:** public upstreams can rate-limit, change schemas,
  delay data, or be unavailable by region. Yahoo access through `yfinance` is
  not an SLA-backed market-data service. Do not silently substitute another
  provider when one fails.
- **Binance/OKX through CCXT:** only public spot endpoints are used, with CCXT
  rate limiting enabled and no credentials. Regional restrictions and exchange
  limits still apply. Daily crypto bars use completed UTC days. Bounded
  backward windows include empty pre-listing and short intermediate pages;
  repeated, non-advancing, duplicate, out-of-window, and page-cap responses fail
  rather than becoming a complete partial history.
- **Universe downloads:** these are current snapshots, not historical
  constituents. CSI 300 and exchange-board lists come through AKShare; HSTECH
  comes from the verified official factsheet PDF at
  `https://www.hsi.com.hk/api/wsit-hsi-ddoc-ea-public-website-proxy/v1/content/gcs/download?resource=%2Fpublic-website%2Fwebapp%2Ffactsheets%2Fen-hk%2Fhstech.pdf`.
  The PDF is byte-bounded, content-type checked, and parsed with `pypdf`; its
  declared count and schema remain mandatory, and failure preserves the last
  valid membership. Nasdaq-100 selection uses current Invesco QQQ equity holdings; SOXX uses
  current iShares equity holdings. Fund holdings/source methodology can differ
  from an index provider's official list. Never assert a permanent constituent
  count.
- **No SLA or redistribution grant:** provider availability, completeness, and
  correction timing are not guaranteed. These adapters do not grant commercial
  redistribution rights; review each provider's terms and licensing separately.
- **Equity volume is SHARES:** A-share lot counts are multiplied by 100 by the
  AKShare adapter; Hong Kong and Yahoo equity volumes are already share counts
  and are not rescaled by sync. Yahoo indices (`^NDX` and `HSTECH.HK`) map
  missing, NaN, and source-zero volume to `null`; equity zero volume remains a
  real zero. For crypto, volume is the base-asset quantity
  (for example BTC in `BTC/USDT`), not an equity share count. Do not compare the
  units as though they were identical across asset classes.
- **Crypto IDs are exchange-qualified:** Task `spot_pairs` uses
  `{"exchange":"binance","symbol":"BTC/USDT"}` or the OKX equivalent.
  Canonical IDs are `BINANCE:BTC/USDT` and `OKX:BTC/USDT`. The same pair on two
  exchanges has distinct instrument IDs and bar series; always use the
  canonical ID in Task overrides and API lookups.

Provider errors are surfaced with sanitized public messages. Preserve existing
local data, inspect the run logs, and report precise schema mismatches for
review rather than weakening validation or turning failures into passes.

## 7. Offline and explicitly opt-in online verification

The default suite uses temporary SQLite/configuration files, fixtures, and
mocks. Online tests are marked `online` and skip unless the environment variable
is exactly `STOCK_LAB_ONLINE=1`; provider SDK imports and network calls occur
only in functions reached by the opted-in tests, not during default collection.

```bash
.venv/bin/python -m pytest -v
.venv/bin/python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v
```

Only after the default suite is green, an operator who explicitly authorizes
public network access can run:

```bash
STOCK_LAB_ONLINE=1 .venv/bin/python -m pytest tests/online -v -s
```

The online suite uses bounded liquid samples (Moutai, Tencent through AKShare
and Yahoo, Apple, and Binance/OKX BTC/USDT), a recent inclusive 14-calendar-day
range, and structural checks for all six current-universe adapters. It does not run market Tasks or
full-history downloads. Every persistence/failure-preservation check uses a new
temporary migrated SQLite database, never `../data/backend.sqlite3`. Universe
assertions require valid non-empty structure and uniqueness, never fixed counts.
Provider unavailability remains a real test failure; it is not converted to a
skip or a fake pass.

## 8. Add custom indicators and Tasks

Discovery is recursive at **process startup**, not hot reload. Add local `.py`
files, keep imports free of network/work side effects, test them offline, and
restart the one worker. Import errors and duplicate public names deliberately
fail startup instead of selecting an arbitrary implementation.

### Custom indicator

1. Create `app/indicators/custom/my_indicator.py`.
2. Subclass `Indicator`; define a unique `name`, non-empty `display_name`, and
   `description`; decorate the class with `@register_indicator`.
3. Use a `params_model` derived from `IndicatorParams` (or another frozen Pydantic
   model with `extra="forbid"`). Validate and bound every parameter.
4. Implement synchronous `calculate(context, bars, params)`. Use
   `require_params` and `snapshot_bars`, return a new immutable
   `IndicatorResult`, and never mutate inputs. `app/indicators/builtin/rsi.py`
   and `donchian.py` are complete examples.
5. Restart, then verify `GET /api/v1/indicators` and a bounded compute request.

### Custom Task

1. Create `app/tasks/custom/my_task.py`.
2. Subclass `Task`; define a unique dotted `name`, non-empty `display_name`, and
   `description`; decorate with `@register_task`.
3. Use a frozen, extra-forbidding `TaskParams` model and implement
   `async run(context, params) -> TaskResult`. Use `require_task_params`, persist
   progress/logs through `TaskContext`, sanitize errors, and return a new result.
4. Restart. Startup adds a missing configuration with `enabled: false`; configure
   and manually validate it before enabling Cron.

Minimal Task shape:

```python
from typing import ClassVar

from pydantic import BaseModel

from app.tasks.base import (
    Task,
    TaskContext,
    TaskParams,
    TaskResult,
    require_task_params,
)
from app.tasks.registry import register_task


class ExampleParams(TaskParams):
    message: str = "hello"


@register_task
class ExampleTask(Task):
    name: ClassVar[str] = "custom.example"
    display_name: ClassVar[str] = "Example custom Task"
    description: ClassVar[str] = "Validate custom Task discovery"
    params_model: ClassVar[type[BaseModel]] = ExampleParams

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        options = require_task_params(params, ExampleParams)
        context.log("INFO", "Custom Task ran", message=options.message)
        return TaskResult(details={"message": options.message})
```

Production custom Tasks should add bounded input, comprehensive error handling,
and offline tests before restart.
