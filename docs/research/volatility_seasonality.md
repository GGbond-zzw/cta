# 波动率月份效应（Maitra 2018 的可计算部分）

`scripts/identify_seasonality_papers.py` 使用已有 `monthly_volatility.csv` 的月度日收益均方根波动率。每个品种按日历月分组，以 ANOVA 和 Kruskal–Wallis 检验月份差异，并比较历年同月均值与总体均值的样本外预测误差。结果覆盖 `volatility_by_product.csv`；`volatility_by_year.csv` 现在保存各品种年度平均对数波动率。

原文还在 GARCH／EGARCH 方差方程中加入月份虚拟变量、结构断点变量和现货—期货波动溢出项。当前输入没有对应的现货序列，脚本也尚未拟合 GARCH／EGARCH，所以这里只复现“月份波动效应”的识别部分。`monthly_volatility.csv` 是保留的输入数据，不由此脚本重写。
