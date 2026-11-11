import { Empty, Space, Table, Tag, Typography } from "antd";
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

export interface TaskRunHistoryProps {
  runs: readonly TaskRunDTO[];
  selectedRunId: number | null;
  logs: readonly TaskLogDTO[];
  logsLoading: boolean;
  onSelectRun: (run: TaskRunDTO) => void;
  onRefresh: () => void;
}

/** Run history plus the durable logs of the selected run. */
export function TaskRunHistory({
  runs,
  selectedRunId,
  logs,
  logsLoading,
  onSelectRun,
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
        })}
        locale={{ emptyText: <Empty description="还没有运行记录" /> }}
      />
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
            { title: "级别", dataIndex: "level", key: "level", width: 90 },
            { title: "消息", dataIndex: "message", key: "message" },
          ]}
        />
      </div>
    </Space>
  );
}
