import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Preset, TV, TvListResponse } from "./types";
import { TvTile } from "./components/TvTile";
import { ShiftBar } from "./components/ShiftBar";
import { ChannelBar } from "./components/ChannelBar";

export default function App() {
  const [data, setData] = useState<TvListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    api.listTvs()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const flash = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2200);
  }, []);

  const tvs: TV[] = data?.tvs ?? [];
  const presets: Preset[] = data?.presets ?? [];

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__title">
          <span className="app__brand">Rocky's American Grill</span>
          <span className="app__subtitle">TV Control</span>
        </div>
        <ShiftBar onAction={flash} />
      </header>

      <ChannelBar presets={presets} onAction={flash} />

      <main className="app__grid">
        {error && <div className="app__error">Failed to load: {error}</div>}
        {!data && !error && <div className="app__loading">Loading…</div>}
        {tvs.map((tv) => (
          <TvTile key={tv.id} tv={tv} presets={presets} onAction={flash} />
        ))}
      </main>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
