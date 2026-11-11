import { Alert, Button, Card, InputNumber, Select, Space, Typography } from "antd";

import type { MarketSettings } from "../../types/settings";
import { MARKET_PROVIDERS, marketLabel } from "./marketOptions";
import type { SettingsSaveState } from "./useSettingsSave";

export interface MarketSettingsFormProps {
  market: string;
  settings: MarketSettings;
  editing: boolean;
  busy: boolean;
  saveState: SettingsSaveState;
  onEdit: () => void;
  onDiscard: () => void;
  onSave: (next: MarketSettings) => void;
  onChange: (next: MarketSettings) => void;
}

/** One independently editable market Group. */
export function MarketSettingsForm({
  market,
  settings,
  editing,
  busy,
  saveState,
  onEdit,
  onDiscard,
  onSave,
  onChange,
}: MarketSettingsFormProps) {
  const providers = MARKET_PROVIDERS[market] ?? [];
  const label = marketLabel(market);
  const disabled = !editing || busy;

  const patch = (changes: Partial<MarketSettings>): void => {
    onChange({ ...settings, ...changes });
  };

  return (
    <Card
      size="small"
      title={label}
      className={editing ? "market-group market-group-editing" : "market-group market-group-readonly"}
      data-testid={`market-group-${market}`}
      extra={editing ? (
        <Space size="small" wrap>
          <Button size="small" aria-label={`放弃 ${label}`} disabled={busy} onClick={onDiscard}>
            放弃
          </Button>
          <Button
            size="small"
            type="primary"
            aria-label={`保存 ${label}`}
            loading={saveState.status === "saving"}
            disabled={busy}
            onClick={() => onSave(settings)}
          >
            保存
          </Button>
        </Space>
      ) : (
        <Button size="small" aria-label={`编辑 ${label}`} disabled={busy} onClick={onEdit}>
          编辑
        </Button>
      )}
    >
      <Space orientation="vertical" size="small" style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>数据源</Typography.Text>
          <Select
            aria-label={`${label} 数据源`}
            style={{ width: 160 }}
            value={settings.provider}
            disabled={disabled}
            options={providers.map((provider) => ({
              value: provider,
              label: provider,
            }))}
            onChange={(provider: string) => patch({ provider })}
          />
        </Space>
        <Space wrap>
          <Typography.Text>请求超时（秒）</Typography.Text>
          <InputNumber
            aria-label={`${label} 请求超时`}
            min={1}
            max={300}
            step={0.5}
            value={settings.request_timeout_seconds}
            disabled={disabled}
            onChange={(value) =>
              patch({
                request_timeout_seconds:
                  typeof value === "number" ? value : settings.request_timeout_seconds,
              })
            }
          />
        </Space>
        {saveState.status === "idle" || saveState.message === null ? null : (
          <Alert
            type={
              saveState.status === "conflict"
                ? "warning"
                : saveState.status === "saved"
                  ? "success"
                  : "error"
            }
            showIcon
            title={saveState.message}
          />
        )}
      </Space>
    </Card>
  );
}
