import {
  createContext,
  useContext,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";

import type { InstrumentRecord, Timeframe } from "../../types/market";
import type { ActiveIndicatorInstance } from "./indicatorInstances";

interface AnalysisSessionValue {
  search: string;
  setSearch: Dispatch<SetStateAction<string>>;
  instrument: InstrumentRecord | null;
  setInstrument: Dispatch<SetStateAction<InstrumentRecord | null>>;
  timeframe: Timeframe;
  setTimeframe: Dispatch<SetStateAction<Timeframe>>;
  instances: ActiveIndicatorInstance[];
  setInstances: Dispatch<SetStateAction<ActiveIndicatorInstance[]>>;
  hiddenInstances: ReadonlySet<string>;
  setHiddenInstances: Dispatch<SetStateAction<ReadonlySet<string>>>;
}

const AnalysisSessionContext = createContext<AnalysisSessionValue | null>(null);

/** Preserves lightweight analysis choices while route components unmount. */
export function AnalysisSessionProvider({ children }: { children: ReactNode }) {
  const [search, setSearch] = useState("");
  const [instrument, setInstrument] = useState<InstrumentRecord | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [instances, setInstances] = useState<ActiveIndicatorInstance[]>([]);
  const [hiddenInstances, setHiddenInstances] = useState<ReadonlySet<string>>(
    () => new Set<string>(),
  );

  const value = useMemo(
    () => ({
      search,
      setSearch,
      instrument,
      setInstrument,
      timeframe,
      setTimeframe,
      instances,
      setInstances,
      hiddenInstances,
      setHiddenInstances,
    }),
    [search, instrument, timeframe, instances, hiddenInstances],
  );

  return (
    <AnalysisSessionContext.Provider value={value}>
      {children}
    </AnalysisSessionContext.Provider>
  );
}

export function useAnalysisSession(): AnalysisSessionValue {
  const value = useContext(AnalysisSessionContext);
  if (value === null) {
    throw new Error(
      "useAnalysisSession must be used within AnalysisSessionProvider",
    );
  }
  return value;
}
