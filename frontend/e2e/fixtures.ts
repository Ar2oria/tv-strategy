import type { Page, Route } from "@playwright/test";
import type { TaskDescriptor, TaskLogDTO, TaskRunDTO } from "../src/types/task";

/** Deterministic API fixtures so E2E never touches a real provider. */

export const BARS = [
  {
    time: "2026-01-05",
    open: 10,
    high: 12,
    low: 9,
    close: 11,
    volume: 1_000,
    source: "yfinance",
    adjustment: "qfq",
  },
  {
    time: "2026-01-06",
    open: 11,
    high: 13,
    low: 10.5,
    close: 12,
    volume: 1_200,
    source: "yfinance",
    adjustment: "qfq",
  },
  {
    time: "2026-01-07",
    open: 12,
    high: 13.5,
    low: 11.5,
    close: 13,
    volume: 900,
    source: "yfinance",
    adjustment: "qfq",
  },
  {
    time: "2026-01-08",
    open: 13,
    high: 14,
    low: 12,
    close: 12.5,
    volume: 1_500,
    source: "yfinance",
    adjustment: "qfq",
  },
];

export const INSTRUMENTS = [
  {
    id: 1,
    active: true,
    symbol: "AAA",
    name: "Alpha Corp",
    market: "us_stock",
    exchange: "NASDAQ",
    currency: "USD",
    timezone: "America/New_York",
    instrument_type: "stock",
    provider_symbol: "AAA",
  },
  {
    id: 2,
    active: true,
    symbol: "BBB",
    name: "Beta Corp",
    market: "us_stock",
    exchange: "NASDAQ",
    currency: "USD",
    timezone: "America/New_York",
    instrument_type: "stock",
    provider_symbol: "BBB",
  },
];

const DONCHIAN = {
  name: "donchian",
  display_name: "Donchian Breakout",
  description: "Previous N-bar channel with breakout arrows",
  params_schema: {
    type: "object",
    properties: {
      window: { type: "integer", default: 2, minimum: 1, maximum: 200 },
    },
    required: ["window"],
  },
};

const RSI = {
  name: "rsi",
  display_name: "Relative Strength Index",
  description: "Wilder RSI with configurable thresholds",
  params_schema: {
    type: "object",
    properties: {
      window: { type: "integer", default: 2, minimum: 2, maximum: 200 },
    },
    required: ["window"],
  },
};

export const INDICATORS = [DONCHIAN, RSI];

function donchianResult(instanceId: string, window: number) {
  return {
    instance_id: instanceId,
    name: "donchian",
    panes: [],
    series: [
      {
        id: `${instanceId}:upper`,
        pane_id: "main",
        type: "line",
        title: `Previous ${window}-bar high`,
        points: [
          { time: "2026-01-05", value: 12.4, color: null },
          { time: "2026-01-06", value: 12.6, color: null },
          { time: "2026-01-07", value: 12.9, color: null },
        ],
        color: "#168b5b",
      },
    ],
    markers: [
      {
        time: "2026-01-07",
        position: "belowBar",
        shape: "arrowUp",
        color: "#168b5b",
        text: "Up breakout",
        tooltip: "Close 13 above previous 2-bar high 12.9",
        series_id: null,
      },
    ],
    reference_lines: [],
    warnings: [],
    error: null,
  };
}

function rsiResult(instanceId: string, window: number, failing: boolean) {
  if (failing) {
    return {
      instance_id: instanceId,
      name: "rsi",
      panes: [],
      series: [],
      markers: [],
      reference_lines: [],
      warnings: [],
      error: `RSI window=${window} needs at least ${window + 1} bars; series is empty.`,
    };
  }
  return {
    instance_id: instanceId,
    name: "rsi",
    panes: [{ id: `${instanceId}:rsi`, title: "RSI", height: 160, price_scale: "right" }],
    series: [
      {
        id: `${instanceId}:rsi`,
        pane_id: `${instanceId}:rsi`,
        type: "line",
        title: `RSI (${window})`,
        points: [
          { time: "2026-01-05", value: 45, color: null },
          { time: "2026-01-06", value: 55, color: null },
          { time: "2026-01-07", value: 72, color: "#d1345b" },
        ],
        color: "#2962ff",
      },
    ],
    markers: [],
    reference_lines: [
      { series_id: `${instanceId}:rsi`, value: 70, color: "#d1345b", title: "Overbought 70" },
      { series_id: `${instanceId}:rsi`, value: 30, color: "#168b5b", title: "Oversold 30" },
    ],
    warnings: [],
    error: null,
  };
}

const TASK = {
  name: "market.sync",
  display_name: "Synchronize market data",
  description: "Download daily bars for every configured universe",
  enabled: false,
  cron: "0 0 * * *",
  params: { market: "us_stock" },
  params_schema: {
    type: "object",
    properties: {
      market: {
        type: "string",
        enum: ["us_stock", "hk_stock", "a_share", "crypto"],
        default: "us_stock",
      },
    },
    required: ["market"],
  },
  revision: 3,
  next_run_at: "2026-01-09T00:00:00Z",
  last_run: null,
};

const RUN = {
  id: 11,
  task_name: "market.sync",
  trigger: "manual",
  status: "success",
  params: { market: "us_stock" },
  config_snapshot: null,
  progress: 100,
  error: null,
  created_at: "2026-01-08T00:00:00Z",
  started_at: "2026-01-08T00:00:01Z",
  finished_at: "2026-01-08T00:00:09Z",
};

const LOG = {
  id: 21,
  run_id: 11,
  level: "INFO",
  message: "Synchronized 2 instruments",
  context: { run_id: 11, symbol: "BINANCE:BTC/USDT", bar_count: 2 },
  created_at: "2026-01-08T00:00:09Z",
};

const ERROR_LOG = {
  id: 22,
  run_id: 11,
  level: "ERROR",
  message: "Instrument synchronization failed",
  context: {
    run_id: 11,
    universe_code: "nasdaq100",
    error_type: "ProviderUnavailable",
    detail: "CCXT binance OHLCV request failed (NetworkError)",
  },
  created_at: "2026-01-08T00:00:10Z",
};

const SETTINGS = {
  schema_version: 1,
  revision: 5,
  markets: {
    a_share: {
      provider: "akshare",
      history_years: 10,
      symbols: [],
      request_timeout_seconds: 20,
      max_retries: 3,
      concurrency: 1,
      overlap_days: 45,
    },
    hk_stock: {
      provider: "yfinance",
      history_years: 10,
      symbols: [],
      request_timeout_seconds: 20,
      max_retries: 3,
      concurrency: 1,
      overlap_days: 45,
    },
    us_stock: {
      provider: "yfinance",
      history_years: 10,
      symbols: [],
      request_timeout_seconds: 20,
      max_retries: 3,
      concurrency: 1,
      overlap_days: 45,
    },
    crypto: {
      provider: "binance",
      history_years: null,
      symbols: [{ exchange: "binance", symbol: "BTC/USDT" }],
      request_timeout_seconds: 20,
      max_retries: 3,
      concurrency: 1,
      overlap_days: 45,
    },
  },
  timezone: "UTC",
  indicators: { max_active_indicators: 20 },
  tasks: {
    "market.sync": { enabled: false, cron: "0 0 * * *", params: { market: "us_stock" } },
  },
};

interface NetworkTestFixture {
  market: string;
  provider: string;
  symbol: string;
  connected: boolean;
  latency_ms: number;
  price: number | null;
  price_date: string | null;
  currency: string | null;
  error_type: string | null;
  detail: string | null;
}

const NETWORK_TEST_RESULT: NetworkTestFixture = {
  market: "a_share",
  provider: "akshare",
  symbol: "600519.SH",
  connected: true,
  latency_ms: 12.3,
  price: 101.5,
  price_date: "2026-11-11",
  currency: "CNY",
  error_type: null,
  detail: null,
};

function envelope(data: unknown, meta: Record<string, unknown> = {}) {
  return { success: true, data, error: null, meta };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

export interface ApiState {
  emptyDatabase: boolean;
  rsiFails: boolean;
  settings: typeof SETTINGS;
  task: TaskDescriptor;
  revisionConflict: boolean;
  networkTestResult: NetworkTestFixture;
  runs: TaskRunDTO[];
  logs: TaskLogDTO[];
}

export function createState(): ApiState {
  return {
    emptyDatabase: false,
    rsiFails: false,
    settings: structuredClone(SETTINGS),
    task: structuredClone(TASK) as unknown as TaskDescriptor,
    revisionConflict: false,
    networkTestResult: structuredClone(NETWORK_TEST_RESULT),
    runs: [structuredClone(RUN) as unknown as TaskRunDTO],
    logs: [structuredClone(LOG) as unknown as TaskLogDTO, structuredClone(ERROR_LOG) as unknown as TaskLogDTO],
  };
}

export async function installApiRoutes(page: Page, state: ApiState) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path === "/api/v1/instruments") {
      return json(route, envelope(state.emptyDatabase ? [] : INSTRUMENTS));
    }
    if (path === "/api/v1/indicators") {
      return json(route, envelope(INDICATORS));
    }
    if (path === "/api/v1/bars") {
      return json(route, envelope(BARS, { count: BARS.length }));
    }
    if (path === "/api/v1/indicators/compute") {
      const body = request.postDataJSON() as {
        indicators: Array<{ instance_id: string; name: string; params: { window?: number } }>;
      };
      return json(
        route,
        envelope(
          body.indicators.map((item) =>
            item.name === "donchian"
              ? donchianResult(item.instance_id, item.params.window ?? 2)
              : rsiResult(item.instance_id, item.params.window ?? 2, state.rsiFails),
          ),
          { count: body.indicators.length },
        ),
      );
    }
    if (path === "/api/v1/tasks") {
      return json(route, envelope([state.task]));
    }
    if (path.endsWith("/config") && request.method() === "PUT") {
      const body = request.postDataJSON() as Record<string, unknown>;
      if (state.revisionConflict) {
        state.revisionConflict = false;
        state.task = { ...state.task, revision: state.task.revision + 1, cron: "0 6 * * *" };
        return json(
          route,
          {
            success: false,
            data: null,
            error: { code: "revision_conflict", message: "Request conflict" },
            meta: {},
          },
          409,
        );
      }
      state.task = {
        ...state.task,
        revision: state.task.revision + 1,
        ...(body.cron === undefined ? {} : { cron: String(body.cron) }),
        ...(body.enabled === undefined ? {} : { enabled: Boolean(body.enabled) }),
      };
      return json(route, envelope(state.task));
    }
    if (path.endsWith("/config")) {
      return json(route, envelope(state.task));
    }
    if (path.endsWith("/runs") && request.method() === "POST") {
      return json(route, envelope({ ...RUN, status: "queued" }), 202);
    }
    if (path.endsWith("/runs")) {
      const limit = Number(url.searchParams.get("limit") ?? 20);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const items = state.runs.slice(offset, offset + limit);
      return json(route, envelope(items, { count: items.length, total: state.runs.length }));
    }
    if (path.includes("/task-runs/") && path.endsWith("/logs")) {
      const match = path.match(/\/task-runs\/(\d+)\/logs$/);
      const runId = match === null ? null : Number(match[1]);
      const limit = Number(url.searchParams.get("limit") ?? 20);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const runLogs = state.logs.filter((log) => log.run_id === runId);
      const items = runLogs.slice(offset, offset + limit);
      return json(route, envelope(items, { count: items.length, total: runLogs.length }));
    }
    if (path === "/api/v1/settings" && request.method() === "PUT") {
      const body = request.postDataJSON() as Record<string, unknown>;
      if (state.revisionConflict) {
        state.revisionConflict = false;
        state.settings = {
          ...state.settings,
          revision: state.settings.revision + 1,
        };
        return json(
          route,
          {
            success: false,
            data: null,
            error: { code: "revision_conflict", message: "Request conflict" },
            meta: {},
          },
          409,
        );
      }
      state.settings = {
        ...(body as unknown as typeof SETTINGS),
        revision:
          Number((body as { expected_revision: number }).expected_revision) + 1,
      };
      return json(route, envelope(state.settings));
    }
    if (path.endsWith("/network-test") && request.method() === "POST") {
      const body = request.postDataJSON() as { symbol: string };
      return json(
        route,
        envelope({ ...state.networkTestResult, symbol: body.symbol }),
      );
    }
    if (path === "/api/v1/settings") {
      return json(route, envelope(state.settings));
    }
    return json(
      route,
      {
        success: false,
        data: null,
        error: { code: "not_found", message: "Resource not found" },
        meta: {},
      },
      404,
    );
  });
}
