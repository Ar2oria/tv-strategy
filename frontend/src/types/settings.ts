import type { JsonObject } from "./api";

export interface CryptoSymbol {
  exchange: "binance" | "okx";
  symbol: string;
}

export interface MarketSettings {
  provider: string;
  history_years: number | null;
  symbols: CryptoSymbol[];
  request_timeout_seconds: number;
  max_retries: number;
  concurrency: 1;
  overlap_days: number;
}

export interface TaskSettings {
  enabled: boolean;
  cron: string;
  params: JsonObject;
}

export interface IndicatorSettings {
  max_active_indicators: number;
}

export interface Settings {
  schema_version: 1;
  revision: number;
  markets: Record<string, MarketSettings>;
  timezone: string;
  indicators: IndicatorSettings;
  tasks: Record<string, TaskSettings>;
}

export type SettingsUpdate = Omit<Settings, "revision"> & {
  expected_revision: number;
};
