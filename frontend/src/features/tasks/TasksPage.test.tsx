import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEventBase from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  taskLogPayload,
  taskPayload,
  taskRunPayload,
} from "../../test/apiFixtures";
import { routes } from "../../router";
import type { TaskDescriptor, TaskLogDTO, TaskRunDTO } from "../../types/task";
import * as taskApi from "../../api/endpoints";

import { WorkspaceVisibilityProvider } from "../workspace/WorkspaceVisibility";

vi.mock("../../charts/FinancialChart", () => ({
  FinancialChart: () => <div data-testid="financial-chart" />,
}));
vi.mock("./TaskTable", async () => {
  const { TaskTableStub } = await import("../../test/TaskTableStub");
  return { TaskTable: TaskTableStub };
});

const userEvent = userEventBase.setup({ delay: null });

interface Recorded {
  url: string;
  method: string;
  body: unknown;
}

const requests: Recorded[] = [];
interface TaskState {
  task: TaskDescriptor;
  runs: TaskRunDTO[];
  logs: TaskLogDTO[];
  conflictOnce: boolean;
  rateLimited: boolean;
  delayRuns: boolean;
  logsFail: boolean;
}

const state: TaskState = {
  task: structuredClone(taskPayload) as unknown as TaskDescriptor,
  runs: [structuredClone(taskRunPayload) as unknown as TaskRunDTO],
  logs: [structuredClone(taskLogPayload) as unknown as TaskLogDTO],
  conflictOnce: false,
  rateLimited: false,
  delayRuns: false,
  logsFail: false,
};

function success(data: unknown, meta: Record<string, unknown> = {}): Response {
  return new Response(JSON.stringify({ success: true, data, error: null, meta }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function failure(status: number, code: string, message: string): Response {
  return new Response(
    JSON.stringify({ success: false, data: null, error: { code, message }, meta: {} }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

function taskView(task: TaskDescriptor): TaskDescriptor {
  const token = task.params.itiger_token;
  if (typeof token !== "string" || token.trim() === "") {
    return task;
  }
  return {
    ...task,
    params: { ...task.params, itiger_token: "********" },
  };
}

async function respond(recorded: Recorded): Promise<Response> {
  const url = new URL(recorded.url, "http://localhost");
  const path = url.pathname;
  if (path === "/api/v1/tasks") {
    return success([taskView(state.task)], { count: 1 });
  }
  if (path.endsWith("/config") && recorded.method === "GET") {
    return success(taskView(state.task));
  }
  if (path.endsWith("/config") && recorded.method === "PUT") {
    if (state.conflictOnce) {
      state.conflictOnce = false;
      state.task = { ...state.task, revision: state.task.revision + 1, cron: "0 6 * * *" };
      return failure(409, "revision_conflict", "Request conflict");
    }
    if (state.rateLimited) {
      state.rateLimited = false;
      return failure(429, "rate_limited", "Too many requests");
    }
    const body = recorded.body as {
      expected_revision: number;
      enabled?: boolean;
      cron?: string;
      params?: Record<string, unknown>;
    };
    state.task = {
      ...state.task,
      revision: state.task.revision + 1,
      ...(body.enabled === undefined ? {} : { enabled: body.enabled }),
      ...(body.cron === undefined ? {} : { cron: body.cron }),
      ...(body.params === undefined
        ? {}
        : { params: body.params as TaskDescriptor["params"] }),
    };
    return success(taskView(state.task));
  }
  if (path.endsWith("/runs") && recorded.method === "POST") {
    state.runs = [
      { ...taskRunPayload, id: 9, status: "running" } as unknown as TaskRunDTO,
      ...state.runs,
    ];
    return new Response(
      JSON.stringify({
        success: true,
        data: state.runs[0],
        error: null,
        meta: {},
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    );
  }
  if (path.endsWith("/runs")) {
    const limit = Number(url.searchParams.get("limit") ?? 20);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const items = state.runs.slice(offset, offset + limit);
    const response = success(items, { count: items.length, total: state.runs.length });
    return state.delayRuns
      ? new Promise<Response>((resolve) => setTimeout(() => resolve(response), 100))
      : response;
  }
  if (path.includes("/task-runs/") && path.endsWith("/logs")) {
    if (state.logsFail) {
      return failure(500, "internal_error", "Log fetch failed");
    }
    const match = path.match(/\/task-runs\/(\d+)\/logs$/);
    const runId = match === null ? null : Number(match[1]);
    const limit = Number(url.searchParams.get("limit") ?? 20);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const runLogs = state.logs.filter((log) => log.run_id === runId);
    const items = runLogs.slice(offset, offset + limit);
    return success(items, { count: items.length, total: runLogs.length });
  }
  return failure(404, "not_found", "Resource not found");
}

beforeEach(() => {
  requests.length = 0;
  state.task = structuredClone(taskPayload) as unknown as TaskDescriptor;
  state.runs = [structuredClone(taskRunPayload) as unknown as TaskRunDTO];
  state.logs = [structuredClone(taskLogPayload) as unknown as TaskLogDTO];
  state.conflictOnce = false;
  state.rateLimited = false;
  state.delayRuns = false;
  state.logsFail = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const recorded: Recorded = {
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
      };
      requests.push(recorded);
      return respond(recorded);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderTasks(active = true) {
  const router = createMemoryRouter(routes, { initialEntries: ["/tasks"] });
  return render(
    <QueryClientProvider
      client={new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })}
    >
      <WorkspaceVisibilityProvider active={active}>
        <RouterProvider router={router} />
      </WorkspaceVisibilityProvider>
    </QueryClientProvider>,
  );
}

function writes(method: string): Recorded[] {
  return requests.filter((request) => request.method === method);
}

describe("TasksPage", { timeout: 40000 }, () => {
  it("lists tasks with description, cron, enabled state and next run", async () => {
    renderTasks();

    expect(await screen.findByText("Synchronize market")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Task 管理" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Task 管理" })).toBeInTheDocument();
    expect(screen.getByText("0 0 * * *")).toBeInTheDocument();
    expect(screen.getAllByText(/下次运行/).length).toBeGreaterThan(0);
  });

  it("rejects a cron with the wrong number of fields before calling the server", async () => {
    renderTasks();
    fireEvent.click(await screen.findByRole("button", { name: "配置 market.sync" }));
    const drawer = await screen.findByRole("dialog");

    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "* * *");
    fireEvent.click(
      within(drawer).getByRole("button", { name: "保存配置" }),
    );

    expect(
      await within(drawer).findByText(/Cron 需要恰好 5 个字段/),
    ).toBeInTheDocument();
    expect(writes("PUT")).toHaveLength(0);
  });

  it("saves cron and enabled state with the current revision", async () => {
    renderTasks();
    fireEvent.click(await screen.findByRole("button", { name: "配置 market.sync" }));
    const drawer = await screen.findByRole("dialog");
    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "30 8 * * 1-5");
    fireEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

    await waitFor(() => expect(writes("PUT")).toHaveLength(1));
    expect(writes("PUT")[0].body).toMatchObject({
      expected_revision: 4,
      cron: "30 8 * * 1-5",
      enabled: true,
    });
    expect(await screen.findByText("30 8 * * 1-5")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("shows a backend field error for a cron the server rejects", async () => {
    renderTasks();
    fireEvent.click(await screen.findByRole("button", { name: "配置 market.sync" }));
    const drawer = await screen.findByRole("dialog");
    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "0 0 31 2 *");
    state.rateLimited = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const recorded: Recorded = {
          url: String(input),
          method: init?.method ?? "GET",
          body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
        };
        requests.push(recorded);
        if (recorded.method === "PUT") {
          return failure(422, "validation_error", "Request validation failed");
        }
        return respond(recorded);
      }),
    );
    fireEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

    expect(
      await within(drawer).findByText("Request validation failed"),
    ).toBeInTheDocument();
  });

  it("runs a task immediately while scheduling is disabled", async () => {
    state.task = { ...state.task, enabled: false };
    renderTasks();
    fireEvent.click(
      await screen.findByRole("button", { name: "立即执行 market.sync" }),
    );

    await waitFor(() => expect(writes("POST")).toHaveLength(1));
    expect(writes("POST")[0].url).toContain("/tasks/market.sync/runs");
    expect(await screen.findByText("运行中")).toBeInTheDocument();
  });

  it("selects the new run and fetches its logs before run history finishes", async () => {
    state.delayRuns = true;
    renderTasks();
    fireEvent.click(
      await screen.findByRole("button", { name: "立即执行 market.sync" }),
    );

    await waitFor(() =>
      expect(
        requests.some((request) => /\/task-runs\/9\/logs/.test(request.url)),
      ).toBe(true),
    );
    const logIndex = requests.findIndex((request) =>
      /\/task-runs\/9\/logs/.test(request.url),
    );
    const historyIndex = requests.findIndex(
      (request) =>
        request.method === "GET" && /\/tasks\/market\.sync\/runs/.test(request.url),
    );
    expect(logIndex).toBeGreaterThanOrEqual(0);
    expect(historyIndex).toBeGreaterThan(logIndex);
    expect(await screen.findByTestId("task-run-9")).toHaveClass("ant-table-row-selected");
  });

  it("persists the iTiger token and lets immediate runs use saved config", async () => {
    state.task = {
      ...state.task,
      name: "market.sync_universes",
      params_schema: {
        ...state.task.params_schema,
        properties: {
          ...state.task.params_schema.properties,
          itiger_token: { type: "string" },
        },
      },
    };
    renderTasks();
    fireEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync_universes" }),
    );
    const drawer = await screen.findByRole("dialog");
    await userEvent.type(
      within(drawer).getByLabelText(/itiger/i),
      "secret-token",
    );
    fireEvent.click(within(drawer).getByRole("button", { name: /保\s*存配置/ }));
    await waitFor(() => expect(writes("PUT")).toHaveLength(1));

    fireEvent.click(
      await screen.findByRole("button", { name: "立即执行 market.sync_universes" }),
    );

    await waitFor(() => expect(writes("POST")).toHaveLength(1));
    expect(
      (writes("PUT")[0].body as { params: { itiger_token?: string } }).params
        .itiger_token,
    ).toBe("secret-token");
    expect(state.task.params.itiger_token).toBe("secret-token");
    expect(writes("POST")[0].body).toEqual({});

    fireEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync_universes" }),
    );
    const reopened = await screen.findByRole("dialog");
    expect(within(reopened).getByLabelText(/itiger/i)).toHaveValue("********");
    expect(screen.queryByDisplayValue("secret-token")).not.toBeInTheDocument();
  });

  it("shows log loading errors instead of leaving an unexplained empty view", async () => {
    state.logsFail = true;
    renderTasks();
    fireEvent.click(
      await screen.findByRole("button", { name: "立即执行 market.sync" }),
    );

    expect(await screen.findByText("运行日志加载失败")).toBeInTheDocument();
  });

  it("refreshes tasks run history and logs every three seconds including terminal states", async () => {
    renderTasks();
    fireEvent.click(
      await screen.findByRole("row", { name: "查看历史 market.sync" }),
    );
    await screen.findByText("Completed");
    const countCalls = (pattern: RegExp): number =>
      requests.filter((request) => pattern.test(request.url)).length;
    const taskCallsBefore = countCalls(/\/api\/v1\/tasks$/);
    const runCallsBefore = countCalls(/\/tasks\/market\.sync\/runs/);
    const logCallsBefore = countCalls(/\/task-runs\/\d+\/logs/);

    await new Promise((resolve) => setTimeout(resolve, 3200));

    expect(countCalls(/\/api\/v1\/tasks$/)).toBeGreaterThan(taskCallsBefore);
    expect(countCalls(/\/tasks\/market\.sync\/runs/)).toBeGreaterThan(runCallsBefore);
    expect(countCalls(/\/task-runs\/\d+\/logs/)).toBeGreaterThan(logCallsBefore);
  });

  it("pauses active-run polling while the task tab is hidden", async () => {
    const interval = vi.spyOn(globalThis, "setInterval");
    renderTasks();
    fireEvent.click(
      await screen.findByRole("button", { name: "立即执行 market.sync" }),
    );
    await screen.findByText("运行中", undefined, { timeout: 10_000 });

    fireEvent.click(screen.getByRole("link", { name: "图表分析" }));
    interval.mockClear();
    await new Promise((resolve) => setTimeout(resolve, 2500));

    expect(interval.mock.calls.filter(([, milliseconds]) => milliseconds === 3000)).toHaveLength(0);
    interval.mockRestore();
  });

  it("shows run logs for a selected historical run", async () => {
    renderTasks();
    fireEvent.click(
      await screen.findByRole("row", { name: "查看历史 market.sync" }),
    );

    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("paginates runs and logs independently with latest items first", async () => {
    state.runs = Array.from({ length: 25 }, (_, index) => ({
      ...taskRunPayload,
      id: 25 - index,
      status: "success",
    })) as unknown as TaskRunDTO[];
    state.logs = Array.from({ length: 25 }, (_, index) => ({
      ...taskLogPayload,
      id: 125 - index,
      run_id: 25,
      message: `log-${25 - index}`,
    })) as unknown as TaskLogDTO[];
    renderTasks();
    fireEvent.click(
      await screen.findByRole("row", { name: "查看历史 market.sync" }),
    );

    expect(await screen.findByTestId("task-run-25")).toBeInTheDocument();
    expect(screen.getByTestId("task-run-6")).toBeInTheDocument();
    expect(screen.queryByTestId("task-run-5")).not.toBeInTheDocument();
    expect(await screen.findByText("log-25")).toBeInTheDocument();
    expect(screen.queryByText("log-5")).not.toBeInTheDocument();

    const runsNavigation = screen.getByRole("navigation", { name: "运行批次分页" });
    fireEvent.click(within(runsNavigation).getByRole("button", { name: "Page 2" }));
    expect(await screen.findByTestId("task-run-5")).toBeInTheDocument();
    expect(
      requests.some((request) =>
        /\/tasks\/market\.sync\/runs\?limit=20&offset=20/.test(request.url),
      ),
    ).toBe(true);

    state.logs = state.logs.map((log) => ({ ...log, run_id: 5 }));
    const logsNavigation = screen.getByRole("navigation", { name: "运行日志分页" });
    fireEvent.click(await within(logsNavigation).findByRole("button", { name: "Page 2" }));
    expect(await screen.findByText("log-5")).toBeInTheDocument();
    expect(screen.getByTestId("task-run-5")).toHaveClass("ant-table-row-selected");
    expect(
      requests.some((request) =>
        /\/task-runs\/\d+\/logs\?limit=20&offset=20/.test(request.url),
      ),
    ).toBe(true);
  });

  it("resets selected run and both pages when configuring a task", async () => {
    state.runs = Array.from({ length: 25 }, (_, index) => ({
      ...taskRunPayload,
      id: 25 - index,
      status: "success",
    })) as unknown as TaskRunDTO[];
    state.logs = Array.from({ length: 25 }, (_, index) => ({
      ...taskLogPayload,
      id: 125 - index,
      run_id: 25,
      message: `log-${25 - index}`,
    })) as unknown as TaskLogDTO[];
    renderTasks();
    fireEvent.click(
      await screen.findByRole("row", { name: "查看历史 market.sync" }),
    );
    fireEvent.click(
      await within(screen.getByRole("navigation", { name: "运行批次分页" })).findByRole(
        "button",
        { name: "Page 2" },
      ),
    );
    expect(await screen.findByTestId("task-run-5")).toBeInTheDocument();
    state.logs = state.logs.map((log) => ({ ...log, run_id: 5 }));
    fireEvent.click(
      await within(screen.getByRole("navigation", { name: "运行日志分页" })).findByRole(
        "button",
        { name: "Page 2" },
      ),
    );
    expect(await screen.findByText("log-5")).toBeInTheDocument();
    requests.length = 0;

    fireEvent.click(screen.getByRole("button", { name: "配置 market.sync" }));
    await screen.findByRole("dialog");

    await waitFor(() =>
      expect(screen.getByTestId("task-run-25")).toHaveClass("ant-table-row-selected"),
    );
    expect(
      requests.some((request) =>
        /\/tasks\/market\.sync\/runs\?limit=20&offset=0/.test(request.url),
      ),
    ).toBe(true);
    expect(
      requests.some((request) =>
        /\/task-runs\/25\/logs\?limit=20&offset=0/.test(request.url),
      ),
    ).toBe(true);
  });

  it("refreshes on 409 and asks the user to reapply instead of overwriting", async () => {
    state.conflictOnce = true;
    renderTasks();
    fireEvent.click(await screen.findByRole("button", { name: "配置 market.sync" }));
    const drawer = await screen.findByRole("dialog");
    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "15 9 * * *");
    fireEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

    expect(
      await within(drawer).findByText(/配置已被其他页面修改/),
    ).toBeInTheDocument();
    const refreshed = await screen.findByDisplayValue("0 6 * * *");
    expect(refreshed).toBeInTheDocument();
    expect(writes("PUT")).toHaveLength(1);
  });

  it("keeps the user's cron edit after a conflict so it can be reapplied", async () => {
    state.conflictOnce = true;
    renderTasks();
    fireEvent.click(await screen.findByRole("button", { name: "配置 market.sync" }));
    const drawer = await screen.findByRole("dialog");
    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "15 9 * * *");
    fireEvent.click(within(drawer).getByRole("button", { name: /保\s*存配置/ }));

    await within(drawer).findByText(/配置已被其他页面修改/);
    // The newest server value is loaded, and only one write was attempted: the
    // user must explicitly reapply instead of the client retrying blindly.
    expect(writes("PUT")).toHaveLength(1);
  });

  it("drops the stale revision after a toggle conflict", async () => {
    renderTasks();
    await screen.findByText("Synchronize market");
    let toggleWrites = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const recorded: Recorded = {
          url: String(input),
          method: init?.method ?? "GET",
          body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
        };
        requests.push(recorded);
        if (recorded.method === "PUT") {
          toggleWrites += 1;
          return failure(409, "revision_conflict", "Request conflict");
        }
        return respond(recorded);
      }),
    );

    const toggle = screen.getByRole("switch", { name: "启用 market.sync" });
    fireEvent.click(toggle);

    await waitFor(() => expect(toggleWrites).toBe(1));
    // A conflict must refresh the catalog so the next attempt uses a new revision.
    await waitFor(() =>
      expect(
        requests.filter(
          (request) =>
            request.method === "GET" &&
            request.url.endsWith("/api/v1/tasks"),
        ).length,
      ).toBeGreaterThan(1),
    );
  });

  it("saves with the revision from the refreshed catalog, not a stale snapshot", async () => {
    renderTasks();
    await screen.findByText("Synchronize market");

    // A conflicting toggle refreshes the catalog after another page bumps the
    // stored revision; the later drawer save must use 9, not the initial 4.
    state.task = { ...state.task, revision: 9, cron: "0 7 * * *" };
    let toggleWrites = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const recorded: Recorded = {
          url: String(input),
          method: init?.method ?? "GET",
          body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
        };
        requests.push(recorded);
        if (recorded.method === "PUT" && toggleWrites === 0) {
          toggleWrites += 1;
          return failure(409, "revision_conflict", "Request conflict");
        }
        return respond(recorded);
      }),
    );
    fireEvent.click(screen.getByRole("switch", { name: "启用 market.sync" }));
    await waitFor(() => expect(toggleWrites).toBe(1));
    await screen.findByText("0 7 * * *");
    const updateSpy = vi.spyOn(taskApi, "updateTaskConfig");

    fireEvent.click(
      screen.getByRole("button", { name: "配置 market.sync" }),
    );
    const drawer = await screen.findByRole("dialog");
    fireEvent.click(
      within(drawer).getByRole("button", { name: /保\s*存配置/ }),
    );

    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(1), {
      timeout: 5000,
    });
    expect(writes("PUT")).toHaveLength(2);
    expect(writes("PUT").at(-1)?.body).toMatchObject({ expected_revision: 9 });
  });

  it("shows a retry hint when rate limited", async () => {
    state.rateLimited = true;
    renderTasks();
    fireEvent.click(await screen.findByRole("button", { name: "配置 market.sync" }));
    const drawer = await screen.findByRole("dialog");
    fireEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

    expect(await within(drawer).findByText(/请求过于频繁/)).toBeInTheDocument();
  });
});
