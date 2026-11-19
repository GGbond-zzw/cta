# 挖掘因子（exported sleeves）

挖掘项目（另一个 checkout）用表达式搜索在价量仓特征上搜因子，拟合方向与尺度后把信号冻结成可移植的包。
本仓库不重新拟合：`china_cta/factors/exported.py` 只保存定位与校验所需的元数据，把包目录当成第五种
sleeve 来源。

## 登记表

| sleeve | 包 | 目录 | 方向 | 尺度 | 状态 |
| --- | --- | --- | ---: | ---: | --- |
| `crowded_trend_reversal_60d` | `old-mined-20261116` | `old_08` | +1 | 0.7074 | 合格 |
| `volume_burst_vol_reversal_60d` | `old-mined-20261116` | `new_01_previous_round` | −1 | 0.3029 | 合格 |
| `turnover_surprise_channel_ratio` | `round2-20261119` | `current_01_turnover_surprise_channel_ratio` | +1 | 4.4143 | 合格 |
| `inverse_oi_turnover_surprise_ratio` | `round2-20261119` | `current_08_inverse_oi_turnover_surprise_ratio` | −1 | 3.1317 | 合格 |
| `volume_variability_weighted_reversal` | `round2-20261119` | `current_20_volume_variability_weighted_reversal` | −1 | 0.0007 | 合格 |
| `volume_oi_coflow_10d` | `old-mined-20261116` | `old_02` | +1 | 0.7148 | 退役 |
| `volume_channel_price_oi_volatility` | `round2-20261119` | `current_06_volume_channel_price_oi_volatility` | +1 | 5.3721 | 退役 |

状态字段由 `ExportedSleeve.status` 携带，`classification.QUALIFIED_EXPORTED` 只取 `qualified` 的五条。
两条退役 sleeve 保留在登记表里，保证历史结果可复现，但不进组合：

* `volume_oi_coflow_10d`：研究层样本外（2022–2025）夏普 −0.27，唯一可调窗口的最优点仍然是 10，没有改进空间。
* `volume_channel_price_oi_volatility`：与 `turnover_surprise_channel_ratio` 日收益相关 0.72（2025 年 0.80），
  单腿原生账户 −0.08；删掉它只损失 0.03 夏普，却省下约两个点的摩擦。

## 命名规则

描述性前缀说明表达式在衡量什么，数字后缀是它最关键的那个窗口：`crowded_trend_reversal_60d` 的 60 是相关性窗口，
`volume_oi_coflow_10d` 的 10 是唯一窗口，`turnover_surprise_channel_ratio` 没有可调窗口所以不带后缀。

## 多包混装

`--extra-package` 可以重复给，`exported.locate()` 会为每条 sleeve 找真正持有它的那个目录，重复或缺失都会报错。
`--extra-factors` 接受 `all`、`qualified`、`retired` 或逗号分隔的名字：

```
python scripts/70_native_backtest.py \
  --factors historical_skewness_252d,fixed_maturity_carry_90_180d,xsmom_252_21,oi_participation_trend_60d \
  --extra-package <round-1-export> --extra-package <round-2-export> \
  --extra-factors qualified --book-factors none \
  --start 2016-01-04 --end 2026-09-04 --out-dir results/final_9f_native
```

## 数据契约

每个 sleeve 目录需含 `signals.parquet`（列 `trading_date/instrument/raw_factor/signal/factor_name`）与
`definition.json`（表达式树 + `fitted.direction/scale`）。`validate_package()` 会核对目录名、`factor_name`、
方向与尺度；`load_signals()` 还会拒绝重复键、越界信号（|signal| > 1）与不可解析日期。

导出包的 `raw_factor` 可能已经含了方向，因此本仓库统一按“`raw_factor` 已定向，`signal = clip(raw_factor / scale, −1, 1)`”
处理，与 `schema.make_factor_table` 一致。

## 与既有因子一起使用时

* 导出包覆盖 30 个品种（含项目未定价的 BU/C/FU/HC/RM）；进入组合前与项目 `universe` 做同样的 PIT 连接，
  并打印被剔除的品种。
* 结果写进 `config.json` 的 `sleeves`、`sleeve_weights`、`exported_packages`、`exported_sleeves`。

## 最终组合：九条 sleeve

四条手写 + 五条挖掘（一轮两条、二轮三条），各 1/9。原生账户口径（5000 万本金、50% 保证金按实时权益、
1 跳滑点、原生手续费），2016-01-04..2026-09-04：夏普 1.7018、年化 37.79%、波动 20.02%、最大回撤 −20.18%，
期末 26.08 倍；三段 训练 1.722 / 验证 1.387 / 测试 2.112。研究层等权（1bp）夏普 2.01。

同一账户下的对照：四腿 1.3498、六腿 1.5359、七腿 1.5674、九腿 1.7018、十腿 1.7293 —— 九腿比十腿少 0.03 夏普，
但摩擦从 22.4% 降到 20.3%、回撤更浅，是成本与分散度之间的折中。
