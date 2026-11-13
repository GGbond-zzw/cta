"""CTA factor definitions, split into qualified and unqualified packages."""

from china_cta.factors.cta_catalog import (
    AVAILABLE_FACTORS,
    FACTOR_SPECS,
    UNAVAILABLE_FACTORS,
    build_all as build_cta_alpha_factors,
    spec_table as cta_alpha_spec_table,
)
from china_cta.factors.qualified.fixed_maturity_carry import (
    CURVE_CARRY_DIAGNOSTIC_COLUMNS,
    calculate_curve_carry,
    compute_curve_carry_factor,
)
from china_cta.factors.unqualified.historical_skewness_cs_rank import (
    compute_historical_skewness_factor_cs_rank,
)
from china_cta.factors.qualified.oi_participation_trend import (
    OI_PARTICIPATION_TREND_DIAGNOSTIC_COLUMNS,
    calculate_oi_participation_trend,
    compute_oi_participation_trend_factor,
)
from china_cta.factors.schema import FACTOR_COLUMNS
from china_cta.factors.unqualified.aggregate_oi import (
    AGGREGATE_OI_DIAGNOSTIC_COLUMNS,
    calculate_aggregate_oi_growth,
    compute_aggregate_oi_growth_factor,
)
from china_cta.factors.unqualified.basis_momentum import (
    BASIS_MOMENTUM_DIAGNOSTIC_COLUMNS,
    calculate_basis_momentum,
    compute_basis_momentum_factor,
)
from china_cta.factors.unqualified.carry import (
    calculate_near_main_carry,
    compute_carry_factor,
)
from china_cta.factors.unqualified.consistent_trend import (
    CONSISTENT_TREND_DIAGNOSTIC_COLUMNS,
    calculate_consistent_trend,
    compute_consistent_trend_factor,
)
from china_cta.factors.qualified.historical_skewness import (
    HISTORICAL_SKEWNESS_DIAGNOSTIC_COLUMNS,
    calculate_historical_skewness,
    compute_historical_skewness_factor,
)
from china_cta.factors.unqualified.multi_horizon_trend import (
    MULTI_HORIZON_TREND_DIAGNOSTIC_COLUMNS,
    calculate_multi_horizon_trend,
    compute_multi_horizon_trend_factor,
)
from china_cta.factors.unqualified.oi_confirmed_trend import (
    OI_TREND_DIAGNOSTIC_COLUMNS,
    calculate_oi_confirmed_trend,
    compute_oi_confirmed_trend_factor,
)
from china_cta.factors.unqualified.trend import compute_trend_factor

__all__ = [
    "AGGREGATE_OI_DIAGNOSTIC_COLUMNS",
    "AVAILABLE_FACTORS",
    "FACTOR_SPECS",
    "UNAVAILABLE_FACTORS",
    "build_cta_alpha_factors",
    "cta_alpha_spec_table",
    "BASIS_MOMENTUM_DIAGNOSTIC_COLUMNS",
    "CURVE_CARRY_DIAGNOSTIC_COLUMNS",
    "CONSISTENT_TREND_DIAGNOSTIC_COLUMNS",
    "FACTOR_COLUMNS",
    "HISTORICAL_SKEWNESS_DIAGNOSTIC_COLUMNS",
    "MULTI_HORIZON_TREND_DIAGNOSTIC_COLUMNS",
    "OI_TREND_DIAGNOSTIC_COLUMNS",
    "OI_PARTICIPATION_TREND_DIAGNOSTIC_COLUMNS",
    "calculate_aggregate_oi_growth",
    "calculate_basis_momentum",
    "calculate_curve_carry",
    "calculate_consistent_trend",
    "calculate_historical_skewness",
    "calculate_multi_horizon_trend",
    "calculate_near_main_carry",
    "calculate_oi_confirmed_trend",
    "calculate_oi_participation_trend",
    "compute_aggregate_oi_growth_factor",
    "compute_basis_momentum_factor",
    "compute_carry_factor",
    "compute_curve_carry_factor",
    "compute_consistent_trend_factor",
    "compute_historical_skewness_factor",
    "compute_historical_skewness_factor_cs_rank",
    "compute_multi_horizon_trend_factor",
    "compute_oi_confirmed_trend_factor",
    "compute_oi_participation_trend_factor",
    "compute_trend_factor",
]
