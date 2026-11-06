/** Five-field crontab shape check used before the server sees a value. */

const CRON_FIELD_PATTERN = /^[0-9A-Za-z*/,?#LW-]+$/;

export interface CronValidation {
  valid: boolean;
  message: string | null;
}

/** Reject obvious numeric out-of-range values the server would also refuse. */
function fieldBoundsError(field: string, index: number): string | null {
  if (field.includes("/") || field.includes("-") || field.includes(",")) {
    return null;
  }
  if (field === "*" || /[A-Za-z?#]/.test(field)) {
    return null;
  }
  const numeric = Number(field);
  if (!Number.isInteger(numeric)) {
    return null;
  }
  const limits: ReadonlyArray<readonly [number, number]> = [
    [0, 59],
    [0, 23],
    [1, 31],
    [1, 12],
    [0, 7],
  ];
  const [low, high] = limits[index];
  return numeric < low || numeric > high
    ? `Cron 第 ${index + 1} 个字段超出范围 ${low}-${high}：${field}`
    : null;
}

export function validateCronShape(value: string): CronValidation {
  const fields = value.trim().split(/\s+/).filter((field) => field.length > 0);
  if (value.trim().length === 0) {
    return { valid: false, message: "Cron 表达式不能为空" };
  }
  if (fields.length !== 5) {
    return {
      valid: false,
      message: `Cron 需要恰好 5 个字段，当前为 ${fields.length} 个`,
    };
  }
  const invalid = fields.find((field) => !CRON_FIELD_PATTERN.test(field));
  if (invalid !== undefined) {
    return { valid: false, message: `Cron 字段包含非法字符：${invalid}` };
  }
  for (const [index, field] of fields.entries()) {
    const boundsError = fieldBoundsError(field, index);
    if (boundsError !== null) {
      return { valid: false, message: boundsError };
    }
  }
  return { valid: true, message: null };
}
