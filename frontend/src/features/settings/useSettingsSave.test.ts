import { ApiError } from "../../api/errors";
import { buildUpdate, describeSaveError } from "./useSettingsSave";
import { describe, expect, it } from "vitest";

import type { Settings } from "../../types/settings";

const settings: Settings = {
  schema_version: 1,
  revision: 7,
  markets: {},
  timezone: "UTC",
  indicators: { max_active_indicators: 20 },
  tasks: {},
};

describe("settings save helpers", () => {
  it("carries the draft revision as the expected revision", () => {
    const update = buildUpdate(settings);
    expect(update.expected_revision).toBe(7);
    expect(update.schema_version).toBe(1);
    expect(update.timezone).toBe("UTC");
  });

  it("turns 409 into a reapply instruction", () => {
    const state = describeSaveError(
      new ApiError("Request conflict", { status: 409, code: "revision_conflict" }),
    );
    expect(state.status).toBe("conflict");
    expect(state.message).toMatch(/已被其他页面修改/);
  });

  it("turns 429 into a retry hint", () => {
    const state = describeSaveError(
      new ApiError("Too many requests", { status: 429, code: "rate_limited" }),
    );
    expect(state.status).toBe("error");
    expect(state.message).toMatch(/请求过于频繁/);
  });

  it("keeps other validation messages", () => {
    const state = describeSaveError(
      new ApiError("Request validation failed", { status: 422, code: "validation_error" }),
    );
    expect(state.message).toBe("Request validation failed");
  });

  it("hides non-ApiError details", () => {
    expect(describeSaveError(new Error("SECRET")).message).toBe(
      "保存失败，请稍后重试。",
    );
  });
});
