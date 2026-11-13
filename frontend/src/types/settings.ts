import type { JsonObject } from "./api";

export interface MarketSettings {
  provider: string;
  request_timeout_seconds: number;
  proxy_url: string | null;
}

export interface NetworkTestRequest {
  symbol: string;
}

export interface NetworkTestResult {
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
