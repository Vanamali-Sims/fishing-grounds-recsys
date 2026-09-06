import type {
  Anomaly,
  HistoryRow,
  Recommendation,
  Stats,
  VesselDetail,
  VesselSummary,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${path} failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export function listVessels(q = "", gear = ""): Promise<VesselSummary[]> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (gear) params.set("gear", gear);
  params.set("limit", "50");
  const query = params.toString();
  return getJson(`/vessels?${query}`);
}

export function getVessel(mmsi: string): Promise<VesselDetail> {
  return getJson(`/vessels/${mmsi}`);
}

export function getHistory(mmsi: string): Promise<HistoryRow[]> {
  return getJson(`/vessels/${mmsi}/history`);
}

export function getRecommendations(
  mmsi: string,
  excludeMpa: boolean,
  season = "",
): Promise<Recommendation[]> {
  const params = new URLSearchParams({
    k: "50",
    exclude_mpa: String(excludeMpa),
  });
  if (season) params.set("season", season);
  return getJson(`/vessels/${mmsi}/recommendations?${params}`);
}

export function getAnomalies(): Promise<Anomaly[]> {
  return getJson("/anomalies?limit=8");
}

export function getStats(): Promise<Stats> {
  return getJson("/stats");
}
