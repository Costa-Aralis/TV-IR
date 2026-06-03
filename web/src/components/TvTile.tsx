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
  defective: "Defective",
};

export function TvTile({ tv, presets, onAction }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const disabled = tv.type === "tbd" || tv.type === "defective";

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

  const dotClass = !tv.status
    ? "dot dot--unknown"
    : tv.status.reachable
    ? "dot dot--ok"
    : "dot dot--down";

  // Strip the brand/model prefix from "TV01 Vizio V756x-J03" → "TV01" for a
  // calmer tile. The full name lives in the tooltip.
  const shortName = tv.name.match(/^(TV\d+)/)?.[1] ?? tv.name;
  const currentRf = tv.status?.channel_rf ?? null;
  // What's playing right now (channel label) — find the preset whose rf matches.
  const onPreset = currentRf ? presets.find((p) => p.rf === currentRf) : null;

  return (
    <div className={`tile tile--${tv.type}`} title={`${tv.name} · ${TYPE_BADGE[tv.type]}`}>
      <header className="tile__header">
        <span className={dotClass} title={
          !tv.status ? "no status yet" :
          tv.status.reachable ? "reachable" :
          tv.status.error ?? "unreachable"
        } />
        <span className="tile__name">{shortName}</span>
        <button
          className="tile__power"
          disabled={disabled || busy !== null}
          onClick={(e) => { e.stopPropagation(); run("power", () => api.power(tv.id, "toggle"), "power"); }}
        >
          {busy === "power" ? "…" : "⏻"}
        </button>
      </header>

      {currentRf && (
        <div className="tile__now" title={onPreset ? `${onPreset.label} · DirecTV ${onPreset.channel ?? "?"}` : `Channel ${currentRf}`}>
          {onPreset?.label ?? `Ch ${currentRf}`}
        </div>
      )}

      <div className="tile__presets">
        {presets.map((p) => {
          const major = p.rf?.split(".")[0];
          const active = p.rf && currentRf === p.rf;
          return (
            <button
              key={p.num}
              className={`preset ${active ? "preset--active" : ""}`}
              disabled={disabled || busy !== null}
              onClick={() => run(`p${p.num}`, () => api.preset(tv.id, p.num), `→ ${p.label}`)}
              title={[
                p.label,
                p.channel ? `DirecTV ${p.channel}` : null,
                p.rf ? `RF ${p.rf}` : null,
                `Box ${p.num}`,
              ].filter(Boolean).join(" · ")}
            >
              <span className="preset__label">{major ?? p.label}</span>
            </button>
          );
        })}
      </div>

      {error && <div className="tile__error" title={error}>!</div>}
      {tv.type === "tbd" && <div className="tile__overlay">TBD</div>}
      {tv.type === "defective" && <div className="tile__overlay tile__overlay--defective">DEFECTIVE</div>}
    </div>
  );
}
