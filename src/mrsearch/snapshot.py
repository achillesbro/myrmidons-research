"""Provenance manifest for a research loop.

Every loop records where its data came from BEFORE computing anything: a
``manifest.json`` in the loop directory, written once when the snapshot is
taken and read back by the notebook's first cell. A result without a manifest
is not reproducible and does not count.

    from mrsearch.snapshot import Manifest, write_manifest, read_manifest

    write_manifest("loops/01-oracle-staleness", Manifest(
        snapshot_date="2026-08-06",
        mnemon_commit="601d1f6...",
        metron_version="v1.0.0",
        tables=("market_state", "markets", "prices"),
    ))
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class Manifest:
    snapshot_date: str  # UTC date the Parquet copy was taken, "YYYY-MM-DD"
    mnemon_commit: str  # MNEMON commit the snapshot came from (full SHA)
    metron_version: str  # METRON git tag installed, e.g. "v1.0.0"
    tables: tuple[str, ...]  # Parquet tables the loop reads


def installed_metron_version() -> str:
    """The METRON tag installed in this environment, as recorded in manifests."""
    import metron

    return f"v{metron.__version__}"


def write_manifest(loop_dir: str | Path, manifest: Manifest) -> Path:
    """Write ``manifest.json`` into a loop directory; returns its path."""
    path = Path(loop_dir) / MANIFEST_NAME
    path.write_text(json.dumps(asdict(manifest), indent=2) + "\n")
    return path


def read_manifest(loop_dir: str | Path) -> Manifest:
    """Read a loop's ``manifest.json`` back into a Manifest."""
    path = Path(loop_dir) / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(
            f"no {MANIFEST_NAME} in {path.parent} — record provenance before computing "
            "(mrsearch.snapshot.write_manifest)"
        )
    raw = json.loads(path.read_text())
    return Manifest(
        snapshot_date=raw["snapshot_date"],
        mnemon_commit=raw["mnemon_commit"],
        metron_version=raw["metron_version"],
        tables=tuple(raw["tables"]),
    )
