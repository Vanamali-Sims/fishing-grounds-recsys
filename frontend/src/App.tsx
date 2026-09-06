import { useEffect, useMemo, useState } from "react";
import type { MapViewState } from "@deck.gl/core";
import AnchorMark from "./AnchorMark";
import MapPane from "./MapPane";
import {
  getHistory,
  getRecommendations,
  getStats,
  getVessel,
  listVessels,
} from "./api";
import type {
  HistoryRow,
  Recommendation,
  Stats,
  VesselDetail,
  VesselSummary,
} from "./types";

const INITIAL_VIEW: MapViewState = {
  longitude: 141.6,
  latitude: -38.6,
  zoom: 7.2,
  pitch: 0,
  bearing: 0,
};

function centroid(rows: { lat: number; lon: number }[]): { lat: number; lon: number } | null {
  if (!rows.length) return null;
  const lat = rows.reduce((sum, row) => sum + row.lat, 0) / rows.length;
  const lon = rows.reduce((sum, row) => sum + row.lon, 0) / rows.length;
  return { lat, lon };
}

function formatGear(gear: string): string {
  return gear.replaceAll("_", " ");
}

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [vessels, setVessels] = useState<VesselSummary[]>([]);
  const [query, setQuery] = useState("");
  const [gear, setGear] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<VesselDetail | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [excludeMpa, setExcludeMpa] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewState, setViewState] = useState<MapViewState>(INITIAL_VIEW);

  useEffect(() => {
    getStats().then(setStats).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    listVessels(query, gear)
      .then((rows) => {
        setVessels(rows);
        setSelected((current) =>
          current && rows.some((row) => row.mmsi === current)
            ? current
            : (rows[0]?.mmsi ?? null),
        );
      })
      .catch((err: Error) => setError(err.message));
  }, [query, gear]);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    setError(null);
    Promise.all([
      getVessel(selected),
      getHistory(selected),
      getRecommendations(selected, excludeMpa),
    ])
      .then(([vessel, observed, predicted]) => {
        setDetail(vessel);
        setHistory(observed);
        setRecs(predicted);
        const center = centroid(observed) ?? centroid(predicted);
        if (center) {
          setViewState((prev) => ({
            ...prev,
            latitude: center.lat + 0.05,
            longitude: center.lon + 0.05,
            zoom: 8,
          }));
        }
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [selected, excludeMpa]);

  const gears = useMemo(() => {
    const unique = new Set(vessels.map((v) => v.gear));
    return [...unique].sort();
  }, [vessels]);

  return (
    <div className="app">
      <aside className="dock">
        <header className="brand">
          <AnchorMark />
          <div>
            <p className="eyebrow">Grounds recsys</p>
            <h1>Sea Anchor</h1>
          </div>
        </header>

        <p className="lede">
          Observed fishing hours on the left. Model suggestions on the right. Brass
          cells were fished; sea-blue cells are recommended.
        </p>

        {stats && (
          <dl className="stats">
            <div>
              <dt>Vessels</dt>
              <dd>{stats.n_vessels.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Years</dt>
              <dd>{stats.years.join("–")}</dd>
            </div>
          </dl>
        )}

        <label className="field">
          <span>Find a vessel</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="MMSI or name"
          />
        </label>

        <label className="field">
          <span>Gear</span>
          <select value={gear} onChange={(event) => setGear(event.target.value)}>
            <option value="">All gear</option>
            {gears.map((value) => (
              <option key={value} value={value}>
                {formatGear(value)}
              </option>
            ))}
          </select>
        </label>

        <label className="check">
          <input
            type="checkbox"
            checked={excludeMpa}
            onChange={(event) => setExcludeMpa(event.target.checked)}
          />
          Exclude MPAs from recommendations
        </label>

        <ul className="fleet">
          {vessels.map((vessel) => (
            <li key={vessel.mmsi}>
              <button
                className={vessel.mmsi === selected ? "active" : ""}
                onClick={() => setSelected(vessel.mmsi)}
              >
                <strong>{vessel.name ?? "Unnamed"}</strong>
                <span>
                  {vessel.mmsi} · {vessel.flag} · {formatGear(vessel.gear)}
                </span>
              </button>
            </li>
          ))}
        </ul>

        {detail && (
          <section className="card">
            <h2>{detail.metadata.name ?? detail.metadata.mmsi}</h2>
            <p>
              {detail.active_days} active days
              {detail.metadata.length
                ? ` · ${detail.metadata.length.toFixed(1)} m`
                : ""}
            </p>
            {recs[0] && <p className="reason">{recs[0].reason}</p>}
          </section>
        )}

        {error && <p className="error">{error}</p>}
        {loading && <p className="muted">Sounding the grounds…</p>}
      </aside>

      <main className="charts">
        <section className="chart">
          <h2>Observed</h2>
          <MapPane
            pane="observed"
            viewState={viewState}
            onViewStateChange={setViewState}
            history={history}
            recommendations={recs}
            onHover={() => undefined}
          />
        </section>
        <section className="chart">
          <h2>Recommended</h2>
          <MapPane
            pane="predicted"
            viewState={viewState}
            onViewStateChange={setViewState}
            history={history}
            recommendations={recs}
            onHover={() => undefined}
          />
        </section>
      </main>
    </div>
  );
}
