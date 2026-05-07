import { useState } from "react";
import { api } from "../api";
import type { Preset, SceneResult } from "../types";

interface Props {
  presets: Preset[];
  zone: string | null;
  onAction: (msg: string) => void;
}

export function ChannelBar({ presets, zone, onAction }: Props) {
  const [busy, setBusy] = useState<number | null>(null);

  const run = async (p: Preset) => {
    if (busy !== null) return;
    setBusy(p.num);
    try {
      const r: SceneResult = zone
        ? await api.zoneToPreset(zone, p.num)
        : await api.allToPreset(p.num);
      const failed = Object.keys(r.failed ?? {}).length;
      const scope = zone ?? "All";
      onAction(failed ? `${scope} → ${p.label}: ${failed} failed` : `${scope} → ${p.label} ✓`);
    } catch (e) {
      onAction(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="channelbar">
      <span className="channelbar__label">{zone ?? "All TVs"} to</span>
      <div className="channelbar__buttons">
        {presets.map((p) => (
          <button
            key={p.num}
            className="channel"
            disabled={busy !== null}
            onClick={() => run(p)}
            title={[
              p.channel ? `DirecTV ${p.channel}` : null,
              p.rf ? `RF ${p.rf}` : null,
              `Box ${p.num}`,
            ].filter(Boolean).join(" · ")}
          >
            <span className="channel__label">{p.label}</span>
            <span className="channel__sub">
              Box {p.num}
              {p.channel ? <span className="channel__num"> · Ch {p.channel}</span> : null}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
