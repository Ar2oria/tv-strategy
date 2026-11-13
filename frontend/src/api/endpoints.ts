import type { ApiResult, JsonObject } from "../types/api";
import type {
  IndicatorComputation,
  IndicatorComputeRequest,
  IndicatorDescriptor,
} from "../types/indicator";
import type {
  BarDTO,
  BarsQuery,
  InstrumentRecord,
  InstrumentQuery,
} from "../types/market";
import type {
  NetworkTestRequest,
  NetworkTestResult,
  Settings,
  SettingsUpdate,
} from "../types/settings";
import type {
  TaskConfigUpdate,
  TaskDescriptor,
  TaskLogDTO,
  TaskRunDTO,
  TaskRunRequest,
} from "../types/task";
import { apiRequest } from "./client";
import {
  decodeIndicatorComputations,
  decodeIndicators,
} from "./decoders/indicator";
import { decodeBars, decodeInstrumentRecords } from "./decoders/market";
import { decodeNetworkTestResult, decodeSettings } from "./decoders/settings";
import {
  decodeTask,
  decodeTaskLogs,
  decodeTaskRun,
  decodeTaskRuns,
  decodeTasks,
} from "./decoders/task";

const API_ROOT = "/api/v1";
const DEFAULT_TASK_HISTORY_LIMIT = 100;
const DEFAULT_TASK_LOG_LIMIT = 1000;
type QueryValue = string | number | boolean | null | undefined;

function queryString(values: Record<string, QueryValue>): string {
  const entries = Object.entries(values).filter(
    (entry): entry is [string, string | number | boolean] => entry[1] != null,
  );
  const search = new URLSearchParams(
    entries.map(([key, value]) => [key, String(value)]),
  );
  const serialized = search.toString();
  return serialized.length === 0 ? "" : `?${serialized}`;
}

function jsonBody(value: unknown): Pick<RequestInit, "body" | "headers"> {
  return {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  };
}

function positiveId(value: number, name: string): number {
  if (!Number.isInteger(value) || value <= 0) {
    throw new TypeError(`${name} must be a positive integer`);
  }
  return value;
}

export function listInstruments(
  filters: InstrumentQuery = {},
): Promise<ApiResult<InstrumentRecord[]>> {
  return apiRequest(
    `${API_ROOT}/instruments${queryString({ ...filters })}`,
    decodeInstrumentRecords,
  );
}

export function getBars(filters: BarsQuery): Promise<ApiResult<BarDTO[]>> {
  const instrumentId = positiveId(filters.instrument_id, "instrument_id");
  return apiRequest(
    `${API_ROOT}/bars${queryString({ ...filters, instrument_id: instrumentId })}`,
    decodeBars,
  );
}

export function listIndicators(): Promise<ApiResult<IndicatorDescriptor[]>> {
  return apiRequest(`${API_ROOT}/indicators`, decodeIndicators);
}

export function computeIndicators(
  request: IndicatorComputeRequest,
): Promise<ApiResult<IndicatorComputation[]>> {
  return apiRequest(
    `${API_ROOT}/indicators/compute`,
    decodeIndicatorComputations,
    { method: "POST", ...jsonBody(request) },
  );
}

export function getSettings(): Promise<ApiResult<Settings>> {
  return apiRequest(`${API_ROOT}/settings`, decodeSettings);
}

export function putSettings(update: SettingsUpdate): Promise<ApiResult<Settings>> {
  return apiRequest(`${API_ROOT}/settings`, decodeSettings, {
    method: "PUT",
    ...jsonBody(update),
  });
}

export function testMarketNetwork(
  market: string,
  request: NetworkTestRequest,
): Promise<ApiResult<NetworkTestResult>> {
  return apiRequest(
    `${API_ROOT}/settings/markets/${encodeURIComponent(market)}/network-test`,
    decodeNetworkTestResult,
    { method: "POST", ...jsonBody(request) },
  );
}

export function listTasks(): Promise<ApiResult<TaskDescriptor[]>> {
  return apiRequest(`${API_ROOT}/tasks`, decodeTasks);
}

export function getTaskConfig(taskName: string): Promise<ApiResult<TaskDescriptor>> {
  return apiRequest(
    `${API_ROOT}/tasks/${encodeURIComponent(taskName)}/config`,
    decodeTask,
  );
}

export function updateTaskConfig(
  taskName: string,
  update: TaskConfigUpdate,
): Promise<ApiResult<TaskDescriptor>> {
  return apiRequest(
    `${API_ROOT}/tasks/${encodeURIComponent(taskName)}/config`,
    decodeTask,
    { method: "PUT", ...jsonBody(update) },
  );
}

export function startTaskRun(
  taskName: string,
  params?: JsonObject,
): Promise<ApiResult<TaskRunDTO>> {
  const request: TaskRunRequest = params === undefined ? {} : { params };
  return apiRequest(
    `${API_ROOT}/tasks/${encodeURIComponent(taskName)}/runs`,
    decodeTaskRun,
    { method: "POST", ...jsonBody(request) },
  );
}

export function getTaskRuns(
  taskName: string,
  limit = DEFAULT_TASK_HISTORY_LIMIT,
  offset = 0,
): Promise<ApiResult<TaskRunDTO[]>> {
  return apiRequest(
    `${API_ROOT}/tasks/${encodeURIComponent(taskName)}/runs${queryString({ limit, offset })}`,
    decodeTaskRuns,
  );
}

export function getTaskLogs(
  runId: number,
  limit = DEFAULT_TASK_LOG_LIMIT,
  offset = 0,
): Promise<ApiResult<TaskLogDTO[]>> {
  const validRunId = positiveId(runId, "run_id");
  return apiRequest(
    `${API_ROOT}/task-runs/${validRunId}/logs${queryString({ limit, offset })}`,
    decodeTaskLogs,
  );
}
