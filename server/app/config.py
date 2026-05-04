"""Runtime configuration. Reads env vars; falls back to local-dev defaults."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    config_path: Path
    irdb_path: Path
    data_path: Path
    static_path: Path
    request_timeout_s: float

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            config_path=Path(os.environ.get("TVIR_CONFIG", "config/tvs.yaml")),
            irdb_path=Path(os.environ.get("TVIR_IRDB", "flipper-irdb")),
            data_path=Path(os.environ.get("TVIR_DATA", "data")),
            static_path=Path(os.environ.get("TVIR_STATIC", "static")),
            request_timeout_s=float(os.environ.get("TVIR_TIMEOUT", "5.0")),
        )


settings = Settings.load()
