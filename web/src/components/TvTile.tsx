import { useState } from "react";
import type { Preset, TV } from "../types";
import { api } from "../api";

interface Props {
  tv: TV;
  presets: Preset[];
  onAction: (msg: string) => void;
}

const TYPE_BADGE: Record<TV["type"], string> = {
  vizio: "Vizio",
  lg: "LG",
  roku: "Roku",
  androidtv: "Android",
  firetv: "Fire TV",
  ir: "IR",
  tbd: "—",
};

export function TvTile({ tv, presets, onAction }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const disabled = tv.type === "tbd";

  const run = async (label: string, action: () => Promise<unknown>, toast: string) => {
    if (disabled || busy) return;
    setBusy(label);
    setError(null);
    try {
      await action();
      onAction(`${tv.name}: ${toast}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onAction(`${tv.name}: ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={`tile tile--${tv.type}`}>
      <header className="tile__header">
        <span className="tile__slot">{tv.slot}</span>
        <span className="tile__name">{tv.name}</span>
        <span className="tile__badge">{TYPE_BADGE[tv.type]}</span>
      </header>

      <button
        className="tile__power"
        disabled={disabled || busy !== null}
        onClick={() => run("power", () => api.power(tv.id, "toggle"), "power")}
      >
        {busy === "power" ? "…" : "Power"}
      </button>

      <div className="tile__presets">
        {presets.map((p) => (
          <button
            key={p.num}
            className="preset"
            disabled={disabled || busy !== null}
            onClick={() => run(`p${p.num}`, () => api.preset(tv.id, p.num), `→ ${p.label}`)}
            title={[
              p.channel ? `DirecTV ${p.channel}` : null,
              p.rf ? `RF ${p.rf}` : null,
              `Box ${p.num}`,
            ].filter(Boolean).join(" · ")}
          >
            <span className="preset__label">{p.label}</span>
            {p.channel && <span className="preset__num">{p.channel}</span>}
          </button>
        ))}
      </div>

      {error && <div className="tile__error" title={error}>!</div>}
      {disabled && <div className="tile__overlay">TBD</div>}
    </div>
  );
}
