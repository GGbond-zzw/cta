# CTA 十一因子研究与回测

仅保留当前十一项因子，全部位于china_cta/factors/qualified/，每个因子独立文件夹，包含factor.py、__init__.py、parameters.json、README.md。

|目录|因子|
|---|---|
|fixed_maturity_carry|固定期限Carry|
|historical_skewness|历史偏度|
|oi_participation_trend|持仓参与趋势|
|xsmom_252_21|横截面动量|
|crowded_trend_reversal_60d|拥挤趋势反转|
|volume_burst_vol_reversal_60d|放量波动反转|
|turnover_surprise_channel_ratio|成交额意外通道比|
|inverse_oi_turnover_surprise_ratio|持仓成交额意外反比|
|volume_variability_weighted_reversal|成交量变异加权反转|
|smoothed_close_carry|五日平滑收盘Carry|
|reg35_transformer|正则Transformer|

统一注册入口：`from china_cta.factors.qualified import BUILDERS`，调用`BUILDERS[name](inputs)`。
目录对应见[完整清单](docs/eleven_factor_layout.json)。输入合同见[自有因子说明](china_cta/factors/qualified/OWN_FACTORS_README.md)。

## 安装和生成信号

Python3.11，`pip install -e .`；Transformer选装：`pip install -e ".[transformer]"`。

`python scripts/25_build_eleven_factors.py --input-dir path/to/inputs --out-dir results/eleven_signals`

输入目录需有continuous_prices.parquet、contract_snapshots.parquet、dominant_map.parquet、universe.parquet；聚合量仓挖掘因子还应提供product_flows.parquet。不要提交行情、bundle、凭据或环境。

四个原手写因子保留原默认参数，历史调优数值须显式配置，不能把默认计算误认为历史最佳参数的精确复现。五个挖掘因子可直接重建，冻结公式、方向和尺度见各自parameters.json。Transformer三份冻结权重已随目录保存于reg35_transformer/assets/reg35_transformer，无需重新训练；79原始特征加79缺失标志，60日序列。

## 测试和边界

`python -m pytest tests -m "not integration and not formal" -q`

集成/正式回测另需本地数据及权限。所有因子返回标准五列。信号在收盘及真实输入可得后生成，最早下一交易日首时段开盘执行（含夜盘）。分数不是手数，账户、风控、费用由原流程处理。新增脚本只生成信号，不自动启动十一因子账户。

qualified是接入分类，不是统计显著或实盘批准。历史多段测试已查看；2026固定池回看历史存在事后选样；Transformer2016—2021为训练回放；原同事全精度参数及导出快照缺失。请保留这些复现边界。

已移除unqualified、旧scripts/research、changes及直接依赖已删除因子的旧测试。公共数学、表达式算子、数据层、风控和账户引擎保留。清理记录见[docs/CLEANUP.md](docs/CLEANUP.md)，完整备份保存在仓库外。
