import { AutoComplete, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import type { InstrumentRecord } from "../../types/market";

const SEARCH_DEBOUNCE_MS = 300;

export interface InstrumentSelectorProps {
  instruments: readonly InstrumentRecord[];
  loading: boolean;
  selected: InstrumentRecord | null;
  search: string;
  onSearchChange: (value: string) => void;
  onSelect: (instrument: InstrumentRecord) => void;
}

function label(instrument: InstrumentRecord): string {
  return `${instrument.symbol} · ${instrument.name}`;
}

/** Type-ahead selector; the option label is the only identification shown. */
export function InstrumentSelector({
  instruments,
  loading,
  selected,
  search,
  onSearchChange,
  onSelect,
}: InstrumentSelectorProps) {
  const [value, setValue] = useState(
    selected === null ? search : label(selected),
  );

  useEffect(() => {
    setValue(selected === null ? search : label(selected));
  }, [selected, search]);

  const options = useMemo(
    () =>
      instruments.map((instrument) => ({
        value: String(instrument.id),
        label: label(instrument),
        instrument,
      })),
    [instruments],
  );

  return (
    <div>
      <Typography.Text strong>证券</Typography.Text>
      <AutoComplete
        aria-label="股票搜索"
        style={{ width: "100%", marginTop: 4 }}
        value={value}
        options={options}
        placeholder="输入代码或名称搜索"
        onSearch={onSearchChange}
        onChange={setValue}
        onSelect={(id) => {
          const option = options.find((item) => item.value === id);
          if (option !== undefined) {
            setValue(option.label);
            onSelect(option.instrument);
          }
        }}
        notFoundContent={
          loading ? "搜索中…" : search.trim() === "" ? null : "没有匹配的证券"
        }
      />
    </div>
  );
}

export { SEARCH_DEBOUNCE_MS };
