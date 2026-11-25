# inverse_oi_turnover_surprise_ratio

入口：`china_cta.factors.qualified.inverse_oi_turnover_surprise_ratio.build(inputs)`，返回标准五列因子表
（`trading_date/instrument/factor_name/raw_factor/signal`）。

- 信号时点：`trading_date` 收盘后可得，最早在下一交易日开盘执行（项目统一口径）。
- 参数来源：冻结的挖掘拟合结果（方向与尺度），本地未重新调优
- 参数取值：见 `parameters.json`。
- 说明：表达式：`oi_surprise_20 / mean(turnover_surprise_20, 10)`。
