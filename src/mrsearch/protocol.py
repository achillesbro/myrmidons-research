"""Morpho Blue protocol algebra.

Deliberately local to this repo: METRON stays protocol-agnostic, and these
constants come from the Morpho Blue contract, not from statistics.
"""

from __future__ import annotations

# Morpho Blue liquidation incentive factor constants (contract values).
LIF_CAP = 1.15
LIF_CURSOR = 0.3


def lif_from_lltv(lltv: float) -> float:
    """Morpho Blue liquidation incentive factor: min(1.15, 1 / (0.3 * lltv + 0.7)).

    lltv is the market's liquidation LTV as a fraction in (0, 1).
    """
    if not 0.0 < lltv < 1.0:
        raise ValueError("lltv must lie strictly inside (0, 1)")
    return min(LIF_CAP, 1.0 / (LIF_CURSOR * lltv + (1.0 - LIF_CURSOR)))


def max_slippage_threshold(lltv: float, haircut: float) -> float:
    """Max tolerable liquidation slippage: x = (1 - 1/LIF) - haircut.

    1 - 1/LIF is the liquidator's gross margin as a fraction of seized
    collateral value. When the 1.15 cap does not bind, the closed form is
    0.3 * (1 - lltv). The haircut absorbs gas, latency and inventory risk.

    Returns 0.0 when x <= 0: a market whose liquidation incentive cannot
    cover the haircut has zero modeled capacity. That row is a finding,
    not a bug, so this is not an error path.
    """
    if not haircut >= 0.0:
        raise ValueError("haircut must be >= 0")
    x = (1.0 - 1.0 / lif_from_lltv(lltv)) - haircut
    return max(0.0, x)
