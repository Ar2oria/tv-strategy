import type { CSSProperties } from "react";

import type { Timeframe } from "../types/market";
import type { ChartTheme } from "./theme";

/** The OHLC slice shared by ``BarDTO`` and ``ChartHover``. */
export interface ChartHeaderBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

const TIMEFRAME_LABELS: Record<Timeframe, string> = {
  "1d": "日线",
  "1w": "周线",
  "1M": "月线",
};

export interface ChartHeaderProps {
  symbol: string;
  timeframe: Timeframe;
  /** The bar to describe: the hovered bar, or the latest one when idle. */
  bar: ChartHeaderBar | null;
  /** True when `bar` came from the crosshair rather than the newest bar. */
  hovering: boolean;
  theme: ChartTheme;
}

function price(value: number): string {
  return value.toFixed(2);
}

function ratioPercent(numerator: number, denominator: number): string {
  if (
    denominator === 0 ||
    !Number.isFinite(numerator) ||
    !Number.isFinite(denominator)
  ) {
    return "—";
  }
  const ratio = numerator / denominator - 1;
  if (!Number.isFinite(ratio)) {
    return "—";
  }
  return `${ratio >= 0 ? "+" : ""}${(ratio * 100).toFixed(2)}%`;
}

function volume(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(
    value,
  );
}

/**
 * TradingView-style OHLC legend in the chart information band. It shows the
 * hovered bar while the crosshair is inside the chart and falls back to the
 * newest bar so the block never blanks out.
 */
export function ChartHeader({
  symbol,
  timeframe,
  bar,
  hovering,
  theme,
}: ChartHeaderProps) {
  const style: CSSProperties = {
    position: "relative",
    padding: "8px 12px 4px",
    pointerEvents: "none",
    fontSize: 12,
    lineHeight: 1.5,
    color: theme.textSecondary,
  };

  if (bar === null) {
    return (
      <div style={style} data-testid="chart-header">
        <div style={{ fontWeight: 600, color: theme.text }}>
          {symbol} · {TIMEFRAME_LABELS[timeframe]}
        </div>
      </div>
    );
  }

  const rising = bar.close >= bar.open;
  const directionColor = rising ? theme.up : theme.down;

  return (
    <div style={style} data-testid="chart-header">
      <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
        <span style={{ fontWeight: 600, color: theme.text }}>{symbol}</span>
        <span>{TIMEFRAME_LABELS[timeframe]}</span>
        <span style={{ color: theme.text }} data-testid="chart-header-date">
          {bar.time}
          {hovering ? "" : "（最新）"}
        </span>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <span>
          开{" "}
          <span style={{ color: directionColor }} data-testid="chart-header-open">
            {price(bar.open)}
          </span>
        </span>
        <span>
          高{" "}
          <span style={{ color: directionColor }} data-testid="chart-header-high">
            {price(bar.high)}
          </span>
        </span>
        <span>
          低{" "}
          <span style={{ color: directionColor }} data-testid="chart-header-low">
            {price(bar.low)}
          </span>
        </span>
        <span>
          收{" "}
          <span style={{ color: directionColor }} data-testid="chart-header-close">
            {price(bar.close)}
          </span>
        </span>
        <span>
          涨幅{" "}
          <span style={{ color: directionColor }} data-testid="chart-header-change">
            {ratioPercent(bar.close, bar.open)}
          </span>
        </span>
        <span>
          振幅{" "}
          <span data-testid="chart-header-amplitude">
            {ratioPercent(bar.high, bar.low)}
          </span>
        </span>
        <span data-testid="chart-header-volume">量 {volume(bar.volume)}</span>
      </div>
    </div>
  );
}
