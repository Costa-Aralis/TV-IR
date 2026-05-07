interface Props {
  zones: string[];
  active: string | null;
  onChange: (zone: string | null) => void;
}

export function ZoneTabs({ zones, active, onChange }: Props) {
  if (zones.length === 0) return null;
  return (
    <div className="zonetabs">
      <button
        className={`zonetab ${active === null ? "is-active" : ""}`}
        onClick={() => onChange(null)}
      >All</button>
      {zones.map((z) => (
        <button
          key={z}
          className={`zonetab ${active === z ? "is-active" : ""}`}
          onClick={() => onChange(z)}
        >{z}</button>
      ))}
    </div>
  );
}
