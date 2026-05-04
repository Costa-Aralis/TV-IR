import { useEffect, useState } from "react";
import { api } from "./api";
import type { TV } from "./types";
import { TvTile } from "./components/TvTile";
import { SceneBar } from "./components/SceneBar";

export default function App() {
  const [tvs, setTvs] = useState<TV[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listTvs()
      .then(setTvs)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="app">
      <header className="app__header">
        <h1>TV Control</h1>
        <SceneBar />
      </header>
      <main className="app__grid">
        {error && <div className="app__error">Failed to load: {error}</div>}
        {!tvs && !error && <div className="app__loading">Loading…</div>}
        {tvs && tvs.map((tv) => <TvTile key={tv.id} tv={tv} />)}
      </main>
    </div>
  );
}
