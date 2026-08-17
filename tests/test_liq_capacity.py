"""Orchestration smoke test on hand-built toy frames, plus the append-only
writer contract. Market A reuses METRON fixture F1 verbatim (capacity
325_000 is hand-verified there); market B is the censored case with a Core
book add-on and a fee-corrected threshold; A2 shares A's collateral so the
grouped ratio differs from the isolated one."""

import json

import pandas as pd
import pytest

from mrsearch.liq_capacity import (
    blended_route_fee,
    build_rows,
    capacity_ratios,
    core_depth_within,
)
from mrsearch.outputs import LIQ_CAPACITY, OutputStore

AS_OF = pd.Timestamp("2026-08-13 14:00:00", tz="UTC")
STATE_TS = pd.Timestamp("2026-08-13 13:55:00", tz="UTC")
BOOK_TS = pd.Timestamp("2026-08-13 14:00:00", tz="UTC")

# x = 0.3 * (1 - lltv) - 0.005 = 0.02 exactly when lltv = 11/12.
LLTV = 11 / 12
LOAN = "0xloan"
SIZES = [1_000.0, 10_000.0, 100_000.0, 1_000_000.0]
VERSION = "metron-v1.3.0+testsha"


def _dex_rows(
    token_in: str, slips: list[float | None], ref_route: dict | None = None
) -> pd.DataFrame:
    # ref_route: the $1k rung's stored route blob (None = unrecovered fee).
    return pd.DataFrame(
        {
            "token_in": token_in,
            "token_out": LOAN,
            "size_usd": SIZES,
            "slippage": slips,
            "status": ["ok" if s is not None else "no_route" for s in slips],
            "route_json": [json.dumps(ref_route) if ref_route and s == SIZES[0] else None
                           for s in SIZES],
        }
    )


# PrjxV3 reports Uniswap pips: fee 3000 -> 0.003.
REF_ROUTE_3000 = {"hopSwaps": [[{"routerName": "PrjxV3", "fee": 3000, "amountIn": "100"}]]}


def _meta(market_id: str, collateral: str, symbol: str, borrow_usd: float | None) -> dict:
    return {
        "chain_id": 999,
        "market_id": market_id,
        "collateral_token": collateral,
        "loan_token": LOAN,
        "collateral_symbol": symbol,
        "lltv": LLTV,
        "borrow_usd": borrow_usd,
        "state_ts": STATE_TS,
    }


CORE = pd.DataFrame(
    {
        "coin": "HYPE",
        "depth_bps": [25, 50, 100, 200, 400],
        "bid_depth_usd": [100_000.0, 150_000.0, 200_000.0, 300_000.0, 500_000.0],
        "ts": BOOK_TS,
    }
)


@pytest.fixture
def rows() -> list[dict]:
    dex = pd.concat(
        [
            _dex_rows("0xaaa", [0.001, 0.004, 0.010, 0.050]),  # METRON F1 ladder, no route
            _dex_rows("0xwhype", [0.001, 0.002, 0.003, 0.004], REF_ROUTE_3000),  # F2 ladder
        ],
        ignore_index=True,
    )
    meta = pd.DataFrame(
        [
            _meta("0xm_a", "0xaaa", "AAA", 1_000_000.0),
            _meta("0xm_a2", "0xaaa", "AAA", 3_000_000.0),  # same collateral: shared depth
            _meta("0xm_b", "0xwhype", "WHYPE", 2_000_000.0),
        ]
    )
    return build_rows(AS_OF, dex, meta, CORE, haircut=0.005, model_version=VERSION)


def test_interior_crossing_market(rows: list[dict]) -> None:
    a = next(r for r in rows if r["market_id"] == "0xm_a")
    # F1: crossing at 0.02 -> 325_000; no Core book for AAA. The pair's ref
    # route is unrecovered, so the threshold stays uncorrected.
    assert a["status"] == "ok"
    assert a["max_slippage_used"] == pytest.approx(0.02, rel=1e-9)
    assert a["x_pre_fee"] == pytest.approx(0.02, rel=1e-9)
    assert a["fee_ref"] is None
    assert json.loads(a["params"])["fee_adjustment"] == "none"
    assert a["capacity_evm_usd"] == pytest.approx(325_000.0, rel=1e-9)
    assert a["capacity_core_usd"] == 0.0
    assert a["capacity_total_usd"] == pytest.approx(325_000.0, rel=1e-9)
    assert a["capacity_censored"] is False
    assert a["lif"] == pytest.approx(1.0 / (0.3 * LLTV + 0.7), rel=1e-12)
    assert a["outstanding_borrow_usd"] == 1_000_000.0
    # isolated ratio: capacity / LIF / own borrow = 325_000 * 0.975 / 1e6
    # (LIF = 1/0.975 at lltv 11/12).
    assert a["capacity_ratio"] == pytest.approx(0.316875, rel=1e-9)
    # grouped: same collateral as 0xm_a2, group borrow 4M ->
    # 325_000 * 0.975 / 4_000_000.
    assert a["collateral_group_borrow_usd"] == 4_000_000.0
    assert a["capacity_ratio_grouped"] == pytest.approx(0.07921875, rel=1e-9)


def test_same_collateral_markets_share_the_group_denominator(rows: list[dict]) -> None:
    a = next(r for r in rows if r["market_id"] == "0xm_a")
    a2 = next(r for r in rows if r["market_id"] == "0xm_a2")
    # Same pair -> same capacity and LIF -> identical grouped ratio; the
    # isolated ratios differ with own borrow.
    assert a2["collateral_group_borrow_usd"] == 4_000_000.0
    assert a2["capacity_ratio"] == pytest.approx(0.316875 / 3, rel=1e-9)
    assert a2["capacity_ratio_grouped"] == pytest.approx(a["capacity_ratio_grouped"], rel=1e-12)


def test_censored_market_with_core_addon(rows: list[dict]) -> None:
    b = next(r for r in rows if r["market_id"] == "0xm_b")
    # Ref route fee 0.003 corrects the threshold: x_used = 0.02 - 0.003.
    # F2: whole ladder below 0.017 -> capacity = 1_000_000, censored.
    # Core at 170 bps, between the 100 and 200 tiers:
    # 200_000 + 0.7 * 100_000 = 270_000. Total 1_270_000.
    assert b["status"] == "ok"
    assert b["fee_ref"] == pytest.approx(0.003, rel=1e-12)
    assert b["x_pre_fee"] == pytest.approx(0.02, rel=1e-9)
    assert b["max_slippage_used"] == pytest.approx(0.017, rel=1e-9)
    assert json.loads(b["params"])["fee_adjustment"] == "ref_route_fee"
    assert b["capacity_evm_usd"] == 1_000_000.0
    assert b["capacity_core_usd"] == pytest.approx(270_000.0, rel=1e-9)
    assert b["capacity_total_usd"] == pytest.approx(1_270_000.0, rel=1e-9)
    assert b["capacity_censored"] is True
    # isolated: 1_270_000 * 0.975 / 2_000_000; alone in its collateral
    # group, so the grouped ratio equals the isolated one.
    assert b["capacity_ratio"] == pytest.approx(0.619125, rel=1e-9)
    assert b["collateral_group_borrow_usd"] == 2_000_000.0
    assert b["capacity_ratio_grouped"] == pytest.approx(b["capacity_ratio"], rel=1e-12)


def test_rows_match_output_contract(rows: list[dict]) -> None:
    contract = {f.name for f in LIQ_CAPACITY.schema}
    for row in rows:
        assert set(row) == contract
        params = json.loads(row["params"])
        assert params["model_semver"] == "1.1"
        assert params["haircut"] == 0.005
        assert params["size_grid_usd"] == SIZES
        assert params["interpolation"] == "linear"
        assert params["crossing_rule"] == "first"
        assert params["depth_sharing"] == "pro_rata_by_borrow"
        assert params["cross_group_overlap"] == "not_modeled"
        window = json.loads(row["input_window"])
        assert window["dex_as_of"] == AS_OF.isoformat()
        assert window["market_state_ts"] == STATE_TS.isoformat()
    a = next(r for r in rows if r["market_id"] == "0xm_a")
    b = next(r for r in rows if r["market_id"] == "0xm_b")
    assert json.loads(a["params"])["venues"] == ["liquidswap"]
    assert json.loads(a["params"])["core_included"] is False
    assert json.loads(b["params"])["venues"] == ["liquidswap", "hypercore"]
    assert json.loads(b["input_window"])["core_book_as_of"] == BOOK_TS.isoformat()


def test_no_price_and_no_route_statuses() -> None:
    dex = _dex_rows("0xrouted_but_dead", [None, None, None, None])
    meta = pd.DataFrame(
        [
            _meta("0xm_c", "0xnever_quoted", "CCC", 500_000.0),
            _meta("0xm_d", "0xrouted_but_dead", "DDD", None),
        ]
    )
    rows = build_rows(AS_OF, dex, meta, CORE.iloc[0:0], haircut=0.005, model_version=VERSION)
    c = next(r for r in rows if r["market_id"] == "0xm_c")
    d = next(r for r in rows if r["market_id"] == "0xm_d")
    assert c["status"] == "no_price" and c["capacity_total_usd"] == 0.0
    assert c["capacity_ratio"] == 0.0  # borrow 500k, capacity 0
    assert d["status"] == "no_route" and d["capacity_total_usd"] == 0.0
    assert d["outstanding_borrow_usd"] is None and d["capacity_ratio"] is None


def test_zero_threshold_status() -> None:
    dex = _dex_rows("0xaaa", [0.001, 0.004, 0.010, 0.050])
    meta = pd.DataFrame([_meta("0xm_e", "0xaaa", "AAA", 1_000.0)])
    meta["lltv"] = 0.98  # 0.3 * 0.02 = 0.006 < haircut 0.01 -> zero threshold
    rows = build_rows(AS_OF, dex, meta, CORE.iloc[0:0], haircut=0.01, model_version=VERSION)
    assert rows[0]["status"] == "zero_threshold"
    assert rows[0]["max_slippage_used"] == 0.0
    assert rows[0]["capacity_total_usd"] == 0.0


def test_fee_exceeds_margin_status() -> None:
    # lltv 0.98, h 0.005 -> x_pre = 0.001; ref fee 0.003 eats the whole
    # margin -> x_used = 0.0 with the fee-specific status, distinct from
    # zero_threshold (whose cause is the haircut alone).
    dex = _dex_rows("0xaaa", [0.001, 0.004, 0.010, 0.050], REF_ROUTE_3000)
    meta = pd.DataFrame([_meta("0xm_f", "0xaaa", "AAA", 1_000.0)])
    meta["lltv"] = 0.98
    rows = build_rows(AS_OF, dex, meta, CORE.iloc[0:0], haircut=0.005, model_version=VERSION)
    f = rows[0]
    assert f["status"] == "fee_exceeds_margin"
    assert f["x_pre_fee"] == pytest.approx(0.001, rel=1e-9)
    assert f["fee_ref"] == pytest.approx(0.003, rel=1e-12)
    assert f["max_slippage_used"] == 0.0
    assert f["capacity_total_usd"] == 0.0


def test_threshold_fee_fixtures() -> None:
    # lltv 0.86, h 0.005, f_ref 0.003 -> x_pre = 0.037, x_used = 0.034.
    dex = _dex_rows("0xaaa", [0.001, 0.004, 0.010, 0.050], REF_ROUTE_3000)
    meta = pd.DataFrame([_meta("0xm_t", "0xaaa", "AAA", 1_000.0)])
    meta["lltv"] = 0.86
    row = build_rows(AS_OF, dex, meta, CORE.iloc[0:0], haircut=0.005, model_version=VERSION)[0]
    assert row["x_pre_fee"] == pytest.approx(0.037, rel=1e-9)
    assert row["max_slippage_used"] == pytest.approx(0.034, rel=1e-9)


def test_blended_route_fee_fixtures() -> None:
    def v3(fee: int, amount: str = "100") -> dict:
        return {"routerName": "HyperSwapV3", "fee": fee, "amountIn": amount}

    # single hop, fee 500 -> 0.0005
    assert blended_route_fee({"hopSwaps": [[v3(500)]]}) == pytest.approx(0.0005, rel=1e-12)
    # two sequential hops, 500 then 3000 -> 1 - 0.9995 * 0.997 = 0.0034985
    assert blended_route_fee({"hopSwaps": [[v3(500)], [v3(3000)]]}) == pytest.approx(
        0.0034985, rel=1e-12
    )
    # one hop split 60/40 by amountIn across fees 500 and 10000 -> 0.0043
    split = [[v3(500, "60"), v3(10000, "40")]]
    assert blended_route_fee({"hopSwaps": split}) == pytest.approx(0.0043, rel=1e-12)
    # that split hop followed by a single hop, fee 3000 ->
    # 1 - 0.9957 * 0.997 = 0.0072871
    assert blended_route_fee({"hopSwaps": [*split, [v3(3000)]]}) == pytest.approx(
        0.0072871, rel=1e-12
    )
    # no hops -> None (caller falls back / marks fee_adjustment none)
    assert blended_route_fee({"hopSwaps": []}) is None


def test_blended_route_fee_venue_units() -> None:
    # LiquidCore reports basis points: fee 5 -> 0.0005.
    lc = {"hopSwaps": [[{"routerName": "LiquidCore", "fee": 5, "amountIn": "1"}]]}
    assert blended_route_fee(lc) == pytest.approx(0.0005, rel=1e-12)
    # A reported fee of 0 is a reporting gap, not a free swap: 0.30% default.
    nest = {"hopSwaps": [[{"routerName": "NestExchange", "fee": 0, "amountIn": "1"}]]}
    assert blended_route_fee(nest) == pytest.approx(0.003, rel=1e-12)
    # Unknown venues get the larger (/1e4) reading.
    other = {"hopSwaps": [[{"routerName": "MysteryDEX", "fee": 10, "amountIn": "1"}]]}
    assert blended_route_fee(other) == pytest.approx(0.001, rel=1e-12)


def test_capacity_ratios_fixtures() -> None:
    # capacity 100_000, LIF 1.05, own borrow 500_000, group 2_000_000.
    ratio, grouped = capacity_ratios(100_000.0, 1.05, 500_000.0, 2_000_000.0)
    assert ratio == pytest.approx(0.19047619047619047, rel=1e-12)
    assert grouped == pytest.approx(0.047619047619047616, rel=1e-12)
    # a market alone in its group: the two ratios are equal
    ratio, grouped = capacity_ratios(100_000.0, 1.05, 500_000.0, 500_000.0)
    assert ratio == grouped
    # unknown denominators stay NULL
    assert capacity_ratios(100_000.0, 1.05, None, None) == (None, None)


def test_core_depth_within_interpolation() -> None:
    tiers = CORE.set_index("depth_bps")["bid_depth_usd"]
    # below the first tier: segment from (0, 0) -> 100_000 * 12.5 / 25 = 50_000
    assert core_depth_within(tiers, 0.00125) == pytest.approx(50_000.0, rel=1e-12)
    # between tiers: 100 -> 200 bps at 150 bps = 200_000 + 0.5 * 100_000
    assert core_depth_within(tiers, 0.015) == pytest.approx(250_000.0, rel=1e-12)
    # at a knot
    assert core_depth_within(tiers, 0.005) == pytest.approx(150_000.0, rel=1e-12)
    # beyond the last tier: clamped, no extrapolation
    assert core_depth_within(tiers, 0.10) == 500_000.0
    # degenerate inputs
    assert core_depth_within(tiers.iloc[0:0], 0.02) == 0.0
    assert core_depth_within(tiers, 0.0) == 0.0


def test_output_store_is_append_only(tmp_path, rows: list[dict]) -> None:
    store = OutputStore(tmp_path)
    assert store.append(LIQ_CAPACITY, rows) == 3
    # re-append: existing keys win, nothing added
    mutated = [dict(r, capacity_evm_usd=999.0) for r in rows]
    assert store.append(LIQ_CAPACITY, mutated) == 0
    df = store.read(LIQ_CAPACITY)
    assert len(df) == 3
    assert not (df["capacity_evm_usd"] == 999.0).any()
    # a new model_version appends alongside, never replaces
    assert store.append(LIQ_CAPACITY, [dict(r, model_version="metron-v9+x") for r in rows]) == 3
    assert len(store.read(LIQ_CAPACITY)) == 6
    # everything lives under outputs/, day-partitioned on as_of
    assert (tmp_path / "outputs" / "liq_capacity" / "date=2026-08-13" / "part-0.parquet").exists()
    assert store.processed_cycles(LIQ_CAPACITY, VERSION) == {AS_OF}


def test_output_store_reads_mixed_schema_files(tmp_path, rows: list[dict]) -> None:
    # A day file written before columns were added must read as typed NULLs
    # for those columns, alongside a newer full-schema file.
    import pyarrow as pa
    import pyarrow.parquet as pq

    store = OutputStore(tmp_path)
    v11_cols = {"x_pre_fee", "fee_ref", "collateral_group_borrow_usd", "capacity_ratio_grouped"}
    old_schema = pa.schema([f for f in LIQ_CAPACITY.schema if f.name not in v11_cols])
    old_row = {
        k: v for k, v in dict(rows[0], as_of=AS_OF - pd.Timedelta(days=30)).items()
        if k not in v11_cols
    }
    old_dir = tmp_path / "outputs" / "liq_capacity" / "date=2026-07-14"
    old_dir.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([old_row], schema=old_schema), old_dir / "part-0.parquet"
    )
    store.append(LIQ_CAPACITY, rows)  # new full-schema day file

    df = store.read(LIQ_CAPACITY)
    assert len(df) == 4
    old = df[df.as_of == AS_OF - pd.Timedelta(days=30)].iloc[0]
    assert pd.isna(old["capacity_ratio_grouped"]) and pd.isna(old["fee_ref"])
    assert old["capacity_ratio"] == rows[0]["capacity_ratio"]  # old columns intact


def test_output_store_rejects_incomplete_rows(tmp_path) -> None:
    with pytest.raises(ValueError, match="lack columns"):
        OutputStore(tmp_path).append(LIQ_CAPACITY, [{"as_of": AS_OF}])
