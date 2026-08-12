# CLAUDE.md

myrmidons-research is the consumer repo of a three-part stack: MNEMON (Parquet/
DuckDB archive of Morpho Blue state, the write side), METRON (pure statistical
metric library), and this repo (research loops, risk-framework work, write-ups).
Later this becomes the Phase 3 risk-engine repo writing to MNEMON output tables
— not in this phase.

## Hard rules

- **Boundary.** This repo imports METRON (git dependency, pinned by tag in
  pyproject.toml). METRON must never import this repo, and nothing here goes
  upstream into it. MNEMON is a data source, not a dependency of record.
- **Read-only against MNEMON.** Never write Parquet, never open the ingestion's
  `mnemon.duckdb`. The reader is an in-memory DuckDB over the `data/` globs.
- **No statistical logic in SQL.** SQL does per-row algebra only (unit scaling,
  joins, filters, resampling keys). Statistics live in METRON. If a metric is
  missing from METRON, do NOT implement it here — leave
  `# TODO(metron): add <function_name>` naming the function to add upstream.
- **Provenance before computation.** Every loop writes `manifest.json`
  (snapshot_date UTC, mnemon_commit, metron_version, tables) via
  `mrsearch.snapshot.write_manifest` before anything runs. The notebook's first
  cell reads and prints it. A result without a manifest does not count.

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

`data/` is gitignored — the rsync target for the VPS snapshot (see README).

## Commands

Managed with uv (Python 3.12, pinned in .python-version).

- `uv run pytest`
- `uv run ruff check .`

Both green before any commit. No CI.
