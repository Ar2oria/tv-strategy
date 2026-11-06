import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { routes } from "./router";

vi.mock("./features/analysis/AnalysisPage", () => ({
  AnalysisPage: () => <div>analysis page</div>,
}));

function renderRoutes(initialPath: string) {
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("App shell", () => {
  it("renders navigation and redirects the root path to the analysis page", async () => {
    renderRoutes("/");

    expect(await screen.findByText("analysis page")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "图表分析" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Task 管理" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "系统设置" })).toBeInTheDocument();
  });

  it("marks the active section as selected", async () => {
    renderRoutes("/analysis");

    expect(await screen.findByText("analysis page")).toBeInTheDocument();
    const selected = document.querySelector(".ant-menu-item-selected");
    expect(selected?.textContent).toContain("图表分析");
  });

  it("redirects unknown paths to the analysis page", async () => {
    renderRoutes("/nope");

    expect(await screen.findByText("analysis page")).toBeInTheDocument();
  });
});
