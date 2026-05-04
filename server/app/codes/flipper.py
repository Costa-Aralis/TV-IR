"""Parser for Flipper-IRDB `.ir` files.

Format reference: https://github.com/Lucaslhm/Flipper-IRDB

Each file contains one or more button blocks separated by `#` lines:

    Filetype: IR signals file
    Version: 1
    #
    name: Power
    type: parsed
    protocol: NEC
    address: 04 00 00 00
    command: 08 00 00 00
    #
    name: Vol_up
    type: raw
    frequency: 38000
    duty_cycle: 0.330000
    data: 9024 4512 564 564 ...

`address` and `command` are 4-byte little-endian hex.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def parse(path: Path) -> dict[str, dict[str, Any]]:
    """Read a `.ir` file and return {button_name: command_dict}."""
    buttons: dict[str, dict[str, Any]] = {}
    current: dict[str, str] = {}

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("Filetype") or line.startswith("Version"):
                continue
            if line == "#":
                _flush(current, buttons)
                current = {}
                continue
            key, sep, value = line.partition(":")
            if not sep:
                continue
            current[key.strip()] = value.strip()
        _flush(current, buttons)

    return buttons


def _flush(entry: dict[str, str], out: dict[str, dict[str, Any]]) -> None:
    name = entry.get("name")
    if not name:
        return
    try:
        out[name] = _normalize(entry)
    except (KeyError, ValueError):
        # Malformed entry — skip rather than crash on a single bad button.
        pass


def _normalize(entry: dict[str, str]) -> dict[str, Any]:
    kind = entry.get("type", "")
    if kind == "parsed":
        return {
            "type": "parsed",
            "protocol": entry["protocol"],
            "address": _hex_le(entry["address"]),
            "command": _hex_le(entry["command"]),
        }
    if kind == "raw":
        return {
            "type": "raw",
            "frequency": int(entry.get("frequency", "38000")),
            "duty_cycle": float(entry.get("duty_cycle", "0.33")),
            "data": [int(x) for x in entry["data"].split()],
        }
    raise ValueError(f"unknown entry type: {kind!r}")


def _hex_le(text: str) -> int:
    """Convert a Flipper-style space-separated little-endian hex string to int."""
    return int.from_bytes(bytes.fromhex(text.replace(" ", "")), "little")
