import type { CSSProperties } from "react";

import type { ChartHover } from "./types";
import type { ChartTheme } from "./theme";

const OFFSET = 16;
const TOOLTIP_WIDTH = 260;
const LINE_HEIGHT = 19.2; // fontSize 12 * lineHeight 1.6
const CHROME_HEIGHT = 18; // padding 8+8 plus the 1px borders

export interface ChartTooltipProps {
  hover: ChartHover;
  theme: ChartTheme;
  /** Width of the positioning container (the chart card), in pixels. */
  containerWidth: number;
  /** Height of the positioning container (the chart card), in pixels. */
  containerHeight: number;
}

function formatPrice(value: number): string {
  return value.toFixed(2);
}

function formatVolume(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(
    value,
  );
}

function tooltipStyle(
  hover: ChartHover,
  theme: ChartTheme,
  containerWidth: number,
  containerHeight: number,
): CSSProperties {
  // ``hover.x``/``hover.y`` are relative to the chart container, so the
  // boundaries must be the container's own size. Comparing them against the
  // viewport made a wide chart place the tooltip outside its card, which
  // widened the document and flickered the page scrollbars.
  // The OHLC/volume block is four lines; every series and marker adds one.
  const estimatedHeight =
    CHROME_HEIGHT +
    LINE_HEIGHT * (4 + hover.series.length + hover.markers.length);
  // A zero measurement means layout has not run yet (or a headless DOM):
  // fall back to anchoring right/down rather than flipping on every hover.
  const boundedWidth = containerWidth > 0 ? containerWidth : Number.MAX_SAFE_INTEGER;
  const boundedHeight =
    containerHeight > 0 ? containerHeight : Number.MAX_SAFE_INTEGER;
  const flipX = hover.x + OFFSET + TOOLTIP_WIDTH > boundedWidth;
  const flipY = hover.y + OFFSET + estimatedHeight > boundedHeight;
  return {
    position: "absolute",
    left: flipX ? undefined : hover.x + OFFSET,
    right: flipX ? boundedWidth - hover.x + OFFSET : undefined,
    top: flipY ? undefined : hover.y + OFFSET,
    bottom: flipY ? boundedHeight - hover.y + OFFSET : undefined,
    width: TOOLTIP_WIDTH,
    maxHeight:
      containerHeight > 0 ? containerHeight - OFFSET * 2 : undefined,
    overflow: "hidden",
    padding: "8px 10px",
    borderRadius: 6,
    border: `1px solid ${theme.tooltipBorder}`,
    background: theme.tooltipSurface,
    color: theme.text,
    fontSize: 12,
    lineHeight: 1.6,
    pointerEvents: "none",
    zIndex: 2,
    boxShadow: "0 4px 12px rgba(0, 0, 0, 0.12)",
  };
}

/** Pure text tooltip; no HTML from the API is ever interpreted. */
export function ChartTooltip({
  hover,
  theme,
  containerWidth,
  containerHeight,
}: ChartTooltipProps) {
  return (
    <div
      style={tooltipStyle(hover, theme, containerWidth, containerHeight)}
      role="tooltip"
    >
      <div style={{ fontWeight: 600, color: theme.text }}>{hover.time}</div>
      <div style={{ color: theme.textSecondary }}>
        开 {formatPrice(hover.open)}　高 {formatPrice(hover.high)}
      </div>
      <div style={{ color: theme.textSecondary }}>
        低 {formatPrice(hover.low)}　收 {formatPrice(hover.close)}
      </div>
      <div style={{ color: theme.textSecondary }}>
        成交量 {formatVolume(hover.volume)}
      </div>
      {hover.series.map((item) => (
        <div key={item.id} style={{ display: "flex", gap: 6 }}>
          <span
            aria-hidden="true"
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              marginTop: 7,
              borderRadius: "50%",
              background: item.color,
            }}
          />
          <span style={{ color: theme.textSecondary }}>
            {item.title} {formatPrice(item.value)}
          </span>
        </div>
      ))}
      {hover.markers.map((marker, index) => (
        <div key={`${marker.text ?? "marker"}-${index}`} style={{ color: theme.text }}>
          <span style={{ color: marker.color }}>●</span>{" "}
          {marker.text ?? "信号"}
          {marker.tooltip === null ? "" : ` — ${marker.tooltip}`}
        </div>
      ))}
    </div>
  );
}
