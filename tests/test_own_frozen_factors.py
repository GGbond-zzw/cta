"""Formula/PIT/package checks, optionally full frozen-history signal parity."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

from china_cta.factors.qualified import BUILDERS
from china_cta.factors.qualified.smoothed_close_carry import calculate_close_carry
from china_cta.factors.qualified.reg35_transformer import compute_reg35_transformer_factor
from china_cta.factors.schema import FACTOR_COLUMNS

ROOT = Path(__file__).resolve().parent


def fixture(n: int = 180) -> dict[str, pd.DataFrame]:
    cal = pd.bdate_range('2019-01-02', periods=n)
    symbols = ['A', 'B', 'C']
    u = pd.MultiIndex.from_product([cal, symbols], names=['trading_date', 'instrument']).to_frame(index=False).assign(eligible=True)
    rng = np.random.default_rng(20261120)
    c = 100 * np.exp(np.cumsum(rng.normal(0, .01, (n, 3)), axis=0))
    p = pd.DataFrame(dict(trading_date=np.repeat(cal, 3), underlying_symbol=symbols * n,
        close=c.ravel(), open=(c * .999).ravel(), high=(c * 1.01).ravel(), low=(c * .99).ravel(),
        volume=rng.uniform(1e4, 1e5, n * 3), open_interest=rng.uniform(1e4, 1e5, n * 3),
        total_turnover=rng.uniform(1e8, 1e9, n * 3)))
    dom = p[['trading_date', 'underlying_symbol']].rename(columns={'underlying_symbol': 'product'})
    dom['dominant_order_book_id'] = dom['product'] + '3101'
    near = p[['trading_date', 'underlying_symbol', 'close']].copy()
    near['order_book_id'] = near.underlying_symbol + '3001'
    near['maturity_date'] = pd.Timestamp('2030-01-01')
    near['close'] *= 1.03
    main = p[['trading_date', 'underlying_symbol', 'close']].copy()
    main['order_book_id'] = main.underlying_symbol + '3101'
    main['maturity_date'] = pd.Timestamp('2031-01-01')
    return dict(continuous_prices=p, universe=u, contract_snapshots=pd.concat([near, main]), dominant_map=dom)


class FactorPackageTests(unittest.TestCase):
    def test_carry_formula_deadband_and_five_column_contract(self) -> None:
        d = fixture(10)
        before = {k: v.copy(deep=True) for k, v in d.items()}
        result = BUILDERS['our_close_carry_smooth5'](d)
        self.assertEqual(tuple(result.columns), FACTOR_COLUMNS)
        self.assertEqual(len(result), 18)
        np.testing.assert_allclose(result.raw_factor, .03, atol=1e-14)
        np.testing.assert_allclose(result.signal, .6, atol=1e-12)
        for key in d:
            pd.testing.assert_frame_equal(d[key], before[key])

    def test_missing_session_not_filled_and_future_invariance(self) -> None:
        d = fixture(20)
        cut = sorted(d['universe'].trading_date.unique())[10]
        old = BUILDERS['our_close_carry_smooth5'](d)
        d['contract_snapshots'].loc[d['contract_snapshots'].trading_date.ge(cut), 'close'] *= 9
        new = BUILDERS['our_close_carry_smooth5'](d)
        pd.testing.assert_frame_equal(old.loc[old.trading_date.lt(cut)], new.loc[new.trading_date.lt(cut)])
        d = fixture(20)
        missing_day = sorted(d['universe'].trading_date.unique())[8]
        d['contract_snapshots'] = d['contract_snapshots'].loc[~d['contract_snapshots'].trading_date.eq(missing_day)]
        f = BUILDERS['our_close_carry_smooth5'](d)
        dates = sorted(d['universe'].trading_date.unique())
        self.assertFalse(f.trading_date.isin(dates[8:13]).any())

    def test_settlement_label_and_duplicate_keys_rejected(self) -> None:
        d = fixture(10)
        s = d['contract_snapshots'].rename(columns={'close': 'price'}).assign(price_field='settlement')
        with self.assertRaises(ValueError):
            calculate_close_carry(s, d['dominant_map'], d['universe'])
        d['dominant_map'] = pd.concat([d['dominant_map'], d['dominant_map'].head(1)])
        with self.assertRaises(ValueError):
            BUILDERS['our_close_carry_smooth5'](d)

    def test_frozen_model_causality_and_manifest(self) -> None:
        import torch
        torch.set_num_threads(4)
        d = fixture(180)
        args = lambda: (d['continuous_prices'], d['universe'], d['contract_snapshots'], d['dominant_map'])
        old = compute_reg35_transformer_factor(*args(), device='cpu')
        self.assertEqual(tuple(old.columns), FACTOR_COLUMNS)
        self.assertTrue(old.signal.between(-1, 1).all())
        self.assertEqual(old.attrs['encoded_feature_count'], 158)
        cut = sorted(d['universe'].trading_date.unique())[150]
        for field in ['open', 'high', 'low', 'close']:
            d['continuous_prices'].loc[d['continuous_prices'].trading_date.ge(cut), field] *= 2
        d['contract_snapshots'].loc[d['contract_snapshots'].trading_date.ge(cut), 'close'] *= 2
        new = compute_reg35_transformer_factor(*args(), device='cpu')
        pd.testing.assert_frame_equal(old.loc[old.trading_date.lt(cut)], new.loc[new.trading_date.lt(cut)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
