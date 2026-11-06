import type {
  TaskDescriptor,
  TaskLogDTO,
  TaskRunDTO,
} from "../../types/task";
import {
  decodeArray,
  decodeBoolean,
  decodeFiniteNumber,
  decodeJsonObject,
  decodeLiteral,
  decodeNonNegativeInteger,
  decodeNullable,
  decodePositiveInteger,
  decodeRecord,
  decodeString,
} from "../decoding";

const TASK_STATUSES = [
  "queued",
  "running",
  "success",
  "partial",
  "failed",
  "skipped",
  "interrupted",
] as const;

export function decodeTaskRun(value: unknown): TaskRunDTO {
  const item = decodeRecord(value);
  return {
    id: decodePositiveInteger(item.id),
    task_name: decodeString(item.task_name),
    trigger: decodeLiteral(item.trigger, ["manual", "scheduled"]),
    status: decodeLiteral(item.status, TASK_STATUSES),
    params: decodeJsonObject(item.params),
    config_snapshot: decodeNullable(item.config_snapshot, decodeJsonObject),
    progress: decodeFiniteNumber(item.progress),
    error: decodeNullable(item.error, decodeString),
    created_at: decodeString(item.created_at),
    started_at: decodeNullable(item.started_at, decodeString),
    finished_at: decodeNullable(item.finished_at, decodeString),
  };
}

export function decodeTaskRuns(value: unknown): TaskRunDTO[] {
  return decodeArray(value, decodeTaskRun);
}

export function decodeTask(value: unknown): TaskDescriptor {
  const item = decodeRecord(value);
  return {
    name: decodeString(item.name),
    display_name: decodeString(item.display_name),
    description: decodeString(item.description),
    enabled: decodeBoolean(item.enabled),
    cron: decodeString(item.cron),
    params: decodeJsonObject(item.params),
    params_schema: decodeJsonObject(item.params_schema),
    revision: decodeNonNegativeInteger(item.revision),
    next_run_at: decodeNullable(item.next_run_at, decodeString),
    last_run: decodeNullable(item.last_run, decodeTaskRun),
  };
}

export function decodeTasks(value: unknown): TaskDescriptor[] {
  return decodeArray(value, decodeTask);
}

export function decodeTaskLog(value: unknown): TaskLogDTO {
  const item = decodeRecord(value);
  return {
    id: decodePositiveInteger(item.id),
    run_id: decodePositiveInteger(item.run_id),
    level: decodeString(item.level),
    message: decodeString(item.message),
    context: decodeJsonObject(item.context),
    created_at: decodeString(item.created_at),
  };
}

export function decodeTaskLogs(value: unknown): TaskLogDTO[] {
  return decodeArray(value, decodeTaskLog);
}
