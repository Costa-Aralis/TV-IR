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
  channel: string | null;
}

export interface TvStatus {
  reachable: boolean;
  last_check_ts: number;
  error: string | null;
  channel: string | null;        // raw form as TV reports (e.g. '30-2' on Vizio)
  channel_rf: string | null;     // normalized '30.2'
}

export interface TV {
  id: string;
  name: string;
  slot: number;
  type: TVType;
  zone: string | null;
  status: TvStatus | null;
}

export interface TvListResponse {
  presets: Preset[];
  zones: string[];
  tvs: TV[];
}

export interface SceneResult {
  ok: boolean;
  failed: Record<string, string>;
}

export interface EventAction {
  target: string | string[];
  power?: "on" | "off";
  preset?: number;
}

export interface SavedEvent {
  id: string;
  name: string;
  description: string | null;
  actions: EventAction[];
}

export interface Box {
  num: number;
  name: string | null;
  host: string;
  rf: string | null;
}

export interface AuthStatus {
  pin_required: boolean;
  authed: boolean;
}
