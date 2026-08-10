# Loop 02 — working notes

Observations, anomalies, and threshold judgment calls, newest last.

## Scaffold decisions (2026-08-10)

- Snapshot re-synced 2026-08-10 at MNEMON b50c56c — the commit that ships
  `v_exit_spells`. Reader imports views from $MNEMON_REPO (also at b50c56c).
- Occupancy verdict (read from METRON src, not docs): `time_at_utilization`
  hard-validates values to [0, 1] and takes threshold_bps in [0, 10000];
  `buffer_breach_freq` requires (series, reference, buffer_bps). Neither
  admits a generic (series, dollar thresholds) contract → per repo rule the
  occupancy block is deferred: `TODO(metron): add occupancy_below(series,
  thresholds)`. Spell lanes reported without it.
- Open-spell rule mirrors MNEMON's own export (`jobs/export.py`):
  open ⇔ end_ts >= market's max(ts) − 2h. Censored duration per spec:
  snapshot_ts − spell_start, snapshot_ts = global max market_state ts.
- Live-era boundary per market = first ts whose gap to the next sample is
  < 30 min (backfill is hourly; live is 5-min). Spells stratify on
  spell_start >= that boundary.
- Optional permutation test (book-HHI vs duration) cut from this run per the
  spec's "cut first" instruction.
- Loop 01's README deferred "HEGEMON V1 stuck periods" to this loop; the
  owner descoped V1 history here (no event sink existed then). Not lost —
  just not answerable from this archive.

## Terminal-window correction (2026-08-10, before the run)

The spec's lane-2 window [end−2h, end] misses the resolving event by
construction: end_ts is the last ABOVE-threshold sample, so the flow that
pushed u below 0.999 lands in (end_ts, next_sample]. Measured: with the
literal window 81% of resolved spells classify "none"; the gap from end to
the next state sample is 1h for every resolved spell, and 400/400 sampled
spells have flows in [end−2h, next_sample]. Window used:
[end−2h, min(next_state_ts, end+2h)] — stated in README Method as a
deviation from the drafted window, same 2h-tolerance spirit.

## Other judgment calls (2026-08-10)

- duration_min is the span between the first and last above-threshold
  SAMPLES: a single-sample spell has duration 0 — read as "resolved within
  one sampling interval", not literally instantaneous.
- Open-flag formula vs censoring: 0 markets have an open spell whose last
  sample lags the snapshot by >2h, so the spec's censored duration
  (snapshot_ts − start) coincides with censoring at last observation.
- Book reconstruction includes is_ikr rows (they transfer ownership — real
  book changes); only lane 2 classification and the withdrawal-HHI exclude
  them. Bad-debt socialization ($185 chain-wide) ignored in book shares.
- Accounts with net reconstructed shares <= 0 (rounding dust) are dropped
  before HHI.
- Book "at spell start" = flows with ts <= start_ts.

## Run surprises (2026-08-10)

- tz-handling cost three execution attempts: np.minimum strips tz from
  datetime Series (use .clip), and .to_numpy() on tz-aware Series yields
  OBJECT arrays of Timestamps — searchsorted against naive datetime64 then
  raises. Everything funnels through a ts64() helper now.
- The 0.99 and 0.999 tiers nearly coincide (3,520 vs 3,073 spells): pinning
  is bimodal; there is almost no "between 0.99 and 0.999" regime.
- Era mechanism flip: backfill-era resolutions are 48% new_supply / 26%
  repay; live-era 71% / 3.5%. Part composition shift (full-scan added small
  markets), part visibility floor.
- 23% of resolved spells show NO loan-side flow in [end-2h, next_sample].
  Hypothesis: knife-edge utilization ticks — the API's utilization field can
  cross 0.999 downward on accrual-timing rounding without an event. Many
  "none" spells are 0-duration single-sample blips. Unresolved; would need
  raw-assets recomputation of u to settle.
- Withdrawal HHI median AND p25 = 1.0 — the door is literally one account in
  most blocked spells. Books median 9 lenders but HHI 0.974: V1 vaults ARE
  the lenders.
- AVLT in-kind share 87.6% of spell-window withdrawals (45.9M vs 6.5M
  capacity) — loop 01's "matched supply/withdraw rotations" formalized: the
  post-depeg exit was exposure transfer via same-tx pairs, not exits.
- Cross-check outlier: 0xa24d04c3 (UBTC/USDT0) reconstruction vs snapshot
  max share diff 0.67 — MATERIAL, unexplained. Other 7 markets <= 10%, five
  <= 1%. Candidate causes: onBehalf attribution in flows vs position owner,
  or share transfers invisible to loan-side flows. Needs its own look before
  trusting per-account books on that market.
- IRM pump median multiple 1.011 — the ratchet barely moves for typical
  (short) spells; max 37x on the long tail. The "pump" narrative only
  applies to blocks that already lasted days.
