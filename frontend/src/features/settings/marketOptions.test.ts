import { describe, expect, it } from "vitest";

import type { MarketSettings } from "../../types/settings";
import {
  historyYearsLabel,
  marketLabel,
  providerLabel,
  symbolKind,
  withSignals,
} from "./marketOptions";

const market: MarketSettings = {
  provider: "yfinance",
  history_years: 10,
  symbols: [],
  request_timeout_seconds: 20,
  max_retries: 3,
  concurrency: 1,
  overlap_days: 45,
};

describe("market options", () => {
  it("classifies crypto separately from stock markets", () => {
    expect(symbolKind("crypto")).toBe("crypto");
    expect(symbolKind("a_share")).toBe("stock");
    expect(symbolKind("us_stock")).toBe("stock");
  });

  it("maps known market codes and preserves unknown ones", () => {
    expect(marketLabel("a_share")).toBe("A 股");
    expect(marketLabel("us_stock")).toBe("美股");
    expect(marketLabel("carbon")).toBe("carbon");
  });

  it("flags providers outside the backend allowlist", () => {
    expect(providerLabel("us_stock", "yfinance")).toBe("yfinance");
    expect(providerLabel("us_stock", "akshare")).toContain("不在允许列表");
    expect(providerLabel("unknown", "any")).toContain("不在允许列表");
  });

  it("formats history depth", () => {
    expect(historyYearsLabel(null)).toBe("全部可用历史");
    expect(historyYearsLabel(10)).toBe("10 年");
  });

  it("preserves market object identity ordering", () => {
    const entries = withSignals({ a_share: market, crypto: market });
    expect(entries.map(([name]) => name)).toEqual(["a_share", "crypto"]);
    expect(entries[0][1]).toBe(market);
  });
});
