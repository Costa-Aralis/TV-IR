import { useEffect, useState } from "react";
import { api } from "../api";
import type { SavedEvent } from "../types";

interface Props {
  onAction: (msg: string) => void;
}

export function EventBar({ onAction }: Props) {
  const [events, setEvents] = useState<SavedEvent[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.events().then(setEvents).catch(() => setEvents([]));
  }, []);

  if (events.length === 0) return null;

  const apply = async (e: SavedEvent) => {
    if (busy) return;
    setBusy(e.id);
    try {
      const r = await api.applyEvent(e.id);
      const failed = Object.keys(r.failed ?? {}).length;
      onAction(failed ? `${e.name}: ${failed} failed` : `${e.name} ✓`);
    } catch (err) {
      onAction(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="eventbar">
      <span className="eventbar__label">Quick scenes</span>
      <div className="eventbar__buttons">
        {events.map((e) => (
          <button
            key={e.id}
            className="event"
            disabled={busy !== null}
            onClick={() => apply(e)}
            title={e.description ?? ""}
          >
            {busy === e.id ? "…" : e.name}
          </button>
        ))}
      </div>
    </div>
  );
}
