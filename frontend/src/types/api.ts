export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = Record<string, JsonValue>;

export interface ResponseMeta {
  count?: number;
  limit?: number;
  offset?: number;
  revision?: number;
  current_revision?: number;
  retry_after?: number;
  run_id?: number;
  task_name?: string;
  timeframe?: string;
  [key: string]: JsonValue | undefined;
}

export interface ApiResult<T> {
  data: T;
  meta: ResponseMeta;
}

export interface ApiErrorBody {
  code: string;
  message: string;
}

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: ApiErrorBody | null;
  meta: ResponseMeta;
}
