import { useState } from "react";
import { api } from "../api";

const PRESETS = [1, 2, 3, 4, 5, 6, 7, 8];

export function SceneBar() {
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
    <div className="scenebar">
      <div className="scenebar__group">
        <button
          className="scenebar__btn scenebar__btn--off"
          disabled={busy !== null}
          onClick={() => run("off", api.allOff)}
        >
          {busy === "off" ? "…" : "All Off"}
        </button>
        <button
          className="scenebar__btn"
          disabled={busy !== null}
          onClick={() => run("on", api.allOn)}
        >
          {busy === "on" ? "…" : "All On"}
        </button>
      </div>
      <div className="scenebar__group">
        <span className="scenebar__label">All to box</span>
        {PRESETS.map((n) => (
          <button
            key={n}
            className="scenebar__btn"
            disabled={busy !== null}
            onClick={() => run(`preset-${n}`, () => api.allToPreset(n))}
          >
            {busy === `preset-${n}` ? "…" : n}
          </button>
        ))}
      </div>
      {error && <div className="scenebar__error">{error}</div>}
    </div>
  );
}
