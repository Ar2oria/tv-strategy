import type { BarDTO } from "../types/market";

/** Marker bucket that means "attach to the shared candle series". */
export const CANDLE_SERIES_KEY = "main:candles";

/** A chart-integrity violation that must surface instead of rendering. */
export class ChartDataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChartDataError";
  }
}

export interface ChartCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface ChartVolumeBar {
  time: string;
  value: number;
  color: string;
}

export interface ChartWhitespaceItem {
  time: string;
}

export interface ChartValueItem {
  time: string;
  value: number;
  color?: string;
}

export type SeriesDataItem = ChartValueItem | ChartWhitespaceItem;

export interface ChartPaneBinding {
  key: string;
  paneIndex: number;
  height: number;
  priceScale: "left" | "right";
}

export interface ChartSeriesBinding {
  id: string;
  instanceId: string;
  title: string;
  type: "line" | "area" | "histogram";
  paneIndex: number;
  priceScale: "left" | "right";
  color: string;
  data: SeriesDataItem[];
  valuesByTime: ReadonlyMap<string, number>;
}

export interface ChartMarker {
  time: string;
  position: "aboveBar" | "belowBar" | "inBar";
  shape: "arrowUp" | "arrowDown" | "circle" | "square";
  color: string;
  text: string | null;
  tooltip: string | null;
}

export interface ChartMarkerGroup {
  targetId: string;
  markers: ChartMarker[];
}

export interface ChartReferenceLine {
  seriesId: string;
  value: number;
  color: string;
  title: string | null;
}

export interface ChartIssue {
  instanceId: string;
  message: string;
}

export interface ChartWarningGroup {
  instanceId: string;
  messages: string[];
}

export interface ChartSummary {
  instanceId: string;
  title: string;
  pointCount: number;
  markerCount: number;
}

export interface ChartModel {
  candles: ChartCandle[];
  volume: ChartVolumeBar[];
  panes: ChartPaneBinding[];
  series: ChartSeriesBinding[];
  markers: ChartMarkerGroup[];
  referenceLines: ChartReferenceLine[];
  issues: ChartIssue[];
  warnings: ChartWarningGroup[];
  summaries: ChartSummary[];
  barsByTime: ReadonlyMap<string, BarDTO>;
}

export interface ChartHoverSeriesValue {
  id: string;
  title: string;
  value: number;
  color: string;
}

export interface ChartHoverMarker {
  text: string | null;
  tooltip: string | null;
  color: string;
}

export interface ChartHover {
  time: string;
  x: number;
  y: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  series: ChartHoverSeriesValue[];
  markers: ChartHoverMarker[];
}
