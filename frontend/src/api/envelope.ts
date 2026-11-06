import type { ApiErrorBody, ApiResult } from "../types/api";
import type { Decoder } from "./decoding";
import { decodeResponseMeta } from "./decoding";
import { ApiError } from "./errors";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasEnvelopeKeys(value: Record<string, unknown>): boolean {
  return ["success", "data", "error", "meta"].every((key) =>
    Object.hasOwn(value, key),
  );
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    value.code.length > 0 &&
    typeof value.message === "string"
  );
}

export function invalidEnvelope(status: number): ApiError {
  return new ApiError("Invalid API response envelope", {
    status,
    code: "invalid_envelope",
  });
}

export function parseEnvelope<T>(
  payload: unknown,
  status: number,
  decoder: Decoder<T>,
): ApiResult<T> {
  if (!isRecord(payload) || !hasEnvelopeKeys(payload)) {
    throw invalidEnvelope(status);
  }

  let meta;
  try {
    meta = decodeResponseMeta(payload.meta);
  } catch {
    throw invalidEnvelope(status);
  }

  if (payload.success === false) {
    if (payload.data !== null || !isErrorBody(payload.error)) {
      throw invalidEnvelope(status);
    }
    throw new ApiError(payload.error.message, {
      status,
      code: payload.error.code,
      meta,
    });
  }

  const successfulStatus = status >= 200 && status < 300;
  if (payload.success !== true || payload.error !== null || !successfulStatus) {
    throw invalidEnvelope(status);
  }

  let data: T;
  try {
    data = decoder(payload.data);
  } catch {
    throw invalidEnvelope(status);
  }

  return { data, meta: { ...meta } };
}
