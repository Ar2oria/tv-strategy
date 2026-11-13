import { describe, expect, it } from "vitest";

import { composeProxyUrl, parseProxyUrl } from "./proxySettings";

describe("proxy settings parts", () => {
  it("returns empty defaults when no proxy is configured", () => {
    expect(parseProxyUrl(null)).toEqual({ protocol: "http", host: "", port: null });
    expect(composeProxyUrl({ protocol: "http", host: "", port: null })).toBeNull();
  });

  it.each([
    ["http", "http://127.0.0.1:8080"],
    ["https", "https://proxy.example:8443"],
    ["socks5", "socks5://127.0.0.1:1080"],
    ["socks5h", "socks5h://127.0.0.1:1080"],
  ])("round-trips %s without losing protocol, host, or port", (protocol, value) => {
    const parts = parseProxyUrl(value);

    expect(parts).toEqual({
      protocol,
      host: value.includes("proxy.example") ? "proxy.example" : "127.0.0.1",
      port: Number(value.split(":").at(-1)),
    });
    expect(composeProxyUrl(parts)).toBe(value);
  });

  it("preserves IPv6 brackets", () => {
    const parts = parseProxyUrl("socks5://[::1]:1080");

    expect(parts).toEqual({ protocol: "socks5", host: "[::1]", port: 1080 });
    expect(composeProxyUrl(parts)).toBe("socks5://[::1]:1080");
  });

  it("keeps partial values visible for backend validation instead of dropping them", () => {
    expect(
      composeProxyUrl({ protocol: "socks5", host: " 127.0.0.1 ", port: null }),
    ).toBe("socks5://127.0.0.1");
    expect(composeProxyUrl({ protocol: "socks5", host: "", port: 1080 })).toBe(
      "socks5://:1080",
    );
  });

  it.each([
    ["http://proxy.example:80", 80],
    ["https://proxy.example:443", 443],
  ])("preserves an explicitly configured default port for %s", (value, port) => {
    const parts = parseProxyUrl(value);

    expect(parts.port).toBe(port);
    expect(composeProxyUrl(parts)).toBe(value);
  });

  it("retains an invalid existing value so the user can correct it", () => {
    expect(parseProxyUrl("not-a-url")).toEqual({
      protocol: "http",
      host: "not-a-url",
      port: null,
    });
  });
});
