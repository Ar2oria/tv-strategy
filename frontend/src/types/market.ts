export type Market = "a_share" | "hk_stock" | "us_stock" | "crypto";
export type InstrumentType = "stock" | "index" | "etf" | "crypto_spot";
export type Adjustment = "qfq" | "none";
export type Timeframe = "1d" | "1w" | "1M";

export interface InstrumentDTO {
  symbol: string;
  name: string;
  market: Market;
  exchange: string;
  currency: string;
  timezone: string;
  instrument_type: InstrumentType;
  provider_symbol: string;
}

export interface InstrumentRecord extends InstrumentDTO {
  id: number;
  active: boolean;
}

export interface BarDTO {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  source: string;
  adjustment: Adjustment;
}

export interface InstrumentQuery {
  query?: string;
  market?: Market;
  universe_code?: string;
  limit?: number;
  offset?: number;
}

export interface BarsQuery {
  instrument_id: number;
  timeframe?: Timeframe;
  start?: string;
  end?: string;
  limit?: number;
}
