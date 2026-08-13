"""Hand-computed fixtures for the Morpho Blue protocol algebra."""

import pytest

from mrsearch.protocol import lif_from_lltv, max_slippage_threshold


def test_lif_uncapped_086() -> None:
    # 0.3 * 0.86 + 0.7 = 0.958 -> LIF = 1 / 0.958
    assert lif_from_lltv(0.86) == pytest.approx(1.0438413361169102, rel=1e-12)


def test_lif_uncapped_0625() -> None:
    # 0.3 * 0.625 + 0.7 = 0.8875 -> LIF = 1 / 0.8875
    assert lif_from_lltv(0.625) == pytest.approx(1.1267605633802817, rel=1e-12)


def test_lif_cap_binds() -> None:
    # 0.3 * 0.50 + 0.7 = 0.85 -> 1 / 0.85 = 1.1764... > 1.15 -> cap binds
    assert lif_from_lltv(0.50) == 1.15


def test_lif_rejects_out_of_domain() -> None:
    for bad in (0.0, 1.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="lltv"):
            lif_from_lltv(bad)


H = 0.005


def test_threshold_086() -> None:
    # closed form (cap not binding): 0.3 * (1 - 0.86) = 0.042 -> x = 0.037
    assert max_slippage_threshold(0.86, H) == pytest.approx(0.037, rel=1e-12)


def test_threshold_0625() -> None:
    # 0.3 * 0.375 = 0.1125 -> x = 0.1075
    assert max_slippage_threshold(0.625, H) == pytest.approx(0.1075, rel=1e-12)


def test_threshold_capped_050() -> None:
    # 1 - 1/1.15 = 0.1304347826... -> x = 0.1254347826...
    assert max_slippage_threshold(0.50, H) == pytest.approx(0.12543478260869565, rel=1e-12)


def test_threshold_098() -> None:
    # 0.3 * 0.02 = 0.006 -> x = 0.001
    assert max_slippage_threshold(0.98, H) == pytest.approx(0.001, rel=1e-12)


def test_threshold_floors_at_zero() -> None:
    # incentive cannot cover the haircut: 0.006 - 0.01 < 0 -> 0.0, not an error
    assert max_slippage_threshold(0.98, 0.01) == 0.0


def test_threshold_rejects_negative_haircut() -> None:
    with pytest.raises(ValueError, match="haircut"):
        max_slippage_threshold(0.86, -0.001)
