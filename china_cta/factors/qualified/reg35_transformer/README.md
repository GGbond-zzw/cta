# reg35_transformer

入口：`china_cta.factors.qualified.reg35_transformer.build(inputs)`，返回标准五列因子表
（`trading_date/instrument/factor_name/raw_factor/signal`）。

- 信号时点：`trading_date` 收盘后可得，最早在下一交易日开盘执行（项目统一口径）。
- 参数来源：frozen model weights (assets/reg35_transformer); torch required
- 参数取值：见 `parameters.json`。
- 说明：移植自远端 `850772a`；需要 torch 与 `assets/reg35_transformer/` 下的三个 `.pt` 权重与 `manifest.json`（本仓库不含二进制权重）。
