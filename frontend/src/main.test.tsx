import { act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("application bootstrap", { timeout: 20000 }, () => {
  afterEach(() => {
    vi.resetModules();
    document.body.innerHTML = "";
  });

  it("mounts the application into the root element", async () => {
    document.body.innerHTML = '<div id="root"></div>';
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ success: true, data: [], error: null, meta: {} }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await act(async () => {
      await import("./main");
    });

    expect(
      document.querySelector("#root")?.childElementCount,
    ).toBeGreaterThan(0);
    vi.unstubAllGlobals();
  });

  it("fails fast when the root element is missing", async () => {
    await expect(import("./main")).rejects.toThrow(
      "Application root element is missing",
    );
  });
});
