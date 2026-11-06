import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChartTooltip } from "./ChartTooltip";
import { getChartTheme } from "./theme";
import type { ChartHover } from "./types";

const theme = getChartTheme("light");

function hover(overrides: Partial<ChartHover> = {}): ChartHover {
  return {
    time: "2026-01-05",
    x: 40,
    y: 20,
    open: 10,
    high: 12,
    low: 9,
    close: 11,
    volume: 1_234_567,
    series: [
      { id: "rsi", title: "RSI (14)", value: 55.5, color: "#2962ff" },
    ],
    markers: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ChartTooltip", () => {
  it("formats OHLC, grouped volume, and series values as text", () => {
    render(
      <ChartTooltip
        hover={hover()}
        theme={theme}
        containerWidth={1052}
        containerHeight={560}
      />,
    );

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("2026-01-05");
    expect(tooltip).toHaveTextContent("开 10.00");
    expect(tooltip).toHaveTextContent("收 11.00");
    expect(tooltip).toHaveTextContent("1,234,567");
    expect(tooltip).toHaveTextContent("RSI (14) 55.50");
  });

  it("shows an em dash for missing volume", () => {
    render(
      <ChartTooltip
        hover={hover({ volume: null })}
        theme={theme}
        containerWidth={1052}
        containerHeight={560}
      />,
    );

    expect(screen.getByRole("tooltip")).toHaveTextContent("成交量 —");
  });

  it("renders marker text and tooltip without interpreting markup", () => {
    render(
      <ChartTooltip
        hover={hover({
          markers: [
            {
              text: "Up breakout",
              tooltip: "<img src=x onerror=alert(1)>",
              color: "#d84949",
            },
            { text: null, tooltip: null, color: "#008300" },
          ],
        })}
        theme={theme}
        containerWidth={1052}
        containerHeight={560}
      />,
    );

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("Up breakout — <img src=x onerror=alert(1)>");
    expect(tooltip).toHaveTextContent("信号");
    expect(tooltip.querySelector("img")).toBeNull();
  });

  it("flips near the right edge of a narrow container", () => {
    render(
      <ChartTooltip
        hover={hover({ x: 1000 })}
        theme={theme}
        containerWidth={1024}
        containerHeight={560}
      />,
    );

    const style = screen.getByRole("tooltip").style;
    expect(style.left).toBe("");
    expect(style.right).not.toBe("");
  });

  it("stays to the right of the cursor away from the edge", () => {
    render(
      <ChartTooltip
        hover={hover({ x: 100 })}
        theme={theme}
        containerWidth={1024}
        containerHeight={560}
      />,
    );

    const style = screen.getByRole("tooltip").style;
    expect(style.left).toBe("116px");
    expect(style.right).toBe("");
  });
});

describe("ChartTooltip container-relative bounds", () => {
  it("flips left when the tooltip would overflow the chart container", () => {
    // Container is 1052px wide and sits 372px from the viewport's left edge.
    // x=930 is 44px from the container's right edge, so a 260px tooltip
    // anchored rightward would spill out even though the viewport is wide.
    render(
      <ChartTooltip
        hover={hover({ x: 930 })}
        theme={theme}
        containerWidth={1052}
        containerHeight={560}
      />,
    );

    const style = screen.getByRole("tooltip").style;
    expect(style.left).toBe("");
    expect(style.right).toBe(`${1052 - 930 + 16}px`);
  });

  it("anchors rightward when the tooltip fits inside the container", () => {
    render(
      <ChartTooltip
        hover={hover({ x: 100 })}
        theme={theme}
        containerWidth={1052}
        containerHeight={560}
      />,
    );

    const style = screen.getByRole("tooltip").style;
    expect(style.left).toBe("116px");
    expect(style.right).toBe("");
  });

  it("flips above the cursor near the container's bottom edge", () => {
    render(
      <ChartTooltip
        hover={hover({ x: 100, y: 540 })}
        theme={theme}
        containerWidth={1052}
        containerHeight={560}
      />,
    );

    const style = screen.getByRole("tooltip").style;
    // Bottom-anchored so the tooltip grows upward instead of past the chart.
    expect(style.top).toBe("");
    expect(style.bottom).toBe(`${560 - 540 + 16}px`);
  });

  it("keeps the downward anchor when there is room below the cursor", () => {
    render(
      <ChartTooltip
        hover={hover({ x: 100, y: 40 })}
        theme={theme}
        containerWidth={1052}
        containerHeight={560}
      />,
    );

    const style = screen.getByRole("tooltip").style;
    expect(style.top).toBe("56px");
    expect(style.bottom).toBe("");
  });
});
