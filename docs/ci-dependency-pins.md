# CI Python dependency pins

`requirements-ci.txt` holds the exact `numpy==` and `pytest==` versions that
both CI install sites (`tests` and `rtl-sim` in `.github/workflows/ci.yml`)
install with `python3 -m pip install --quiet -r requirements-ci.txt`.
Contract test: `tests/test_ci_dependency_pins.py`.

**What this is and is not.** It makes the CI environment reproducible so a new
PyPI release cannot change test numerics with no repo change. It establishes
nothing about RTL exactness, model-vs-reference agreement, or preset quality.
Transitive pytest dependencies (pluggy, iniconfig, packaging, ...) are not
pinned; they do not affect numerics.

## Why numpy 2.4.2

- numpy >= 2 is required: the float32 `power` / NEP 50 rounding hazard
  recorded at `.github/workflows/ci.yml` (comment above the install in the
  `tests` job) is why a numpy-optional fallback was rejected, and the model's
  bit-exact tests depend on numpy float32 behavior.
- 2.4.2 is the version stamped by the most recent manually replayable record
  (`reports/spectral-corr-per-leaf-migration`), whose leg-2 replay is
  environment-sensitive; it supports CPython 3.12.
- No `reports/` stamp is a live CI obligation (`docs/numpy-stamp-inventory.md`),
  so stamps did not decide the pin and no test compares stamps to it.
- The oracle runtime (`oracle/manifest.json`, numpy 1.26.4, CPython 3.11.16)
  is a separate live pin and is unchanged.

## Bump procedure

1. Edit `requirements-ci.txt` only (exact `==` pins). Do not edit `reports/`
   or any byte-frozen source (`docs/byte-frozen-sources.md`).
2. Run the full suite on CPython 3.12 with the new pins (and the rtl-sim job).
   A test failure here is the expected visible signal of a numeric change.
3. Re-run `python3 tools/numpy_stamp_inventory.py --check`; it must still pass.
4. If you want to regenerate any manual evidence (notably
   `tools/spectral_corr_per_leaf_checks.py` leg 2 replay), do so as its own
   change under that record's procedure; see the inventory for which records
   are environment-sensitive. Do not regenerate as part of a pin bump.
5. A version difference between a committed stamp and the pin does not by
   itself make a PASS record STALE; only a failed re-derivation does.
   Report un-run checks as NOT_RUN.
