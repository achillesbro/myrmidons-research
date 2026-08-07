# Loop 01 — working notes

Observations and data-coverage findings that inform the method but don't
belong in the README (which reads as a methodology paper). Newest last.

## Data coverage (2026-08-07 snapshot)

- Live oracle-price capture began 2026-07 for all 63 covered markets (8 of 71
  have none) — a consequence of MNEMON's full-scan discovery deploy
  (2026-07-22). Census/divergence lanes run on ~1 month of 5-min data.
- Backfilled `market_state` rows have `oracle_price_raw = NULL` (the Morpho
  API serves no price history; see below). Utilization/supply/borrow ARE
  backfilled to market creation.
- AVLT/USDT0 has no oracle prices before 2026-07-21 — none pre-depeg.
- PT-hbUSDT-18DEC2025's DeFiLlama feed died 2026-05-03: frozen reference,
  excluded from the divergence lane rather than flagged by it.

## Morpho API: no oracle price history (verified live 2026-08-07)

Re-introspected api.morpho.org/graphql, confirming MNEMON's SCHEMA_NOTES.md:
- `MarketHistory` (the timestamped surface) has no price field of any kind.
- `Oracle` is static config (type, feeds, creation event) — no timeseries.
- The only historical price surface is `Asset.historicalPriceUsd`, and it is
  an independent market reference, NOT oracle-derived: over the post-07-21
  overlap, AVLT's oracle sits constant at 1.0945 while that reference moved
  ~1.01 → ~1.04 → ~0.32. The pre-depeg NAV trajectory is unrecoverable.

## Reference price (`prices`) timestamp semantics (checked 2026-08-07)

- `morpho_history` rows (192k, hourly, 2025-04-25 → 2026-07-28): provider-
  timestamped points from `Asset.historicalPriceUsd`, floored to the hour.
  Writes stop 2026-07-28 — live llama coverage takes over.
- `llama` rows (50k, 15-min, since 2026-07-09): ts is the JOB bucket
  (`floor_ts(now, 900)`); DeFiLlama's own quote timestamp is discarded by
  `normalize.price_rows_llama_current`, so the quote may be minutes older
  than ts. Optional MNEMON improvement if sub-15-min alignment ever matters:
  store the provider quote timestamp as a `quote_ts` column.
- DeFiLlama began listing AVLT in July 2026 — its 15-min rows continue where
  morpho_history ends.
- Divergence-lane consequence (also stated in README Data): oracle (5-min,
  discrete process) vs reference (15-min/hourly, continuous process) → only
  divergences sustained >= one reference interval are resolvable; ASOF join
  on last known reference; flash wicks out of scope.

## llama_fine backfill (2026-08-07, MNEMON PR #17)

- MNEMON now captures every native DeFiLlama point at its provider timestamp
  (source `llama_fine`) — live every 15 min plus a one-shot deep backfill.
  Snapshot re-synced same day (manifest updated to MNEMON abde3c1): 719,397
  fine rows, 27 tokens, back to 2025-04-25.
- Resolution varies with llama's own storage: ~10-15 min recently, hourly for
  low-liquidity tokens further back. AVLT's June depeg window is hourly
  (336 points, median gap 3600s) — true timestamps, same density as
  morpho_history there.
- Prefer `llama_fine` as the divergence-lane reference; it supersedes the
  bucket-stamped `llama` rows and the hour-floored histories wherever both
  exist.

## AVLT depeg facts (anchor for lane 3)

- Depeg ~2026-06-21 (Altura insolvency). MYRMIDONS never allocated into the
  market — this is someone else's loss, observed.
- DeFiLlama never listed AVLT; MNEMON's `prices` rows for it come from the
  `morpho_history` fallback and SPAN the depeg (2026-04-28 →): smooth
  NAV-tracking ~1.089 with gentle upward drift through 06-20 (1.0913), then
  06-21 onward 1.06 / 0.92 / 0.84 / 0.77 → ~0.32 by end-July.
- The oracle NAV kept accruing after the depeg (1.0913 on 06-20 → 1.0945)
  before freezing; still 1.0945 as of the snapshot → assertion gap ≈ 3.4x
  collateral overvaluation. Live positive example for the divergence lane.
