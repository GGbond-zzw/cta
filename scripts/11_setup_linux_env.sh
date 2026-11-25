#!/usr/bin/env bash
# Bootstrap a Linux Python environment for the RQData fetch stage.
#
# Why: on Windows hosts with Smart App Control enabled, the unsigned C
# extensions shipped by rqdatac (connection.cp311-win_amd64.pyd) and
# rqalpha_plus (daybar.cp311-win_amd64.pyd) are blocked by code-integrity
# policy. WSL2 runs a real Linux kernel, so the same code works there without
# weakening the Windows policy.
#
# Usage (inside WSL, from the repository root):
#   bash scripts/11_setup_linux_env.sh            # create .venv-linux and install deps
#   bash scripts/11_setup_linux_env.sh --recreate # rebuild the venv from scratch
#
# Then export the license once per shell (it is a network license):
#   export RQDATAC_CONF='tcp://<token>@rqdatad-pro.ricequant.com:16011'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv-linux"
PYTHON="${PYTHON:-python3}"

if [[ "${1:-}" == "--recreate" ]]; then
    rm -rf "${VENV}"
fi

if ! command -v "${PYTHON}" >/dev/null 2>&1; then
    echo "python3 not found; install it first: sudo apt-get install -y python3 python3-venv python3-dev" >&2
    exit 1
fi

if [[ ! -d "${VENV}" ]]; then
    "${PYTHON}" -m venv "${VENV}"
fi

"${VENV}/bin/python" -m pip install --upgrade pip wheel
"${VENV}/bin/python" -m pip install \
    "rqdatac>=3.6" \
    "pandas>=2.1" \
    "pyarrow>=14" \
    "numpy<2" \
    "scipy" \
    "matplotlib" \
    "optuna" \
    "h5py" \
    "pyyaml"

"${VENV}/bin/python" - <<'PY'
import pandas
import pyarrow
import rqdatac

print(f"rqdatac {rqdatac.__version__} | pandas {pandas.__version__} | pyarrow {pyarrow.__version__}")
PY

cat <<'MSG'

Environment ready: .venv-linux

Next steps (inside WSL, from the repository root):

  1. export RQDATAC_CONF='tcp://<token>@rqdatad-pro.ricequant.com:16011'
     (use the same value your Windows shell has in $env:RQDATAC_CONF)

  2. .venv-linux/bin/python scripts/10_fetch_research_inputs.py \
         --start 2016-01-01 --end 2026-11-01 --refresh

     This writes data/research_inputs/cta_alpha22/*.parquet with a native
     `open` column, so scripts/12_add_open_from_bundle.py becomes optional.

  3. On the Windows side, re-run the pipeline:

     <conda-env-python> scripts\50_backtest_portfolio.py \
         --start 2025-01-01 --end 2026-10-31 --vol-target 0.2 --run-name equal_weight_4f

MSG
