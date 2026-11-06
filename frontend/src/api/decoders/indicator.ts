import type {
  IndicatorComputation,
  IndicatorDescriptor,
  MarkerDefinition,
  PaneDefinition,
  ReferenceLine,
  SeriesDefinition,
  SeriesPoint,
} from "../../types/indicator";
import {
  decodeArray,
  decodeFiniteNumber,
  decodeJsonObject,
  decodeLiteral,
  decodeNullable,
  decodeRecord,
  decodeString,
} from "../decoding";

function decodePane(value: unknown): PaneDefinition {
  const item = decodeRecord(value);
  return {
    id: decodeString(item.id),
    title: decodeString(item.title),
    height: decodeFiniteNumber(item.height),
    price_scale: decodeLiteral(item.price_scale, ["left", "right"]),
  };
}

function decodeSeriesPoint(value: unknown): SeriesPoint {
  const item = decodeRecord(value);
  return {
    time: decodeString(item.time),
    value: decodeNullable(item.value, decodeFiniteNumber),
    color: decodeNullable(item.color, decodeString),
  };
}

function decodeSeries(value: unknown): SeriesDefinition {
  const item = decodeRecord(value);
  return {
    id: decodeString(item.id),
    pane_id: decodeString(item.pane_id),
    type: decodeLiteral(item.type, ["line", "area", "histogram"]),
    title: decodeString(item.title),
    points: decodeArray(item.points, decodeSeriesPoint),
    color: decodeString(item.color),
  };
}

function decodeMarker(value: unknown): MarkerDefinition {
  const item = decodeRecord(value);
  return {
    time: decodeString(item.time),
    position: decodeLiteral(item.position, ["aboveBar", "belowBar", "inBar"]),
    shape: decodeLiteral(item.shape, [
      "arrowUp",
      "arrowDown",
      "circle",
      "square",
    ]),
    color: decodeString(item.color),
    text: decodeNullable(item.text, decodeString),
    tooltip: decodeNullable(item.tooltip, decodeString),
    series_id: decodeNullable(item.series_id, decodeString),
  };
}

function decodeReferenceLine(value: unknown): ReferenceLine {
  const item = decodeRecord(value);
  return {
    series_id: decodeString(item.series_id),
    value: decodeFiniteNumber(item.value),
    color: decodeString(item.color),
    title: decodeNullable(item.title, decodeString),
  };
}

export function decodeIndicatorDescriptor(value: unknown): IndicatorDescriptor {
  const item = decodeRecord(value);
  return {
    name: decodeString(item.name),
    display_name: decodeString(item.display_name),
    description: decodeString(item.description),
    params_schema: decodeJsonObject(item.params_schema),
  };
}

export function decodeIndicators(value: unknown): IndicatorDescriptor[] {
  return decodeArray(value, decodeIndicatorDescriptor);
}

export function decodeIndicatorComputation(
  value: unknown,
): IndicatorComputation {
  const item = decodeRecord(value);
  return {
    instance_id: decodeString(item.instance_id),
    name: decodeString(item.name),
    panes: decodeArray(item.panes, decodePane),
    series: decodeArray(item.series, decodeSeries),
    markers: decodeArray(item.markers, decodeMarker),
    reference_lines: decodeArray(item.reference_lines, decodeReferenceLine),
    warnings: decodeArray(item.warnings, decodeString),
    error: decodeNullable(item.error, decodeString),
  };
}

export function decodeIndicatorComputations(
  value: unknown,
): IndicatorComputation[] {
  return decodeArray(value, decodeIndicatorComputation);
}
