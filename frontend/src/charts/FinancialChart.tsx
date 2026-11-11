import { Alert, Empty, Space, Typography } from "antd";
import type { CSSProperties, ReactNode } from "react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { BarDTO, Timeframe } from "../types/market";
import type { IndicatorComputation } from "../types/indicator";
import { buildChartModel } from "./adapter";
import { getChartHeight } from "./chartLayout";
import { ChartHeader } from "./ChartHeader";
import { ChartTooltip } from "./ChartTooltip";
import { getChartTheme, type ChartMode } from "./theme";
import {
  ChartDataError,
  type ChartHover,
  type ChartModel,
  type ChartPaneLayout,
} from "./types";
import { useFinancialChart } from "./useFinancialChart";

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
  /** Controls kept inside the chart panel, including in non-data states. */
  toolbar?: ReactNode;
  /** Empty, loading, or error content shown in place of the live canvas. */
  stateContent?: ReactNode;
  /** Short-lived status shown in the chart information band, never over candles. */
  loadingContent?: ReactNode;
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
    /** Undefined is treated as all items by compatibility renderers. */
    paneId?: string;
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
  toolbar,
  stateContent,
  loadingContent,
  mode = "dark",
  onNearLeftEdge,
  symbol = "",
  timeframe = "1d",
  renderIndicatorLegend,
  onActiveTimeChange,
}: FinancialChartProps) {
  const theme = getChartTheme(mode);
  const [hover, setHover] = useState<ChartHover | null>(null);
  const [paneLayouts, setPaneLayouts] = useState<ChartPaneLayout[]>([]);
  const measured = useMeasuredBox();
  const hasStateContent = stateContent !== undefined && stateContent !== null;
  const hasLoadingContent = loadingContent !== undefined && loadingContent !== null;
  const { model, failure } = useChartModel(bars, computations);
  const active =
    !hasStateContent && bars.length > 0 && failure === null && model !== null;
  const containerRef = useFinancialChart({
    model: model ?? EMPTY_MODEL,
    theme,
    onHover: setHover,
    onLayout: setPaneLayouts,
    active,
    onNearLeftEdge,
  });
  const lastActivePanesRef = useRef<ChartModel["panes"]>([]);
  useLayoutEffect(() => {
    if (active && model !== null) {
      lastActivePanesRef.current = model.panes;
    }
  }, [active, model]);
  const heightModel =
    active && model !== null
      ? model
      : {
          ...(model ?? EMPTY_MODEL),
          panes:
            lastActivePanesRef.current.length > 0
              ? lastActivePanesRef.current
              : (model ?? EMPTY_MODEL).panes,
        };

  const latestBar = bars.length === 0 ? null : bars[bars.length - 1];
  const onActiveTimeChangeRef = useRef(onActiveTimeChange);
  onActiveTimeChangeRef.current = onActiveTimeChange;
  const dataIdentity = `${symbol}\u0000${timeframe}`;
  const previousIdentityRef = useRef(dataIdentity);
  const identityMatches = previousIdentityRef.current === dataIdentity;
  useEffect(() => {
    previousIdentityRef.current = dataIdentity;
    setHover(null);
  }, [active, dataIdentity]);
  const visibleHover = active && identityMatches ? hover : null;
  const activeBar = visibleHover ?? latestBar;
  const activeTime = active && activeBar !== null ? activeBar.time : null;

  useEffect(() => {
    onActiveTimeChangeRef.current?.(activeTime);
  }, [activeTime]);
  const renderLegend = (paneId?: string): ReactNode =>
    renderIndicatorLegend === undefined
      ? null
      : renderIndicatorLegend({
          hovered: visibleHover,
          latestBar,
          activeTime,
          paneId,
        });

  const mainLegend = renderLegend("main");

  const inactiveContent = hasStateContent ? (
    stateContent
  ) : failure !== null ? (
    <Alert
      type="error"
      showIcon
      title="K 线数据无法绘制"
      description={failure}
    />
  ) : (
      <Empty
        description="当前区间没有可显示的 K 线数据。"
        style={{ padding: 48 }}
      />
    );

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {!active || model === null || model.issues.length === 0 ? null : (
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
      {!active || model === null || model.warnings.length === 0 ? null : (
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
        style={{
          position: "relative",
          width: "100%",
          background: theme.surface,
          borderRadius: 4,
          border: `1px solid ${theme.border}`,
          // Absolute tooltips must never widen the document; they are
          // clamped inside the card instead of creating page scrollbars.
          overflow: "hidden",
        }}
        data-testid="financial-chart"
      >
        {toolbar === undefined ? null : (
          <div
            data-testid="financial-chart-toolbar"
            style={{ borderBottom: `1px solid ${theme.border}` }}
          >
            {toolbar}
          </div>
        )}
        <div
          data-testid="financial-chart-canvas"
          style={{
            position: "relative",
            width: "100%",
            display: "flex",
            flexDirection: "column",
            "--chart-height": getChartHeight(computations, heightModel),
            height: "var(--chart-height)",
          } as CSSProperties}
        >
          {active || hasLoadingContent ? (
            <div
              data-testid="financial-chart-info"
              style={{ flex: "0 0 auto", position: "relative", zIndex: 3 }}
            >
              {hasLoadingContent ? (
                <div
                  data-testid="financial-chart-loading"
                  style={{
                    position: "relative",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    height: 48,
                    color: theme.textSecondary,
                    fontSize: 12,
                    pointerEvents: "none",
                  }}
                >
                  {loadingContent}
                </div>
              ) : (
                <ChartHeader
                  symbol={symbol}
                  timeframe={timeframe}
                  bar={activeBar}
                  hovering={visibleHover !== null}
                  theme={theme}
                />
              )}
              {mainLegend === null ? null : (
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 8,
                    padding: "0 12px 8px",
                    pointerEvents: "none",
                  }}
                >
                  {mainLegend}
                </div>
              )}
            </div>
          ) : null}
          <div
            ref={measured.ref}
            data-testid="financial-chart-plot"
            style={{ position: "relative", flex: "1 1 auto", minHeight: 0 }}
          >
            <div
              ref={containerRef}
              style={{
                position: "absolute",
                inset: 0,
                visibility: active ? "visible" : "hidden",
              }}
              aria-hidden="true"
            />
            {active ? (
              <>
                {paneLayouts.map((pane) => (
                  <div
                    key={pane.key}
                    data-testid={`indicator-pane-legend-${pane.key}`}
                    style={{
                      position: "absolute",
                      top: pane.top + (pane.height < 8 ? 0 : 2),
                      transform: `scale(${Math.min(
                        1,
                        Math.max(0.1, (pane.height - 4) / 40),
                      )})`,
                      transformOrigin: "top left",
                      left: 12,
                      right: 12,
                      zIndex: 3,
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 8,
                      pointerEvents: "none",
                    }}
                  >
                    {renderLegend(pane.key)}
                  </div>
                ))}
                {visibleHover === null ? null : (
                  <ChartTooltip
                    hover={visibleHover}
                    theme={theme}
                    containerWidth={measured.width}
                    containerHeight={measured.height}
                  />
                )}
              </>
            ) : (
              inactiveContent
            )}
          </div>
        </div>
      </div>
      {!active || model === null ? null : (
        <>
          <ChartSummaryRegion model={model} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            上涨为红色、下跌为绿色；颜色对比度已按 CVD 可读性校验。
          </Typography.Text>
        </>
      )}
    </Space>
  );
}
