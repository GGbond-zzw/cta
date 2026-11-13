# 固定30品种回测口径

默认回测品种文件为 `results/liquidity_monthly_2026-09/selected_products.json`。这份名单由 2026 年 8 月逐日评分筛出、标记为 2026 年 9 月持有名单；在本项目后续研究回测中，**名单固定贯穿整个回测区间**。例如回测 2020 年时仍使用同一30品种，不按 2020 年的月份重新筛选。需要换用以后生成的固定名单，可显式传 `--products-file`。

固定的是**品种允许集合**，不是每个历史日期都强行持有30个品种。未上市、已退市、缺价格或未通过现有逐日交易资格检查的品种，在对应日期不会产生有效交易。因名单用 2026 年之后的信息选出，再用于更早年份，这种回测有明确的**事后选择/前瞻样本偏差**，不可当成真实历史可实施策略的无偏绩效。

五个主要研究回测入口默认读取这份文件：`basis_momentum_test.py`、`historical_skewness_test.py`、`historical_skewness_cs_test.py`、`factor_v2_test.py`、`factor_v3_test.py`。单项入口结果目录带 `fixedpool_2026_09` 后缀，可通过 `--overwrite` 更新同名结果。统一入口 `rerun_all_factors.py --overwrite` 使用同一份名单、同一批行情和资格表，重跑并覆盖当前八份因子结果目录。教学 walkthrough、RQAlpha smoke、季节性研究和名单筛选文件不属于这八份因子回测。

价格型因子的信号价格统一为收盘价：主连趋势与历史偏度使用复权连续合约收盘价；固定90/180天 carry 和基差动量使用未复权真实合约收盘价。研究收益保持收盘价到收盘价、一交易期执行时滞、原教学标准的1bp换手成本代理；每份结果的 `config.json` 记录实际使用的 `cost_rate`，是口径的唯一来源。每个当前因子只保留一份结果；固定期限 carry 的目录为 `results/qualified/fixed_maturity_carry_90_180d_2016_2025_v1`。结果按 0.65 阈值分流到 `results/qualified/` 与 `results/unqualified/`，完整映射见 `docs/factor_classification.md`。重复的旧 consistent/OI v1 结果已清理，实际因子定义与目录名保持一致。流动性名单中的结算价只用于金额估算。

```powershell
python scripts/basis_momentum_test.py --start 2016-01-01 --end 2026-01-01
python scripts/factor_v3_test.py --products-file results/liquidity_monthly_2026-09/selected_products.json

# 覆盖当前八份因子回测；全部计算成功后才开始写入旧目录
python scripts/rerun_all_factors.py --overwrite
```

统一入口还输出 `results/all_factors_fixed30_summary.csv` 和完成清单
`results/all_factors_fixed30_manifest.json`。固定期限 carry 的目录下另存
`fixed_maturity_diagnostics.csv` 与逐品种 `fixed_maturity_coverage.csv`。
数据缺失、许可证不可用或某因子没有有效观测时，报错且不替换旧结果。

第一次对新30品种运行时可能需要 RQData 联网补齐历史行情；`--cache-only` 只有所有请求均已缓存时才可用。所有新因子回测也应通过 `china_cta.data.fixed_universe.load_fixed_product_pool` 读取相同文件，而不是重新维护脚本内手写品种名单。
