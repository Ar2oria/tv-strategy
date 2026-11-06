import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../../api/errors";
import { computeIndicators } from "../../api/endpoints";
import type { IndicatorComputation } from "../../types/indicator";
import type { Timeframe } from "../../types/market";
import {
  instancesKey,
  type ActiveIndicatorInstance,
} from "./indicatorInstances";

export const DEBOUNCE_MS = 350;

export interface UseIndicatorComputationOptions {
  instrumentId: number | null;
  timeframe: Timeframe;
  start: string | null;
  end?: string;
  instances: readonly ActiveIndicatorInstance[];
}

export interface IndicatorComputationState {
  computations: IndicatorComputation[];
  isLoading: boolean;
  error: unknown;
}

/** Debounce instance edits, then batch-compute them for one shared range. */
export function useIndicatorComputation({
  instrumentId,
  timeframe,
  start,
  end,
  instances,
}: UseIndicatorComputationOptions): IndicatorComputationState {
  const requestStart = start ?? undefined;
  const requestEnd = end;
  const signature = instancesKey(instances);
  const [debouncedSignature, setDebouncedSignature] = useState(signature);

  useEffect(() => {
    if (signature === debouncedSignature) {
      return;
    }
    const timer = setTimeout(() => setDebouncedSignature(signature), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [signature, debouncedSignature]);

  const pending = signature !== debouncedSignature;
  const requestInstances = useMemo(
    () => (pending ? [] : instances),
    // The signature fully describes the instance payload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [debouncedSignature, pending],
  );

  const enabled =
    instrumentId !== null && requestInstances.length > 0 && !pending;

  const activeIds = useMemo(
    () => new Set(instances.map((item) => item.instanceId)),
    // The signature is a stable digest of every instance id and its params.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signature],
  );

  const query = useQuery({
    queryKey: [
      "indicator-computations",
      instrumentId,
      timeframe,
      requestStart,
      requestEnd,
      debouncedSignature,
    ],
    enabled,
    retry: false,
    // Refetching after a param edit must not blank the panes: keep the last
    // successful results while the new batch runs.
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<IndicatorComputation[]> => {
      const result = await computeIndicators({
        instrument_id: instrumentId as number,
        timeframe,
        start: requestStart,
        end: requestEnd,
        indicators: requestInstances.map((item) => ({
          instance_id: item.instanceId,
          name: item.name,
          params: item.params,
        })),
      });
      return result.data;
    },
  });

  // Previous data may describe instances the user already deleted, so results
  // are filtered against the instances that still exist on screen.
  const computations = useMemo(
    () => (query.data ?? []).filter((item) => activeIds.has(item.instance_id)),
    [query.data, activeIds],
  );

  return {
    computations,
    isLoading: query.isFetching || pending,
    error: query.error instanceof ApiError ? query.error : query.error,
  };
}
