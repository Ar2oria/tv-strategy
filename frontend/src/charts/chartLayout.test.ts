import { describe, expect, it } from "vitest";

import type { BarDTO } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import { buildChartModel } from "./adapter";
import {
  calculateAdditionalHeight,
  getSecondaryPaneHeights,
} from "./chartLayout";

const BARS: readonly BarDTO[] = [
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
    instance_id: "indicator-1",
    name: "example",
    panes: [],
    series: [],
    markers: [],
    reference_lines: [],
    warnings: [],
    error: null,
    ...overrides,
  };
}

function mainSeries(id: string): IndicatorComputation["series"][number] {
  return {
    id,
    pane_id: "main",
    type: "line",
    title: id,
    points: [{ time: "2026-01-05", value: 11, color: null }],
    color: "#2962ff",
  };
}

function heightOf(computations: readonly IndicatorComputation[]): number {
  const model = buildChartModel({ bars: BARS, computations });
  return calculateAdditionalHeight(computations, model);
}

function secondaryHeightsOf(
  computations: readonly IndicatorComputation[],
): number[] {
  const model = buildChartModel({ bars: BARS, computations });
  return getSecondaryPaneHeights(model);
}

function withPaneHeights(heights: readonly number[]): IndicatorComputation {
  return computation({
    panes: heights.map((height, index) => ({
      id: `pane-${index}`,
      title: `Pane ${index}`,
      height,
      price_scale: "right",
    })),
    series: heights.map((_, index) => ({
      ...mainSeries(`series-${index}`),
      pane_id: `pane-${index}`,
    })),
  });
}

describe("calculateAdditionalHeight", () => {
  it("adds nothing when no indicators are present", () => {
    expect(heightOf([])).toBe(0);
  });

  it("does not add height for main series or a declared main height", () => {
    const indicator = computation({
      panes: [{ id: "main", title: "Price", height: 400, price_scale: "right" }],
      series: [mainSeries("upper"), mainSeries("lower")],
    });

    expect(heightOf([indicator])).toBe(0);
  });

  it("does not add height for an undeclared main series", () => {
    const indicator = computation({ series: [mainSeries("upper")] });

    expect(heightOf([indicator])).toBe(0);
  });

  it("does not add height for multiple main indicator instances", () => {
    const first = computation({ instance_id: "first", series: [mainSeries("first:upper")] });
    const second = computation({ instance_id: "second", series: [mainSeries("second:upper")] });

    expect(heightOf([first, second])).toBe(0);
  });

  it("adds the declared height of each rendered secondary pane", () => {
    const indicator = computation({
      panes: [
        { id: "one", title: "One", height: 160, price_scale: "right" },
        { id: "two", title: "Two", height: 140, price_scale: "right" },
      ],
      series: [
        { ...mainSeries("one-line"), id: "one-line", pane_id: "one" },
        { ...mainSeries("two-line"), id: "two-line", pane_id: "two" },
      ],
    });

    expect(heightOf([indicator])).toBe(300);
  });

  it("combines main legend space and secondary pane heights", () => {
    const indicator = computation({
      series: [
        mainSeries("overlay"),
        { ...mainSeries("oscillator"), pane_id: "oscillator" },
      ],
      panes: [
        { id: "oscillator", title: "Oscillator", height: 160, price_scale: "right" },
      ],
    });

    expect(heightOf([indicator])).toBe(160);
  });

  it("ignores declared secondary panes that have no rendered series", () => {
    const indicator = computation({
      panes: [{ id: "unused", title: "Unused", height: 120, price_scale: "right" }],
      series: [mainSeries("overlay")],
    });

    expect(heightOf([indicator])).toBe(0);
  });

  it("does not reserve space for an instance rejected by chart validation", () => {
    const indicator = computation({
      error: "invalid result",
      panes: [{ id: "main", title: "Price", height: 400, price_scale: "right" }],
      series: [mainSeries("overlay")],
    });

    expect(heightOf([indicator])).toBe(0);
  });

  it("does not add height for a marker-only main indicator", () => {
    const indicator = computation({
      markers: [
        {
          time: "2026-01-05",
          position: "belowBar",
          shape: "arrowUp",
          color: "#168b5b",
          text: "signal",
          tooltip: null,
          series_id: null,
        },
      ],
    });

    expect(heightOf([indicator])).toBe(0);
  });

  it("keeps declared heights for one and two secondary panes", () => {
    expect(secondaryHeightsOf([withPaneHeights([120])])).toEqual([120]);
    expect(secondaryHeightsOf([withPaneHeights([120, 160])])).toEqual([120, 160]);
  });

  it("shrinks all secondary panes to 80 percent after the second pane", () => {
    expect(secondaryHeightsOf([withPaneHeights([160, 160, 160])])).toEqual([
      128, 128, 128,
    ]);
    for (const height of secondaryHeightsOf([
      withPaneHeights([160, 160, 160, 160]),
    ])) {
      expect(height).toBeCloseTo(102.4, 8);
    }
  });

  it("uses the average of the first two heights for non-uniform panes", () => {
    expect(secondaryHeightsOf([withPaneHeights([120, 160, 160])])).toEqual([
      112, 112, 112,
    ]);
  });

  it("caps total additional height at the two-pane height", () => {
    expect(heightOf([withPaneHeights([160, 160, 160])])).toBe(320);
    expect(heightOf([withPaneHeights([160, 160, 160, 160])])).toBe(320);
    expect(heightOf([withPaneHeights([120, 160, 160])])).toBe(280);
  });
});
