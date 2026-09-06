import { DeckGL } from "@deck.gl/react";
import type { MapViewState, PickingInfo } from "@deck.gl/core";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { HistoryRow, Recommendation } from "./types";
import { historyLayer, mpaOverlayLayer, recommendationLayer } from "./layers";

const MAP_STYLE = {
  version: 8 as const,
  name: "sea-anchor-dark",
  sources: {
    carto: {
      type: "raster" as const,
      tiles: ["https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}@2x.png"],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    },
  },
  layers: [{ id: "carto", type: "raster" as const, source: "carto" }],
};

type Pane = "observed" | "predicted";

type Props = {
  viewState: MapViewState;
  onViewStateChange: (viewState: MapViewState) => void;
  pane: Pane;
  history: HistoryRow[];
  recommendations: Recommendation[];
  focus: string | null;
  showMpa: boolean;
  loading: boolean;
  onFocus: (cellId: string | null, reason?: string) => void;
};

export default function MapPane({
  viewState,
  onViewStateChange,
  pane,
  history,
  recommendations,
  focus,
  showMpa,
  loading,
  onFocus,
}: Props) {
  const layers =
    pane === "observed"
      ? [historyLayer(history, focus)]
      : [
          recommendationLayer(recommendations, focus),
          ...(showMpa ? [mpaOverlayLayer(recommendations)] : []),
        ];

  return (
    <div className={`chart-frame${loading ? " is-loading" : ""}`}>
      <DeckGL
        viewState={viewState}
        controller
        layers={layers}
        onViewStateChange={(event) => onViewStateChange(event.viewState as MapViewState)}
        onHover={(info: PickingInfo) => {
          const obj = info.object as HistoryRow | Recommendation | undefined;
          onFocus(obj?.cell_id ?? null, obj && "reason" in obj ? obj.reason : undefined);
        }}
        onClick={(info: PickingInfo) => {
          const obj = info.object as HistoryRow | Recommendation | undefined;
          if (!obj) return;
          onFocus(obj.cell_id, "reason" in obj ? obj.reason : undefined);
        }}
        getTooltip={(info) => {
          const obj = info.object as HistoryRow | Recommendation | undefined;
          if (!obj) return null;
          if ("fishing_hours" in obj) {
            return `${obj.cell_id}\n${obj.fishing_hours.toFixed(1)} fishing hours`;
          }
          return `${obj.cell_id}\nscore ${obj.score.toFixed(2)}${obj.in_mpa ? " · MPA" : ""}\n${obj.reason}`;
        }}
      >
        <Map mapStyle={MAP_STYLE} attributionControl={false} />
      </DeckGL>
      {loading && <div className="chart-loading">Sounding the grounds…</div>}
    </div>
  );
}
