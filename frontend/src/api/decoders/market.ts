import type { BarDTO, InstrumentRecord } from "../../types/market";
import {
  decodeArray,
  decodeBoolean,
  decodeFiniteNumber,
  decodeLiteral,
  decodeNullable,
  decodePositiveInteger,
  decodeRecord,
  decodeString,
} from "../decoding";

export function decodeBar(value: unknown): BarDTO {
  const item = decodeRecord(value);
  return {
    time: decodeString(item.time),
    open: decodeFiniteNumber(item.open),
    high: decodeFiniteNumber(item.high),
    low: decodeFiniteNumber(item.low),
    close: decodeFiniteNumber(item.close),
    volume: decodeNullable(item.volume, decodeFiniteNumber),
    source: decodeString(item.source),
    adjustment: decodeLiteral(item.adjustment, ["qfq", "none"]),
  };
}

export function decodeBars(value: unknown): BarDTO[] {
  return decodeArray(value, decodeBar);
}

export function decodeInstrumentRecord(value: unknown): InstrumentRecord {
  const item = decodeRecord(value);
  return {
    id: decodePositiveInteger(item.id),
    active: decodeBoolean(item.active),
    symbol: decodeString(item.symbol),
    name: decodeString(item.name),
    market: decodeLiteral(item.market, [
      "a_share",
      "hk_stock",
      "us_stock",
      "crypto",
    ]),
    exchange: decodeString(item.exchange),
    currency: decodeString(item.currency),
    timezone: decodeString(item.timezone),
    instrument_type: decodeLiteral(item.instrument_type, [
      "stock",
      "index",
      "etf",
      "crypto_spot",
    ]),
    provider_symbol: decodeString(item.provider_symbol),
  };
}

export function decodeInstrumentRecords(value: unknown): InstrumentRecord[] {
  return decodeArray(value, decodeInstrumentRecord);
}
