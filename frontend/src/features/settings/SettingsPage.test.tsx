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

function renderSettings(path = "/settings") {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
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
  it("renders only data-source controls for every market", async () => {
    renderSettings();

    expect(await screen.findByText("A 股")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "数据源配置" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "数据源配置" })).toBeInTheDocument();
    expect(screen.getByText("A 股")).toBeInTheDocument();
    expect(screen.getByText("港股")).toBeInTheDocument();
    expect(screen.getByText("美股")).toBeInTheDocument();
    expect(screen.getByText("加密货币")).toBeInTheDocument();
    expect(screen.getByLabelText("A 股 数据源")).toBeDisabled();
    expect(screen.getByLabelText("A 股 请求超时")).toBeDisabled();
    expect(screen.getByLabelText("加密货币 请求超时")).toBeDisabled();
    expect(screen.getAllByRole("button", { name: /^编辑 / })).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "保存设置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "放弃修改" })).not.toBeInTheDocument();
    expect(screen.queryByText("历史深度（年）")).not.toBeInTheDocument();
    expect(screen.queryByText("最大重试")).not.toBeInTheDocument();
    expect(screen.queryByText("重叠天数")).not.toBeInTheDocument();
    expect(screen.queryByText("并发固定为 1")).not.toBeInTheDocument();
    expect(screen.queryByText("前复权")).not.toBeInTheDocument();
    expect(screen.queryByText("调度时区")).not.toBeInTheDocument();
    expect(screen.queryByText("最大启用指标数")).not.toBeInTheDocument();
  });

  it("also renders the data-source subroute", async () => {
    renderSettings("/settings/data-sources");

    expect(await screen.findByText("A 股")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "数据源配置" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "数据源配置" })).toBeInTheDocument();
  });

  it("does not render market-level spot pair controls", async () => {
    renderSettings();

    expect(await screen.findByLabelText("A 股 数据源")).toBeInTheDocument();
    expect(screen.getByLabelText("加密货币 请求超时")).toBeInTheDocument();
    expect(screen.queryByText(/现货交易对/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("添加交易对")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("加密货币 交易对 1")).not.toBeInTheDocument();
  });

  it("saves each Group independently and preserves other unsaved Group edits", async () => {
    state.settings.tasks["market.sync_crypto_daily"] = {
      enabled: false,
      cron: "0 0 * * *",
      params: {
        spot_pairs: [{ exchange: "binance", symbol: "BTC/USDT" }],
      },
    };
    renderSettings();
    await screen.findByText("美股");
    await userEvent.click(screen.getByRole("button", { name: "编辑 A 股" }));
    const provider = screen.getByLabelText("A 股 数据源");
    await userEvent.click(provider);
    await userEvent.click(await screen.findByTitle("baostock"));
    await userEvent.clear(screen.getByLabelText("A 股 请求超时"));
    await userEvent.type(screen.getByLabelText("A 股 请求超时"), "30");
    await userEvent.click(screen.getByRole("button", { name: "编辑 港股" }));
    await userEvent.clear(screen.getByLabelText("港股 请求超时"));
    await userEvent.type(screen.getByLabelText("港股 请求超时"), "40");
    await userEvent.click(screen.getByRole("button", { name: "保存 A 股" }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    const first = puts()[0].body as {
      expected_revision: number;
      markets: Record<string, { provider: string; request_timeout_seconds: number }>;
      tasks: Settings["tasks"];
    };
    expect(first.expected_revision).toBe(4);
    expect(first.markets.a_share.provider).toBe("baostock");
    expect(first.markets.a_share.request_timeout_seconds).toBe(30);
    expect(first.markets.hk_stock.request_timeout_seconds).toBe(20);
    expect(first.tasks["market.sync_crypto_daily"].params.spot_pairs).toEqual([
      { exchange: "binance", symbol: "BTC/USDT" },
    ]);
    for (const market of Object.values(first.markets)) {
      expect(market).not.toHaveProperty("symbols");
    }
    expect(screen.getByLabelText("港股 请求超时")).toHaveValue("40.0");
    expect(screen.getByLabelText("港股 请求超时")).toBeEnabled();
    expect(screen.getByLabelText("A 股 请求超时")).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "保存 港股" }));
    await waitFor(() => expect(puts()).toHaveLength(2));
    const second = puts()[1].body as {
      expected_revision: number;
      markets: Record<string, { provider: string; request_timeout_seconds: number }>;
    };
    expect(second.expected_revision).toBe(5);
    expect(second.markets.a_share.provider).toBe("baostock");
    expect(second.markets.a_share.request_timeout_seconds).toBe(30);
    expect(second.markets.hk_stock.request_timeout_seconds).toBe(40);
    expect(await screen.findByText("设置已保存并立即生效。")).toBeInTheDocument();
  });

  it("reloads the newest revision on 409 and asks the user to reapply", async () => {
    state.conflictOnce = true;
    renderSettings();
    await screen.findByText("美股");
    await userEvent.click(screen.getByRole("button", { name: "编辑 A 股" }));

    const timeout = screen.getByLabelText("A 股 请求超时");
    await userEvent.clear(timeout);
    await userEvent.type(timeout, "45");
    await userEvent.click(screen.getByRole("button", { name: "保存 A 股" }));

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
    await userEvent.click(screen.getByRole("button", { name: "编辑 A 股" }));
    await userEvent.click(screen.getByRole("button", { name: "保存 A 股" }));

    expect(await screen.findByText(/请求过于频繁/)).toBeInTheDocument();
  });

  it("discards local edits", async () => {
    renderSettings();
    await screen.findByText("美股");
    await userEvent.click(screen.getByRole("button", { name: "编辑 A 股" }));

    const timeout = screen.getByLabelText("A 股 请求超时");
    await userEvent.clear(timeout);
    await userEvent.type(timeout, "45");
    await userEvent.click(screen.getByRole("button", { name: "放弃 A 股" }));

    expect(screen.getByLabelText("A 股 请求超时")).toHaveValue("20.0");
    expect(screen.getByLabelText("A 股 请求超时")).toBeDisabled();
    expect(puts()).toHaveLength(0);
  });
});
