import { describe, expect, it } from "vitest";

import type { BarDTO } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import {
  buildChartModel,
  buildHover,
  isValidIsoDate,
  mergeMarkerGroups,
} from "./adapter";
import { ChartDataError } from "./types";

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

function computation(
  overrides: Partial<IndicatorComputation> = {},
): IndicatorComputation {
  return {
    instance_id: "a1",
    name: "demo",
    panes: [],
    series: [],
    markers: [],
    reference_lines: [],
    warnings: [],
    error: null,
    ...overrides,
  };
}

describe("isValidIsoDate", () => {
  it.each(["2026-01-05", "2024-02-29"])("accepts %s", (value) => {
    expect(isValidIsoDate(value)).toBe(true);
  });

  it.each(["2026-1-05", "2026-01-05T00:00:00Z", "2026-02-30", "20260105"])(
    "rejects %s",
    (value) => {
      expect(isValidIsoDate(value)).toBe(false);
    },
  );
});

describe("buildChartModel edge cases", () => {
  it("rejects duplicate series identifiers owned by different instances", () => {
    expect(() =>
      buildChartModel({
        bars: BARS,
        computations: [
          computation({
            instance_id: "a1",
            series: [
              {
                id: "shared",
                pane_id: "main",
                type: "line",
                title: "A",
                points: [],
                color: "#2a78d6",
              },
            ],
          }),
          computation({
            instance_id: "a2",
            series: [
              {
                id: "shared",
                pane_id: "main",
                type: "line",
                title: "B",
                points: [],
                color: "#2a78d6",
              },
            ],
          }),
        ],
      }),
    ).toThrow(ChartDataError);
  });

  it("allows one instance to reuse its own identifier across series and pane", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          panes: [
            { id: "osc", title: "Osc", height: 120, price_scale: "right" },
          ],
          series: [
            {
              id: "osc",
              pane_id: "osc",
              type: "line",
              title: "Osc",
              points: [{ time: "2026-01-05", value: 1, color: null }],
              color: "#2a78d6",
            },
          ],
        }),
      ],
    });

    expect(model.panes).toEqual([
      { key: "osc", paneIndex: 1, height: 120, priceScale: "right" },
    ]);
    expect(model.series[0].paneIndex).toBe(1);
  });

  it("reports a series that targets a pane the instance never declared", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          series: [
            {
              id: "a1:value",
              pane_id: "ghost",
              type: "line",
              title: "Ghost",
              points: [],
              color: "#2a78d6",
            },
          ],
        }),
      ],
    });

    expect(model.issues[0].message).toContain("ghost");
    expect(model.series).toEqual([]);
  });

  it("reports non-finite reference-line values", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          series: [
            {
              id: "a1:value",
              pane_id: "main",
              type: "line",
              title: "Value",
              points: [{ time: "2026-01-05", value: 1, color: null }],
              color: "#2a78d6",
            },
          ],
          reference_lines: [
            {
              series_id: "a1:value",
              value: Number.POSITIVE_INFINITY,
              color: "#8b94a7",
              title: null,
            },
          ],
        }),
      ],
    });

    expect(model.issues[0].message).toContain("有限");
    expect(model.referenceLines).toEqual([]);
  });

  it("falls back to the pane title and then the indicator name in summaries", () => {
    const paneOnly = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          panes: [{ id: "osc", title: "Oscillator", height: 120, price_scale: "right" }],
        }),
      ],
    });
    const bare = buildChartModel({
      bars: BARS,
      computations: [computation({ name: "empty-name" })],
    });

    expect(paneOnly.summaries[0].title).toBe("Oscillator");
    expect(bare.summaries[0].title).toBe("empty-name");
  });

  it("reports non-Error failures with a generic chart message", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          series: [
            {
              id: "a1:value",
              pane_id: "main",
              type: "line",
              title: "Value",
              points: [
                { time: "2026-01-06", value: 1, color: null },
                { time: "2026-01-05", value: 2, color: null },
              ],
              color: "#2a78d6",
            },
          ],
        }),
      ],
    });

    expect(model.issues).toHaveLength(1);
    expect(model.issues[0].message).toContain("strictly increasing");
  });
});

describe("markers on a shared target", () => {
  it("merges two instances that both mark the candle series", () => {
    const first = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          instance_id: "a1",
          markers: [
            {
              time: "2026-01-05",
              position: "belowBar",
              shape: "arrowUp",
              color: "#168b5b",
              text: "A up",
              tooltip: null,
              series_id: null,
            },
          ],
        }),
        computation({
          instance_id: "a2",
          markers: [
            {
              time: "2026-01-05",
              position: "aboveBar",
              shape: "arrowDown",
              color: "#d1345b",
              text: "B down",
              tooltip: null,
              series_id: null,
            },
          ],
        }),
      ],
    });

    expect(first.markers).toHaveLength(1);
    expect(first.markers[0].markers.map((marker) => marker.text)).toEqual([
      "A up",
      "B down",
    ]);
  });

  it("sorts merged markers ascending in time", () => {
    const model = buildChartModel({
      bars: [
        { ...BARS[0], time: "2026-01-05" },
        { ...BARS[0], time: "2026-01-06" },
        { ...BARS[0], time: "2026-01-07" },
      ],
      computations: [
        computation({
          instance_id: "late",
          markers: [
            {
              time: "2026-01-07",
              position: "belowBar",
              shape: "arrowUp",
              color: "#168b5b",
              text: "late",
              tooltip: null,
              series_id: null,
            },
          ],
        }),
        computation({
          instance_id: "early",
          markers: [
            {
              time: "2026-01-05",
              position: "belowBar",
              shape: "arrowUp",
              color: "#168b5b",
              text: "early",
              tooltip: null,
              series_id: null,
            },
          ],
        }),
      ],
    });

    expect(model.markers[0].markers.map((marker) => marker.time)).toEqual([
      "2026-01-05",
      "2026-01-07",
    ]);
  });

  it("keeps separate targets apart", () => {
    const groups = mergeMarkerGroups([
      { targetId: "main:candles", markers: [] },
      { targetId: "rsi:value", markers: [] },
    ]);

    expect(groups.map((group) => group.targetId)).toEqual([
      "main:candles",
      "rsi:value",
    ]);
  });

  it("returns no groups for no markers", () => {
    expect(mergeMarkerGroups([])).toEqual([]);
  });
});

describe("buildHover", () => {
  it("returns null outside visible bars", () => {
    const model = buildChartModel({ bars: BARS, computations: [] });

    expect(buildHover(model, "2026-01-07", { x: 1, y: 2 })).toBeNull();
  });

  it("collects series values and markers for the hovered date", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          series: [
            {
              id: "a1:value",
              pane_id: "main",
              type: "line",
              title: "Value",
              points: [{ time: "2026-01-05", value: 3.5, color: null }],
              color: "#2a78d6",
            },
          ],
          markers: [
            {
              time: "2026-01-05",
              position: "aboveBar",
              shape: "circle",
              color: "#d1345b",
              text: "Signal",
              tooltip: "Signal tooltip",
              series_id: null,
            },
          ],
        }),
      ],
    });

    expect(buildHover(model, "2026-01-05", { x: 5, y: 6 })).toEqual({
      time: "2026-01-05",
      x: 5,
      y: 6,
      open: 10,
      high: 12,
      low: 9,
      close: 11,
      volume: 100,
      series: [
        { id: "a1:value", title: "Value", value: 3.5, color: "#2a78d6" },
      ],
      markers: [
        {
          text: "Signal",
          tooltip: "Signal tooltip",
          color: "#d1345b",
        },
      ],
    });
  });

  it("skips series without a value on the hovered date", () => {
    const model = buildChartModel({
      bars: BARS,
      computations: [
        computation({
          series: [
            {
              id: "a1:value",
              pane_id: "main",
              type: "line",
              title: "Value",
              points: [{ time: "2025-12-31", value: 3.5, color: null }],
              color: "#2a78d6",
            },
          ],
        }),
      ],
    });

    const hover = buildHover(model, "2026-01-05", { x: 0, y: 0 });
    expect(hover?.series).toEqual([]);
  });
});
