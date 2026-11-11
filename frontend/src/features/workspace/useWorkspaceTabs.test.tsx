import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useWorkspaceTabs } from "./useWorkspaceTabs";

function TestWorkspace() {
  const result = useWorkspaceTabs(<div />);
  return (
    <div>
      <div data-testid="active-key">{result.activeKey}</div>
      <div data-testid="tab-keys">
        {result.tabs.map((tab) => tab.key).join(",")}
      </div>
      <button data-testid="go-tasks" onClick={() => result.navigate("/tasks")} />
      <button data-testid="go-analysis" onClick={() => result.navigate("/analysis?ignored=true#section")} />
      <button data-testid="close-analysis" onClick={() => result.closeTab("/analysis")} />
      <button data-testid="close-tasks" onClick={() => result.closeTab("/tasks")} />
    </div>
  );
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: "/analysis", element: <TestWorkspace /> },
      { path: "/tasks", element: <TestWorkspace /> },
      { path: "/settings/data-sources", element: <TestWorkspace /> },
      { path: "/blank", element: <TestWorkspace /> },
    ],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

describe("useWorkspaceTabs", () => {
  it("opens a route once and only activates it on repeat navigation", () => {
    renderAt("/analysis");
    expect(screen.getByTestId("tab-keys")).toHaveTextContent("/analysis");
    fireEvent.click(screen.getByTestId("go-tasks"));
    expect(screen.getByTestId("tab-keys")).toHaveTextContent("/analysis,/tasks");
    expect(screen.getByTestId("active-key")).toHaveTextContent("/tasks");
    fireEvent.click(screen.getByTestId("go-analysis"));
    expect(screen.getByTestId("tab-keys")).toHaveTextContent("/analysis,/tasks");
    expect(screen.getByTestId("active-key")).toHaveTextContent("/analysis");
  });

  it("activates a neighboring tab when the active tab closes", () => {
    renderAt("/analysis");
    fireEvent.click(screen.getByTestId("go-tasks"));
    fireEvent.click(screen.getByTestId("close-tasks"));
    expect(screen.getByTestId("tab-keys")).toHaveTextContent("/analysis");
    expect(screen.getByTestId("active-key")).toHaveTextContent("/analysis");
  });

  it("shows the blank route after the last tab closes", () => {
    renderAt("/analysis");
    fireEvent.click(screen.getByTestId("close-analysis"));
    expect(screen.getByTestId("tab-keys")).toBeEmptyDOMElement();
    expect(screen.getByTestId("active-key")).toHaveTextContent("/blank");
  });
});
