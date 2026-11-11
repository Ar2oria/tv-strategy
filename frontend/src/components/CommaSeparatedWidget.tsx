import { Input } from "antd";
import type { WidgetProps } from "@rjsf/utils";
import { useEffect, useRef, useState } from "react";

const LIST_INPUT_HEIGHT_PX = 72;

export function parseCommaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function displayValue(value: unknown): string {
  if (!Array.isArray(value)) {
    return "";
  }
  return value.filter((item): item is string => typeof item === "string").join(", ");
}

/** One fixed-height editor for string arrays; structured arrays stay untouched. */
export function CommaSeparatedWidget({
  id,
  value,
  onChange,
  disabled,
  readonly,
  placeholder,
  label,
  rawErrors,
  onBlur,
  onFocus,
}: WidgetProps) {
  const [text, setText] = useState(() => displayValue(value));
  const focused = useRef(false);

  useEffect(() => {
    if (!focused.current) {
      setText(displayValue(value));
    }
  }, [value]);

  return (
    <Input.TextArea
      id={id}
      aria-label={label}
      value={text}
      disabled={disabled || readonly}
      status={rawErrors !== undefined && rawErrors.length > 0 ? "error" : undefined}
      placeholder={placeholder ?? "使用英文逗号分隔"}
      style={{ height: LIST_INPUT_HEIGHT_PX, resize: "none" }}
      onChange={(event) => {
        const next = event.target.value;
        setText(next);
        onChange(parseCommaSeparated(next));
      }}
      onFocus={(event) => {
        focused.current = true;
        onFocus(id, event.target.value);
      }}
      onBlur={(event) => {
        focused.current = false;
        setText(displayValue(value));
        onBlur(id, event.target.value);
      }}
    />
  );
}
