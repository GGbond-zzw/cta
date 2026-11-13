"""Unqualified factors: everything that is not one of the four live sleeves.

This package keeps the historical research library (Sharpe <= 0.65 on the
fixed-30 pool, unavailable data, or superseded variants such as the
``historical_skewness_252d_cs_rank`` cross-sectional variant and the
``breakout_55`` / ``carry_ann`` / ``vol_scaled_carry`` sleeves that were
replaced by the open-execution four-factor book.
"""

from __future__ import annotations

from china_cta.factors.unqualified.breakout_55 import build as build_breakout_55
from china_cta.factors.unqualified.carry_ann import build as build_carry_ann
from china_cta.factors.unqualified.historical_skewness_cs_rank import (
    build as build_historical_skewness_252d_cs_rank,
)
from china_cta.factors.unqualified.vol_scaled_carry import build as build_vol_scaled_carry
from china_cta.factors.unqualified.basis_mom_20 import build as build_basis_mom_20
from china_cta.factors.unqualified.broker_net_chg_5 import (
    build as build_broker_net_chg_5,
)
from china_cta.factors.unqualified.ema_xover_20_100 import (
    build as build_ema_xover_20_100,
)
from china_cta.factors.unqualified.inventory_mom_20 import (
    build as build_inventory_mom_20,
)
from china_cta.factors.unqualified.lowvol import build as build_lowvol
from china_cta.factors.unqualified.ls_ratio_z import build as build_ls_ratio_z
from china_cta.factors.unqualified.oi_price_confirm_20 import (
    build as build_oi_price_confirm_20,
)
from china_cta.factors.unqualified.receipt_mom_20 import build as build_receipt_mom_20
from china_cta.factors.unqualified.roll_return_63 import build as build_roll_return_63
from china_cta.factors.unqualified.spot_profit_z import build as build_spot_profit_z
from china_cta.factors.unqualified.st_reversal_5 import build as build_st_reversal_5
from china_cta.factors.unqualified.ts_curvature import build as build_ts_curvature
from china_cta.factors.unqualified.ts_slope import build as build_ts_slope
from china_cta.factors.unqualified.tsmom_252 import build as build_tsmom_252
from china_cta.factors.unqualified.tsmom_252_21 import build as build_tsmom_252_21
from china_cta.factors.unqualified.tsmom_63 import build as build_tsmom_63
from china_cta.factors.unqualified.virtual_ratio_chg import (
    build as build_virtual_ratio_chg,
)
from china_cta.factors.unqualified.xsmom_63 import build as build_xsmom_63


BUILDERS = {
    "breakout_55": build_breakout_55,
    "carry_ann": build_carry_ann,
    "historical_skewness_252d_cs_rank": build_historical_skewness_252d_cs_rank,
    "basis_mom_20": build_basis_mom_20,
    "broker_net_chg_5": build_broker_net_chg_5,
    "ema_xover_20_100": build_ema_xover_20_100,
    "inventory_mom_20": build_inventory_mom_20,
    "lowvol": build_lowvol,
    "ls_ratio_z": build_ls_ratio_z,
    "oi_price_confirm_20": build_oi_price_confirm_20,
    "receipt_mom_20": build_receipt_mom_20,
    "roll_return_63": build_roll_return_63,
    "spot_profit_z": build_spot_profit_z,
    "st_reversal_5": build_st_reversal_5,
    "ts_curvature": build_ts_curvature,
    "ts_slope": build_ts_slope,
    "tsmom_252": build_tsmom_252,
    "tsmom_252_21": build_tsmom_252_21,
    "tsmom_63": build_tsmom_63,
    "vol_scaled_carry": build_vol_scaled_carry,
    "virtual_ratio_chg": build_virtual_ratio_chg,
    "xsmom_63": build_xsmom_63,
}

__all__ = ["BUILDERS"]
