import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEventBase from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { taskPayload } from "../../test/apiFixtures";
import { cryptoTaskFixture } from "../../test/cryptoTaskFixture";
import type { TaskDescriptor } from "../../types/task";
import { TaskConfigDrawer } from "./TaskConfigDrawer";

const userEvent = userEventBase.setup({ delay: null });

describe("TaskConfigDrawer", () => {
  it("submits the current configuration through onSave", () => {
    const onSave = vi.fn();
    render(
      <TaskConfigDrawer
        task={{ ...(taskPayload as unknown as TaskDescriptor), revision: 9 }}
        saving={false}
        saveError={null}
        conflict={false}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    expect(onSave).toHaveBeenCalledWith({
      cron: taskPayload.cron,
      enabled: taskPayload.enabled,
      params: { value: 1 },
    });
  });

  it("keeps the masked iTiger token when saving other task settings", () => {
    const onSave = vi.fn();
    const base = taskPayload as unknown as TaskDescriptor;
    const task: TaskDescriptor = {
      ...base,
      name: "market.sync_universes",
      params: { ...base.params, itiger_token: "********" },
      params_schema: {
        ...base.params_schema,
        properties: {
          ...base.params_schema.properties,
          itiger_token: { type: "string" },
        },
      },
    };
    render(
      <TaskConfigDrawer
        task={task}
        saving={false}
        saveError={null}
        conflict={false}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/itiger/i)).toHaveValue("********");
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    expect(onSave).toHaveBeenCalledOnce();
    expect(onSave.mock.calls[0]?.[0].params.itiger_token).toBe("********");
  });

  it("uses one left-aligned column and submits edited structured spot pairs", async () => {
    const onSave = vi.fn();
    render(
      <TaskConfigDrawer
        task={cryptoTaskFixture}
        saving={false}
        saveError={null}
        conflict={false}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );
    const drawer = screen.getByRole("dialog");

    expect(drawer.querySelectorAll(".ant-col-12")).toHaveLength(0);
    expect(drawer.querySelector(".ant-form-item-label-left")).not.toBeNull();

    const firstSymbol = drawer.querySelector("#root_spot_pairs_0_symbol");
    expect(firstSymbol).not.toBeNull();
    fireEvent.change(firstSymbol as Element, { target: { value: "ETH/USDT" } });
    const spotPairs = drawer.querySelector("#root_spot_pairs");
    expect(spotPairs).not.toBeNull();
    const add = (spotPairs as Element).querySelector(".rjsf-array-item-add");
    expect(add).not.toBeNull();
    await userEvent.click(add as Element);
    await waitFor(() =>
      expect(drawer.querySelector("#root_spot_pairs_1_symbol")).not.toBeNull(),
    );
    const secondSymbol = drawer.querySelector("#root_spot_pairs_1_symbol");
    fireEvent.change(secondSymbol as Element, { target: { value: "SOL/USDT" } });
    await waitFor(() =>
      expect((spotPairs as Element).querySelectorAll(".rjsf-array-item-remove")).toHaveLength(2),
    );
    const removeButtons = (spotPairs as Element).querySelectorAll(".rjsf-array-item-remove");
    await userEvent.click(removeButtons[removeButtons.length - 1] as Element);
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[0].params.spot_pairs).toEqual([
      { exchange: "binance", symbol: "ETH/USDT" },
    ]);
  });
});
