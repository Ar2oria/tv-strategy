import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  Space,
  Spin,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import { getSettings } from "../../api/endpoints";
import { ErrorState } from "../../components/ErrorState";
import type { MarketSettings, Settings } from "../../types/settings";
import { MarketSettingsForm } from "./MarketSettingsForm";
import { marketLabel, withSignals } from "./marketOptions";
import { useSettingsSave } from "./useSettingsSave";

function replaceMarket(
  settings: Settings,
  market: string,
  next: MarketSettings,
): Settings {
  return { ...settings, markets: { ...settings.markets, [market]: next } };
}

/** Whole-document editor; every save carries the revision it was based on. */
export function SettingsPage() {
  const settingsQuery = useQuery({
    queryKey: ["settings"],
    retry: false,
    queryFn: async () => (await getSettings()).data,
  });

  const [draft, setDraft] = useState<Settings | null>(null);

  useEffect(() => {
    if (settingsQuery.data !== undefined && draft === null) {
      setDraft(structuredClone(settingsQuery.data));
    }
  }, [settingsQuery.data, draft]);

  const save = useSettingsSave({
    onSaved: (saved) => setDraft(structuredClone(saved)),
    onConflict: () => {
      void settingsQuery.refetch().then((result) => {
        if (result.data !== undefined) {
          setDraft(structuredClone(result.data));
        }
      });
    },
  });

  const markets = useMemo(() => (draft === null ? [] : withSignals(draft.markets)), [
    draft,
  ]);

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
      <Typography.Title level={4} style={{ margin: 0 }}>
        系统设置
      </Typography.Title>
      <Typography.Text type="secondary">
        保存后立即生效，无需重启后端。当前修订号：{draft.revision}
      </Typography.Text>
      {save.state.status === "idle" || save.state.message === null ? null : (
        <Alert
          type={
            save.state.status === "conflict"
              ? "warning"
              : save.state.status === "saved"
                ? "success"
                : "error"
          }
          showIcon
          title={save.state.message}
        />
      )}
      <Card size="small" title="全局">
        <Space wrap>
          <Typography.Text>调度时区</Typography.Text>
          <Input
            aria-label="调度时区"
            style={{ width: 200 }}
            value={draft.timezone}
            onChange={(event) =>
              setDraft({ ...draft, timezone: event.target.value })
            }
          />
          <Typography.Text>最大启用指标数</Typography.Text>
          <InputNumber
            aria-label="最大启用指标数"
            min={1}
            max={100}
            value={draft.indicators.max_active_indicators}
            onChange={(value) =>
              setDraft({
                ...draft,
                indicators: {
                  ...draft.indicators,
                  max_active_indicators:
                    typeof value === "number"
                      ? value
                      : draft.indicators.max_active_indicators,
                },
              })
            }
          />
        </Space>
      </Card>
      {markets.length === 0 ? (
        <Empty description="配置中没有可选市场" />
      ) : (
        markets.map(([market, settings]) => (
          <MarketSettingsForm
            key={market}
            market={market}
            settings={settings}
            disabled={save.state.status === "saving"}
            onChange={(next) => setDraft(replaceMarket(draft, market, next))}
          />
        ))
      )}
      <Space>
        <Button
          type="primary"
          loading={save.state.status === "saving"}
          onClick={() => save.save(draft)}
        >
          保存设置
        </Button>
        <Button
          disabled={save.state.status === "saving"}
          onClick={() => {
            if (settingsQuery.data !== undefined) {
              setDraft(structuredClone(settingsQuery.data));
              save.reset();
            }
          }}
        >
          放弃修改
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          市场：{markets.map(([market]) => marketLabel(market)).join("、")}
        </Typography.Text>
      </Space>
    </Space>
  );
}
