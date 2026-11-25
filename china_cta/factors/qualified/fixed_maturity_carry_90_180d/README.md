# fixed_maturity_carry

入口：`china_cta.factors.qualified.fixed_maturity_carry.build(inputs)`，返回标准五列因子表
（`trading_date/instrument/factor_name/raw_factor/signal`）。

- 信号时点：`trading_date` 收盘后可得，最早在下一交易日开盘执行（项目统一口径）。
- 参数来源：本地 300 次贝叶斯调优结果（`results/tuning/qualified4_300/fixed_maturity_carry_90_180d/best_params.json`）
- 参数取值：见 `parameters.json`。
- 说明：实现沿用项目原有模块，只换了目录结构。
