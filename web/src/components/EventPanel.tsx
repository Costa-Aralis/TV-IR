import { useEffect, useState } from "react";
import { api } from "../api";
import type { SavedEvent } from "../types";

interface Props {
  onAction: (msg: string) => void;
  onClose: () => void;
}

export function EventPanel({ onAction, onClose }: Props) {
  const [events, setEvents] = useState<SavedEvent[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.events().then(setEvents).catch(() => setEvents([]));
  }, []);

  const apply = async (e: SavedEvent) => {
    if (busy) return;
    setBusy(e.id);
    try {
      const r = await api.applyEvent(e.id);
      const failed = Object.keys(r.failed ?? {}).length;
      onAction(failed ? `${e.name}: ${failed} failed` : `${e.name} ✓`);
      onClose();
    } catch (err) {
      onAction(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="boxpanel" onClick={onClose}>
      <div className="boxpanel__sheet" onClick={(e) => e.stopPropagation()}>
        <div className="boxpanel__head">
          <span>Scenes</span>
          <button className="boxpanel__close" onClick={onClose}>×</button>
        </div>
        <div className="boxpanel__list">
          {events.length === 0 && <div className="boxpanel__empty">No saved scenes.</div>}
          {events.map((e) => (
            <button
              key={e.id}
              className="scene"
              disabled={busy !== null}
              onClick={() => apply(e)}
            >
              <span className="scene__name">{busy === e.id ? "…" : e.name}</span>
              {e.description && <span className="scene__desc">{e.description}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
