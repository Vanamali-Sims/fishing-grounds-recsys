import { PolygonLayer } from "@deck.gl/layers";
import { cellSquare, type HistoryRow, type Recommendation } from "./types";

const TEAK: [number, number, number] = [166, 124, 72];
const FOAM: [number, number, number] = [126, 184, 201];
const MPA: [number, number, number] = [196, 92, 74];

function scaleAlpha(value: number, max: number, lo = 80, hi = 210): number {
  if (max <= 0) return hi;
  return Math.round(lo + (hi - lo) * Math.min(1, value / max));
}

export function historyLayer(rows: HistoryRow[]): PolygonLayer<ReturnType<typeof cellSquare<HistoryRow>>> {
  const maxHours = Math.max(...rows.map((r) => r.fishing_hours), 1);
  return new PolygonLayer({
    id: "observed-cells",
    data: rows.map(cellSquare),
    getPolygon: (d) => d.polygon,
    getFillColor: (d) => [...TEAK, scaleAlpha(d.fishing_hours, maxHours)],
    getLineColor: [244, 239, 230, 140],
    lineWidthMinPixels: 1,
    stroked: true,
    filled: true,
    pickable: true,
  });
}

export function recommendationLayer(
  rows: Recommendation[],
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
    getLineColor: [244, 239, 230, 140],
    lineWidthMinPixels: 1,
    stroked: true,
    filled: true,
    pickable: true,
  });
}
