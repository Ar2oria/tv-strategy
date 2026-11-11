export const settingsPayload = {
  schema_version: 1,
  revision: 4,
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
  indicators: {
    max_active_indicators: 20,
  },
  tasks: {
    "market.sync": {
      enabled: true,
      cron: "0 0 * * *",
      params: { value: 1, nested: [true, null] },
    },
    "market.sync_crypto_daily": {
      enabled: false,
      cron: "0 0 * * *",
      params: {
        spot_pairs: [{ exchange: "binance", symbol: "BTC/USDT" }],
      },
    },
  },
};

export const barPayload = {
  time: "2026-01-05",
  open: 10,
  high: 12,
  low: 9,
  close: 11,
  volume: 100,
  source: "yfinance",
  adjustment: "qfq",
};

export const instrumentPayload = {
  id: 1,
  active: true,
  symbol: "AAA",
  name: "Alpha",
  market: "us_stock",
  exchange: "NASDAQ",
  currency: "USD",
  timezone: "America/New_York",
  instrument_type: "stock",
  provider_symbol: "AAA",
};

export const indicatorDescriptorPayload = {
  name: "rsi",
  display_name: "Relative Strength Index",
  description: "Momentum indicator",
  params_schema: {
    type: "object",
    properties: { period: { type: "integer", default: 14 } },
    required: ["period"],
  },
};

export const indicatorComputationPayload = {
  instance_id: "rsi-1",
  name: "rsi",
  panes: [{ id: "rsi-1", title: "RSI", height: 160, price_scale: "right" }],
  series: [
    {
      id: "rsi-1.value",
      pane_id: "rsi-1",
      type: "line",
      title: "RSI",
      points: [{ time: "2026-01-05", value: 55.5, color: null }],
      color: "#2962ff",
    },
  ],
  markers: [
    {
      time: "2026-01-05",
      position: "aboveBar",
      shape: "circle",
      color: "#2962ff",
      text: null,
      tooltip: null,
      series_id: "rsi-1.value",
    },
  ],
  reference_lines: [
    {
      series_id: "rsi-1.value",
      value: 70,
      color: "#8b94a7",
      title: "Overbought",
    },
  ],
  warnings: ["warmup"],
  error: null,
};

export const taskRunPayload = {
  id: 8,
  task_name: "market.sync",
  trigger: "manual",
  status: "success",
  params: { value: 1 },
  config_snapshot: {
    enabled: true,
    cron: "0 0 * * *",
    params: { value: 1 },
  },
  progress: 100,
  error: null,
  created_at: "2026-01-05T00:00:00Z",
  started_at: "2026-01-05T00:00:01Z",
  finished_at: "2026-01-05T00:00:02Z",
};

export const taskPayload = {
  name: "market.sync",
  display_name: "Synchronize market",
  description: "Synchronize market data",
  enabled: true,
  cron: "0 0 * * *",
  params: { value: 1 },
  params_schema: {
    type: "object",
    properties: { value: { type: "integer", default: 1 } },
  },
  revision: 4,
  next_run_at: "2026-01-06T00:00:00Z",
  last_run: taskRunPayload,
};

export const taskLogPayload = {
  id: 3,
  run_id: 8,
  level: "INFO",
  message: "Completed",
  context: { count: 2 },
  created_at: "2026-01-05T00:00:02Z",
};
