import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BarDTO } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import { FinancialChart } from "./FinancialChart";

type SeriesRecord = {
  kind: string;
  options: Record<string, unknown>;
  setData: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  createPriceLine: ReturnType<typeof vi.fn>;
  removePriceLine: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
};

const state = {
  chartOptions: [] as unknown[],
  seriesPriceScaleOptions: [] as Array<{ kind: string; options: unknown }>,
  priceScaleOptions: [] as Array<{ id: string; options: unknown }>,
  visibleRangeHandlers: [] as Array<(
    range: { from: number; to: number } | null,
  ) => void>,
  visibleRange: null as { from: unknown; to: unknown } | null,
  setVisibleRange: vi.fn(),
  series: [] as SeriesRecord[],
  markerPlugins: [] as Array<{
    setMarkers: ReturnType<typeof vi.fn>;
    detach: ReturnType<typeof vi.fn>;
  }>,
  applyOptions: vi.fn(),
  removedPriceLines: [] as unknown[],
  resizeCallbacks: [] as ResizeObserverCallback[],
  observed: 0,
  disconnected: 0,
};

vi.mock("lightweight-charts", () => {
  class CandlestickSeries {}
  class LineSeries {}
  class AreaSeries {}
  class HistogramSeries {}
  const kinds = new Map<unknown, string>([
    [CandlestickSeries, "candlestick"],
    [LineSeries, "line"],
    [AreaSeries, "area"],
    [HistogramSeries, "histogram"],
  ]);
  return {
    CandlestickSeries,
    LineSeries,
    AreaSeries,
    HistogramSeries,
    LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3 },
    createSeriesMarkers: vi.fn(() => {
      const plugin = { setMarkers: vi.fn(), detach: vi.fn() };
      state.markerPlugins.push(plugin);
      return plugin;
    }),
    // createChart(container, options): the second argument is the config.
    createChart: vi.fn((_container: unknown, options: unknown) => {
      state.chartOptions.push(options);
      return {
      addSeries: vi.fn(
        (definition: unknown, options: Record<string, unknown>) => {
          const series: SeriesRecord = {
            kind: kinds.get(definition) ?? "line",
            options,
            setData: vi.fn(),
            applyOptions: vi.fn(),
            priceScale: vi.fn(() => ({
              applyOptions: vi.fn((next: unknown) => {
                state.seriesPriceScaleOptions.push({
                  kind: kinds.get(definition) ?? "line",
                  options: next,
                });
              }),
            })),
            createPriceLine: vi.fn((line: Record<string, unknown>) => ({
              line,
            })),
            removePriceLine: vi.fn((line: unknown) => {
              state.removedPriceLines.push(line);
            }),
          };
          state.series.push(series);
          return series;
        },
      ),
      removeSeries: vi.fn(),
      addPane: vi.fn(() => ({ setHeight: vi.fn() })),
      removePane: vi.fn(),
      panes: vi.fn(() => [{}, {}]),
      priceScale: vi.fn((id: string) => ({
        applyOptions: vi.fn((options: unknown) => {
          state.priceScaleOptions.push({ id, options });
        }),
      })),
      applyOptions: state.applyOptions,
      subscribeCrosshairMove: vi.fn(),
      unsubscribeCrosshairMove: vi.fn(),
      timeScale: vi.fn(() => ({
        subscribeVisibleLogicalRangeChange: vi.fn(
          (handler: (range: { from: number; to: number } | null) => void) => {
            state.visibleRangeHandlers.push(handler);
          },
        ),
        unsubscribeVisibleLogicalRangeChange: vi.fn(),
        getVisibleRange: vi.fn(() => state.visibleRange),
        setVisibleRange: state.setVisibleRange,
      })),
      remove: vi.fn(),
      };
    }),
  };
});

const BARS: BarDTO[] = [
  {
    time: "2026-01-05",
    open: 10,
    high: 12,
    low: 9,
    close: 11,
    volume: 100,
    source: "yfinance",
    adjustment: "qfq",
  },
];

function rsi(pointsValue: number | null): IndicatorComputation {
  return {
    instance_id: "r1",
    name: "rsi",
    panes: [{ id: "r1:rsi", title: "RSI", height: 150, price_scale: "right" }],
    series: [
      {
        id: "r1:rsi",
        pane_id: "r1:rsi",
        type: "line",
        title: "RSI (14)",
        points: [{ time: "2026-01-05", value: pointsValue, color: null }],
        color: "#2962ff",
      },
    ],
    markers: [
      {
        time: "2026-01-05",
        position: "inBar",
        shape: "circle",
        color: "#2962ff",
        text: "signal",
        tooltip: null,
        series_id: "r1:rsi",
      },
    ],
    reference_lines: [
      {
        series_id: "r1:rsi",
        value: 70,
        color: "#d1345b",
        title: "Overbought 70",
      },
    ],
    warnings: [],
    error: null,
  };
}

beforeEach(() => {
  state.chartOptions = [];
  state.seriesPriceScaleOptions = [];
  state.priceScaleOptions = [];
  state.visibleRangeHandlers = [];
  state.visibleRange = null;
  state.setVisibleRange = vi.fn();
  state.series = [];
  state.markerPlugins = [];
  state.applyOptions = vi.fn();
  state.removedPriceLines = [];
  state.resizeCallbacks = [];
  state.observed = 0;
  state.disconnected = 0;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
        state.resizeCallbacks.push(callback);
      }
      observe() {
        state.observed += 1;
      }
      unobserve() {}
      disconnect() {
        state.disconnected += 1;
      }
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useFinancialChart updates", () => {
  it("updates series data and marker plugins in place when structure is stable", async () => {
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[rsi(55)]} />,
    );

    const lineSeries = state.series.find((series) => series.kind === "line");
    expect(lineSeries).toBeDefined();
    expect(state.markerPlugins).toHaveLength(1);

    rerender(<FinancialChart bars={BARS} computations={[rsi(62)]} />);

    await waitFor(() =>
      expect(lineSeries?.setData).toHaveBeenLastCalledWith([
        { time: "2026-01-05", value: 62 },
      ]),
    );
    expect(state.markerPlugins[0].setMarkers).toHaveBeenCalledWith([
      {
        time: "2026-01-05",
        position: "inBar",
        shape: "circle",
        color: "#2962ff",
        text: "signal",
      },
    ]);
    expect(state.series.filter((series) => series.kind === "line")).toHaveLength(
      1,
    );
  });

  it("applies a new title and color when only params change", async () => {
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[rsi(55)]} />,
    );
    const lineSeries = state.series.find((series) => series.kind === "line");
    expect(lineSeries?.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({ title: "RSI (14)", color: "#2962ff" }),
    );

    rerender(
      <FinancialChart
        bars={BARS}
        computations={[
          {
            ...rsi(55),
            series: [
              {
                ...rsi(55).series[0],
                title: "RSI (21)",
                color: "#6250d6",
              },
            ],
          },
        ]}
      />,
    );

    await waitFor(() =>
      expect(lineSeries?.applyOptions).toHaveBeenLastCalledWith(
        expect.objectContaining({ title: "RSI (21)", color: "#6250d6" }),
      ),
    );
  });

  it("uses area-specific options instead of an ignored color key", async () => {
    const area: IndicatorComputation = {
      ...rsi(55),
      series: [{ ...rsi(55).series[0], type: "area", color: "#eb6834" }],
    };

    render(<FinancialChart bars={BARS} computations={[area]} />);

    const areaSeries = state.series.find((series) => series.kind === "area");
    expect(areaSeries?.options).toMatchObject({
      lineColor: "#eb6834",
      topColor: "rgba(235, 104, 52, 0.28)",
      bottomColor: "rgba(235, 104, 52, 0.02)",
    });
    expect(areaSeries?.options).not.toHaveProperty("color");
  });

  it("removes a reference line when it disappears", async () => {
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[rsi(55)]} />,
    );
    const lineSeries = state.series.find((series) => series.kind === "line");
    expect(lineSeries?.createPriceLine).toHaveBeenCalledTimes(1);

    rerender(
      <FinancialChart
        bars={BARS}
        computations={[{ ...rsi(55), reference_lines: [] }]}
      />,
    );

    await waitFor(() =>
      expect(state.removedPriceLines).toHaveLength(1),
    );
    expect(lineSeries?.removePriceLine).toHaveBeenCalledTimes(1);
  });

  it("applies positive resize measurements and ignores zero sizes", async () => {
    render(<FinancialChart bars={BARS} computations={[rsi(55)]} />);

    // FinancialChart also mounts a ResizeObserver to measure the card width,
    // so the chart's own observer is the one that receives the chart sizes.
    const observer =
      state.resizeCallbacks[state.resizeCallbacks.length - 1];
    observer(
      [{ contentRect: { width: 0, height: 0 } } as ResizeObserverEntry],
      {} as ResizeObserver,
    );
    expect(state.applyOptions).not.toHaveBeenCalledWith(
      expect.objectContaining({ width: 0 }),
    );

    observer(
      [{ contentRect: { width: 800, height: 400 } } as ResizeObserverEntry],
      {} as ResizeObserver,
    );
    expect(state.applyOptions).toHaveBeenCalledWith({
      width: 800,
      height: 400,
    });

    observer([] as ResizeObserverEntry[], {} as ResizeObserver);
  });

  it("renders whitespace for null indicator values", async () => {
    render(<FinancialChart bars={BARS} computations={[rsi(null)]} />);

    const lineSeries = state.series.find((series) => series.kind === "line");
    expect(lineSeries?.setData).toHaveBeenCalledWith([
      { time: "2026-01-05" },
    ]);
  });
});

describe("useFinancialChart left-edge paging", () => {
  it("reports a near-left-edge when fewer than 200 bars remain ahead", () => {
    const onNearLeftEdge = vi.fn();
    render(
      <FinancialChart
        bars={BARS}
        computations={[]}
        onNearLeftEdge={onNearLeftEdge}
      />,
    );
    expect(state.visibleRangeHandlers).toHaveLength(1);
    const handler = state.visibleRangeHandlers[0];

    // from = 30 means 30 bars sit to the left of the viewport.
    handler({ from: 30, to: 90 });
    expect(onNearLeftEdge).toHaveBeenCalledTimes(1);
  });

  it("stays quiet while plenty of history remains to the left", () => {
    const onNearLeftEdge = vi.fn();
    render(
      <FinancialChart
        bars={BARS}
        computations={[]}
        onNearLeftEdge={onNearLeftEdge}
      />,
    );
    const handler = state.visibleRangeHandlers[0];

    handler({ from: 250, to: 310 });
    expect(onNearLeftEdge).not.toHaveBeenCalled();

    handler(null);
    expect(onNearLeftEdge).not.toHaveBeenCalled();
  });

  it("keeps the visible time range steady when older bars are prepended", () => {
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[]} />,
    );

    const extended: BarDTO[] = [
      { ...BARS[0], time: "2026-01-01" },
      { ...BARS[0], time: "2026-01-02" },
      ...BARS,
    ];
    state.visibleRange = { from: "2026-01-05", to: "2026-01-05" };

    rerender(<FinancialChart bars={extended} computations={[]} />);

    expect(state.setVisibleRange).toHaveBeenCalledWith({
      from: "2026-01-05",
      to: "2026-01-05",
    });
  });

  it("does not restore a range when bars are replaced without prepending", () => {
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[]} />,
    );
    state.visibleRange = { from: "2026-01-05", to: "2026-01-05" };

    rerender(<FinancialChart bars={BARS} computations={[]} />);

    expect(state.setVisibleRange).not.toHaveBeenCalled();
  });
});

describe("useFinancialChart pane layout", () => {
  it("keeps the candle band clear of the volume histogram", () => {
    render(<FinancialChart bars={BARS} computations={[]} />);

    // The candle series' own price scale carries the margins; that is the
    // only entry point the library honours for an auto-scaled axis.
    const candleScale = state.seriesPriceScaleOptions.find(
      (entry) => entry.kind === "candlestick",
    );
    expect(candleScale).toBeDefined();
    const margins = candleScale?.options as {
      scaleMargins?: { top: number; bottom: number };
    };
    // The histogram occupies the bottom 18%; the candle band must stop above
    // it, so the bottom margin has to be at least that tall.
    expect(margins.scaleMargins?.bottom).toBeGreaterThanOrEqual(0.18);
    expect(margins.scaleMargins?.top).toBeGreaterThan(0);

    // The histogram keeps its own reserved band at the pane bottom.
    expect(state.priceScaleOptions).toContainEqual({
      id: "volume",
      options: { scaleMargins: { top: expect.any(Number), bottom: 0 } },
    });
  });
});
