export type VesselSummary = {
  mmsi: string;
  name: string | null;
  gear: string;
  flag: string;
  length: number | null;
};

export type CellEffort = {
  cell_id: string;
  lat: number;
  lon: number;
  fishing_hours: number;
};

export type VesselDetail = {
  metadata: VesselSummary;
  active_days: number;
  top_cells: CellEffort[];
};

export type HistoryRow = {
  cell_id: string;
  lat: number;
  lon: number;
  fishing_hours: number;
};

export type Recommendation = {
  cell_id: string;
  lat: number;
  lon: number;
  score: number;
  depth: number | null;
  in_mpa: boolean | null;
  distance_to_port: number | null;
  reason: string;
};

export type Stats = {
  n_vessels: number;
  n_cells: number;
  n_interaction_rows: number;
  fishing_hours: number;
  years: number[];
  note: string;
};

export type CellPolygon<T> = T & {
  polygon: [number, number][];
};

export function cellSquare<T extends { lat: number; lon: number }>(row: T): CellPolygon<T> {
  const { lat, lon } = row;
  return {
    ...row,
    polygon: [
      [lon, lat],
      [lon + 0.1, lat],
      [lon + 0.1, lat + 0.1],
      [lon, lat + 0.1],
    ],
  };
}
