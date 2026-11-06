import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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
}

const state: TaskState = {
  task: structuredClone(taskPayload) as unknown as TaskDescriptor,
  runs: [structuredClone(taskRunPayload) as unknown as TaskRunDTO],
  logs: [structuredClone(taskLogPayload) as unknown as TaskLogDTO],
  conflictOnce: false,
  rateLimited: false,
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

function respond(recorded: Recorded): Response {
  const url = new URL(recorded.url, "http://localhost");
  const path = url.pathname;
  if (path === "/api/v1/tasks") {
    return success([state.task], { count: 1 });
  }
  if (path.endsWith("/config") && recorded.method === "GET") {
    return success(state.task);
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
    return success(state.task);
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
    return success(state.runs, { count: state.runs.length });
  }
  if (path.includes("/task-runs/") && path.endsWith("/logs")) {
    return success(state.logs, { count: state.logs.length });
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

function renderTasks() {
  const router = createMemoryRouter(routes, { initialEntries: ["/tasks"] });
  return render(
    <QueryClientProvider
      client={new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })}
    >
      <RouterProvider router={router} />
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
    expect(screen.getByText("0 0 * * *")).toBeInTheDocument();
    expect(screen.getAllByText(/下次运行/).length).toBeGreaterThan(0);
  });

  it("rejects a cron with the wrong number of fields before calling the server", async () => {
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync" }),
    );
    const drawer = await screen.findByRole("dialog");

    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "* * *");
    await userEvent.click(
      within(drawer).getByRole("button", { name: "保存配置" }),
    );

    expect(
      await within(drawer).findByText(/Cron 需要恰好 5 个字段/),
    ).toBeInTheDocument();
    expect(writes("PUT")).toHaveLength(0);
  });

  it("saves cron and enabled state with the current revision", async () => {
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync" }),
    );
    const drawer = await screen.findByRole("dialog");
    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "30 8 * * 1-5");
    await userEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

    await waitFor(() => expect(writes("PUT")).toHaveLength(1));
    expect(writes("PUT")[0].body).toMatchObject({
      expected_revision: 4,
      cron: "30 8 * * 1-5",
      enabled: true,
    });
    expect(await screen.findByText("30 8 * * 1-5")).toBeInTheDocument();
  });

  it("shows a backend field error for a cron the server rejects", async () => {
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync" }),
    );
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
    await userEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

    expect(
      await within(drawer).findByText("Request validation failed"),
    ).toBeInTheDocument();
  });

  it("runs a task immediately while scheduling is disabled", async () => {
    state.task = { ...state.task, enabled: false };
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "立即执行 market.sync" }),
    );

    await waitFor(() => expect(writes("POST")).toHaveLength(1));
    expect(writes("POST")[0].url).toContain("/tasks/market.sync/runs");
    expect(await screen.findByText("运行中")).toBeInTheDocument();
  });

  it("polls run history while a run is active and stops on a terminal state", async () => {
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "立即执行 market.sync" }),
    );
    await screen.findByText("运行中");

    const historyCallsBefore = requests.filter((request) =>
      /\/tasks\/market\.sync\/runs$/.test(new URL(request.url, "http://x").pathname),
    ).length;

    state.runs = [
      { ...taskRunPayload, id: 9, status: "success" } as unknown as TaskRunDTO,
      ...state.runs,
    ];

    await waitFor(
      () => {
        const historyCalls = requests.filter((request) =>
          /\/tasks\/market\.sync\/runs$/.test(
            new URL(request.url, "http://x").pathname,
          ),
        ).length;
        expect(historyCalls).toBeGreaterThan(historyCallsBefore);
      },
      { timeout: 10000 },
    );

    const settled = requests.filter((request) =>
      /\/tasks\/market\.sync\/runs$/.test(new URL(request.url, "http://x").pathname),
    ).length;
    await new Promise((resolve) => setTimeout(resolve, 1200));
    const after = requests.filter((request) =>
      /\/tasks\/market\.sync\/runs$/.test(new URL(request.url, "http://x").pathname),
    ).length;
    expect(after).toBe(settled);
  });

  it("shows run logs for a selected historical run", async () => {
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "历史 market.sync" }),
    );

    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("refreshes on 409 and asks the user to reapply instead of overwriting", async () => {
    state.conflictOnce = true;
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync" }),
    );
    const drawer = await screen.findByRole("dialog");
    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "15 9 * * *");
    await userEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

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
    await userEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync" }),
    );
    const drawer = await screen.findByRole("dialog");
    const cronInput = within(drawer).getByLabelText("Cron 表达式");
    await userEvent.clear(cronInput);
    await userEvent.type(cronInput, "15 9 * * *");
    await userEvent.click(within(drawer).getByRole("button", { name: /保\s*存配置/ }));

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
    await userEvent.click(toggle);

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

    // Another page bumps the stored revision; an immediate run refetches the
    // catalog so the later save must use revision 9, not the initial 4.
    state.task = { ...state.task, revision: 9, cron: "0 7 * * *" };
    await userEvent.click(
      screen.getByRole("button", { name: "立即执行 market.sync" }),
    );
    await waitFor(
      () => expect(screen.getByText("0 7 * * *")).toBeInTheDocument(),
      { timeout: 5000 },
    );
    // The queued run must reach a terminal state so run-history polling
    // stops; constant polling re-renders keep the row unstable for
    // userEvent under coverage instrumentation.
    state.runs = state.runs.map((run) =>
      run.id === 9 ? { ...run, status: "success" } : run,
    );
    process.stderr.write("FLIPPED\n");
    await waitFor(
      () => expect(screen.getAllByText("成功").length).toBeGreaterThan(0),
      { timeout: 5000 },
    ).catch(() => process.stderr.write("SUCCESS-WAIT-TIMEOUT\n"));
    process.stderr.write("TERMINAL seen\n");

    process.stderr.write("PRE-CONFIGURE\n");
    await userEvent.click(
      screen.getByRole("button", { name: "配置 market.sync" }),
    );
    process.stderr.write("CONFIGURE clicked\n");
    const drawer = await screen.findByRole("dialog");
    process.stderr.write("DRAWER open\n");
    await userEvent.click(
      within(drawer).getByRole("button", { name: /保\s*存配置/ }),
    );
    process.stderr.write("SAVE clicked\n");

    await waitFor(() => expect(writes("PUT")).toHaveLength(1), {
      timeout: 5000,
    }).catch((error: unknown) => {
      process.stderr.write(`PUT-WAIT-FAILED: ${String(error)}
`);
      process.stderr.write(
        `ALL REQUESTS: ${JSON.stringify(requests.map((r) => r.method + " " + r.url.slice(-40)))}
`,
      );
    });
    expect(
      (writes("PUT")[0].body as { expected_revision: number }).expected_revision,
    ).toBe(9);
  });

  it("shows a retry hint when rate limited", async () => {
    state.rateLimited = true;
    renderTasks();
    await userEvent.click(
      await screen.findByRole("button", { name: "配置 market.sync" }),
    );
    const drawer = await screen.findByRole("dialog");
    await userEvent.click(within(drawer).getByRole("button", { name: "保存配置" }));

    expect(await within(drawer).findByText(/请求过于频繁/)).toBeInTheDocument();
  });
});
