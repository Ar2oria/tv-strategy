import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChartHeader } from "./ChartHeader";
import { getChartTheme } from "./theme";

const theme = getChartTheme("light");

const bar = {
  time: "2026-03-12",
  open: 10.2,
  high: 12,
  low: 9,
  close: 11,
  volume: 1_234_567,
};

describe("ChartHeader", () => {
  it("shows symbol and timeframe when no bar is available yet", () => {
    render(
      <ChartHeader
        symbol="0700.HK"
        timeframe="1w"
        bar={null}
        hovering={false}
        theme={theme}
      />,
    );

    expect(screen.getByTestId("chart-header")).toHaveTextContent("0700.HK");
    expect(screen.getByTestId("chart-header")).toHaveTextContent("周线");
    expect(screen.queryByTestId("chart-header-open")).toBeNull();
  });

  it("formats OHLC and volume for the hovered bar", () => {
    render(
      <ChartHeader
        symbol="0700.HK"
        timeframe="1d"
        bar={bar}
        hovering
        theme={theme}
      />,
    );

    expect(screen.getByTestId("chart-header-date")).toHaveTextContent(
      "2026-03-12",
    );
    expect(screen.getByTestId("chart-header-open")).toHaveTextContent("10.20");
    expect(screen.getByTestId("chart-header-high")).toHaveTextContent("12.00");
    expect(screen.getByTestId("chart-header-low")).toHaveTextContent("9.00");
    expect(screen.getByTestId("chart-header-close")).toHaveTextContent("11.00");
    expect(screen.getByTestId("chart-header-volume")).toHaveTextContent(
      "1,234,567",
    );
    // A hovered bar is not labelled as the newest one.
    expect(screen.getByTestId("chart-header-date")).not.toHaveTextContent(
      "最新",
    );
  });

  it("shows close-to-open change and high-to-low amplitude percentages", () => {
    render(
      <ChartHeader
        symbol="0700.HK"
        timeframe="1d"
        bar={{ ...bar, open: 10 }}
        hovering
        theme={theme}
      />,
    );

    expect(screen.getByTestId("chart-header-change")).toHaveTextContent(
      "+10.00%",
    );
    expect(screen.getByTestId("chart-header-amplitude")).toHaveTextContent(
      "+33.33%",
    );
  });

  it("marks the fallback bar as the newest when not hovering", () => {
    render(
      <ChartHeader
        symbol="0700.HK"
        timeframe="1d"
        bar={bar}
        hovering={false}
        theme={theme}
      />,
    );

    expect(screen.getByTestId("chart-header-date")).toHaveTextContent("最新");
  });

  it("colors OHLC by direction and shows an em dash for missing volume", () => {
    render(
      <ChartHeader
        symbol="0700.HK"
        timeframe="1d"
        bar={{ ...bar, close: 9.5, volume: null }}
        hovering
        theme={theme}
      />,
    );

    expect(screen.getByTestId("chart-header-close")).toHaveStyle({
      color: theme.down,
    });
    expect(screen.getByTestId("chart-header-high")).toHaveStyle({
      color: theme.down,
    });
    expect(screen.getByTestId("chart-header-volume")).toHaveTextContent("—");
    expect(screen.getByTestId("chart-header-change")).toHaveTextContent("-6.86%");
    expect(screen.getByTestId("chart-header-change")).toHaveStyle({
      color: theme.down,
    });
  });

  it("shows em dashes when percentage denominators are zero", () => {
    render(
      <ChartHeader
        symbol="0700.HK"
        timeframe="1d"
        bar={{ ...bar, open: 0, high: 0, low: 0, close: 0 }}
        hovering
        theme={theme}
      />,
    );

    expect(screen.getByTestId("chart-header-change")).toHaveTextContent("—");
    expect(screen.getByTestId("chart-header-amplitude")).toHaveTextContent("—");
  });

  it("uses the up color when the bar closed above its open", () => {
    render(
      <ChartHeader
        symbol="0700.HK"
        timeframe="1d"
        bar={bar}
        hovering
        theme={theme}
      />,
    );

    expect(screen.getByTestId("chart-header-close")).toHaveStyle({
      color: theme.up,
    });
  });
});
