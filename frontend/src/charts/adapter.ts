import type { BarDTO } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import {
  CANDLE_SERIES_KEY,
  ChartDataError,
  type ChartCandle,
  type ChartHover,
  type ChartIssue,
  type ChartMarker,
  type ChartMarkerGroup,
  type ChartModel,
  type ChartPaneBinding,
  type ChartReferenceLine,
  type ChartSeriesBinding,
  type ChartSummary,
  type ChartVolumeBar,
  type ChartWarningGroup,
  type SeriesDataItem,
} from "./types";

const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const MAIN_PANE_ID = "main";
const MAIN_PRICE_SCALE: "left" | "right" = "right";

export interface SeriesPointInput {
  time: string;
  value: number | null;
  color?: string | null;
}

export interface BuildChartModelInput {
  bars: readonly BarDTO[];
  computations: readonly IndicatorComputation[];
}

export function isValidIsoDate(value: string): boolean {
  const match = ISO_DATE_PATTERN.exec(value);
  if (match === null) {
    return false;
  }
  const year = Number.parseInt(match[1], 10);
  const month = Number.parseInt(match[2], 10);
  const day = Number.parseInt(match[3], 10);
  const timestamp = Date.UTC(year, month - 1, day);
  const parsed = new Date(timestamp);
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

function requireDate(value: string, location: string): string {
  if (!isValidIsoDate(value)) {
    throw new ChartDataError(`${location} is not a valid ISO date: ${value}`);
  }
  return value;
}

function requireFinite(value: number, location: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ChartDataError(`${location} must be a finite number`);
  }
  return value;
}

/** Convert backend points, keeping gaps as whitespace and rejecting bad data. */
export function toFiniteSeriesData(
  points: readonly SeriesPointInput[],
): SeriesDataItem[] {
  const items: SeriesDataItem[] = [];
  let previous: string | null = null;
  for (const point of points) {
    const time = requireDate(point.time, "Series point time");
    if (previous !== null && time <= previous) {
      throw new ChartDataError(
        `Series point dates must be strictly increasing: ${time}`,
      );
    }
    previous = time;
    if (point.value === null) {
      items.push({ time });
      continue;
    }
    const value = requireFinite(point.value, `Series point at ${time}`);
    const color = point.color;
    items.push(
      typeof color === "string" && color.length > 0
        ? { time, value, color }
        : { time, value },
    );
  }
  return items;
}

export function toCandlestickData(bars: readonly BarDTO[]): ChartCandle[] {
  const candles: ChartCandle[] = [];
  let previous: string | null = null;
  for (const bar of bars) {
    const time = requireDate(bar.time, "Bar time");
    if (previous !== null && time <= previous) {
      throw new ChartDataError(`Bar dates must be strictly increasing: ${time}`);
    }
    previous = time;
    const open = requireFinite(bar.open, `Open price at ${time}`);
    const high = requireFinite(bar.high, `High price at ${time}`);
    const low = requireFinite(bar.low, `Low price at ${time}`);
    const close = requireFinite(bar.close, `Close price at ${time}`);
    if (high < Math.max(open, close) || low > Math.min(open, close)) {
      throw new ChartDataError(
        `Bar at ${time} has a high/low range that excludes open or close`,
      );
    }
    candles.push({ time, open, high, low, close });
  }
  return candles;
}

export function toVolumeData(
  bars: readonly BarDTO[],
  colors: Readonly<{ up: string; down: string }>,
): ChartVolumeBar[] {
  return bars.flatMap((bar) => {
    if (bar.volume === null || !Number.isFinite(bar.volume)) {
      return [];
    }
    return [
      {
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? colors.up : colors.down,
      },
    ];
  });
}

/** Build a render-ready model; per-instance problems never drop other data. */
export function buildChartModel(input: BuildChartModelInput): ChartModel {
  const candles = toCandlestickData(input.bars);
  const barsByTime = new Map<string, BarDTO>(
    input.bars.map((bar) => [bar.time, bar]),
  );
  const visibleDates = new Set(barsByTime.keys());

  const paneOwners = new Map<string, string>();
  const seriesOwners = new Map<string, string>();
  const issues: ChartIssue[] = [];
  const warnings: ChartWarningGroup[] = [];
  const summaries: ChartSummary[] = [];
  const pending: AssembledInstance[] = [];

  for (const computation of input.computations) {
    const customPanes = computation.panes.filter(
      (pane) => pane.id !== MAIN_PANE_ID,
    );
    for (const pane of customPanes) {
      const owner = paneOwners.get(pane.id);
      if (owner !== undefined && owner !== computation.instance_id) {
        throw new ChartDataError(
          `Duplicate pane identifier across indicators: ${pane.id}`,
        );
      }
      paneOwners.set(pane.id, computation.instance_id);
    }
    for (const series of computation.series) {
      const owner = seriesOwners.get(series.id);
      if (owner !== undefined && owner !== computation.instance_id) {
        throw new ChartDataError(
          `Duplicate series identifier across indicators: ${series.id}`,
        );
      }
      seriesOwners.set(series.id, computation.instance_id);
    }

    if (computation.error !== null) {
      issues.push({
        instanceId: computation.instance_id,
        message: computation.error,
      });
      continue;
    }

    const attempt = assembleInstance(computation, visibleDates);
    if ("issue" in attempt) {
      issues.push({
        instanceId: computation.instance_id,
        message: attempt.issue,
      });
      continue;
    }
    pending.push(attempt);
    if (computation.warnings.length > 0) {
      warnings.push({
        instanceId: computation.instance_id,
        messages: [...computation.warnings],
      });
    }
    summaries.push({
      instanceId: computation.instance_id,
      title:
        computation.series[0]?.title ??
        computation.panes[0]?.title ??
        computation.name,
      pointCount: computation.series.reduce(
        (total, series) => total + series.points.length,
        0,
      ),
      markerCount: computation.markers.length,
    });
  }

  const panes: ChartPaneBinding[] = [];
  const paneIndexByKey = new Map<string, number>();
  const panePriceScale = new Map<string, "left" | "right">();
  const referencedPaneKeys = new Set(
    pending.flatMap((instance) =>
      instance.series.map((binding) => binding.paneIdKey),
    ),
  );
  for (const instance of pending) {
    for (const pane of instance.computation.panes) {
      if (pane.id === MAIN_PANE_ID || !referencedPaneKeys.has(pane.id)) {
        continue;
      }
      paneIndexByKey.set(pane.id, panes.length + 1);
      panePriceScale.set(pane.id, pane.price_scale);
      panes.push({
        key: pane.id,
        paneIndex: panes.length + 1,
        height: pane.height,
        priceScale: pane.price_scale,
      });
    }
  }

  const series = pending.flatMap((instance) =>
    instance.series.map((binding) => {
      const paneIndex = paneIndexByKey.get(binding.paneIdKey) ?? 0;
      return {
        ...binding,
        paneIndex,
        /** Pane 0 is shared, so its scale never follows an indicator's wish. */
        priceScale:
          paneIndex === 0
            ? MAIN_PRICE_SCALE
            : (panePriceScale.get(binding.paneIdKey) ?? MAIN_PRICE_SCALE),
      };
    }),
  );

  return {
    candles,
    volume: toVolumeData(input.bars, { up: "#d84949", down: "#008300" }),
    panes,
    series: series.map(stripPaneKey),
    markers: mergeMarkerGroups(
      pending.flatMap((instance) => instance.markerGroups),
    ),
    referenceLines: pending.flatMap((instance) => instance.referenceLines),
    issues,
    warnings,
    summaries,
    barsByTime,
  };
}

/**
 * Several instances may legitimately target the same series (one candle series
 * is shared by every main-pane indicator). Lightweight Charts accepts a single
 * marker array per series, so groups must be merged — otherwise the plugin
 * only ever receives the first group and the rest disappear silently. Merged
 * markers stay ascending in time because the primitive binary-searches them.
 */
export function mergeMarkerGroups(
  groups: readonly ChartMarkerGroup[],
): ChartMarkerGroup[] {
  const byTarget = new Map<string, ChartMarker[]>();
  for (const group of groups) {
    const bucket = byTarget.get(group.targetId) ?? [];
    bucket.push(...group.markers);
    byTarget.set(group.targetId, bucket);
  }
  return [...byTarget].map(([targetId, markers]) => ({
    targetId,
    markers: [...markers].sort((left, right) =>
      left.time < right.time ? -1 : left.time > right.time ? 1 : 0,
    ),
  }));
}

interface InternalSeriesBinding extends ChartSeriesBinding {
  paneIdKey: string;
}

interface AssembledInstance {
  computation: IndicatorComputation;
  series: InternalSeriesBinding[];
  markerGroups: ChartMarkerGroup[];
  referenceLines: ChartReferenceLine[];
}

interface InstanceIssue {
  issue: string;
}

function assembleInstance(
  computation: IndicatorComputation,
  visibleDates: ReadonlySet<string>,
): AssembledInstance | InstanceIssue {
  const paneIds = new Set([
    MAIN_PANE_ID,
    ...computation.panes.map((pane) => pane.id),
  ]);
  const knownSeries = new Set(computation.series.map((series) => series.id));
  const series: InternalSeriesBinding[] = [];

  for (const definition of computation.series) {
    if (!paneIds.has(definition.pane_id)) {
      return {
        issue: `序列 ${definition.id} 引用了未声明的 pane ${definition.pane_id}`,
      };
    }
    let data: SeriesDataItem[];
    try {
      data = toFiniteSeriesData(definition.points);
    } catch (error) {
      return { issue: describeError(error) };
    }
    const values = new Map<string, number>();
    for (const point of data) {
      if ("value" in point) {
        values.set(point.time, point.value);
      }
    }
    series.push({
      id: definition.id,
      instanceId: computation.instance_id,
      title: definition.title,
      type: definition.type,
      paneIdKey: definition.pane_id,
      paneIndex: 0,
      priceScale: MAIN_PRICE_SCALE,
      color: definition.color,
      data,
      valuesByTime: values,
    });
  }

  const markersByTarget = new Map<string, ChartMarker[]>();
  for (const marker of computation.markers) {
    if (!visibleDates.has(marker.time)) {
      return {
        issue: `标记日期 ${marker.time} 不存在于返回的 K 线中`,
      };
    }
    if (marker.series_id !== null && !knownSeries.has(marker.series_id)) {
      return { issue: `标记引用了未知序列 ${marker.series_id}` };
    }
    const target = marker.series_id ?? CANDLE_SERIES_KEY;
    const bucket = markersByTarget.get(target) ?? [];
    bucket.push({
      time: marker.time,
      position: marker.position,
      shape: marker.shape,
      color: marker.color,
      text: marker.text,
      tooltip: marker.tooltip,
    });
    markersByTarget.set(target, bucket);
  }

  const referenceLines: ChartReferenceLine[] = [];
  for (const line of computation.reference_lines) {
    if (!knownSeries.has(line.series_id)) {
      return { issue: `参考线引用了未知序列 ${line.series_id}` };
    }
    if (!Number.isFinite(line.value)) {
      return { issue: `参考线 ${line.series_id} 的值不是有限数字` };
    }
    referenceLines.push({
      seriesId: line.series_id,
      value: line.value,
      color: line.color,
      title: line.title,
    });
  }

  return {
    computation,
    series,
    markerGroups: [...markersByTarget].map(([targetId, markers]) => ({
      targetId,
      markers,
    })),
    referenceLines,
  };
}

function stripPaneKey(binding: InternalSeriesBinding): ChartSeriesBinding {
  const { paneIdKey: _paneIdKey, ...rest } = binding;
  return rest;
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : "图表数据不合法";
}

/** Text-only hover payload for the given date, or null when outside bars. */
export function buildHover(
  model: ChartModel,
  time: string,
  position: Readonly<{ x: number; y: number }>,
): ChartHover | null {
  const bar = model.barsByTime.get(time);
  if (bar === undefined) {
    return null;
  }
  const series = model.series.flatMap((binding) => {
    const value = binding.valuesByTime.get(time);
    return value === undefined
      ? []
      : [
          {
            id: binding.id,
            title: binding.title,
            value,
            color: binding.color,
          },
        ];
  });
  const markers = model.markers.flatMap((group) =>
    group.markers
      .filter((marker) => marker.time === time)
      .map((marker) => ({
        text: marker.text,
        tooltip: marker.tooltip,
        color: marker.color,
      })),
  );
  return {
    time,
    x: position.x,
    y: position.y,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
    series,
    markers,
  };
}
