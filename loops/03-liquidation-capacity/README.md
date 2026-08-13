# 03 — Liquidation capacity

## Question

When positions in a HyperEVM market must be liquidated, how much debt can
liquidators actually clear at a profit? Which markets owe more than the
venues around them can absorb?

Scope: every tracked HyperEVM market with a collateral token. This loop
defines the model, applies it to one full quote cycle as a cross-section,
and opens the output table that accumulates the time series. Distributional
statements about capacity over time belong to a later run of this loop.

## Data

The MNEMON snapshot is pinned in `manifest.json`. The model consumes four
inputs and writes one output:

- `dex_quotes` / `v_dex_slippage` — LiquidSwap aggregator route quotes per
  (collateral → loan) pair on a fixed USD ladder (1k, 10k, 50k, 100k, 500k,
  1M, 5M, 10M), hourly. Failed quotes persist with a status: a pair the
  aggregator cannot route has zero swap capacity, and that is data. The view
  derives slippage against the same cycle's $1k rung.
- `core_book_levels` / `v_core_depth` — HyperCore spot order books for the
  three collaterals with a Core listing of the same asset (HYPE, UBTC,
  UETH), stored at four price aggregations per snapshot. The view gives
  cumulative bid-side USD depth within 25/50/100/200/400 bps of mid, from
  the finest book that reaches each band.
- `markets`, `market_state`, `prices` — LLTV per market, outstanding borrow
  ASOF-priced in USD at the quote cycle.
- `outputs/liq_capacity` — the written result, append-only, keyed
  (as_of, market_id, model_version). Every row carries its `params` and
  `input_window` JSON, so any row recomputes from raw inputs alone. The
  notebook re-derives the largest market's row end to end as a check.

Three caveats set the limits of the data:

1. Quotes are aggregator route state, not executed trades. The model
   measures what the router sees, and routing quality bounds it from below.
   Observed liquidator behavior is a separate calibration (a later loop).
2. Venue coverage is one aggregator plus one order book. Any venue the
   model does not see makes true capacity larger, never smaller. Errors
   point in the conservative direction.
3. This cross-section is one cycle. The table accumulates hourly cycles
   under a daily writer, so persistence and time-variation of capacity are
   measurable later, not here.

## Method

### What the modeled capacity is

`capacity_total_usd` answers one question: if liquidation had to happen
now, how many dollars of this market's collateral could a liquidator sell,
in one transaction, into the liquidity we can observe, before the
liquidation stops being profitable? Below this size, liquidation is a
profitable arbitrage and can be expected promptly. Beyond it, every
additional dollar liquidated loses money, so the remaining debt waits —
for pool refills, for off-venue buyers, or for a deeper price move that
re-arms the incentive. `capacity_ratio` states what fraction of the
market's outstanding debt sits on the profitable side of that line.

The number is deliberately narrow in three ways. It is instantaneous: one
snapshot of quoted liquidity, no replenishment, so it bounds from below
what a patient liquidator could clear over hours — and it is exactly the
binding number when waiting is what hurts (a fast depeg). It is
market-level: it does not read the health-factor distribution; it is the
ceiling on profitable clearing whatever the queue of positions looks like.
And it is supply-side only: it says nothing about whether that much debt
will need liquidating.

### Derivation

A liquidation is a swap with a subsidy. Morpho Blue pays liquidators a
liquidation incentive factor set by the market's LLTV:

    LIF = min(1.15, 1 / (0.3 * LLTV + 0.7))

The liquidator seizes collateral worth LIF times the debt repaid. The gross
margin, as a fraction of seized collateral value, is `1 - 1/LIF` (closed
form `0.3 * (1 - LLTV)` when the 1.15 cap does not bind). Selling the
seized collateral costs slippage. Liquidation stays profitable while
slippage stays below the margin, so the max tolerable slippage is

    x = (1 - 1/LIF) - h

with `h = 0.005`, a haircut for gas, latency and inventory risk. When
`x <= 0` the incentive cannot cover the haircut and modeled capacity is
zero by construction (`zero_threshold`). A high-LLTV market therefore has
tight capacity twice over: less margin per liquidation and a lower
tolerable slippage.

DEX-route capacity is METRON's `liquidation_capacity` on the pair's quoted
slippage ladder: sort by size, interpolate linearly, return the first size
where the curve reaches `x`. Three choices keep the estimate conservative.
Slippage is convex in size, so the linear chord overestimates slippage
between rungs and the crossing lands early. The first crossing decides: a
curve that dips back below the threshold at a larger size does not reopen
capacity. Such dips are real in the data and they are router artifacts, not
liquidity: the aggregator's path search is not monotone in size, and it can
pick a worse route at one rung than at the next (the stored `route_json`
per rung shows which route each quote used). There is no extrapolation: a curve that
never crosses is right-censored at the largest quoted size and the true
capacity is at least the reported value (`capacity_censored`).

Core-book capacity applies only where a Core spot book trades the
collateral ITSELF: WHYPE → HYPE, UBTC, UETH, and kHYPE → its own
KHYPE/USDC book. kHYPE never maps to the HYPE book: the redemption path to
HYPE (Kinetiq, 0.1% fee) runs a multi-day unstaking queue, which is not a
liquidation timescale, so the swap routes and the KHYPE book are a
liquidator's whole exit. wstHYPE, beHYPE and PT tokens have no Core book
and do not map. Core capacity is the
cumulative bid-side USD depth within `x` of mid, interpolated linearly
between the stored bps tiers, anchored at (0, 0) below the first tier and
clamped at the deepest tier. Both ends understate depth — the same
conservatism direction as the DEX leg.

    capacity_total = capacity_evm + capacity_core
    capacity_ratio = (capacity_total / LIF) / outstanding_borrow

The ratio divides by LIF because capacity is sell-side collateral notional:
clearing debt D seizes and sells LIF × D of collateral, so capacity / LIF
is the debt-clearing equivalent the denominator compares against.

Two v1 simplifications are declared in every row's `params`: additivity of
the two venues (their standing inventories are distinct, but arbitrage
links them under stress), and Core mid treated as equivalent to the oracle
mark.

Provenance: every row records `model_version` (the METRON tag plus the
risk-engine commit), `params` (haircut, size grid, interpolation and
crossing rules, venues) and `input_window` (the exact as_of of each input
consumed). The table is append-only; a model change writes new rows under a
new version and never rewrites history.

## Results

All numbers come from `notebook.ipynb` over the cross-section cycle; the
charts are saved by the notebook into `assets/`. 65 markets: 57 `ok`, 7
`no_route`, 1 `no_price`; 64 carry outstanding borrow.

### Finding 1 — The DEX route walls out two orders of magnitude under the debt

Across markets with a routable pair, DEX capacity clusters far below the
large markets' debt: median $11k, p75 $55k, p95 $134k. The four largest
markets cross their thresholds between $55k and $154k, and their slippage
curves collapse onto the same cliff between $50k and $500k despite
different pairs and different thresholds:

![Slippage ladders and thresholds](assets/slippage_ladders.png)

Reading: the aggregator's pooled depth, not any market's own parameters,
sets the DEX-route capacity. Doubling the margin (`x` of 0.108 against
0.064) buys almost no extra size — the curves are near-vertical where they
cross. The kHYPE/WHYPE panel shows the first-crossing rule at work. The
quoted curve collapses at $500k, then returns to par at $1M. The stored
routes explain the dip: at $100k and $1M the router selects a direct
kHYPE → WHYPE concentrated-liquidity pool at near-zero impact, while at
$500k and $5M it routes through a kHYPE → USDC leg with about $56k of
effective depth. The recovery at $1M is the router re-finding a route that
also existed at $500k, not liquidity appearing at size. The model refuses
to count the region past the first crossing, which is correct here twice:
the dip is a search artifact, and if the direct pool truly holds that
depth, the reported capacity errs low, never high. The same instability
moves the wall between cycles — the same pair's crossing shifted by 2x
from one hour to the next as the router's path choice changed — without
ever bringing it within reach of the large markets' debt. The wall raises
the question finding 2 answers: what carries capacity beyond the router?

### Finding 2 — Where a Core book exists, it is the capacity; kHYPE's holds $3.3k

29 markets have collateral with a Core spot book, and for them the book
contributes 98.2% of modeled capacity: the HYPE book adds $3.5M and the
UBTC book $7.4M of tolerable-slippage depth, against DEX legs of
$2k–$155k. Modeled capacity is, in practice, Core depth wherever real
Core depth applies. The counter-case proves the rule: kHYPE maps to its
own KHYPE/USDC book, and that book holds $3.3k inside the tolerable band —
a listed pair with no depth. The measurement replaces the earlier
assumption and changes nothing: kHYPE's exit is the DEX route. This
raises finding 3: most of the chain's debt sits on collateral whose book
is absent or empty.

### Finding 3 — The largest debt stacks are the least covered

The aggregate hides the problem: $99.3M of outstanding borrow against
$96.3M of modeled capacity reads as near-parity. The distribution inverts
it. 34 of 64 markets clear ratio 1, but they are small — the five largest
markets hold 83.8% of the chain's debt and their pooled ratio is 0.051.

![Capacity against outstanding borrow](assets/capacity_vs_borrow.png)

The composition of the top of the table:

![Coverage of the twelve largest debt stacks](assets/capacity_ratio_top.png)

- kHYPE markets owe $45.8M — nearly half the chain — and the four largest
  sit at ratios between 0.008 and 0.028. Their capacity is a ~$120–154k
  DEX route plus a $3.3k Core book against eight-figure debt; the deep
  HYPE book does not apply, because unstaking into it takes days.
- WHYPE/USDC, the largest single market at $37.8M, reaches only 0.090 even
  with the HYPE book: `x = 0.064` caps the usable band of the book at
  $3.5M.
- AVLT/USD₮0 owes $2.7M at ratio 0.001: LLTV 0.915 leaves `x = 0.021`, and
  the pair's quoted depth inside that band is $2.3k.

Reading: capacity and debt live on different collaterals. The markets that
would matter in a stress event are precisely the ones the venues cannot
absorb within the protocol's incentive.

### Finding 4 — Zero-capacity rows are findings, not gaps

Seven pairs return `no_route` at every rung: six PT-kHYPE markets and
sUSDe/USH, together owing $0.3M. The aggregator cannot swap these
collaterals at all — a liquidator's exit is redemption or an off-router
venue, both outside this model, so modeled capacity is zero rather than
unknown. One market's whole quoted curve stays below its threshold and is
right-censored: its true capacity exceeds the $10M grid top, and the row
says so instead of guessing.

## Conclusion

The model prices a liquidation as a subsidized swap and asks whether the
subsidy covers the exit. From finding 1: on the DEX route the answer stops
depending on the market almost immediately — the router's pooled depth
walls every pair two orders of magnitude under the large markets' debt,
so LLTV-driven margin differences barely move capacity. From finding 2:
real capacity lives where a Core order book holds real depth in the
collateral itself, and there it is effectively the whole model — while
kHYPE's own book, measured, holds $3.3k. From finding 3: depth is absent
exactly where the debt is — half the chain's borrow sits on staked-HYPE
collateral whose only liquidation-timescale exits are a ~$150k DEX route
and that empty book, and the five largest markets are covered at five
cents on the dollar. The
practical output for cap sizing is the ratio column and its status flags:
a market's safe borrow scale is set by its collateral's route to real
depth, not by its LLTV, and the markets that look deepest by TVL are the
least liquidatable per dollar owed. Every number here is conservative by
construction and recomputable from its own row months later; what the
cross-section cannot yet say — how capacity moves, and whether observed
liquidations respect the modeled wall — is what the accumulating table and
the liquidation-replay loop exist to answer.
