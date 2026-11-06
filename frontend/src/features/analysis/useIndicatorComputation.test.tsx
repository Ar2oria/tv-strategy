import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { indicatorComputationPayload } from "../../test/apiFixtures";
import type { ActiveIndicatorInstance } from "./indicatorInstances";
import { useIndicatorComputation } from "./useIndicatorComputation";

const requests: unknown[] = [];

beforeEach(() => {
  requests.length = 0;
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      requests.push(JSON.parse(String(init?.body ?? "{}")));
      return new Response(
        JSON.stringify({
          success: true,
          data: JSON.parse(String(init?.body ?? "{}")).indicators.map(
            (indicator: { instance_id: string; name: string }) => ({
              ...indicatorComputationPayload,
              instance_id: indicator.instance_id,
              name: indicator.name,
            }),
          ),
          error: null,
          meta: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const BASE = { instrumentId: 1, timeframe: "1d" as const, start: "2024-01-01", end: "2026-01-01" };

function instance(window: number, instanceId = "a"): ActiveIndicatorInstance {
  return {
    instanceId,
    name: "rsi",
    displayName: "RSI",
    params: { window },
  };
}

describe("useIndicatorComputation", () => {
  it("does nothing without an instrument", async () => {
    renderHook(
      () =>
        useIndicatorComputation({
          ...BASE,
          instrumentId: null,
          instances: [instance(14)],
        }),
      { wrapper },
    );

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(requests).toHaveLength(0);
  });

  it("debounces rapid parameter edits into a single request", async () => {
    const { rerender } = renderHook(
      (props: { instances: ActiveIndicatorInstance[] }) =>
        useIndicatorComputation({ ...BASE, ...props }),
      { wrapper, initialProps: { instances: [instance(7)] } },
    );

    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    rerender({ instances: [instance(8)] });
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    rerender({ instances: [instance(9)] });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    // One immediate request for the first render, then exactly one for the
    // settled edit — the intermediate window=8 value never leaves the client.
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1]).toMatchObject({
      indicators: [{ instance_id: "a", name: "rsi", params: { window: 9 } }],
    });
  });

  it("keeps the previous results visible while a new batch is in flight", async () => {
    const { result, rerender } = renderHook(
      (props: { instances: ActiveIndicatorInstance[] }) =>
        useIndicatorComputation({ ...BASE, ...props }),
      { wrapper, initialProps: { instances: [instance(7)] } },
    );

    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    await waitFor(() => expect(result.current.computations).toHaveLength(1));
    const first = result.current.computations[0];

    rerender({ instances: [instance(9)] });
    await act(async () => {
      vi.advanceTimersByTime(10);
    });

    // Pending debounce, but the panes must not blank out.
    expect(result.current.computations).toHaveLength(1);
    expect(result.current.computations[0].instance_id).toBe(first.instance_id);
  });

  it("drops results for an instance that no longer exists", async () => {
    const { result, rerender } = renderHook(
      (props: { instances: ActiveIndicatorInstance[] }) =>
        useIndicatorComputation({ ...BASE, ...props }),
      {
        wrapper,
        initialProps: { instances: [instance(7, "a"), instance(7, "b")] },
      },
    );

    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    await waitFor(() => expect(result.current.computations).toHaveLength(2));

    rerender({ instances: [instance(7, "a")] });
    await act(async () => {
      vi.advanceTimersByTime(10);
    });

    expect(result.current.computations.map((item) => item.instance_id)).toEqual([
      "a",
    ]);
  });

  it("keeps empty instance lists from firing a request", async () => {
    renderHook(() => useIndicatorComputation({ ...BASE, instances: [] }), {
      wrapper,
    });

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(requests).toHaveLength(0);
  });
});
