import { Alert, Empty, Space, Typography } from "antd";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { BarDTO, Timeframe } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import { buildChartModel } from "./adapter";
import { ChartHeader } from "./ChartHeader";
import { ChartTooltip } from "./ChartTooltip";
import { getChartTheme, type ChartMode } from "./theme";
import { ChartDataError, type ChartHover } from "./types";
import { useFinancialChart } from "./useFinancialChart";

/**
 * The chart shrinks to fit the viewport so the volume pane never falls below
 * the fold once the in-chart toolbar and legends occupy vertical space.
 */
const CHART_HEIGHT = "clamp(360px, calc(100vh - 320px), 560px)";
/** Two 18px header lines starting at 8px, plus a small gap. */
const HEADER_HEIGHT = 52;
const EMPTY_MODEL = {
  candles: [],
  volume: [],
  panes: [],
  series: [],
  markers: [],
  referenceLines: [],
  issues: [],
  warnings: [],
  summaries: [],
  barsByTime: new Map(),
} satisfies ReturnType<typeof buildChartModel>;

export interface FinancialChartProps {
  bars: readonly BarDTO[];
  computations: readonly IndicatorComputation[];
  mode?: ChartMode;
  onNearLeftEdge?: () => void;
  /** Symbol shown in the in-chart legend. */
  symbol?: string;
  /** Timeframe shown in the in-chart legend. */
  timeframe?: Timeframe;
  /**
   * TradingView-style per-indicator legend row rendered inside the chart
   * card, above the candles. Receives the hovered bar (or the newest one)
   * so values can track the crosshair.
   */
  renderIndicatorLegend?: (context: {
    hovered: ChartHover | null;
    latestBar: BarDTO | null;
    activeTime: string | null;
  }) => ReactNode;
  /** Reports the bar the legends describe (hovered, else the newest one). */
  onActiveTimeChange?: (time: string | null) => void;
}

interface ModelResult {
  model: ReturnType<typeof buildChartModel> | null;
  failure: string | null;
}

/** A rejected bar or marker must degrade one chart, never the whole page. */
function useChartModel(
  bars: readonly BarDTO[],
  computations: readonly IndicatorComputation[],
): ModelResult {
  return useMemo(() => {
    try {
      return { model: buildChartModel({ bars, computations }), failure: null };
    } catch (error: unknown) {
      return {
        model: null,
        failure:
          error instanceof ChartDataError
            ? error.message
            : "图表数据不合法，无法绘制。",
      };
    }
  }, [bars, computations]);
}

function ChartSummaryRegion({
  model,
}: {
  model: ReturnType<typeof buildChartModel>;
}) {
  return (
    <section
      aria-label="图表数据摘要"
      style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}
    >
      <h2>图表数据摘要</h2>
      <p>共 {model.candles.length} 根 K 线</p>
      <ul>
        {model.summaries.map((summary) => (
          <li key={summary.instanceId}>
            {summary.title}：{summary.pointCount} 个数据点，
            {summary.markerCount} 个标记
          </li>
        ))}
      </ul>
    </section>
  );
}

function useMeasuredBox(): {
  width: number;
  height: number;
  ref: (node: HTMLDivElement | null) => void;
} {
  const [box, setBox] = useState({ width: 0, height: 0 });
  const observerRef = useRef<ResizeObserver | null>(null);

  const ref = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (node === null) {
      return;
    }
    const set = (width: number, height: number) => {
      setBox((current) =>
        current.width === width && current.height === height
          ? current
          : { width, height },
      );
    };
    const rect = node.getBoundingClientRect();
    set(rect.width, rect.height);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry !== undefined) {
        set(entry.contentRect.width, entry.contentRect.height);
      }
    });
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  useEffect(() => () => observerRef.current?.disconnect(), []);

  return { ...box, ref };
}

export function FinancialChart({
  bars,
  computations,
  mode = "light",
  onNearLeftEdge,
  symbol = "",
  timeframe = "1d",
  renderIndicatorLegend,
  onActiveTimeChange,
}: FinancialChartProps) {
  const theme = getChartTheme(mode);
  const [hover, setHover] = useState<ChartHover | null>(null);
  const measured = useMeasuredBox();
  const { model, failure } = useChartModel(bars, computations);
  const active = bars.length > 0 && failure === null && model !== null;
  const containerRef = useFinancialChart({
    model: model ?? EMPTY_MODEL,
    theme,
    onHover: setHover,
    active,
    onNearLeftEdge,
  });

  const latestBar = bars.length === 0 ? null : bars[bars.length - 1];
  const onActiveTimeChangeRef = useRef(onActiveTimeChange);
  onActiveTimeChangeRef.current = onActiveTimeChange;
  const activeBar = hover !== null ? hover : latestBar;
  const activeTime = activeBar === null ? null : activeBar.time;

  useEffect(() => {
    onActiveTimeChangeRef.current?.(activeTime);
  }, [activeTime]);
  const legend =
    renderIndicatorLegend === undefined
      ? null
      : renderIndicatorLegend({
          hovered: hover,
          latestBar,
          activeTime,
        });

  if (failure !== null) {
    return (
      <Alert
        type="error"
        showIcon
        title="K 线数据无法绘制"
        description={failure}
      />
    );
  }

  if (bars.length === 0 || model === null) {
    return (
      <div style={{ position: "relative", width: "100%", height: CHART_HEIGHT }}>
        {/* Kept mounted so the lifecycle effect can create the chart when bars
            arrive on a later render, and so an empty range does not tear down
            a live chart. */}
        <div
          ref={containerRef}
          style={{ position: "absolute", inset: 0, visibility: "hidden" }}
          aria-hidden="true"
        />
        <Empty
          description="当前区间没有可显示的 K 线数据。"
          style={{ padding: 48 }}
        />
      </div>
    );
  }

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {model.issues.length === 0 ? null : (
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          {model.issues.map((issue) => (
            <Alert
              key={issue.instanceId}
              type="warning"
              showIcon
              title={`指标 ${issue.instanceId} 未能绘制`}
              description={issue.message}
            />
          ))}
        </Space>
      )}
      {model.warnings.length === 0 ? null : (
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          {model.warnings.map((warning) => (
            <Alert
              key={warning.instanceId}
              type="info"
              title={`指标 ${warning.instanceId} 提示`}
              description={warning.messages.join("；")}
            />
          ))}
        </Space>
      )}
      <div
        ref={measured.ref}
        style={{
          position: "relative",
          width: "100%",
          height: CHART_HEIGHT,
          background: theme.surface,
          borderRadius: 8,
          border: `1px solid ${theme.border}`,
          // Absolute tooltips must never widen the document; they are
          // clamped inside the card instead of creating page scrollbars.
          overflow: "hidden",
        }}
        data-testid="financial-chart"
      >
        <div
          ref={containerRef}
          style={{ width: "100%", height: "100%" }}
          aria-hidden="true"
        />
        <ChartHeader
          symbol={symbol}
          timeframe={timeframe}
          bar={activeBar}
          hovering={hover !== null}
          theme={theme}
        />
        {legend === null ? null : (
          <div
            style={{
              position: "absolute",
              // Below the two-line OHLC header (top 8, 18px lines) so an
              // indicator row never overlaps the price block.
              top: HEADER_HEIGHT,
              left: 12,
              right: 12,
              zIndex: 3,
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              // Let hover reach the candles behind the legend band.
              pointerEvents: "none",
            }}
          >
            {legend}
          </div>
        )}
        {hover === null ? null : (
          <ChartTooltip
            hover={hover}
            theme={theme}
            containerWidth={measured.width}
            containerHeight={measured.height}
          />
        )}
      </div>
      <ChartSummaryRegion model={model} />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        上涨为红色、下跌为绿色；颜色对比度已按 CVD 可读性校验。
      </Typography.Text>
    </Space>
  );
}
