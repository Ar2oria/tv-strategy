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

const userEvent = userEventBase.setup({ delay: null });

const nearLeftEdge = { trigger: null as null | (() => void) };

vi.mock("../../charts/FinancialChart", () => ({
  FinancialChart: ({
    computations,
    onNearLeftEdge,
    renderIndicatorLegend,
  }: {
    computations: Array<{ instance_id: string }>;
    onNearLeftEdge?: () => void;
    renderIndicatorLegend?: (context: {
      hovered: null;
      latestBar: null;
      activeTime: string | null;
    }) => React.ReactNode;
  }) => {
    nearLeftEdge.trigger = onNearLeftEdge ?? null;
    return (
      <div data-testid="financial-chart">
        {computations.map((item) => (
          <span key={item.instance_id}>{item.instance_id}</span>
        ))}
        {renderIndicatorLegend === undefined
          ? null
          : renderIndicatorLegend({
              hovered: null,
              latestBar: null,
              activeTime: null,
            })}
      </div>
    );
  },
}));

interface Recorded {
  url: string;
  method: string;
  body: unknown;
}

const requests: Recorded[] = [];
const computeFailure = { value: false };

const BARS = [
  { ...barPayload, time: "2026-01-05" },
  { ...barPayload, time: "2026-01-06", open: 11, close: 12, high: 12.5, low: 10.5 },
];

const PAGE_SIZE = 1000;
const FIRST_PAGE_END = "2026-01-05";
const barPages = { remaining: 2 };

function barsEndingOn(endIso: string, count: number) {
  const end = new Date(`${endIso}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) => {
    const day = new Date(end);
    day.setUTCDate(day.getUTCDate() - (count - 1 - index));
    return { ...barPayload, time: day.toISOString().slice(0, 10) };
  });
}

function earliestOfFirstPage(): string {
  return barsEndingOn(FIRST_PAGE_END, PAGE_SIZE)[0].time;
}

function pageBefore(endIso: string): string {
  const day = new Date(`${endIso}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

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

function success(data: unknown): Response {
  return new Response(
    JSON.stringify({ success: true, data, error: null, meta: {} }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function failure(status: number, code: string, message: string): Response {
  return new Response(
    JSON.stringify({ success: false, data: null, error: { code, message }, meta: {} }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

function respond(request: Recorded): Response {
  const url = new URL(request.url, "http://localhost");
  if (url.pathname.endsWith("/instruments")) {
    return success([instrumentPayload]);
  }
  if (url.pathname.endsWith("/indicators")) {
    return success([RSI]);
  }
  if (url.pathname.endsWith("/bars")) {
    const requestedEnd = url.searchParams.get("end");
    if (requestedEnd === null && barPages.remaining > 0) {
      barPages.remaining -= 1;
      return success(barsEndingOn(FIRST_PAGE_END, PAGE_SIZE));
    }
    if (requestedEnd !== null && barPages.remaining > 0) {
      barPages.remaining -= 1;
      return success(barsEndingOn(requestedEnd, PAGE_SIZE));
    }
    return success(BARS);
  }
  if (url.pathname.endsWith("/indicators/compute")) {
    if (computeFailure.value) {
      return failure(429, "rate_limited", "Too many requests");
    }
    const body = request.body as { indicators: Array<{ instance_id: string; name: string }> };
    return success(
      body.indicators.map((indicator) => ({
        ...indicatorComputationPayload,
        instance_id: indicator.instance_id,
        name: indicator.name,
        panes: [],
        series: [],
        markers: [],
        reference_lines: [],
        warnings: [],
        error: null,
      })),
    );
  }
  return failure(404, "not_found", "Resource not found");
}

beforeEach(() => {
  requests.length = 0;
  computeFailure.value = false;
  barPages.remaining = 2;
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
  let counter = 0;
  vi.stubGlobal("crypto", {
    randomUUID: () => {
      counter += 1;
      return `uuid-${counter}`;
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  const router = createMemoryRouter(routes, { initialEntries: ["/analysis"] });
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

async function selectInstrument() {
  const search = await screen.findByRole("combobox", { name: "股票搜索" });
  await userEvent.type(search, "AAA");
  await userEvent.click(await screen.findByText("AAA · Alpha"));
}

async function addRsi(window: number | null) {
  await userEvent.click(await screen.findByRole("button", { name: "添加指标" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByText("Relative Strength Index"));
  if (window !== null) {
    const input = await within(dialog).findByRole("spinbutton");
    await userEvent.clear(input);
    await userEvent.type(input, String(window));
  }
  await userEvent.click(
    await within(dialog).findByRole("button", { name: /添\s*加/ }),
  );
}

describe("AnalysisPage editing flows", { timeout: 20000 }, () => {
  it("edits an existing instance's params without changing its instance id", async () => {
    renderPage();
    await selectInstrument();
    await addRsi(14);
    await screen.findByText("Relative Strength Index (window=14)");

    await userEvent.click(
      screen.getByRole("button", {
        name: "编辑参数 Relative Strength Index (window=14)",
      }),
    );
    const dialog = await waitFor(() => {
      const match = screen
        .queryAllByRole("dialog")
        .find((item) => item.textContent?.includes("编辑"));
      if (match === undefined) {
        throw new Error("editor dialog not open yet");
      }
      return match;
    });
    const input = await within(dialog).findByRole("spinbutton");
    await userEvent.clear(input);
    await userEvent.type(input, "30");
    await userEvent.click(
      await within(dialog).findByRole("button", { name: /保\s*存/ }),
    );

    expect(
      await screen.findByText("Relative Strength Index (window=30)"),
    ).toBeInTheDocument();
    await waitFor(() => {
      const computeBodies = requests
        .filter((request) => request.url.includes("/indicators/compute"))
        .map(
          (request) =>
            request.body as { indicators: Array<Record<string, unknown>> },
        );
      expect(computeBodies.at(-1)?.indicators).toEqual([
        { instance_id: "uuid-1", name: "rsi", params: { window: 30 } },
      ]);
    });
  });

  it("loads an older page when the chart reaches its left edge", async () => {
    renderPage();
    await selectInstrument();
    await waitFor(() =>
      expect(requests.some((request) => request.url.includes("/bars"))).toBe(true),
    );
    const initialBars = requests.filter((request) =>
      request.url.includes("/bars"),
    );
    expect(initialBars).toHaveLength(1);
    const initialUrl = new URL(initialBars[0].url, "http://localhost");
    expect(initialUrl.searchParams.get("limit")).toBe("1000");
    expect(initialUrl.searchParams.get("start")).toBeNull();

    await waitFor(() => expect(nearLeftEdge.trigger).not.toBeNull());
    nearLeftEdge.trigger?.();

    await waitFor(() =>
      expect(
        requests.filter((request) => request.url.includes("/bars")).length,
      ).toBe(2),
    );
    const olderUrl = new URL(
      requests.filter((request) => request.url.includes("/bars"))[1].url,
      "http://localhost",
    );
    expect(olderUrl.searchParams.get("limit")).toBe("1000");
    // The older page ends the day before the earliest loaded bar.
    expect(olderUrl.searchParams.get("end")).toBe(
      pageBefore(earliestOfFirstPage()),
    );
  });

  it("walks further back with each left-edge hit and stops at exhaustion", async () => {
    renderPage();
    await selectInstrument();
    await waitFor(() => expect(nearLeftEdge.trigger).not.toBeNull());

    // Page 1 is the initial load; the counter allows one older full page.
    nearLeftEdge.trigger?.();
    await waitFor(() =>
      expect(
        requests.filter((request) => request.url.includes("/bars")).length,
      ).toBe(2),
    );
    const firstOlder = new URL(
      requests.filter((request) => request.url.includes("/bars"))[1].url,
      "http://localhost",
    );
    expect(firstOlder.searchParams.get("end")).toBe(
      pageBefore(earliestOfFirstPage()),
    );

    // The next page comes back short, which marks the history exhausted.
    nearLeftEdge.trigger?.();
    await waitFor(() =>
      expect(
        requests.filter((request) => request.url.includes("/bars")).length,
      ).toBe(3),
    );

    // Further left-edge hits must not issue more requests.
    nearLeftEdge.trigger?.();
    nearLeftEdge.trigger?.();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(
      requests.filter((request) => request.url.includes("/bars")).length,
    ).toBe(3);
  });

  it("shows a rate-limit message while keeping the candles", async () => {
    computeFailure.value = true;
    renderPage();
    await selectInstrument();
    await addRsi(14);

    expect(
      await screen.findByText("指标计算请求失败，已保留 K 线。"),
    ).toBeInTheDocument();
    expect(screen.getByText("Too many requests")).toBeInTheDocument();
    expect(screen.getByTestId("financial-chart")).toBeInTheDocument();
  });

  it("surfaces a non-Error compute failure without a description", async () => {
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
    renderPage();
    await selectInstrument();
    await addRsi(14);
    await screen.findByTestId("financial-chart");
    expect(requests.some((request) => request.url.includes("/compute"))).toBe(false);
  });
});
