import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { AuthStatus, Preset, TV, TvListResponse } from "./types";
import { TvTile } from "./components/TvTile";
import { ShiftBar } from "./components/ShiftBar";
import { ZoneTabs } from "./components/ZoneTabs";
import { EventBar } from "./components/EventBar";
import { BoxPanel } from "./components/BoxPanel";
import { LoginGate } from "./components/LoginGate";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [pinRequired, setPinRequired] = useState<boolean>(false);

  const [data, setData] = useState<TvListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [zone, setZone] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(false);

  // ---- auth check on load ----
  useEffect(() => {
    api.authStatus()
      .then((s: AuthStatus) => {
        setPinRequired(s.pin_required);
        setAuthed(s.authed);
      })
      .catch(() => setAuthed(true)); // server down? fall through; calls will surface
  }, []);

  // ---- inventory + status polling once authed ----
  useEffect(() => {
    if (!authed) return;
    let alive = true;

    const fetchAll = () => {
      api.listTvs()
        .then((d) => alive && setData(d))
        .catch((e) => {
          if ((e as Error & { code?: string }).code === "auth_required") {
            setAuthed(false);
            return;
          }
          alive && setError(e instanceof Error ? e.message : String(e));
        });
    };
    const fetchStatus = () => {
      api.tvStatus()
        .then((s) => {
          if (!alive) return;
          setData((d) => {
            if (!d) return d;
            return {
              ...d,
              tvs: d.tvs.map((tv) => ({
                ...tv,
                status: s[tv.id]
                  ? { reachable: s[tv.id].reachable, last_check_ts: 0, error: null }
                  : tv.status,
              })),
            };
          });
        })
        .catch(() => {});
    };

    fetchAll();
    const t1 = window.setInterval(fetchStatus, 10_000);
    const t2 = window.setInterval(fetchAll, 60_000);
    return () => {
      alive = false;
      window.clearInterval(t1);
      window.clearInterval(t2);
    };
  }, [authed]);

  const flash = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2200);
  }, []);

  if (authed === null) return <div className="app__loading">Loading…</div>;
  if (authed === false && pinRequired) return <LoginGate onAuthed={() => setAuthed(true)} />;

  const tvs: TV[] = data?.tvs ?? [];
  const zones: string[] = data?.zones ?? [];
  const presets: Preset[] = data?.presets ?? [];
  const visibleTvs = zone ? tvs.filter((t) => t.zone === zone) : tvs;

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__title">
          <span className="app__brand">Rocky's American Grill</span>
          <span className="app__subtitle">TV Control</span>
        </div>
        <div className="app__headeractions">
          <button className="boxbtn" onClick={() => setShowBoxes(true)}>Boxes</button>
          <ShiftBar onAction={flash} />
        </div>
      </header>

      {zones.length > 0 && (
        <ZoneTabs zones={zones} active={zone} onChange={setZone} />
      )}

      <EventBar onAction={flash} />

      <main className="app__grid">
        {error && <div className="app__error">Failed to load: {error}</div>}
        {!data && !error && <div className="app__loading">Loading…</div>}
        {visibleTvs.map((tv) => (
          <TvTile key={tv.id} tv={tv} presets={presets} onAction={flash} />
        ))}
      </main>

      {showBoxes && <BoxPanel onAction={flash} onClose={() => setShowBoxes(false)} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
