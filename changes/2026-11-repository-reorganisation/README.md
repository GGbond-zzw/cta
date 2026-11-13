# 2026-11 repository reorganisation

Goal: turn the working directory into a self-contained, GitHub-ready project in
which the only qualified book is the four next-open sleeves, and every step of
the runnable path is a numbered script with documented defaults.

Read the five notes in order:

1. `01-factor-reclassification.md` - which factor modules moved, and why the
   qualified set shrank from seven to four.
2. `02-script-pipeline.md` - the old `scripts/` contents versus the numbered
   pipeline, including the new bundle rebuild stage.
3. `03-tests-and-results.md` - test directories, renamed test files, and how the
   tuning result directories were regrouped.
4. `04-docs-and-cleanup.md` - documentation set, deleted caches, and the
   remaining known issues.
5. `05-linux-fetch.md` - why `rqdatac` is blocked on this Windows host and how
   stage 0 runs under WSL2 instead.

`file-moves.csv` is generated from the reorganisation ledger and lists every
file that was created, moved, rewritten or deleted, with the command or reason.
