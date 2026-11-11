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
        <section key={task.name}>
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
            onClick={() => onToggleEnabled(task, !task.enabled)}
          >
            {task.enabled ? "已启用" : "已停用"}
          </button>
          <button
            type="button"
            aria-label={`历史 ${task.name}`}
            onClick={() => onSelect(task)}
          >
            历史
          </button>
          <button
            type="button"
            aria-label={`配置 ${task.name}`}
            onClick={() => onConfigure(task)}
          >
            配置
          </button>
          <button
            type="button"
            aria-label={`立即执行 ${task.name}`}
            disabled={busyTask === task.name}
            onClick={() => onRunNow(task)}
          >
            立即执行
          </button>
        </section>
      ))}
    </div>
  );
}
