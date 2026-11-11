import type { TaskDescriptor } from "../types/task";

/** Mirrors the backend CryptoDailySyncParams schema, including its $ref item. */
export const cryptoTaskFixture: TaskDescriptor = {
  name: "market.sync_crypto_daily",
  display_name: "Synchronize crypto daily bars",
  description: "Resume exchange-scoped crypto OHLCV synchronization",
  enabled: false,
  cron: "0 0 * * *",
  params: {
    universe_codes: [],
    symbols: [],
    full_refresh: false,
    history_years: null,
    overlap_days: 45,
    concurrency: 1,
    adjustment: "auto",
    spot_pairs: [{ exchange: "binance", symbol: "BTC/USDT" }],
  },
  params_schema: {
    $defs: {
      CryptoSymbol: {
        additionalProperties: false,
        description: "A crypto market symbol scoped to a supported exchange.",
        properties: {
          exchange: {
            enum: ["binance", "okx"],
            title: "Exchange",
            type: "string",
          },
          symbol: { title: "Symbol", type: "string" },
        },
        required: ["exchange", "symbol"],
        title: "CryptoSymbol",
        type: "object",
      },
    },
    additionalProperties: false,
    description: "Daily options plus the default exchange-qualified crypto catalog.",
    properties: {
      universe_codes: {
        default: [],
        items: { type: "string" },
        title: "Universe Codes",
        type: "array",
      },
      symbols: {
        default: [],
        items: { type: "string" },
        title: "Symbols",
        type: "array",
      },
      full_refresh: { default: false, title: "Full Refresh", type: "boolean" },
      history_years: {
        anyOf: [{ minimum: 1, type: "integer" }, { type: "null" }],
        default: null,
        title: "History Years",
      },
      overlap_days: {
        default: 45,
        maximum: 366,
        minimum: 1,
        title: "Overlap Days",
        type: "integer",
      },
      concurrency: {
        default: 1,
        maximum: 8,
        minimum: 1,
        title: "Concurrency",
        type: "integer",
      },
      adjustment: {
        default: "auto",
        enum: ["auto", "qfq", "none"],
        title: "Adjustment",
        type: "string",
      },
      spot_pairs: {
        default: [],
        items: { $ref: "#/$defs/CryptoSymbol" },
        title: "Spot Pairs",
        type: "array",
      },
    },
    title: "CryptoDailySyncParams",
    type: "object",
  },
  revision: 3,
  next_run_at: null,
  last_run: null,
};
