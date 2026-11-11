import { expect, test, type Locator, type Page } from "@playwright/test";

import { createState, installApiRoutes } from "./fixtures";

async function centerY(control: Locator): Promise<number> {
  const box = await control.boundingBox();
  if (box === null) {
    throw new Error("control box missing");
  }
  return box.y + box.height / 2;
}

async function panelHeight(chart: Locator): Promise<number> {
  const box = await chart.boundingBox();
  if (box === null) {
    throw new Error("chart box missing");
  }
  return box.height;
}

async function secondaryCanvasHeights(page: Page): Promise<number[]> {
  const heights = await page.locator("canvas").evaluateAll((canvases) =>
    canvases.map((canvas) => canvas.getBoundingClientRect().height),
  );
  return [...new Set(
    heights
      .filter((height) => height > 0 && height <= 160 && height !== 28)
      .map((height) => Math.round(height * 100) / 100),
  )].sort((left, right) => left - right);
}

async function addIndicator(page: Page, label: string): Promise<void> {
  await page.getByRole("button", { name: "添加指标" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByText(label).click();
  await dialog.getByRole("button", { name: /添\s*加/ }).click();
  await expect(dialog).toHaveCount(0);
}

test.describe("chart analysis journey", () => {
  test("selects a stock, adds a main signal and an RSI pane, and edits parameters", async ({
    page,
  }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/analysis");

    await expect(page.getByRole("link", { name: "图表分析" })).toBeVisible();

    const search = page.getByRole("combobox", { name: "股票搜索" });
    await search.fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();

    const chart = page.getByTestId("financial-chart");
    await expect(chart).toBeVisible();

    await page.getByRole("button", { name: "添加指标" }).click();
    const picker = page.getByRole("dialog");
    await picker.getByText("Donchian Breakout").click();
    await picker.getByRole("button", { name: /添\s*加/ }).click();
    await expect(page.getByText("Donchian Breakout (window=2)")).toBeVisible();

    await page.getByRole("button", { name: "添加指标" }).click();
    const second = page.getByRole("dialog");
    await second.getByText("Relative Strength Index").click();
    await second.getByRole("button", { name: /添\s*加/ }).click();
    await expect(page.getByText("Relative Strength Index (window=2)")).toBeVisible();

    const summary = page.getByRole("region", { name: "图表数据摘要" });
    await expect(summary).toContainText("共 4 根 K 线");
    await expect(summary).toContainText("Previous 2-bar high");
    await expect(summary).toContainText("RSI (2)");
    await expect(summary).toContainText("1 个标记");

    await page.getByRole("button", { name: "编辑参数" }).first().click();
    const editor = page.getByRole("dialog");
    const windowInput = editor.getByRole("spinbutton");
    await windowInput.fill("3");
    await editor.getByRole("button", { name: /保\s*存/ }).click();

    await expect(page.getByText("Donchian Breakout (window=3)")).toBeVisible();
  });

  test("switches between daily, weekly, and monthly bars", async ({ page }) => {
    const state = createState();
    await installApiRoutes(page, state);
    const requested: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname === "/api/v1/bars") {
        requested.push(url.searchParams.get("timeframe") ?? "");
      }
    });

    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();
    await expect(page.getByTestId("financial-chart")).toBeVisible();

    await page.getByText("周线", { exact: true }).click();
    await expect.poll(() => requested).toContain("1w");

    await page.getByText("月线", { exact: true }).click();
    await expect.poll(() => requested).toContain("1M");
  });

  test("keeps chart geometry stable while loading in the info band", async ({
    page,
  }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.route("**/api/v1/bars?**", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 200));
      await route.fallback();
    });
    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();
    const chart = page.getByTestId("financial-chart");
    await expect(chart).toBeVisible();
    const before = await chart.boundingBox();
    expect(before).not.toBeNull();

    await page.getByText("月线", { exact: true }).click();
    const loading = page.getByTestId("financial-chart-loading");
    await expect(loading).toBeVisible();
    await expect(loading).toHaveText("正在加载历史数据");
    await expect(loading).toHaveCSS("height", "48px");
    await expect(loading).toHaveCSS("position", "relative");
    expect(
      await loading.evaluate(
        (element) => element.parentElement?.dataset.testid,
      ),
    ).toBe("financial-chart-info");
    const during = await chart.boundingBox();
    expect(during).not.toBeNull();
    expect({ height: during?.height, y: during?.y }).toEqual({
      height: before?.height,
      y: before?.y,
    });

    await expect(loading).toHaveCount(0);
    const after = await chart.boundingBox();
    expect(after).not.toBeNull();
    expect({ height: after?.height, y: after?.y }).toEqual({
      height: before?.height,
      y: before?.y,
    });
  });

  test("keeps candles uncovered during older-history loading", async ({ page }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.route("**/api/v1/bars?**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.has("end")) {
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
      await route.fallback();
    });
    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();
    const chart = page.getByTestId("financial-chart");
    await expect(chart).toBeVisible();
    const before = await chart.boundingBox();
    expect(before).not.toBeNull();
    const plot = page.getByTestId("financial-chart-plot");
    const plotBox = await plot.boundingBox();
    expect(plotBox).not.toBeNull();
    if (plotBox !== null) {
      await page.mouse.move(
        plotBox.x + plotBox.width / 2,
        plotBox.y + plotBox.height / 2,
      );
      await page.mouse.wheel(0, 500);
    }
    const loading = page.getByTestId("financial-chart-loading");
    await expect(loading).toBeVisible();
    await expect(loading).toHaveCSS("position", "relative");
    const during = await chart.boundingBox();
    expect(during).not.toBeNull();
    expect({ height: during?.height, y: during?.y }).toEqual({
      height: before?.height,
      y: before?.y,
    });
    await expect(loading).toHaveCount(0);
    const after = await chart.boundingBox();
    expect(after).not.toBeNull();
    expect({ height: after?.height, y: after?.y }).toEqual({
      height: before?.height,
      y: before?.y,
    });
  });

  test("shows empty-database guidance instead of a blank chart", async ({
    page,
  }) => {
    const state = createState();
    state.emptyDatabase = true;
    await installApiRoutes(page, state);

    await page.goto("/analysis");

    await expect(page.getByText(/尚未同步任何证券数据/)).toBeVisible();
    await expect(page.getByText(/启用并立即执行/)).toBeVisible();
  });

  test("keeps healthy indicators visible when one calculation fails", async ({
    page,
  }) => {
    const state = createState();
    state.rsiFails = true;
    await installApiRoutes(page, state);

    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();

    for (const label of ["Relative Strength Index", "Donchian Breakout"]) {
      await page.getByRole("button", { name: "添加指标" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText(label).click();
      await dialog.getByRole("button", { name: /添\s*加/ }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }

    await expect(page.getByText(/needs at least 3 bars/).first()).toBeVisible();
    await expect(page.getByTestId("financial-chart")).toBeVisible();
    await expect(
      page.getByRole("region", { name: "图表数据摘要" }),
    ).toContainText("Previous 2-bar high");
  });

  test("does not overflow horizontally at a mobile width", async ({ page }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();
    await expect(page.getByTestId("financial-chart")).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

test.describe("tradingview-style chrome", () => {
  test("keeps symbol, timeframe and indicator controls on the chart, and shows OHLC in the top-left", async ({
    page,
  }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/analysis");

    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();
    const chart = page.getByTestId("financial-chart");
    await expect(chart).toBeVisible();

    // All three selectors are descendants of the chart panel, not a sibling card.
    const searchControl = chart.getByRole("combobox", { name: "股票搜索" });
    const timeframeControl = chart.getByRole("radiogroup", { name: "周期" });
    const addControl = chart.getByRole("button", { name: "添加指标" });
    await expect(searchControl).toBeVisible();
    await expect(timeframeControl).toBeVisible();
    await expect(addControl).toBeVisible();
    const centers = await Promise.all([
      centerY(searchControl),
      centerY(timeframeControl),
      centerY(addControl),
    ]);
    expect(Math.abs(centers[0] - centers[1])).toBeLessThanOrEqual(2);
    expect(Math.abs(centers[0] - centers[2])).toBeLessThanOrEqual(2);

    // The in-chart legend idles on the newest bar and marks it as such.
    const header = page.getByTestId("chart-header");
    await expect(header).toContainText("AAA");
    await expect(header).toContainText("日线");
    // The timeframe appears twice: once in the toolbar, once in the legend.
    await expect(page.getByTestId("chart-header-date")).toContainText("最新");

    // Hovering the candles retargets the legend to the hovered bar.
    const box = await chart.boundingBox();
    if (box === null) {
      throw new Error("chart box missing");
    }
    // The fixture holds four bars and the library right-aligns sparse data,
    // so sweep the right part of the pane until the crosshair hits a candle.
    for (const fx of [0.93, 0.96, 0.9, 0.85]) {
      for (const fy of [0.3, 0.45, 0.6]) {
        await page.mouse.move(
          box.x + box.width * fx,
          box.y + box.height * fy,
        );
        const date = await page.getByTestId("chart-header-date").textContent();
        if (date !== null && !date.includes("最新")) {
          break;
        }
      }
      const date = await page.getByTestId("chart-header-date").textContent();
      if (date !== null && !date.includes("最新")) {
        break;
      }
    }
    await expect(page.getByTestId("chart-header-date")).not.toContainText(
      "最新",
      { timeout: 5_000 },
    );
    await expect(page.getByTestId("chart-header-open")).toBeVisible();
    await expect(page.getByTestId("chart-header-close")).toBeVisible();
  });

  test("grows only by secondary pane heights, then shrinks on hide and remove", async ({
    page,
  }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();

    const chart = page.getByTestId("financial-chart");
    await expect(chart).toBeVisible();
    const plot = page.getByTestId("financial-chart-plot");
    const initialPlotBox = await plot.boundingBox();
    if (initialPlotBox === null) {
      throw new Error("plot box missing");
    }
    const baseHeight = await panelHeight(chart);

    await addIndicator(page, "Donchian Breakout");
    await expect(page.getByText("Donchian Breakout (window=2)")).toBeVisible();
    await expect.poll(() => panelHeight(chart)).toBe(baseHeight);
    await expect
      .poll(async () => (await plot.boundingBox())?.y ?? 0)
      .toBeGreaterThan(initialPlotBox.y);
    const infoBox = await page.getByTestId("financial-chart-info").boundingBox();
    const shiftedPlotBox = await plot.boundingBox();
    if (infoBox === null || shiftedPlotBox === null) {
      throw new Error("chart layout box missing");
    }
    expect(infoBox.y + infoBox.height).toBeLessThanOrEqual(shiftedPlotBox.y);
    const mainHeight = await panelHeight(chart);

    await addIndicator(page, "Relative Strength Index");
    await expect(page.getByText("Relative Strength Index (window=2)")).toBeVisible();
    await expect.poll(() => panelHeight(chart)).toBe(mainHeight + 160);
    const oneRsiHeight = await panelHeight(chart);

    await addIndicator(page, "Relative Strength Index");
    await expect(page.getByTestId(/^indicator-legend-/)).toHaveCount(3);
    await expect.poll(() => panelHeight(chart)).toBe(oneRsiHeight + 160);
    const twoRsiHeight = await panelHeight(chart);

    const firstRsiRow = page
      .getByTestId(/^indicator-legend-/)
      .filter({ hasText: "Relative Strength Index" })
      .first();
    await firstRsiRow.getByRole("button", { name: /隐藏/ }).click();
    await expect.poll(() => panelHeight(chart)).toBe(twoRsiHeight - 160);
    await firstRsiRow.getByRole("button", { name: /显示/ }).click();
    await expect.poll(() => panelHeight(chart)).toBe(twoRsiHeight);

    await page
      .getByRole("button", { name: /移除 Donchian Breakout/ })
      .click();
    await expect.poll(() => panelHeight(chart)).toBe(twoRsiHeight);
    await page
      .getByRole("button", { name: /移除 Relative Strength Index/ })
      .first()
      .click();
    await expect.poll(() => panelHeight(chart)).toBe(baseHeight + 160);
    await page
      .getByRole("button", { name: /移除 Relative Strength Index/ })
      .click();
    await expect.poll(() => panelHeight(chart)).toBe(baseHeight);
  });

  test("caps height at two panes, equalizes additional panes and preserves timeframe layouts", async ({
    page,
  }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();
    const chart = page.getByTestId("financial-chart");

    await addIndicator(page, "Donchian Breakout");
    await addIndicator(page, "Relative Strength Index");
    await addIndicator(page, "Relative Strength Index");
    await expect(page.getByTestId(/^indicator-pane-legend-/)).toHaveCount(2);
    const cappedHeight = await panelHeight(chart);
    const mainInfo = page.getByTestId("financial-chart-info");
    await expect(mainInfo).toContainText("Donchian Breakout");
    await expect(mainInfo).not.toContainText("Relative Strength Index");

    await addIndicator(page, "Relative Strength Index");
    await expect(page.getByTestId(/^indicator-pane-legend-/)).toHaveCount(3);
    await expect.poll(() => panelHeight(chart)).toBe(cappedHeight);
    await expect.poll(() => secondaryCanvasHeights(page)).toEqual([128]);
    await expect(
      page.getByTestId(/^indicator-pane-legend-/).filter({
        hasText: "Relative Strength Index",
      }),
    ).toHaveCount(3);

    await addIndicator(page, "Relative Strength Index");
    await expect(page.getByTestId(/^indicator-pane-legend-/)).toHaveCount(4);
    await expect.poll(() => panelHeight(chart)).toBe(cappedHeight);
    await expect.poll(() => secondaryCanvasHeights(page)).toEqual([102]);

    for (const timeframe of ["周线", "月线"]) {
      await page.getByText(timeframe, { exact: true }).click();
      expect(await panelHeight(chart)).toBe(cappedHeight);
      await expect.poll(() => panelHeight(chart)).toBe(cappedHeight);
      await expect.poll(() => secondaryCanvasHeights(page)).toEqual([102]);
    }

    for (let index = 4; index < 10; index += 1) {
      await addIndicator(page, "Relative Strength Index");
    }
    const compactLegends = page.getByTestId(/^indicator-pane-legend-/);
    await expect(compactLegends).toHaveCount(10);
    await expect.poll(() => panelHeight(chart)).toBe(cappedHeight);
    await expect.poll(() => secondaryCanvasHeights(page)).toEqual([27]);
    const boxes = await compactLegends.evaluateAll((legends) =>
      legends.map((legend) => {
        const box = legend.getBoundingClientRect();
        return { top: box.top, bottom: box.bottom };
      }),
    );
    for (let index = 1; index < boxes.length; index += 1) {
      expect(boxes[index].top).toBeGreaterThanOrEqual(boxes[index - 1].bottom);
    }
  });

  test("preserves symbol and indicators when leaving and returning to analysis", async ({
    page,
  }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/analysis");
    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();
    await addIndicator(page, "Donchian Breakout");
    await addIndicator(page, "Relative Strength Index");
    await expect(page.getByTestId(/^indicator-pane-legend-/)).toHaveCount(1);

    await page.getByRole("link", { name: "Task 管理" }).click();
    await expect(page).toHaveURL(/\/tasks$/);
    await page.getByRole("link", { name: "图表分析" }).click();

    await expect(page).toHaveURL(/\/analysis$/);
    await expect(page.getByRole("combobox", { name: "股票搜索" })).toHaveValue(
      "AAA · Alpha Corp",
    );
    await expect(page.getByText("Donchian Breakout (window=2)")).toBeVisible();
    await expect(page.getByTestId(/^indicator-pane-legend-/)).toHaveCount(1);
  });

  test("manages indicators from the in-chart legend", async ({ page }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/analysis");

    await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
    await page.getByText("AAA · Alpha Corp").click();

    await page.getByRole("button", { name: "添加指标" }).click();
    const picker = page.getByRole("dialog");
    await picker.getByText("Relative Strength Index").click();
    await picker.getByRole("button", { name: /添\s*加/ }).click();

    // The legend row appears over the chart, not in a side column.
    const row = page.getByTestId(/^indicator-legend-/).first();
    await expect(row).toBeVisible();
    await expect(row).toContainText("Relative Strength Index");

    // Hiding keeps the row but dims it.
    await row.getByRole("button", { name: /隐藏/ }).click();
    await expect(
      page.getByRole("button", { name: /显示 Relative Strength Index/ }),
    ).toBeVisible();

    // Removing drops the row entirely.
    await page
      .getByRole("button", { name: /移除 Relative Strength Index/ })
      .click();
    await expect(page.getByTestId(/^indicator-legend-/)).toHaveCount(0);
  });
});
