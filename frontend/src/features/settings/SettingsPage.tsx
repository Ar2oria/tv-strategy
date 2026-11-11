import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Empty, Space, Spin, Typography } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";

import { getSettings } from "../../api/endpoints";
import { ErrorState } from "../../components/ErrorState";
import type { MarketSettings, Settings } from "../../types/settings";
import { MarketSettingsForm } from "./MarketSettingsForm";
import { marketEntries, marketLabel } from "./marketOptions";
import { useSettingsSave, type SettingsSaveState } from "./useSettingsSave";

const IDLE_SAVE_STATE: SettingsSaveState = { status: "idle", message: null };

function replaceMarket(
  settings: Settings,
  market: string,
  next: MarketSettings,
): Settings {
  return { ...settings, markets: { ...settings.markets, [market]: next } };
}

function mergeServerWithUnsaved(
  current: Settings,
  server: Settings,
  target: string | null,
  editing: ReadonlySet<string>,
): Settings {
  const markets = Object.fromEntries(
    Object.entries(server.markets).map(([name, serverMarket]) => [
      name,
      name !== target && editing.has(name)
        ? (current.markets[name] ?? serverMarket)
        : serverMarket,
    ]),
  );
  return { ...server, markets };
}

/** Whole-document persistence with independent per-Group editing. */
export function SettingsPage() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({
    queryKey: ["settings"],
    retry: false,
    queryFn: async () => (await getSettings()).data,
  });
  const [draft, setDraft] = useState<Settings | null>(null);
  const [editingMarkets, setEditingMarkets] = useState<ReadonlySet<string>>(
    () => new Set<string>(),
  );
  const [feedbackMarket, setFeedbackMarket] = useState<string | null>(null);
  const editingRef = useRef<ReadonlySet<string>>(new Set<string>());
  const feedbackRef = useRef<string | null>(null);

  useEffect(() => {
    if (settingsQuery.data !== undefined && draft === null) {
      setDraft(structuredClone(settingsQuery.data));
    }
  }, [settingsQuery.data, draft]);

  const setMarketEditing = (market: string, editing: boolean): void => {
    const next = new Set(editingRef.current);
    if (editing) {
      next.add(market);
    } else {
      next.delete(market);
    }
    editingRef.current = next;
    setEditingMarkets(next);
  };

  const setFeedback = (market: string | null): void => {
    feedbackRef.current = market;
    setFeedbackMarket(market);
  };

  const save = useSettingsSave({
    onSaved: (saved) => {
      const target = feedbackRef.current;
      queryClient.setQueryData(["settings"], saved);
      setDraft((current) =>
        current === null
          ? saved
          : mergeServerWithUnsaved(current, saved, target, editingRef.current),
      );
      if (target !== null) {
        setMarketEditing(target, false);
      }
    },
    onConflict: () => {
      const target = feedbackRef.current;
      void settingsQuery.refetch().then((result) => {
        if (result.data !== undefined) {
          setDraft((current) =>
            current === null
              ? result.data
              : mergeServerWithUnsaved(
                  current,
                  result.data,
                  target,
                  editingRef.current,
                ),
          );
        }
      });
    },
  });

  const markets = useMemo(
    () => (draft === null ? [] : marketEntries(draft.markets)),
    [draft],
  );

  if (settingsQuery.error !== null) {
    return (
      <ErrorState
        error={settingsQuery.error}
        onRetry={() => {
          void settingsQuery.refetch();
        }}
      />
    );
  }

  if (draft === null) {
    return (
      <Card>
        <Spin />
      </Card>
    );
  }

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        保存后立即生效，无需重启后端。当前修订号：{draft.revision}
      </Typography.Text>
      {markets.length === 0 ? (
        <Empty description="配置中没有可选市场" />
      ) : (
        markets.map(([market, settings]) => (
          <MarketSettingsForm
            key={market}
            market={market}
            settings={settings}
            editing={editingMarkets.has(market)}
            busy={save.state.status === "saving"}
            saveState={feedbackMarket === market ? save.state : IDLE_SAVE_STATE}
            onEdit={() => {
              setMarketEditing(market, true);
              setFeedback(null);
              save.reset();
            }}
            onDiscard={() => {
              const baseline = settingsQuery.data?.markets[market];
              if (baseline !== undefined) {
                setDraft((current) =>
                  current === null ? current : replaceMarket(current, market, baseline),
                );
              }
              setMarketEditing(market, false);
              if (feedbackRef.current === market) {
                setFeedback(null);
                save.reset();
              }
            }}
            onSave={(next) => {
              const baseline = settingsQuery.data;
              if (baseline !== undefined) {
                setFeedback(market);
                save.save(replaceMarket(baseline, market, next));
              }
            }}
            onChange={(next) =>
              setDraft((current) =>
                current === null ? current : replaceMarket(current, market, next),
              )
            }
          />
        ))
      )}
      {markets.length === 0 ? null : (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          市场：{markets.map(([market]) => marketLabel(market)).join("、")}
        </Typography.Text>
      )}
    </Space>
  );
}
