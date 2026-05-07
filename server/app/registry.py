"""TV inventory loaded from a YAML config file.

Per-TV auth (Vizio token, LG client-key, ADB key path) lives in a separate
gitignored pairings.json so secrets never sit in the inventory file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


KeyStep = str | dict  # either "Power" or {"delay_ms": 200}

TVType = Literal["ir", "roku", "vizio", "lg", "androidtv", "firetv", "tbd"]


class TV(BaseModel):
    id: str
    name: str
    slot: int
    type: TVType
    url: str  # base URL or host[:port] depending on type
    codes: str | None = None  # IR only: path under IRDB
    key_map: dict[str, str] = Field(default_factory=dict)
    presets: dict[str, list[KeyStep]] | None = None
    key_gap_ms: int | None = None


class Registry(BaseModel):
    key_gap_ms: int = 200
    preset_template: dict[str, list[KeyStep]] = Field(default_factory=dict)
    preset_labels: dict[str, str] = Field(default_factory=dict)
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


# -------- pairings (auth tokens / client keys / ADB key paths) --------

class Pairings:
    """Persistent per-TV auth store, JSON-backed.

    Vizio:    {"auth_token": "..."}
    LG webOS: {"client_key": "..."}
    Android:  {"adb_key": "/path/to/key"} (defaults to data_dir/adb_key)
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            self._data = json.loads(self._path.read_text())

    def get(self, tv_id: str) -> dict[str, Any]:
        return self._data.get(tv_id, {})

    def set(self, tv_id: str, **fields: Any) -> None:
        self._data.setdefault(tv_id, {}).update(fields)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
