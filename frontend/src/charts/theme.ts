/** Chart theme tokens and candle colors validated for both surfaces. */

export type ChartMode = "light" | "dark";

export interface ChartTheme {
  surface: string;
  text: string;
  textSecondary: string;
  grid: string;
  border: string;
  crosshair: string;
  tooltipSurface: string;
  tooltipBorder: string;
  up: string;
  down: string;
}

/**
 * Validated pair: CVD Delta E 8.3 (protan), normal-vision 31.8, both >= 3:1
 * against the light (#fcfcfb) and dark (#1a1a19) chart surfaces.
 */
export const CANDLE_COLORS: Readonly<{ up: string; down: string }> = {
  up: "#d84949",
  down: "#008300",
};

const LIGHT_THEME: ChartTheme = {
  surface: "#fcfcfb",
  text: "#0b0b0b",
  textSecondary: "#52514e",
  grid: "#e8e7e3",
  border: "#d9d8d3",
  crosshair: "#8a8880",
  tooltipSurface: "#ffffff",
  tooltipBorder: "#d9d8d3",
  up: CANDLE_COLORS.up,
  down: CANDLE_COLORS.down,
};

const DARK_THEME: ChartTheme = {
  surface: "#1a1a19",
  text: "#f0efec",
  textSecondary: "#c3c2b7",
  grid: "#2b2b29",
  border: "#383835",
  crosshair: "#8f8d84",
  tooltipSurface: "#232322",
  tooltipBorder: "#383835",
  up: CANDLE_COLORS.up,
  down: CANDLE_COLORS.down,
};

export function getChartTheme(mode: ChartMode): ChartTheme {
  return mode === "dark" ? DARK_THEME : LIGHT_THEME;
}

const HEX_PATTERN = /^#([0-9a-f]{6})$/i;

/** Compose a validated `#rrggbb` into an rgba() string for area fills. */
export function withAlpha(hex: string, alpha: number): string {
  const match = HEX_PATTERN.exec(hex);
  if (match === null) {
    return `rgba(42, 120, 214, ${alpha})`;
  }
  const value = Number.parseInt(match[1], 16);
  const red = (value >> 16) & 0xff;
  const green = (value >> 8) & 0xff;
  const blue = value & 0xff;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}
