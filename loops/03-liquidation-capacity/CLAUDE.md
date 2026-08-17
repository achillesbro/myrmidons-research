# Loop 03 — working notes

Internal notes; the README is the publication-ready document.

- Cross-section computed 2026-08-13 from the first VPS-written cycle
  (as_of 2026-08-13 15:00 UTC, model_version metron-v1.3.0+aead7a1). The
  writer is `mrsearch.liq_capacity`, wired as a daily systemd timer on the
  VPS (liq-capacity.timer, 00:20 UTC); the table accumulates hourly quote
  cycles from here.
- The kHYPE/WHYPE dip at $1M is diagnosed (2026-08-13, from stored
  route_json): the router flips between a direct kHYPE/WHYPE RamsesV3 CL
  pool (unit ~1.0225, used at $100k and $1M) and a kHYPE->USDC->WHYPE
  LiquidCore route whose USDC leg exhausts at ~$56k (used at $500k and
  $5M; $10M splits over four dust pools and collapses). Router path search
  is not monotone in size — the good route existed at $500k and was not
  selected. Consequences: the $500k rung understates the pair; capacity
  errs low (conservative); the first-crossing rule is vindicated on real
  data. If this pattern generalizes, a v2 could quote per-pool books or
  retry rungs, but only after observing more cycles.
- Model v2 (metron-v1.3.0+15811c5, 2026-08-13): capacity_ratio divides by
  LIF (debt-clearing units), and kHYPE maps to its OWN KHYPE/USDC Core
  book (@336) — measured at $3.3k inside the tolerable band, confirming
  the thinness the v1 assumption guessed. Owner-supplied facts behind the
  call: kinetiq.xyz/docs/faq — redemption to HYPE costs 0.1% but queues
  8-9 days (not liquidation timescale, so kHYPE→HYPE stays unmapped);
  KHYPE/USDC trades ~$10k/day on Core. The v1 rows (metron-v1.3.0+aead7a1,
  cycle 15:00) stay in the table; the notebook pins MODEL_VERSION and the
  newest cycle.
- Cross-cycle route instability is real: kHYPE/USDC DEX capacity read $62k
  at the 15:00 cycle and $154k at 16:00 — same pair, different router path
  choices. Distributional statements about the wall need the accumulated
  series, not one cycle.
- The censored row is a small UBTC market: its whole ladder stays under a
  10.8% threshold through $10M. Grid top, not market size, binds there.
- v_dex_slippage cycles: 14:00 UTC cycle exists only in the deleted local
  scratch store; the VPS store (and this snapshot) starts at 15:00 UTC.
- Re-running the notebook needs MNEMON_REPO set and the snapshot rsynced;
  outputs/ arrives with the same rsync (canonical rows are VPS-written).
- Next runs of this loop: time-variation of capacity_ratio once weeks of
  cycles exist; calibration against observed liquidations (fil d'Ariane E4)
  — does realized liquidator flow respect the modeled wall?

## Model 1.1 (2026-08-17, metron-v1.3.0+390430e)

- Fee-unit verification surprises: (1) the route `fee` field is NOT one
  unit — V3-style venues report Uniswap pips (/1e6; confirmed by a
  route-switch residual: removing a PrjxV3-3000 leg moved slippage ~0.1%,
  excluding the /1e4 reading outright), while LiquidCore reports bps
  (/1e4; an added LC-5 hop cost +3.3 bps measured vs +5 predicted).
  (2) Venues reporting fee 0 (HyperSwapV2, PrjxV2, KittenSwapV4,
  NestExchange) are a reporting gap, not free: a residual pins
  NestExchange at ~0.30% — 0.30% default adopted for all of them.
  (3) RamsesV3 and HybraV4 stayed ambiguous; larger (/1e4) reading chosen.
- v1 -> v1.1 deltas at the shared cycle (2026-08-16 23:00): 56 of 65
  markets lose capacity to the fee correction (median ref fee 15 bps,
  p75 36 bps, max 2.1%); one status change — AVLT/USD₮0 ok ->
  fee_exceeds_margin (route fee 2.3% > margin 2.1%; its v1 capacity $2.3k
  was an illusion of the netted-out fee). Largest single reduction $151k.
- The grouped ratio is the bigger of the two changes: isolated median
  1.21-1.23 vs grouped median 0.040; 51 of 64 markets shrink. Only the
  UBTC group clears 1 (2.97). kHYPE group $45.3M at 0.011; WHYPE group
  $45.2M at 0.064. The "34 of 64 markets clear ratio 1" line survives only
  under the isolated assumption.
- The 90-cycle retroactive recompute worked exactly as designed: the fee
  data was already in every stored route_json, so the whole accumulated
  series (5,850 rows) recomputed under v1.1 in one idempotent run.
- Recompute contradiction to watch: kHYPE/WHYPE's DEX capacity at the
  08:00 cross-section reads $517k (direct RamsesV3 pool route) vs $60-150k
  in earlier cycles — the router-instability wall moves more than first
  documented. The accumulated series, not any single cycle, is the object.
- Conclusion rewrite deliberately left TODO(owner); Results marked DRAFT.
