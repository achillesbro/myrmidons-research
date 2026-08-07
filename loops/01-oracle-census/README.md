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

Fingerprints for 63 markets (~4,900–7,000 five-minute samples each) separate
cleanly into four behaviors: 32 market-rate (sparse two-sided heartbeats —
UBTC/UETH/WHYPE families, stale-share 0.8–0.96 but up-share ≈ 0.5), 14
exchange-rate (accrual oracles, ≥90% of changes upward — LSTs, hbUSDT), 14
NAV/sparse, and 3 frozen (AVLT at zero changes in 4,906 samples with a 17-day
stale stretch; hbHYPE/WHYPE and the matured PT-13NOV2025 at 29 days). Live PT
markets update every sample near-monotonically — stale-looking by reputation,
benign by measurement.

The divergence screen flags, in order of severity: AVLT/USDT0 (time-weighted
mean deviation +196%, max +1035% — the frozen NAV against a collapsing market
price), sUSDe/USH (−31%, one 8-day ≥5% spell — a loan-token depeg, showing
divergence catches either leg), a USDH wobble (7.6% peak, ~30 short spells),
and a kHYPE market dip of ~4% on 2026-07-29 that every kHYPE exchange-rate
oracle asserted par through — the exact failure class this screen exists for,
at survivable size. Structural premia (thBILL +1.5% mean) are persistent and
two-sided-stable: features to model, not alerts.

The AVLT anatomy: borrows accelerated *into* the depeg (4.2M USDT0 the week
of 2026-06-21 — depositing NAV-marked collateral and borrowing against it was
the rational exit); ~7.5M of 9.8M supplied USDT0 escaped in a four-week
supply/repay rotation; 2.2M remains trapped at 100% utilization against
collateral the oracle marks at 1.0945 and the market prices near 0.10–0.25.
Recorded bad debt on the whole chain, all time: 157 events, ≈ $185. The AVLT
hole (~$1.5–2M economic) does not appear in it, because the frozen oracle
prevents the liquidations that would record it.

## Conclusion

On one month of live oracle data, behavioral fingerprints classify every
HyperEVM oracle without reading a single contract, and the divergence screen
finds real events at every severity: a fatal frozen NAV (AVLT), a loan-token
depeg (USH), and a par-asserting LST dip (kHYPE) — but the census's sharpest
finding is about the metric, not the markets. Recorded bad debt measures only
what liquidations realize, and assertion-priced oracles suppress liquidations
precisely when losses occur, so the standard risk number is structurally
blind to the worst failure mode. Exposure accounting should therefore weight
markets by oracle class — frozen/NAV-assertion collateral is unpriceable risk
regardless of its history — and the divergence screen (persistent |deviation|
≥ 2% on a market-priced leg) is a workable standing alert, while staleness
alone is not a signal: the most stale-looking healthy oracles (live PTs,
heartbeat feeds) are benign by construction.
