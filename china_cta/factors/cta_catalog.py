"""Registry for the 22-factor CTA alpha catalog.

Every available factor is built on the project's five-column contract. Four
catalog designs need provider series that the licensed RQData futures API does
not expose; they are registered with an explicit reason instead of being
silently approximated by an unrelated series.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import pandas as pd

from china_cta.factors.cta_common import FactorDataUnavailable
from china_cta.factors.qualified import BUILDERS as QUALIFIED_BUILDERS
from china_cta.factors.unqualified import BUILDERS as UNQUALIFIED_BUILDERS


BUILDERS = {**QUALIFIED_BUILDERS, **UNQUALIFIED_BUILDERS}


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
    "basis_mom_20": (
        "RQData 的 get_basis 仅覆盖股指期货；30 个商品品种没有统一现货序列，"
        "无法按 (现货-近月)/现货 的 20 日变化计算。"
    ),
    "ls_ratio_z": (
        "RQData 不提供散户多空比（ls_ratio）；会员持仓不能替代散户情绪，"
        "因此不计算。"
    ),
    "inventory_mom_20": (
        "RQData 只提供注册仓单（on_warrant），没有独立的社会库存/交易所库存序列；"
        "不能与 receipt_mom_20 共用同一份数据冒充两个因子。"
    ),
    "spot_profit_z": (
        "RQData 不提供覆盖 30 个商品品种的现货加工利润序列。"
    ),
}


FACTOR_SPECS: Final[tuple[FactorSpec, ...]] = (
    FactorSpec(
        "tsmom_252",
        "A_time_series_momentum",
        "P_t / P_{t-252} - 1",
        ("close",),
        "IC+ prior; repository call: ~0 in China",
        True,
        0.20,
    ),
    FactorSpec(
        "tsmom_252_21",
        "A_time_series_momentum",
        "P_{t-21} / P_{t-252} - 1",
        ("close",),
        "IC+ prior; repository call: weak IC+",
        True,
        0.20,
    ),
    FactorSpec(
        "tsmom_63",
        "A_time_series_momentum",
        "P_t / P_{t-63} - 1",
        ("close",),
        "IC+ prior; repository call: strong IC- reversal",
        True,
        0.20,
    ),
    FactorSpec(
        "breakout_55",
        "A_time_series_momentum",
        "clip((P_t - mid)/(0.5*(HH_55-LL_55)), -1, 1)",
        ("close", "high", "low"),
        "IC+ prior; repository call: IC- reversal",
        True,
        1.0,
    ),
    FactorSpec(
        "ema_xover_20_100",
        "A_time_series_momentum",
        "(EMA_20 - EMA_100) / (HV_20 * P_t)",
        ("close",),
        "IC+ prior; repository call: IC- reversal",
        True,
        0.50,
    ),
    FactorSpec(
        "xsmom_252_21",
        "B_cross_sectional_momentum",
        "per-date rank of P_{t-21}/P_{t-252}-1",
        ("close",),
        "IC+ prior; repository call: weak IC+",
        True,
        1.0,
    ),
    FactorSpec(
        "xsmom_63",
        "B_cross_sectional_momentum",
        "per-date rank of P_t/P_{t-63}-1",
        ("close",),
        "IC+ prior; repository call: strong IC- reversal",
        True,
        1.0,
    ),
    FactorSpec(
        "carry_ann",
        "C_carry_and_roll",
        "(Pn/Pf - 1) * 365 / (Df - Dn)",
        ("near_price", "far_price", "near_days", "far_days"),
        "IC+ prior; repository call: IC- in China",
        True,
        0.20,
    ),
    FactorSpec(
        "roll_return_63",
        "C_carry_and_roll",
        "63d sum of (old/new - 1) on roll days",
        ("contract_prices", "dominant_map"),
        "IC+ prior; repository call: not tested",
        True,
        0.05,
    ),
    FactorSpec(
        "basis_mom_20",
        "C_carry_and_roll",
        "basis_t - basis_{t-20}, basis=(spot - Pn)/spot",
        ("spot_price", "near_price"),
        "IC+ prior; repository call: not tested",
        False,
        0.20,
        UNAVAILABLE_REASONS["basis_mom_20"],
    ),
    FactorSpec(
        "vol_scaled_carry",
        "C_carry_and_roll",
        "carry_ann / HV_20",
        ("near_price", "far_price", "near_days", "far_days", "close"),
        "IC+ prior; repository call: IC- in China",
        True,
        0.50,
    ),
    FactorSpec(
        "ts_slope",
        "D_term_structure",
        "ln(Pf/Pn) / (Df - Dn)",
        ("near_price", "far_price", "near_days", "far_days"),
        "IC- prior; repository call: IC+ and best tradable factor",
        True,
        0.0005,
    ),
    FactorSpec(
        "ts_curvature",
        "D_term_structure",
        "(P3 - 2*P2 + P1) / P2",
        ("near_price", "second_price", "third_price"),
        "exploratory; repository call: not tested",
        True,
        0.05,
    ),
    FactorSpec(
        "oi_price_confirm_20",
        "E_positioning",
        "sign(P_t - P_{t-20}) * ln(OI_t/OI_{t-20})",
        ("close", "open_interest"),
        "IC+ prior; repository call: ~0 in China",
        True,
        0.20,
    ),
    FactorSpec(
        "broker_net_chg_5",
        "E_positioning",
        "delta(top20 member net long, 5d) / OI_t",
        ("member_rank", "open_interest"),
        "IC+ prior; repository call: not tested",
        True,
        0.02,
    ),
    FactorSpec(
        "ls_ratio_z",
        "E_positioning",
        "60d z-score of retail long/short ratio",
        ("ls_ratio",),
        "IC- prior; repository call: not tested",
        False,
        1.0,
        UNAVAILABLE_REASONS["ls_ratio_z"],
    ),
    FactorSpec(
        "virtual_ratio_chg",
        "E_positioning",
        "delta(OI/volume, 20d)",
        ("open_interest", "volume"),
        "exploratory; repository call: not tested",
        True,
        0.20,
        proxy=True,
    ),
    FactorSpec(
        "inventory_mom_20",
        "F_inventory_and_spot",
        "ln(inventory_t / inventory_{t-20})",
        ("inventory",),
        "IC- prior; repository call: not tested",
        False,
        0.20,
        UNAVAILABLE_REASONS["inventory_mom_20"],
    ),
    FactorSpec(
        "receipt_mom_20",
        "F_inventory_and_spot",
        "ln(on_warrant_t / on_warrant_{t-20})",
        ("on_warrant",),
        "IC- prior; repository call: not tested",
        True,
        0.20,
    ),
    FactorSpec(
        "spot_profit_z",
        "F_inventory_and_spot",
        "60d z-score of spot processing profit",
        ("spot_profit",),
        "IC- prior; repository call: not tested",
        False,
        1.0,
        UNAVAILABLE_REASONS["spot_profit_z"],
    ),
    FactorSpec(
        "lowvol",
        "G_volatility_and_reversal",
        "-HV_20",
        ("close",),
        "IC+ prior; repository call: strongest IC+ but weak tradable Sharpe",
        True,
        0.20,
    ),
    FactorSpec(
        "st_reversal_5",
        "G_volatility_and_reversal",
        "-(P_t / P_{t-5} - 1)",
        ("close",),
        "IC+ prior; repository call: IC+",
        True,
        0.05,
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


def build_all(
    *,
    continuous_prices: pd.DataFrame,
    contract_snapshots: pd.DataFrame,
    dominant_map: pd.DataFrame,
    warehouse_stocks: pd.DataFrame,
    member_rank: pd.DataFrame,
    universe: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Build every available factor and return the unavailable reasons."""

    inputs = {
        "continuous_prices": continuous_prices,
        "contract_snapshots": contract_snapshots,
        "dominant_map": dominant_map,
        "warehouse_stocks": warehouse_stocks,
        "member_rank": member_rank,
        "universe": universe,
    }
    factors: dict[str, pd.DataFrame] = {}
    for name in AVAILABLE_FACTORS:
        builder = BUILDERS.get(name)
        if builder is None:
            raise RuntimeError(f"no builder registered for available factor {name}")
        factors[name] = builder(inputs)

    missing = sorted(set(AVAILABLE_FACTORS) - set(factors))
    extra = sorted(set(factors) - set(AVAILABLE_FACTORS))
    if missing:
        raise RuntimeError(f"available factors were not built: {missing}")
    if extra:
        raise RuntimeError(f"unregistered factors were built: {extra}")
    unavailable = {
        spec.name: spec.reason or "unavailable"
        for spec in FACTOR_SPECS
        if not spec.available
    }
    for name, table in factors.items():
        if table.empty:
            raise RuntimeError(f"factor {name} produced an empty table")
    return factors, unavailable


__all__ = [
    "AVAILABLE_FACTORS",
    "FACTOR_SPECS",
    "FactorDataUnavailable",
    "FactorSpec",
    "UNAVAILABLE_FACTORS",
    "UNAVAILABLE_REASONS",
    "build_all",
    "spec_table",
]
