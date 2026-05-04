"""Cached lookup of IR button codes from Flipper-IRDB files."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from . import flipper


class CodeLibrary:
    """Resolves (codes_file, button_name) → command dict.

    `codes_file` is a path relative to the IRDB root (e.g.
    `TVs/Samsung/Samsung_BN59-01199F.ir`).
    """

    def __init__(self, irdb_root: Path) -> None:
        self._root = irdb_root
        self._cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = Lock()

    def get(self, codes_file: str, button: str) -> dict[str, Any]:
        buttons = self._load(codes_file)
        cmd = buttons.get(button)
        if cmd is None:
            raise KeyError(f"button {button!r} not found in {codes_file!r}")
        return cmd

    def list_buttons(self, codes_file: str) -> list[str]:
        return sorted(self._load(codes_file).keys())

    def _load(self, codes_file: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            cached = self._cache.get(codes_file)
            if cached is not None:
                return cached
            path = self._resolve(codes_file)
            parsed = flipper.parse(path)
            self._cache[codes_file] = parsed
            return parsed

    def _resolve(self, codes_file: str) -> Path:
        path = (self._root / codes_file).resolve()
        # Prevent path traversal outside the IRDB root.
        if not str(path).startswith(str(self._root.resolve())):
            raise ValueError(f"codes_file escapes IRDB root: {codes_file!r}")
        if not path.is_file():
            raise FileNotFoundError(f"IR file not found: {path}")
        return path
