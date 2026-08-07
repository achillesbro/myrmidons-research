# 01 — Oracle census

## Question

Across all tracked HyperEVM markets, how does each oracle actually behave —
update cadence, direction, volatility, divergence from reference price — and
which markets show genuine staleness, assertion pricing, or depeg signatures?

This loop makes no prediction claim about issuer failure: the one bad-debt
event on HyperEVM (AVLT/USDT0) was an issuer-NAV oracle working exactly as
designed while the number it published stopped being true, which no statistic
anticipates. It measures what is measurable: which markets price by assertion
rather than discovery (exposure accounting), and which oracles diverge from an
observable market price (depeg detection — the risk class where an
exchange-rate oracle asserts par through a real market depeg).

## Data

MNEMON snapshot pinned in `manifest.json`: 5-minute `market_state` for 71
HyperEVM markets with the `markets` dimension, and token USD reference prices
(`prices`; DeFiLlama with Morpho-API fallback). Oracle prices exist on live
rows only; utilization, supply and borrow extend back to market creation via
backfill. Coverage boundaries and known feed gaps are recorded in this loop's
CLAUDE.md.

Sampling note: 5-minute snapshots observe price *changes*, not on-chain update
events; "staleness" throughout means runs of unchanged observed price. The
oracle series samples a discretely-updating process, so little is lost at
5 minutes; the reference series samples a continuously-moving market price at
15-minute (live) or hourly (historical) cadence, so the divergence screen
resolves only divergences sustained for at least one reference interval, joins
oracle to reference as-of the last known reference point, and treats anything
shorter as noise. Flash depegs are out of scope by construction.

## Method

Three lanes; SQL does extraction only, statistics live in METRON.

1. **Fingerprint census** — per market, from `v_market_state.oracle_price`:
   `staleness_stats` on runs of unchanged price, `realized_vol` on oracle
   log-returns, directionality (share of up-moves; hand-tabulated —
   `# TODO(metron): add direction_stats`). Output: each market classified
   market-rate / exchange-rate / NAV-assertion / PT-decay.
2. **Divergence screen** — `deviation_vs_reference` of the oracle-implied
   collateral/loan ratio against the reference USD-price ratio, where
   reference coverage allows. Persistent divergence indicates assertion
   pricing; sudden divergence indicates a depeg; a frozen reference is a data
   gap, not a signal.
3. **Calibration anatomy** — AVLT/USDT0 through its 2026-06-21 depeg as the
   known-positive (reference-price arc plus the oracle's frozen assertion
   gap), PT-decay markets as the known-benign "stale-looking but fine"
   control.

Deferred to loop 02: exit dynamics (PT-hbUSDT-18DEC2025 illiquidity anatomy,
HEGEMON V1 stuck periods, utilization/exit-capacity screen).

## Result

(not run yet)

## Conclusion

(one paragraph, written after the run)
