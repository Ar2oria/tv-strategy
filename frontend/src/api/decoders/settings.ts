import type {
  IndicatorSettings,
  MarketSettings,
  NetworkTestResult,
  Settings,
  TaskSettings,
} from "../../types/settings";
import {
  decodeBoolean,
  decodeFiniteNumber,
  decodeJsonObject,
  decodeLiteral,
  decodeNonNegativeInteger,
  decodeNullable,
  decodePositiveInteger,
  decodeRecord,
  decodeRecordOf,
  decodeString,
} from "../decoding";

function decodeMarketSettings(value: unknown): MarketSettings {
  const item = decodeRecord(value);
  return {
    provider: decodeString(item.provider),
    request_timeout_seconds: decodeFiniteNumber(item.request_timeout_seconds),
    proxy_url:
      item.proxy_url === undefined
        ? null
        : decodeNullable(item.proxy_url, decodeString),
  };
}

export function decodeNetworkTestResult(value: unknown): NetworkTestResult {
  const item = decodeRecord(value);
  return {
    market: decodeString(item.market),
    provider: decodeString(item.provider),
    symbol: decodeString(item.symbol),
    connected: decodeBoolean(item.connected),
    latency_ms: decodeFiniteNumber(item.latency_ms),
    price: decodeNullable(item.price, decodeFiniteNumber),
    price_date: decodeNullable(item.price_date, decodeString),
    currency: decodeNullable(item.currency, decodeString),
    error_type: decodeNullable(item.error_type, decodeString),
    detail: decodeNullable(item.detail, decodeString),
  };
}

function decodeTaskSettings(value: unknown): TaskSettings {
  const item = decodeRecord(value);
  return {
    enabled: decodeBoolean(item.enabled),
    cron: decodeString(item.cron),
    params: decodeJsonObject(item.params),
  };
}

function decodeIndicatorSettings(value: unknown): IndicatorSettings {
  const item = decodeRecord(value);
  return {
    max_active_indicators: decodePositiveInteger(item.max_active_indicators),
  };
}

export function decodeSettings(value: unknown): Settings {
  const item = decodeRecord(value);
  return {
    schema_version: decodeLiteral(item.schema_version, [1]),
    revision: decodeNonNegativeInteger(item.revision),
    markets: decodeRecordOf(item.markets, decodeMarketSettings),
    timezone: decodeString(item.timezone),
    indicators: decodeIndicatorSettings(item.indicators),
    tasks: decodeRecordOf(item.tasks, decodeTaskSettings),
  };
}
