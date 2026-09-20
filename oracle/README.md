# Native oracle (SXT-010)

This directory pins and drives the **external** native Surge XT oracle — the
executable sound reference for the whole project. The engine (GPL-3.0-or-later)
is *not* part of this repository; only pins, harness scripts, and evidence are.

## Layout

| File | Role |
|---|---|
| `manifest.json` | Machine-readable pin: engine commit, all submodule SHAs, toolchain, 48 kHz runtime, scheduling/reset/tuning/randomness semantics, environment identity. |
| `fetch-and-build.sh` | Drift gate: refuses engine HEAD drift, any submodule SHA drift, dirty engine trees, then configures and builds `surgepy` + `surge-testrunner` and smoke-imports the binding. |
| `oracle_common.py` | Shared harness helpers (pinned-python re-exec, engine env, blob SHA-1 verification, WAV writer). |
| `run_load_report.py` | Loads all 3,561 census entries into the pinned engine at 48 kHz; writes `reports/sxt-010/load-report.csv` and `load-summary.json`. |
| `capture_first_note.py` | Renders one note of a simple factory preset through the real engine; writes `reports/sxt-010/first-capture/`. |

## Reproduce

```sh
# 1. Engine checkout (external, GPL — kept out of this repo)
git clone --recurse-submodules https://github.com/surge-synthesizer/surge \
    /Users/joseph/dev/surge-xt-oracle/surge
git -C /Users/joseph/dev/surge-xt-oracle/surge checkout 58914e59c608ed4384ba6002e44c3465c58b2e71
git -C /Users/joseph/dev/surge-xt-oracle/surge submodule update --init --recursive

# 2. Verify pins and build (any drift aborts with a clear error)
oracle/fetch-and-build.sh            # add --verify-only to stop after verification

# 3. Load report over the whole census (3,561 entries, 48 kHz)
oracle/run_load_report.py

# 4. First-note capture (own render, mono 16-bit, ~2 s)
oracle/capture_first_note.py
```

Environment overrides: `ORACLE_SURGE_DIR`, `ORACLE_MANIFEST`,
`ORACLE_PYTHON`, `ORACLE_BUILD_DIR`, `ORACLE_JOBS` (see `fetch-and-build.sh`).

## Semantics pinned by this oracle

- Sample rate 48 kHz; compiled block size 32 (`SURGE_COMPILE_BLOCK_SIZE`
  default); tempo 120; `SURGE_DATA_HOME` points at the pinned tree's
  `resources/data`, so assets resolve inside the pinned checkout only.
- Tuning: engine default 12-TET, no SCL/KBM/MTS override. MPE off.
- Randomness: the harness never seeds or alters engine RNG; repeatability of
  the note capture is measured and reported, not assumed.
- Load semantics: `SurgeSynthesizer.loadPatch()` (the native loader with all
  migrations) is authoritative for normalized state; `.fxp` files are never
  repaired. Failures are recorded, never silently dropped.

## Licensing

Harness scripts are original to this repository (Apache-2.0 per `LICENSE`).
They import the external GPL-3.0-or-later engine at runtime and copy no Surge
source, tables, assets, or preset payloads into this repository. The WAV in
`reports/sxt-010/first-capture/` is this project's own render of a loaded
preset (small, mono 16-bit), not redistributed upstream content. See
`manifest.json` → `licensing_note`.
