# Loop 04 — working notes

Internal notes; the README is the publication-ready document.

- Inputs are PUBLISHED rows: the `lltv_headroom_{1,6,24}h` /
  `worst_drop_{1,6,24}h` family of `outputs/market_metrics`, written
  hourly by myrmidons-api (module
  `orchestrators/market_metrics/lltv_headroom.py`, since v0.4.14 on
  2026-09-07; cleaning rules v0.4.15/v0.4.17). The loop computes nothing
  new — it reads, joins and interprets. The recomputability cell rebuilds
  one market's row from `prices` with METRON `worst_window` and the api's
  `bad_debt_buffer` / `drop_short_excursions`, exactly as loop 03 did for
  liq_capacity.
- Snapshot: rsync of 2026-09-08 (MNEMON a10446e, api v0.4.18, METRON
  v1.4.0). Pins moved from api v0.1.0 / METRON v1.3.0 to v0.4.18 / v1.4.0
  in this loop — the family exists only from v0.4.14.
- Known-bad rows: cycles 2026-09-07 16:00 and 17:00 of the family are
  pre-filter (a WETH $979 one-hour tick in the feed made every WETH-leg
  market read a 74% drop). Same model_version as the good rows; they are
  distinguishable by params (`spike_filter` absent / without `max_run`).
  The loop pins the newest cycle, which is post-filter.
- Why the cross rate: kHYPE/WHYPE, wstETH/WETH and the like are correlated
  pairs; the collateral's USD series inherits the loan asset's volatility.
  The family prices collateral in loan units (both legs, inner-joined per
  hour). A loan-asset depeg-and-rebound (USR 2026-03-22) therefore shows as
  a collateral drop — the debt tripled against the collateral, which is the
  shock the market's oracle would mark.
- Why the bad-debt buffer (1 - LLTV x LIF) and not 1 - LLTV: the latter is
  when liquidation STARTS for a reference position; the former is when a
  liquidation at the threshold stops covering the debt. At 86% LLTV the
  two are 14.0% vs 10.2%; at 96.5% they are 3.5% vs 2.5%.
- Data-quality facts behind the two cleaning rules (declared in every
  row's params): DefiLlama's own chart carries the WETH/msETH 2025-09-02
  ticks, so no source switch removes them; SolvBTC sat at one tenth for
  three hours (Morpho-only); wUSDL at ~1e-16 for months and wbrETH at 0
  in Morpho's self-derived history. Excursions of <= 3 samples that
  fully revert (sides within 0.2 log) are dropped; prices < 1e-6 USD are
  excluded. Persisting moves (USR, deUSD, the 2026-02-05 crash) survive.
- Guards: history < 90 d or hourly coverage < 0.9 -> insufficient_history
  with the measured values in params. On HyperEVM the sparse legs are
  wstHYPE, beHYPE and the USDHL-loan pairs (coverage 0.39-0.75).
- Costs are NOT in the headroom yet (params `costs: none`): slippage at
  the observed capacity (loop 03) and oracle deviation. Joining them is
  the next run of this loop.
- Resolution limit: LST/WETH pairs at 94.5-96.5% have buffers of 2.5-3.9%
  while the two legs are sampled at different minutes within the hour
  during the live period; a fast market alone yields a few percent of
  apparent cross move. At 24h those pairs sit at the resolution limit of
  the data; same-minute alignment of the legs is the refinement.
- Curator benchmark mechanics: Morpho Blue markets are permissionless, so
  a curator does not SET an LLTV — it chooses which LLTV market to fund.
  `vault_allocations` (latest snapshot per vault, supply > 0) joined to
  `vaults.name` gives each vault's funded markets; the vault name carries
  the curator (Gauntlet, Steakhouse, Block Analitica, MEV Capital, ...).
  The benchmark is therefore: the share of each curator's supplied USD that
  sits in markets whose history has breached the bad-debt buffer, per
  horizon, and where curators disagree on the same collateral.
- Re-running the notebook needs MNEMON_REPO set and the snapshot rsynced;
  outputs/ arrives with the same rsync (canonical rows are VPS-written).
- First cross-section: cycle 2026-09-08 08:00 UTC (17 family cycles
  existed). Two notebook bugs caught on the first run: `pivot_table` drops
  a market whose values are all null (the insufficient_history rows
  vanished — 276 markets instead of 657), and `10 ** loan_decimals` on an
  int32 column overflows (negative supply totals). Both fixed; the wide
  frame is built from the status pivot.
- Recomputation race: the writer runs at :05, before the hourly tick's
  prices job has written that hour's sample, so a snapshot taken later
  holds one more hourly sample than `input_window.n_samples`. The rebuild
  uses `ts < end` (strict) and matches exactly.
- Unlisted markets: PAXG/USDC on Ethereum (unlisted) reports 7.2B USDC
  borrow == supply, a synthetic position that dominates any weighted
  figure; RLP/USDC ($50M) and AZND/USDC are unlisted too. The README's
  weighted numbers use listed markets; the notebook prints both.
- Curator label collisions from the first-word rule: "Vault" = Vault
  Bridge, "Yield" = Yield Clearstar (Clearstar), "Smokehouse" = Steakhouse's
  higher-risk line, "MEV" = MEV Capital, "Index" = Index Coop. Named in the
  README where it matters.
- The "sparse legs" count in the notebook lists loan symbols too (USDC 73):
  USDC is the loan leg of most sparse-collateral markets, not itself
  sparse. The coverage in params is the cross rate's; per-leg coverage is
  not stored.
- Owner questions left open by this run: which horizon headlines (1h vs
  24h); whether to lower `min_coverage` for HyperEVM's DefiLlama-sparse
  legs (wstHYPE 0.64, beHYPE 0.39); MODEL_API_TAG stays 0.4.1 (decided
  2026-09-08: no history recompute).
