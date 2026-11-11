import type { IndicatorComputation } from "../types/indicator";
import type { ChartModel } from "./types";

/** Responsive canvas height before any secondary-pane space is added. */
const BASE_CHART_HEIGHT = "clamp(360px, calc(100vh - 320px), 560px)";
const FREE_EXPANSION_PANE_COUNT = 2;
const SECONDARY_SHRINK_RATIO = 0.8;

/** Additional canvas height is capped at the height reached by two panes. */
export function calculateAdditionalHeight(
  _computations: readonly IndicatorComputation[],
  model: ChartModel,
): number {
  return model.panes
    .slice(0, FREE_EXPANSION_PANE_COUNT)
    .reduce((total, pane) => total + pane.height, 0);
}

/** Equalize and shrink secondary panes after the two-pane height cap. */
export function getSecondaryPaneHeights(model: ChartModel): number[] {
  if (model.panes.length <= FREE_EXPANSION_PANE_COUNT) {
    return model.panes.map((pane) => pane.height);
  }
  const referenceHeight =
    (model.panes[0].height + model.panes[1].height) /
    FREE_EXPANSION_PANE_COUNT;
  const height =
    referenceHeight *
    SECONDARY_SHRINK_RATIO **
      (model.panes.length - FREE_EXPANSION_PANE_COUNT);
  return model.panes.map(() => height);
}

/** CSS canvas height that grows without squeezing existing chart panes. */
export function getChartHeight(
  computations: readonly IndicatorComputation[],
  model: ChartModel,
): string {
  const additional = calculateAdditionalHeight(computations, model);
  return additional === 0
    ? BASE_CHART_HEIGHT
    : `calc(${BASE_CHART_HEIGHT} + ${additional}px)`;
}
