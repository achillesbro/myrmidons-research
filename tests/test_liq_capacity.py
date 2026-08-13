"""Orchestration smoke test on hand-built toy frames, plus the append-only
writer contract. Market A reuses METRON fixture F1 verbatim (capacity
325_000 is hand-verified there); market B is the censored case with a Core
book add-on."""

import json

import pandas as pd
import pytest

from mrsearch.liq_capacity import build_rows, core_depth_within
from mrsearch.outputs import LIQ_CAPACITY, OutputStore

AS_OF = pd.Timestamp("2026-08-13 14:00:00", tz="UTC")
STATE_TS = pd.Timestamp("2026-08-13 13:55:00", tz="UTC")
BOOK_TS = pd.Timestamp("2026-08-13 14:00:00", tz="UTC")

# x = 0.3 * (1 - lltv) - 0.005 = 0.02 exactly when lltv = 11/12.
LLTV = 11 / 12
LOAN = "0xloan"
SIZES = [1_000.0, 10_000.0, 100_000.0, 1_000_000.0]
VERSION = "metron-v1.3.0+testsha"


def _dex_rows(token_in: str, slips: list[float | None]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "token_in": token_in,
            "token_out": LOAN,
            "size_usd": SIZES,
            "slippage": slips,
            "status": ["ok" if s is not None else "no_route" for s in slips],
        }
    )


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
            _dex_rows("0xaaa", [0.001, 0.004, 0.010, 0.050]),  # METRON F1 ladder
            _dex_rows("0xwhype", [0.001, 0.002, 0.003, 0.004]),  # METRON F2 ladder
        ],
        ignore_index=True,
    )
    meta = pd.DataFrame(
        [
            _meta("0xm_a", "0xaaa", "AAA", 1_000_000.0),
            _meta("0xm_b", "0xwhype", "WHYPE", 2_000_000.0),
        ]
    )
    return build_rows(AS_OF, dex, meta, CORE, haircut=0.005, model_version=VERSION)


def test_interior_crossing_market(rows: list[dict]) -> None:
    a = next(r for r in rows if r["market_id"] == "0xm_a")
    # F1: crossing at 0.02 -> 325_000; no Core book for AAA.
    assert a["status"] == "ok"
    assert a["max_slippage_used"] == pytest.approx(0.02, rel=1e-9)
    assert a["capacity_evm_usd"] == pytest.approx(325_000.0, rel=1e-9)
    assert a["capacity_core_usd"] == 0.0
    assert a["capacity_total_usd"] == pytest.approx(325_000.0, rel=1e-9)
    assert a["capacity_censored"] is False
    assert a["lif"] == pytest.approx(1.0 / (0.3 * LLTV + 0.7), rel=1e-12)
    assert a["outstanding_borrow_usd"] == 1_000_000.0
    # ratio divides the debt-clearing equivalent by debt: capacity / LIF /
    # borrow = 325_000 * 0.975 / 1_000_000 (LIF = 1/0.975 at lltv 11/12).
    assert a["capacity_ratio"] == pytest.approx(0.316875, rel=1e-9)


def test_censored_market_with_core_addon(rows: list[dict]) -> None:
    b = next(r for r in rows if r["market_id"] == "0xm_b")
    # F2: whole ladder below 0.02 -> capacity = 1_000_000, censored.
    # Core: x = 0.02 -> 200 bps tier -> 300_000. Total 1_300_000.
    assert b["status"] == "ok"
    assert b["capacity_evm_usd"] == 1_000_000.0
    assert b["capacity_core_usd"] == pytest.approx(300_000.0, rel=1e-9)
    assert b["capacity_total_usd"] == pytest.approx(1_300_000.0, rel=1e-9)
    assert b["capacity_censored"] is True
    # 1_300_000 * 0.975 / 2_000_000
    assert b["capacity_ratio"] == pytest.approx(0.63375, rel=1e-9)


def test_rows_match_output_contract(rows: list[dict]) -> None:
    contract = {f.name for f in LIQ_CAPACITY.schema}
    for row in rows:
        assert set(row) == contract
        params = json.loads(row["params"])
        assert params["haircut"] == 0.005
        assert params["size_grid_usd"] == SIZES
        assert params["interpolation"] == "linear"
        assert params["crossing_rule"] == "first"
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
    assert store.append(LIQ_CAPACITY, rows) == 2
    # re-append: existing keys win, nothing added
    mutated = [dict(r, capacity_evm_usd=999.0) for r in rows]
    assert store.append(LIQ_CAPACITY, mutated) == 0
    df = store.read(LIQ_CAPACITY)
    assert len(df) == 2
    assert not (df["capacity_evm_usd"] == 999.0).any()
    # a new model_version appends alongside, never replaces
    assert store.append(LIQ_CAPACITY, [dict(r, model_version="metron-v9+x") for r in rows]) == 2
    assert len(store.read(LIQ_CAPACITY)) == 4
    # everything lives under outputs/, day-partitioned on as_of
    assert (tmp_path / "outputs" / "liq_capacity" / "date=2026-08-13" / "part-0.parquet").exists()
    assert store.processed_cycles(LIQ_CAPACITY, VERSION) == {AS_OF}


def test_output_store_rejects_incomplete_rows(tmp_path) -> None:
    with pytest.raises(ValueError, match="lack columns"):
        OutputStore(tmp_path).append(LIQ_CAPACITY, [{"as_of": AS_OF}])
