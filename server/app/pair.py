"""Interactive pairing CLI.

Usage:
    docker compose exec server python -m app.pair tv01
    docker compose exec server python -m app.pair --all

Per TV type, walks the human through whatever the protocol requires and
saves the resulting auth into pairings.json (in the data volume, gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import settings
from .drivers.android_tv import AdbClient, ensure_adb_key
from .drivers.lg_webos import LgClient, LgError
from .drivers.vizio import VizioClient, VizioError
from . import registry as registry_mod
from .registry import TV, Pairings


def _pairings_path() -> Path:
    return settings.data_path / "pairings.json"


def _adb_key_path() -> Path:
    return settings.data_path / "adb_key"


async def pair_vizio(tv: TV, pairings: Pairings) -> None:
    print(f"\n[{tv.id}] Vizio SmartCast pairing")

    existing = pairings.get(tv.id).get("auth_token")
    if existing:
        print(f"  already paired — enabling Quick Start so WoL wakes it cleanly.")
        client = VizioClient(tv.url, auth_token=existing)
        try:
            changed = await client.set_quick_start()
            print("  ✓ Quick Start now enabled" if changed else "  ✓ Quick Start already on")
        except VizioError as exc:
            print(f"  ⚠ Quick Start setup failed: {exc}")
            print(f"    (set it manually: Menu → System → Power Mode → Quick Start)")
        return

    print(f"  url: {tv.url}")
    print("  → Watch the TV. A 4-digit PIN should appear in a few seconds.")

    client = VizioClient(tv.url)
    try:
        challenge = await client.pair_start(device_name=f"tv-ir-{tv.id}")
    except VizioError as exc:
        print(f"  ✗ pair_start failed: {exc}")
        return

    print(f"  challenge token: {challenge}")
    pin = input("  enter PIN shown on TV: ").strip()
    if not pin:
        print("  ✗ no PIN entered, aborting")
        return

    try:
        token = await client.pair_finish(challenge, pin, device_name=f"tv-ir-{tv.id}")
    except VizioError as exc:
        print(f"  ✗ pair_finish failed: {exc}")
        return

    pairings.set(tv.id, auth_token=token)
    print(f"  ✓ paired, token saved ({len(token)} chars)")

    # Now flip Power Mode → Quick Start so WoL actually wakes this TV from off.
    try:
        changed = await client.set_quick_start()
        print("  ✓ Quick Start enabled (WoL will now wake the TV)" if changed
              else "  ✓ Quick Start was already on")
    except VizioError as exc:
        print(f"  ⚠ Quick Start setup failed: {exc}")
        print(f"    Set it manually on the TV: Menu → System → Power Mode → Quick Start")


async def pair_lg(tv: TV, pairings: Pairings) -> None:
    print(f"\n[{tv.id}] LG webOS pairing")
    print(f"  host: {tv.url}")
    print("  → Watch the TV. After connect, accept the prompt with the magic remote.")

    host = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/")
    lg = LgClient(host)
    try:
        async with lg:
            key = lg.client_key
    except LgError as exc:
        print(f"  ✗ pair failed: {exc}")
        return

    if not key:
        print("  ✗ no client_key returned (did you accept on the TV?)")
        return
    pairings.set(tv.id, client_key=key)
    print(f"  ✓ paired, client_key saved ({len(key)} chars)")


async def pair_adb(tv: TV, pairings: Pairings) -> None:
    label = "Android TV / Fire TV"
    print(f"\n[{tv.id}] {label} (ADB over WiFi)")
    print(f"  host: {tv.url}")
    print("  → On the TV, enable Developer Options → ADB debugging.")
    print("  → On first connect the TV shows 'Allow USB debugging?' — tap Always allow.")

    key_path = _adb_key_path()
    ensure_adb_key(key_path)

    client = AdbClient(tv.url, key_path)
    ok = await client.healthy()
    await client.close()
    if not ok:
        print("  ✗ connect failed (no accept prompt? ADB not enabled? wrong IP?)")
        return

    pairings.set(tv.id, adb_key=str(key_path))
    print(f"  ✓ ADB connected and key authorised")


async def pair_one(tv: TV, pairings: Pairings) -> None:
    if tv.type == "vizio":
        await pair_vizio(tv, pairings)
    elif tv.type == "lg":
        await pair_lg(tv, pairings)
    elif tv.type in ("androidtv", "firetv"):
        await pair_adb(tv, pairings)
    elif tv.type == "roku":
        print(f"[{tv.id}] Roku — no pairing required.")
    elif tv.type == "ir":
        print(f"[{tv.id}] IR — flash the ESP32 firmware separately.")
    elif tv.type == "tbd":
        print(f"[{tv.id}] TBD — skipping.")
    else:
        print(f"[{tv.id}] unknown type {tv.type!r}, skipping.")


async def main_async(args: argparse.Namespace) -> int:
    reg = registry_mod.load(settings.config_path)
    pairings = Pairings(_pairings_path())

    targets: list[TV]
    if args.all:
        targets = reg.tvs
    else:
        targets = []
        for tv_id in args.tv_ids:
            try:
                targets.append(reg.get(tv_id))
            except KeyError:
                print(f"unknown tv: {tv_id}", file=sys.stderr)
                return 2

    for tv in targets:
        await pair_one(tv, pairings)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="tv-ir-pair")
    parser.add_argument("tv_ids", nargs="*", help="one or more TV ids (e.g. tv01)")
    parser.add_argument("--all", action="store_true", help="pair every TV in inventory")
    args = parser.parse_args()
    if not args.all and not args.tv_ids:
        parser.print_usage()
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
