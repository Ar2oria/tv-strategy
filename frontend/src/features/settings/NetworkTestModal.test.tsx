import { render, screen, waitFor } from "@testing-library/react";
import userEventBase from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NetworkTestModal } from "./NetworkTestModal";

const userEvent = userEventBase.setup({ delay: null });

interface Recorded {
  url: string;
  method: string;
  body: unknown;
}

const requests: Recorded[] = [];
const fetchMock = vi.fn<typeof fetch>();

function success(data: unknown): Response {
  return new Response(
    JSON.stringify({ success: true, data, error: null, meta: {} }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function result(overrides: Record<string, unknown> = {}) {
  return {
    market: "a_share",
    provider: "akshare",
    symbol: "600519.SH",
    connected: true,
    latency_ms: 12.3,
    price: 101.5,
    price_date: "2026-11-11",
    currency: "CNY",
    error_type: null,
    detail: null,
    ...overrides,
  };
}

function renderModal(market = "a_share", open = true) {
  return render(
    <NetworkTestModal
      market={market}
      provider={market === "crypto" ? "binance" : "akshare"}
      open={open}
      onClose={vi.fn()}
    />,
  );
}

beforeEach(() => {
  requests.length = 0;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    requests.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    return success(result());
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NetworkTestModal", () => {
  it.each([
    ["a_share", "600519.SH"],
    ["hk_stock", "0700.HK"],
    ["us_stock", "AAPL"],
    ["crypto", "BTC/USDT"],
  ])("uses the default symbol for %s", (market, symbol) => {
    renderModal(market);

    expect(screen.getByLabelText("测试 Symbol 或交易对")).toHaveValue(symbol);
  });

  it("rejects a blank symbol without making a request", async () => {
    renderModal();
    await userEvent.clear(screen.getByLabelText("测试 Symbol 或交易对"));
    await userEvent.click(screen.getByRole("button", { name: "开始测试" }));

    expect(screen.getByText("请输入 Symbol 或交易对")).toBeInTheDocument();
    expect(requests).toHaveLength(0);
  });

  it("shows connectivity, latency, latest close, and date after success", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      requests.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: JSON.parse(String(init?.body)),
      });
      return success(result({ symbol: "000001.SZ" }));
    });
    renderModal();
    await userEvent.clear(screen.getByLabelText("测试 Symbol 或交易对"));
    await userEvent.type(screen.getByLabelText("测试 Symbol 或交易对"), "000001.SZ");
    await userEvent.click(screen.getByRole("button", { name: "开始测试" }));

    expect(await screen.findByText("数据源可用")).toBeInTheDocument();
    expect(screen.getByText("耗时: 12.3 ms")).toBeInTheDocument();
    expect(screen.getByText("最新价格（日线收盘）: 101.5 CNY")).toBeInTheDocument();
    expect(screen.getByText("价格日期: 2026-11-11")).toBeInTheDocument();
    expect(requests).toEqual([
      {
        url: "/api/v1/settings/markets/a_share/network-test",
        method: "POST",
        body: { symbol: "000001.SZ" },
      },
    ]);
    expect(requests.every((request) => request.method === "POST")).toBe(true);
  });

  it("shows provider failure details and elapsed time", async () => {
    fetchMock.mockResolvedValueOnce(
      success(
        result({
          connected: false,
          latency_ms: 9.1,
          price: null,
          price_date: null,
          currency: null,
          error_type: "ProviderUnavailable",
          detail: "AKShare daily request failed (RuntimeError)",
        }),
      ),
    );
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: "开始测试" }));

    expect(await screen.findByText("数据源不可用")).toBeInTheDocument();
    expect(screen.getByText("错误类型: ProviderUnavailable")).toBeInTheDocument();
    expect(screen.getByText("AKShare daily request failed (RuntimeError)")).toBeInTheDocument();
    expect(screen.getByText("耗时: 9.1 ms")).toBeInTheDocument();
  });

  it("shows the dedicated nonblocking ProviderBusy warning", async () => {
    fetchMock.mockResolvedValueOnce(
      success(
        result({
          connected: false,
          latency_ms: 2,
          price: null,
          price_date: null,
          currency: null,
          error_type: "ProviderBusy",
          detail: "Data source is currently in use, retry later",
        }),
      ),
    );
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: "开始测试" }));

    const warning = await screen.findByText("数据源正在使用中，请稍后重试");
    expect(warning.closest(".ant-alert")).toHaveClass("ant-alert-warning");
    expect(screen.queryByText("数据源不可用")).not.toBeInTheDocument();
    expect(screen.getByText("耗时: 2 ms")).toBeInTheDocument();
  });

  it("shows a safe transport error", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          success: false,
          data: null,
          error: { code: "internal_error", message: "An internal error occurred" },
          meta: {},
        }),
        { status: 500, headers: { "Content-Type": "application/json" } },
      ),
    );
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: "开始测试" }));

    expect(await screen.findByText("网络测试失败，请稍后重试。")).toBeInTheDocument();
  });

  it("prevents duplicate starts while a request is pending", async () => {
    let resolveRequest: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveRequest = resolve;
        }),
    );
    renderModal();
    const start = screen.getByRole("button", { name: "开始测试" });
    await userEvent.click(start);
    await waitFor(() => expect(start).toBeDisabled());
    await userEvent.click(start);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveRequest?.(success(result()));
    expect(await screen.findByText("数据源可用")).toBeInTheDocument();
  });

  it("resets input and results when reopened", async () => {
    const { rerender } = render(
      <NetworkTestModal market="a_share" provider="akshare" open onClose={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "开始测试" }));
    expect(await screen.findByText("数据源可用")).toBeInTheDocument();

    rerender(
      <NetworkTestModal market="a_share" provider="akshare" open={false} onClose={vi.fn()} />,
    );
    rerender(
      <NetworkTestModal market="a_share" provider="akshare" open onClose={vi.fn()} />,
    );

    expect(screen.getByLabelText("测试 Symbol 或交易对")).toHaveValue("600519.SH");
    expect(screen.queryByText("数据源可用")).not.toBeInTheDocument();
  });
});
