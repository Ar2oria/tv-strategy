import { describe, expect, it } from "vitest";

import type { MarketSettings } from "../../types/settings";
import {
  marketEntries,
  marketLabel,
  providerLabel,
} from "./marketOptions";

const market: MarketSettings = {
  provider: "yfinance",
  request_timeout_seconds: 20,
  proxy_url: null,
};

describe("market options", () => {

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

  it("preserves market object identity ordering", () => {
    const entries = marketEntries({ a_share: market, crypto: market });
    expect(entries.map(([name]) => name)).toEqual(["a_share", "crypto"]);
    expect(entries[0][1]).toBe(market);
  });
});
