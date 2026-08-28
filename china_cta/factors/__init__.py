"""Minimal Phase 3 CTA factor definitions."""

from china_cta.factors.carry import (
    calculate_near_main_carry,
    compute_carry_factor,
)
from china_cta.factors.oi_confirmed_trend import (
    OI_TREND_DIAGNOSTIC_COLUMNS,
    calculate_oi_confirmed_trend,
    compute_oi_confirmed_trend_factor,
)
from china_cta.factors.schema import FACTOR_COLUMNS
from china_cta.factors.trend import compute_trend_factor

__all__ = [
    "FACTOR_COLUMNS",
    "OI_TREND_DIAGNOSTIC_COLUMNS",
    "calculate_near_main_carry",
    "calculate_oi_confirmed_trend",
    "compute_carry_factor",
    "compute_oi_confirmed_trend_factor",
    "compute_trend_factor",
]
