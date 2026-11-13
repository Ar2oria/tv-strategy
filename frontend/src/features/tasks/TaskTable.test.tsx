import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { taskPayload } from "../../test/apiFixtures";
import type { TaskDescriptor } from "../../types/task";
import { TaskTable } from "./TaskTable";

const TASK = taskPayload as unknown as TaskDescriptor;

function renderTable() {
  const props = {
    tasks: [TASK],
    loading: false,
    busyTask: null,
    selectedTaskName: null,
    onSelect: vi.fn(),
    onConfigure: vi.fn(),
    onRunNow: vi.fn(),
    onToggleEnabled: vi.fn(),
  };
  render(<TaskTable {...props} />);
  return props;
}

describe("TaskTable row activation", () => {
  it("activates a task row instead of showing a separate history button", () => {
    const props = renderTable();

    expect(screen.queryByRole("button", { name: "历史 market.sync" })).not.toBeInTheDocument();
    const row = screen.getByRole("row", { name: "查看历史 market.sync" });
    fireEvent.click(row);
    expect(props.onSelect).toHaveBeenCalledWith(TASK);
    fireEvent.keyDown(row, { key: "Enter" });
    expect(props.onSelect).toHaveBeenCalledTimes(2);
  });

  it("lets nested action controls handle Enter and Space without selecting the row", () => {
    const props = renderTable();
    const configure = screen.getByRole("button", { name: "配置 market.sync" });
    const runNow = screen.getByRole("button", { name: "立即执行 market.sync" });

    fireEvent.keyDown(configure, { key: "Enter" });
    fireEvent.keyDown(runNow, { key: " " });

    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("does not activate the row for configure or immediate-run actions", () => {
    const props = renderTable();

    fireEvent.click(screen.getByRole("button", { name: "配置 market.sync" }));
    fireEvent.click(screen.getByRole("button", { name: "立即执行 market.sync" }));

    expect(props.onConfigure).toHaveBeenCalledWith(TASK);
    expect(props.onRunNow).toHaveBeenCalledWith(TASK);
    expect(props.onSelect).not.toHaveBeenCalled();
  });
});
