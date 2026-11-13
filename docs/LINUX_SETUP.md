# Fetching data from Linux (WSL2)

## Why

On this host the Windows code-integrity policy (**Smart App Control**, registry
`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState = 1`)
blocks unsigned native extensions. The research pipeline itself is pure Python,
but the RQData fetch stage imports `rqdatac`, whose `connection*.pyd` is
unsigned, so stage 0 cannot run natively:

```
Code Integrity determined that a process (...\envs\cta\python.exe) attempted to
load ...\rqdatac\connection.cp311-win_amd64.pyd that did not meet the Enterprise
signing level requirements or violated code integrity policy
(Policy ID:{0283ac0f-fff1-49ae-ada1-8a933130cad6}).
```

WSL2 runs a real Linux kernel, and Smart App Control does not apply inside it.
This keeps the Windows policy intact: only the data-fetch step moves to Linux.

## One-time setup (needs administrator, reboots once)

```powershell
wsl --install -d Ubuntu
```

Reboot, open "Ubuntu" from the start menu, create the Linux user, then from the
repository root **inside WSL**:

```bash
sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-dev
bash scripts/11_setup_linux_env.sh
```

The project is visible unchanged at `/mnt/c/Users/ct/Desktop/python/CTA/china-cta`,
so no file copying is needed.

## Licence

RQData here uses a **network licence** (`tcp://...@rqdatad-pro.ricequant.com:16011`),
which is not bound to the Windows installation, so it works from WSL. Export the
same value the Windows shell has:

```bash
export RQDATAC_CONF='tcp://<token>@rqdatad-pro.ricequant.com:16011'
```

To avoid retyping it, append that line to `~/.bashrc` (it contains a token, so do
not commit it anywhere).

## Refresh the inputs with a native open column

```bash
cd /mnt/c/Users/ct/Desktop/python/CTA/china-cta
.venv-linux/bin/python scripts/10_fetch_research_inputs.py \
    --start 2016-01-01 --end 2026-11-01 --refresh
```

Stage 0 now requests `open` together with `close/high/low/volume/open_interest`,
so the resulting `continuous_prices.parquet` already carries the column the
execution engine fills on. After this, `scripts/12_add_open_from_bundle.py` is a
fallback for hosts that cannot reach RQData, not a required stage.

## Back on Windows

The tuning, correlation and backtest stages do not import `rqdatac`, so they keep
running in the conda environment:

```powershell
& "C:\Users\ct\miniconda3\envs\cta\python.exe" scripts\32_verify_tuning_outputs.py
& "C:\Users\ct\miniconda3\envs\cta\python.exe" scripts\50_backtest_portfolio.py `
    --start 2025-01-01 --end 2026-10-31 --vol-target 0.2 --run-name equal_weight_4f
```

## Notes

* `/mnt/c` I/O is slower than the Linux filesystem, but the inputs are only a few
  hundred MB; readability matters more than speed here.
* Keep the shell scripts LF-only. If you edit them on Windows, set
  `git config core.autocrlf input` or they will fail with `bad interpreter`.
* `rqalpha_plus` stays Windows-only and unused: the research pipeline never
  imports it. Only `china_cta/formal_backtest` and its test need it.
* If you would rather keep everything on Windows, the alternative is turning
  Smart App Control off (irreversible without reinstalling Windows).
