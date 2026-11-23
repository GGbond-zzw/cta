# crowded_trend_reversal_60d

入口：`china_cta.factors.qualified.crowded_trend_reversal_60d.build(inputs)`。

标准五列输出；信号为当日信息时点，最早下一交易日开盘执行。计算实现见factor.py；冻结模型和参数随目录提交。四个原手写因子保留函数默认值，历史调参结果须显式传入原回测配置，不能把默认值误认为历史最优参数。
