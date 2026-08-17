"""Phase 3a liquidation capacity: compute and write the ``liq_capacity`` output table.

Per ``v_dex_slippage`` cycle and per market: build the pair's slippage
ladder, derive the max tolerable slippage from the market's LLTV
(``mrsearch.protocol``), call ``metron.liquidation_capacity``, add HyperCore
bid depth for collaterals with a Core spot book, and append one row per
(as_of, market, model_version) to the outputs namespace.

Model 1.1 semantics: the threshold passed to METRON subtracts the $1k
reference route's blended swap fee (the measured curve nets that fee out,
which understated liquidator cost); ``capacity_ratio`` divides the
debt-clearing equivalent (``capacity_total / LIF``) by the market's own
borrow (isolated liquidation), and ``capacity_ratio_grouped`` divides by
the summed borrow of every market sharing the collateral (simultaneous
same-collateral stress under pro-rata depth sharing).

V1 assumptions, declared in each row's ``params``: naive additivity of DEX
route capacity and Core book depth; Core mid treated as equivalent to the
oracle mark; linear interpolation between the stored depth tiers.

Run as a module (cron/systemd-friendly, idempotent — cycles already written
under the current model version are skipped):

    uv run python -m mrsearch.liq_capacity --data data --mnemon-repo ~/mnemon
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from mrsearch.mnemon_reader import SnapshotReader
from mrsearch.outputs import LIQ_CAPACITY, OutputStore
from mrsearch.protocol import lif_from_lltv, max_slippage_threshold

HAIRCUT_DEFAULT = 0.005

# Which HyperEVM collateral symbols have a HyperCore spot book OF THE SAME
# ASSET (the `core_assets` dimension holds Core coin names, not EVM
# addresses). kHYPE maps to its own KHYPE/USDC book — thin, which the model
# then measures instead of assuming; it never maps to the HYPE book
# (Kinetiq redemption runs a multi-day queue, not liquidation timescale).
# wstHYPE, beHYPE and PT tokens have no Core book and do not map.
CORE_COIN_BY_SYMBOL = {"WHYPE": "HYPE", "UBTC": "UBTC", "UETH": "UETH", "kHYPE": "KHYPE"}

# A Core book older than this is not used (stale depth would inflate capacity).
CORE_BOOK_MAX_AGE = pd.Timedelta(hours=24)

# Semantic model version, recorded in params next to the code-level
# model_version (metron tag + commit).
MODEL_SEMVER = "1.1"

# Route-hop fee units per venue (verification 2026-08-13, loop 03 CLAUDE.md):
# - V3-style venues report Uniswap pips (fee / 1e6). Confirmed: removing a
#   PrjxV3 fee-3000 leg moved measured slippage ~0.1%, excluding the /1e4
#   reading (30%) outright; tier values (100/500/3000/10000) are canonical.
# - LiquidCore reports basis points (fee / 1e4). Supported: one added LC-5
#   hop cost +0.033% measured vs +0.05% predicted at /1e4 (+0.0005% at /1e6).
#   Also the larger, conservative reading.
# - RamsesV3 and HybraV4 could not be verified from stored routes: the
#   larger (/1e4) interpretation is chosen, per the conservative rule.
FEE_UNIT_DIVISOR = {
    "HyperSwapV3": 1e6,
    "PrjxV3": 1e6,
    "HyperTradeV3": 1e6,
    "HybraV3": 1e6,
    "Turbo": 1e6,
    "UltraSolidV3": 1e6,
    "LiquidCore": 1e4,
    "RamsesV3": 1e4,
    "HybraV4": 1e4,
}
# Venues not in the table get the larger (/1e4) reading.
_UNKNOWN_VENUE_DIVISOR = 1e4
# Several venues report fee 0 (HyperSwapV2, PrjxV2, KittenSwapV4,
# NestExchange). That is a reporting gap, not a free swap: a route-switch
# residual pins NestExchange at ~0.30%, and 0.30% is the canonical V2 fee.
# Assuming 0 would reintroduce the defect this correction removes.
ZERO_REPORTED_FEE_DEFAULT = 0.003


def blended_route_fee(route: dict) -> float | None:
    """Blended swap fee of one stored route (the `route_json` blob).

    Within one hop that splits across pools, each split's fee is weighted by
    its amountIn share of the hop. Across sequential hops, fees compound:
    f = 1 - prod(1 - f_hop). Returns None when the route holds no hops.
    """
    hops = route.get("hopSwaps") or []
    if not hops:
        return None
    keep = 1.0
    for hop in hops:
        weights = [float(s.get("amountIn") or 0.0) for s in hop]
        denom = sum(weights)
        if denom <= 0.0:  # no amounts recorded: weight splits equally
            weights = [1.0] * len(hop)
            denom = float(len(hop))
        f_hop = 0.0
        for swap, w in zip(hop, weights, strict=True):
            raw = swap.get("fee")
            divisor = FEE_UNIT_DIVISOR.get(str(swap.get("routerName")), _UNKNOWN_VENUE_DIVISOR)
            fee = (float(raw) / divisor) if raw else 0.0
            if fee == 0.0:
                fee = ZERO_REPORTED_FEE_DEFAULT
            f_hop += (w / denom) * fee
        keep *= 1.0 - f_hop
    return 1.0 - keep


def capacity_ratios(
    capacity_total: float, lif: float, borrow: float | None, group_borrow: float | None
) -> tuple[float | None, float | None]:
    """(capacity_ratio, capacity_ratio_grouped) in debt-clearing units.

    Both divide capacity / LIF (clearing debt D sells LIF * D of collateral).
    The isolated ratio divides by the market's own borrow: the market
    liquidates alone. The grouped ratio divides by the summed borrow of every
    market sharing the collateral: simultaneous same-collateral stress under
    pro-rata depth sharing — the pro-rata allocation
    capacity * (borrow_i / borrow_group) / borrow_i reduces to this closed
    form. Each is None when its denominator is 0 or unknown.
    """
    clearing = capacity_total / lif
    ratio = clearing / borrow if borrow else None
    grouped = clearing / group_borrow if group_borrow else None
    return ratio, grouped


def core_depth_within(depth_usd_by_bps: pd.Series, x: float) -> float:
    """Cumulative bid-side USD depth within ``x`` (fraction) of mid.

    ``depth_usd_by_bps`` is indexed by depth tier in basis points, values are
    cumulative USD depth at that tier (``v_core_depth`` rows for one book).
    Linear interpolation between tiers; below the first tier the segment
    starts at (0, 0), which understates depth near mid; above the last tier
    depth is clamped at the last observed value (no extrapolation). Both
    choices understate capacity — the same conservatism argument as
    ``metron.liquidation_capacity``.
    """
    if depth_usd_by_bps.empty:
        return 0.0
    if x <= 0.0:
        return 0.0
    s = depth_usd_by_bps.sort_index()
    tiers = s.index.to_numpy(dtype=float)
    depths = s.to_numpy(dtype=float)
    x_bps = x * 10_000.0
    if x_bps <= tiers[0]:
        return float(depths[0] * x_bps / tiers[0])
    for i in range(1, len(tiers)):
        if x_bps <= tiers[i]:
            t = (x_bps - tiers[i - 1]) / (tiers[i] - tiers[i - 1])
            return float(depths[i - 1] + t * (depths[i] - depths[i - 1]))
    return float(depths[-1])


def build_rows(
    as_of: pd.Timestamp,
    dex: pd.DataFrame,
    market_meta: pd.DataFrame,
    core_depth: pd.DataFrame,
    *,
    haircut: float,
    model_version: str,
) -> list[dict]:
    """liq_capacity rows for one cycle. Pure: frames in, row dicts out.

    ``dex``: the cycle's v_dex_slippage rows joined with the raw quotes'
    route blob (token_in, token_out, size_usd, slippage, status,
    route_json). ``market_meta``: one row per market (chain_id, market_id,
    collateral_token, loan_token, collateral_symbol, lltv as a fraction,
    borrow_usd, state_ts). ``core_depth``: the freshest eligible book per
    coin (coin, depth_bps, bid_depth_usd, ts).
    """
    from metron import liquidation_capacity

    # Same-collateral markets share their venues' depth: grouped ratios
    # divide by the summed borrow over the whole collateral group at this
    # cycle. Every tracked market counts in the denominator, whatever its
    # own status — dead-router debt still competes for the shared depth.
    group_borrow_by_coll = market_meta.groupby("collateral_token")["borrow_usd"].sum(min_count=1)

    rows: list[dict] = []
    for m in market_meta.itertuples():
        lltv = float(m.lltv)
        lif = lif_from_lltv(lltv)
        x_pre = max_slippage_threshold(lltv, haircut)

        pair = dex[(dex["token_in"] == m.collateral_token) & (dex["token_out"] == m.loan_token)]
        ladder = pair.dropna(subset=["slippage"]).set_index("size_usd")["slippage"]

        # The measured slippage curve nets out the $1k reference rung's own
        # route fee (and impact, treated as 0 at $1k), so the liquidator's
        # true cost is understated by that fee — subtract it from the
        # threshold instead. The fee comes from the ref rung's stored route;
        # fallback: the smallest successful rung that parses.
        fee_ref = _ref_route_fee(pair)
        x_used = x_pre if fee_ref is None else max(0.0, x_pre - fee_ref)

        core_coin = CORE_COIN_BY_SYMBOL.get(str(m.collateral_symbol))
        coin_book = (
            core_depth[core_depth["coin"] == core_coin] if core_coin else core_depth.iloc[0:0]
        )
        book_ts = coin_book["ts"].iloc[0] if not coin_book.empty else None

        censored = False
        capacity_core = 0.0
        if x_pre == 0.0:
            status = "zero_threshold"  # the incentive cannot cover the haircut
            capacity_evm = 0.0
        elif pair.empty:
            status = "no_price"  # the pair was never quoted this cycle
            capacity_evm = 0.0
        elif ladder.empty:
            status = "no_route"  # quoted, every rung failed: zero swap capacity
            capacity_evm = 0.0
        elif x_used == 0.0:
            status = "fee_exceeds_margin"  # the ref route's fee alone eats the margin
            capacity_evm = 0.0
        else:
            status = "ok"
            capacity_evm, censored = liquidation_capacity(ladder, x_used)
            if not coin_book.empty:
                capacity_core = core_depth_within(
                    coin_book.set_index("depth_bps")["bid_depth_usd"], x_used
                )

        capacity_total = capacity_evm + capacity_core
        borrow = None if pd.isna(m.borrow_usd) else float(m.borrow_usd)
        group_borrow_raw = group_borrow_by_coll.get(m.collateral_token)
        group_borrow = None if pd.isna(group_borrow_raw) else float(group_borrow_raw)
        ratio, ratio_grouped = capacity_ratios(capacity_total, lif, borrow, group_borrow)

        params = {
            "model_semver": MODEL_SEMVER,
            "haircut": haircut,
            "size_grid_usd": sorted(float(v) for v in pair["size_usd"]),
            "interpolation": "linear",
            "crossing_rule": "first",
            "venues": ["liquidswap"] + (["hypercore"] if capacity_core > 0.0 else []),
            "core_included": capacity_core > 0.0,
            "depth_sharing": "pro_rata_by_borrow",
            # Route overlap ACROSS collateral groups (a kHYPE route crossing
            # WHYPE pools mid-path) is not modeled; that belongs to the 3c
            # shock simulator.
            "cross_group_overlap": "not_modeled",
            "fee_adjustment": "none" if fee_ref is None else "ref_route_fee",
        }
        input_window = {
            "dex_as_of": as_of.isoformat(),
            "core_book_as_of": book_ts.isoformat() if book_ts is not None else None,
            "market_state_ts": None if pd.isna(m.state_ts) else m.state_ts.isoformat(),
        }
        rows.append(
            {
                "as_of": as_of,
                "chain_id": int(m.chain_id),
                "market_id": m.market_id,
                "model_version": model_version,
                "params": json.dumps(params, sort_keys=True),
                "input_window": json.dumps(input_window, sort_keys=True),
                "capacity_evm_usd": float(capacity_evm),
                "capacity_core_usd": float(capacity_core),
                "capacity_total_usd": float(capacity_total),
                "capacity_censored": bool(censored),
                "max_slippage_used": float(x_used),
                "x_pre_fee": float(x_pre),
                "fee_ref": fee_ref,
                "lif": float(lif),
                "outstanding_borrow_usd": borrow,
                "collateral_group_borrow_usd": group_borrow,
                "capacity_ratio": ratio,
                "capacity_ratio_grouped": ratio_grouped,
                "status": status,
            }
        )
    return rows


def _ref_route_fee(pair: pd.DataFrame) -> float | None:
    """Blended fee of the pair's $1k reference route.

    Walks successful rungs smallest-first (the $1k rung when it succeeded),
    so a failed or unparseable ref rung falls back to the smallest rung
    whose route parses. None when nothing parses — the caller keeps the
    uncorrected threshold and marks the row (never a silent fee of 0)."""
    if pair.empty or "route_json" not in pair.columns:
        return None
    ok = pair[(pair["status"] == "ok") & pair["route_json"].notna()].sort_values("size_usd")
    for raw in ok["route_json"]:
        try:
            fee = blended_route_fee(json.loads(raw))
        except (ValueError, TypeError):
            continue
        if fee is not None:
            return float(fee)
    return None


_MARKET_META_SQL = """
WITH c AS (SELECT ?::TIMESTAMPTZ AS as_of)
SELECT m.chain_id, m.market_id, m.collateral_token, m.loan_token, m.collateral_symbol,
       m.lltv::DOUBLE / 1e18 AS lltv,
       ms.total_borrow_assets::DOUBLE / POW(10, m.loan_decimals) * p.price_usd AS borrow_usd,
       ms.ts AS state_ts
FROM markets m
CROSS JOIN c
ASOF LEFT JOIN market_state ms
    ON ms.chain_id = m.chain_id AND ms.market_id = m.market_id AND ms.ts <= c.as_of
ASOF LEFT JOIN prices p
    ON p.chain_id = m.chain_id AND p.token_address = m.loan_token AND p.ts <= c.as_of
WHERE m.chain_id = ? AND m.collateral_token IS NOT NULL
"""

_CORE_DEPTH_SQL = """
SELECT coin, depth_bps, bid_depth_usd, ts
FROM v_core_depth
WHERE ts <= ? AND ts > ?
QUALIFY ROW_NUMBER() OVER (PARTITION BY coin, depth_bps ORDER BY ts DESC) = 1
"""


def run(
    reader: SnapshotReader,
    store: OutputStore,
    *,
    haircut: float,
    model_version: str,
) -> str:
    """Process every unprocessed v_dex_slippage cycle; returns a summary line."""
    done = store.processed_cycles(LIQ_CAPACITY, model_version)
    cycles = reader.sql(
        "SELECT DISTINCT chain_id, ts FROM v_dex_slippage ORDER BY ts"
    )
    written = 0
    skipped = 0
    for c in cycles.itertuples():
        as_of = pd.Timestamp(c.ts)
        if as_of in done:
            skipped += 1
            continue
        dex = reader.sql(
            "SELECT d.token_in, d.token_out, d.size_usd, d.slippage, d.status, q.route_json "
            "FROM v_dex_slippage d "
            "LEFT JOIN dex_quotes q USING (ts, chain_id, token_in, token_out, size_usd) "
            "WHERE d.ts = ? AND d.chain_id = ?",
            [as_of, int(c.chain_id)],
        )
        meta = reader.sql(_MARKET_META_SQL, [as_of, int(c.chain_id)])
        core = reader.sql(_CORE_DEPTH_SQL, [as_of, as_of - CORE_BOOK_MAX_AGE])
        rows = build_rows(
            as_of, dex, meta, core, haircut=haircut, model_version=model_version
        )
        written += store.append(LIQ_CAPACITY, rows)
    return (
        f"liq_capacity: {written} rows written, {len(cycles) - skipped} cycles processed, "
        f"{skipped} already present ({model_version})"
    )


def repo_model_version() -> str:
    """``metron-v<tag>+<shortsha>`` — the METRON tag plus this repo's commit."""
    import metron

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return f"metron-v{metron.__version__}+{sha}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mrsearch.liq_capacity", description="compute and append liq_capacity rows"
    )
    parser.add_argument("--data", default=None, help="MNEMON data dir (default: $MNEMON_DATA)")
    parser.add_argument(
        "--mnemon-repo", default=None, help="local MNEMON checkout (default: $MNEMON_REPO)"
    )
    parser.add_argument("--haircut", type=float, default=HAIRCUT_DEFAULT)
    args = parser.parse_args(argv)

    with SnapshotReader(args.data, mnemon_repo=args.mnemon_repo) as reader:
        store = OutputStore(reader.data_dir)
        summary = run(
            reader, store, haircut=args.haircut, model_version=repo_model_version()
        )
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
