"""Registry for the eleven qualified CTA factor packages.

Each factor is a stand-alone package under :mod:`china_cta.factors.qualified`;
this module only carries metadata and the bulk builder used by notebooks and
scripts. Ten packages build from the local research inputs; ``reg35_transformer``
additionally needs PyTorch and the frozen weights in
``china_cta/factors/qualified/reg35_transformer/assets``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import pandas as pd

from china_cta.factors.cta_common import FactorDataUnavailable
from china_cta.factors.qualified import BUILDERS


@dataclass(frozen=True)
class FactorSpec:
    name: str
    family: str
    formula: str
    inputs: tuple[str, ...]
    direction: str
    available: bool
    signal_scale: float
    reason: str | None = None
    proxy: bool = False


UNAVAILABLE_REASONS: Final[dict[str, str]] = {
    "our_reg35_transformer": (
        "推理需要 PyTorch 与 assets/reg35_transformer 下的三个 .pt 权重（112,963 字节/个）"
        "以及 manifest.json；本仓库只提交代码，未包含二进制权重。"
    ),
}


FACTOR_SPECS: Final[tuple[FactorSpec, ...]] = (
    FactorSpec(
        "fixed_maturity_carry_90_180d",
        "C_carry_and_roll",
        "annualised (near-far) log carry on linearly interpolated tenors",
        ("contract_snapshots", "universe"),
        "long backwardation / short contango",
        True,
        0.0763984642190698,
    ),
    FactorSpec(
        "historical_skewness_252d",
        "G_volatility_and_reversal",
        "-rolling skewness of daily returns, cross-sectional rank",
        ("continuous_prices", "universe"),
        "long relative negative skewness",
        True,
        0.9999802791509596,
    ),
    FactorSpec(
        "oi_participation_trend_60d",
        "E_positioning",
        "multi-horizon trend vote scaled by OI-growth participation weight",
        ("continuous_prices", "contract_snapshots", "universe"),
        "trend direction, risk scaled",
        True,
        0.615749574733305,
    ),
    FactorSpec(
        "xsmom_252_21",
        "B_cross_sectional_momentum",
        "per-date rank of P_{t-skip} / P_{t-lookback} - 1",
        ("continuous_prices", "universe"),
        "cross-sectional momentum",
        True,
        0.6397851035292096,
    ),
    FactorSpec(
        "our_close_carry_smooth5",
        "C_carry_and_roll",
        "mean5(365 * (near_close/main_close - 1) / calendar expiry gap)",
        ("contract_snapshots", "dominant_map", "universe"),
        "long backwardation / short contango, deadband 0.05",
        True,
        0.05,
    ),
    FactorSpec(
        "our_reg35_transformer",
        "H_learned",
        "3-seed regularised Transformer over 60 causal sessions",
        ("continuous_prices", "contract_snapshots", "dominant_map", "universe"),
        "relative-return rank score",
        False,
        1.0,
        UNAVAILABLE_REASONS["our_reg35_transformer"],
    ),
    FactorSpec(
        "crowded_trend_reversal_60d",
        "H_shipped",
        "neg(corr_60(mean_60(return_60), channel_position_20 * volatility_20))",
        ("continuous_prices", "universe"),
        "fade trend crowded into the top of a high-volatility channel",
        True,
        0.7073720289720415,
    ),
    FactorSpec(
        "volume_burst_vol_reversal_60d",
        "H_shipped",
        "-mean_60(corr_20(delta_20(volume_surprise_20), mean_60(volatility_ratio)))",
        ("continuous_prices", "universe"),
        "fade volume bursts that arrive with expanding volatility",
        True,
        0.3029101622490162,
    ),
    FactorSpec(
        "turnover_surprise_channel_ratio",
        "H_shipped",
        "turnover_surprise_20 / channel_position_20",
        ("continuous_prices", "universe"),
        "turnover surprise relative to channel position",
        True,
        4.414286511620197,
    ),
    FactorSpec(
        "inverse_oi_turnover_surprise_ratio",
        "H_shipped",
        "-(oi_surprise_20 / mean_10(turnover_surprise_20))",
        ("continuous_prices", "universe"),
        "fade OI moves that are not backed by turnover",
        True,
        3.13168742823665,
    ),
    FactorSpec(
        "volume_variability_weighted_reversal",
        "H_shipped",
        "-(return_1 * std_5(std_20(volume_change)))",
        ("continuous_prices", "universe"),
        "reversal weighted by instability of volume changes",
        True,
        0.0007038049575569826,
    ),
)


AVAILABLE_FACTORS: Final[tuple[str, ...]] = tuple(
    spec.name for spec in FACTOR_SPECS if spec.available
)
UNAVAILABLE_FACTORS: Final[tuple[str, ...]] = tuple(
    spec.name for spec in FACTOR_SPECS if not spec.available
)


def spec_table() -> pd.DataFrame:
    """Return the catalog metadata as a small DataFrame."""

    return pd.DataFrame(
        [
            {
                "factor_name": spec.name,
                "family": spec.family,
                "formula": spec.formula,
                "inputs": ",".join(spec.inputs),
                "direction": spec.direction,
                "available": spec.available,
                "signal_scale": spec.signal_scale,
                "proxy": spec.proxy,
                "reason": spec.reason,
            }
            for spec in FACTOR_SPECS
        ]
    )


def build_all(inputs: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Build every available factor and return the unavailable reasons."""

    factors: dict[str, pd.DataFrame] = {}
    for name in AVAILABLE_FACTORS:
        builder = BUILDERS.get(name)
        if builder is None:
            raise RuntimeError(f"no builder registered for available factor {name}")
        factors[name] = builder(inputs)

    missing = sorted(set(AVAILABLE_FACTORS) - set(factors))
    if missing:
        raise RuntimeError(f"available factors were not built: {missing}")
    for name, table in factors.items():
        if table.empty:
            raise RuntimeError(f"factor {name} produced an empty table")
    unavailable = {
        spec.name: spec.reason or "unavailable"
        for spec in FACTOR_SPECS
        if not spec.available
    }
    return factors, unavailable


__all__ = [
    "AVAILABLE_FACTORS",
    "BUILDERS",
    "FACTOR_SPECS",
    "FactorDataUnavailable",
    "FactorSpec",
    "UNAVAILABLE_FACTORS",
    "UNAVAILABLE_REASONS",
    "build_all",
    "spec_table",
]
