import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BarDTO } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import { FinancialChart } from "./FinancialChart";
import { getChartTheme } from "./theme";

type MockSeries = {
  kind: "candlestick" | "line" | "area" | "histogram";
  options: Record<string, unknown>;
  paneIndex: number;
  setData: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
  createPriceLine: ReturnType<typeof vi.fn>;
  removePriceLine: ReturnType<typeof vi.fn>;
  priceLines: Array<Record<string, unknown>>;
};

type MockPane = {
  setHeight: ReturnType<typeof vi.fn>;
  paneIndex: ReturnType<typeof vi.fn>;
  getSeries: ReturnType<typeof vi.fn>;
  series: MockSeries[];
};

type CrosshairHandler = (param: {
  time?: string;
  point?: { x: number; y: number };
  paneIndex?: number;
}) => void;

const chartCalls = {
  created: 0,
  addSeries: [] as Array<{ kind: string; paneIndex: number }>,
  addPane: 0,
  removePane: [] as number[],
  removedSeries: [] as MockSeries[],
  removeSeriesOrder: [] as number[],
  detachedMarkers: 0,
  markerCalls: [] as Array<{ series: MockSeries; markers: unknown[] }>,
  markerUpdates: [] as unknown[][],
  appliedOptions: [] as Array<Record<string, unknown>>,
  priceScaleOptions: [] as unknown[],
  removed: 0,
  appliedPriceLines: [] as Array<Record<string, unknown>>,
};

let crosshairHandler: CrosshairHandler | null = null;
let seriesRecords: MockSeries[] = [];
let paneRecords: MockPane[] = [];
let disconnected = 0;
let observed = 0;

vi.mock("lightweight-charts", () => {
  class CandlestickSeriesDefinition {
    readonly kind = "candlestick";
  }
  class LineSeriesDefinition {
    readonly kind = "line";
  }
  class AreaSeriesDefinition {
    readonly kind = "area";
  }
  class HistogramSeriesDefinition {
    readonly kind = "histogram";
  }

  const kinds = new Map<unknown, MockSeries["kind"]>([
    [CandlestickSeriesDefinition, "candlestick"],
    [LineSeriesDefinition, "line"],
    [AreaSeriesDefinition, "area"],
    [HistogramSeriesDefinition, "histogram"],
  ]);

  function makeSeries(
    definition: unknown,
    options: Record<string, unknown>,
    paneIndex: number,
  ): MockSeries {
    const series: MockSeries = {
      kind: kinds.get(definition) ?? "line",
      options,
      paneIndex,
      setData: vi.fn(),
      applyOptions: vi.fn(),
      priceScale: vi.fn(() => ({
        applyOptions: vi.fn((next: unknown) => {
          chartCalls.priceScaleOptions.push(next);
        }),
      })),
      createPriceLine: vi.fn((line: Record<string, unknown>) => {
        series.priceLines.push(line);
        chartCalls.appliedPriceLines.push(line);
        return { line };
      }),
      removePriceLine: vi.fn(),
      priceLines: [],
    };
    seriesRecords.push(series);
    const pane = paneRecords[paneIndex];
    if (pane !== undefined) {
      pane.series.push(series);
    }
    chartCalls.addSeries.push({ kind: series.kind, paneIndex });
    return series;
  }

  return {
    CandlestickSeries: CandlestickSeriesDefinition,
    LineSeries: LineSeriesDefinition,
    AreaSeries: AreaSeriesDefinition,
    HistogramSeries: HistogramSeriesDefinition,
    LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3 },
    createSeriesMarkers: vi.fn((series: MockSeries, markers: unknown[]) => {
      chartCalls.markerCalls.push({ series, markers });
      return {
        setMarkers: vi.fn((next: unknown[]) => {
          chartCalls.markerUpdates.push(next);
        }),
        markers: () => [],
        detach: vi.fn(() => {
          chartCalls.detachedMarkers += 1;
        }),
      };
    }),
    createChart: vi.fn(() => {
      chartCalls.created += 1;
      paneRecords = [
        {
          setHeight: vi.fn(),
          paneIndex: vi.fn(() => 0),
          getSeries: vi.fn(() => paneRecords[0]?.series ?? []),
          series: [],
        },
      ];
      return {
        addSeries: vi.fn(
          (definition: unknown, options: Record<string, unknown>, index = 0) =>
            makeSeries(definition, options, index),
        ),
        // Mirrors lightweight-charts 5.2.1: removing a series also drops its
        // pane once it is empty and more than one pane remains.
        removeSeries: vi.fn((series: MockSeries) => {
          chartCalls.removedSeries.push(series);
          chartCalls.removeSeriesOrder.push(series.paneIndex);
          seriesRecords = seriesRecords.filter((item) => item !== series);
          for (const pane of paneRecords) {
            pane.series = pane.series.filter((item) => item !== series);
          }
          const emptyIndex = paneRecords.findIndex(
            (pane) => pane.series.length === 0,
          );
          if (emptyIndex > 0 && paneRecords.length > 1) {
            paneRecords.splice(emptyIndex, 1);
            paneRecords.forEach((pane, index) => {
              pane.series.forEach((item) => {
                item.paneIndex = index;
              });
            });
          }
        }),
        addPane: vi.fn(() => {
          chartCalls.addPane += 1;
          const pane: MockPane = {
            setHeight: vi.fn(),
            paneIndex: vi.fn(() => paneRecords.indexOf(pane)),
            getSeries: vi.fn(() => pane.series),
            series: [],
          };
          paneRecords.push(pane);
          return pane;
        }),
        removePane: vi.fn((index: number) => {
          chartCalls.removePane.push(index);
          paneRecords.splice(index, 1);
        }),
        panes: vi.fn(() => paneRecords),
        priceScale: vi.fn(() => ({
          applyOptions: vi.fn(),
          width: vi.fn(() => 0),
        })),
        paneSize: vi.fn(() => ({ width: 800, height: 400 })),
        applyOptions: vi.fn((options: Record<string, unknown>) => {
          chartCalls.appliedOptions.push(options);
        }),
        subscribeCrosshairMove: vi.fn((handler: CrosshairHandler) => {
          crosshairHandler = handler;
        }),
        unsubscribeCrosshairMove: vi.fn(),
        timeScale: vi.fn(() => ({
          subscribeVisibleLogicalRangeChange: vi.fn(),
          unsubscribeVisibleLogicalRangeChange: vi.fn(),
          getVisibleRange: vi.fn(() => null),
          setVisibleRange: vi.fn(),
        })),
        remove: vi.fn(() => {
          chartCalls.removed += 1;
        }),
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
  {
    time: "2026-01-06",
    open: 11,
    high: 13,
    low: 10,
    close: 10,
    volume: 120,
    source: "yfinance",
    adjustment: "qfq",
  },
];

const DONCHIAN: IndicatorComputation = {
  instance_id: "d1",
  name: "donchian",
  panes: [{ id: "main", title: "Price", height: 400, price_scale: "right" }],
  series: [
    {
      id: "d1:upper",
      pane_id: "main",
      type: "line",
      title: "Previous high",
      points: [{ time: "2026-01-05", value: 12.4, color: null }],
      color: "#168b5b",
    },
  ],
  markers: [
    {
      time: "2026-01-06",
      position: "belowBar",
      shape: "arrowUp",
      color: "#168b5b",
      text: "Up breakout",
      tooltip: "Close 13 above 12.4",
      series_id: null,
    },
  ],
  reference_lines: [],
  warnings: [],
  error: null,
};

const RSI: IndicatorComputation = {
  instance_id: "r1",
  name: "rsi",
  panes: [{ id: "r1:rsi", title: "RSI", height: 150, price_scale: "right" }],
  series: [
    {
      id: "r1:rsi",
      pane_id: "r1:rsi",
      type: "line",
      title: "RSI (14)",
      points: [
        { time: "2026-01-05", value: 45.5, color: null },
        { time: "2026-01-06", value: 52.5, color: "#d1345b" },
      ],
      color: "#2962ff",
    },
  ],
  markers: [
    {
      time: "2026-01-05",
      position: "inBar",
      shape: "circle",
      color: "#2962ff",
      text: null,
      tooltip: null,
      series_id: "r1:rsi",
    },
  ],
  reference_lines: [
    { series_id: "r1:rsi", value: 70, color: "#d1345b", title: "Overbought 70" },
  ],
  warnings: ["warmup"],
  error: null,
};

beforeEach(() => {
  chartCalls.created = 0;
  chartCalls.addSeries = [];
  chartCalls.addPane = 0;
  chartCalls.removePane = [];
  chartCalls.removedSeries = [];
  chartCalls.removeSeriesOrder = [];
  chartCalls.detachedMarkers = 0;
  chartCalls.markerCalls = [];
  chartCalls.markerUpdates = [];
  chartCalls.appliedOptions = [];
  chartCalls.removed = 0;
  chartCalls.appliedPriceLines = [];
  crosshairHandler = null;
  seriesRecords = [];
  paneRecords = [];
  disconnected = 0;
  observed = 0;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(_callback: ResizeObserverCallback) {}
      observe() {
        observed += 1;
      }
      unobserve() {}
      disconnect() {
        disconnected += 1;
      }
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FinancialChart", () => {
  it("creates one candle series in pane 0 and custom panes in request order", async () => {
    render(<FinancialChart bars={BARS} computations={[RSI]} />);

    await waitFor(() => expect(chartCalls.created).toBe(1));
    expect(chartCalls.addSeries[0]).toEqual({
      kind: "candlestick",
      paneIndex: 0,
    });
    expect(chartCalls.addSeries[1]).toEqual({
      kind: "histogram",
      paneIndex: 0,
    });
    expect(chartCalls.addPane).toBe(1);
    expect(chartCalls.addSeries[2]).toEqual({ kind: "line", paneIndex: 1 });
    expect(paneRecords[1].setHeight).toHaveBeenCalledWith(150);
    expect(observed).toBeGreaterThan(0);
  });

  it("attaches markers to the candle series and to named series", async () => {
    render(<FinancialChart bars={BARS} computations={[DONCHIAN, RSI]} />);

    await waitFor(() => expect(chartCalls.markerCalls).toHaveLength(2));
    const candleSeries = seriesRecords.find(
      (series) => series.kind === "candlestick",
    );
    const rsiSeries = seriesRecords.find(
      (series) => series.options.title === "RSI (14)",
    );
    const targets = chartCalls.markerCalls.map((call) => call.series);
    expect(targets).toContain(candleSeries);
    expect(targets).toContain(rsiSeries);
    const candleMarkers = chartCalls.markerCalls.find(
      (call) => call.series === candleSeries,
    )?.markers;
    expect(candleMarkers).toEqual([
      {
        time: "2026-01-06",
        position: "belowBar",
        shape: "arrowUp",
        color: "#168b5b",
        text: "Up breakout",
      },
    ]);
  });

  it("applies reference lines to the owning series, not the candles", async () => {
    render(<FinancialChart bars={BARS} computations={[RSI]} />);

    await waitFor(() => expect(chartCalls.appliedPriceLines).toHaveLength(1));
    expect(chartCalls.appliedPriceLines[0]).toMatchObject({
      price: 70,
      color: "#d1345b",
      title: "Overbought 70",
    });
    const owner = seriesRecords.find(
      (series) => series.options.title === "RSI (14)",
    );
    const candles = seriesRecords.find(
      (series) => series.kind === "candlestick",
    );
    expect(owner?.priceLines).toHaveLength(1);
    expect(candles?.createPriceLine).not.toHaveBeenCalled();
  });

  it("removes multi-pane indicator series from the highest pane down", async () => {
    const twoPanes: IndicatorComputation = {
      ...RSI,
      instance_id: "multi",
      panes: [
        { id: "multi:a", title: "A", height: 120, price_scale: "right" },
        { id: "multi:b", title: "B", height: 140, price_scale: "right" },
      ],
      series: [
        {
          id: "multi:a",
          pane_id: "multi:a",
          type: "line",
          title: "A",
          points: [{ time: "2026-01-05", value: 1, color: null }],
          color: "#2a78d6",
        },
        {
          id: "multi:b",
          pane_id: "multi:b",
          type: "line",
          title: "B",
          points: [{ time: "2026-01-05", value: 2, color: null }],
          color: "#eb6834",
        },
      ],
      markers: [],
      reference_lines: [],
    };
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[twoPanes]} />,
    );

    await waitFor(() => expect(chartCalls.addPane).toBe(2));
    expect(chartCalls.addSeries.map((item) => item.paneIndex)).toEqual([
      0, 0, 1, 2,
    ]);

    rerender(<FinancialChart bars={BARS} computations={[]} />);

    // Highest pane first, so the lower pane index stays valid while removing.
    expect(chartCalls.removeSeriesOrder).toEqual([2, 1]);
    expect(paneRecords).toHaveLength(1);
  });

  it("cleans up indicator layers and stale panes while keeping candles", async () => {
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[DONCHIAN, RSI]} />,
    );

    await waitFor(() => expect(chartCalls.markerCalls).toHaveLength(2));
    const candleSeries = seriesRecords.find(
      (series) => series.kind === "candlestick",
    );
    const volumeSeries = seriesRecords.find(
      (series) => series.options.priceScaleId === "volume",
    );

    rerender(<FinancialChart bars={BARS} computations={[DONCHIAN]} />);

    await waitFor(() => expect(chartCalls.detachedMarkers).toBeGreaterThan(0));
    // Donchian's overlay series live on pane 0, so only RSI's pane is dropped.
    // lightweight-charts removes that pane itself once its last series goes
    // (asserted through the surviving pane count, not the call mechanism).
    expect(chartCalls.removeSeriesOrder).toEqual([1, 0]);
    expect(chartCalls.removedSeries).not.toContain(candleSeries);
    expect(chartCalls.removedSeries).not.toContain(volumeSeries);
    expect(paneRecords).toHaveLength(1);
  });

  it("keeps candles and healthy panes while an indicator reports an issue", async () => {
    const broken: IndicatorComputation = {
      ...RSI,
      instance_id: "broken",
      error: "Indicator output failed validation",
      panes: [],
      series: [],
      reference_lines: [],
    };

    render(<FinancialChart bars={BARS} computations={[broken, DONCHIAN]} />);

    await waitFor(() =>
      expect(
        screen.getByText("Indicator output failed validation"),
      ).toBeInTheDocument(),
    );
    expect(chartCalls.addSeries.filter((item) => item.kind === "candlestick"))
      .toHaveLength(1);
    expect(chartCalls.addPane).toBe(0);
  });

  it("renders a text-only crosshair tooltip for the hovered date", async () => {
    render(<FinancialChart bars={BARS} computations={[DONCHIAN]} />);

    await waitFor(() => expect(crosshairHandler).not.toBeNull());
    expect(crosshairHandler).not.toBeNull();

    crosshairHandler?.({ time: "2026-01-06", point: { x: 120, y: 60 } });

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("2026-01-06");
    expect(tooltip).toHaveTextContent("11.00");
    expect(tooltip).toHaveTextContent("Up breakout");
    expect(tooltip).toHaveTextContent("Close 13 above 12.4");
    expect(tooltip).not.toHaveTextContent("<script>");
  });

  it("offsets a synthetic crosshair by the left axis and pane heights", async () => {
    render(<FinancialChart bars={BARS} computations={[RSI]} />);
    await waitFor(() => expect(crosshairHandler).not.toBeNull());

    crosshairHandler?.({
      time: "2026-01-06",
      point: { x: 40, y: 30 },
      paneIndex: 1,
    });

    const tooltip = await screen.findByRole("tooltip");
    // container left offset (mock width 0) + pane-local x, and one pane above.
    expect(tooltip.style.left).toBe(`${40 + 0 + 16}px`);
    // This tooltip has no series or marker rows, so its estimated height
    // still fits below y=430 inside the 560px card and no vertical flip
    // happens; the pane offset is what this test pins.
    expect(tooltip.style.top).toBe(`${30 + 400 + 16}px`);
    expect(tooltip.style.bottom).toBe("");
  });

  it("hides the tooltip when the crosshair leaves the chart", async () => {
    render(<FinancialChart bars={BARS} computations={[DONCHIAN]} />);
    await waitFor(() => expect(crosshairHandler).not.toBeNull());

    crosshairHandler?.({ time: "2026-01-06", point: { x: 10, y: 10 } });
    await screen.findByRole("tooltip");

    crosshairHandler?.({});
    await waitFor(() =>
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument(),
    );
  });

  it("creates exactly one custom pane per referenced pane across instances", async () => {
    const twoPanes: IndicatorComputation = {
      ...RSI,
      instance_id: "multi",
      panes: [
        { id: "multi:a", title: "A", height: 120, price_scale: "right" },
        { id: "multi:b", title: "B", height: 140, price_scale: "left" },
        { id: "multi:unused", title: "Unused", height: 90, price_scale: "right" },
      ],
      series: [
        {
          id: "multi:a",
          pane_id: "multi:a",
          type: "line",
          title: "A",
          points: [{ time: "2026-01-05", value: 1, color: null }],
          color: "#2a78d6",
        },
        {
          id: "multi:b",
          pane_id: "multi:b",
          type: "area",
          title: "B",
          points: [{ time: "2026-01-05", value: 2, color: null }],
          color: "#eb6834",
        },
      ],
      markers: [],
      reference_lines: [],
    };

    render(<FinancialChart bars={BARS} computations={[twoPanes, RSI]} />);

    await waitFor(() => expect(chartCalls.created).toBe(1));
    expect(chartCalls.addPane).toBe(3);
    expect(chartCalls.addSeries.map((item) => item.paneIndex)).toEqual([
      0, 0, 1, 2, 3,
    ]);
    expect(paneRecords[1].setHeight).toHaveBeenCalledWith(120);
    expect(paneRecords[2].setHeight).toHaveBeenCalledWith(140);
    expect(paneRecords[3].setHeight).toHaveBeenCalledWith(150);
    expect(chartCalls.appliedOptions[0]).toMatchObject({
      leftPriceScale: { visible: true },
    });
  });

  it("hides the left price scale when no series asks for it", async () => {
    render(<FinancialChart bars={BARS} computations={[DONCHIAN]} />);

    await waitFor(() => expect(chartCalls.created).toBe(1));
    expect(chartCalls.appliedOptions[0]).toMatchObject({
      leftPriceScale: { visible: false },
    });
  });

  it("mounts a working chart when bars arrive after an empty first render", async () => {
    const { rerender } = render(<FinancialChart bars={[]} computations={[]} />);
    expect(chartCalls.created).toBe(0);

    rerender(<FinancialChart bars={BARS} computations={[]} />);

    await waitFor(() => expect(chartCalls.created).toBe(1));
    expect(await screen.findByTestId("financial-chart")).toBeInTheDocument();
  });

  it("tears the chart down on an empty range and rebuilds it when bars return", async () => {
    const { rerender } = render(
      <FinancialChart bars={BARS} computations={[]} />,
    );
    await waitFor(() => expect(chartCalls.created).toBe(1));
    expect(chartCalls.removed).toBe(0);

    rerender(<FinancialChart bars={[]} computations={[]} />);
    expect(
      screen.getByText("当前区间没有可显示的 K 线数据。"),
    ).toBeInTheDocument();
    // No live chart may keep drawing into a detached node.
    await waitFor(() => expect(chartCalls.removed).toBe(1));

    rerender(<FinancialChart bars={BARS} computations={[]} />);
    await waitFor(() =>
      expect(screen.getByTestId("financial-chart")).toBeInTheDocument(),
    );
    await waitFor(() => expect(chartCalls.created).toBe(2));
    expect(disconnected).toBeGreaterThanOrEqual(1);
  });

  it("degrades to a visible error instead of crashing on an invalid bar", async () => {
    const broken = [{ ...BARS[0], high: 1 }];

    render(<FinancialChart bars={broken} computations={[]} />);

    expect(screen.getByText("K 线数据无法绘制")).toBeInTheDocument();
    expect(screen.getByText(/high\/low range/)).toBeInTheDocument();
    expect(chartCalls.created).toBe(0);
  });

  it("degrades to a visible error on a duplicate bar date", async () => {
    render(<FinancialChart bars={[BARS[0], BARS[0]]} computations={[]} />);

    expect(screen.getByText("K 线数据无法绘制")).toBeInTheDocument();
    expect(screen.getByText(/strictly increasing/)).toBeInTheDocument();
  });

  it("shows guidance instead of a chart when no bars are available", async () => {
    render(<FinancialChart bars={[]} computations={[]} />);

    expect(
      screen.getByText("当前区间没有可显示的 K 线数据。"),
    ).toBeInTheDocument();
    expect(chartCalls.created).toBe(0);
  });

  it("removes the chart and disconnects observers on unmount", async () => {
    const { unmount } = render(
      <FinancialChart bars={BARS} computations={[RSI]} />,
    );
    await waitFor(() => expect(chartCalls.created).toBe(1));

    unmount();

    expect(chartCalls.removed).toBe(1);
    expect(disconnected).toBeGreaterThan(0);
  });

  it("exposes an accessible summary of rendered series and markers", async () => {
    render(<FinancialChart bars={BARS} computations={[RSI]} />);

    const summary = await screen.findByRole("region", {
      name: "图表数据摘要",
    });
    expect(summary).toHaveTextContent("RSI (14)");
    expect(summary).toHaveTextContent("2 个数据点");
    expect(summary).toHaveTextContent("1 个标记");
  });
});

describe("chart theme", () => {
  it("switches surface and text tokens between light and dark", () => {
    const light = getChartTheme("light");
    const dark = getChartTheme("dark");

    expect(light.surface).toBe("#fcfcfb");
    expect(dark.surface).toBe("#1a1a19");
    expect(light.text).not.toBe(dark.text);
    expect(light.up).toBe("#d84949");
    expect(dark.down).toBe("#008300");
  });
});
