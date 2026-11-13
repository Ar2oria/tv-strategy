import { Empty, Pagination, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { TaskLogDTO, TaskRunDTO } from "../../types/task";
import { formatTimestamp, RUN_STATUS_TEXT } from "./taskRuns";

const STATUS_COLORS: Record<TaskRunDTO["status"], string> = {
  queued: "default",
  running: "processing",
  success: "success",
  partial: "warning",
  failed: "error",
  skipped: "default",
  interrupted: "warning",
};

const LOG_LEVEL_COLORS: Readonly<Record<string, string>> = {
  INFO: "processing",
  ERROR: "error",
};

const PAGE_SIZE = 20;

function textDetail(value: unknown, label: string): string | null {
  return typeof value === "string" && value.trim() !== ""
    ? `${label}: ${value}`
    : null;
}

function logDetails(log: TaskLogDTO): readonly string[] {
  const { context } = log;
  const barCount = context.bar_count;
  return [
    textDetail(context.symbol, "Symbol"),
    textDetail(context.universe_code, "Universe"),
    textDetail(context.error_type, "错误类型"),
    textDetail(context.detail, "详情"),
    typeof barCount === "number" && Number.isFinite(barCount)
      ? `K 线数: ${barCount}`
      : null,
  ].filter((detail): detail is string => detail !== null);
}

function TaskLogMessage({ log }: { log: TaskLogDTO }) {
  const details = logDetails(log);
  return (
    <Space orientation="vertical" size={2}>
      <Typography.Text>{log.message}</Typography.Text>
      {details.length === 0 ? (
        <Typography.Text type="secondary">—</Typography.Text>
      ) : (
        details.map((detail, index) => (
          <Typography.Text
            key={`${index}-${detail}`}
            type="secondary"
            className={detail.startsWith("详情:") ? "task-log-detail" : undefined}
          >
            {detail}
          </Typography.Text>
        ))
      )}
    </Space>
  );
}

export interface TaskRunHistoryProps {
  runs: readonly TaskRunDTO[];
  selectedRunId: number | null;
  logs: readonly TaskLogDTO[];
  logsLoading: boolean;
  onSelectRun: (run: TaskRunDTO) => void;
  onRefresh: () => void;
  runsTotal: number;
  runsPage: number;
  logsTotal: number;
  logsPage: number;
  onRunsPageChange: (page: number) => void;
  onLogsPageChange: (page: number) => void;
}

/** Run history plus the durable logs of the selected run. */
export function TaskRunHistory({
  runs,
  selectedRunId,
  logs,
  logsLoading,
  onSelectRun,
  runsTotal,
  runsPage,
  logsTotal,
  logsPage,
  onRunsPageChange,
  onLogsPageChange,
}: TaskRunHistoryProps) {
  const columns: ColumnsType<TaskRunDTO> = [
    { title: "运行", dataIndex: "id", key: "id", width: 80 },
    {
      title: "触发",
      dataIndex: "trigger",
      key: "trigger",
      render: (trigger: TaskRunDTO["trigger"]) =>
        trigger === "manual" ? "手动" : "定时",
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (status: TaskRunDTO["status"]) => (
        <Tag color={STATUS_COLORS[status]}>{RUN_STATUS_TEXT[status]}</Tag>
      ),
    },
    {
      title: "开始",
      dataIndex: "started_at",
      key: "started_at",
      render: (value: string | null) => formatTimestamp(value),
    },
    {
      title: "结束",
      dataIndex: "finished_at",
      key: "finished_at",
      render: (value: string | null) => formatTimestamp(value),
    },
  ];

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Table
        rowKey="id"
        size="small"
        dataSource={[...runs]}
        columns={columns}
        scroll={{ x: "max-content" }}
        pagination={false}
        rowClassName={(run) => (run.id === selectedRunId ? "ant-table-row-selected" : "")}
        onRow={(run) => ({
          onClick: () => onSelectRun(run),
          style: { cursor: "pointer" },
          "data-testid": `task-run-${run.id}`,
        })}
        locale={{ emptyText: <Empty description="还没有运行记录" /> }}
      />
      <nav aria-label="运行批次分页" style={{ display: "flex", justifyContent: "flex-end" }}>
        <Pagination
          size="small"
          current={runsPage}
          pageSize={PAGE_SIZE}
          total={runsTotal}
          showSizeChanger={false}
          onChange={onRunsPageChange}
        />
      </nav>
      <div>
        <Typography.Text strong>运行日志</Typography.Text>
        <Table
          style={{ marginTop: 8 }}
          rowKey="id"
          size="small"
          loading={logsLoading}
          dataSource={[...logs]}
          scroll={{ x: "max-content" }}
          pagination={false}
          locale={{ emptyText: <Empty description="选择一条运行记录查看日志" /> }}
          columns={[
            { title: "时间", dataIndex: "created_at", key: "created_at", render: formatTimestamp },
            {
              title: "级别",
              dataIndex: "level",
              key: "level",
              width: 90,
              render: (level: string) => (
                <Tag color={LOG_LEVEL_COLORS[level] ?? "default"}>{level}</Tag>
              ),
            },
            {
              title: "消息",
              dataIndex: "message",
              key: "message",
              render: (_: string, log) => <TaskLogMessage log={log} />,
            },
          ]}
        />
        <nav
          aria-label="运行日志分页"
          style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}
        >
          <Pagination
            size="small"
            current={logsPage}
            pageSize={PAGE_SIZE}
            total={logsTotal}
            showSizeChanger={false}
            onChange={onLogsPageChange}
          />
        </nav>
      </div>
    </Space>
  );
}
