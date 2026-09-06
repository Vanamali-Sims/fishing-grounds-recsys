import { useEffect, useMemo, useState } from "react";
import type { MapViewState } from "@deck.gl/core";
import AnchorMark from "./AnchorMark";
import MapPane from "./MapPane";
import {
  getAnomalies,
  getForecast,
  getHistory,
  getMpaCells,
  getRecommendations,
  getStats,
  getVessel,
  listVessels,
} from "./api";
import type {
  Anomaly,
  ForecastRow,
  HistoryRow,
  MpaCell,
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

function viewBbox(view: MapViewState): {
  west: number;
  south: number;
  east: number;
  north: number;
} {
  const lonSpan = 360 / 2 ** Math.max(view.zoom, 1);
  const latSpan = 180 / 2 ** Math.max(view.zoom - 0.4, 1);
  return {
    west: view.longitude - lonSpan / 2,
    east: view.longitude + lonSpan / 2,
    south: view.latitude - latSpan / 2,
    north: view.latitude + latSpan / 2,
  };
}

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [vessels, setVessels] = useState<VesselSummary[]>([]);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [gear, setGear] = useState("");
  const [season, setSeason] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<VesselDetail | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [forecast, setForecast] = useState<ForecastRow[]>([]);
  const [showForecast, setShowForecast] = useState(false);
  const [mpaCells, setMpaCells] = useState<MpaCell[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [excludeMpa, setExcludeMpa] = useState(true);
  const [showMpa, setShowMpa] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMaps, setLoadingMaps] = useState(false);
  const [loadingStats, setLoadingStats] = useState(true);
  const [viewState, setViewState] = useState<MapViewState>(INITIAL_VIEW);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [pinned, setPinned] = useState<{ cellId: string; reason?: string } | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setLoadingStats(true);
    getStats()
      .then(setStats)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingStats(false));
    getAnomalies().then(setAnomalies).catch(() => setAnomalies([]));
  }, []);

  useEffect(() => {
    getForecast(season || "winter", excludeMpa)
      .then(setForecast)
      .catch(() => setForecast([]));
  }, [season, excludeMpa]);

  useEffect(() => {
    if (!showMpa) return;
    const timer = window.setTimeout(() => {
      getMpaCells(viewBbox(viewState)).then(setMpaCells).catch(() => setMpaCells([]));
    }, 280);
    return () => window.clearTimeout(timer);
  }, [showMpa, viewState.longitude, viewState.latitude, viewState.zoom]);

  useEffect(() => {
    setLoadingList(true);
    listVessels(debouncedQuery, gear)
      .then((rows) => {
        setVessels(rows);
        setSelected((current) =>
          current && rows.some((row) => row.mmsi === current)
            ? current
            : (rows[0]?.mmsi ?? null),
        );
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingList(false));
  }, [debouncedQuery, gear]);

  useEffect(() => {
    if (!selected) return;
    setLoadingMaps(true);
    setError(null);
    setPinned(null);
    Promise.all([
      getVessel(selected),
      getHistory(selected),
      getRecommendations(selected, excludeMpa, season),
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
            zoom: 7.4,
          }));
        }
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingMaps(false));
  }, [selected, excludeMpa, season]);

  const gears = useMemo(() => {
    const unique = new Set(vessels.map((v) => v.gear));
    return [...unique].sort();
  }, [vessels]);

  const focus = pinned?.cellId ?? hoverId;
  const observedIds = useMemo(() => new Set(history.map((row) => row.cell_id)), [history]);
  const blockedInView = recs.filter((row) => row.in_mpa === true).length;
  const mpaReady = Boolean(stats?.mpa_ready);
  const rightRows: Recommendation[] = showForecast
    ? forecast.map((row) => ({
        cell_id: row.cell_id,
        lat: row.lat,
        lon: row.lon,
        score: row.predicted_hours,
        depth: null,
        in_mpa: null,
        distance_to_port: null,
        reason: row.reason,
      }))
    : recs;
  const reason =
    pinned?.reason
    ?? rightRows.find((row) => row.cell_id === focus)?.reason
    ?? rightRows[0]?.reason;
  const overlapCount = rightRows.filter((row) => observedIds.has(row.cell_id)).length;

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
          Same vessel, two questions. Left: where it actually fished. Right: where
          the model would send it next. Maps stay locked together.
        </p>

        {loadingStats ? (
          <div className="skeleton" aria-hidden="true">
            <div />
          </div>
        ) : stats ? (
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
        ) : null}

        <label className="field">
          <span>Find a vessel</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="MMSI"
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

        <label className="field">
          <span>Season</span>
          <select value={season} onChange={(event) => setSeason(event.target.value)}>
            <option value="">Any</option>
            <option value="summer">Summer</option>
            <option value="autumn">Autumn</option>
            <option value="winter">Winter</option>
            <option value="spring">Spring</option>
          </select>
        </label>

        <label className="check">
          <input
            type="checkbox"
            checked={excludeMpa}
            onChange={(event) => setExcludeMpa(event.target.checked)}
          />
          Exclude protected cells from recommendations
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={showForecast}
            onChange={(event) => setShowForecast(event.target.checked)}
          />
          Show effort forecast (climatology)
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={showMpa}
            onChange={(event) => setShowMpa(event.target.checked)}
          />
          Shade protected areas ({mpaReady ? mpaCells.length : 0} in view)
        </label>
        <p className="muted mpa-status">
          {mpaReady
            ? `${(stats?.n_mpa_cells ?? 0).toLocaleString()} cells flagged from WDPA marine/coastal polygons.`
            : "Protected-area layer is unknown — filter cannot drop closed cells yet."}
        </p>

        <ul className="legend">
          <li><span className="swatch teak" /> Observed hours</li>
          <li><span className="swatch foam" /> Recommended</li>
          <li><span className="swatch mpa" /> Marine protected area</li>
        </ul>

        {loadingList ? (
          <div className="skeleton" aria-hidden="true">
            <div />
            <div />
            <div />
          </div>
        ) : (
          <ul className="fleet">
            {vessels.length === 0 && (
              <li className="muted">No vessels match that search.</li>
            )}
            {vessels.map((vessel) => (
              <li key={vessel.mmsi}>
                <button
                  className={vessel.mmsi === selected ? "active" : ""}
                  onClick={() => setSelected(vessel.mmsi)}
                >
                  <strong>{vessel.name ?? vessel.mmsi}</strong>
                  <span>
                    {vessel.flag} · {formatGear(vessel.gear)}
                    {vessel.length ? ` · ${vessel.length.toFixed(0)} m` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {detail && (
          <section className="card">
            <h2>{detail.metadata.name ?? detail.metadata.mmsi}</h2>
            <p>
              {detail.active_days} active days
              {detail.metadata.length
                ? ` · ${detail.metadata.length.toFixed(1)} m`
                : ""}
            </p>
            {reason && <p className="reason">{reason}</p>}
          </section>
        )}

        {anomalies.length > 0 && (
          <section className="card">
            <h2>Low-score activity</h2>
            <ul className="anomalies">
              {anomalies.map((row) => (
                <li key={`${row.mmsi}-${row.cell_id}-${row.date}`}>
                  <button
                    onClick={() => {
                      setSelected(row.mmsi);
                      setPinned({ cellId: row.cell_id });
                    }}
                  >
                    {row.mmsi} · {row.date} · score {row.score.toFixed(2)}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {error && <p className="error">{error}</p>}
      </aside>

      <main className="charts">
        <div className="compare-strip">
          <p>
            <strong>{history.length}</strong> observed
            <span aria-hidden="true"> · </span>
            <strong>{rightRows.length}</strong> {showForecast ? "forecast" : "recommended"}
            <span aria-hidden="true"> · </span>
            <strong>{overlapCount}</strong> overlap
            <span aria-hidden="true"> · </span>
            <strong>{showMpa ? mpaCells.length : 0}</strong> protected in view
          </p>
          <p className="muted">
            {overlapCount === 0
              ? `None of the ${showForecast ? "forecast" : "recommended"} cells were already fished.`
              : `${overlapCount} ${showForecast ? "forecast" : "recommended"} cell${overlapCount === 1 ? "" : "s"} already appear in this vessel's history.`}
            {excludeMpa && mpaReady
              ? " Closed cells are held out of the ranking."
              : !excludeMpa && blockedInView
                ? ` ${blockedInView} recommended cell${blockedInView === 1 ? "" : "s"} sit inside a protected area.`
                : ""}
          </p>
        </div>
        <section className="chart">
          <h2>Observed</h2>
          <MapPane
            pane="observed"
            viewState={viewState}
            onViewStateChange={setViewState}
            history={history}
            recommendations={recs}
            mpaCells={mpaCells}
            focus={focus}
            showMpa={showMpa}
            loading={loadingMaps}
            emptyLabel="No observed fishing cells for this vessel"
            onFocus={(cellId, nextReason) => {
              setHoverId(cellId);
              if (cellId && nextReason) setPinned({ cellId, reason: nextReason });
            }}
          />
        </section>
        <section className="chart">
          <h2>{showForecast ? "Forecast" : "Recommended"}</h2>
          <MapPane
            pane="predicted"
            viewState={viewState}
            onViewStateChange={setViewState}
            history={history}
            recommendations={rightRows}
            mpaCells={mpaCells}
            focus={focus}
            showMpa={showMpa}
            loading={loadingMaps}
            emptyLabel={
              showForecast
                ? "No forecast cells for this season"
                : "No recommendations in this filter"
            }
            onFocus={(cellId, nextReason) => {
              setHoverId(cellId);
              if (cellId && nextReason) setPinned({ cellId, reason: nextReason });
            }}
          />
        </section>
      </main>
    </div>
  );
}
