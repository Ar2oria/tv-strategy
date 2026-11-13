import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Card, Space } from "antd";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../../api/errors";
import {
  getTaskLogs,
  getTaskRuns,
  listTasks,
  startTaskRun,
  updateTaskConfig,
} from "../../api/endpoints";
import type { JsonObject, ResponseMeta } from "../../types/api";
import type { TaskDescriptor } from "../../types/task";
import { TaskConfigDrawer } from "./TaskConfigDrawer";
import { TaskRunHistory } from "./TaskRunHistory";
import { TaskTable } from "./TaskTable";
import { latestRun } from "./taskRuns";
import { useWorkspaceVisibility } from "../workspace/WorkspaceVisibility";

const RUN_POLL_INTERVAL_MS = 3000;
const PAGE_SIZE = 20;

function totalOf(meta: ResponseMeta): number {
  const total = meta.total;
  return typeof total === "number" && Number.isFinite(total) && total >= 0 ? total : 0;
}

interface SavePayload {
  cron: string;
  enabled: boolean;
  params: JsonObject;
}

function messageFor(error: unknown): string | null {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return "请求过于频繁，请稍后重试。";
    }
    return error.message;
  }
  return error === null ? null : "保存失败，请稍后重试。";
}

export function TasksPage() {
  const queryClient = useQueryClient();
  const [selectedTask, setSelectedTask] = useState<TaskDescriptor | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runsPage, setRunsPage] = useState(1);
  const [logsPage, setLogsPage] = useState(1);
  const [busyTask, setBusyTask] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const tasksQuery = useQuery({
    queryKey: ["tasks"],
    retry: false,
    queryFn: async () => (await listTasks()).data,
  });

  const activeTaskName = selectedTask?.name ?? null;
  const tasksByName = useMemo(
    () => new Map((tasksQuery.data ?? []).map((task) => [task.name, task])),
    [tasksQuery.data],
  );
  const runsQuery = useQuery({
    queryKey: ["task-runs", activeTaskName, runsPage],
    enabled: activeTaskName !== null,
    retry: false,
    queryFn: async () =>
      getTaskRuns(activeTaskName as string, PAGE_SIZE, (runsPage - 1) * PAGE_SIZE),
  });

  const runs = useMemo(() => runsQuery.data?.data ?? [], [runsQuery.data]);
  const runsTotal = totalOf(runsQuery.data?.meta ?? {});
  const workspaceActive = useWorkspaceVisibility();

  const logsQuery = useQuery({
    queryKey: ["task-logs", selectedRunId, logsPage],
    enabled: selectedRunId !== null,
    retry: false,
    queryFn: async () =>
      getTaskLogs(
        selectedRunId as number,
        PAGE_SIZE,
        (logsPage - 1) * PAGE_SIZE,
      ),
  });
  const logsTotal = totalOf(logsQuery.data?.meta ?? {});

  const saveMutation = useMutation({
    mutationFn: async (payload: SavePayload) => {
      if (activeTaskName === null) {
        throw new Error("No task selected");
      }
      // The catalog is the source of truth for the revision: `selectedTask` is
      // a snapshot, so a refresh after another page's write must win, otherwise
      // the next save would be rejected with a stale `expected_revision`.
      const current = tasksByName.get(activeTaskName);
      if (current === undefined) {
        throw new Error("Selected task is no longer registered");
      }
      return updateTaskConfig(current.name, {
        expected_revision: current.revision,
        cron: payload.cron,
        enabled: payload.enabled,
        params: payload.params,
      });
    },
    onSuccess: async (result) => {
      setSaveError(null);
      setConflict(false);
      setSelectedTask(result.data);
      setDrawerOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: async (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(true);
        setSaveError(null);
        const refreshed = await tasksQuery.refetch();
        const fresh = refreshed.data?.find(
          (task) => task.name === selectedTask?.name,
        );
        if (fresh !== undefined) {
          setSelectedTask(fresh);
        }
        return;
      }
      setConflict(false);
      setSaveError(messageFor(error));
    },
  });

  const runMutation = useMutation({
    mutationFn: async (task: TaskDescriptor) => startTaskRun(task.name),
    onMutate: (task) => {
      setBusyTask(task.name);
      setRunError(null);
    },
    onSuccess: (result, task) => {
      // Selecting for history must not re-open the configuration drawer.
      setDrawerOpen(false);
      setSelectedTask(task);
      setSelectedRunId(result.data.id);
      setRunsPage(1);
      setLogsPage(1);
      void queryClient
        .fetchQuery({
          queryKey: ["task-logs", result.data.id, 1],
          queryFn: () => getTaskLogs(result.data.id, PAGE_SIZE, 0),
        })
        .catch(() => undefined);
      void queryClient.invalidateQueries({ queryKey: ["task-runs", task.name] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (error: unknown) => {
      setRunError(messageFor(error));
    },
    onSettled: () => setBusyTask(null),
  });

  const toggleMutation = useMutation({
    mutationFn: async (input: { task: TaskDescriptor; enabled: boolean }) =>
      updateTaskConfig(input.task.name, {
        expected_revision: input.task.revision,
        enabled: input.enabled,
      }),
    onMutate: (input) => setBusyTask(input.task.name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: async (error: unknown) => {
      setRunError(messageFor(error));
      if (error instanceof ApiError && error.status === 409) {
        // The stored config moved on; drop the stale revision before retrying.
        await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      }
    },
    onSettled: () => setBusyTask(null),
  });

  useEffect(() => {
    if (!workspaceActive) {
      return;
    }
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      if (activeTaskName !== null) {
        void queryClient.invalidateQueries({
          queryKey: ["task-runs", activeTaskName],
        });
      }
      if (selectedRunId !== null) {
        void queryClient.invalidateQueries({
          queryKey: ["task-logs", selectedRunId],
        });
      }
    }, RUN_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [activeTaskName, queryClient, selectedRunId, workspaceActive]);

  const tasks = useMemo(() => tasksQuery.data ?? [], [tasksQuery.data]);
  const newestRun = latestRun(runs);

  useEffect(() => {
    if (selectedRunId === null && newestRun !== null) {
      setSelectedRunId(newestRun.id);
      setLogsPage(1);
    }
  }, [newestRun, selectedRunId]);

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {runError === null ? null : (
        <Alert type="error" showIcon title={runError} closable onClose={() => setRunError(null)} />
      )}
      {tasksQuery.error === null ? null : (
        <Alert type="error" showIcon title="任务列表加载失败" />
      )}
      <Card size="small">
        <TaskTable
          tasks={tasks}
          loading={tasksQuery.isFetching}
          busyTask={busyTask}
          selectedTaskName={selectedTask?.name ?? null}
          onSelect={(task) => {
            setSelectedTask(task);
            setSelectedRunId(null);
            setRunsPage(1);
            setLogsPage(1);
          }}
          onConfigure={(task) => {
            setSelectedTask(task);
            setSelectedRunId(null);
            setRunsPage(1);
            setLogsPage(1);
            setDrawerOpen(true);
            setConflict(false);
            setSaveError(null);
          }}
          onRunNow={(task) => runMutation.mutate(task)}
          onToggleEnabled={(task, enabled) =>
            toggleMutation.mutate({ task, enabled })
          }
        />
      </Card>
      {selectedTask === null ? null : (
        <Card size="small" title={`${selectedTask.display_name} 运行历史`}>
          {logsQuery.error === null ? null : (
            <Alert type="error" showIcon title="运行日志加载失败" />
          )}
          <TaskRunHistory
            runs={runs}
            selectedRunId={selectedRunId}
            logs={logsQuery.data?.data ?? []}
            logsLoading={logsQuery.isFetching}
            runsTotal={runsTotal}
            runsPage={runsPage}
            logsTotal={logsTotal}
            logsPage={logsPage}
            onRunsPageChange={(page) => {
              setRunsPage(page);
              setSelectedRunId(null);
              setLogsPage(1);
            }}
            onLogsPageChange={setLogsPage}
            onSelectRun={(run) => {
              setSelectedRunId(run.id);
              setLogsPage(1);
            }}
            onRefresh={() => {
              void runsQuery.refetch();
            }}
          />
        </Card>
      )}
      <TaskConfigDrawer
        task={drawerOpen ? selectedTask : null}
        saving={saveMutation.isPending}
        saveError={saveError}
        conflict={conflict}
        onSave={(payload) => saveMutation.mutate(payload)}
        onClose={() => setDrawerOpen(false)}
      />
    </Space>
  );
}
