# CLAUDE.md

myrmidons-research is the consumer repo of a three-part stack: MNEMON (Parquet/
DuckDB archive of Morpho Blue state, the ingestion side), METRON (pure
statistical metric library), and this repo (research loops, risk-framework
work, write-ups). Since 2026-08-13 it is also the Phase 3 risk-engine repo:
it computes and writes MNEMON OUTPUT tables (the first is `liq_capacity`).

## Hard rules

- **Boundary.** This repo imports METRON (git dependency, pinned by tag in
  pyproject.toml). METRON must never import this repo, and nothing here goes
  upstream into it. MNEMON is a data source, not a dependency of record.
- **Read-only against MNEMON ingestion.** Every ingestion table and derived
  view stays read-only: never write their Parquet, never open the ingestion's
  `mnemon.duckdb`. The reader is an in-memory DuckDB over the `data/` globs.
- **One write namespace: `<data>/outputs/`.** The risk engine writes MNEMON
  OUTPUT tables under an `outputs/` prefix inside the store, physically
  separate from ingestion data. Only `mrsearch.outputs.OutputStore` writes,
  it resolves every path under that prefix, and nothing here ever writes
  outside it. MNEMON's ingestion enumerates its own table specs and never
  scans `outputs/`; `SnapshotReader` never registers output tables. Output
  tables are APPEND-ONLY: existing keys always win, history is never
  rewritten, a model change writes new rows under a new `model_version`.
- **No statistical logic in SQL.** SQL does per-row algebra only (unit scaling,
  joins, filters, resampling keys). Statistics live in METRON. If a metric is
  missing from METRON, do NOT implement it here — leave
  `# TODO(metron): add <function_name>` naming the function to add upstream.
- **Provenance before computation.** Every loop writes `manifest.json`
  (snapshot_date UTC, mnemon_commit, metron_version, tables) via
  `mrsearch.snapshot.write_manifest` before anything runs. The notebook's first
  cell reads and prints it. A result without a manifest does not count.

## Module map (risk engine)

- `mrsearch/protocol.py` — Morpho Blue algebra (`lif_from_lltv`,
  `max_slippage_threshold`). Deliberately local: METRON stays
  protocol-agnostic; these constants come from the contract.
- `mrsearch/outputs.py` — the outputs namespace: `OutputTable` specs
  (`LIQ_CAPACITY`) + `OutputStore` (append-only, day-partitioned on `as_of`,
  atomic tmp+replace, MNEMON-style hive layout).
- `mrsearch/liq_capacity.py` — orchestration + CLI
  (`uv run python -m mrsearch.liq_capacity`): per v_dex_slippage cycle and
  market, build the pair's slippage ladder, threshold from LLTV and haircut
  MINUS the $1k reference route's blended swap fee (model 1.1 — the
  measured curve nets that fee out; per-venue fee units in
  `FEE_UNIT_DIVISOR`, zero-reported fees default to 0.30%), call
  `metron.liquidation_capacity`, add interpolated HyperCore bid depth
  (WHYPE/UBTC/UETH/kHYPE — books of the same asset only), append rows keyed
  (as_of, market_id, model_version). Two ratios: `capacity_ratio`
  (isolated liquidation, own borrow) and `capacity_ratio_grouped`
  (same-collateral simultaneous stress: pro-rata depth sharing reduces to
  dividing by the collateral group's summed borrow). Idempotent: cycles
  already written under the current model version are skipped. Every row
  carries `params` + `input_window` JSON so it is recomputable from raw
  MNEMON inputs months later.

## MNEMON views: chosen approach

`mnemon_reader.SnapshotReader` imports the table specs and derived-view
definitions from a **local MNEMON checkout** — `$MNEMON_REPO` (or the
`mnemon_repo=` arg); its `src/` is put on `sys.path` and `mnemon.schemas`,
`mnemon.storage.Store`, `mnemon.views.create_derived_views` are imported by
reference. `views.py` is never vendored into this repo, so the `v_*` views here
can never drift from what the ingestion produces. Table docs: MNEMON's
`llms.txt`.

## Loop convention

`loops/NN-slug/` with `README.md` (question, data, method, result,
one-paragraph conclusion), `manifest.json`, `notebook.ipynb`, and `CLAUDE.md`
(working notes). Numbered in order started; never renumber. The README reads
like a methodology paper — no dated observations, no "verified on ..."
narration, no conversational asides; those go in the loop's CLAUDE.md as they
are found. Write READMEs and other external docs in ASD-STE100 simplified
technical English: short sentences, one idea per sentence, active voice, no
metaphors or idioms. Owner-verbatim text (loop questions) stays verbatim.

The Results section is a narrative, not a summary. Present each lane's
numbers in the order the lanes run. Interpret each result before the next
lane builds on it. State the question each result raises and which lane
answers it. Embed charts: the notebook saves every figure to the loop's
`assets/` directory (committed), and the README references them — charts
never come from outside the notebook. The Conclusion must follow visibly
from the numbered findings.

READMEs are publication-ready and self-contained. No TODOs, no bot names
(HEGEMON), no upstream-work notes, no pointers to any CLAUDE.md. Naming
MNEMON/METRON as the tools used is fine. Every internal reference lives in
the loop's CLAUDE.md instead.

`data/` is gitignored — the rsync target for the VPS snapshot (see README).

## Commands

Managed with uv (Python 3.12, pinned in .python-version).

- `uv run pytest`
- `uv run ruff check .`

Both green before any commit. No CI.
