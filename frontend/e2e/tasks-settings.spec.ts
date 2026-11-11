import { expect, test } from "@playwright/test";

import { createState, installApiRoutes } from "./fixtures";
import { cryptoTaskFixture } from "../src/test/cryptoTaskFixture";

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

test("presents crypto pairs in a single-column dark form", async ({ page }, testInfo) => {
  const state = createState();
  state.task = structuredClone(cryptoTaskFixture);
  state.task.params_schema = {
    ...state.task.params_schema,
    properties: {
      ...state.task.params_schema.properties,
      optional_mode: {
        title: "Optional Mode",
        type: "string",
        enum: ["alpha", "beta"],
      },
    },
  };
  await installApiRoutes(page, state);
  await page.goto("/tasks");
  await page.getByRole("button", { name: "配置 market.sync_crypto_daily" }).click();
  const drawer = page.getByRole("dialog");

  await expect(drawer.locator(".ant-col-12")).toHaveCount(0);
  await expect(drawer.locator(".ant-form-item-label").first()).toHaveCSS(
    "text-align",
    /left|start/,
  );
  await expect(drawer).toHaveCSS(
    "background-color",
    "rgb(32, 38, 52)",
  );
  const symbol = drawer.locator("#root_spot_pairs_0_symbol");
  await expect(drawer.locator(".task-schema-form")).toHaveCSS(
    "background-color",
    "rgb(38, 46, 64)",
  );
  await expect(drawer.locator(".task-schema-form fieldset#root")).toHaveCSS(
    "background-color",
    /^(?:rgba\(0, 0, 0, 0\)|rgb\(38, 46, 64\))$/,
  );
  await expect(symbol).toHaveCSS("color", "rgb(230, 233, 240)");
  await expect(symbol).toHaveCSS("background-color", "rgb(32, 38, 52)");
  await expect(drawer.locator("#root_spot_pairs_0")).toHaveCSS(
    "background-color",
    "rgb(38, 46, 64)",
  );
  await expect(symbol).toHaveCSS("border-color", "rgb(52, 64, 84)");
  const symbolWrapper = drawer.locator("#root_spot_pairs_0 .ant-input-affix-wrapper").first();
  await expect(symbolWrapper).toHaveCSS("background-color", "rgb(32, 38, 52)");
  await expect(symbolWrapper).toHaveCSS("border-color", "rgb(52, 64, 84)");
  await expect(drawer.getByLabel("Cron 表达式")).toHaveCSS(
    "background-color",
    "rgb(32, 38, 52)",
  );
  await expect(drawer.locator("#root_spot_pairs_0 .ant-select").first()).toHaveCSS(
    "background-color",
    "rgb(32, 38, 52)",
  );
  await expect(drawer.locator(".ant-select-placeholder").first()).toHaveCSS(
    "color",
    "rgb(166, 173, 189)",
  );
  await expect(drawer.locator(".ant-select-suffix").first()).toHaveCSS(
    "color",
    "rgb(230, 233, 240)",
  );
  const checkbox = drawer.locator(".ant-checkbox").first();
  await expect(checkbox).toHaveCSS("background-color", "rgb(32, 38, 52)");
  await expect(checkbox).toHaveCSS("border-color", "rgb(52, 64, 84)");
  await drawer.getByRole("checkbox", { name: "Full Refresh" }).check();
  await expect(checkbox).toHaveCSS("background-color", "rgb(41, 98, 255)");
  await expect(drawer.getByRole("checkbox", { name: "Full Refresh" })).toBeChecked();
  await drawer.getByRole("checkbox", { name: "Full Refresh" }).uncheck();

  const schedulingSwitch = drawer.locator(".ant-switch").first();
  await expect(schedulingSwitch).toHaveCSS("background-color", "rgb(52, 64, 84)");
  await schedulingSwitch.click();
  await expect(schedulingSwitch).toHaveCSS("background-color", "rgb(41, 98, 255)");
  await schedulingSwitch.click();
  const numberInput = drawer.locator(".ant-input-number").first();
  await numberInput.hover();
  const stepperActions = numberInput.locator(".ant-input-number-actions");
  const stepperAction = stepperActions.locator(".ant-input-number-action").first();
  await expect(stepperAction).toHaveCSS("background-color", "rgb(32, 38, 52)");
  await expect(stepperAction).toHaveCSS("color", "rgb(230, 233, 240)");
  await stepperAction.hover();
  await expect(stepperAction).toHaveCSS("background-color", "rgb(38, 46, 64)");

  const universeInput = drawer.locator("#root_universe_codes");
  const symbolsInput = drawer.locator("#root_symbols");
  await expect(universeInput).toHaveCSS("height", "72px");
  await expect(symbolsInput).toHaveCSS("height", "72px");
  await expect(drawer.locator("#root_universe_codes__add")).toHaveCount(0);
  await expect(drawer.locator("#root_symbols__add")).toHaveCount(0);
  expect(
    await universeInput.evaluate((element) => getComputedStyle(element, "::placeholder").color),
  ).toBe("rgb(166, 173, 189)");
  expect(
    await symbolsInput.evaluate((element) => getComputedStyle(element, "::placeholder").color),
  ).toBe("rgb(166, 173, 189)");
  await universeInput.fill("nasdaq100, soxx");
  await symbolsInput.fill("BINANCE:BTC/USDT, OKX:BTC/USDT");
  const actions = drawer.locator(".schema-form-actions");
  await expect(actions).toHaveCSS("display", "flex");
  await expect(actions).toHaveCSS("flex-direction", "row");
  await expect(actions.getByRole("button", { name: /保\s*存配置/ })).toBeVisible();
  await expect(actions.getByRole("button", { name: /关\s*闭/ })).toBeVisible();
  const desktopBox = await drawer.boundingBox();
  expect(desktopBox).not.toBeNull();
  expect(desktopBox?.width).toBeLessThanOrEqual(640);

  await symbol.fill("ETH/USDT");
  const update = page.waitForResponse(
    (response) =>
      response.url().endsWith("/tasks/market.sync_crypto_daily/config") &&
      response.request().method() === "PUT",
  );
  await drawer.getByRole("button", { name: /保\s*存配置/ }).click();
  const response = await update;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().params.spot_pairs).toEqual([
    { exchange: "binance", symbol: "ETH/USDT" },
  ]);
  expect(response.request().postDataJSON().params.universe_codes).toEqual([
    "nasdaq100",
    "soxx",
  ]);
  expect(response.request().postDataJSON().params.symbols).toEqual([
    "BINANCE:BTC/USDT",
    "OKX:BTC/USDT",
  ]);
  await page.screenshot({
    path: testInfo.outputPath("crypto-form-desktop.png"),
    fullPage: true,
  });

  await page.setViewportSize({ width: 375, height: 812 });
  await expect(symbol).toHaveCSS("background-color", "rgb(32, 38, 52)");
  await expect(symbol).toHaveCSS("color", "rgb(230, 233, 240)");
  await expect(
    drawer.locator("#root_spot_pairs_0 .ant-select").first(),
  ).toHaveCSS("background-color", "rgb(32, 38, 52)");
  await expect
    .poll(() => drawer.evaluate((element) => element.getBoundingClientRect().width))
    .toBeLessThanOrEqual(375);
  const mobileBox = await drawer.boundingBox();
  expect(mobileBox).not.toBeNull();
  await expect(drawer).toBeVisible();
  expect(mobileBox?.width).toBeLessThanOrEqual(375);
  expect(mobileBox?.x).toBeGreaterThanOrEqual(0);
  expect((mobileBox?.x ?? 0) + (mobileBox?.width ?? 0)).toBeLessThanOrEqual(375);
  for (const control of [
    drawer.locator("#root_spot_pairs_0_symbol"),
    drawer.locator("#root_spot_pairs_0 .ant-select").first(),
  ]) {
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.width).toBeGreaterThanOrEqual(200);
  }
  const removeButton = drawer.locator("#root_spot_pairs_0__remove");
  const removeBox = await removeButton.boundingBox();
  expect(removeBox).not.toBeNull();
  expect(removeBox?.x).toBeGreaterThanOrEqual(0);
  expect((removeBox?.x ?? 0) + (removeBox?.width ?? 0)).toBeLessThanOrEqual(375);
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    )
    .toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("crypto-form-mobile.png"),
    fullPage: true,
  });
});

test.describe("settings journey", () => {
  test("group editing saves only the selected market", async ({ page }) => {
    const state = createState();
    await installApiRoutes(page, state);
    await page.goto("/settings");

    await expect(page.getByText("A 股", { exact: true })).toBeVisible();
    await expect(page.getByLabel("加密货币 交易对 1")).toHaveCount(0);
    await expect(page.getByText("现货交易对（交易所限定）")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "保存设置" })).toHaveCount(0);
    const timeout = page.getByLabel("A 股 请求超时");
    const aProvider = page.locator("[data-testid='market-group-a_share'] .ant-select");
    const aTimeout = page.locator("[data-testid='market-group-a_share'] .ant-input-number");
    await expect(aProvider).toHaveCSS("background-color", "rgb(32, 38, 52)");
    await expect(aProvider).toHaveCSS("border-color", "rgb(52, 64, 84)");
    await expect(aProvider).toHaveCSS("color", "rgb(166, 173, 189)");
    await expect(aTimeout).toHaveCSS("background-color", "rgb(32, 38, 52)");
    await expect(aTimeout).toHaveCSS("border-color", "rgb(52, 64, 84)");
    await expect(timeout).toBeDisabled();
    await page.getByRole("button", { name: "编辑 A 股" }).click();
    await aTimeout.hover();
    const groupAction = aTimeout.locator(".ant-input-number-action").first();
    await expect(groupAction).toHaveCSS("background-color", "rgb(32, 38, 52)");
    await expect(groupAction).toHaveCSS("color", "rgb(230, 233, 240)");
    await groupAction.hover();
    await expect(groupAction).toHaveCSS("background-color", "rgb(38, 46, 64)");
    await expect(aProvider).toHaveCSS("color", "rgb(230, 233, 240)");
    await expect(aTimeout).toHaveCSS("background-color", "rgb(32, 38, 52)");
    await timeout.fill("30");
    await page.getByRole("button", { name: "编辑 港股" }).click();
    const hkTimeout = page.getByLabel("港股 请求超时");
    await hkTimeout.fill("40");

    const firstWrite = page.waitForResponse(
      (response) => response.url().endsWith("/settings") && response.request().method() === "PUT",
    );
    await page.getByRole("button", { name: "保存 A 股" }).click();
    const first = await firstWrite;
    expect(first.request().postDataJSON().expected_revision).toBe(5);
    expect(first.request().postDataJSON().markets.a_share.request_timeout_seconds).toBe(30);
    expect(first.request().postDataJSON().markets.hk_stock.request_timeout_seconds).toBe(20);
    await expect(hkTimeout).toHaveValue("40.0");
    await expect(hkTimeout).toBeEnabled();
    await expect(timeout).toBeDisabled();

    const secondWrite = page.waitForResponse(
      (response) => response.url().endsWith("/settings") && response.request().method() === "PUT",
    );
    await page.getByRole("button", { name: "保存 港股" }).click();
    const second = await secondWrite;
    expect(second.request().postDataJSON().expected_revision).toBe(6);
    expect(second.request().postDataJSON().markets.a_share.request_timeout_seconds).toBe(30);
    expect(second.request().postDataJSON().markets.hk_stock.request_timeout_seconds).toBe(40);
    await expect(page.getByText("设置已保存并立即生效。")).toBeVisible();
    await expect(page.getByText(/当前修订号/)).toHaveCount(0);
  });

  test("keeps unsaved edits after a revision conflict and reloads the newest revision", async ({
    page,
  }) => {
    const state = createState();
    state.revisionConflict = true;
    await installApiRoutes(page, state);
    await page.goto("/settings");

    await page.getByRole("button", { name: "编辑 A 股" }).click();
    await page.getByLabel("A 股 请求超时").fill("45");
    await page.getByRole("button", { name: "保存 A 股" }).click();

    await expect(page.getByText(/配置已被其他页面修改/)).toBeVisible();
    await expect(page.getByText(/当前修订号/)).toHaveCount(0);
  });
});
