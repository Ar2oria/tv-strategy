"""Batch indicator computation with history warmup and per-instance isolation."""

import json
import logging
from collections.abc import Sequence
from datetime import date

from pydantic import ValidationError

from app.api.schemas import IndicatorComputeRequest, IndicatorInstanceRequest
from app.config.models import Settings
from app.domain.dto import BarDTO
from app.indicators.base import IndicatorContext
from app.indicators.models import IndicatorResult
from app.indicators.parameter_validation import contains_non_finite_number
from app.indicators.registry import (
    IndicatorDescriptor,
    IndicatorRegistry,
    UnknownIndicatorError,
)
from app.indicators.validation import namespace_result, validate_result
from app.repositories.instruments import InstrumentRepository
from app.services.bar_service import BarService, InstrumentNotFoundError
from app.services.indicator_cache import (
    IndicatorCache,
    indicator_cache_key,
    params_digest,
)

logger = logging.getLogger(__name__)

CALCULATION_ERROR = "Indicator calculation failed"
PARAMETER_ERROR = "Invalid indicator parameters"
OUTPUT_ERROR = "Indicator output validation failed"
UNKNOWN_INDICATOR_ERROR = "Unknown indicator"


class IndicatorRequestError(ValueError):
    """A validly decoded batch violates a configured request-level limit."""

    def __init__(
        self, message: str, *, code: str = "invalid_indicator_request"
    ) -> None:
        super().__init__(message)
        self.code = code


class IndicatorComputation(IndicatorResult):
    """Flattened immutable result associated with its requested instance."""

    instance_id: str
    name: str


class IndicatorService:
    """Share one historical read while isolating every indicator calculation."""

    def __init__(
        self,
        *,
        bar_service: BarService,
        instruments: InstrumentRepository,
        registry: IndicatorRegistry,
        settings: Settings,
        cache: IndicatorCache | None = None,
    ) -> None:
        self._bar_service = bar_service
        self._instruments = instruments
        self._registry = registry
        self._settings = settings
        self._cache = cache

    def compute(
        self, request: IndicatorComputeRequest
    ) -> list[IndicatorComputation]:
        """Compute a batch without allowing one plugin to erase other results."""
        if not isinstance(request, IndicatorComputeRequest):
            raise TypeError("request must be an IndicatorComputeRequest")
        instrument = self._instruments.get_by_id(request.instrument_id)
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument {request.instrument_id} does not exist"
            )
        self._validate_batch_size(request)
        if not request.indicators:
            return []

        history = self._bar_service.get_history_until(
            request.instrument_id, request.end, request.timeframe
        )
        watermark = history[-1].time if history else date.min
        context = IndicatorContext(
            symbol=instrument.symbol,
            timeframe=request.timeframe,
            start=request.start,
            end=request.end,
        )
        return [
            self._compute_one(item, context, history, request, watermark)
            for item in request.indicators
        ]

    def _resolve_window(
        self,
        request: IndicatorComputeRequest,
        history: Sequence[BarDTO],
    ) -> tuple[date, date]:
        """Resolve the requested slice against available history."""
        earliest = history[0].time if history else date.min
        latest = history[-1].time if history else date.max
        start = request.start if request.start is not None else earliest
        end = request.end if request.end is not None else latest
        if request.limit is not None and request.start is None:
            bounded_end = min(end, latest)
            indexed = [
                bar.time
                for bar in history
                if earliest <= bar.time <= bounded_end
            ]
            if len(indexed) > request.limit:
                start = indexed[-request.limit]
        return start, end

    def _validate_batch_size(self, request: IndicatorComputeRequest) -> None:
        maximum = self._settings.indicators.max_active_indicators
        if len(request.indicators) > maximum:
            raise IndicatorRequestError(
                f"Too many active indicators; maximum is {maximum}",
                code="indicator_limit_exceeded",
            )
        identifiers = [item.instance_id for item in request.indicators]
        if len(set(identifiers)) != len(identifiers):
            raise IndicatorRequestError(
                "Indicator instance_id values must be unique"
            )

    def _compute_one(
        self,
        item: IndicatorInstanceRequest,
        context: IndicatorContext,
        history: Sequence[BarDTO],
        request: IndicatorComputeRequest,
        watermark: date,
    ) -> IndicatorComputation:
        try:
            descriptor = self._registry.get(item.name)
        except UnknownIndicatorError:
            return _failure(item, UNKNOWN_INDICATOR_ERROR)
        except Exception:
            logger.exception(
                "Indicator descriptor resolution failed for instance %s (%s)",
                item.instance_id,
                item.name,
            )
            return _failure(item, CALCULATION_ERROR)
        try:
            json.dumps(item.params, allow_nan=False)
            params = descriptor.params_model.model_validate(item.params)
            if contains_non_finite_number(params):
                raise ValueError("Validated parameters must contain finite numbers")
        except (ValidationError, TypeError, ValueError):
            logger.info("Invalid parameters for indicator %s", item.name)
            return _failure(item, PARAMETER_ERROR)
        except Exception:
            logger.exception(
                "Indicator parameter processing failed for instance %s (%s)",
                item.instance_id,
                item.name,
            )
            return _failure(item, PARAMETER_ERROR)
        window_start, window_end = self._resolve_window(request, history)
        visible_dates = {
            bar.time
            for bar in history
            if window_start <= bar.time <= window_end
        }
        if self._cache is not None:
            digest = params_digest(dict(item.params))
            key = indicator_cache_key(
                request.instrument_id, request.timeframe, item.name, digest
            )
            cached = self._cache.get(key, watermark=watermark)
            if cached is not None:
                return self._validated_success(
                    item,
                    descriptor,
                    cached,
                    visible_dates,
                    window_start,
                    window_end,
                )
        try:
            # A new list prevents one stateful plugin from changing another's input.
            result = descriptor.create().calculate(context, list(history), params)
        except Exception:
            logger.exception(
                "Indicator calculation failed for instance %s (%s)",
                item.instance_id,
                item.name,
            )
            return _failure(item, CALCULATION_ERROR)
        if not isinstance(result, IndicatorResult):
            logger.error(
                "Indicator returned %s instead of IndicatorResult for instance %s",
                type(result).__name__,
                item.instance_id,
            )
            return _failure(item, OUTPUT_ERROR)
        if result.error is not None:
            logger.warning(
                "Indicator returned an error for instance %s", item.instance_id
            )
            return _failure(item, CALCULATION_ERROR)
        if self._cache is not None:
            digest = params_digest(dict(item.params))
            key = indicator_cache_key(
                request.instrument_id, request.timeframe, item.name, digest
            )
            self._cache.store(key, result, watermark=watermark)
        return self._validated_success(
            item,
            descriptor,
            result,
            visible_dates,
            window_start,
            window_end,
        )

    def _validated_success(
        self,
        item: IndicatorInstanceRequest,
        descriptor: IndicatorDescriptor,
        result: IndicatorResult,
        visible_dates: set[date],
        window_start: date,
        window_end: date,
    ) -> IndicatorComputation:
        try:
            trimmed = _trim_result(result, window_start, window_end)
            namespaced = namespace_result(item.instance_id, trimmed)
            validate_result(namespaced, visible_dates)
            return IndicatorComputation(
                instance_id=item.instance_id,
                name=descriptor.name,
                **namespaced.model_dump(mode="python"),
            )
        except Exception:
            logger.exception(
                "Indicator output validation failed for instance %s (%s)",
                item.instance_id,
                item.name,
            )
            return _failure(item, OUTPUT_ERROR)


def _trim_result(
    result: IndicatorResult, start: date, end: date
) -> IndicatorResult:
    """Return a new result containing only points and markers in the range."""
    series = tuple(
        item.model_copy(
            update={
                "points": tuple(
                    point
                    for point in item.points
                    if start <= point.time <= end
                )
            }
        )
        for item in result.series
    )
    markers = tuple(
        marker for marker in result.markers if start <= marker.time <= end
    )
    return result.model_copy(update={"series": series, "markers": markers})


def _failure(
    item: IndicatorInstanceRequest, message: str
) -> IndicatorComputation:
    return IndicatorComputation(
        instance_id=item.instance_id,
        name=item.name,
        error=message,
    )
