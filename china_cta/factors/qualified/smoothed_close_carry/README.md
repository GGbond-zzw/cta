# smoothed_close_carry

入口：`china_cta.factors.qualified.smoothed_close_carry.build(inputs)`，返回标准五列因子表
（`trading_date/instrument/factor_name/raw_factor/signal`）。

- 信号时点：`trading_date` 收盘后可得，最早在下一交易日开盘执行（项目统一口径）。
- 参数来源：round-two spec defaults (smoothing 5, scale 0.05, deadband 0.05)
- 参数取值：见 `parameters.json`。
- 说明：移植自远端 `850772a` 的同名因子包，实现未改动。
