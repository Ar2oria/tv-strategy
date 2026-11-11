import { describe, expect, it } from "vitest";

import type { BarDTO } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import {
  buildChartModel,
  toCandlestickData,
  toFiniteSeriesData,
  toVolumeData,
} from "./adapter";
import { CANDLE_SERIES_KEY, ChartDataError } from "./types";

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
    volume: null,
    source: "yfinance",
    adjustment: "qfq",
  },
];

function rsiComputation(
  overrides: Partial<IndicatorComputation> = {},
): IndicatorComputation {
  return {
    instance_id: "rsi-1",
    name: "rsi",
    panes: [
      { id: "rsi-1:rsi", title: "RSI", height: 160, price_scale: "right" },
    ],
    series: [
      {
        id: "rsi-1:rsi",
        pane_id: "rsi-1:rsi",
        type: "line",
        title: "RSI (14)",
        points: [{ time: "2026-01-05", value: 55.5, color: null }],
        color: "#2962ff",
      },
    ],
    markers: [],
    reference_lines: [
      {
        series_id: "rsi-1:rsi",
        value: 70,
        color: "#d1345b",
        title: "Overbought 70",
      },
    ],
    warnings: [],
    error: null,
    ...overrides,
  };
}

function donchianComputation(
  overrides: Partial<IndicatorComputation> = {},
): IndicatorComputation {
  return {
    instance_id: "donchian-1",
    name: "donchian",
    panes: [{ id: "main", title: "Price", height: 400, price_scale: "right" }],
    series: [
      {
        id: "donchian-1:upper",
        pane_id: "main",
        type: "line",
        title: "Previous 20-bar high",
        points: [
          { time: "2026-01-05", value: 12.5, color: null },
          { time: "2026-01-06", value: 12.8, color: null },
        ],
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
        tooltip: "Close 13 above previous 20-bar high 12.8",
        series_id: null,
      },
    ],
    reference_lines: [],
    warnings: [],
    error: null,
    ...overrides,
  };
}

describe("toFiniteSeriesData", () => {
  it("maps finite points with per-point color overrides", () => {
    expect(
      toFiniteSeriesData([
        { time: "2026-01-05", value: 55.5, color: null },
        { time: "2026-01-06", value: 71.2, color: "#d1345b" },
      ]),
    ).toEqual([
      { time: "2026-01-05", value: 55.5 },
      { time: "2026-01-06", value: 71.2, color: "#d1345b" },
    ]);
  });

  it("turns null values into whitespace items", () => {
    expect(
      toFiniteSeriesData([{ time: "2026-01-05", value: null }]),
    ).toEqual([{ time: "2026-01-05" }]);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    "rejects non-finite value %s",
    (value) => {
      expect(() =>
        toFiniteSeriesData([{ time: "2026-01-05", value }]),
      ).toThrow(ChartDataError);
    },
  );

  it("rejects duplicate dates", () => {
    expect(() =>
      toFiniteSeriesData([
        { time: "2026-01-05", value: 1 },
        { time: "2026-01-05", value: 2 },
      ]),
    ).toThrow(ChartDataError);
  });

  it("rejects dates that are not strictly increasing", () => {
    expect(() =>
      toFiniteSeriesData([
        { time: "2026-01-06", value: 1 },
        { time: "2026-01-05", value: 2 },
      ]),
    ).toThrow(ChartDataError);
  });

  it("rejects malformed dates", () => {
    expect(() =>
      toFiniteSeriesData([{ time: "2026-13-40", value: 1 }]),
    ).toThrow(ChartDataError);
  });
});

describe("toCandlestickData", () => {
  it("maps OHLC bars", () => {
    expect(toCandlestickData(BARS)).toEqual([
      { time: "2026-01-05", open: 10, high: 12, low: 9, close: 11 },
      { time: "2026-01-06", open: 11, high: 13, low: 10, close: 10 },
    ]);
  });

  it("rejects duplicate bar dates", () => {
    expect(() => toCandlestickData([BARS[0], BARS[0]])).toThrow(ChartDataError);
  });

  it("rejects non-finite prices", () => {
    expect(() =>
      toCandlestickData([{ ...BARS[0], high: Number.NaN }]),
    ).toThrow(ChartDataError);
  });

  it("rejects bars whose high or low does not bound open and close", () => {
    expect(() => toCandlestickData([{ ...BARS[0], high: 10.5 }])).toThrow(
      ChartDataError,
    );
    expect(() => toCandlestickData([{ ...BARS[0], low: 10.5 }])).toThrow(
      ChartDataError,
    );
  });
});

describe("toVolumeData", () => {
  it("colors rising and falling bars and skips missing volume", () => {
    expect(
      toVolumeData(BARS, { up: "#f23645", down: "#089981" }),
    ).toEqual([{ time: "2026-01-05", value: 100, color: "#f23645" }]);
    expect(
      buildChartModel({ bars: BARS, computations: [] }).volume[0].color,
    ).toBe("#f23645");
  });
});

describe("buildChartModel", () => {
  it("orders custom panes after the main pane in request order", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        rsiComputation(),
        rsiComputation({
          instance_id: "rsi-2",
          panes: [
            { id: "rsi-2:rsi", title: "RSI 2", height: 200, price_scale: "left" },
          ],
          series: [
            {
              id: "rsi-2:rsi",
              pane_id: "rsi-2:rsi",
              type: "line",
              title: "RSI (28)",
              points: [{ time: "2026-01-05", value: 40, color: null }],
              color: "#2a78d6",
            },
          ],
          reference_lines: [],
        }),
      ],
    });

    expect(model.panes).toEqual([
      { key: "rsi-1:rsi", paneIndex: 1, height: 160, priceScale: "right" },
      { key: "rsi-2:rsi", paneIndex: 2, height: 200, priceScale: "left" },
    ]);
    expect(model.series.map((item) => item.paneIndex)).toEqual([1, 2]);
    expect(model.series[1].priceScale).toBe("left");
  });

  it("ignores a main-pane price-scale wish so shared candles keep one scale", () => {
    const leftWish = donchianComputation({
      panes: [{ id: "main", title: "Price", height: 400, price_scale: "left" }],
    });

    const model = buildChartModel({ bars: BARS, computations: [leftWish] });

    expect(model.series[0].paneIndex).toBe(0);
    expect(model.series[0].priceScale).toBe("right");
    expect(model.panes).toEqual([]);
  });

  it("skips declared panes that no series targets", () => {
    const unusedPane = donchianComputation({
      panes: [
        { id: "main", title: "Price", height: 400, price_scale: "right" },
        { id: "donchian-1:unused", title: "Unused", height: 120, price_scale: "right" },
      ],
    });

    const model = buildChartModel({
      bars: BARS,
      computations: [unusedPane, rsiComputation()],
    });

    expect(model.panes.map((pane) => pane.key)).toEqual(["rsi-1:rsi"]);
  });

  it("keeps main-pane series on pane 0", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [donchianComputation()],
    });

    expect(model.panes).toEqual([]);
    expect(model.series[0]).toMatchObject({ paneIndex: 0, type: "line" });
  });

  it("groups markers on the candle series and on named series", () => {
    const onSeries = rsiComputation({
      markers: [
        {
          time: "2026-01-06",
          position: "aboveBar",
          shape: "circle",
          color: "#d1345b",
          text: null,
          tooltip: null,
          series_id: "rsi-1:rsi",
        },
      ],
    });
    const model = buildChartModel({
      bars: BARS,
      computations: [onSeries, donchianComputation()],
    });

    const candleGroup = model.markers.find(
      (group) => group.targetId === CANDLE_SERIES_KEY,
    );
    const seriesGroup = model.markers.find(
      (group) => group.targetId === "rsi-1:rsi",
    );
    expect(candleGroup?.markers.map((marker) => marker.text)).toEqual([
      "Up breakout",
    ]);
    expect(seriesGroup?.markers.map((marker) => marker.position)).toEqual([
      "aboveBar",
    ]);
  });

  it("surfaces a marker date without a bar as an instance issue", () => {
    const misaligned = donchianComputation({
      markers: [
        {
          time: "2026-01-07",
          position: "belowBar",
          shape: "arrowUp",
          color: "#168b5b",
          text: "Ghost",
          tooltip: null,
          series_id: null,
        },
      ],
    });

    const model = buildChartModel({
      bars: BARS,
      computations: [misaligned, rsiComputation()],
    });

    expect(model.issues).toHaveLength(1);
    expect(model.issues[0].instanceId).toBe("donchian-1");
    expect(model.issues[0].message).toContain("2026-01-07");
    expect(model.series.map((item) => item.id)).toEqual(["rsi-1:rsi"]);
    expect(model.markers).toEqual([]);
  });

  it("rejects markers that target an unknown series", () => {
    const broken = rsiComputation({
      markers: [
        {
          time: "2026-01-05",
          position: "inBar",
          shape: "square",
          color: "#d1345b",
          text: null,
          tooltip: null,
          series_id: "missing",
        },
      ],
    });

    const model = buildChartModel({
      bars: BARS,
      computations: [broken],
    });

    expect(model.issues[0].message).toContain("missing");
    expect(model.markers).toEqual([]);
  });

  it("keeps healthy instances when another calculation reports an error", () => {
    const failed = rsiComputation({
      instance_id: "rsi-fail",
      error: "RSI oversold must be lower than overbought",
      panes: [],
      series: [],
      reference_lines: [],
    });

    const model = buildChartModel({
      bars: BARS,
      computations: [failed, donchianComputation()],
    });

    expect(model.issues).toEqual([
      {
        instanceId: "rsi-fail",
        message: "RSI oversold must be lower than overbought",
      },
    ]);
    expect(model.series.map((item) => item.id)).toEqual(["donchian-1:upper"]);
    expect(model.candles).toHaveLength(2);
  });

  it("drops a reference line that targets an unknown series", () => {
    const broken = rsiComputation({
      reference_lines: [
        { series_id: "nope", value: 70, color: "#d1345b", title: "Bad" },
      ],
    });

    const model = buildChartModel({ bars: BARS, computations: [broken] });

    expect(model.issues[0].message).toContain("nope");
    expect(model.referenceLines).toEqual([]);
  });

  it("preserves warnings and series titles for the accessible summary", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        rsiComputation({ warnings: ["Flat periods were omitted."] }),
      ],
    });

    expect(model.warnings).toEqual([
      { instanceId: "rsi-1", messages: ["Flat periods were omitted."] },
    ]);
    expect(model.summaries).toEqual([
      {
        instanceId: "rsi-1",
        title: "RSI (14)",
        pointCount: 1,
        markerCount: 0,
      },
    ]);
  });

  it("rejects duplicate custom pane identifiers", () => {
    expect(() =>
      buildChartModel({
        bars: BARS,
        computations: [
          rsiComputation(),
          rsiComputation({ instance_id: "rsi-2" }),
        ],
      }),
    ).toThrow(ChartDataError);
  });
});
