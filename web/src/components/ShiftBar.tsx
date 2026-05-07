import { useState } from "react";
import { api } from "../api";
import type { SceneResult } from "../types";

interface Props {
  onAction: (msg: string) => void;
}

export function ShiftBar({ onAction }: Props) {
  const [busy, setBusy] = useState<"open" | "close" | null>(null);

  const summarise = (label: string, r: SceneResult) => {
    const failed = Object.keys(r.failed ?? {}).length;
    if (!failed) return `${label}: all TVs ✓`;
    return `${label}: ${failed} failed`;
  };

  const run = async (which: "open" | "close") => {
    if (busy) return;
    if (which === "close" && !window.confirm("Turn off ALL TVs?")) return;
    setBusy(which);
    try {
      const r = which === "open" ? await api.open() : await api.close();
      onAction(summarise(which === "open" ? "Open" : "Close", r));
    } catch (e) {
      onAction(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="shiftbar">
      <button
        className="shift shift--open"
        disabled={busy !== null}
        onClick={() => run("open")}
      >
        {busy === "open" ? "…" : "Open"}
      </button>
      <button
        className="shift shift--close"
        disabled={busy !== null}
        onClick={() => run("close")}
      >
        {busy === "close" ? "…" : "Close"}
      </button>
    </div>
  );
}
