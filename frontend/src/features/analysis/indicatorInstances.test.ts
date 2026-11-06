import { describe, expect, it } from "vitest";

import {
  addInstance,
  describeInstance,
  instancesKey,
  removeInstance,
  updateInstanceParams,
  type ActiveIndicatorInstance,
} from "./indicatorInstances";

function instance(
  overrides: Partial<ActiveIndicatorInstance> = {},
): ActiveIndicatorInstance {
  return {
    instanceId: "a1",
    name: "rsi",
    displayName: "RSI",
    params: { window: 14 },
    ...overrides,
  };
}

describe("indicator instances", () => {
  it("adds a deep-copied instance without mutating the source", () => {
    const params = { window: 14, nested: { flag: true } };
    const before = [instance()];

    const after = addInstance(before, {
      instanceId: "b2",
      name: "donchian",
      displayName: "Donchian",
      params,
    });

    expect(after).toHaveLength(2);
    expect(after[1].params).toEqual(params);
    expect(after[1].params).not.toBe(params);
    expect(before).toHaveLength(1);
  });

  it("rejects a duplicate instance id", () => {
    expect(() =>
      addInstance([instance()], {
        instanceId: "a1",
        name: "rsi",
        displayName: "RSI",
        params: {},
      }),
    ).toThrow(/Duplicate indicator instance id/);
  });

  it("removes only the requested instance", () => {
    const instances = [instance(), instance({ instanceId: "b2" })];

    expect(removeInstance(instances, "a1").map((item) => item.instanceId)).toEqual([
      "b2",
    ]);
  });

  it("replaces params immutably", () => {
    const instances = [instance()];

    const updated = updateInstanceParams(instances, "a1", { window: 21 });

    expect(updated[0].params).toEqual({ window: 21 });
    expect(instances[0].params).toEqual({ window: 14 });
    expect(updated[0]).not.toBe(instances[0]);
  });

  it("leaves other instances untouched when updating params", () => {
    const other = instance({ instanceId: "b2", params: { window: 7 } });
    const instances = [instance(), other];

    const updated = updateInstanceParams(instances, "a1", { window: 21 });

    expect(updated[1]).toBe(other);
  });

  it("describes an instance with its parameters", () => {
    expect(describeInstance(instance())).toBe("RSI (window=14)");
    expect(describeInstance(instance({ params: { window: 14, threshold: null } }))).toBe(
      "RSI (window=14)",
    );
    expect(describeInstance(instance({ params: {} }))).toBe("RSI");
  });

  it("builds a key that is stable across property order", () => {
    const left = instancesKey([instance({ params: { a: 1, b: 2 } })]);
    const right = instancesKey([instance({ params: { b: 2, a: 1 } })]);

    expect(left).toBe(right);
  });

  it("changes the key when params, ids, or order change", () => {
    const base = instancesKey([instance()]);

    expect(instancesKey([instance({ params: { window: 15 } })])).not.toBe(base);
    expect(instancesKey([instance({ instanceId: "z9" })])).not.toBe(base);
    expect(
      instancesKey([instance(), instance({ instanceId: "b2" })]),
    ).not.toBe(base);
  });

  it("serializes arrays and nested objects deterministically", () => {
    const left = instancesKey([
      instance({ params: { list: [1, { z: 1, a: 2 }], flag: true } }),
    ]);
    const right = instancesKey([
      instance({ params: { flag: true, list: [1, { a: 2, z: 1 }] } }),
    ]);

    expect(left).toBe(right);
  });
});
