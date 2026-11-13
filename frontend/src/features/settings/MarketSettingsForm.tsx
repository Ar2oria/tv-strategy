import { Alert, Button, Card, Input, InputNumber, Select, Space, Typography } from "antd";
import { useEffect, useRef, useState } from "react";

import type { MarketSettings } from "../../types/settings";
import { MARKET_PROVIDERS, marketLabel } from "./marketOptions";
import { NetworkTestModal } from "./NetworkTestModal";
import { composeProxyUrl, parseProxyUrl, type ProxyParts } from "./proxySettings";
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
  const [networkTestOpen, setNetworkTestOpen] = useState(false);

  const patch = (changes: Partial<MarketSettings>): void => {
    onChange({ ...settings, ...changes });
  };
  const [proxyParts, setProxyParts] = useState<ProxyParts>(() =>
    parseProxyUrl(settings.proxy_url),
  );
  const lastComposedProxy = useRef(settings.proxy_url);
  useEffect(() => {
    if (settings.proxy_url !== lastComposedProxy.current) {
      setProxyParts(parseProxyUrl(settings.proxy_url));
      lastComposedProxy.current = settings.proxy_url;
    }
  }, [settings.proxy_url]);
  const updateProxy = (changes: Partial<ProxyParts>): void => {
    const next = { ...proxyParts, ...changes };
    const composed = composeProxyUrl(next);
    lastComposedProxy.current = composed;
    setProxyParts(next);
    patch({ proxy_url: composed });
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
        <Space
          wrap
          align="center"
          className="market-settings-primary-row"
          data-testid={`market-primary-row-${market}`}
        >
          <Space wrap align="center">
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
          <Space wrap align="center">
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
        </Space>
        <div className="market-settings-proxy-row" data-testid={`market-proxy-row-${market}`}>
          <Space wrap align="center">
            <Typography.Text>代理设置</Typography.Text>
            <Select
              aria-label={`${label} 代理协议`}
              style={{ width: 112 }}
              value={proxyParts.protocol}
              disabled={disabled}
              options={["http", "https", "socks5", "socks5h"].map((protocol) => ({
                value: protocol,
                label: protocol,
              }))}
              onChange={(protocol: ProxyParts["protocol"]) => updateProxy({ protocol })}
            />
            <Input
              aria-label={`${label} 代理 IP/域名`}
              style={{ maxWidth: 300 }}
              placeholder="127.0.0.1 或 proxy.example"
              value={proxyParts.host}
              disabled={disabled}
              onChange={(event) => updateProxy({ host: event.target.value })}
            />
            <InputNumber
              aria-label={`${label} 代理端口`}
              min={1}
              max={65535}
              placeholder="端口"
              style={{ width: 120 }}
              value={proxyParts.port}
              disabled={disabled}
              onChange={(port) => updateProxy({ port: typeof port === "number" ? port : null })}
            />
          </Space>
          {settings.provider === "baostock" && settings.proxy_url !== null ? (
            <Typography.Text type="warning">BaoStock 不支持代理</Typography.Text>
          ) : null}
        </div>
        <Space wrap>
          <Button
            size="small"
            aria-label={`网络测试 ${label}`}
            disabled={editing || busy}
            onClick={() => setNetworkTestOpen(true)}
          >
            网络测试
          </Button>
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
      <NetworkTestModal
        market={market}
        provider={settings.provider}
        open={networkTestOpen}
        onClose={() => setNetworkTestOpen(false)}
      />
    </Card>
  );
}
