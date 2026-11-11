import { Radio } from "antd";

import type { InstrumentRecord, Timeframe } from "../../types/market";
import { AddIndicatorButton } from "./IndicatorPicker";
import { InstrumentSelector } from "./InstrumentSelector";

const TIMEFRAME_OPTIONS: ReadonlyArray<{ label: string; value: Timeframe }> = [
  { label: "日线", value: "1d" },
  { label: "周线", value: "1w" },
  { label: "月线", value: "1M" },
];

export interface ChartToolbarProps {
  instruments: readonly InstrumentRecord[];
  instrumentsLoading: boolean;
  selectedInstrument: InstrumentRecord | null;
  search: string;
  timeframe: Timeframe;
  onSearchChange: (value: string) => void;
  onSelectInstrument: (instrument: InstrumentRecord) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  onAddIndicator: () => void;
}

/** TradingView-style controls hosted by the chart panel, not a separate card. */
export function ChartToolbar({
  instruments,
  instrumentsLoading,
  selectedInstrument,
  search,
  timeframe,
  onSearchChange,
  onSelectInstrument,
  onTimeframeChange,
  onAddIndicator,
}: ChartToolbarProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 8,
        width: "100%",
        padding: 8,
      }}
    >
      <div style={{ width: 280, minWidth: 220, flex: "0 1 280px" }}>
          <InstrumentSelector
            instruments={instruments}
            loading={instrumentsLoading}
            selected={selectedInstrument}
            search={search}
            onSearchChange={onSearchChange}
            onSelect={onSelectInstrument}
          />
        </div>
        <Radio.Group
          aria-label="周期"
          value={timeframe}
          onChange={(event) => onTimeframeChange(event.target.value as Timeframe)}
          options={TIMEFRAME_OPTIONS.map((option) => ({
            label: option.label,
            value: option.value,
          }))}
          optionType="button"
        />
        <AddIndicatorButton onOpen={onAddIndicator} />
    </div>
  );
}
