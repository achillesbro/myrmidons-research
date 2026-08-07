# 01 — Oracle census

## Question

Across all tracked HyperEVM markets (~71), how does each oracle actually
behave — update cadence, direction, volatility, divergence from reference
price — and which markets show genuine staleness, assertion pricing, or depeg
signatures?

Context: the one bad-debt event on HyperEVM (AVLT/USDT0, depeg ~2026-06-21)
was an issuer-NAV oracle working exactly as designed while the number became a
lie — qualitatively detectable, not quantitatively. This loop therefore makes
no prediction claim about issuer failure. It measures what IS measurable:
which markets price by assertion rather than discovery (exposure accounting),
and which oracles diverge from an observable market price (depeg detection —
the kHYPE/wstHYPE class of risk, where an exchange-rate oracle can assert par
through a real market depeg).

## Method

Three lanes; SQL does extraction only, statistics live in METRON.

1. **Fingerprint census** — per market, from `v_market_state.oracle_price`
   (live rows only; backfill has no oracle price): `staleness_stats` on runs
   of unchanged price, `realized_vol` on oracle log-returns, directionality
   (share of up-moves; hand-tabulated — `# TODO(metron): add direction_stats`).
   Output: each market classified market-rate / exchange-rate / NAV-assertion /
   PT-decay.
2. **Divergence screen** — `deviation_vs_reference` of the oracle-implied
   collateral/loan ratio vs the DeFiLlama USD-price ratio (`prices` table,
   27 tokens covered). Persistent divergence = assertion pricing; sudden
   divergence = depeg; frozen reference = data gap, not a signal.
3. **Calibration anatomy** — AVLT/USDT0 around 2026-06-21 as known-positive
   depeg (MYRMIDONS never allocated — someone else's loss), PT-decay markets
   as known-benign "stale-looking but fine" control.

Coverage constraints (checked 2026-08-07): live oracle-price capture began
2026-07 for all 63 covered markets (8 have none) — the census and divergence
lanes run on ~1 month of 5-min data. AVLT has NO oracle prices before
2026-07-21, i.e. none pre-depeg: its anatomy uses the DeFiLlama market price
(spans the depeg, 2026-04-28→) plus utilization/supply/borrow from backfilled
state, and the oracle enters only as the post-depeg assertion gap (NAV vs
collapsed market price). PT-hbUSDT-18DEC2025's DeFiLlama feed died 2026-05-03
(frozen reference — noted, not a divergence signal).

Sampling caveat: 5-min snapshots observe price *changes*, not on-chain update
events; "staleness" here means runs of unchanged observed price.

Deferred to loop 02: exit dynamics (PT-hbUSDT-18DEC2025 illiquidity anatomy,
HEGEMON V1 stuck periods, utilization/exit-capacity screen).

## Result

(not run yet)

## Conclusion

(one paragraph, written after the run)
