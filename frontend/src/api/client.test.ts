import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "./client";

const fetchMock = vi.fn<typeof fetch>();

function echo<T>(value: unknown): T {
  return value as T;
}

function decodeRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("Expected an object");
  }
  return value as Record<string, unknown>;
}

function mockResponse(payload: unknown, status = 200): void {
  fetchMock.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response);
}

function mockJsonFailure(error: Error, status = 200): void {
  fetchMock.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockRejectedValue(error),
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

describe("apiRequest", () => {
  it("returns typed data and preserves success metadata", async () => {
    mockResponse({
      success: true,
      data: { revision: 4, timezone: "UTC" },
      error: null,
      meta: { count: 1, revision: 4 },
    });

    const result = await apiRequest<{ revision: number; timezone: string }>(
      "/api/v1/settings",
      echo,
    );

    expect(result).toEqual({
      data: { revision: 4, timezone: "UTC" },
      meta: { count: 1, revision: 4 },
    });
    const [path, init] = fetchMock.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/settings");
    expect(new Headers(init?.headers).get("accept")).toBe("application/json");
  });

  it("preserves paginated list metadata", async () => {
    mockResponse({
      success: true,
      data: [{ id: 8 }, { id: 9 }],
      error: null,
      meta: { count: 2, limit: 50, offset: 100 },
    });

    const result = await apiRequest<Array<{ id: number }>>(
      "/api/v1/instruments?limit=50&offset=100",
      echo,
    );

    expect(result.data).toEqual([{ id: 8 }, { id: 9 }]);
    expect(result.meta).toEqual({ count: 2, limit: 50, offset: 100 });
  });

  it("retains backend validation status and code without exposing details", async () => {
    mockResponse(
      {
        success: false,
        data: null,
        error: { code: "validation_error", message: "Request validation failed" },
        meta: {},
      },
      422,
    );

    const error = await capturedError(apiRequest("/api/v1/bars", echo));

    expect(error).toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Request validation failed",
      meta: {},
    });
  });

  it("retains conflict revision metadata", async () => {
    mockResponse(
      {
        success: false,
        data: null,
        error: {
          code: "config_conflict",
          message: "Configuration revision conflict",
        },
        meta: { revision: 17, current_revision: 17 },
      },
      409,
    );

    const error = await capturedError(apiRequest("/api/v1/settings", echo, { method: "PUT" }));

    expect(error.status).toBe(409);
    expect(error.code).toBe("config_conflict");
    expect(error.revision).toBe(17);
    expect(error.meta).toEqual({ revision: 17, current_revision: 17 });
  });

  it.each([
    [413, "http_error", "Request is too large"],
    [429, "http_error", "Too many requests"],
  ])("maps sanitized HTTP %i failures", async (status, code, message) => {
    mockResponse(
      {
        success: false,
        data: null,
        error: { code, message },
        meta: {},
      },
      status,
    );

    const error = await capturedError(apiRequest("/api/v1/tasks", echo));

    expect(error).toMatchObject({ status, code, message });
  });

  it("never promotes a server traceback or secret into an ApiError", async () => {
    mockResponse(
      {
        success: false,
        data: null,
        error: {
          code: "internal_error",
          message: "Traceback (most recent call last): SECRET_TOKEN=raw-secret",
        },
        meta: { debug: "Traceback: raw-secret" },
      },
      500,
    );

    const error = await capturedError(apiRequest("/api/v1/settings", echo));

    expect(error.status).toBe(500);
    expect(error.code).toBe("internal_error");
    expect(error.message).toBe("An internal error occurred");
    expect(error.message).not.toContain("Traceback");
    expect(error.message).not.toContain("raw-secret");
    expect(JSON.stringify(error)).not.toContain("raw-secret");
  });

  it.each([
    null,
    [],
    {},
    { success: true, data: {}, error: null },
    { success: true, data: {}, error: null, meta: null },
    { success: "true", data: {}, error: null, meta: {} },
    { success: false, data: {}, error: null, meta: {} },
    { success: true, data: {}, error: { code: "bad" }, meta: {} },
  ])("rejects a malformed envelope without returning data", async (payload) => {
    mockResponse(payload);

    const error = await capturedError(apiRequest("/api/v1/instruments", echo));

    expect(error).toMatchObject({ code: "invalid_envelope", status: 200 });
    expect(error.message).toBe("Invalid API response envelope");
  });

  it("rejects malformed JSON without exposing the parser or response body", async () => {
    mockJsonFailure(new SyntaxError("Unexpected token near raw-secret"));

    const error = await capturedError(apiRequest("/api/v1/settings", echo));

    expect(error).toMatchObject({ code: "invalid_envelope", status: 200 });
    expect(error.message).not.toContain("raw-secret");
  });

  it("wraps network failures in a sanitized typed error", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("https://private.test/raw-secret"));

    const error = await capturedError(apiRequest("/api/v1/settings", echo));

    expect(error).toMatchObject({ status: 0, code: "network_error" });
    expect(error.message).not.toContain("private.test");
    expect(error.message).not.toContain("raw-secret");
  });

  it.each([
    { data: "bad", meta: {} },
    { data: {}, meta: { count: "2" } },
    { data: {}, meta: { count: -1 } },
    { data: {}, meta: { revision: 1.5 } },
    { data: {}, meta: { offset: -1 } },
    { data: {}, meta: { limit: "50" } },
    { data: {}, meta: { timeframe: 1 } },
    { data: {}, meta: { created_at: false } },
  ])("rejects malformed successful data or metadata", async ({ data, meta }) => {
    mockResponse({ success: true, data, error: null, meta });

    const error = await capturedError(
      apiRequest("/api/v1/settings", decodeRecord),
    );

    expect(error).toMatchObject({ code: "invalid_envelope", status: 200 });
    expect(error.message).toBe("Invalid API response envelope");
  });

  it("preserves unknown metadata after validating known fields", async () => {
    mockResponse({
      success: true,
      data: {},
      error: null,
      meta: { count: 1, vendor: { future: true } },
    });

    const result = await apiRequest("/api/v1/settings", decodeRecord);

    expect(result.meta).toEqual({ count: 1, vendor: { future: true } });
  });

  it("sanitizes decoder failures without exposing raw data", async () => {
    mockResponse({ success: true, data: {}, error: null, meta: {} });
    const decoder = (): never => {
      throw new Error("SECRET_TOKEN=raw-secret");
    };

    const error = await capturedError(
      apiRequest("/api/v1/settings", decoder),
    );

    expect(error).toMatchObject({ code: "invalid_envelope", status: 200 });
    expect(error.message).not.toContain("raw-secret");
  });
});
