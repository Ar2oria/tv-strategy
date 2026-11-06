import { describe, expect, it } from "vitest";

import { validateCronShape } from "./cron";

describe("validateCronShape", () => {
  it.each([
    "0 0 * * *",
    "30 8 * * 1-5",
    "*/5 * * * *",
    "0 0 1,15 * *",
    "0 9 * * MON-FRI",
    "  0   0   *   *   *  ",
  ])("accepts %s", (value) => {
    expect(validateCronShape(value)).toEqual({ valid: true, message: null });
  });

  it("rejects an empty expression", () => {
    expect(validateCronShape("   ")).toEqual({
      valid: false,
      message: "Cron 表达式不能为空",
    });
  });

  it.each(["* * *", "* * * * * *"])("rejects %s with the wrong field count", (value) => {
    const result = validateCronShape(value);
    expect(result.valid).toBe(false);
    expect(result.message).toMatch(/恰好 5 个字段/);
  });

  it("rejects illegal characters", () => {
    const result = validateCronShape("0 0 * * 1$");
    expect(result.valid).toBe(false);
    expect(result.message).toMatch(/非法字符/);
  });

  it.each([
    ["60 0 * * *", /第 1 个字段超出范围 0-59/],
    ["0 24 * * *", /第 2 个字段超出范围 0-23/],
    ["0 0 32 * *", /第 3 个字段超出范围 1-31/],
    ["0 0 * 13 *", /第 4 个字段超出范围 1-12/],
    ["0 0 * * 8", /第 5 个字段超出范围 0-7/],
  ])("rejects out-of-range field in %s", (value, pattern) => {
    const result = validateCronShape(value);
    expect(result.valid).toBe(false);
    expect(result.message).toMatch(pattern);
  });

  it("does not range-check composite fields", () => {
    expect(validateCronShape("0 0 * * 1-5").valid).toBe(true);
  });
});
