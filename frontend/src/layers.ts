import { PolygonLayer } from "@deck.gl/layers";
import { cellSquare, type HistoryRow, type MpaCell, type Recommendation } from "./types";

const TEAK: [number, number, number] = [166, 124, 72];
const FOAM: [number, number, number] = [126, 184, 201];
const MPA: [number, number, number] = [196, 92, 74];
const HIGHLIGHT: [number, number, number, number] = [244, 239, 230, 230];

function scaleAlpha(value: number, max: number, lo = 80, hi = 210): number {
  if (max <= 0) return hi;
  return Math.round(lo + (hi - lo) * Math.min(1, value / max));
}

function lineColor(cellId: string, focus: string | null): [number, number, number, number] {
  if (focus && cellId === focus) return HIGHLIGHT;
  return [244, 239, 230, 140];
}

export function historyLayer(
  rows: HistoryRow[],
  focus: string | null,
): PolygonLayer<ReturnType<typeof cellSquare<HistoryRow>>> {
  const maxHours = Math.max(...rows.map((r) => r.fishing_hours), 1);
  return new PolygonLayer({
    id: "observed-cells",
    data: rows.map(cellSquare),
    getPolygon: (d) => d.polygon,
    getFillColor: (d) => [...TEAK, scaleAlpha(d.fishing_hours, maxHours)],
    getLineColor: (d) => lineColor(d.cell_id, focus),
    getLineWidth: (d) => (d.cell_id === focus ? 3 : 1),
    lineWidthMinPixels: 1,
    stroked: true,
    filled: true,
    pickable: true,
    updateTriggers: { getLineColor: focus, getLineWidth: focus },
  });
}

export function recommendationLayer(
  rows: Recommendation[],
  focus: string | null,
): PolygonLayer<ReturnType<typeof cellSquare<Recommendation>>> {
  const maxScore = Math.max(...rows.map((r) => r.score), 1);
  return new PolygonLayer({
    id: "recommended-cells",
    data: rows.map(cellSquare),
    getPolygon: (d) => d.polygon,
    getFillColor: (d) => {
      const alpha = scaleAlpha(d.score, maxScore);
      if (d.in_mpa) return [...MPA, alpha];
      return [...FOAM, alpha];
    },
    getLineColor: (d) => lineColor(d.cell_id, focus),
    getLineWidth: (d) => (d.cell_id === focus ? 3 : 1),
    lineWidthMinPixels: 1,
    stroked: true,
    filled: true,
    pickable: true,
    updateTriggers: { getLineColor: focus, getLineWidth: focus },
  });
}

export function mpaOverlayLayer(
  rows: MpaCell[],
): PolygonLayer<ReturnType<typeof cellSquare<MpaCell>>> {
  return new PolygonLayer({
    id: "mpa-overlay",
    data: rows.map(cellSquare),
    getPolygon: (d) => d.polygon,
    getFillColor: [...MPA, 55],
    getLineColor: [...MPA, 170],
    getLineWidth: 1,
    lineWidthMinPixels: 1,
    stroked: true,
    filled: true,
    pickable: false,
  });
}
