import { describe, expect, it } from "vitest";

import type { TaskDescriptor, TaskRunDTO } from "../../types/task";
import {
  describeTask,
  formatTimestamp,
  hasActiveRun,
  isActiveRun,
  latestRun,
  RUN_STATUS_TEXT,
} from "./taskRuns";

function run(overrides: Partial<TaskRunDTO> = {}): TaskRunDTO {
  return {
    id: 1,
    task_name: "market.sync",
    trigger: "manual",
    status: "success",
    params: {},
    config_snapshot: null,
    progress: 100,
    error: null,
    created_at: "2026-01-05T00:00:00Z",
    started_at: "2026-01-05T00:00:01Z",
    finished_at: "2026-01-05T00:00:02Z",
    ...overrides,
  };
}

describe("task run helpers", () => {
  it("treats queued and running as active", () => {
    expect(isActiveRun("queued")).toBe(true);
    expect(isActiveRun("running")).toBe(true);
    expect(isActiveRun("success")).toBe(false);
    expect(isActiveRun("failed")).toBe(false);
  });

  it("detects any active run", () => {
    expect(hasActiveRun([run({ status: "success" })])).toBe(false);
    expect(hasActiveRun([run({ status: "success" }), run({ id: 2, status: "running" })])).toBe(
      true,
    );
    expect(hasActiveRun([])).toBe(false);
  });

  it("returns the newest run by id, not by array order", () => {
    expect(latestRun([])).toBeNull();
    expect(latestRun([run({ id: 7 }), run({ id: 3 })])?.id).toBe(7);
    expect(latestRun([run({ id: 2 }), run({ id: 13 })])?.id).toBe(13);
  });

  it("formats timestamps in UTC and passes through unparseable values", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp("2026-01-05T00:00:00Z")).toContain("2026");
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });

  it("labels every status for the UI", () => {
    expect(RUN_STATUS_TEXT.queued).toBe("排队中");
    expect(RUN_STATUS_TEXT.running).toBe("运行中");
    expect(RUN_STATUS_TEXT.partial).toBe("部分成功");
    expect(RUN_STATUS_TEXT.interrupted).toBe("已中断");
  });

  it("describes a task by display name and unique name", () => {
    const task = {
      name: "market.sync",
      display_name: "Synchronize market",
    } as TaskDescriptor;
    expect(describeTask(task)).toBe("Synchronize market · market.sync");
  });
});
