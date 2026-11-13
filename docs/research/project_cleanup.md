# 当前30品种回测清理记录

依据：2016—2025年固定30商品池、八种当前因子、统一执行时滞和成本。

已删除 18 个生成目录，约 1.74 MiB；另删除无对应 reversal 实现的遗留测试。

已删除目录：

- .pytest_cache
- .pytest_temp_fixed_carry_20261014
- .pytest_temp_rerun30_20261014a
- .pytest_temp_rerun30_20261014b
- .pytest_temp_rerun30_20261014c
- __pycache__
- china_cta\__pycache__
- china_cta\data\__pycache__
- china_cta\factors\__pycache__
- china_cta\formal_backtest\__pycache__
- china_cta\portfolio\__pycache__
- china_cta\research\__pycache__
- china_cta\validation\__pycache__
- scripts\__pycache__
- tests\__pycache__
- results\consistent_trend_63_126_252d_5r_2016_2025_v1
- results\oi_participation_trend_60d_2016_2025_v1
- swanlog\run-20260923_170515-ykd3ugn9

结果目录重命名：`curve_carry_4c_2016_2025_v1` → `fixed_maturity_carry_90_180d_2016_2025_v1`。

保留：30品种筛选证据、RQData行情缓存、八份唯一因子结果、季节性研究资料、正式回测及对账测试、环境和开发规范。它们有独立研究或复现用途。

未删除：旧 `.pytest_temp` 因 Windows 权限拒绝访问；不影响当前回测，后续测试使用独立临时目录。
