import type {
  CryptoSymbol,
  IndicatorSettings,
  MarketSettings,
  Settings,
  TaskSettings,
} from "../../types/settings";
import {
  decodeArray,
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

function decodeCryptoSymbol(value: unknown): CryptoSymbol {
  const item = decodeRecord(value);
  return {
    exchange: decodeLiteral(item.exchange, ["binance", "okx"]),
    symbol: decodeString(item.symbol),
  };
}

function decodeMarketSettings(value: unknown): MarketSettings {
  const item = decodeRecord(value);
  return {
    provider: decodeString(item.provider),
    history_years: decodeNullable(item.history_years, decodePositiveInteger),
    symbols: decodeArray(item.symbols, decodeCryptoSymbol),
    request_timeout_seconds: decodeFiniteNumber(item.request_timeout_seconds),
    max_retries: decodeNonNegativeInteger(item.max_retries),
    concurrency: decodeLiteral(item.concurrency, [1]),
    overlap_days: decodePositiveInteger(item.overlap_days),
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
