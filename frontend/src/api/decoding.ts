import type { JsonObject, JsonValue, ResponseMeta } from "../types/api";

export type Decoder<T> = (value: unknown) => T;
type Literal = string | number | boolean;

function invalidData(): never {
  throw new TypeError("Invalid API response data");
}

export function decodeRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return invalidData();
  }
  return value as Record<string, unknown>;
}

export function decodeString(value: unknown): string {
  return typeof value === "string" ? value : invalidData();
}

export function decodeFiniteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : invalidData();
}

export function decodeInteger(value: unknown): number {
  const numeric = decodeFiniteNumber(value);
  return Number.isSafeInteger(numeric) ? numeric : invalidData();
}

export function decodeNonNegativeInteger(value: unknown): number {
  const numeric = decodeInteger(value);
  return numeric >= 0 ? numeric : invalidData();
}

export function decodePositiveInteger(value: unknown): number {
  const numeric = decodeInteger(value);
  return numeric > 0 ? numeric : invalidData();
}

export function decodeBoolean(value: unknown): boolean {
  return typeof value === "boolean" ? value : invalidData();
}

export function decodeNullable<T>(
  value: unknown,
  decoder: Decoder<T>,
): T | null {
  return value === null ? null : decoder(value);
}

export function decodeArray<T>(
  value: unknown,
  decodeItem: Decoder<T>,
): T[] {
  return Array.isArray(value) ? value.map(decodeItem) : invalidData();
}

export function decodeLiteral<T extends Literal>(
  value: unknown,
  allowed: readonly T[],
): T {
  const match = allowed.find((candidate) => candidate === value);
  return match === undefined ? invalidData() : match;
}

export function decodeRecordOf<T>(
  value: unknown,
  decodeValue: Decoder<T>,
): Record<string, T> {
  return Object.fromEntries(
    Object.entries(decodeRecord(value)).map(([key, item]) => [
      key,
      decodeValue(item),
    ]),
  );
}

export function decodeJsonValue(value: unknown): JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "number") {
    return decodeFiniteNumber(value);
  }
  if (Array.isArray(value)) {
    return value.map(decodeJsonValue);
  }
  return decodeJsonObject(value);
}

export function decodeJsonObject(value: unknown): JsonObject {
  return decodeRecordOf(value, decodeJsonValue);
}

const NUMERIC_META_KEYS = [
  "count",
  "limit",
  "offset",
  "revision",
  "current_revision",
  "retry_after",
  "run_id",
] as const;

const TEXTUAL_META_KEYS = ["task_name", "timeframe", "created_at"] as const;

export function decodeResponseMeta(value: unknown): ResponseMeta {
  const item = decodeRecord(value);
  const meta: ResponseMeta = {};
  for (const [key, entry] of Object.entries(item)) {
    meta[key] = decodeJsonValue(entry);
  }
  for (const key of NUMERIC_META_KEYS) {
    const entry = item[key];
    if (entry !== undefined) {
      decodeNonNegativeInteger(entry);
    }
  }
  for (const key of TEXTUAL_META_KEYS) {
    const entry = item[key];
    if (entry !== undefined) {
      decodeString(entry);
    }
  }
  return meta;
}
