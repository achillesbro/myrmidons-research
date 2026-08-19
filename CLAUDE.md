# CLAUDE.md

myrmidons-research is the consumer repo of a four-part stack: MNEMON (Parquet/
DuckDB archive of Morpho Blue state, the ingestion side), METRON (pure
statistical metric library), myrmidons-api (the production risk engine: it
computes and writes MNEMON OUTPUT tables such as `liq_capacity`), and this
repo (research loops, risk-framework work, write-ups). The risk engine lived
here 2026-08-13 → 2026-08-19; it now lives in myrmidons-api.

## Hard rules

- **Boundary.** This repo imports METRON and myrmidons-api (git dependencies,
  pinned by tag in pyproject.toml). Neither must ever import this repo, and
  nothing here goes upstream into them. MNEMON is a data source, not a
  dependency of record. Production compute (output writers, orchestrators,
  protocol algebra) belongs in myrmidons-api, never here.
- **Read-only against MNEMON ingestion.** Every ingestion table and derived
  view stays read-only: never write their Parquet, never open the ingestion's
  `mnemon.duckdb`. The reader is an in-memory DuckDB over the `data/` globs.
- **One write namespace: `<data>/outputs/`.** The risk engine (myrmidons-api)
  writes MNEMON OUTPUT tables under an `outputs/` prefix inside the store,
  physically separate from ingestion data. Only
  `myrmidons_api.outputs.OutputStore` writes; this repo never writes the
  store at all. MNEMON's ingestion enumerates its own table specs and never
  scans `outputs/`; `SnapshotReader` never registers output tables. Output
  tables are APPEND-ONLY: existing keys always win, history is never
  rewritten, and a model change writes new rows under a new `model_version`.
- **No statistical logic in SQL.** SQL does per-row algebra only (unit scaling,
  joins, filters, resampling keys). Statistics live in METRON. If a metric is
  missing from METRON, do NOT implement it here — leave
  `# TODO(metron): add <function_name>` naming the function to add upstream.
- **Provenance before computation.** Every loop writes `manifest.json`
  (snapshot_date UTC, mnemon_commit, metron_version, tables) via
  `mrsearch.snapshot.write_manifest` before anything runs. The notebook's first
  cell reads and prints it. A result without a manifest does not count.

## Module map

- `mrsearch/snapshot.py` — loop provenance (`Manifest`, `write_manifest`,
  `read_manifest`). The only package code left in this repo.
- Everything else (protocol algebra, `SnapshotReader`, `OutputStore`, the
  liq_capacity orchestrator, systemd units) moved to **myrmidons-api**
  (2026-08-19). Loops import it directly:
  `from myrmidons_api import SnapshotReader, OutputStore, LIQ_CAPACITY`.
  Its `SnapshotReader` still imports MNEMON table specs and views by
  reference from a local checkout (`$MNEMON_REPO`) — never vendored.

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
