import { useState } from "react";
import type { TV } from "../types";
import { api } from "../api";

interface Props {
  tv: TV;
}

export function TvTile({ tv }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={`tile ${tv.type === "roku" ? "tile--roku" : ""}`}>
      <header className="tile__header">
        <span className="tile__slot">{tv.slot}</span>
        <span className="tile__name">{tv.name}</span>
      </header>

      <button
        className="tile__power"
        disabled={busy !== null}
        onClick={() => run("power", () => api.power(tv.id, "toggle"))}
      >
        {busy === "power" ? "…" : "Power"}
      </button>

      <div className="tile__presets">
        {tv.presets.map((n) => (
          <button
            key={n}
            className="tile__preset"
            disabled={busy !== null}
            onClick={() => run(`preset-${n}`, () => api.preset(tv.id, n))}
          >
            {busy === `preset-${n}` ? "…" : n}
          </button>
        ))}
      </div>

      {error && <div className="tile__error" title={error}>!</div>}
    </div>
  );
}
