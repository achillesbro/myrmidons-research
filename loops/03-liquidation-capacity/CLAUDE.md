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
