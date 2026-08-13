# myrmidons-research

Research loops joining MNEMON data with METRON logic. This is the consumer repo
of a three-part stack:

- **[MNEMON](https://github.com/achillesbro/MNEMON)** — the data layer: a
  Parquet/DuckDB archive of Morpho Blue state, ingested every 5–15 minutes on
  the VPS. This repo reads snapshots of it, read-only.
- **[METRON](https://github.com/achillesbro/METRON)** — the pure statistical
  metric library, installed here as a git dependency pinned by tag.
- **myrmidons-research** (this repo) — research loops, risk-framework work,
  write-ups, and the Phase 3 risk engine: it computes MNEMON OUTPUT tables
  (first: `liq_capacity`) and writes them to the store's `outputs/`
  namespace. Ingestion tables stay read-only.

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

## Risk engine: liq_capacity

The write side of Phase 3a. Per `v_dex_slippage` cycle and per market, the
runner builds the pair's slippage ladder, derives the max tolerable
liquidation slippage from the market's LLTV (Morpho Blue algebra in
`mrsearch.protocol`), calls `metron.liquidation_capacity`, adds HyperCore bid
depth for collaterals with a Core spot book, and appends one row per
(as_of, market_id, model_version) to `outputs/liq_capacity/`:

```bash
uv run python -m mrsearch.liq_capacity --data data --mnemon-repo ~/mnemon
```

The runner is idempotent (cycles already written under the current model
version are skipped) and cron-friendly. The canonical run happens on the VPS:
a daily systemd timer (`systemd/liq-capacity.timer` -> `run_liq_capacity.sh`,
00:20 UTC) processes every cycle the ingestion accumulated. A local run
against `data/` is a dry computation on a snapshot — note that the next
`rsync --delete` replaces `data/` (including `data/outputs/`) with the VPS
state, which carries the canonical outputs down.

Output tables are append-only, live only under `outputs/`, and every row
carries its `model_version`, `params` and `input_window`, so any row can be
recomputed from the raw MNEMON inputs months later.

## Rules

- MNEMON ingestion tables and views are read-only; the one write namespace is
  `outputs/` (via `mrsearch.outputs.OutputStore`, append-only).
- No statistical logic in SQL — SQL does per-row algebra only; statistics live
  in METRON. A metric missing from METRON gets a TODO naming the function to
  add upstream, never a local implementation.

## Commands

```bash
uv run pytest
uv run ruff check .
```
