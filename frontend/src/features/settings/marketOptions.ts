import type { MarketSettings } from "../../types/settings";

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

export function marketLabel(market: string): string {
  return MARKET_LABELS[market] ?? market;
}

export function marketEntries(
  settings: Record<string, MarketSettings>,
): Array<[string, MarketSettings]> {
  return Object.entries(settings);
}

export function providerLabel(market: string, provider: string): string {
  return MARKET_PROVIDERS[market]?.includes(provider) === true
    ? provider
    : `${provider}（不在允许列表）`;
}
