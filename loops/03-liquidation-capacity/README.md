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
in one transaction, into the observable liquidity, before the liquidation
stops being profitable? Below this size, liquidation is a profitable
arbitrage and can be expected promptly. Beyond it, every additional dollar
liquidated loses money. The remaining debt then waits for pool refills,
for off-venue buyers, or for a deeper price move that restores the
incentive. The ratio columns state what fraction of debt sits on the
profitable side of that line.

The number is deliberately narrow in three ways. It is instantaneous: one
snapshot of quoted liquidity, with no replenishment. It therefore bounds
from below what a patient liquidator could clear over hours, and it is the
binding number when the price moves fast (a depeg). It is market-level: it
does not read the health-factor distribution, and it is the limit on
profitable clearing for any distribution of positions. And it is
supply-side only: it says nothing about whether that much debt will need
liquidating.

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
zero by construction (`zero_threshold`). Two effects reduce a high-LLTV
market's capacity: less margin per liquidation and a lower tolerable
slippage.

DEX-route capacity is METRON's `liquidation_capacity` on the pair's quoted
slippage ladder: sort by size, interpolate linearly, return the first size
where the curve reaches `x`. Three choices keep the estimate conservative.
Slippage is convex in size, so the linear chord overestimates slippage
between rungs and the crossing lands early. The first crossing decides: a
curve that dips back below the threshold at a larger size does not reopen
capacity. Such dips are real in the data, and they are router artifacts,
not liquidity. The aggregator's path search is not monotone in size: it
can pick a worse route at one rung than at the next. The stored
`route_json` per rung shows which route each quote used. There is no
extrapolation: a curve that never crosses is right-censored at the largest
quoted size, and the true capacity is at least the reported value
(`capacity_censored`).

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
    capacity_ratio         = (capacity_total / LIF) / outstanding_borrow
    capacity_ratio_grouped = (capacity_total / LIF) / collateral_group_borrow

Both ratios divide by LIF because capacity is sell-side collateral
notional: clearing debt D seizes and sells LIF × D of collateral, so
capacity / LIF is the debt-clearing equivalent the denominators compare
against.

The two ratios answer different stress questions. `capacity_ratio` divides
by the market's own borrow: the market liquidates ALONE, with the venues'
full depth to itself. But markets sharing a collateral are stressed by the
same price move, and their liquidators sell into the same books and pools —
depth is a property of the collateral, not of the market.
`capacity_ratio_grouped` therefore divides by the summed borrow of every
tracked market sharing the collateral at the cycle (dead-router markets
included: their debt competes even when their own path is closed). The
pro-rata depth allocation `capacity × (borrow_i / borrow_group)` over own
borrow reduces algebraically to this closed form. Route overlap ACROSS
collateral groups (one collateral's route crossing another's pools
mid-path) is not modeled here; it belongs to the shock simulator.

The threshold subtracts one more cost. The slippage curve is measured
against the same cycle's $1k reference rung. The reference route's own
swap fee therefore nets out of every measured value, but the liquidator
still pays it. (The reference rung's impact also nets out; the model
treats it as 0 and declares this.) The threshold applied is
`x_used = max(0, x - fee_ref)`. `fee_ref` is the blended fee of the $1k
rung's stored route: within a hop that splits across pools, each split's
fee weighs by its amountIn share; across sequential hops, fees compound. Fee units are per-venue, verified against stored routes:
V3-style venues report Uniswap pips (fee/1e6), LiquidCore reports basis
points, and a reported fee of 0 is a reporting gap, not a free swap — such
venues carry a 0.30% default. When no reference route can be recovered,
the threshold keeps the full value of `x` and the row records that no fee
was subtracted — never a silent fee of zero. A market whose
reference-route fee alone exceeds the margin reports `fee_exceeds_margin`,
distinct from `zero_threshold` (haircut alone).

Two declared simplifications live in every row's `params`: additivity of
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
charts are saved by the notebook into `assets/`. 65 markets: 55 `ok`, 7
`no_route`, 2 `no_price`, 1 `fee_exceeds_margin`; 64 carry outstanding
borrow.

### Finding 1 — The DEX route stops two orders of magnitude below the debt

Across markets with a routable pair, DEX capacity clusters far below the
large markets' debt: median $12k, p75 $56k, p95 $145k. The largest markets
cross their thresholds between $55k and $517k, and their slippage curves
steepen in the same size region despite different pairs and different
thresholds:

![Slippage ladders and thresholds](assets/slippage_ladders.png)

Reading: the aggregator's pooled depth, not any market's own parameters,
sets the DEX-route capacity. A doubled margin (`x` of 0.108 against 0.064)
adds almost no size, because the curves are near-vertical where they
cross. The kHYPE/WHYPE panel shows the first-crossing rule on real data.
The quoted slippage jumps above 80% at $500k, then returns to par at $1M.
The stored routes explain the dip. At $100k and $1M the router selects a
direct kHYPE → WHYPE concentrated-liquidity pool at near-zero impact. At
$500k and $5M it routes through a kHYPE → USDC leg with about $56k of
effective depth. The recovery at $1M is the router selecting a
route that also existed at $500k. It is not liquidity that appears at
size. The model does not count the region past the first crossing. That
rule is correct here twice: the dip is a search artifact, and if the
direct pool truly holds that depth, the reported capacity errs low, never
high. The same instability moves the crossing between cycles — the same
pair's crossing shifted by 2x from one hour to the next as the router's
path choice changed — but it never comes near the large markets' debt.
This limit raises the question finding 2 answers: what carries capacity
beyond the router?

### Finding 2 — Where a Core book exists, it is the capacity; kHYPE's holds $3.4k

29 markets have collateral with a Core spot book, and for them the book
contributes 97.7% of modeled capacity. The HYPE book adds $3.0M and the
UBTC book $6.3M of tolerable-slippage depth, against DEX legs of
$2k–$517k. Modeled capacity is, in practice, Core depth wherever real
Core depth applies. kHYPE is the counter-case: it maps to its own
KHYPE/USDC book, and that book holds $3.4k inside the tolerable band — a
listed pair with almost no depth. kHYPE's usable exit is therefore the
DEX route. This raises finding 3: most of the chain's debt sits on
collateral whose book is absent or almost empty.

### Finding 3 — The largest debt stacks are the least covered

The aggregate hides the problem: $99.7M of outstanding borrow against
$83.1M of modeled capacity reads as near-parity. The distribution inverts
it. 34 of 64 markets clear an isolated ratio of 1, but they are small.
The five largest markets hold 83.8% of the chain's debt, and their pooled
ratio is 0.046. The grouped ratio inverts it further: the isolated median
is 1.23, the grouped median is 0.040, and the ratio of 51 of 64 markets
falls when their same-collateral neighbors compete for the same depth.
Per collateral group: kHYPE owes $45.3M at a grouped ratio of 0.011,
WHYPE owes $45.2M at 0.064, and UBTC ($2.0M at 2.97) is the only group
above 1.

![Capacity against outstanding borrow](assets/capacity_vs_borrow.png)

The composition of the top of the table:

![Coverage of the twelve largest debt stacks](assets/capacity_ratio_top.png)

- kHYPE markets owe $45.3M — nearly half the chain — at a grouped ratio of
  0.011 (isolated ratios 0.004–0.032 across the four largest). Their
  capacity is a DEX route plus a $3.4k Core book against eight-figure
  debt; the deep HYPE book does not apply, because unstaking into it takes
  days.
- WHYPE/USDC, the largest single market at $38.6M, reaches an isolated
  0.075 and a grouped 0.064 even with the HYPE book. Its applied threshold
  `x_used = 0.061` caps the usable band of the book at $3.0M, and $45.2M
  of WHYPE-collateralized debt shares that band.
- AVLT/USD₮0 owes $2.9M at capacity zero, status `fee_exceeds_margin`:
  LLTV 0.915 leaves a 2.1% margin, and the pair's cheapest quoted route
  charges 2.3% in swap fees alone. The incentive cannot pay for any exit
  at any size.

Reading: capacity and debt live on different collaterals. The markets that
would matter in a stress event are precisely the ones the venues cannot
absorb within the protocol's incentive.

### Finding 4 — Zero-capacity rows are findings, not gaps

Seven pairs return `no_route` at every rung: six PT-kHYPE markets and
sUSDe/USH, together owing $0.3M. The aggregator cannot swap these
collaterals at all. A liquidator's exit is then redemption or an
off-router venue, both outside this model, so modeled capacity is zero
rather than unknown. The second zero-capacity class is
`fee_exceeds_margin` (AVLT/USD₮0 above): a route exists, but its fee alone
exceeds the liquidation margin. The fee term itself is small but
one-sided: the median reference route charges 15 bps, the largest 2.1%,
and it lowers the capacity of 56 of 65 markets. Without it, the measured
slippage would understate the liquidator's true cost — the one error
direction the model must not have.

## Conclusion

The model prices a liquidation as a subsidized swap and asks whether the
subsidy covers the exit. From finding 1: on the DEX route the answer
stops depending on the market almost immediately. The router's pooled
depth limits every pair to two orders of magnitude below the large
markets' debt, so LLTV-driven margin differences barely move capacity.
From finding 2: real capacity lives where a Core order book holds real
depth in the collateral itself, and there it is effectively the whole
model — while kHYPE's own book, measured, holds $3.4k. From finding 3:
depth is absent exactly where the debt is, and the grouped ratio states
it correctly. A market's isolated ratio assumes it liquidates alone; its
collateral group liquidates together, into the same books. Under that
reading the median market's coverage falls from 1.23 to 0.040. The kHYPE
group ($45.3M, nearly half the chain) has a grouped ratio of 0.011, the
WHYPE group ($45.2M) 0.064. UBTC is the only collateral on the chain
whose debt the venues can absorb in full. From finding 4: the model's
zero rows are exact, not missing — unroutable PT collateral, and one
market (AVLT) whose cheapest route charges more in swap fees than the
protocol's entire liquidation margin pays.

The practical output for cap sizing is the grouped ratio and the status
flags. A market's safe borrow scale is set by its collateral's route to
real depth, shared with every sibling market on that collateral — not by
its LLTV. The markets that look deepest by TVL are the least liquidatable
per dollar owed. Every number is conservative by construction and
recomputable from its own row months later. What the cross-section cannot
yet say — how capacity moves over time, and whether observed liquidations
stay below the modeled limit — is what the accumulating table and the
liquidation-replay loop exist to answer.
