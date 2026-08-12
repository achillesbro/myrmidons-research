# 01 — Oracle census

## Question

How does each oracle on the tracked HyperEVM markets behave? We measure
update cadence, direction, volatility, and divergence from a reference
price. Which markets show true staleness, assertion pricing, or depeg
signatures?

This loop does not try to predict issuer failure. The one bad-debt event on
HyperEVM (AVLT/USDT0) came from an issuer-NAV oracle that operated as
designed. The published value stopped being true. No statistic can detect
this before it occurs. The loop measures two things that data can show.
First, which markets get their price from issuer assertion and not from
market discovery. Second, which oracles diverge from an observable market
price. The second class includes an exchange-rate oracle that asserts par
through a real market depeg.

## Data

The MNEMON snapshot is pinned in `manifest.json`. It holds 5-minute
`market_state` for 71 HyperEVM markets, the `markets` dimension, and token
USD reference prices (`prices`: DeFiLlama with Morpho-API fallback). Oracle
prices exist on live rows only. Utilization, supply, and borrow extend back
to market creation through backfill. The loop CLAUDE.md records coverage
boundaries and known feed gaps.

The 5-minute snapshots show price changes, not on-chain update events. In
this loop, "staleness" means a run of unchanged observed prices. The oracle
updates in discrete steps, so 5-minute sampling loses little. The reference
price moves continuously, and its samples are 15 minutes (live) or 1 hour
(historical) apart. The divergence screen can only resolve divergences that
last at least one reference interval. It joins the oracle to the last known
reference point (ASOF join). It treats shorter divergences as noise. Flash
depegs are out of scope.

## Method

Three lanes. SQL extracts data. METRON computes statistics.

1. **Fingerprint census.** For each market, we take `oracle_price` from
   `v_market_state`. `staleness_stats` measures runs of unchanged price.
   `realized_vol` measures the volatility of oracle log-returns. We tabulate
   the share of upward moves by hand (`# TODO(metron): add direction_stats`).
   Output: each market gets one class — market-rate, exchange-rate,
   NAV-assertion, or PT-decay.
2. **Divergence screen.** `deviation_vs_reference` compares the
   oracle-implied collateral/loan ratio to the reference USD-price ratio,
   where reference coverage exists. Persistent divergence indicates
   assertion pricing. Sudden divergence indicates a depeg. A frozen
   reference is a data gap, not a signal.
3. **Calibration anatomy.** AVLT/USDT0 through its 2026-06-21 depeg is the
   known-positive case. We use the reference-price path and the oracle's
   frozen assertion gap. PT-decay markets are the known-benign control: they
   look stale but are correct.

Loop 02 covers exit dynamics.

## Result

The census fingerprints 63 markets, each with about 4,900 to 7,000
five-minute samples. Four behavior classes separate cleanly. 32 markets are
market-rate: sparse two-sided heartbeats (UBTC, UETH, WHYPE families; stale
share 0.8–0.96; up-share near 0.5). 14 are exchange-rate: accrual oracles
with 90% or more of their changes upward (LSTs, hbUSDT). 14 are NAV/sparse.
3 are frozen: AVLT with zero changes in 4,906 samples and a 17-day stale
stretch; hbHYPE/WHYPE and the matured PT-13NOV2025 at 29 days. Live PT
markets update at every sample, almost monotonically. They look stale by
reputation but measure as benign.

The divergence screen flags these events, in order of severity. AVLT/USDT0:
time-weighted mean deviation +196%, maximum +1035% — a frozen NAV against a
collapsing market price. sUSDe/USH: −31% with one 8-day spell above 5% —
here the loan token (USH) depegged, which shows the screen catches either
leg. USDH: a 7.6% peak across about 30 short spells. kHYPE: a market dip of
about 4% on 2026-07-29, which every kHYPE exchange-rate oracle asserted par
through — the exact failure class this screen exists for, at a survivable
size. Structural premia (thBILL, +1.5% mean) are persistent and stable. They
are features to model, not alerts.

The AVLT anatomy. Borrows accelerated into the depeg: 4.2M USDT0 in the week
of 2026-06-21. To deposit NAV-marked collateral and borrow against it was
the rational exit. 7.5M of the 9.8M supplied USDT0 escaped in a four-week
supply/repay rotation. 2.35M remains trapped at 100% utilization. The oracle
marks the collateral at 1.0945. The market prices it near 0.10–0.25.

The frozen oracle did not block liquidations. 750 liquidations fired between
2026-06-25 and 2026-08-02, with 5.2M USDT0 repaid; one address did 67% of
it. Each one executed at the frozen oracle mark: the implied seize price of
1.06658 equals oracle / LIF for LLTV 0.915, exact to five decimals. Interest
accrual is the trigger, not collateral repricing. At 639% APY-at-target and
100% utilization, debt grows into the LLTV while the mark stands still. The
median borrower health factor fell from 0.776 to 0.604 over three weeks. 253
borrowers were liquidatable and mostly stayed unliquidated: to repay real
USDT0 for collateral marked more than 4x above market is a certain loss to
the liquidator. Recorded bad debt for this market remains zero. The
chain-wide all-time total is 141 events and about $185.

## Conclusion

One month of live oracle data is enough to classify every HyperEVM oracle by
behavior, without reading a contract. The divergence screen finds real
events at every severity: a frozen NAV (AVLT), a loan-token depeg (USH), and
an LST dip that the oracles asserted away (kHYPE). The most important
finding concerns the metric, not the markets. Morpho records bad debt only
when a liquidation exhausts a position's collateral and debt remains. At an
inflated mark, the collateral always appears sufficient. The shortfall is
never recorded; it transfers to the liquidator. Realization requires the
oracle to converge to the market price, or interest to accrue past what the
frozen mark covers. Recorded bad debt therefore lags the economic loss for
as long as the assertion holds, and it reads zero throughout. Exposure
accounting must weight markets by oracle class: collateral priced by issuer
assertion is unpriceable risk, whatever its recorded history. The divergence
screen (persistent |deviation| ≥ 2% on a market-priced leg) is a workable
standing alert. Staleness alone is not a signal: the most stale-looking
healthy oracles (live PTs, heartbeat feeds) are benign by construction.
