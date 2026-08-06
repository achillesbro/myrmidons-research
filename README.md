# myrmidons-research

Research loops joining MNEMON data with METRON logic. This is the consumer repo
of a three-part stack:

- **[MNEMON](https://github.com/achillesbro/MNEMON)** — the data layer: a
  Parquet/DuckDB archive of Morpho Blue state, ingested every 5–15 minutes on
  the VPS. This repo reads snapshots of it, read-only.
- **[METRON](https://github.com/achillesbro/METRON)** — the pure statistical
  metric library, installed here as a git dependency pinned by tag.
- **myrmidons-research** (this repo) — research loops, risk-framework work, and
  write-ups. Later it becomes the Phase 3 risk-engine repo (write-side to
  MNEMON output tables); in this phase it writes nothing.

## Setup

```bash
uv sync
export MNEMON_REPO=~/mnemon   # local MNEMON checkout; the reader imports its view definitions
```

## Syncing a MNEMON snapshot

`data/` is the gitignored rsync target for a copy of the VPS store:

```bash
rsync -av --delete ubuntu@<vps-host>:/home/ubuntu/mnemon/data/ data/
```

Record the provenance at the same time — the MNEMON commit running on the VPS:

```bash
ssh ubuntu@<vps-host> git -C /home/ubuntu/mnemon rev-parse HEAD
```

Then read it from any loop:

```python
from mrsearch import SnapshotReader

r = SnapshotReader("data")  # or set $MNEMON_DATA
r.tables()
df = r.table("v_market_state")
```

## Starting a new loop

Each loop is a numbered directory under `loops/` (e.g. `loops/02-<slug>/`) with:

1. `README.md` — question, method, result, one-paragraph conclusion.
2. `manifest.json` — provenance, written **before** anything is computed:

   ```python
   from mrsearch import Manifest, installed_metron_version, write_manifest

   write_manifest(
       "loops/02-<slug>",
       Manifest(
           snapshot_date="YYYY-MM-DD",  # UTC date of the rsync
           mnemon_commit="<sha from the VPS>",
           metron_version=installed_metron_version(),
           tables=("market_state", "markets"),  # what the loop reads
       ),
   )
   ```

3. `notebook.ipynb` — first cell reads and prints the manifest, then the work.

A result without a manifest is not reproducible and does not count.

## Rules

- Read-only against MNEMON in this phase; never write Parquet.
- No statistical logic in SQL — SQL does per-row algebra only; statistics live
  in METRON. A metric missing from METRON gets a TODO naming the function to
  add upstream, never a local implementation.

## Commands

```bash
uv run pytest
uv run ruff check .
```
