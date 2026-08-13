"""The MNEMON OUTPUT namespace: the only place this repo writes.

Layout: ``<data_dir>/outputs/<table>/date=YYYY-MM-DD/part-0.parquet`` — the
same hive layout MNEMON uses, one directory level down. The separation is
physical: MNEMON's ingestion enumerates its own table specs and never scans
``outputs/``; this module resolves every path under the ``outputs/`` root and
can never write outside it. SnapshotReader never registers output tables, so
the read side of this repo stays exactly what the ingestion produced.

Output tables are APPEND-ONLY. ``append`` inserts rows whose key is absent
and leaves existing rows untouched (first write wins). History is never
rewritten; a model change writes new rows under a new ``model_version``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

OUTPUTS_DIR = "outputs"

TS = pa.timestamp("us", tz="UTC")


@dataclass(frozen=True)
class OutputTable:
    name: str
    schema: pa.Schema
    keys: list[str]  # append-only identity; existing keys always win


LIQ_CAPACITY = OutputTable(
    name="liq_capacity",
    schema=pa.schema(
        [
            ("as_of", TS),  # the v_dex_slippage cycle this row was computed from
            ("chain_id", pa.int32()),
            ("market_id", pa.string()),
            ("model_version", pa.string()),  # metron tag + this repo's commit
            ("params", pa.string()),  # JSON: haircut, size grid, rules, venues
            ("input_window", pa.string()),  # JSON: as_of of each input consumed
            ("capacity_evm_usd", pa.float64()),
            ("capacity_core_usd", pa.float64()),
            ("capacity_total_usd", pa.float64()),
            ("capacity_censored", pa.bool_()),
            ("max_slippage_used", pa.float64()),
            ("lif", pa.float64()),
            ("outstanding_borrow_usd", pa.float64()),
            ("capacity_ratio", pa.float64()),  # null when borrow is 0 or unknown
            ("status", pa.string()),  # ok | no_route | no_price | zero_threshold
        ]
    ),
    keys=["as_of", "market_id", "model_version"],
)


class OutputStore:
    """Append-only writer (and reader) for the outputs namespace."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir).expanduser().resolve() / OUTPUTS_DIR

    def table_glob(self, table: OutputTable) -> str:
        return str(self.root / table.name / "*" / "*.parquet")

    def has_data(self, table: OutputTable) -> bool:
        d = self.root / table.name
        return d.exists() and any(d.rglob("*.parquet"))

    def read(self, table: OutputTable) -> pd.DataFrame:
        """The whole output table as a DataFrame (empty frame when absent)."""
        if not self.has_data(table):
            return pd.DataFrame({f.name: pd.Series(dtype="object") for f in table.schema})
        import duckdb

        con = duckdb.connect()
        try:
            return con.execute(
                f"SELECT {', '.join(f.name for f in table.schema)} "
                f"FROM read_parquet('{self.table_glob(table)}', "
                "hive_partitioning = 1, union_by_name = 1)"
            ).df()
        finally:
            con.close()

    def append(self, table: OutputTable, rows: list[dict]) -> int:
        """Insert rows whose key is absent; existing keys always win.

        Day-partitioned on ``as_of``; each day file is merged and replaced
        atomically (tmp + rename), mirroring MNEMON's storage semantics.
        Returns the number of rows actually added.
        """
        if not rows:
            return 0
        df = pd.DataFrame(rows)
        missing = [f.name for f in table.schema if f.name not in df.columns]
        if missing:
            raise ValueError(f"{table.name}: rows lack columns {missing}")
        df = df[[f.name for f in table.schema]]
        df["as_of"] = pd.to_datetime(df["as_of"], utc=True)
        if df[table.keys].isna().any().any():
            raise ValueError(f"{table.name}: null in key column")

        added = 0
        for day, day_df in df.groupby(df["as_of"].dt.strftime("%Y-%m-%d")):
            path = self.root / table.name / f"date={day}" / "part-0.parquet"
            if path.exists():
                existing = pq.read_table(path).to_pandas()
                merged = pd.concat([existing, day_df], ignore_index=True)
            else:
                existing = None
                merged = day_df
            merged = merged.drop_duplicates(subset=table.keys, keep="first").sort_values(
                table.keys
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            out = pa.Table.from_pandas(merged, schema=table.schema, preserve_index=False)
            tmp = path.with_suffix(".parquet.tmp")
            pq.write_table(out, tmp)
            tmp.replace(path)  # atomic on POSIX
            added += len(merged) - (len(existing) if existing is not None else 0)
        return added

    def processed_cycles(self, table: OutputTable, model_version: str) -> set[pd.Timestamp]:
        """Distinct ``as_of`` values already written under a model version."""
        if not self.has_data(table):
            return set()
        df = self.read(table)
        hit = df[df["model_version"] == model_version]
        return set(pd.to_datetime(hit["as_of"], utc=True))
