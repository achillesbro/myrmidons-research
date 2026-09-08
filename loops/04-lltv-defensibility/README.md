# 04 — LLTV defensibility

## Question

Does the LLTV of each market leave room for the worst collateral move its
price history holds, before the protocol books bad debt? Which curators fund
markets whose history has already breached that room, and where do curators
disagree on the same collateral?

Scope: every market with a collateral token on Ethereum, Base and HyperEVM.
This loop reads one published cross-section of the LLTV defensibility
metrics, interprets it, and benchmarks the curators' allocations against it.
Time variation of the verdict belongs to a later run of this loop.

## Data

The MNEMON snapshot is pinned in `manifest.json`. The loop reads five inputs
and computes no new statistic:

- `outputs/market_metrics` — the `worst_drop_{1,6,24}h` and
  `lltv_headroom_{1,6,24}h` metrics, written hourly by the risk engine for
  every market. The loop pins one model version and the newest cycle. Every
  row carries its `params` (buffer, LIF, coverage, history length, cleaning
  rule, samples dropped) and `input_window` (history start and end, sample
  count), so any row recomputes from the raw inputs alone. The notebook
  rebuilds the largest listed Ethereum market's row end to end as a check.
- `outputs/liq_capacity` — outstanding borrow in USD per market at the
  nearest cycle, used only as a weight.
- `markets` — LLTV, token symbols and decimals, and the `listed` flag of the
  Morpho app. Unlisted markets exist on chain but the app does not show
  them. Some carry synthetic positions: one unlisted PAXG/USDC market
  reports 7.2 billion USDC of borrow equal to its supply. Weighted figures
  are therefore given for listed markets separately.
- `vault_allocations` and `vaults` — how much each tracked vault supplies to
  each market at the latest snapshot, and the vault's display name.
- `prices` — hourly USD prices of both legs, for the recomputation check and
  for the USD value of the vaults' supply.

Three caveats set the limits of the data:

1. The price history is hourly and starts on 2025-01-01 for Ethereum and
   Base and on 2025-04-25 for HyperEVM. It holds the 2025-02-03 and
   2026-02-05 crashes, the 2025-10-10 HYPE crash, the 2025-11 deUSD
   collapse and the 2026-03-22 Resolv depeg. It does not hold 2022.
2. The feeds carry artifacts: one-hour ticks and short plateaus at wrong
   prices, and decimal-scale garbage for some self-priced tokens. The
   engine removes them with two declared rules (Method). What survives is
   what the feed said.
3. The two legs of a pair are sampled at different minutes within the hour
   during the live period. A fast market alone produces a few percent of
   apparent cross-rate move. Pairs whose buffer is a few percent sit at the
   resolution limit of the data.

## Method

### What the metric is

A liquidation on Morpho Blue repays debt and seizes collateral worth LIF
times the repaid debt, with `LIF = min(1.15, 1 / (0.3 x LLTV + 0.7))`. A
position at the liquidation threshold holds collateral worth `debt / LLTV`.
It clears without loss while its collateral is worth at least `LIF x debt`,
so the protocol books bad debt once the collateral has fallen by more than

    buffer = 1 - LLTV x LIF

since the threshold. At 86% LLTV the buffer is 10.2%; at 96.5% it is 2.5%.
This buffer is smaller than `1 - LLTV`, which says when liquidation starts
for a reference position, not when it stops covering the debt.

The collateral is priced in loan units: `collateral_usd / loan_usd`, last
price per hour, on the hours where both legs have a price. A USD series is
the wrong input for a correlated pair such as wstETH/WETH or kHYPE/WHYPE:
it inherits the loan asset's volatility and misses the depeg that
liquidates. The cross rate also catches loan-side events. A loan stablecoin
that depegs and rebounds appears as a drop of the collateral in loan units,
which is the shock the market's oracle marks.

`worst_drop_{tau}h` is the worst cumulative log return over any window of
tau consecutive hourly samples in the whole stored history, for tau of 1, 6
and 24 hours. `lltv_headroom_{tau}h` is the buffer minus the worst simple
drop, `1 - exp(worst_drop)`. Positive headroom means the history never
breached the buffer at that horizon.

### Guards and cleaning rules

A market gets no verdict when its history is shorter than 90 days or when
fewer than 90% of the hour slots between its first and last sample hold a
price. The measured values are in the row's params.

Two rules clean the feed before anything is computed. A run of at most
three samples that sits more than 0.5 log units from both the sample before
it and the sample after it, in the same direction, while those two samples
agree within 0.2 log units, is dropped. A 65% move that fully returns within
three hours is a feed tick, not a price. Moves that persist or that do not
return are kept. Prices below one millionth of a dollar are excluded. Both
rules and the number of samples they removed are in the row's params.

### The verdict

A market is *defensible* at a horizon when its headroom is strictly
positive and *breached* when it is negative. The horizon is the time a
liquidation takes after a position crosses the threshold: one hour for a
liquid collateral with a working oracle and active keepers, six or
twenty-four hours when liquidation waits for capacity, for an oracle update,
or for a keeper.

Liquidation costs are not subtracted from the headroom in this run. The
slippage a liquidator pays at the observed capacity (loop 03) and the
deviation of the market's oracle from the reference price both reduce the
room. Headroom is therefore an upper bound on defensibility. The rows say
so (`costs: none`).

### The curators' benchmark

Morpho Blue markets are permissionless. A curator does not set an LLTV; it
chooses which LLTV market to fund. The latest `vault_allocations` snapshot
gives the markets each vault supplies and how much. The supply converts to
USD with the loan asset's latest price. The curator label is the first word
of the vault's name. Two labels are brands rather than firms: Smokehouse is
Steakhouse's higher-risk line, and Vault stands for Vault Bridge. The
benchmark is the share of each curator's supplied USD, among markets with a
verdict, that sits in markets whose history breached the buffer, at 1h and
at 24h. Where two curators fund different LLTV tiers of the same pair, the
tiers and their verdicts are listed.

## Results

All numbers come from `notebook.ipynb` over one cross-section cycle; the
charts are saved by the notebook into `assets/`. The three chains hold 515
markets with a collateral: 324 on Ethereum, 125 on Base, 66 on HyperEVM.

### Finding 1 — At 24 hours the history breaches most LLTVs; at one hour it defends most of them

248 markets carry a verdict at every horizon. At 24h, 100 of 147 Ethereum
markets are breached, 43 of 56 on Base, 16 of 45 on HyperEVM. At 1h the
picture inverts: 95 of 147 defensible on Ethereum, 43 of 56 on Base, 35 of
45 on HyperEVM. Weighted by borrow over listed markets, 87.1% of $2,763M
sits in markets breached at 24h and 6.4% in markets breached at 1h.

![Headroom against LLTV](assets/headroom_vs_lltv.png)

Reading: the dashed line is the buffer itself, the headroom of a collateral
that never moved. Every point sits below it by the worst 24h drop of its
pair. The 86% tier, where most of the debt lives, has a 10.2% buffer, and
the worst 24h drops of BTC and ETH against USD in the history are 14.6% and
20.4%. That tier is breached at 24h for every BTC and ETH market. The 62.5%
tier holds a 29.6% buffer, and almost every market there is defensible.
This raises the question the next finding answers: at what horizon do the
large markets turn?

### Finding 2 — The large markets turn between one and six hours

![Headroom by horizon, twenty largest listed markets](assets/headroom_by_horizon.png)

Reading, for the twenty largest listed debt stacks:

- cbBTC/USDC at 86% on Base, the largest market at $1,390M: headroom +5.1%
  at 1h, +0.3% at 6h, -4.4% at 24h. WBTC/USDC on Ethereum reads the same:
  +5.3%, +1.0%, -3.9%. A BTC market at 86% is defensible if liquidation
  completes within about six hours of the threshold crossing, and not
  otherwise.
- The ETH markets at 86% turn earlier. wstETH/USDT reads +3.3% at 1h, -6.9%
  at 6h, -11.6% at 24h; WETH/USDC on Base +3.3%, -5.7%, -10.2%; weETH/PYUSD
  +0.1%, -5.9%, -10.5%. Their defensibility rests on liquidation inside one
  hour.
- The stablecoin and RWA collaterals with a USD loan (AA_FalconXUSDC,
  mF-ONE, PST, wFalconX) read the same positive headroom at every horizon.
  Their history holds no move of the size of their buffer.
- cbXRP/USDC at 62.5% and WHYPE/USDC at 77% are defensible at every horizon
  with +5.3% and +0.7% left at 24h.
- wstETH/WETH at 96.5% ($77M) and at 94.5% ($26M) are breached at every
  horizon, by 0.4% to 3.2%. Their buffers are 2.5% and 3.9%, and the worst
  moves measured, 4.3% to 5.7%, are within the resolution limit set by the
  two legs' sampling (Data, caveat 3). The data cannot judge these two
  markets. Same-minute alignment of the legs is what a verdict on them
  needs.

Across the three chains, 87 markets are defensible at 1h and breached at
24h; the 63 listed ones hold $2,230M of borrow. 75 markets are breached
even at 1h. They are the collapsed or depegged collaterals (RLP, USR,
AVLT, deUSD-based tokens, USUALX), the PT tokens of those, volatile
long-tail tokens against USDC (EIGEN, KTA, TOSHI), LsETH, and the LST/WETH
and BTC/BTC pairs at 91.5% to 96.5%. The verdict at 24h is a
statement about liquidation latency, not about the LLTV alone. This raises
the question of finding 3: when two tiers coexist, does the history split
them?

### Finding 3 — Where two tiers coexist, the history defends the lower one

![Collateral tiers against the worst drop](assets/collateral_tiers.png)

25 pairs trade at two or more LLTVs. The 24h history defends every tier on
10 of them and no tier on 9. It splits the tiers on 6:

- cbXRP/USDC on Base: the worst 24h drop is 24.3%. The 62.5% tier's buffer
  of 29.6% holds; the 77% tier's 17.3% does not.
- UBTC/USD₮0, UBTC/USDe and UETH/USD₮0 on HyperEVM: worst drops of 13.8% to
  14.5% sit between the 77% tier's 17.3% and the 86% tier's 10.2%.
- wstETH/WETH and weETH/WETH on Base: drops of 3.2% and 4.9% split the
  94.5% tier from the 96.5%, and the 91.5% from the 94.5%. These are the
  resolution-limit pairs of finding 2.

Reading: the split is where the market's own history draws the line
between tiers, without a model. On HyperEVM it falls exactly between the
two tiers in use for BTC and ETH collateral. This raises the question of
finding 4: which tiers do the curators fund?

### Finding 4 — The curators' money sits on the 24h-breached side, except on HyperEVM

74 vaults on the three chains supply $1,357M into collateral markets. Seven
curators supply $20M or more:

![Curators' supply in breached markets](assets/curator_breach_share.png)

- Gauntlet ($500M, 19 vaults, 68 markets): 97.2% of its judged supply sits
  in markets breached at 24h, 3.2% in markets breached at 1h.
- Steakhouse ($348M, 9 vaults, 47 markets): 99.2% at 24h, 9.6% at 1h.
- Spark ($313M, 2 vaults, 3 markets): 100% at 24h, 0% at 1h. Its three
  markets are the BTC and ETH majors at 86%.
- Smokehouse ($37M): 44.4% at 24h, 2.1% at 1h. Vault Bridge ($28M): 100%
  at 24h and 41.6% at 1h, the highest 1h exposure of the seven. Hakutora
  ($26M): 100% at 24h, 0% at 1h.
- Felix ($32M, HyperEVM): 0.3% at 24h and 0% at 1h. Its markets are HYPE
  collateral at 62.5% and 77% and BTC at 77%, the tiers finding 3 found
  defended.

Where curators fund different tiers of the same pair, 13 pairs qualify.
The higher tier holds little money on most of them: cbXRP/USDC on Base
carries $3.5M at 62.5% (defensible) and $0.1M at 77% (breached); UBTC/USD₮0
on HyperEVM $0.6M at 77% (defensible) and $0.1M at 86% (breached);
weETH/WETH on Base $0.1M at 91.5% (defensible) and $1.3M at 94.5%
(breached). The exception is wstETH/WETH on Ethereum: $57.3M at 96.5% from
seven curators against $0.6M at 94.5% from four. Both tiers read breached,
and both sit at the resolution limit.

Reading: the industry's 86% for BTC and ETH against USD is a bet on
liquidation within one to six hours. Every large curator makes it. The one
curator whose book the 24h history defends works on HyperEVM at 62.5% and
77%, where the liquidation venues are the thinnest (loop 03). The lower
LLTV is the price of that thin venue, and the history says it is the right
price.

### Finding 5 — The long tail has no verdict

267 of the 515 markets carry no verdict at 24h: 188 have hourly coverage
below 0.9 on at least one leg, 54 have no priced leg at all, 25 are younger
than 90 days. The sparse legs are long-tail tokens lending USDC, WETH or
EURCV: wstHYPE, sUSDe, cbBTC pairs with an exotic loan asset, PT tokens.
The cleaning rules removed samples from 47 of the 515 series, at most 24
samples from one. The metric reaches every market whose two legs an hourly
price feed covers, and no further.

## Conclusion

The metric asks whether a liquidation at the threshold would have covered
its debt through the worst move the collateral has made against the loan
asset. From finding 1: the answer depends on the horizon more than on the
LLTV. At 24 hours the history breaches the 86% tier for every BTC and ETH
market and 87% of the listed borrow; at one hour it defends 94% of it. From
finding 2: the large markets turn between one and six hours. BTC at 86%
holds through six; ETH at 86% needs one. The LST pairs against WETH at
94.5% and 96.5% sit at the resolution limit of hourly two-leg data and
cannot be judged with it. From finding 3: where two tiers coexist, the
history splits them at the pair's own worst drop, and on HyperEVM that line
falls between the 77% and 86% tiers in use. From finding 4: the large
curators' books are 97% to 100% on the 24h-breached side and 0% to 10% on
the 1h-breached side. They fund the standard tiers, and the standard tiers
assume fast liquidation. The one book the 24h history defends is on
HyperEVM at 62.5% and 77%. From finding 5: 267 of 515 markets have no
verdict, because no hourly feed prices their legs.

The practical output is a requirement rather than a number. An LLTV is
defensible if liquidation completes within the horizon at which its
headroom turns negative. For the largest markets that horizon is one to six
hours, and loop 03 measures whether the venues can clear the debt in that
time. Headroom is an upper bound: it subtracts no liquidation cost. The next
run of this loop joins the slippage at the observed capacity and the
oracle's deviation to the buffer, and aligns the two legs to the same
minute so the high-LLTV pairs get a verdict.
