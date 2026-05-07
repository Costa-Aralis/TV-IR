"""Backup the data volume (pairings.json + adb_key) to a tarball.

Usage inside the container:
    python -m app.backup [--out /backup/tv-ir-data.tgz]

Recommended cron on the LXC (outside Docker):
    0 4 * * *  docker run --rm -v tv-ir-data:/data -v /backup:/backup alpine \
                tar czf /backup/tv-ir-data-$(date +\%F).tgz -C /data .
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tarfile
from pathlib import Path

from .config import settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tv-ir-backup")
    parser.add_argument(
        "--out", default=None,
        help="path to tarball (default: data_path/backups/tv-ir-data-YYYY-MM-DD.tgz)",
    )
    args = parser.parse_args(argv)

    src = settings.data_path
    if not src.exists():
        print(f"data dir does not exist: {src}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else (
        src / "backups" / f"tv-ir-data-{dt.date.today().isoformat()}.tgz"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(out, "w:gz") as tar:
        for entry in src.iterdir():
            # Don't recurse into the backups dir itself.
            if entry.name == "backups":
                continue
            tar.add(entry, arcname=entry.name)

    size = out.stat().st_size
    print(f"wrote {out} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
