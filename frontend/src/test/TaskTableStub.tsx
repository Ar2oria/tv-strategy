import type { TaskTableProps } from "../features/tasks/TaskTable";

/**
 * Lightweight TasksPage test boundary. AntD Table rendering is covered by
 * browser tests; this stub exposes the same user actions without rc-table's
 * resize/motion work under V8-instrumented jsdom.
 */
export function TaskTableStub({
  tasks,
  busyTask,
  onSelect,
  onConfigure,
  onRunNow,
  onToggleEnabled,
}: TaskTableProps) {
  return (
    <div>
      {tasks.map((task) => (
        <section
          key={task.name}
          role="row"
          tabIndex={0}
          aria-label={`查看历史 ${task.name}`}
          onClick={() => onSelect(task)}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) {
              return;
            }
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onSelect(task);
            }
          }}
        >
          <span>{task.display_name}</span>
          <span>{task.description}</span>
          <code>{task.cron}</code>
          <span>
            下次运行 {task.enabled ? (task.next_run_at ?? "—") : "（已停用）"}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={task.enabled}
            aria-label={`启用 ${task.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onToggleEnabled(task, !task.enabled);
            }}
          >
            {task.enabled ? "已启用" : "已停用"}
          </button>
          <button
            type="button"
            aria-label={`配置 ${task.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onConfigure(task);
            }}
          >
            配置
          </button>
          <button
            type="button"
            aria-label={`立即执行 ${task.name}`}
            disabled={busyTask === task.name}
            onClick={(event) => {
              event.stopPropagation();
              onRunNow(task);
            }}
          >
            立即执行
          </button>
        </section>
      ))}
    </div>
  );
}
