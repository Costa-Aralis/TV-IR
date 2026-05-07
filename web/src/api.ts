import type { SceneResult, TvListResponse } from "./types";

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
  listTvs: () => call("/api/tvs") as Promise<TvListResponse>,

  power: (id: string, state: "on" | "off" | "toggle" = "toggle") =>
    call(`/api/tvs/${id}/power`, { method: "POST", body: JSON.stringify({ state }) }),

  preset: (id: string, n: number) =>
    call(`/api/tvs/${id}/preset/${n}`, { method: "POST" }),

  key: (id: string, key: string) =>
    call(`/api/tvs/${id}/key`, { method: "POST", body: JSON.stringify({ key }) }),

  open: () => call("/api/scenes/open", { method: "POST" }) as Promise<SceneResult>,
  close: () => call("/api/scenes/close", { method: "POST" }) as Promise<SceneResult>,
  allToPreset: (n: number) =>
    call(`/api/scenes/all-to-preset/${n}`, { method: "POST" }) as Promise<SceneResult>,
};
