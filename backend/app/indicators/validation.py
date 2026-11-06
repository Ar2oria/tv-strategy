"""Cross-field result validation and immutable per-instance namespacing."""

import math
import re
from datetime import date
from typing import Iterable

from app.indicators.models import (
    IDENTIFIER_PATTERN,
    MAX_IDENTIFIER_LENGTH,
    IndicatorResult,
    SeriesDefinition,
)


class ResultValidationError(ValueError):
    """An indicator result violates chart integrity requirements."""


def validate_result(result: IndicatorResult, visible_dates: set[date]) -> None:
    """Validate relationships and dates without modifying the supplied result."""
    dates = frozenset(visible_dates)
    pane_ids = _unique_ids((pane.id for pane in result.panes), "pane")
    series_ids = _unique_ids((item.id for item in result.series), "series")
    valid_pane_targets = pane_ids | {"main"}

    for item in result.series:
        _validate_series(item, dates, valid_pane_targets)
    previous_marker_date: date | None = None
    for marker in result.markers:
        if previous_marker_date is not None and marker.time < previous_marker_date:
            raise ResultValidationError("Marker dates must be nondecreasing")
        previous_marker_date = marker.time
        if marker.time not in dates:
            raise ResultValidationError(
                f"Marker at {marker.time.isoformat()} is outside visible dates"
            )
        if marker.series_id is not None and marker.series_id not in series_ids:
            raise ResultValidationError(
                f"Marker at {marker.time.isoformat()} references unknown target "
                f"series {marker.series_id!r}"
            )
    for line in result.reference_lines:
        if line.series_id not in series_ids:
            raise ResultValidationError(
                f"Reference line references unknown target series {line.series_id!r}"
            )
        _require_finite(line.value, f"Reference line for {line.series_id!r}")


def namespace_result(instance_id: str, result: IndicatorResult) -> IndicatorResult:
    """Prefix every owned ID while retaining the shared main pane and input."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", instance_id):
        raise ValueError(
            "instance_id must be 1-64 alphanumeric, underscore, or hyphen characters"
        )

    def owned(identifier: str) -> str:
        namespaced_id = f"{instance_id}:{identifier}"
        if len(namespaced_id) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(
                f"Namespaced ID length {len(namespaced_id)} exceeds maximum "
                f"length {MAX_IDENTIFIER_LENGTH} for instance {instance_id!r}"
            )
        return namespaced_id

    def pane_target(identifier: str) -> str:
        return "main" if identifier == "main" else owned(identifier)

    panes = tuple(
        pane if pane.id == "main" else pane.model_copy(update={"id": owned(pane.id)})
        for pane in result.panes
    )
    series = tuple(
        item.model_copy(
            update={"id": owned(item.id), "pane_id": pane_target(item.pane_id)}
        )
        for item in result.series
    )
    markers = tuple(
        marker.model_copy(
            update={
                "series_id": (
                    owned(marker.series_id) if marker.series_id is not None else None
                )
            }
        )
        for marker in result.markers
    )
    reference_lines = tuple(
        line.model_copy(update={"series_id": owned(line.series_id)})
        for line in result.reference_lines
    )
    return result.model_copy(
        update={
            "panes": panes,
            "series": series,
            "markers": markers,
            "reference_lines": reference_lines,
        }
    )


def _unique_ids(identifiers: Iterable[str], kind: str) -> frozenset[str]:
    values = tuple(identifiers)
    unique = frozenset(values)
    if len(unique) != len(values):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        raise ResultValidationError(
            f"Duplicate {kind} ID(s): {', '.join(duplicates)}"
        )
    return unique


def _validate_series(
    item: SeriesDefinition,
    visible_dates: frozenset[date],
    pane_ids: frozenset[str],
) -> None:
    if item.pane_id not in pane_ids:
        raise ResultValidationError(
            f"Series {item.id!r} references unknown target pane {item.pane_id!r}"
        )
    previous_date: date | None = None
    for point in item.points:
        if previous_date is not None and point.time <= previous_date:
            raise ResultValidationError(
                f"Series {item.id!r} point dates must be strictly increasing"
            )
        previous_date = point.time
        if point.time not in visible_dates:
            raise ResultValidationError(
                f"Series {item.id!r} point at {point.time.isoformat()} is outside "
                "visible dates"
            )
        _require_finite(point.value, f"Series {item.id!r} point at {point.time}")


def _require_finite(value: float, location: str) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ResultValidationError(f"{location} must have a finite numeric value")
