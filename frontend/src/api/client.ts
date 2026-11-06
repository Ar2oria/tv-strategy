import type { ApiResult } from "../types/api";
import type { Decoder } from "./decoding";
import { invalidEnvelope, parseEnvelope } from "./envelope";
import { ApiError } from "./errors";

function requestHeaders(init: RequestInit | undefined): Headers {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

function validSameOriginPath(path: string): boolean {
  return path === "/api" || (path.startsWith("/api/") && !path.startsWith("//"));
}

export async function apiRequest<T>(
  path: string,
  decoder: Decoder<T>,
  init?: RequestInit,
): Promise<ApiResult<T>> {

  if (!validSameOriginPath(path)) {
    throw new ApiError("Invalid API request path", {
      status: 0,
      code: "invalid_request_path",
    });
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: requestHeaders(init),
    });
  } catch (error: unknown) {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(aborted ? "Request was aborted" : "Network request failed", {
      status: 0,
      code: aborted ? "request_aborted" : "network_error",
    });
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw invalidEnvelope(response.status);
  }
  return parseEnvelope<T>(payload, response.status, decoder);
}

export { ApiError } from "./errors";
export type { ApiResult } from "../types/api";
