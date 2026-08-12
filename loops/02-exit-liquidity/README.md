# 02 — Exit liquidity

## Question

When a lender wants out of a HyperEVM market, how long does the wait last,
what ends it, and who owns the door?

Scope: every tracked HyperEVM market with utilization history. This is a
census of the whole chain, not a study of pre-selected markets. HEGEMON V1
history is out of scope (no event sink existed).

## Data

MNEMON snapshot pinned in `manifest.json`: `market_state` (utilization,
supply, borrow — 5-minute live sampling, hourly backfill to market creation),
the `markets` dimension, `market_flows` (complete per-account, per-transaction
event history), `prices` (USD reference), and `supplier_positions` (hourly
lender-book snapshots). Views consumed: `v_exit_spells` (gaps-and-islands
episodes of u ≥ 0.99 / 0.999 with 2-hour hole tolerance), `v_market_flows`
(signed loan-side flows in token units), and `v_market_state`.

Four caveats bound what the data can say:

1. Backfill granularity is hourly and the spell view tolerates 2-hour holes,
   so spells shorter than roughly one to two hours are invisible before a
   market's live 5-minute capture begins. Lane 1 output is stratified by data
   regime: a spell is live-era when it starts at or after the market's first
   sub-30-minute sampling gap, backfill-era otherwise.
2. `supplier_positions` exists only from late in the sample; every historical
   lender book is reconstructed from flows. The snapshots serve solely as a
   cross-check of the reconstruction on the overlap period; a material
   discrepancy is reported, not silently absorbed.
3. Open spells are right-censored (observed = False); all survival numbers
   are Kaplan-Meier. Where a market's largest observation is censored, the
   curve flattens and S beyond it is a lower-bound statement — flagged as
   such where reported.
4. `market_flows` is complete event history since 2025-04-25. No tracked
   market on this chain predates that date, so flow-reconstructed books are
   available for every spell; reconstruction before that date would be
   impossible.

## Method

Definitions. Exit is BLOCKED when u ≥ 0.999: a withdrawal of any size reverts
or waits — this matches `v_market_health`'s pinned_util definition. u ≥ 0.99
is the near-blocked sensitivity tier. Below that, stuckness is
size-conditional and is measured as occupancy of low-available-liquidity
states, not as spells. The 0.92 / 0.95 tiers of `v_util_spells` are HEGEMON
operational thresholds and are not used here.

Three lanes, run sequentially. SQL extracts; METRON estimates.

### Lane 1 — Blocked-spell census

`v_exit_spells` over full backfilled history, per market and pooled. The
≥ 0.999 tier is the primary object; the ≥ 0.99 tier is reported as
sensitivity. A spell whose end reaches the market's last sample (within the
2-hour hole tolerance) is open at the snapshot and right-censored:
observed = False, duration = snapshot_ts − spell_start. Open spells are never
dropped or truncated. METRON `spell_stats` and `empirical_survival` (horizons
1h, 6h, 24h, 72h, 168h) run per market and pooled on the ≥ 0.999 tier. Per
market the census reports: n spells, n open, median and p90 resolved
duration, S(24h), S(168h).

Size-conditional occupancy (time-weighted share of time available liquidity
sits below $1k / $10k / $100k) is omitted this run: METRON's
`time_at_utilization` validates its input to utilization in [0, 1] with an
integer-basis-point threshold, and `buffer_breach_freq` requires a reference
series and a basis-point buffer — neither admits a generic series with dollar
thresholds, and the repo rule forbids adapting statistics locally. The lane
is deferred upstream (`TODO(metron): add occupancy_below(series,
thresholds)`) and the spell results stand without it.

### Lane 2 — Resolution anatomy

For every resolved ≥ 0.999 spell, the ending mechanism is classified from
loan-side flows in the terminal window [spell_end − 2h, spell_end] (the
window mirrors the spell view's hole tolerance):

- any Liquidation event in the window → "liquidation" (takes precedence);
- net borrow_flow < 0 and dominant in magnitude → "repay";
- net supply_flow > 0 and dominant → "new_supply";
- both flows material — each side's magnitude > 25% of the larger →
  "mixed".

Magnitudes are loan-token units from `v_market_flows`. Classification is
per-row algebra plus the thresholds above, implemented in notebook pandas,
not in METRON.

IKR filter. A flashloan-funded Supply paired with an offsetting vault-side
Withdraw in the same tx_hash is a Vault V2 in-kind redemption — an exposure
transfer, not an exit or a resolution. Before any gross-flow tally,
same-tx_hash loan-side Supply/Withdraw pairs with amounts equal within 1
basis point are tagged `is_ikr` and excluded from lane 2 classification
inputs. Tagged rows are kept: lane 3 uses them.

IRM-as-exit-pump, for spells classified "repay": `rate_at_target` at spell
start versus spell end (ASOF join on `market_state`) and elapsed time; the
distribution of rate multiples at resolution is reported descriptively
(pandas describe) — anything beyond that is deferred upstream rather than
implemented locally.

### Lane 3 — Door concentration

Two HHI computations per ≥ 0.999 spell (METRON `hhi`):

1. withdrawal amounts by account during the spell window, loan side,
   excluding `is_ikr` rows;
2. the lender book at spell start, reconstructed from cumulative signed
   loan-side supply flows per account up to spell_start, each flow converted
   to shares at event time via ASOF join on `market_state`
   (shares = assets × supply_shares / supply_assets at the nearest state row
   at-or-before the event); HHI on net positive shares. The conversion is
   per-row algebra: SQL/pandas, not METRON.

Exit-class split, all markets: per spell window, withdrawn volume in two
classes — capacity-consuming (non-IKR withdrawals) versus in-kind (`is_ikr`
pairs) — and the per-market in-kind share across all spells.

The optional permutation test of book-HHI against spell duration is cut from
this run (budget); see the loop CLAUDE.md.

## Result

Census. 3,073 blocked spells (u ≥ 0.999) across 64 markets over the full
history; 7 open at the snapshot. The 0.99 sensitivity tier holds 3,520 spells
— the two tiers nearly coincide, so pinning is bimodal: markets sit either
comfortably below 0.99 or effectively at 1.0. Pooled over all spells, the
median resolved block lasts 10 minutes and the p90 12 hours; Kaplan-Meier
S(24h) = 5.2% and S(168h) = 0.7%, with the longest resolved block at 61.8
days. Era stratification confirms the visibility floor rather than a regime
change: backfill-era spells show S(1h) = 43.6% against 7.9% live-era —
hourly sampling cannot see sub-hour spells, so the backfill-era distribution
is right-shifted by construction, and the live-era curve is the truer picture
of short blocks. One market's survival numbers are lower bounds (its largest
observation is censored), flagged in the census table.

Resolution anatomy. Of 3,066 resolved spells: 53% end in new supply, 21% in
repayment, 2% in liquidation, 1% mixed, and 23% show no attributable
loan-side flow in the terminal window (a residual consistent with knife-edge
utilization ticks at the 0.999 boundary; hypothesis recorded in the loop
notes, not resolved here). The live-era mix is starker: 71% new_supply
against 3.5% repay — blocked doors reopen because new money arrives, hardly
ever because borrowers leave. The IRM-as-pump effect is modest at the median
(rate-at-target multiple 1.011 at resolution, p75 1.041) because most spells
resolve within hours, but the tail is real (max multiple 37×): the ratchet
does its work only on the blocks that last.

Door concentration. The withdrawal HHI during blocked spells has median 1.0
and p25 1.0: in at least three quarters of spells with any capacity-consuming
withdrawal, every withdrawn coin left through a single account. The lender
book at spell start is nearly as concentrated (median HHI 0.974, median 9
lenders) — the books are vault-intermediated, and the door belongs to whoever
runs the vault. In-kind redemptions are negligible chain-wide (0.74% of gross
Supply/Withdraw volume) with one exception: AVLT/USDT0, where 87.6% of
spell-window withdrawal volume was in-kind (45.9M transferred against 6.5M
capacity-consuming) — the post-depeg "exit" was overwhelmingly exposure
transfer, not exit.

Reconstruction cross-check. Flow-reconstructed books match the
supplier_positions snapshots within 1% max share difference for five of
eight checked markets and within 10% for two more. The one material
divergence (UBTC/USDT0, 0.67 max share difference) is attribution, not data
loss: `market_flows` credits the transaction caller while positions accrue
to `onBehalf`, which the flows API does not expose — a router that supplied
and withdrew 447M near-net-zero across 17 markets absorbs the book that
belongs to its users. Reconstructed books are therefore caller books,
correct exactly where caller = owner — the vault-dominated norm on this
chain, which is why the other checks pass. Consequently the within-spell
withdrawal HHI is caller-level: the router is material in two markets
(UETH/USDT0 at 73% of spell-window withdrawals, PT-hbUSDT-18DEC2025 at 20%),
where HHI = 1.0 overstates owner-level concentration; elsewhere the single
withdrawing account is a vault and the concentration reading is genuine.

Size-conditional occupancy is omitted pending
`TODO(metron): add occupancy_below(series, thresholds)`.

## Conclusion

On HyperEVM, a blocked exit is a frequent, usually brief event with a thin
but consequential tail: the median block resolves within minutes and only
one in twenty outlasts a day, yet the spells that do persist are the ones
where the IRM ratchet — the protocol's only endogenous pump — needs days to
work, and the longest ran two months. What reopens the door is almost never
the borrowers: in the live-sampled era 71% of resolutions arrive as new
supply against 3.5% as repayment, so exit liquidity on this chain is other
people's entrance, and a lender's true exit option is the market's ability
to keep attracting deposits rather than any behavior of its debtors. The
door itself is singular — in at least three quarters of blocked spells every
withdrawn coin left through one account, and the lender books behind them
are vault-owned near-monopolies — so for a depositor the practical question
is not "can this market be exited" but "does my curator reach the door
first"; the one market where exits happened another way (AVLT, 88% in-kind)
transferred exposure rather than ending it. For HEGEMON the operational
reading is direct: utilization thresholds identify blocks after the fact,
but the risk that matters is standing in a single-door queue — position size
relative to available liquidity, and to the other lender behind the same
door, is the exit-risk variable worth engineering against.
