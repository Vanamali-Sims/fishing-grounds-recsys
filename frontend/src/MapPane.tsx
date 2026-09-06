import { DeckGL } from "@deck.gl/react";
import type { MapViewState, PickingInfo } from "@deck.gl/core";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { HistoryRow, Recommendation } from "./types";
import { historyLayer, recommendationLayer } from "./layers";

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
  onHover: (info: PickingInfo) => void;
};

export default function MapPane({
  viewState,
  onViewStateChange,
  pane,
  history,
  recommendations,
  onHover,
}: Props) {
  const layers =
    pane === "observed"
      ? [historyLayer(history)]
      : [recommendationLayer(recommendations)];

  return (
    <DeckGL
      viewState={viewState}
      controller
      layers={layers}
      onViewStateChange={(event) => onViewStateChange(event.viewState as MapViewState)}
      onHover={onHover}
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
  );
}
