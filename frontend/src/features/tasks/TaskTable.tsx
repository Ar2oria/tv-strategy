import { Button, Space, Switch, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { TaskDescriptor, TaskRunDTO } from "../../types/task";
import { formatTimestamp, RUN_STATUS_TEXT } from "./taskRuns";

export interface TaskTableProps {
  tasks: readonly TaskDescriptor[];
  loading: boolean;
  busyTask: string | null;
  selectedTaskName: string | null;
  onSelect: (task: TaskDescriptor) => void;
  onConfigure: (task: TaskDescriptor) => void;
  onRunNow: (task: TaskDescriptor) => void;
  onToggleEnabled: (task: TaskDescriptor, enabled: boolean) => void;
}

function statusOf(run: TaskRunDTO | null): React.ReactNode {
  if (run === null) {
    return <Typography.Text type="secondary">从未运行</Typography.Text>;
  }
  const colors: Record<TaskRunDTO["status"], string> = {
    queued: "default",
    running: "processing",
    success: "success",
    partial: "warning",
    failed: "error",
    skipped: "default",
    interrupted: "warning",
  };
  return <Tag color={colors[run.status]}>{RUN_STATUS_TEXT[run.status]}</Tag>;
}

/** Task catalog: schedule state, last outcome, and one-click actions. */
export function TaskTable({
  tasks,
  loading,
  busyTask,
  selectedTaskName,
  onSelect,
  onConfigure,
  onRunNow,
  onToggleEnabled,
}: TaskTableProps) {
  const columns: ColumnsType<TaskDescriptor> = [
    {
      title: "任务",
      key: "task",
      render: (_, task) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text strong>{task.display_name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {task.name}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {task.description}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "Cron",
      dataIndex: "cron",
      key: "cron",
      render: (cron: string) => <code>{cron}</code>,
    },
    {
      title: "启用",
      key: "enabled",
      render: (_, task) => (
        <span onClick={(event) => event.stopPropagation()}>
          <Switch
            aria-label={`启用 ${task.name}`}
            checked={task.enabled}
            loading={busyTask === task.name}
            onChange={(checked) => onToggleEnabled(task, checked)}
          />
        </span>
      ),
    },
    {
      title: "上次运行",
      key: "lastRun",
      render: (_, task) => (
        <Space orientation="vertical" size={0}>
          {statusOf(task.last_run)}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {formatTimestamp(task.last_run?.finished_at ?? null)}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "下次运行",
      key: "nextRun",
      render: (_, task) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          下次运行 {task.enabled ? formatTimestamp(task.next_run_at) : "（已停用）"}
        </Typography.Text>
      ),
    },
    {
      title: "操作",
      key: "actions",
      render: (_, task) => (
        <Space wrap>
          <Button
            size="small"
            aria-label={`配置 ${task.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onConfigure(task);
            }}
          >
            配置
          </Button>
          <Button
            size="small"
            type="primary"
            aria-label={`立即执行 ${task.name}`}
            loading={busyTask === task.name}
            onClick={(event) => {
              event.stopPropagation();
              onRunNow(task);
            }}
          >
            立即执行
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Table
      rowKey="name"
      size="small"
      loading={loading}
      dataSource={[...tasks]}
      columns={columns}
      scroll={{ x: "max-content" }}
      pagination={false}
      rowClassName={(task) =>
        task.name === selectedTaskName ? "ant-table-row-selected" : ""
      }
      onRow={(task) => ({
        onClick: () => onSelect(task),
        onKeyDown: (event) => {
          if (event.target !== event.currentTarget) {
            return;
          }
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect(task);
          }
        },
        tabIndex: 0,
        role: "row",
        "aria-label": `查看历史 ${task.name}`,
      })}
    />
  );
}
