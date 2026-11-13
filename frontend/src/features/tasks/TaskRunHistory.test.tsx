import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TaskLogDTO, TaskRunDTO } from "../../types/task";
import { TaskRunHistory, type TaskRunHistoryProps } from "./TaskRunHistory";

const RUN: TaskRunDTO = {
  id: 11,
  task_name: "market.sync_crypto_daily",
  trigger: "manual",
  status: "partial",
  params: {},
  config_snapshot: null,
  progress: 100,
  error: "1 of 2 instrument synchronizations failed",
  created_at: "2026-01-08T00:00:00Z",
  started_at: "2026-01-08T00:00:01Z",
  finished_at: "2026-01-08T00:00:09Z",
};

function log(id: number, level: string, message: string, context: TaskLogDTO["context"]): TaskLogDTO {
  return {
    id,
    run_id: RUN.id,
    level,
    message,
    context,
    created_at: "2026-01-08T00:00:09Z",
  };
}

function renderHistory(
  logs: readonly TaskLogDTO[],
  overrides: Partial<TaskRunHistoryProps> = {},
) {
  return render(
    <TaskRunHistory
      runs={[RUN]}
      selectedRunId={RUN.id}
      logs={logs}
      logsLoading={false}
      onSelectRun={vi.fn()}
      onRefresh={vi.fn()}
      runsTotal={25}
      runsPage={1}
      logsTotal={25}
      logsPage={1}
      onRunsPageChange={vi.fn()}
      onLogsPageChange={vi.fn()}
      {...overrides}
    />,
  );
}

describe("TaskRunHistory log presentation", () => {
  it("distinguishes INFO and ERROR tags and shows whitelisted details", () => {
    renderHistory([
      log(1, "INFO", "Instrument synchronization succeeded", {
        run_id: RUN.id,
        symbol: "BINANCE:BTC/USDT",
        bar_count: 11,
      }),
      log(2, "ERROR", "Instrument synchronization failed", {
        run_id: RUN.id,
        universe_code: "nasdaq100",
        error_type: "ProviderUnavailable",
        detail: "CCXT binance OHLCV request failed (NetworkError)",
      }),
      log(3, "WARNING", "Task returned a warning", {}),
    ]);

    expect(screen.getByText("INFO").closest(".ant-tag")).toHaveClass("ant-tag-processing");
    expect(screen.getByText("ERROR").closest(".ant-tag")).toHaveClass("ant-tag-error");
    expect(screen.getByText("WARNING").closest(".ant-tag")).not.toHaveClass("ant-tag-processing");
    expect(screen.getByText("Symbol: BINANCE:BTC/USDT")).toBeInTheDocument();
    expect(screen.getByText("K 线数: 11")).toBeInTheDocument();
    expect(screen.getByText("Universe: nasdaq100")).toBeInTheDocument();
    expect(screen.getByText("错误类型: ProviderUnavailable")).toBeInTheDocument();
    expect(
      screen.getByText("详情: CCXT binance OHLCV request failed (NetworkError)"),
    ).toHaveClass("task-log-detail");
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/run_id/)).not.toBeInTheDocument();
    expect(screen.queryByText(/object Object/)).not.toBeInTheDocument();
  });

  it("provides independent run and log pagination controls", () => {
    const onRunsPageChange = vi.fn();
    const onLogsPageChange = vi.fn();
    renderHistory([], { onRunsPageChange, onLogsPageChange });

    const runsNavigation = screen.getByRole("navigation", { name: "运行批次分页" });
    fireEvent.click(within(runsNavigation).getByRole("button", { name: "Page 2" }));
    expect(onRunsPageChange).toHaveBeenCalledWith(2, 20);

    const logsNavigation = screen.getByRole("navigation", { name: "运行日志分页" });
    fireEvent.click(within(logsNavigation).getByRole("button", { name: "Page 2" }));
    expect(onLogsPageChange).toHaveBeenCalledWith(2, 20);
  });

  it("does not render unknown context fields", () => {
    renderHistory([
      log(4, "ERROR", "Instrument synchronization failed", {
        error_type: "ProviderDataInvalid",
        detail: "Provider response has unexpected Content-Type",
        nested: { secret: "do-not-render" },
      }),
    ]);

    expect(screen.queryByText(/do-not-render/)).not.toBeInTheDocument();
    expect(screen.queryByText(/nested/)).not.toBeInTheDocument();
  });
});
