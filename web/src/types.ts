export type TVType = "ir" | "roku";

export interface TV {
  id: string;
  name: string;
  slot: number;
  type: TVType;
  presets: number[];
}
