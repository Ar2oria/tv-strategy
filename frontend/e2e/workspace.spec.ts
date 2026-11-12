import { expect, test, type Page } from "@playwright/test";

import { createState, installApiRoutes } from "./fixtures";

async function addIndicator(page: Page): Promise<void> {
  await page.getByRole("button", { name: "添加指标" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByText("Relative Strength Index", { exact: true }).click();
  await dialog.getByRole("button", { name: /添\s*加/ }).click();
  await expect(dialog).toHaveCount(0);
}


test("workspace tabs keeps pages mounted and closes them without reopening", async ({
  page,
}) => {
  const state = createState();
  await installApiRoutes(page, state);
  await page.goto("/analysis");
  await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");
  await page.getByText("AAA · Alpha Corp").click();
  await addIndicator(page);
  await expect(page.getByTestId(/^indicator-pane-legend-/)).toHaveCount(1);

  await page.getByRole("link", { name: "Task 管理" }).click();
  await expect(page).toHaveURL(/\/tasks$/);
  await expect(page.getByTestId("financial-chart")).not.toBeVisible();
  await expect(page.getByRole("tab", { name: "图表分析" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Task 管理" })).toBeVisible();

  await page.getByRole("link", { name: "Task 管理" }).click();
  await expect(page.getByRole("tab", { name: "Task 管理" })).toHaveCount(1);

  await page.getByRole("tab", { name: "图表分析" }).click();
  await expect(page.getByTestId("financial-chart")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "股票搜索" })).toHaveValue(
    "AAA · Alpha Corp",
  );
  await expect(page.getByTestId(/^indicator-pane-legend-/)).toHaveCount(1);

  await page.getByRole("button", { name: "关闭 Task 管理" }).click();
  await expect(page.getByRole("tab", { name: "Task 管理" })).toHaveCount(0);
  await page.getByRole("button", { name: "关闭 图表分析" }).click();
  await expect(page).toHaveURL(/\/blank$/);
  await expect(page.getByText("暂无打开的页面")).toBeVisible();

  await page.getByRole("link", { name: "图表分析" }).click();
  await expect(page.getByRole("combobox", { name: "股票搜索" })).toHaveValue("");
});

test("opens data-source settings through the nested menu", async ({ page }) => {
  const state = createState();
  await installApiRoutes(page, state);
  await page.goto("/analysis");

  await page.getByText("系统设置").click();
  await page.getByRole("link", { name: "数据源配置" }).click();

  await expect(page).toHaveURL(/\/settings\/data-sources$/);
  await expect(page.getByText("数据源配置").last()).toBeVisible();
  await expect(page.getByRole("tab", { name: "数据源配置" })).toBeVisible();
});

test("keeps Task and Settings state when Analysis closes and reopens", async ({
  page,
}) => {
  const state = createState();
  await installApiRoutes(page, state);
  await page.goto("/analysis");
  await page.getByRole("combobox", { name: "股票搜索" }).fill("AAA");

  await page.getByRole("link", { name: "Task 管理" }).click();
  await page.getByRole("button", { name: "历史 market.sync" }).click();
  await expect(page.getByText("Synchronized 2 instruments")).toBeVisible();

  await page.getByRole("button", { name: "关闭 图表分析" }).click();
  await expect(page.getByText("Synchronized 2 instruments")).toBeVisible();

  await page.getByText("系统设置").click();
  await page.getByRole("link", { name: "数据源配置" }).click();
  const timeout = page.getByLabel("A 股 请求超时");
  await page.getByRole("button", { name: "编辑 A 股" }).click();
  await timeout.fill("45");

  await page.getByRole("link", { name: "图表分析" }).click();
  await expect(page.getByRole("combobox", { name: "股票搜索" })).toHaveValue("");
  await page.getByRole("tab", { name: "数据源配置" }).click();
  await expect(timeout).toHaveValue(/^45(?:\.0+)?$/);
});

test("tab appearance uses connected dark tabs", async ({ page }) => {
  const state = createState();
  await installApiRoutes(page, state);
  await page.goto("/analysis");
  await page.getByRole("link", { name: "Task 管理" }).click();

  const tablist = page.getByRole("tablist", { name: "已打开页面" });
  await expect(tablist).toHaveCSS("border-bottom", "1px solid rgb(42, 46, 57)");
  const active = page.getByRole("tab", { name: "Task 管理", selected: true });
  const shell = active.locator("xpath=..");
  await expect(shell).toHaveClass(/workspace-tab-active/);
  await expect(shell).toHaveCSS("background-color", "rgb(30, 34, 45)");
  await expect(shell).toHaveCSS("border-top-left-radius", "6px");
  await expect(shell).toHaveCSS("border-top-right-radius", "6px");
  await expect(shell).toHaveCSS("border-top-color", "rgb(41, 98, 255)");
  await expect(page.getByRole("button", { name: "关闭 Task 管理" })).toBeVisible();
});

test("keeps non-analysis content top spacing", async ({ page }) => {
  const state = createState();
  await installApiRoutes(page, state);
  await page.goto("/tasks");
  await expect(page.locator(".app-content")).toHaveCSS("padding-top", "16px");
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.locator(".app-content")).toHaveCSS("padding-top", "8px");
  await page.getByRole("link", { name: "图表分析" }).click();
  await expect(page.locator(".app-content")).toHaveCSS("padding-top", "0px");
});

test("settings menu collapses and expands", async ({ page }) => {
  const state = createState();
  await installApiRoutes(page, state);
  await page.goto("/analysis");
  const toggle = page.getByText("系统设置", { exact: true });
  const dataSources = page.getByRole("link", { name: "数据源配置" });
  await expect(dataSources).toBeVisible();

  await toggle.click();
  await expect(dataSources).toBeHidden();
  await toggle.click();
  await expect(dataSources).toBeVisible();
});
