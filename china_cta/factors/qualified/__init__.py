"""Qualified factors: the four open-execution sleeves used by the live pipeline.

Every factor here is validated with next-open execution, next-open fills and the
1bp-per-unit-turnover cost model used by :mod:`china_cta.research.fast_backtest`:

* ``fixed_maturity_carry_90_180d``
* ``historical_skewness_252d``
* ``oi_participation_trend_60d``
* ``xsmom_252_21``
"""

from __future__ import annotations

from china_cta.factors.qualified.fixed_maturity_carry import (
    build as build_fixed_maturity_carry_90_180d,
)
from china_cta.factors.qualified.historical_skewness import (
    build as build_historical_skewness_252d,
)
from china_cta.factors.qualified.oi_participation_trend import (
    build as build_oi_participation_trend_60d,
)
from china_cta.factors.qualified.xsmom_252_21 import build as build_xsmom_252_21


BUILDERS = {
    "fixed_maturity_carry_90_180d": build_fixed_maturity_carry_90_180d,
    "historical_skewness_252d": build_historical_skewness_252d,
    "oi_participation_trend_60d": build_oi_participation_trend_60d,
    "xsmom_252_21": build_xsmom_252_21,
}

__all__ = ["BUILDERS"]
