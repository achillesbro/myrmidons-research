"""Read a local MNEMON Parquet snapshot into pandas, via in-memory DuckDB.

Mirrors MNEMON's ``mnemon.reader.MnemonReader``: registers the Parquet globs
under a snapshot ``data/`` directory as DuckDB views and creates MNEMON's
derived ``v_*`` views over them. The table specs and view definitions are
IMPORTED from a local MNEMON checkout (``$MNEMON_REPO``), never copied into
this repo, so what this reader sees can never drift from what the ingestion
produces.

Read-only by construction: an in-memory connection over Parquet globs has
nothing to write back to.

    from mrsearch.mnemon_reader import SnapshotReader

    r = SnapshotReader("data")               # or set $MNEMON_DATA
    r.tables()                               # what's available
    df = r.table("v_market_state")           # one frame, whole
    df = r.sql("SELECT ts, market_id, oracle_price FROM v_market_state")
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


def _mnemon_modules(repo: str | Path | None) -> tuple[Any, Any, Any]:
    """Import (ALL_TABLES, Store, create_derived_views) from a local MNEMON checkout."""
    repo = repo or os.environ.get("MNEMON_REPO")
    if not repo:
        raise ValueError(
            "No MNEMON checkout: pass mnemon_repo=... or set the MNEMON_REPO env var "
            "to a local clone of github.com/achillesbro/MNEMON."
        )
    src = Path(repo).expanduser().resolve() / "src"
    if not (src / "mnemon").is_dir():
        raise ValueError(f"not a MNEMON checkout (no src/mnemon): {repo}")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from mnemon.schemas import ALL_TABLES
    from mnemon.storage import Store
    from mnemon.views import create_derived_views

    return ALL_TABLES, Store, create_derived_views


class SnapshotReader:
    """Query a MNEMON Parquet snapshot read-only. Cheap to construct; reuse one instance."""

    def __init__(
        self, data_dir: str | Path | None = None, mnemon_repo: str | Path | None = None
    ) -> None:
        data_dir = data_dir or os.environ.get("MNEMON_DATA")
        if not data_dir:
            raise ValueError(
                "No data directory: pass data_dir=... or set the MNEMON_DATA env var "
                "to this repo's data/ snapshot."
            )
        self.data_dir = Path(data_dir).expanduser().resolve()
        if not self.data_dir.exists():
            raise FileNotFoundError(f"snapshot data dir not found: {self.data_dir}")

        self._all_tables, store_cls, self._create_views = _mnemon_modules(mnemon_repo)
        self._store = store_cls(self.data_dir)
        self._con = duckdb.connect(":memory:")
        self._views: set[str] = set()
        self.available = self._register()

    def _register(self) -> set[str]:
        available: set[str] = set()
        for spec in self._all_tables.values():
            if not self._store.has_data(spec):
                continue
            hive = ", hive_partitioning = 1" if spec.partitioned else ""
            self._con.execute(
                f"CREATE OR REPLACE VIEW {spec.name} AS "
                f"SELECT * FROM read_parquet('{self._store.parquet_glob(spec)}'{hive})"
            )
            available.add(spec.name)
        self._views = set(self._create_views(self._con, available))
        return available

    def sql(self, query: str, params: list[Any] | None = None) -> pd.DataFrame:
        """Arbitrary SQL over the snapshot; returns a DataFrame. Use `?` placeholders
        + `params` for values. Per-row algebra only — statistics live in METRON."""
        return self._con.execute(query, params or []).df()

    def table(self, name: str) -> pd.DataFrame:
        """One raw table or derived view, whole, as a DataFrame."""
        if name not in self.available | self._views:
            raise ValueError(f"unknown table/view: {name!r} (see .tables())")
        return self.sql(f"SELECT * FROM {name}")

    def tables(self) -> list[str]:
        """Raw tables and derived views queryable in this snapshot."""
        return sorted(self.available | self._views)

    def refresh(self) -> None:
        """Re-scan the data dir (call after re-syncing the snapshot)."""
        self.available = self._register()

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> SnapshotReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
