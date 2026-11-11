/** Chart theme tokens and candle colors validated for both surfaces. */

export type ChartMode = "light" | "dark";

export interface ChartTheme {
  surface: string;
  text: string;
  textSecondary: string;
  grid: string;
  border: string;
  paneSeparator: string;
  paneSeparatorHover: string;
  crosshair: string;
  tooltipSurface: string;
  tooltipBorder: string;
  up: string;
  down: string;
}

/**
 * TradingView-style red-up/green-down pair: CVD Delta E 11.1, normal-vision
 * 32.7, both >= 3:1 against the light and dark chart surfaces.
 */
export const CANDLE_COLORS: Readonly<{ up: string; down: string }> = {
  up: "#f23645",
  down: "#089981",
};

const LIGHT_THEME: ChartTheme = {
  surface: "#fcfcfb",
  text: "#0b0b0b",
  textSecondary: "#52514e",
  grid: "#e8e7e3",
  border: "#d9d8d3",
  paneSeparator: "#898781",
  paneSeparatorHover: "#2962ff",
  crosshair: "#8a8880",
  tooltipSurface: "#ffffff",
  tooltipBorder: "#d9d8d3",
  up: CANDLE_COLORS.up,
  down: CANDLE_COLORS.down,
};

const DARK_THEME: ChartTheme = {
  surface: "#131722",
  text: "#d1d4dc",
  textSecondary: "#9598a1",
  grid: "#1e222d",
  border: "#2a2e39",
  paneSeparator: "#5f6b7d",
  paneSeparatorHover: "#2962ff",
  crosshair: "#758696",
  tooltipSurface: "#1e222d",
  tooltipBorder: "#2a2e39",
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
