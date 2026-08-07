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

## market_flows depth (checked 2026-08-07)

- `market_flows` is COMPLETE event history since 2025-04-25, 150 markets:
  Supply/Withdraw/Borrow/Repay/SupplyCollateral/WithdrawCollateral/
  Liquidation per account per tx, with repaid/seized/bad_debt_assets.
  Borrower positions at any historical ts are reconstructable from flows
  (the hourly `positions` snapshots with API health factors only start
  2026-07-09).
- Realized bad debt across ALL HyperEVM liquidations ≈ $185 total (157
  events, largest USH/sUSDe ≈ $153, rest dust). AVLT appears NOWHERE in the
  bad-debt log: the frozen 1.0945 NAV keeps liquidations from ever
  triggering, so the one real loss is unrealized by construction. The
  recorded bad-debt metric is blind to exactly the assertion-oracle failure
  mode — state this in the census conclusion.

## Census run surprises (2026-08-07)

- MNEMON already ships the divergence per-row algebra: `v_oracle_price_check`
  (oracle vs ASOF DeFiLlama, both legs as collateral-in-loan-tokens) and
  `v_depeg_spells` (2%/5% episodes, 2h hole tolerance). Lane 2 consumes them
  and adds METRON stats — don't re-derive the SQL.
- hbHYPE/WHYPE oracle frozen 29 days (0 changes) — a second live frozen
  oracle beyond AVLT, unnoticed. Worth a qualitative look at that oracle.
- sUSDe/USH −31% deviation is the LOAN token depegging (USH), not the
  collateral: divergence catches either leg; sign tells which.
- kHYPE dipped ~4% on 2026-07-29 ~19:45 and every kHYPE exchange-rate oracle
  asserted par through it — first live observation of the class the user
  worried about; survivable size this time.
- AVLT flows: borrows ACCELERATED into the depeg (borrow-against-NAV was the
  smart exit); exit happened via matched supply/repay-withdraw rotations over
  ~4 weeks (weekly Supply ≈ Withdraw to the dollar, 23.5M gross in the
  biggest week); 2.2M USDT0 trapped at 100% util since 2026-07-20.
- Loan-side Supply/Withdraw in market_flows shows 1-7 distinct accounts —
  vault-intermediated; the exit door belonged to a couple of curators.
- up_share with <=10 nonzero changes is NaN → classifier sends those to
  nav/sparse; fine descriptively, revisit if the census ever drives sizing.

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
