import { fireEvent, render, screen } from "@testing-library/react";
import type { WidgetProps } from "@rjsf/utils";
import { describe, expect, it, vi } from "vitest";

import { CommaSeparatedWidget, parseCommaSeparated } from "./CommaSeparatedWidget";

describe("comma-separated Task list input", () => {
  it("splits on English commas, trims items, and ignores empty entries", () => {
    expect(parseCommaSeparated("AAA, BBB,,CCC,  ")).toEqual([
      "AAA",
      "BBB",
      "CCC",
    ]);
  });

  it("uses one fixed-height input without destroying commas while typing", () => {
    const onChange = vi.fn();
    const props = {
      id: "root_symbols",
      value: ["AAA"],
      onChange,
    } as unknown as WidgetProps;
    render(<CommaSeparatedWidget {...props} />);
    const input = screen.getByRole("textbox");

    expect(input).toHaveStyle({ height: "72px" });
    fireEvent.change(input, { target: { value: "AAA, BBB,,CCC," } });
    expect(onChange).toHaveBeenLastCalledWith(["AAA", "BBB", "CCC"]);
    fireEvent.change(input, { target: { value: "AAA," } });
    expect(input).toHaveValue("AAA,");
  });
});
