# 4. Documentation and cleanup

## Documentation

* `README.md` rewritten from the old 37 KB research log into a project front
  page: the four sleeves, execution conventions, quick start, layout, verified
  numbers, environment caveats.
* `docs/PIPELINE.md` new: the numbered pipeline with commands, parameters and
  artifact descriptions.
* `docs/FACTOR_CLASSIFICATION.md` new (replaces `docs/factor_classification.md`):
  the qualified book, the retired factors, and the data-limited ones.
* `docs/DATA.md` new: the six tables, their sources, the bundle rebuild, and the
  chaining/dominant-contract caveats.
* `docs/RESEARCH_NOTES.md` new: index of the historical notes.
* `docs/research/` holds the ten historical notes moved out of `docs/`.

## Cleanup

* Deleted the root-level `.pytest_temp*` directories and `swanlog`.
* Deleted stale `__pycache__` directories inside `china_cta/` and `tests/`.
* Added `scripts/12_add_open_from_bundle.py` after discovering that the refreshed
  research inputs (2016-01-04 .. 2026-10-30) were written by a fetch that does not
  produce an `open` column, which would have broken the documented default
  backtest. The script restored the column for the whole history.
* `scripts/10_fetch_research_inputs.py` and the three research scripts that
  import `basis_momentum_test` received a `sys.path` shim, because their sibling
  modules now live in `scripts/research/`.

## Known issues left untouched

* `rqalpha_plus` import failure on this host (application control policy), which
  affects `china_cta/formal_backtest` and `tests/test_formal_backtest.py` only.
* `rqdatac` connection blocked on this host, so stage 0 must be run on a machine
  with RQData access, or replaced by the bundle rebuild stage.
* `pandas` lacks `pytables`; the bundle is read with `h5py`.
