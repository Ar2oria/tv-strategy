import type { ResponseMeta } from "../types/api";

const DEFAULT_ERROR_MESSAGE = "Request failed";
const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_:-]{0,63}$/;
const SAFE_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$/;
const UNSAFE_MESSAGE_PATTERN =
  /traceback|secret|credential|password|api[_-]?key|token|https?:\/\/|file\s+"[^"]+"|[\r\n]/i;
const STATUS_MESSAGES: Readonly<Record<number, string>> = {
  400: "Bad request",
  404: "Resource not found",
  409: "Request conflict",
  413: "Request is too large",
  422: "Request validation failed",
  429: "Too many requests",
  500: "An internal error occurred",
};
const NUMERIC_META_KEYS = [
  "revision",
  "current_revision",
  "count",
  "limit",
  "offset",
  "retry_after",
  "run_id",
] as const;

interface ApiErrorOptions {
  status: number;
  code: string;
  meta?: ResponseMeta;
}

function fallbackMessage(status: number): string {
  return STATUS_MESSAGES[status] ?? DEFAULT_ERROR_MESSAGE;
}

function sanitizeMessage(message: string, status: number): string {
  const normalized = message.trim();
  if (
    normalized.length === 0 ||
    normalized.length > 500 ||
    UNSAFE_MESSAGE_PATTERN.test(normalized)
  ) {
    return fallbackMessage(status);
  }
  return normalized;
}

function sanitizeCode(code: string): string {
  return ERROR_CODE_PATTERN.test(code) ? code : "invalid_error_code";
}

function sanitizeStatus(status: number): number {
  return Number.isInteger(status) && status >= 0 && status <= 599 ? status : 0;
}

function sanitizeMeta(meta: ResponseMeta | undefined): ResponseMeta {
  if (meta === undefined) {
    return {};
  }
  const numeric = Object.fromEntries(
    NUMERIC_META_KEYS.flatMap((key) => {
      const value = meta[key];
      return typeof value === "number" && Number.isFinite(value)
        ? [[key, value]]
        : [];
    }),
  );
  const names = ["task_name", "timeframe"].flatMap((key) => {
    const value = meta[key];
    return typeof value === "string" && SAFE_NAME_PATTERN.test(value)
      ? [[key, value]]
      : [];
  });
  return { ...numeric, ...Object.fromEntries(names) };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly meta: ResponseMeta;
  readonly revision?: number;

  constructor(message: string, options: ApiErrorOptions) {
    const status = sanitizeStatus(options.status);
    super(sanitizeMessage(message, status));
    this.name = "ApiError";
    this.status = status;
    this.code = sanitizeCode(options.code);
    this.meta = sanitizeMeta(options.meta);
    this.revision =
      typeof this.meta.revision === "number"
        ? this.meta.revision
        : typeof this.meta.current_revision === "number"
          ? this.meta.current_revision
          : undefined;
  }

  toJSON(): Readonly<Record<string, unknown>> {
    return {
      name: this.name,
      message: this.message,
      status: this.status,
      code: this.code,
      meta: this.meta,
      revision: this.revision,
    };
  }
}
