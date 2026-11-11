import type { RJSFSchema } from "@rjsf/utils";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SchemaForm } from "./SchemaForm";

interface FormValues extends Record<string, unknown> {
  integer: number;
  float: number;
  boolean: boolean;
  text: string;
  mode: string;
  tags: string[];
  optional: string | null;
}

const schema: RJSFSchema = {
  type: "object",
  properties: {
    integer: { type: "integer", minimum: 1, maximum: 10, default: 5 },
    float: { type: "number", minimum: 0.5, maximum: 2.5, default: 1.5 },
    boolean: { type: "boolean", default: true },
    text: { type: "string", minLength: 3, default: "abc" },
    mode: { type: "string", enum: ["alpha", "beta"], default: "alpha" },
    tags: {
      type: "array",
      items: { type: "string" },
      default: ["one", "two"],
    },
    optional: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
    },
  },
  required: ["integer", "float", "boolean", "text", "mode", "tags"],
};

const validValues: FormValues = {
  integer: 5,
  float: 1.5,
  boolean: true,
  text: "abc",
  mode: "alpha",
  tags: ["one", "two"],
  optional: null,
};

describe("SchemaForm", () => {
  it("uses RJSF defaults for every supported parameter type and nullable fields", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(values: FormValues) => void>();
    render(<SchemaForm<FormValues> schema={schema} onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0]?.[0]).toEqual(validValues);
  });

  it("rejects a fractional integer before submission", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(values: FormValues) => void>();
    render(
      <SchemaForm<FormValues>
        schema={schema}
        formData={{ ...validValues, integer: 5.5 }}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(
      await screen.findAllByText(/must be integer/i),
    ).not.toHaveLength(0);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("replaces an out-of-enum formData value with the schema default before submission", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(values: FormValues) => void>();
    render(
      <SchemaForm<FormValues>
        schema={schema}
        formData={{ ...validValues, mode: "gamma" }}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /submit/i }));

    // The AntD select widget rejects values outside the schema enum and
    // falls back to the schema default, so the invalid value never leaves
    // the client (the backend would also reject it).
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0]?.[0].mode).toBe("alpha");
  });

  it("rejects non-string array items before submission", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(values: FormValues) => void>();
    render(
      <SchemaForm<FormValues>
        schema={schema}
        formData={{
          ...validValues,
          tags: ["one", 2] as unknown as string[],
        }}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findAllByText(/must be string/i)).not.toHaveLength(0);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects AJV integer and float bounds before submission", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(values: FormValues) => void>();
    render(
      <SchemaForm<FormValues>
        schema={schema}
        formData={{ ...validValues, integer: 11, float: 0.25 }}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findAllByText(/must be <= ?10/i)).not.toHaveLength(0);
    expect(await screen.findAllByText(/must be >= ?0\.5/i)).not.toHaveLength(0);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("returns a deep submit snapshot without mutating formData props", async () => {
    const user = userEvent.setup();
    const formData: FormValues = {
      ...validValues,
      tags: ["original"],
      optional: "present",
    };
    const original = structuredClone(formData);
    const onSubmit = vi.fn<(values: FormValues) => void>();
    render(
      <SchemaForm<FormValues>
        schema={schema}
        formData={formData}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const submitted = onSubmit.mock.calls[0]?.[0];
    expect(submitted).toEqual(original);
    expect(submitted).not.toBe(formData);
    expect(submitted?.tags).not.toBe(formData.tags);
    expect(formData).toEqual(original);
  });

  it("disables inputs and submission when requested", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(values: FormValues) => void>();
    render(
      <SchemaForm<FormValues>
        schema={schema}
        formData={validValues}
        onSubmit={onSubmit}
        disabled
      />,
    );

    const submit = screen.getByRole("button", { name: /submit/i });
    expect(submit).toBeDisabled();
    expect(screen.getByLabelText("text")).toBeDisabled();
    await user.click(submit);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("passes left-aligned single-column formContext to RJSF", () => {
    const { container } = render(
      <SchemaForm
        schema={{
          type: "object",
          title: "Parameters",
          properties: {
            first: { type: "string", default: "one" },
            second: { type: "string", default: "two" },
          },
        }}
        formContext={{ labelAlign: "left", colSpan: 24 }}
        onSubmit={vi.fn()}
      />,
    );

    expect(container.querySelectorAll(".ant-col-12")).toHaveLength(0);
    expect(container.querySelector(".ant-form-item-label-left")).not.toBeNull();
  });

  it("submits natively from a horizontal custom action area", () => {
    const onSubmit = vi.fn<(values: { text: string }) => void>();
    const { container } = render(
      <SchemaForm<{ text: string }>
        schema={{
          type: "object",
          properties: { text: { type: "string", default: "abc" } },
        }}
        formData={{ text: "abc" }}
        actions={<button type="button">关闭</button>}
        onSubmit={onSubmit}
      />,
    );

    const actions = container.querySelector(".schema-form-actions");
    expect(actions).not.toBeNull();
    const submit = screen.getByRole("button", { name: /submit/i });
    expect(actions).toContainElement(submit);
    expect(actions).toContainElement(screen.getByRole("button", { name: "关闭" }));
    fireEvent.click(submit);

    expect(onSubmit).toHaveBeenCalledWith({ text: "abc" });
  });
});
