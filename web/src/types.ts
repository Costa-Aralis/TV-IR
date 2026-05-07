export type TVType =
  | "ir"
  | "roku"
  | "vizio"
  | "lg"
  | "androidtv"
  | "firetv"
  | "tbd";

export interface Preset {
  num: number;
  label: string;
  rf: string | null;
}

export interface TV {
  id: string;
  name: string;
  slot: number;
  type: TVType;
}

export interface TvListResponse {
  presets: Preset[];
  tvs: TV[];
}

export interface SceneResult {
  ok: boolean;
  failed: Record<string, string>;
}
