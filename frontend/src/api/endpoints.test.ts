import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SettingsUpdate } from "../types/settings";
import {
  barPayload,
  indicatorComputationPayload,
  indicatorDescriptorPayload,
  instrumentPayload,
  settingsPayload,
  taskLogPayload,
  taskPayload,
  taskRunPayload,
} from "../test/apiFixtures";
import {
  computeIndicators,
  getBars,
  getSettings,
  getTaskConfig,
  getTaskLogs,
  getTaskRuns,
  listIndicators,
  listInstruments,
  listTasks,
  putSettings,
  startTaskRun,
  updateTaskConfig,
} from "./endpoints";
import { ApiError } from "./errors";

const fetchMock = vi.fn<typeof fetch>();

function mockSuccess(data: unknown, meta: Record<string, unknown> = {}): void {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue({
      success: true,
      data,
      error: null,
      meta,
    }),
  } as unknown as Response);
}

async function capturedError(promise: Promise<unknown>): Promise<ApiError> {
  let captured: unknown;
  try {
    await promise;
  } catch (error) {
    captured = error;
  }
  expect(captured).toBeInstanceOf(ApiError);
  return captured as ApiError;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("typed endpoints", () => {
  it("builds instrument queries and decodes records", async () => {
    mockSuccess([instrumentPayload], { count: 1, limit: 50, offset: 100 });

    const result = await listInstruments({
      query: "Alpha Inc",
      market: "us_stock",
      universe_code: "nasdaq100",
      limit: 50,
      offset: 100,
    });

    expect(result.data).toEqual([instrumentPayload]);
    expect(result.meta).toEqual({ count: 1, limit: 50, offset: 100 });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/instruments?query=Alpha+Inc&market=us_stock&universe_code=nasdaq100&limit=50&offset=100",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("builds bar queries and decodes nullable volume", async () => {
    mockSuccess([{ ...barPayload, volume: null }]);

    const result = await getBars({
      instrument_id: 7,
      timeframe: "1d",
      start: "2026-01-01",
      end: "2026-01-31",
      limit: 100,
    });

    expect(result.data[0]?.volume).toBeNull();
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/bars?instrument_id=7&timeframe=1d&start=2026-01-01&end=2026-01-31&limit=100",
    );
  });

  it("decodes indicator descriptors and computation results", async () => {
    mockSuccess([indicatorDescriptorPayload]);
    const descriptors = await listIndicators();
    mockSuccess([indicatorComputationPayload]);
    const request = {
      instrument_id: 7,
      timeframe: "1d" as const,
      start: "2026-01-01",
      end: "2026-01-31",
      indicators: [],
    };
    const computations = await computeIndicators(request);

    expect(descriptors.data).toEqual([indicatorDescriptorPayload]);
    expect(computations.data).toEqual([indicatorComputationPayload]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/indicators");
    const [path, init] = fetchMock.mock.calls[1] ?? [];
    expect(path).toBe("/api/v1/indicators/compute");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual(request);
    expect(new Headers(init?.headers).get("content-type")).toBe("application/json");
  });

  it("decodes settings reads and revision-checked writes", async () => {
    mockSuccess(settingsPayload);
    const fetched = await getSettings();
    const { revision, ...document } = settingsPayload;
    const update = {
      ...document,
      expected_revision: revision,
    } as unknown as SettingsUpdate;
    mockSuccess({ ...settingsPayload, revision: 5 });
    const updated = await putSettings(update);

    expect(fetched.data.markets.a_share).toEqual({
      provider: "akshare",
      request_timeout_seconds: 20,
    });
    for (const market of Object.values(fetched.data.markets)) {
      expect(market).not.toHaveProperty("history_years");
      expect(market).not.toHaveProperty("overlap_days");
      expect(market).not.toHaveProperty("concurrency");
      expect(market).not.toHaveProperty("max_retries");
      expect(market).not.toHaveProperty("symbols");
    }
    expect(fetched.data.tasks["market.sync_crypto_daily"].params.spot_pairs).toEqual([
      { exchange: "binance", symbol: "BTC/USDT" },
    ]);
    expect(updated.data.revision).toBe(5);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/settings");
    const [, init] = fetchMock.mock.calls[1] ?? [];
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual(update);
  });

  it("decodes task catalog, config, run history, and logs", async () => {
    mockSuccess([taskPayload]);
    expect((await listTasks()).data).toEqual([taskPayload]);
    mockSuccess(taskPayload);
    expect((await getTaskConfig("market.sync")).data).toEqual(taskPayload);
    mockSuccess({ ...taskPayload, enabled: false });
    expect(
      (
        await updateTaskConfig("market.sync", {
          expected_revision: 4,
          enabled: false,
        })
      ).data.enabled,
    ).toBe(false);
    mockSuccess(taskRunPayload);
    expect((await startTaskRun("market.sync", { value: 1 })).data).toEqual(
      taskRunPayload,
    );
    mockSuccess([taskRunPayload]);
    expect((await getTaskRuns("market.sync", 25, 50)).data).toEqual([
      taskRunPayload,
    ]);
    mockSuccess([taskLogPayload]);
    expect((await getTaskLogs(8, 100, 0)).data).toEqual([taskLogPayload]);

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/tasks",
      "/api/v1/tasks/market.sync/config",
      "/api/v1/tasks/market.sync/config",
      "/api/v1/tasks/market.sync/runs",
      "/api/v1/tasks/market.sync/runs?limit=25&offset=50",
      "/api/v1/task-runs/8/logs?limit=100&offset=0",
    ]);
    const updateInit = fetchMock.mock.calls[2]?.[1];
    expect(updateInit?.method).toBe("PUT");
    expect(JSON.parse(String(updateInit?.body))).toEqual({
      expected_revision: 4,
      enabled: false,
    });
    const runInit = fetchMock.mock.calls[3]?.[1];
    expect(runInit?.method).toBe("POST");
    expect(JSON.parse(String(runInit?.body))).toEqual({ params: { value: 1 } });
  });

  it("encodes task path segments and submits an empty override object", async () => {
    mockSuccess(taskRunPayload);

    await startTaskRun("market.sync us");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/tasks/market.sync%20us/runs",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({});
  });

  it("rejects invalid resource IDs before fetch", () => {
    expect(() =>
      getBars({ instrument_id: 0, timeframe: "1d", start: "", end: "" }),
    ).toThrow("instrument_id must be a positive integer");
    expect(() => getTaskLogs(-1)).toThrow("run_id must be a positive integer");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    {
      name: "settings",
      payload: { ...settingsPayload, revision: "4" },
      request: () => getSettings(),
    },
    {
      name: "bars",
      payload: [{ ...barPayload, close: "bad" }],
      request: () => getBars({ instrument_id: 7 }),
    },
    {
      name: "indicators",
      payload: [{ ...indicatorDescriptorPayload, name: 42 }],
      request: () => listIndicators(),
    },
    {
      name: "tasks",
      payload: [{ ...taskPayload, enabled: "yes" }],
      request: () => listTasks(),
    },
  ])("rejects malformed successful $name DTOs", async ({ payload, request }) => {
    mockSuccess(payload);

    const error = await capturedError(request());

    expect(error).toMatchObject({ code: "invalid_envelope", status: 200 });
    expect(error.message).toBe("Invalid API response envelope");
  });
});
