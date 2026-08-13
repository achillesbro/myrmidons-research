"""Phase 3a liquidation capacity: compute and write the ``liq_capacity`` output table.

Per ``v_dex_slippage`` cycle and per market: build the pair's slippage
ladder, derive the max tolerable slippage from the market's LLTV
(``mrsearch.protocol``), call ``metron.liquidation_capacity``, add HyperCore
bid depth for collaterals with a Core spot book, and append one row per
(as_of, market, model_version) to the outputs namespace. ``capacity_ratio``
divides the debt-clearing equivalent (``capacity_total / LIF``) by
outstanding borrow.

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

    ``dex``: the cycle's v_dex_slippage rows (token_in, token_out, size_usd,
    slippage, status). ``market_meta``: one row per market (chain_id,
    market_id, collateral_token, loan_token, collateral_symbol, lltv as a
    fraction, borrow_usd, state_ts). ``core_depth``: the freshest eligible
    book per coin (coin, depth_bps, bid_depth_usd, ts).
    """
    from metron import liquidation_capacity

    rows: list[dict] = []
    for m in market_meta.itertuples():
        lltv = float(m.lltv)
        lif = lif_from_lltv(lltv)
        x = max_slippage_threshold(lltv, haircut)

        pair = dex[(dex["token_in"] == m.collateral_token) & (dex["token_out"] == m.loan_token)]
        ladder = pair.dropna(subset=["slippage"]).set_index("size_usd")["slippage"]

        core_coin = CORE_COIN_BY_SYMBOL.get(str(m.collateral_symbol))
        coin_book = (
            core_depth[core_depth["coin"] == core_coin] if core_coin else core_depth.iloc[0:0]
        )
        book_ts = coin_book["ts"].iloc[0] if not coin_book.empty else None

        censored = False
        capacity_core = 0.0
        if x == 0.0:
            status = "zero_threshold"
            capacity_evm = 0.0
        elif pair.empty:
            status = "no_price"  # the pair was never quoted this cycle
            capacity_evm = 0.0
        elif ladder.empty:
            status = "no_route"  # quoted, every rung failed: zero swap capacity
            capacity_evm = 0.0
        else:
            status = "ok"
            capacity_evm, censored = liquidation_capacity(ladder, x)
            if not coin_book.empty:
                capacity_core = core_depth_within(
                    coin_book.set_index("depth_bps")["bid_depth_usd"], x
                )

        capacity_total = capacity_evm + capacity_core
        borrow = None if pd.isna(m.borrow_usd) else float(m.borrow_usd)
        # capacity is SELL-SIDE collateral notional; clearing debt D sells
        # LIF * D of collateral, so the ratio compares debt-clearing
        # equivalent (capacity / LIF) to debt.
        ratio = capacity_total / lif / borrow if borrow else None

        params = {
            "haircut": haircut,
            "size_grid_usd": sorted(float(v) for v in pair["size_usd"]),
            "interpolation": "linear",
            "crossing_rule": "first",
            "venues": ["liquidswap"] + (["hypercore"] if capacity_core > 0.0 else []),
            "core_included": capacity_core > 0.0,
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
                "max_slippage_used": float(x),
                "lif": float(lif),
                "outstanding_borrow_usd": borrow,
                "capacity_ratio": ratio,
                "status": status,
            }
        )
    return rows


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
            "SELECT token_in, token_out, size_usd, slippage, status "
            "FROM v_dex_slippage WHERE ts = ? AND chain_id = ?",
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
