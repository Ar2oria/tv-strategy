import { expect, test } from "@playwright/test";

import { createState, installApiRoutes } from "./fixtures";

test.describe("task management journey", () => {
  test("configures cron, runs immediately, and reads logs", async ({ page }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/tasks");

    await expect(page.getByText("Synchronize market data")).toBeVisible();

    await page.getByRole("button", { name: "配置 market.sync" }).click();
    const drawer = page.getByRole("dialog");
    const cron = drawer.getByLabel("Cron 表达式");
    await cron.fill("30 8 * * 1-5");
    await drawer.getByRole("button", { name: /保\s*存配置/ }).click();
    await expect(drawer.getByLabel("Cron 表达式")).toHaveValue("30 8 * * 1-5");

    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    const runResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/tasks/market.sync/runs") &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "立即执行 market.sync" }).click();
    expect((await runResponse).status()).toBe(202);

    await page.getByRole("button", { name: "历史 market.sync" }).click();
    await expect(page.getByText("Synchronized 2 instruments")).toBeVisible();
  });

  test("rejects an invalid cron before sending it", async ({ page }) => {
    const state = createState();
    await installApiRoutes(page, state);
    let writes = 0;
    page.on("request", (request) => {
      if (request.method() === "PUT") {
        writes += 1;
      }
    });

    await page.goto("/tasks");
    await page.getByRole("button", { name: "配置 market.sync" }).click();
    const drawer = page.getByRole("dialog");
    await drawer.getByLabel("Cron 表达式").fill("* * *");
    await drawer.getByRole("button", { name: /保\s*存配置/ }).click();

    await expect(drawer.getByText(/恰好 5 个字段/)).toBeVisible();
    expect(writes).toBe(0);
  });

  test("refreshes and asks to reapply after a revision conflict", async ({
    page,
  }) => {
    const state = createState();
    state.revisionConflict = true;
    await installApiRoutes(page, state);
    await page.goto("/tasks");

    await page.getByRole("button", { name: "配置 market.sync" }).click();
    const drawer = page.getByRole("dialog");
    await drawer.getByLabel("Cron 表达式").fill("15 9 * * *");
    await drawer.getByRole("button", { name: /保\s*存配置/ }).click();

    await expect(drawer.getByText(/配置已被其他页面修改/)).toBeVisible();
    await expect(drawer.getByLabel("Cron 表达式")).toHaveValue("0 6 * * *");
  });
});

test.describe("settings journey", () => {
  test("edits hot settings and confirms they apply without a restart", async ({
    page,
  }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/settings");

    await expect(page.getByText("A 股", { exact: true })).toBeVisible();
    await expect(page.getByText("并发固定为 1").first()).toBeVisible();
    await expect(page.getByLabel("加密货币 交易对 1")).toHaveValue("BTC/USDT");

    const timezone = page.getByLabel("调度时区");
    await timezone.fill("Asia/Shanghai");
    const timeout = page.getByLabel("A 股 请求超时");
    await timeout.fill("30");

    await page.getByRole("button", { name: "保存设置" }).click();

    await expect(page.getByText("设置已保存并立即生效。")).toBeVisible();
    await expect(page.getByText(/当前修订号：6/)).toBeVisible();
  });

  test("keeps unsaved edits after a revision conflict and reloads the newest revision", async ({
    page,
  }) => {
    const state = createState();
    state.revisionConflict = true;
    await installApiRoutes(page, state);
    await page.goto("/settings");

    await page.getByLabel("调度时区").fill("Europe/Berlin");
    await page.getByRole("button", { name: "保存设置" }).click();

    await expect(page.getByText(/配置已被其他页面修改/)).toBeVisible();
    await expect(page.getByText(/当前修订号：6/)).toBeVisible();
  });
});
