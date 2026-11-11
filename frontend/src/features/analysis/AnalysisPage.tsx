import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { Alert, Empty, Space, Spin, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorState } from "../../components/ErrorState";
import { getBars, listIndicators, listInstruments } from "../../api/endpoints";

import type { JsonObject } from "../../types/api";
import type { BarDTO } from "../../types/market";
import { IndicatorEditor } from "./IndicatorEditor";
import { IndicatorPicker } from "./IndicatorPicker";
import { ChartToolbar } from "./ChartToolbar";
import { useAnalysisSession } from "./AnalysisSession";
import { IndicatorLegend, type IndicatorLegendItem } from "../../charts/IndicatorLegend";
import { getChartTheme } from "../../charts/theme";
import {
  addInstance,
  describeInstance,
  removeInstance,
  updateInstanceParams,
  type ActiveIndicatorInstance,
} from "./indicatorInstances";
import { SEARCH_DEBOUNCE_MS } from "./InstrumentSelector";
import { useIndicatorComputation } from "./useIndicatorComputation";

const FinancialChart = lazy(() =>
  import("../../charts/FinancialChart").then((module) => ({
    default: module.FinancialChart,
  })),
);

const BAR_PAGE_SIZE = 1000;

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

type AnalysisLegendItem = IndicatorLegendItem & { paneId: string };

function legendsForPane(
  items: readonly AnalysisLegendItem[],
  paneId?: string,
): readonly AnalysisLegendItem[] {
  if (paneId === undefined) {
    return items;
  }
  return items.filter((item) => {
    if (paneId === "main") {
      return item.paneId === "main" || !item.visible || item.error !== null;
    }
    return item.visible && item.error === null && item.paneId === paneId;
  });
}

export function AnalysisPage() {
  const {
    search,
    setSearch,
    instrument,
    setInstrument,
    timeframe,
    setTimeframe,
    instances,
    setInstances,
    hiddenInstances,
    setHiddenInstances,
  } = useAnalysisSession();
  const debouncedSearch = useDebounced(search, SEARCH_DEBOUNCE_MS);
  const [olderBars, setOlderBars] = useState<BarDTO[]>([]);
  const [exhausted, setExhausted] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [pagingError, setPagingError] = useState<string | null>(null);
  const [activeTime, setActiveTime] = useState<string | null>(null);
  const inFlight = useRef(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [editing, setEditing] = useState<ActiveIndicatorInstance | null>(null);

  const instrumentsQuery = useQuery({
    queryKey: ["instruments", debouncedSearch],
    retry: false,
    queryFn: async () =>
      (await listInstruments({ query: debouncedSearch || undefined, limit: 20 }))
        .data,
  });

  const descriptorsQuery = useQuery({
    queryKey: ["indicator-descriptors"],
    retry: false,
    queryFn: async () => (await listIndicators()).data,
  });

  const instrumentId = instrument?.id ?? null;
  const barsQuery = useQuery({
    queryKey: ["bars", instrumentId, timeframe, BAR_PAGE_SIZE],
    enabled: instrumentId !== null,
    retry: false,
    queryFn: async () =>
      (
        await getBars({
          instrument_id: instrumentId as number,
          timeframe,
          limit: BAR_PAGE_SIZE,
        })
      ).data,
  });

  const latestBars = useMemo(
    () => barsQuery.data ?? [],
    [barsQuery.data],
  );
  const loadedBars = useMemo(() => {
    const byTime = new Map<string, BarDTO>();
    for (const bar of olderBars) {
      byTime.set(bar.time, bar);
    }
    for (const bar of latestBars) {
      byTime.set(bar.time, bar);
    }
    return [...byTime.values()].sort((a, b) => a.time.localeCompare(b.time));
  }, [olderBars, latestBars]);
  const earliestLoaded = loadedBars[0]?.time ?? null;

  // Fresh instrument or timeframe resets accumulated history.
  useEffect(() => {
    setOlderBars([]);
    setExhausted(false);
    setPagingError(null);
  }, [instrumentId, timeframe]);

  useEffect(() => {
    if (barsQuery.isSuccess) {
      setExhausted((barsQuery.data ?? []).length < BAR_PAGE_SIZE);
    }
  }, [barsQuery.isSuccess, barsQuery.data]);

  const loadOlderBars = useCallback(async () => {
    if (
      inFlight.current ||
      exhausted ||
      instrumentId === null ||
      earliestLoaded === null
    ) {
      return;
    }
    inFlight.current = true;
    setLoadingMore(true);
    setPagingError(null);
    try {
      const previous = new Date(earliestLoaded);
      previous.setUTCDate(previous.getUTCDate() - 1);
      const end = previous.toISOString().slice(0, 10);
      const page = (
        await getBars({
          instrument_id: instrumentId,
          timeframe,
          end,
          limit: BAR_PAGE_SIZE,
        })
      ).data;
      setExhausted(page.length < BAR_PAGE_SIZE);
      if (page.length > 0) {
        setOlderBars((current) => {
          const byTime = new Map<string, BarDTO>();
          for (const bar of current) {
            byTime.set(bar.time, bar);
          }
          for (const bar of page) {
            byTime.set(bar.time, bar);
          }
          return [...byTime.values()].sort((a, b) =>
            a.time.localeCompare(b.time),
          );
        });
      }
    } catch (error) {
      setPagingError(
        error instanceof Error ? error.message : "加载更早历史失败。",
      );
    } finally {
      inFlight.current = false;
      setLoadingMore(false);
    }
  }, [earliestLoaded, exhausted, instrumentId, timeframe]);

  const computation = useIndicatorComputation({
    instrumentId,
    timeframe,
    start: earliestLoaded,
    instances,
  });

  const instruments = instrumentsQuery.data ?? [];
  const databasesEmpty =
    instrumentsQuery.isSuccess && instruments.length === 0 && !debouncedSearch;

  const editDescriptor = useMemo(() => {
    if (editing === null) {
      return null;
    }
    return (
      descriptorsQuery.data?.find((item) => item.name === editing.name) ?? null
    );
  }, [descriptorsQuery.data, editing]);

  const handleAdd = (addition: Parameters<typeof addInstance>[1]): void => {
    setInstances((current) => addInstance(current, addition));
    setPickerOpen(false);
  };

  const handleEditSubmit = (params: JsonObject): void => {
    if (editing === null) {
      return;
    }
    setInstances((current) =>
      updateInstanceParams(current, editing.instanceId, params),
    );
    setEditing(null);
  };

  const legendItems: AnalysisLegendItem[] = instances.map((instance) => {
    const result = computation.computations.find(
      (item) => item.instance_id === instance.instanceId,
    );
    const values =
      result === undefined || activeTime === null
        ? []
        : result.series.flatMap((series) => {
            const point = series.points.find(
              (item) => item.time === activeTime,
            );
            return point === undefined || point.value === null
              ? []
              : [
                  {
                    id: series.id,
                    value: point.value,
                    color: series.color ?? "#2962ff",
                  },
                ];
          });
    const paneId =
      result?.panes.find((pane) => pane.id !== "main")?.id ?? "main";
    return {
      instanceId: instance.instanceId,
      paneId,
      label: describeInstance(instance),
      values,
      error: result?.error ?? null,
      visible: !hiddenInstances.has(instance.instanceId),
    };
  });
  const visibleComputations = computation.computations.filter(
    (item) => !hiddenInstances.has(item.instance_id),
  );
  const chartState = databasesEmpty ? (
    <Empty
      description={
        <Space orientation="vertical">
          <Typography.Text strong>本地数据库尚未同步任何证券数据。</Typography.Text>
          <Typography.Text type="secondary">
            请先到「Task 管理」页启用并立即执行证券列表与日线同步任务，
            完成后再回到本页选择股票。
          </Typography.Text>
        </Space>
      }
    />
  ) : instrument === null ? (
    <Empty description="请选择证券以加载 K 线。" />
  ) : barsQuery.error !== null ? (
    <ErrorState
      error={barsQuery.error}
      onRetry={() => {
        void barsQuery.refetch();
      }}
    />
  ) : barsQuery.isPending ? (
    <div style={{ padding: 48, textAlign: "center" }}>
      <Spin />
    </div>
  ) : null;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {computation.error === null ? null : (
        <Alert
          type="error"
          showIcon
          title="指标计算请求失败，已保留 K 线。"
          description={
            computation.error instanceof Error
              ? computation.error.message
              : undefined
          }
        />
      )}
      {pagingError === null ? null : (
        <Alert
          type="error"
          showIcon
          title="加载更早历史失败，K 线与指标已保留。"
          description={pagingError}
        />
      )}
      {loadingMore ? (
        <Alert type="info" showIcon title="正在加载更早的历史…" />
      ) : null}
      {/* Reserved height keeps the chart from jumping when the hint
          disappears after the first indicator is added. */}
      <div style={{ minHeight: 22 }}>
        {chartState === null && instances.length === 0 ? (
          <Typography.Text type="secondary">
            尚未添加指标。点击「添加指标」从后端可用指标中选择。
          </Typography.Text>
        ) : null}
      </div>
      <Suspense fallback={<Spin />}>
        <FinancialChart
          bars={loadedBars}
          computations={visibleComputations}
          symbol={instrument?.symbol ?? ""}
          timeframe={timeframe}
          stateContent={chartState}
          toolbar={
            <ChartToolbar
              instruments={instruments}
              instrumentsLoading={instrumentsQuery.isFetching}
              selectedInstrument={instrument}
              search={search}
              timeframe={timeframe}
              onSearchChange={setSearch}
              onSelectInstrument={setInstrument}
              onTimeframeChange={setTimeframe}
              onAddIndicator={() => setPickerOpen(true)}
            />
          }
          onNearLeftEdge={() => {
            void loadOlderBars();
          }}
          onActiveTimeChange={setActiveTime}
          renderIndicatorLegend={({ paneId }) => (
            <IndicatorLegend
              items={legendsForPane(legendItems, paneId)}
              theme={getChartTheme("dark")}
              onEdit={(instanceId) => {
                const target = instances.find(
                  (item) => item.instanceId === instanceId,
                );
                if (target !== undefined) {
                  setEditing(target);
                }
              }}
              onToggleVisibility={(instanceId) =>
                setHiddenInstances((current) => {
                  const next = new Set(current);
                  if (next.has(instanceId)) {
                    next.delete(instanceId);
                  } else {
                    next.add(instanceId);
                  }
                  return next;
                })
              }
              onRemove={(instanceId) =>
                setInstances((current) =>
                  removeInstance(current, instanceId),
                )
              }
            />
          )}
        />
      </Suspense>
      <IndicatorPicker
        open={pickerOpen}
        descriptors={descriptorsQuery.data ?? []}
        onCancel={() => setPickerOpen(false)}
        onAdd={handleAdd}
      />
      {editing === null ? null : (
        <IndicatorEditor
          instance={editing}
          descriptor={editDescriptor}
          onSubmit={handleEditSubmit}
          onCancel={() => setEditing(null)}
        />
      )}
    </Space>
  );
}
