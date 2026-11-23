"""Frozen five-session real-close carry, compatible with peer build(inputs)."""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from china_cta.factors.schema import make_factor_table

FACTOR_NAME = 'our_close_carry_smooth5'


def _dates(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy(deep=True)
    for column in columns:
        result[column] = pd.to_datetime(result[column], errors='raise').dt.normalize()
        if result[column].dt.tz is not None or result[column].isna().any():
            raise ValueError('Trading and maturity dates must be nonmissing timezone-naive dates')
    return result


def input_grid(universe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DatetimeIndex, list[str]]:
    """Use the supplied complete official session grid; never invent sessions."""
    if not {'trading_date', 'instrument', 'eligible'}.issubset(universe):
        raise ValueError('universe requires trading_date,instrument,eligible')
    u = _dates(universe, ('trading_date',))
    u['instrument'] = u.instrument.astype('string').str.strip().str.upper()
    if u.instrument.isna().any() or u.instrument.eq('').any() or u.empty:
        raise ValueError('A nonempty universe with product codes is required')
    if u.duplicated(['trading_date', 'instrument']).any():
        raise ValueError('Duplicate universe keys')
    if not u.eligible.isin([True, False]).all():
        raise ValueError('Universe eligibility must contain explicit booleans')
    cal = pd.DatetimeIndex(sorted(u.trading_date.unique()))
    symbols = sorted(u.instrument.unique().tolist())
    if len(u) != len(cal) * len(symbols):
        raise ValueError('Supply every official session/product row, including eligible=False')
    return u, cal, symbols


def calculate_close_carry(contract_snapshots: pd.DataFrame, dominant_map: pd.DataFrame,
                          universe: pd.DataFrame) -> pd.DataFrame:
    """Earliest live near expiry before same-date main; annualize calendar gap."""
    _, cal, symbols = input_grid(universe)
    required = {'trading_date', 'order_book_id', 'underlying_symbol', 'maturity_date'}
    if not required.issubset(contract_snapshots):
        raise ValueError('Contract snapshots require date,id,product,maturity and real close')
    s = _dates(contract_snapshots, ('trading_date', 'maturity_date'))
    if 'close' in s:
        price = s['close']
    elif 'price' in s and 'price_field' in s and s.price_field.eq('close').all():
        price = s['price']
    else:
        raise ValueError('Use close, or price explicitly labeled price_field=close')
    s['price'] = pd.to_numeric(price, errors='coerce').where(lambda x: np.isfinite(x) & x.gt(0))
    s['underlying_symbol'] = s.underlying_symbol.astype('string').str.strip().str.upper()
    s['order_book_id'] = s.order_book_id.astype('string').str.strip().str.upper()
    if s.duplicated(['trading_date', 'order_book_id']).any():
        raise ValueError('Duplicate real contract quotes')
    s = s.loc[s.trading_date.lt(s.maturity_date)]
    if 'listed_date' in s:
        listed = pd.to_datetime(s.listed_date, errors='raise').dt.normalize()
        s = s.loc[s.trading_date.ge(listed)]
    d = _dates(dominant_map, ('trading_date',))
    if 'product' not in d and 'underlying_symbol' in d:
        d = d.rename(columns={'underlying_symbol': 'product'})
    if not {'product', 'dominant_order_book_id'}.issubset(d):
        raise ValueError('Dominant map requires product and dominant_order_book_id')
    d['product'] = d['product'].astype('string').str.strip().str.upper()
    d['dominant_order_book_id'] = d.dominant_order_book_id.astype('string').str.strip().str.upper()
    if d.duplicated(['trading_date', 'product']).any():
        raise ValueError('Duplicate same-date dominant mappings')
    main = d.merge(s[['trading_date', 'order_book_id', 'underlying_symbol', 'price', 'maturity_date']],
        left_on=['trading_date', 'dominant_order_book_id', 'product'],
        right_on=['trading_date', 'order_book_id', 'underlying_symbol'], how='inner', validate='one_to_one')
    main = main[['trading_date', 'product', 'price', 'maturity_date']].rename(
        columns={'price': 'main_price', 'maturity_date': 'main_maturity'})
    pairs = s.merge(main, left_on=['trading_date', 'underlying_symbol'],
        right_on=['trading_date', 'product'], how='inner', validate='many_to_one')
    pairs = pairs.loc[pairs.maturity_date.lt(pairs.main_maturity)]
    pairs = pairs.sort_values(['trading_date', 'product', 'maturity_date', 'order_book_id']).groupby(
        ['trading_date', 'product'], sort=False).head(1)
    pairs['raw_carry'] = (pairs.price / pairs.main_price - 1) * 365 / (pairs.main_maturity - pairs.maturity_date).dt.days
    return pairs.pivot(index='trading_date', columns='product', values='raw_carry').reindex(index=cal, columns=symbols)


def compute_smoothed_close_carry_factor(contract_snapshots: pd.DataFrame,
        dominant_map: pd.DataFrame, universe: pd.DataFrame, *, smoothing_sessions: int = 5,
        signal_scale: float = .05, deadband: float = .05) -> pd.DataFrame:
    """C=365*(nearClose/mainClose-1)/expiryGap; signal=clip(mean5(C)/.05)."""
    if isinstance(smoothing_sessions, bool) or not isinstance(smoothing_sessions, int) or smoothing_sessions < 1:
        raise ValueError('smoothing_sessions must be a positive integer')
    if not np.isfinite(deadband) or not 0 <= deadband < 1:
        raise ValueError('deadband must be in [0,1)')
    raw = calculate_close_carry(contract_snapshots, dominant_map, universe)
    smooth = raw.rolling(smoothing_sessions, min_periods=smoothing_sessions).mean()
    # Preserve the historical own-sleeve row membership: unavailable raw values
    # are omitted, not zero-filled or counted as active peer sleeve exposures.
    long = smooth.rename_axis(index='trading_date', columns='instrument').stack().rename('raw_factor').reset_index()
    result = make_factor_table(long, universe, factor_name=FACTOR_NAME, signal_scale=signal_scale)
    result['signal'] = result.signal.where(result.signal.abs().ge(deadband), 0.)
    result.attrs.update(definition='mean5(365*(near_close/main_close-1)/calendar_expiry_gap)',
        price_field='close', smoothing_sessions=smoothing_sessions, deadband=deadband,
        missing_policy='no price fill;full official-session window;unavailable rows omitted')
    return result


def build(inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    return compute_smoothed_close_carry_factor(inputs['contract_snapshots'],
        inputs['dominant_map'], inputs['universe'])
