import type { JsonObject } from "../../types/api";

export interface ActiveIndicatorInstance {
  instanceId: string;
  name: string;
  displayName: string;
  params: JsonObject;
}

export interface ActiveIndicatorInstanceInput {
  instanceId: string;
  name: string;
  displayName: string;
  params: JsonObject;
}

/** Add one immutable instance, rejecting a duplicate instance id. */
export function addInstance(
  instances: readonly ActiveIndicatorInstance[],
  addition: ActiveIndicatorInstanceInput,
): ActiveIndicatorInstance[] {
  if (instances.some((item) => item.instanceId === addition.instanceId)) {
    throw new Error(`Duplicate indicator instance id: ${addition.instanceId}`);
  }
  return [
    ...instances,
    {
      instanceId: addition.instanceId,
      name: addition.name,
      displayName: addition.displayName,
      params: { ...addition.params },
    },
  ];
}

export function removeInstance(
  instances: readonly ActiveIndicatorInstance[],
  instanceId: string,
): ActiveIndicatorInstance[] {
  return instances.filter((item) => item.instanceId !== instanceId);
}

export function updateInstanceParams(
  instances: readonly ActiveIndicatorInstance[],
  instanceId: string,
  params: JsonObject,
): ActiveIndicatorInstance[] {
  return instances.map((item) =>
    item.instanceId === instanceId ? { ...item, params: { ...params } } : item,
  );
}

export function describeInstance(instance: ActiveIndicatorInstance): string {
  const entries = Object.entries(instance.params)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");
  return entries.length === 0
    ? instance.displayName
    : `${instance.displayName} (${entries})`;
}

/** Stable comparison key so identical params never refetch. */
export function instancesKey(
  instances: readonly ActiveIndicatorInstance[],
): string {
  return instances
    .map(
      (item) =>
        `${item.instanceId}:${item.name}:${stableStringify(item.params)}`,
    )
    .join("|");
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? "null";
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, entry]) => entry !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return `{${entries
    .map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`)
    .join(",")}}`;
}
