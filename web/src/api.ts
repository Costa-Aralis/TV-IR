import type {
  AuthStatus, Box, SavedEvent, SceneResult, TvListResponse,
} from "./types";

async function call(path: string, init?: RequestInit): Promise<unknown> {
  const r = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (r.status === 401) {
    const e = new Error("auth_required");
    (e as Error & { code?: string }).code = "auth_required";
    throw e;
  }
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${text}`);
  }
  return r.json();
}

export const api = {
  authStatus: () => call("/api/auth/status") as Promise<AuthStatus>,
  login:  (pin: string) =>
    call("/api/auth/login", { method: "POST", body: JSON.stringify({ pin }) }),
  logout: () => call("/api/auth/logout", { method: "POST" }),

  listTvs: () => call("/api/tvs") as Promise<TvListResponse>,
  tvStatus: () => call("/api/tvs/status") as Promise<Record<string, { reachable: boolean }>>,

  power: (id: string, state: "on" | "off" | "toggle" = "toggle") =>
    call(`/api/tvs/${id}/power`, { method: "POST", body: JSON.stringify({ state }) }),
  preset: (id: string, n: number) =>
    call(`/api/tvs/${id}/preset/${n}`, { method: "POST" }),
  key: (id: string, key: string) =>
    call(`/api/tvs/${id}/key`, { method: "POST", body: JSON.stringify({ key }) }),

  open:  () => call("/api/scenes/open",  { method: "POST" }) as Promise<SceneResult>,
  close: () => call("/api/scenes/close", { method: "POST" }) as Promise<SceneResult>,
  allToPreset: (n: number) =>
    call(`/api/scenes/all-to-preset/${n}`, { method: "POST" }) as Promise<SceneResult>,
  zoneToPreset: (zone: string, n: number) =>
    call(`/api/scenes/zone/${encodeURIComponent(zone)}/preset/${n}`, { method: "POST" }) as Promise<SceneResult>,
  zonePower: (zone: string, state: "on" | "off") =>
    call(`/api/scenes/zone/${encodeURIComponent(zone)}/power?state=${state}`, { method: "POST" }) as Promise<SceneResult>,

  events: () => call("/api/scenes/events") as Promise<SavedEvent[]>,
  applyEvent: (id: string) =>
    call(`/api/scenes/events/${encodeURIComponent(id)}/apply`, { method: "POST" }) as Promise<SceneResult>,

  boxes: () => call("/api/boxes") as Promise<Box[]>,
  boxTuned: (n: number) => call(`/api/boxes/${n}/tuned`),
  boxTune:  (n: number, channel: string) =>
    call(`/api/boxes/${n}/tune?channel=${encodeURIComponent(channel)}`, { method: "POST" }),
  boxKey:   (n: number, key: string) =>
    call(`/api/boxes/${n}/key/${encodeURIComponent(key)}`, { method: "POST" }),
};
