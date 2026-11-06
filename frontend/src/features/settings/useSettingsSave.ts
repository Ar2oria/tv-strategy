import { useMutation } from "@tanstack/react-query";

import { ApiError } from "../../api/errors";
import { putSettings } from "../../api/endpoints";
import type { Settings, SettingsUpdate } from "../../types/settings";

export interface SettingsSaveState {
  status: "idle" | "saving" | "saved" | "conflict" | "error";
  message: string | null;
}

export interface UseSettingsSaveResult {
  state: SettingsSaveState;
  save: (draft: Settings) => void;
  reset: () => void;
}

export function buildUpdate(draft: Settings): SettingsUpdate {
  return {
    schema_version: draft.schema_version,
    expected_revision: draft.revision,
    markets: draft.markets,
    timezone: draft.timezone,
    indicators: draft.indicators,
    tasks: draft.tasks,
  };
}

export function describeSaveError(error: unknown): SettingsSaveState {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return {
        status: "conflict",
        message: "配置已被其他页面修改，已重新加载最新值，请确认后再保存。",
      };
    }
    if (error.status === 429) {
      return { status: "error", message: "请求过于频繁，请稍后重试。" };
    }
    return { status: "error", message: error.message };
  }
  return { status: "error", message: "保存失败，请稍后重试。" };
}

export interface UseSettingsSaveOptions {
  onSaved: (settings: Settings) => void;
  onConflict: () => void;
}

/** Save the whole document with its revision; never silently retry writes. */
export function useSettingsSave({
  onSaved,
  onConflict,
}: UseSettingsSaveOptions): UseSettingsSaveResult {
  const mutation = useMutation({
    mutationFn: async (draft: Settings) => putSettings(buildUpdate(draft)),
    onSuccess: (result) => onSaved(result.data),
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        onConflict();
      }
    },
  });

  const state: SettingsSaveState = mutation.isPending
    ? { status: "saving", message: null }
    : mutation.error === null || mutation.error === undefined
      ? mutation.isSuccess
        ? { status: "saved", message: "设置已保存并立即生效。" }
        : { status: "idle", message: null }
      : describeSaveError(mutation.error);

  return {
    state,
    save: (draft) => mutation.mutate(draft),
    reset: () => mutation.reset(),
  };
}
