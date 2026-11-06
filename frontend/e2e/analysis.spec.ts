import { expect, test } from "@playwright/test";

import { createState, installApiRoutes } from "./fixtures";

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
    await expect(page.getByTestId("financial-chart")).toBeVisible();

    // The toolbar above the chart holds symbol, timeframe and add-indicator.
    await expect(page.getByRole("combobox", { name: "股票搜索" })).toBeVisible();
    await expect(
      page.getByRole("radiogroup", { name: "周期" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "添加指标" })).toBeVisible();

    // The in-chart legend idles on the newest bar and marks it as such.
    const header = page.getByTestId("chart-header");
    await expect(header).toContainText("AAA");
    await expect(header).toContainText("日线");
    // The timeframe appears twice: once in the toolbar, once in the legend.
    await expect(page.getByTestId("chart-header-date")).toContainText("最新");

    // Hovering the candles retargets the legend to the hovered bar.
    const chart = page.getByTestId("financial-chart");
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
