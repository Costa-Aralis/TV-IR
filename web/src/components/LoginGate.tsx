import { useState } from "react";
import { api } from "../api";

interface Props {
  onAuthed: () => void;
}

export function LoginGate({ onAuthed }: Props) {
  const [pin, setPin] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.login(pin);
      onAuthed();
    } catch {
      setErr("Wrong PIN");
      setPin("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="login__card" onSubmit={submit}>
        <div className="login__brand">Rocky's American Grill</div>
        <div className="login__sub">Staff PIN</div>
        <input
          className="login__pin"
          type="password"
          inputMode="numeric"
          autoFocus
          maxLength={8}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
        />
        <button className="login__submit" disabled={busy || !pin}>
          {busy ? "…" : "Unlock"}
        </button>
        {err && <div className="login__err">{err}</div>}
      </form>
    </div>
  );
}
