import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Workspace } from "./Workspace";

describe("Workspace", () => {
  it("renders active cached content", () => {
    render(
      <Workspace
        tabs={[{ key: "/analysis", title: "图表分析", content: <div>analysis page</div> }]}
        activeKey="/analysis"
        closeTab={vi.fn()}
        navigate={vi.fn()}
      />,
    );
    expect(screen.getByText("analysis page")).toBeInTheDocument();
  });
});
