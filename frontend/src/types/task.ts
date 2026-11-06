import type { RJSFSchema } from "@rjsf/utils";

import type { JsonObject } from "./api";

export type TaskStatus =
  | "queued"
  | "running"
  | "success"
  | "partial"
  | "failed"
  | "skipped"
  | "interrupted";

export interface TaskRunDTO {
  id: number;
  task_name: string;
  trigger: "manual" | "scheduled";
  status: TaskStatus;
  params: JsonObject;
  config_snapshot: JsonObject | null;
  progress: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskLogDTO {
  id: number;
  run_id: number;
  level: string;
  message: string;
  context: JsonObject;
  created_at: string;
}

export interface TaskDescriptor {
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  cron: string;
  params: JsonObject;
  params_schema: RJSFSchema;
  revision: number;
  next_run_at: string | null;
  last_run: TaskRunDTO | null;
}

export interface TaskConfigUpdate {
  expected_revision: number;
  enabled?: boolean;
  cron?: string;
  params?: JsonObject;
}

export interface TaskRunRequest {
  params?: JsonObject;
}
