import {
  AreaSeries,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type IRange,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { buildHover } from "./adapter";
import type {
  ChartHover,
  ChartModel,
  ChartSeriesBinding,
} from "./types";
import { CANDLE_SERIES_KEY } from "./types";
import { withAlpha, type ChartTheme } from "./theme";

const SERIES_DEFINITIONS = {
  line: LineSeries,
  area: AreaSeries,
  histogram: HistogramSeries,
} as const;

const VOLUME_PRICE_SCALE = "volume";
const MAIN_PANE_INDEX = 0;
/** Share of the main pane reserved for the volume histogram. */
const VOLUME_BAND_TOP = 0.82;
/**
 * Candle band inside the main pane. The bottom margin must exceed the 0.18
 * histogram band so the lowest candle never touches the volume bars. These
 * margins are honoured only through ``createChart``'s price-scale options;
 * ``chart.priceScale(...)`` and ``series.priceScale()`` both ignore them for
 * an auto-scaled axis (verified by A/B builds).
 */
const PRICE_SCALE_MARGINS = { top: 0.06, bottom: 0.5 } as const;
/** Candle band: a little headroom on top, a clear gap above the volume bars. */
export const LEFT_EDGE_THRESHOLD_BARS = 200;

interface IndicatorSeriesLayer {
  api: ISeriesApi<SeriesType, Time>;
  paneIndex: number;
}

interface IndicatorLayers {
  signature: string;
  series: Map<string, IndicatorSeriesLayer>;
  markers: Map<string, ISeriesMarkersPluginApi<Time>>;
  priceLines: Map<string, IPriceLine>;
}

function emptyLayers(): IndicatorLayers {
  return {
    signature: "",
    series: new Map(),
    markers: new Map(),
    priceLines: new Map(),
  };
}

/**
 * `MouseEventParams.point` is pane-local (it excludes the price axes and every
 * pane above it), so it cannot position an overlay that lives in the chart
 * wrapper. Prefer the real pointer position; fall back to summing the public
 * pane/axis sizes when the library reports a synthetic crosshair.
 */
function containerPosition(
  chart: IChartApi,
  param: MouseEventParams<Time>,
  container: HTMLElement,
): { x: number; y: number } {
  const source = param.sourceEvent;
  if (source !== undefined) {
    const box = container.getBoundingClientRect();
    return { x: source.clientX - box.left, y: source.clientY - box.top };
  }
  const paneIndex = param.paneIndex ?? 0;
  let y = param.point?.y ?? 0;
  for (let index = 0; index < paneIndex; index += 1) {
    y += chart.paneSize(index).height;
  }
  const leftAxis = chart.priceScale("left").width();
  return { x: (param.point?.x ?? 0) + leftAxis, y };
}

/** Reserve the bottom of the shared pane for the volume histogram. */
function applyVolumeScaleMargins(chart: IChartApi): void {
  chart.priceScale(VOLUME_PRICE_SCALE, MAIN_PANE_INDEX).applyOptions({
    scaleMargins: { top: VOLUME_BAND_TOP, bottom: 0 },
  });
}

function usesLeftScale(model: ChartModel): boolean {
  return model.series.some((item) => item.priceScale === "left");
}

function layerSignature(model: ChartModel): string {
  const panes = model.panes
    .map((pane) => `${pane.key}@${pane.paneIndex}h${pane.height}`)
    .join("|");
  const series = model.series
    .map((item) => `${item.id}:${item.type}:${item.paneIndex}:${item.priceScale}`)
    .join("|");
  return `${panes}::${series}`;
}

function chartOptions(theme: ChartTheme, hasLeftScale: boolean) {
  return {
    autoSize: false,
    layout: {
      background: { color: theme.surface },
      textColor: theme.textSecondary,
      panes: {
        enableResize: true,
        separatorColor: theme.border,
        separatorHoverColor: theme.grid,
      },
    },
    grid: {
      vertLines: { color: theme.grid },
      horzLines: { color: theme.grid },
    },
    crosshair: {
      mode: 0 as const,
      vertLine: {
        color: theme.crosshair,
        style: LineStyle.Dotted,
        width: 1 as const,
        labelBackgroundColor: theme.tooltipBorder,
      },
      horzLine: {
        color: theme.crosshair,
        style: LineStyle.Dotted,
        width: 1 as const,
        labelBackgroundColor: theme.tooltipBorder,
      },
    },
    rightPriceScale: {
      borderColor: theme.border,
      scaleMargins: { top: 0.5, bottom: 0.5 },
      visible: false,
    },
    leftPriceScale: {
      borderColor: theme.border,
      visible: hasLeftScale,
      scaleMargins: PRICE_SCALE_MARGINS,
    },
    timeScale: {
      borderColor: "transparent",
      timeVisible: false,
      rightOffset: 4,
      barSpacing: 8,
      lockVisibleTimeRangeOnResize: true,
    },
  };
}

function markerPayload(
  model: ChartModel,
  targetId: string,
): SeriesMarker<Time>[] {
  const group = model.markers.find((item) => item.targetId === targetId);
  if (group === undefined) {
    return [];
  }
  return group.markers.map((marker) => ({
    time: marker.time,
    position: marker.position,
    shape: marker.shape,
    color: marker.color,
    ...(marker.text === null ? {} : { text: marker.text }),
  }));
}

function referenceLineKey(
  seriesId: string,
  value: number,
  color: string,
  title: string | null,
): string {
  return `${seriesId}\u0000${value}\u0000${color}\u0000${title ?? ""}`;
}

function seriesIdOfKey(key: string): string {
  return key.slice(0, key.indexOf("\u0000"));
}

/**
 * Detach marker plugins, drop reference lines, remove indicator series, then
 * remove panes from the highest index downward, leaving the candle pane intact.
 */
export function cleanupIndicatorLayers(
  chart: IChartApi,
  layers: IndicatorLayers,
): void {
  for (const plugin of layers.markers.values()) {
    plugin.detach();
  }
  layers.markers.clear();

  for (const [key, priceLine] of layers.priceLines) {
    layers.series.get(seriesIdOfKey(key))?.api.removePriceLine(priceLine);
  }
  layers.priceLines.clear();

  /** Removing highest-pane series first keeps later pane indexes stable. */
  const removals = [...layers.series.values()].sort(
    (left, right) => right.paneIndex - left.paneIndex,
  );
  for (const { api } of removals) {
    chart.removeSeries(api);
  }
  layers.series.clear();
  layers.signature = "";

  const paneCount = chart.panes().length;
  for (let index = paneCount - 1; index > MAIN_PANE_INDEX; index -= 1) {
    chart.removePane(index);
  }
}

function syncMarkers(
  model: ChartModel,
  layers: IndicatorLayers,
  candles: ISeriesApi<"Candlestick", Time>,
): void {
  const targets = new Set(model.markers.map((group) => group.targetId));
  for (const targetId of [...layers.markers.keys()]) {
    if (targets.has(targetId)) {
      continue;
    }
    layers.markers.get(targetId)?.detach();
    layers.markers.delete(targetId);
  }
  for (const targetId of targets) {
    const series =
      targetId === CANDLE_SERIES_KEY
        ? (candles as ISeriesApi<SeriesType, Time>)
        : layers.series.get(targetId)?.api;
    if (series === undefined) {
      continue;
    }
    const markers = markerPayload(model, targetId);
    const existing = layers.markers.get(targetId);
    if (existing === undefined) {
      layers.markers.set(targetId, createSeriesMarkers(series, markers));
    } else {
      existing.setMarkers(markers);
    }
  }
}

function syncReferenceLines(model: ChartModel, layers: IndicatorLayers): void {
  const desired = new Map<string, ChartModel["referenceLines"][number]>();
  for (const line of model.referenceLines) {
    desired.set(
      referenceLineKey(line.seriesId, line.value, line.color, line.title),
      line,
    );
  }
  for (const [key, priceLine] of [...layers.priceLines]) {
    if (desired.has(key)) {
      continue;
    }
    layers.series.get(seriesIdOfKey(key))?.api.removePriceLine(priceLine);
    layers.priceLines.delete(key);
  }
  for (const [key, line] of desired) {
    if (layers.priceLines.has(key)) {
      continue;
    }
    const series = layers.series.get(line.seriesId)?.api;
    if (series === undefined) {
      continue;
    }
    layers.priceLines.set(
      key,
      series.createPriceLine({
        price: line.value,
        color: line.color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: line.title ?? "",
      }),
    );
  }
}

/**
 * Series option names differ per type: `color` exists for line and histogram,
 * while area needs `lineColor`/`topColor`/`bottomColor`. Passing `color` to an
 * area series is silently ignored and leaves the library's default green.
 */
function seriesOptions(
  binding: ChartSeriesBinding,
): Record<string, unknown> {
  const shared = {
    title: binding.title,
    priceScaleId: binding.priceScale,
    priceLineVisible: false,
  };
  if (binding.type === "line") {
    return { ...shared, color: binding.color, lineWidth: 2 };
  }
  if (binding.type === "area") {
    return {
      ...shared,
      lineColor: binding.color,
      topColor: withAlpha(binding.color, 0.28),
      bottomColor: withAlpha(binding.color, 0.02),
      lineWidth: 2,
    };
  }
  return { ...shared, color: binding.color };
}

function buildIndicatorLayers(
  chart: IChartApi,
  model: ChartModel,
  candles: ISeriesApi<"Candlestick", Time>,
  layers: IndicatorLayers,
): void {
  const paneApis = model.panes.map(() => chart.addPane());
  /** Heights are applied last, deepest first: resizing redistributes stretch. */
  for (let index = paneApis.length - 1; index >= 0; index -= 1) {
    paneApis[index].setHeight(model.panes[index].height);
  }
  for (const binding of model.series) {
    const series = chart.addSeries(
      SERIES_DEFINITIONS[binding.type],
      seriesOptions(binding),
      binding.paneIndex,
    ) as ISeriesApi<SeriesType, Time>;
    series.setData(binding.data as never);
    layers.series.set(binding.id, { api: series, paneIndex: binding.paneIndex });
  }
  layers.signature = layerSignature(model);
  syncMarkers(model, layers, candles);
  syncReferenceLines(model, layers);
}

function updateIndicatorData(
  model: ChartModel,
  layers: IndicatorLayers,
  candles: ISeriesApi<"Candlestick", Time>,
): void {
  for (const binding of model.series) {
    const layer = layers.series.get(binding.id);
    if (layer === undefined) {
      continue;
    }
    layer.api.setData(binding.data as never);
    // Titles and colors are not part of the structural signature, so a param
    // edit that keeps IDs/panes stable (RSI 14 -> 21) would otherwise leave a
    // stale legend label or series color on screen.
    layer.api.applyOptions(seriesOptions(binding) as never);
  }
  syncMarkers(model, layers, candles);
  syncReferenceLines(model, layers);
}

interface ChartInstance {
  chart: IChartApi;
  candles: ISeriesApi<"Candlestick", Time>;
  volume: ISeriesApi<"Histogram", Time>;
  layers: IndicatorLayers;
}

export interface UseFinancialChartOptions {
  model: ChartModel;
  theme: ChartTheme;
  onHover: (hover: ChartHover | null) => void;
  /** Create the chart only when there is something to draw. */
  active: boolean;
  /** Fires when fewer than LEFT_EDGE_THRESHOLD_BARS bars remain leftward. */
  onNearLeftEdge?: () => void;
}

export function useFinancialChart({
  model,
  theme,
  onHover,
  active,
  onNearLeftEdge,
}: UseFinancialChartOptions) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<ChartInstance | null>(null);
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const onNearLeftEdgeRef = useRef(onNearLeftEdge);
  onNearLeftEdgeRef.current = onNearLeftEdge;
  const modelRef = useRef(model);
  modelRef.current = model;
  const themeRef = useRef(theme);
  themeRef.current = theme;

  useEffect(() => {
    if (!active) {
      return;
    }
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const initialTheme = themeRef.current;
    const initialModel = modelRef.current;
    const chart = createChart(
      container,
      chartOptions(initialTheme, usesLeftScale(initialModel)),
    );
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: initialTheme.up,
      downColor: initialTheme.down,
      wickUpColor: initialTheme.up,
      wickDownColor: initialTheme.down,
      borderVisible: false,
      priceScaleId: "right",
    });
    const volume = chart.addSeries(
      HistogramSeries,
      {
        priceScaleId: VOLUME_PRICE_SCALE,
        priceFormat: { type: "volume" },
        lastValueVisible: false,
        priceLineVisible: false,
      },
      MAIN_PANE_INDEX,
    );
    applyVolumeScaleMargins(chart);

    const layers = emptyLayers();
    candles.setData(initialModel.candles as never);
    volume.setData(initialModel.volume as never);
    buildIndicatorLayers(chart, initialModel, candles, layers);
    instanceRef.current = { chart, candles, volume, layers };

    const handleCrosshair = (param: MouseEventParams<Time>) => {
      if (param.time === undefined || param.point === undefined) {
        onHoverRef.current(null);
        return;
      }
      const position = containerPosition(chart, param, container);
      onHoverRef.current(
        buildHover(modelRef.current, String(param.time), position),
      );
    };
    chart.subscribeCrosshairMove(handleCrosshair);

    const handleVisibleRangeChange = (
      logicalRange: IRange<number> | null,
    ) => {
      if (logicalRange === null) {
        return;
      }
      // ``from`` is the first visible logical index; it equals the number
      // of bars sitting to the left of the viewport. Negative values mean
      // the viewport extends past the oldest bar (also near the edge).
      const barsBefore = Math.floor(Math.max(0, logicalRange.from));
      if (barsBefore < LEFT_EDGE_THRESHOLD_BARS) {
        onNearLeftEdgeRef.current?.();
      }
    };
    chart
      .timeScale()
      .subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry === undefined) {
        return;
      }
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        chart.applyOptions({ width, height });
      }
    });
    observer.observe(container);

    return () => {
      chart
        .timeScale()
        .unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      chart.unsubscribeCrosshairMove(handleCrosshair);
      observer.disconnect();
      for (const plugin of layers.markers.values()) {
        plugin.detach();
      }
      instanceRef.current = null;
      chart.remove();
    };
  }, [active]);

  useEffect(() => {
    const instance = instanceRef.current;
    if (instance === null) {
      return;
    }
    instance.chart.applyOptions(
      chartOptions(theme, usesLeftScale(modelRef.current)),
    );
    instance.candles.applyOptions({
      upColor: theme.up,
      downColor: theme.down,
      wickUpColor: theme.up,
      wickDownColor: theme.down,
    });
  }, [theme]);

  const previousFirstBarRef = useRef<string | null>(null);
  const previousLengthRef = useRef(0);

  useEffect(() => {
    const instance = instanceRef.current;
    if (instance === null) {
      return;
    }
    const firstTime = model.candles[0]?.time;
    const nextFirst = firstTime === undefined ? null : String(firstTime);
    const prepend =
      previousFirstBarRef.current !== null &&
      nextFirst !== null &&
      previousFirstBarRef.current !== nextFirst &&
      model.candles.length > previousLengthRef.current;
    let visibleRange: IRange<Time> | null = null;
    if (prepend) {
      visibleRange = instance.chart.timeScale().getVisibleRange();
    }
    instance.candles.setData(model.candles as never);
    instance.volume.setData(model.volume as never);
    if (layerSignature(model) === instance.layers.signature) {
      updateIndicatorData(model, instance.layers, instance.candles);
    } else {
      cleanupIndicatorLayers(instance.chart, instance.layers);
      buildIndicatorLayers(
        instance.chart,
        model,
        instance.candles,
        instance.layers,
      );
    }
    if (visibleRange !== null) {
      instance.chart.timeScale().setVisibleRange(visibleRange);
    }
    previousFirstBarRef.current = nextFirst;
    previousLengthRef.current = model.candles.length;
  }, [model]);

  return containerRef;
}
