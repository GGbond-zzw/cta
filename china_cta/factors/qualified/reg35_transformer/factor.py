"""Frozen three-seed regularized Transformer sleeve; inference only.

No trainer, results/ paths, network credentials or local market caches are used.
PyTorch is optional until this builder is called. Prediction horizon is five
sessions; scores update every session and are not five fixed holding sleeves.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from china_cta.factors.schema import make_factor_table
from china_cta.factors.qualified.reg35_transformer._features import build_features
from china_cta.factors.qualified.smoothed_close_carry import calculate_close_carry, input_grid

FACTOR_NAME = 'our_reg35_transformer'
ASSETS = Path(__file__).resolve().parent / 'assets' / 'reg35_transformer'


def _model(spec: dict[str, Any], nfeatures: int) -> Any:
    """Same named layers and causal mask as the frozen training architecture."""
    import torch
    from torch import nn

    class Encoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            w, length = spec['width'], spec['length']
            self.project = nn.Linear(nfeatures, w)
            self.position = nn.Parameter(torch.zeros(1, length, w))
            layer = nn.TransformerEncoderLayer(w, 4, w * 2, spec['dropout'],
                activation='gelu', batch_first=True, norm_first=True)
            self.encoder = nn.TransformerEncoder(layer, spec['layers'], enable_nested_tensor=False)
            self.head = nn.Sequential(nn.LayerNorm(w), nn.Linear(w, 1), nn.Tanh())
            self.register_buffer('mask', torch.triu(torch.ones(length, length, dtype=torch.bool), diagonal=1))

        def forward(self, x: Any) -> Any:
            return self.head(self.encoder(self.project(x) + self.position, mask=self.mask)[:, -1]).squeeze(-1)

    return Encoder()


def _panels(prices: pd.DataFrame, dominant: pd.DataFrame, cal: pd.DatetimeIndex,
            symbols: list[str]) -> dict[str, pd.DataFrame]:
    fields = ['open', 'high', 'low', 'close', 'volume', 'open_interest', 'total_turnover']
    if not {'trading_date', 'underlying_symbol', *fields}.issubset(prices):
        raise ValueError('Continuous prices require adjusted OHLC and real dominant volume,OI,amount')
    if prices.attrs.get('adjust_method', 'prev_close_ratio') != 'prev_close_ratio':
        raise ValueError('Frozen features require prev_close_ratio adjustment')
    p = prices.copy(deep=True)
    p['trading_date'] = pd.to_datetime(p.trading_date, errors='raise').dt.normalize()
    p['underlying_symbol'] = p.underlying_symbol.astype('string').str.strip().str.upper()
    if p.duplicated(['trading_date', 'underlying_symbol']).any():
        raise ValueError('Duplicate continuous quotes')
    for field in fields:
        values = pd.to_numeric(p[field], errors='coerce')
        p[field] = values.where(np.isfinite(values) & (values.gt(0) if field in fields[:4] else values.ge(0)))
    panels = {field: p.pivot(index='trading_date', columns='underlying_symbol', values=field).reindex(
        index=cal, columns=symbols) for field in fields}
    d = dominant.copy(deep=True)
    if 'product' not in d:
        d = d.rename(columns={'underlying_symbol': 'product'})
    d['trading_date'] = pd.to_datetime(d.trading_date, errors='raise').dt.normalize()
    d['product'] = d['product'].astype('string').str.strip().str.upper()
    panels['ids'] = d.pivot(index='trading_date', columns='product', values='dominant_order_book_id').reindex(index=cal, columns=symbols)
    return panels


def compute_reg35_transformer_factor(continuous_prices: pd.DataFrame,
        universe: pd.DataFrame, contract_snapshots: pd.DataFrame, dominant_map: pd.DataFrame,
        *, device: str = 'auto', batch_size: int = 512) -> pd.DataFrame:
    """Average three frozen tanh predictions on sixty historical feature tokens."""
    import torch
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError('batch_size must be a positive integer')
    if device not in ['auto', 'cpu', 'cuda']:
        raise ValueError('device must be auto,cpu,cuda')
    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    if device == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA requested but unavailable')
    manifest = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf8'))
    u, cal, symbols = input_grid(universe)
    carry = calculate_close_carry(contract_snapshots, dominant_map, u)
    panels = _panels(continuous_prices, dominant_map, cal, symbols)
    pool = u.pivot(index='trading_date', columns='instrument', values='eligible').reindex(index=cal, columns=symbols).eq(True).to_numpy()
    with np.errstate(divide='ignore', invalid='ignore'):
        raw, features = build_features(panels, pool)
    raw = np.concatenate([raw, carry.to_numpy(dtype=np.float32)[..., None]], axis=-1)
    features += ['raw_close_carry']
    order = manifest['features']
    if len(set(order)) != len(order) or not set(order).issubset(features):
        raise ValueError('Frozen feature order is invalid')
    raw = raw[..., [features.index(n) for n in order]]
    ready = panels['close'].rolling(120, min_periods=120).count().eq(120).to_numpy()
    i, j = np.where(ready & pool)
    predictions = []
    for checkpoint in manifest['checkpoints']:
        path = ASSETS / checkpoint['file']
        if path.parent != ASSETS or hashlib.sha256(path.read_bytes()).hexdigest() != checkpoint['sha256']:
            raise ValueError('Frozen model file checksum mismatch')
        saved = torch.load(path, map_location='cpu', weights_only=True)
        if saved['spec'] != manifest['spec']:
            raise ValueError('Model specification differs from frozen manifest')
        mean, std = np.asarray(saved['mean'], dtype=np.float32), np.asarray(saved['std'], dtype=np.float32)
        if mean.shape != (len(order),) or std.shape != mean.shape or not np.isfinite(mean).all() or not np.isfinite(std).all() or (std <= 0).any():
            raise ValueError('Invalid frozen training scaler')
        observed = np.isfinite(raw)
        encoded = np.concatenate([np.where(observed, np.clip((raw - mean) / std, -5, 5), 0.),
                                  (~observed).astype(float)], axis=-1).astype(np.float32)
        length = saved['spec']['length']
        if length != 60:
            raise ValueError('Frozen model requires sixty-session sequences')
        # No samples can be ready without at least120 valid close observations.
        if len(cal) < length or not len(i):
            return make_factor_table(pd.DataFrame(columns=['trading_date', 'instrument', 'raw_factor']),
                u, factor_name=FACTOR_NAME, signal_scale=1.)
        windows = torch.from_numpy(encoded).unfold(0, length, 1).permute(0, 1, 3, 2)
        net = _model(saved['spec'], encoded.shape[-1]).to(device)
        net.load_state_dict(saved['state_dict'], strict=True)
        net.eval()
        values = []
        with torch.no_grad():
            for first in range(0, len(i), batch_size):
                x = windows[i[first:first + batch_size] - length + 1, j[first:first + batch_size]].to(device)
                with torch.autocast(device_type=device, dtype=torch.bfloat16,
                                    enabled=device == 'cuda' and torch.cuda.is_bf16_supported()):
                    pred = net(x)
                values.append(pred.float().cpu().numpy())
        predictions.append(np.concatenate(values))
        del net
    score = np.mean(predictions, axis=0)
    if not np.isfinite(score).all():
        raise ValueError('Nonfinite frozen model scores')
    raw_table = pd.DataFrame(dict(trading_date=cal[i], instrument=np.asarray(symbols)[j], raw_factor=score))
    result = make_factor_table(raw_table, u, factor_name=FACTOR_NAME, signal_scale=1.)
    result.attrs.update(prediction_horizon=5, update_frequency='every_trading_session',
        sequence_length=60, raw_feature_count=len(order), encoded_feature_count=2 * len(order),
        training=False, scaler='frozen_training_mean_std;clip5;zero_plus_missing_flags',
        training_period='2016-2021;this period is training replay,not out-of-sample',
        inference_precision='cuda_bfloat16' if device == 'cuda' and torch.cuda.is_bf16_supported() else 'float32',
        feature_pool='supplied full universe;cross-sectional features recomputed on that pool',
        signal_meaning='bounded relative-return-rank score,not expected percentage return')
    return result


def build(inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    return compute_reg35_transformer_factor(inputs['continuous_prices'], inputs['universe'],
        inputs['contract_snapshots'], inputs['dominant_map'])
