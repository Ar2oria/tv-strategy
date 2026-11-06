import type { RJSFSchema } from "@rjsf/utils";

import type { JsonObject } from "./api";
import type { Timeframe } from "./market";

export interface IndicatorDescriptor {
  name: string;
  display_name: string;
  description: string;
  params_schema: RJSFSchema;
}

export interface PaneDefinition {
  id: string;
  title: string;
  height: number;
  price_scale: "left" | "right";
}

export interface SeriesPoint {
  time: string;
  /** Null marks a gap; the chart renders it as whitespace, never as zero. */
  value: number | null;
  color: string | null;
}

export interface SeriesDefinition {
  id: string;
  pane_id: string;
  type: "line" | "area" | "histogram";
  title: string;
  points: SeriesPoint[];
  color: string;
}

export interface MarkerDefinition {
  time: string;
  position: "aboveBar" | "belowBar" | "inBar";
  shape: "arrowUp" | "arrowDown" | "circle" | "square";
  color: string;
  text: string | null;
  tooltip: string | null;
  series_id: string | null;
}

export interface ReferenceLine {
  series_id: string;
  value: number;
  color: string;
  title: string | null;
}

export interface IndicatorComputation {
  instance_id: string;
  name: string;
  panes: PaneDefinition[];
  series: SeriesDefinition[];
  markers: MarkerDefinition[];
  reference_lines: ReferenceLine[];
  warnings: string[];
  error: string | null;
}

export interface IndicatorInstanceRequest {
  instance_id: string;
  name: string;
  params: JsonObject;
}

export interface IndicatorComputeRequest {
  instrument_id: number;
  timeframe: Timeframe;
  start?: string;
  end?: string;
  limit?: number;
  indicators: IndicatorInstanceRequest[];
}
