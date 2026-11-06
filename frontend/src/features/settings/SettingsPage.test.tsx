import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEventBase from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { settingsPayload } from "../../test/apiFixtures";
import { routes } from "../../router";
import type { Settings } from "../../types/settings";

const userEvent = userEventBase.setup({ delay: null });

interface Recorded {
  url: string;
  method: string;
  body: unknown;
}

const requests: Recorded[] = [];
const state = {
  settings: structuredClone(settingsPayload) as unknown as Settings,
  conflictOnce: false,
  rateLimited: false,
};

function success(data: unknown): Response {
  return new Response(JSON.stringify({ success: true, data, error: null, meta: {} }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function failure(status: number, code: string, message: string): Response {
  return new Response(
    JSON.stringify({ success: false, data: null, error: { code, message }, meta: {} }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

function respond(recorded: Recorded): Response {
  const url = new URL(recorded.url, "http://localhost");
  if (url.pathname !== "/api/v1/settings") {
    return failure(404, "not_found", "Resource not found");
  }
  if (recorded.method === "GET") {
    return success(state.settings);
  }
  if (state.conflictOnce) {
    state.conflictOnce = false;
    state.settings = { ...state.settings, revision: state.settings.revision + 1 };
    return failure(409, "revision_conflict", "Request conflict");
  }
  if (state.rateLimited) {
    state.rateLimited = false;
    return failure(429, "rate_limited", "Too many requests");
  }
  const body = recorded.body as Record<string, unknown> & {
    expected_revision: number;
  };
  state.settings = {
    ...(body as unknown as Settings),
    revision: body.expected_revision + 1,
  };
  return success(state.settings);
}

beforeEach(() => {
  requests.length = 0;
  state.settings = structuredClone(settingsPayload) as unknown as Settings;
  state.conflictOnce = false;
  state.rateLimited = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const recorded: Recorded = {
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
      };
      requests.push(recorded);
      return respond(recorded);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSettings() {
  const router = createMemoryRouter(routes, { initialEntries: ["/settings"] });
  return render(
    <QueryClientProvider
      client={new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })}
    >
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function puts(): Recorded[] {
  return requests.filter((request) => request.method === "PUT");
}

describe("SettingsPage", { timeout: 20000 }, () => {
  it("renders every market with its provider, fixed concurrency, and history depth", async () => {
    renderSettings();

    expect(await screen.findByText("A 股")).toBeInTheDocument();
    expect(screen.getByText("港股")).toBeInTheDocument();
    expect(screen.getByText("美股")).toBeInTheDocument();
    expect(screen.getByText("加密货币")).toBeInTheDocument();
    expect(screen.getAllByText("并发固定为 1")).toHaveLength(4);
    expect(screen.getAllByText("前复权")).toHaveLength(4);
  });

  it("shows exchange-qualified spot pairs instead of bare symbols", async () => {
    renderSettings();

    const symbol = await screen.findByLabelText("加密货币 交易对 1");
    expect(symbol).toHaveValue("BTC/USDT");
    expect(screen.getByLabelText("加密货币 第 1 个交易对的交易所")).toBeInTheDocument();
  });

  it("saves provider, timeout, timezone, and crypto pairs with the revision", async () => {
    renderSettings();
    await screen.findByText("美股");

    const provider = await screen.findByLabelText("A 股 数据源");
    await userEvent.click(provider);
    await userEvent.click(await screen.findByTitle("baostock"));

    const timezone = screen.getByLabelText("调度时区");
    await userEvent.clear(timezone);
    await userEvent.type(timezone, "Asia/Shanghai");

    const timeout = screen.getByLabelText("A 股 请求超时");
    await userEvent.clear(timeout);
    await userEvent.type(timeout, "30");

    const symbol = screen.getByLabelText("加密货币 交易对 1");
    await userEvent.clear(symbol);
    await userEvent.type(symbol, "ETH/USDT");

    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    const body = puts()[0].body as {
      expected_revision: number;
      timezone: string;
      markets: Record<string, { provider: string; request_timeout_seconds: number; symbols: unknown[] }>;
    };
    expect(body.expected_revision).toBe(4);
    expect(body.timezone).toBe("Asia/Shanghai");
    expect(body.markets.a_share.provider).toBe("baostock");
    expect(body.markets.a_share.request_timeout_seconds).toBe(30);
    expect(body.markets.crypto.symbols).toEqual([
      { exchange: "binance", symbol: "ETH/USDT" },
    ]);
    expect(await screen.findByText("设置已保存并立即生效。")).toBeInTheDocument();
  });

  it("adds and removes crypto spot pairs", async () => {
    renderSettings();
    await screen.findByText("加密货币");

    await userEvent.click(screen.getByLabelText("添加交易对"));
    const second = await screen.findByLabelText("加密货币 交易对 2");
    await userEvent.type(second, "SOL/USDT");
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    const body = puts()[0].body as {
      markets: { crypto: { symbols: Array<{ exchange: string; symbol: string }> } };
    };
    expect(body.markets.crypto.symbols).toEqual([
      { exchange: "binance", symbol: "BTC/USDT" },
      { exchange: "binance", symbol: "SOL/USDT" },
    ]);
  });

  it("reloads the newest revision on 409 and asks the user to reapply", async () => {
    state.conflictOnce = true;
    renderSettings();
    await screen.findByText("美股");

    const timezone = screen.getByLabelText("调度时区");
    await userEvent.clear(timezone);
    await userEvent.type(timezone, "Europe/London");
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    expect(
      await screen.findByText(/配置已被其他页面修改/),
    ).toBeInTheDocument();
    expect(await screen.findByText(/当前修订号：5/)).toBeInTheDocument();
    expect(puts()).toHaveLength(1);
  });

  it("shows a retry hint on 429", async () => {
    state.rateLimited = true;
    renderSettings();
    await screen.findByText("美股");

    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText(/请求过于频繁/)).toBeInTheDocument();
  });

  it("discards local edits", async () => {
    renderSettings();
    await screen.findByText("美股");

    const timezone = screen.getByLabelText("调度时区");
    await userEvent.clear(timezone);
    await userEvent.type(timezone, "Europe/Paris");
    await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));

    expect(screen.getByLabelText("调度时区")).toHaveValue("UTC");
    expect(puts()).toHaveLength(0);
  });
});
