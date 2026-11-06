import type { TaskDescriptor, TaskRunDTO } from "../../types/task";

export const ACTIVE_RUN_STATUSES = ["queued", "running"] as const;

export function isActiveRun(status: TaskRunDTO["status"]): boolean {
  return (ACTIVE_RUN_STATUSES as readonly string[]).includes(status);
}

/** Human-readable run status used in tables and status tags. */
export const RUN_STATUS_TEXT: Readonly<Record<TaskRunDTO["status"], string>> = {
  queued: "排队中",
  running: "运行中",
  success: "成功",
  partial: "部分成功",
  failed: "失败",
  skipped: "已跳过",
  interrupted: "已中断",
};

export function latestRun(runs: readonly TaskRunDTO[]): TaskRunDTO | null {
  let newest: TaskRunDTO | null = null;
  for (const run of runs) {
    if (newest === null || run.id > newest.id) {
      newest = run;
    }
  }
  return newest;
}

export function hasActiveRun(runs: readonly TaskRunDTO[]): boolean {
  return runs.some((run) => isActiveRun(run.status));
}

export function formatTimestamp(value: string | null): string {
  if (value === null) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(parsed);
}

export function describeTask(task: TaskDescriptor): string {
  return `${task.display_name} · ${task.name}`;
}
