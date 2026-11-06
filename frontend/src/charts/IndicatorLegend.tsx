import { CloseOutlined, EyeInvisibleOutlined, EyeOutlined, SettingOutlined } from "@ant-design/icons";
import { Button, Typography } from "antd";

import type { ChartTheme } from "./theme";

const HIDDEN_OPACITY = 0.45;

export interface IndicatorLegendItem {
  instanceId: string;
  label: string;
  /** Series values for the active bar, in legend order. */
  values: ReadonlyArray<{ id: string; value: number; color: string }>;
  /** Set when this instance failed to compute. */
  error: string | null;
  visible: boolean;
}

export interface IndicatorLegendProps {
  items: readonly IndicatorLegendItem[];
  theme: ChartTheme;
  onEdit: (instanceId: string) => void;
  onToggleVisibility: (instanceId: string) => void;
  onRemove: (instanceId: string) => void;
}

function formatValue(value: number): string {
  return Math.abs(value) >= 1000 ? value.toFixed(0) : value.toFixed(2);
}

/**
 * TradingView-style indicator legend drawn over the chart: one row per
 * instance with the value under the crosshair plus inline controls.
 */
export function IndicatorLegend({
  items,
  theme,
  onEdit,
  onToggleVisibility,
  onRemove,
}: IndicatorLegendProps) {
  if (items.length === 0) {
    return null;
  }
  return (
    <>
      {items.map((item) => (
        <div
          key={item.instanceId}
          data-testid={`indicator-legend-${item.instanceId}`}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "2px 6px",
            borderRadius: 4,
            // The wrapper band ignores hover so the crosshair still works;
            // each row re-enables it for its buttons.
            pointerEvents: "auto",
            background: theme.tooltipSurface,
            border: `1px solid ${theme.tooltipBorder}`,
            opacity: item.visible ? 1 : HIDDEN_OPACITY,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          <Typography.Text strong style={{ fontSize: 12, color: theme.text }}>
            {item.label}
          </Typography.Text>
          {item.error === null ? (
            item.values.map((value) => (
              <span key={value.id} style={{ color: value.color }}>
                {formatValue(value.value)}
              </span>
            ))
          ) : (
            <span style={{ color: theme.down }} title={item.error}>
              计算失败
            </span>
          )}
          <Button
            type="text"
            size="small"
            aria-label={`编辑参数 ${item.label}`}
            icon={<SettingOutlined />}
            onClick={() => onEdit(item.instanceId)}
          />
          <Button
            type="text"
            size="small"
            aria-label={
              item.visible ? `隐藏 ${item.label}` : `显示 ${item.label}`
            }
            icon={item.visible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
            onClick={() => onToggleVisibility(item.instanceId)}
          />
          <Button
            type="text"
            size="small"
            danger
            aria-label={`移除 ${item.label}`}
            icon={<CloseOutlined />}
            onClick={() => onRemove(item.instanceId)}
          />
        </div>
      ))}
    </>
  );
}
