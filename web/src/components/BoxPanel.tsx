import { useEffect, useState } from "react";
import { api } from "../api";
import type { Box } from "../types";

interface Props {
  onAction: (msg: string) => void;
  onClose: () => void;
}

export function BoxPanel({ onAction, onClose }: Props) {
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [tuning, setTuning] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    api.boxes().then(setBoxes).catch(() => setBoxes([]));
  }, []);

  const tune = async (b: Box) => {
    const ch = tuning[b.num];
    if (!ch || busy !== null) return;
    setBusy(b.num);
    try {
      await api.boxTune(b.num, ch);
      onAction(`Box ${b.num} → ${ch} ✓`);
      setTuning((t) => ({ ...t, [b.num]: "" }));
    } catch (err) {
      onAction(`Box ${b.num}: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="boxpanel" onClick={onClose}>
      <div className="boxpanel__sheet" onClick={(e) => e.stopPropagation()}>
        <div className="boxpanel__head">
          <span>DirecTV Boxes</span>
          <button className="boxpanel__close" onClick={onClose}>×</button>
        </div>
        <div className="boxpanel__list">
          {boxes.length === 0 && <div className="boxpanel__empty">No receivers configured.</div>}
          {boxes.map((b) => (
            <div key={b.num} className="boxrow">
              <div className="boxrow__title">
                <span className="boxrow__num">{b.num}</span>
                <span className="boxrow__name">{b.name ?? `Box ${b.num}`}</span>
                {b.rf && <span className="boxrow__rf">RF {b.rf}</span>}
              </div>
              <div className="boxrow__form">
                <input
                  className="boxrow__input"
                  placeholder="Channel (e.g. 206 or 206.1)"
                  value={tuning[b.num] ?? ""}
                  onChange={(e) => setTuning((t) => ({ ...t, [b.num]: e.target.value }))}
                />
                <button
                  className="boxrow__tune"
                  disabled={busy !== null || !tuning[b.num]}
                  onClick={() => tune(b)}
                >
                  {busy === b.num ? "…" : "Tune"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
