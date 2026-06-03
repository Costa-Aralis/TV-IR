"""TV inventory loaded from a YAML config file.

Per-TV auth (Vizio token, LG client-key, ADB key path) lives in a separate
gitignored pairings.json so secrets never sit in the inventory file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator


KeyStep = str | dict  # either "Power" or {"delay_ms": 200}

TVType = Literal["ir", "roku", "vizio", "lg", "androidtv", "firetv", "tbd", "defective"]


class TV(BaseModel):
    id: str
    name: str
    slot: int
    type: TVType
    url: str  # base URL or host[:port] depending on type
    codes: str | None = None  # IR only: path under IRDB
    mac: str | None = None    # for Wake-on-LAN ("AA:BB:CC:DD:EE:FF")
    zone: str | None = None   # logical group e.g. "Bar Front", "Patio"
    live_tv_activity: str | None = None   # androidtv/firetv: am start -n <activity>
                                          # to switch to Live TV before digit entry
    key_map: dict[str, str] = Field(default_factory=dict)
    presets: dict[str, list[KeyStep]] | None = None
    key_gap_ms: int | None = None


class EventAction(BaseModel):
    """One step inside a saved event preset.

    `target` is "all", a zone name, a single TV id, or a list of TV ids.
    `power` and `preset` are independent: set whichever apply.
    """
    target: str | list[str]
    power: Literal["on", "off"] | None = None
    preset: int | None = None


class Event(BaseModel):
    id: str
    name: str
    description: str | None = None
    actions: list[EventAction]


class Registry(BaseModel):
    key_gap_ms: int = 80
    preset_template: dict[str, list[KeyStep]] = Field(default_factory=dict)
    preset_labels: dict[str, str] = Field(default_factory=dict)
    preset_channels: dict[str, str] = Field(default_factory=dict)
    receivers: list[dict] = Field(default_factory=list)
    schedule: list[dict] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    tvs: list[TV]

    @model_validator(mode="after")
    def _check_unique(self) -> "Registry":
        ids: set[str] = set()
        slots: set[int] = set()
        for tv in self.tvs:
            if tv.id in ids:
                raise ValueError(f"duplicate TV id: {tv.id!r}")
            if tv.slot in slots:
                raise ValueError(f"duplicate slot {tv.slot} (id {tv.id!r})")
            ids.add(tv.id)
            slots.add(tv.slot)
        return self

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

    def preset_rf_channel(self, preset_num: int) -> str | None:
        """Derive the RF channel ('30.2') from the preset template digit sequence."""
        seq = self.preset_template.get(str(preset_num))
        if not seq:
            return None
        digits: list[str] = []
        for step in seq:
            if isinstance(step, dict):
                continue
            if step in ("Enter", "Ok"):
                break
            if step in ("Dot", "Dash"):
                digits.append(".")
            elif isinstance(step, str) and step.isdigit():
                digits.append(step)
        return "".join(digits) if digits else None


def load(path: Path) -> Registry:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise SystemExit(f"config not found: {path} (copy tvs.example.yaml)") from exc
    except yaml.YAMLError as exc:
        raise SystemExit(f"invalid YAML in {path}: {exc}") from exc
    try:
        return Registry.model_validate(data)
    except ValidationError as exc:
        raise SystemExit(f"invalid config in {path}:\n{exc}") from exc


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
        if not self._path.exists():
            return
        try:
            self._data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            # If the file is mid-write or corrupt, keep our current in-memory
            # data and try again next time.
            pass

    def get(self, tv_id: str) -> dict[str, Any]:
        # Always re-read from disk — the pair CLI runs as a separate process
        # and updates the file out-of-band; the server's in-memory cache would
        # otherwise stay stale until restart.
        self._load()
        return self._data.get(tv_id, {})

    def set(self, tv_id: str, **fields: Any) -> None:
        # Re-read first so we merge with anything written out-of-band, then
        # write atomically (temp file + os.replace) so a concurrent reader
        # never sees a half-written file.
        self._load()
        self._data.setdefault(tv_id, {}).update(fields)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
