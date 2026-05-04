"""TV inventory loaded from a YAML config file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


KeyStep = str | dict  # either "Power" or {"delay_ms": 200}


class TV(BaseModel):
    id: str
    name: str
    slot: int
    type: Literal["ir", "roku"]
    url: str  # http://ip[:port] — ESP32 base URL or Roku ECP base URL
    codes: str | None = None  # path under IRDB, required for ir TVs
    key_map: dict[str, str] = Field(default_factory=dict)  # logical → file button
    presets: dict[str, list[KeyStep]] | None = None  # 1..8 → key sequence
    key_gap_ms: int | None = None


class Registry(BaseModel):
    key_gap_ms: int = 200
    preset_template: dict[str, list[KeyStep]] = Field(default_factory=dict)
    tvs: list[TV]

    def get(self, tv_id: str) -> TV:
        for tv in self.tvs:
            if tv.id == tv_id:
                return tv
        raise KeyError(tv_id)

    def preset_sequence(self, tv: TV, preset_num: int) -> list[KeyStep]:
        key = str(preset_num)
        if tv.presets and key in tv.presets:
            return tv.presets[key]
        if key in self.preset_template:
            return self.preset_template[key]
        raise KeyError(f"no preset {preset_num} for {tv.id}")

    def gap_ms(self, tv: TV) -> int:
        return tv.key_gap_ms if tv.key_gap_ms is not None else self.key_gap_ms


def load(path: Path) -> Registry:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return Registry.model_validate(data)
