"""Eleven research-approved integration builders; not a profitability guarantee."""
from .fixed_maturity_carry import build as build_0
from .historical_skewness import build as build_1
from .oi_participation_trend import build as build_2
from .xsmom_252_21 import build as build_3
from .smoothed_close_carry import build as build_4
from .reg35_transformer import build as build_5
from .crowded_trend_reversal_60d import build as build_6
from .volume_burst_vol_reversal_60d import build as build_7
from .turnover_surprise_channel_ratio import build as build_8
from .inverse_oi_turnover_surprise_ratio import build as build_9
from .volume_variability_weighted_reversal import build as build_10

BUILDERS = {
    'fixed_maturity_carry_90_180d': build_0,
    'historical_skewness_252d': build_1,
    'oi_participation_trend_60d': build_2,
    'xsmom_252_21': build_3,
    'our_close_carry_smooth5': build_4,
    'our_reg35_transformer': build_5,
    'crowded_trend_reversal_60d': build_6,
    'volume_burst_vol_reversal_60d': build_7,
    'turnover_surprise_channel_ratio': build_8,
    'inverse_oi_turnover_surprise_ratio': build_9,
    'volume_variability_weighted_reversal': build_10,
}
__all__=["BUILDERS"]
