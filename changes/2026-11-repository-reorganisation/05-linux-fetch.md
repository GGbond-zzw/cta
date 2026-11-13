# 5. Data fetch from Linux

`rqdatac` cannot be imported on this Windows host: Smart App Control is enabled
(`VerifiedAndReputablePolicyState = 1`) and blocks the unsigned extension
`rqdatac/connection.cp311-win_amd64.pyd` under policy
`{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. The same policy also blocks
`rqalpha_plus/bundle/daybar*.pyd`, `rapidjson*.pyd` and third-party trading
terminals DLLs, so this is an environment-level restriction, not a packaging bug.

Chosen fix: run only stage 0 under WSL2, leaving the Windows policy untouched.

Added:

| file | purpose |
| --- | --- |
| `scripts/11_setup_linux_env.sh` | creates `.venv-linux` and installs rqdatac/pandas/pyarrow/... |
| `docs/LINUX_SETUP.md` | install, licence, refresh and verification steps |
| `scripts/10_fetch_research_inputs.py` | now requests `open` together with the other price fields |

Consequences:

* `continuous_prices.parquet` gets a native `open` column from RQData, so
  `scripts/12_add_open_from_bundle.py` becomes a fallback instead of a required
  stage.
* Tuning, correlation and backtest stay on Windows; they never import `rqdatac`.
* `.venv-linux/` must stay out of git (covered by `.gitignore`).

Verified on 2026-11-12: WSL Ubuntu-24.04, rqdatac 3.8.2, `--refresh` run to
2026-11-01 produced 70,782 continuous rows (2016-01-04..2026-10-30) with zero
missing `open` values; daily returns over the 2016-2025 overlap are bit-identical
to the previous cache (corr 1.0, max |diff| 0), so only the price *level* is
re-based on each refresh. `--end` now defaults to today.
