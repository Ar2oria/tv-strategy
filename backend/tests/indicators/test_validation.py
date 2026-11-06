"""Result integrity and immutable namespacing tests."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.indicators.models import (
    IndicatorResult,
    MarkerDefinition,
    PaneDefinition,
    ReferenceLine,
    SeriesDefinition,
    SeriesPoint,
)
from app.indicators.validation import (
    ResultValidationError,
    namespace_result,
    validate_result,
)

DAY_1 = date(2026, 1, 1)
DAY_2 = date(2026, 1, 2)
UNKNOWN_DAY = date(2026, 1, 3)


def point(day: date = DAY_1, value: float = 10.0) -> SeriesPoint:
    return SeriesPoint(time=day, value=value)


def series(
    series_id: str = "rsi",
    pane_id: str = "rsi",
    points: tuple[SeriesPoint, ...] = (point(),),
) -> SeriesDefinition:
    return SeriesDefinition(
        id=series_id,
        pane_id=pane_id,
        type="line",
        title=series_id.upper(),
        points=points,
    )


def valid_result() -> IndicatorResult:
    return IndicatorResult(
        panes=(
            PaneDefinition(id="main", title="Price"),
            PaneDefinition(id="rsi", title="RSI"),
        ),
        series=(series(points=(point(), point(DAY_2, 11.0))),),
        markers=(
            MarkerDefinition(
                time=DAY_1,
                series_id="rsi",
                position="inBar",
                shape="circle",
                text="test",
                tooltip="plain tooltip",
            ),
        ),
        reference_lines=(ReferenceLine(series_id="rsi", value=70.0),),
    )


def test_valid_result_passes() -> None:
    assert validate_result(valid_result(), {DAY_1, DAY_2}) is None


def test_duplicate_pane_ids_are_rejected() -> None:
    result = valid_result()
    duplicate = result.model_copy(update={"panes": (result.panes[0],) * 2})

    with pytest.raises(ResultValidationError, match="Duplicate pane ID"):
        validate_result(duplicate, {DAY_1, DAY_2})


def test_duplicate_series_ids_are_rejected() -> None:
    result = valid_result().model_copy(update={"series": (series(),) * 2})

    with pytest.raises(ResultValidationError, match="Duplicate series ID"):
        validate_result(result, {DAY_1, DAY_2})


@pytest.mark.parametrize(
    "points",
    [
        (point(DAY_2), point(DAY_1)),
        (point(), point()),
    ],
    ids=["unsorted", "duplicate"],
)
def test_points_must_have_strictly_increasing_dates(
    points: tuple[SeriesPoint, ...],
) -> None:
    result = valid_result().model_copy(update={"series": (series(points=points),)})

    with pytest.raises(ResultValidationError, match="strictly increasing"):
        validate_result(result, {DAY_1, DAY_2})


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_series_values_are_rejected(bad_value: float) -> None:
    result = valid_result().model_copy(
        update={"series": (series(points=(point(value=bad_value),)),)}
    )

    with pytest.raises(ResultValidationError, match="finite"):
        validate_result(result, {DAY_1})


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_reference_values_are_rejected(bad_value: float) -> None:
    result = valid_result().model_copy(
        update={
            "reference_lines": (ReferenceLine(series_id="rsi", value=bad_value),)
        }
    )

    with pytest.raises(ResultValidationError, match="finite"):
        validate_result(result, {DAY_1, DAY_2})


def test_unsorted_markers_are_rejected() -> None:
    result = valid_result().model_copy(
        update={
            "markers": (
                MarkerDefinition(
                    time=DAY_2,
                    series_id="rsi",
                    position="inBar",
                    shape="circle",
                ),
                MarkerDefinition(
                    time=DAY_1,
                    series_id="rsi",
                    position="aboveBar",
                    shape="arrowUp",
                ),
            )
        }
    )

    with pytest.raises(ResultValidationError, match="nondecreasing"):
        validate_result(result, {DAY_1, DAY_2})


def test_distinct_markers_at_the_same_timestamp_are_accepted() -> None:
    result = valid_result().model_copy(
        update={
            "markers": (
                MarkerDefinition(
                    time=DAY_1,
                    series_id="rsi",
                    position="inBar",
                    shape="circle",
                    text="first signal",
                ),
                MarkerDefinition(
                    time=DAY_1,
                    series_id="rsi",
                    position="aboveBar",
                    shape="arrowUp",
                    text="second signal",
                ),
            )
        }
    )

    assert validate_result(result, {DAY_1, DAY_2}) is None


def test_unknown_marker_date_is_rejected() -> None:
    result = valid_result().model_copy(
        update={
            "markers": (
                MarkerDefinition(
                    time=UNKNOWN_DAY,
                    position="aboveBar",
                    shape="arrowUp",
                ),
            )
        }
    )

    with pytest.raises(ResultValidationError, match="visible dates"):
        validate_result(result, {DAY_1, DAY_2})


def test_unknown_series_point_date_is_rejected() -> None:
    result = valid_result().model_copy(
        update={"series": (series(points=(point(UNKNOWN_DAY),)),)}
    )

    with pytest.raises(ResultValidationError, match="visible dates"):
        validate_result(result, {DAY_1, DAY_2})


@pytest.mark.parametrize("target", ["marker", "reference"])
def test_unknown_target_series_is_rejected(target: str) -> None:
    if target == "marker":
        update = {
            "markers": (
                MarkerDefinition(
                    time=DAY_1,
                    series_id="missing",
                    position="inBar",
                    shape="circle",
                ),
            )
        }
    else:
        update = {
            "reference_lines": (ReferenceLine(series_id="missing", value=30.0),)
        }
    result = valid_result().model_copy(update=update)

    with pytest.raises(ResultValidationError, match="unknown target series"):
        validate_result(result, {DAY_1, DAY_2})


def test_unknown_target_pane_is_rejected() -> None:
    result = valid_result().model_copy(
        update={"series": (series(pane_id="missing"),)}
    )

    with pytest.raises(ResultValidationError, match="unknown target pane"):
        validate_result(result, {DAY_1, DAY_2})


def test_namespacing_prefixes_ids_and_preserves_main_pane() -> None:
    original = IndicatorResult(
        panes=(
            PaneDefinition(id="main", title="Price"),
            PaneDefinition(id="rsi", title="RSI"),
        ),
        series=(
            series("main", "main"),
            series("rsi", "rsi"),
        ),
        markers=(
            MarkerDefinition(
                time=DAY_1,
                series_id="rsi",
                position="inBar",
                shape="circle",
            ),
        ),
        reference_lines=(ReferenceLine(series_id="rsi", value=70.0),),
        warnings=("unchanged",),
    )
    before = original.model_dump(mode="python")

    namespaced = namespace_result("instance-1", original)

    assert namespaced is not original
    assert [pane.id for pane in namespaced.panes] == ["main", "instance-1:rsi"]
    assert [item.id for item in namespaced.series] == [
        "instance-1:main",
        "instance-1:rsi",
    ]
    assert [item.pane_id for item in namespaced.series] == [
        "main",
        "instance-1:rsi",
    ]
    assert namespaced.markers[0].series_id == "instance-1:rsi"
    assert namespaced.reference_lines[0].series_id == "instance-1:rsi"
    assert namespaced.warnings == ("unchanged",)
    assert original.model_dump(mode="python") == before
    validate_result(namespaced, {DAY_1})


def test_namespacing_combined_id_at_maximum_is_valid() -> None:
    instance_id = "i" * 64
    series_id = "s" * (255 - len(instance_id) - 1)
    original = IndicatorResult(
        series=(
            SeriesDefinition(
                id=series_id,
                pane_id="main",
                type="line",
                title="Boundary",
            ),
        )
    )

    namespaced = namespace_result(instance_id, original)

    assert len(namespaced.series[0].id) == 255
    revalidated = IndicatorResult.model_validate(
        namespaced.model_dump(mode="python")
    )
    assert revalidated.series[0].id == namespaced.series[0].id
    validate_result(namespaced, set())


def test_namespacing_combined_id_one_over_maximum_is_rejected() -> None:
    instance_id = "i" * 64
    series_id = "s" * (255 - len(instance_id))
    original = IndicatorResult(
        series=(
            SeriesDefinition(
                id=series_id,
                pane_id="main",
                type="line",
                title="Boundary",
            ),
        )
    )

    with pytest.raises(ValueError, match="256.*255"):
        namespace_result(instance_id, original)


def test_namespacing_rejects_blank_instance_id() -> None:
    with pytest.raises(ValueError, match="instance_id"):
        namespace_result(" ", valid_result())


def test_marker_text_is_bounded() -> None:
    with pytest.raises(ValidationError):
        MarkerDefinition(
            time=DAY_1,
            position="inBar",
            shape="circle",
            text="x" * 201,
            tooltip="y" * 1_001,
        )
