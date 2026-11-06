import type { CryptoSymbol, MarketSettings } from "../../types/settings";

/** Mirrors backend ALLOWED_MARKET_PROVIDERS; the server still re-validates. */
export const MARKET_PROVIDERS: Readonly<Record<string, readonly string[]>> = {
  a_share: ["akshare", "baostock"],
  hk_stock: ["akshare", "yfinance"],
  us_stock: ["yfinance"],
  crypto: ["binance", "okx"],
};

export const MARKET_LABELS: Readonly<Record<string, string>> = {
  a_share: "A 股",
  hk_stock: "港股",
  us_stock: "美股",
  crypto: "加密货币",
};

export const EXCHANGE_LABELS: Readonly<Record<CryptoSymbol["exchange"], string>> = {
  binance: "Binance",
  okx: "OKX",
};

export type SymbolKind = "stock" | "crypto";

export function symbolKind(market: string): SymbolKind {
  return market === "crypto" ? "crypto" : "stock";
}

export function marketLabel(market: string): string {
  return MARKET_LABELS[market] ?? market;
}

/** Only crypto markets carry exchange-qualified spot pairs. */
export function editableSymbols(market: string): CryptoSymbol[] {
  return symbolKind(market) === "crypto" ? [] : [];
}

export function withSignals(
  settings: Record<string, MarketSettings>,
): Array<[string, MarketSettings]> {
  return Object.entries(settings);
}

export function providerLabel(market: string, provider: string): string {
  return MARKET_PROVIDERS[market]?.includes(provider) === true
    ? provider
    : `${provider}（不在允许列表）`;
}

export function historyYearsLabel(value: number | null): string {
  return value === null ? "全部可用历史" : `${value} 年`;
}
