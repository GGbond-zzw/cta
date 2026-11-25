# crowded_trend_reversal_60d

入口：`china_cta.factors.qualified.crowded_trend_reversal_60d.build(inputs)`，返回标准五列因子表
（`trading_date/instrument/factor_name/raw_factor/signal`）。

- 信号时点：`trading_date` 收盘后可得，最早在下一交易日开盘执行（项目统一口径）。
- 参数来源：冻结的挖掘拟合结果（方向与尺度），本地未重新调优
- 参数取值：见 `parameters.json`。
- 说明：表达式：`neg(corr(mean(return_60, 60), mul(channel_position_20, volatility_20), 60))`。
