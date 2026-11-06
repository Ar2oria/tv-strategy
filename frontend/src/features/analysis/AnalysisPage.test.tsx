import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEventBase from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  barPayload,
  indicatorComputationPayload,
  indicatorDescriptorPayload,
  instrumentPayload,
} from "../../test/apiFixtures";
import { routes } from "../../router";

vi.mock("../../charts/FinancialChart", () => ({
  FinancialChart: ({
    bars,
    computations,
    renderIndicatorLegend,
  }: {
    bars: unknown[];
    computations: Array<{ instance_id: string; error: string | null }>;
    renderIndicatorLegend?: (context: {
      hovered: null;
      latestBar: null;
      activeTime: string | null;
    }) => React.ReactNode;
  }) => (
    <div data-testid="financial-chart">
      <span>{bars.length} bars</span>
      {computations.map((item) => (
        <span key={item.instance_id}>
          {item.error === null ? "" : item.error}
        </span>
      ))}
      {renderIndicatorLegend === undefined
        ? null
        : renderIndicatorLegend({
            hovered: null,
            latestBar: null,
            activeTime: null,
          })}
    </div>
  ),
}));

interface Recorded {
  url: string;
  method: string;
  body: unknown;
}

const userEvent = userEventBase.setup({ delay: null });

const requests: Recorded[] = [];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function success(data: unknown): Response {
  return jsonResponse({ success: true, data, error: null, meta: {} });
}

const BARS = [
  { ...barPayload, time: "2026-01-05" },
  { ...barPayload, time: "2026-01-06", open: 11, close: 12, high: 12.5, low: 10.5 },
  { ...barPayload, time: "2026-01-07", open: 12, close: 13, high: 13.5, low: 11.5 },
];

const DONCHIAN = {
  ...indicatorDescriptorPayload,
  name: "donchian",
  display_name: "Donchian Breakout",
  description: "Channel breakout",
  params_schema: {
    type: "object",
    properties: { window: { type: "integer", default: 20, minimum: 1 } },
    required: ["window"],
  },
};

const RSI = {
  ...indicatorDescriptorPayload,
  name: "rsi",
  display_name: "Relative Strength Index",
  params_schema: {
    type: "object",
    properties: { window: { type: "integer", default: 14, minimum: 2 } },
    required: ["window"],
  },
};

const computations = new Map<string, unknown>();

function respond(request: Recorded): Response {
  const url = new URL(request.url, "http://localhost");
  if (url.pathname.endsWith("/instruments")) {
    return success([instrumentPayload]);
  }
  if (url.pathname.endsWith("/universes")) {
    return success(["us_ndx"]);
  }
  if (url.pathname.endsWith("/indicators")) {
    return success([DONCHIAN, RSI]);
  }
  if (url.pathname.endsWith("/bars")) {
    return success(BARS);
  }
  if (url.pathname.endsWith("/indicators/compute")) {
    const body = request.body as {
      indicators: Array<{ instance_id: string; name: string }>;
    };
    const results = body.indicators.map((indicator) => ({
      ...(computations.get(indicator.name) ?? indicatorComputationPayload),
      instance_id: indicator.instance_id,
      name: indicator.name,
    }));
    return success(results);
  }
  return jsonResponse(
    { success: false, data: null, error: { code: "not_found", message: "x" }, meta: {} },
    404,
  );
}

beforeEach(() => {
  requests.length = 0;
  computations.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request: Recorded = {
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
      };
      requests.push(request);
      return respond(request);
    }),
  );
  let uuidCounter = 0;
  vi.stubGlobal("crypto", {
    randomUUID: () => {
      uuidCounter += 1;
      return `uuid-${uuidCounter}`;
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: ["/analysis"] });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

async function selectInstrument() {
  const search = await screen.findByRole("combobox", { name: "股票搜索" });
  await userEvent.type(search, "AAA");
  const option = await screen.findByText("AAA · Alpha");
  await userEvent.click(option);
}

function computeRequests(): Array<{ indicators: Array<Record<string, unknown>> }> {
  return requests
    .filter((request) => request.url.includes("/indicators/compute"))
    .map((request) => request.body as { indicators: Array<Record<string, unknown>> });
}

describe("AnalysisPage", { timeout: 20000 }, () => {
  it("guides the user to run a sync task when the database has no instruments", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/instruments")) {
          return success([]);
        }
        return success([]);
      }),
    );

    renderApp();

    expect(
      await screen.findByText(/尚未同步任何证券数据/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/启用并立即执行证券列表与日线同步任务/),
    ).toBeInTheDocument();
  });

  it("loads bars and descriptors, then renders the empty indicator state", async () => {
    renderApp();

    await selectInstrument();

    await waitFor(() => expect(computeRequests()).toHaveLength(0));
    expect(
      await screen.findByText("尚未添加指标。点击「添加指标」从后端可用指标中选择。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/尚未添加指标/)).toBeInTheDocument();
    expect(
      await screen.findByTestId("financial-chart"),
    ).toBeInTheDocument();
  });

  it("requests the latest 1000 daily bars without a date range", async () => {
    renderApp();
    await selectInstrument();

    await waitFor(() =>
      expect(requests.some((request) => request.url.includes("/bars"))).toBe(true),
    );
    const barsUrl = new URL(
      requests.find((request) => request.url.includes("/bars"))?.url ?? "",
      "http://localhost",
    );
    expect(barsUrl.searchParams.get("timeframe")).toBe("1d");
    expect(barsUrl.searchParams.get("limit")).toBe("1000");
    expect(barsUrl.searchParams.get("start")).toBeNull();
    expect(barsUrl.searchParams.get("end")).toBeNull();
  });

  it("adds a main-signal indicator with a generated instance id", async () => {
    renderApp();
    await selectInstrument();

    await userEvent.click(
      await screen.findByRole("button", { name: "添加指标" }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByText("Donchian Breakout"));
    await userEvent.click(
      await within(dialog).findByRole("button", { name: /添\s*加/ }),
    );

    await waitFor(() => expect(computeRequests()).toHaveLength(1));
    expect(computeRequests()[0].indicators).toEqual([
      { instance_id: "uuid-1", name: "donchian", params: { window: 20 } },
    ]);
    expect(
      await screen.findByText("Donchian Breakout (window=20)"),
    ).toBeInTheDocument();
  });

  it("supports two instances of the same indicator with different params", async () => {
    renderApp();
    await selectInstrument();

    for (const window of [7, 21]) {
      await userEvent.click(
        await screen.findByRole("button", { name: "添加指标" }),
      );
      const dialog = await screen.findByRole("dialog");
      await userEvent.click(
        within(dialog).getByText("Relative Strength Index"),
      );
      const windowInput = await within(dialog).findByLabelText(/window/i);
      await userEvent.clear(windowInput);
      await userEvent.type(windowInput, String(window));
      await userEvent.click(
        await within(dialog).findByRole("button", { name: /添\s*加/ }),
      );
      await screen.findByText(`Relative Strength Index (window=${window})`);
    }

    await waitFor(() => expect(computeRequests()).toHaveLength(2));
    expect(computeRequests()[1].indicators).toEqual([
      { instance_id: "uuid-1", name: "rsi", params: { window: 7 } },
      { instance_id: "uuid-2", name: "rsi", params: { window: 21 } },
    ]);
    expect(
      await screen.findByText("Relative Strength Index (window=7)"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Relative Strength Index (window=21)"),
    ).toBeInTheDocument();
  });

  it("keeps one broken indicator isolated while the other still renders", async () => {
    computations.set("rsi", {
      ...indicatorComputationPayload,
      instance_id: "ignored",
      name: "rsi",
      error: "RSI window needs at least 15 bars",
      panes: [],
      series: [],
      reference_lines: [],
      warnings: [],
    });
    renderApp();
    await selectInstrument();

    for (const label of ["Relative Strength Index", "Donchian Breakout"]) {
      await userEvent.click(
        await screen.findByRole("button", { name: "添加指标" }),
      );
      const dialog = await screen.findByRole("dialog");
      await userEvent.click(within(dialog).getByText(label));
      await userEvent.click(
        await within(dialog).findByRole("button", { name: /添\s*加/ }),
      );
      await waitFor(() =>
        expect(document.querySelectorAll(".ant-modal-wrap")).toHaveLength(1),
      );
    }

    expect(
      (await screen.findAllByText("RSI window needs at least 15 bars")).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText(/Donchian Breakout \(window=20\)/),
    ).toBeInTheDocument();
    expect(await screen.findByTestId("financial-chart")).toBeInTheDocument();
  });

  it("removes an instance and its computation from the request", async () => {
    renderApp();
    await selectInstrument();

    await userEvent.click(
      await screen.findByRole("button", { name: "添加指标" }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByText("Donchian Breakout"));
    await userEvent.click(
      await within(dialog).findByRole("button", { name: /添\s*加/ }),
    );
    await screen.findByText("Donchian Breakout (window=20)");
    await waitFor(() => expect(computeRequests()).toHaveLength(1));

    await userEvent.click(
      await screen.findByRole("button", {
        name: "移除 Donchian Breakout (window=20)",
      }),
    );

    await waitFor(() =>
      expect(screen.queryByText(/Donchian Breakout \(window=20\)/)).toBeNull(),
    );
    // Removal empties the active set, so no further compute can be issued.
    expect(computeRequests()).toHaveLength(1);
    expect(computeRequests()[0].indicators).toHaveLength(1);
  });

  it("refetches bars and computations when the timeframe changes", async () => {
    renderApp();
    await selectInstrument();
    await waitFor(() =>
      expect(requests.some((request) => request.url.includes("/bars"))).toBe(true),
    );

    await userEvent.click(await screen.findByText("周线"));

    await waitFor(() => {
      const barsUrls = requests
        .filter((request) => request.url.includes("/bars"))
        .map((request) => new URL(request.url, "http://localhost"));
      expect(barsUrls.some((url) => url.searchParams.get("timeframe") === "1w")).toBe(
        true,
      );
    });
  });

  it("shows a visible error when bars cannot be loaded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/bars")) {
          return jsonResponse(
            {
              success: false,
              data: null,
              error: { code: "internal_error", message: "An internal error occurred" },
              meta: {},
            },
            500,
          );
        }
        return respond({ url, method: "GET", body: undefined });
      }),
    );

    renderApp();
    await selectInstrument();

    expect(
      await screen.findByText("An internal error occurred"),
    ).toBeInTheDocument();
  });
});
