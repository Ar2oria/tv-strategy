import {
  Button,
  Card,
  Input,
  InputNumber,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";

import type { CryptoSymbol, MarketSettings } from "../../types/settings";
import {
  EXCHANGE_LABELS,
  MARKET_PROVIDERS,
  marketLabel,
  symbolKind,
} from "./marketOptions";

export interface MarketSettingsFormProps {
  market: string;
  settings: MarketSettings;
  disabled: boolean;
  onChange: (next: MarketSettings) => void;
}

const NEW_SYMBOL: CryptoSymbol = { exchange: "binance", symbol: "" };

/** One market card: provider, depth, request strategy, and spot pairs. */
export function MarketSettingsForm({
  market,
  settings,
  disabled,
  onChange,
}: MarketSettingsFormProps) {
  const providers = MARKET_PROVIDERS[market] ?? [];
  const isCrypto = symbolKind(market) === "crypto";

  const patch = (changes: Partial<MarketSettings>): void => {
    onChange({ ...settings, ...changes });
  };

  const updateSymbol = (index: number, changes: Partial<CryptoSymbol>): void => {
    patch({
      symbols: settings.symbols.map((item, position) =>
        position === index ? { ...item, ...changes } : item,
      ),
    });
  };

  return (
    <Card size="small" title={marketLabel(market)}>
      <Space orientation="vertical" size="small" style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>数据源</Typography.Text>
          <Select
            aria-label={`${marketLabel(market)} 数据源`}
            style={{ width: 160 }}
            value={settings.provider}
            disabled={disabled}
            options={providers.map((provider) => ({
              value: provider,
              label: provider,
            }))}
            onChange={(provider: string) => patch({ provider })}
          />
          <Tag color="default">并发固定为 1</Tag>
          <Tag color="default">前复权</Tag>
        </Space>
        <Space wrap>
          <Typography.Text>历史深度（年）</Typography.Text>
          <InputNumber
            aria-label={`${marketLabel(market)} 历史深度`}
            min={1}
            max={50}
            value={settings.history_years}
            disabled={disabled || settings.history_years === null}
            onChange={(value) =>
              patch({ history_years: typeof value === "number" ? value : null })
            }
          />
          <Button
            size="small"
            disabled={disabled}
            onClick={() =>
              patch({
                history_years: settings.history_years === null ? 10 : null,
              })
            }
          >
            {settings.history_years === null ? "改为固定年限" : "使用全部可用历史"}
          </Button>
        </Space>
        <Space wrap>
          <Typography.Text>请求超时（秒）</Typography.Text>
          <InputNumber
            aria-label={`${marketLabel(market)} 请求超时`}
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
          <Typography.Text>最大重试</Typography.Text>
          <InputNumber
            aria-label={`${marketLabel(market)} 最大重试`}
            min={0}
            max={10}
            value={settings.max_retries}
            disabled={disabled}
            onChange={(value) =>
              patch({
                max_retries: typeof value === "number" ? value : settings.max_retries,
              })
            }
          />
          <Typography.Text>重叠天数</Typography.Text>
          <InputNumber
            aria-label={`${marketLabel(market)} 重叠天数`}
            min={1}
            max={366}
            value={settings.overlap_days}
            disabled={disabled}
            onChange={(value) =>
              patch({
                overlap_days:
                  typeof value === "number" ? value : settings.overlap_days,
              })
            }
          />
        </Space>
        {isCrypto ? (
          <Space orientation="vertical" size={4} style={{ width: "100%" }}>
            <Typography.Text>现货交易对（交易所限定）</Typography.Text>
            {settings.symbols.map((symbol, index) => (
              <Space key={`${symbol.exchange}-${index}`} wrap>
                <Select
                  aria-label={`${marketLabel(market)} 第 ${index + 1} 个交易对的交易所`}
                  style={{ width: 120 }}
                  value={symbol.exchange}
                  disabled={disabled}
                  options={(
                    Object.keys(EXCHANGE_LABELS) as CryptoSymbol["exchange"][]
                  ).map((exchange) => ({
                    value: exchange,
                    label: EXCHANGE_LABELS[exchange],
                  }))}
                  onChange={(exchange: CryptoSymbol["exchange"]) =>
                    updateSymbol(index, { exchange })
                  }
                />
                <Input
                  aria-label={`${marketLabel(market)} 交易对 ${index + 1}`}
                  style={{ width: 160 }}
                  value={symbol.symbol}
                  disabled={disabled}
                  placeholder="BTC/USDT"
                  onChange={(event) =>
                    updateSymbol(index, { symbol: event.target.value })
                  }
                />
                <Button
                  size="small"
                  danger
                  disabled={disabled}
                  aria-label={`${marketLabel(market)} 移除第 ${index + 1} 个交易对`}
                  onClick={() =>
                    patch({
                      symbols: settings.symbols.filter(
                        (_, position) => position !== index,
                      ),
                    })
                  }
                >
                  移除
                </Button>
              </Space>
            ))}
            <Button
              size="small"
              disabled={disabled}
              aria-label="添加交易对"
              onClick={() => patch({ symbols: [...settings.symbols, { ...NEW_SYMBOL }] })}
            >
              添加交易对
            </Button>
          </Space>
        ) : null}
      </Space>
    </Card>
  );
}
