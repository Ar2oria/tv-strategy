import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/errors";
import { ErrorState } from "./ErrorState";

describe("ErrorState", () => {
  it("shows the sanitized ApiError message", () => {
    render(<ErrorState error={new ApiError("Request validation failed", { status: 422, code: "validation_error" })} />);

    expect(screen.getByText("Request validation failed")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("hides unknown error details behind a static message", () => {
    render(<ErrorState error={new Error("SECRET_TOKEN=raw-secret")} />);

    expect(
      screen.getByText("An unexpected error occurred. Please try again."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/raw-secret/)).not.toBeInTheDocument();
  });

  it("invokes retry when a handler is supplied", async () => {
    const onRetry = vi.fn();
    render(
      <ErrorState error={new ApiError("Network request failed", { status: 0, code: "network_error" })} onRetry={onRetry} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
