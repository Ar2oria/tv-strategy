import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    expect(screen.getByText("系统设置")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "数据源配置" })).toBeInTheDocument();
  });

  it("places the brand and all navigation in a dark left sidebar", async () => {
    renderRoutes("/analysis");

    const sidebar = await screen.findByTestId("app-sidebar");
    expect(sidebar).toHaveAttribute("data-theme", "dark");
    expect(within(sidebar).getByText("TV Strategy")).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "图表分析" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Task 管理" })).toBeInTheDocument();
    expect(within(sidebar).getByText("系统设置")).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "数据源配置" })).toBeInTheDocument();
  });

  it("marks the active section as selected", async () => {
    renderRoutes("/analysis");

    expect(await screen.findByText("analysis page")).toBeInTheDocument();
    const selected = document.querySelector(".ant-menu-item-selected");
    expect(selected?.textContent).toContain("图表分析");
  });

  it("opens the tasks route with navigation", async () => {
    renderRoutes("/tasks");
    expect(await screen.findByRole("link", { name: "图表分析" })).toBeInTheDocument();
  });

  it("redirects unknown paths to the analysis page", async () => {
    renderRoutes("/nope");

    expect(await screen.findByText("analysis page")).toBeInTheDocument();
  });

  it("collapses and expands the system settings submenu", async () => {
    renderRoutes("/analysis");
    const toggle = await screen.findByText("系统设置");
    expect(screen.getByRole("link", { name: "数据源配置" })).toBeVisible();

    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "数据源配置" })).not.toBeVisible(),
    );
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "数据源配置" })).toBeVisible(),
    );
  });
});
