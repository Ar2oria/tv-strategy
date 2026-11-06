import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IndicatorLegend, type IndicatorLegendItem } from "./IndicatorLegend";
import { getChartTheme } from "./theme";

const theme = getChartTheme("light");

function item(overrides: Partial<IndicatorLegendItem> = {}): IndicatorLegendItem {
  return {
    instanceId: "r1",
    label: "RSI (window=14)",
    values: [{ id: "r1:rsi", value: 55.5, color: "#2962ff" }],
    error: null,
    visible: true,
    ...overrides,
  };
}

describe("IndicatorLegend", () => {
  it("renders nothing when no indicator is active", () => {
    const { container } = render(
      <IndicatorLegend
        items={[]}
        theme={theme}
        onEdit={vi.fn()}
        onToggleVisibility={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the label and formatted values for the active bar", () => {
    render(
      <IndicatorLegend
        items={[item()]}
        theme={theme}
        onEdit={vi.fn()}
        onToggleVisibility={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    const row = screen.getByTestId("indicator-legend-r1");
    expect(row).toHaveTextContent("RSI (window=14)");
    expect(row).toHaveTextContent("55.50");
  });

  it("reports failures instead of stale values", () => {
    render(
      <IndicatorLegend
        items={[item({ error: "计算失败", values: [] })]}
        theme={theme}
        onEdit={vi.fn()}
        onToggleVisibility={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByTestId("indicator-legend-r1")).toHaveTextContent(
      "计算失败",
    );
  });

  it("dims hidden indicators and swaps the eye affordance", () => {
    render(
      <IndicatorLegend
        items={[item({ visible: false })]}
        theme={theme}
        onEdit={vi.fn()}
        onToggleVisibility={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    const row = screen.getByTestId("indicator-legend-r1");
    expect(row).toHaveStyle({ opacity: "0.45" });
    expect(
      screen.getByRole("button", { name: "显示 RSI (window=14)" }),
    ).toBeInTheDocument();
  });

  it("forwards edit, visibility, and remove actions", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const onToggleVisibility = vi.fn();
    const onRemove = vi.fn();
    render(
      <IndicatorLegend
        items={[item()]}
        theme={theme}
        onEdit={onEdit}
        onToggleVisibility={onToggleVisibility}
        onRemove={onRemove}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "编辑参数 RSI (window=14)" }),
    );
    await user.click(screen.getByRole("button", { name: "隐藏 RSI (window=14)" }));
    await user.click(screen.getByRole("button", { name: "移除 RSI (window=14)" }));

    expect(onEdit).toHaveBeenCalledWith("r1");
    expect(onToggleVisibility).toHaveBeenCalledWith("r1");
    expect(onRemove).toHaveBeenCalledWith("r1");
  });
});
