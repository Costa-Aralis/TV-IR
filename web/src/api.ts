import type { TV } from "./types";

async function call(path: string, init?: RequestInit): Promise<unknown> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${text}`);
  }
  return r.json();
}

export const api = {
  listTvs: () => call("/api/tvs") as Promise<TV[]>,

  power: (id: string, state: "on" | "off" | "toggle" = "toggle") =>
    call(`/api/tvs/${id}/power`, { method: "POST", body: JSON.stringify({ state }) }),

  preset: (id: string, n: number) =>
    call(`/api/tvs/${id}/preset/${n}`, { method: "POST" }),

  key: (id: string, key: string) =>
    call(`/api/tvs/${id}/key`, { method: "POST", body: JSON.stringify({ key }) }),

  allOff: () => call("/api/scenes/all-off", { method: "POST" }),
  allOn: () => call("/api/scenes/all-on", { method: "POST" }),
  allToPreset: (n: number) =>
    call(`/api/scenes/all-to-preset/${n}`, { method: "POST" }),
};
