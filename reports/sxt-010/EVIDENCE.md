# SXT-010 evidence record — pinned native oracle

Branch: `loom/sxt-010-native-oracle` · Issue: #5 (SXT-010) · Date: 2026-09-20

Engine (external, GPL-3.0-or-later): `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
at `/Users/joseph/dev/surge-xt-oracle/surge`, clean tree, all pinned submodules verified.
Oracle build: `surgepy` + `surge-testrunner` (Release, Ninja), engine self-report
`1.4.HEAD.58914e59c`, 48 kHz, block size 32.

**Claim discipline:** this record establishes *loader coverage* and *environment identity*
only. Load success is not audio-support, not fidelity, and not preset quality. Census
counts establish no audio-support claim. No listening evaluation has occurred.

## Acceptance checklist (issue #5)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Manifest records exact commit, all submodule pins, toolchain/runtime, sample rate, scheduling, reset, tuning, randomness handling | **PASS** | `oracle/manifest.json` — engine commit + date + archive URL; 22 top-level submodule pins (identical to `corpus/census-v0.1/source-lock.json`) + 5 nested submodule SHAs observed on disk; toolchain (macOS 26.5.1 arm64, Xcode 26.6, Apple clang 21.0.0, cmake 4.4.3, ninja, git 2.55.0, python 3.11.16/numpy 1.26.4); 48 kHz; block size 32 (compiled `SURGE_COMPILE_BLOCK_SIZE` default); tempo 120; reset policy (`allNotesOff` before each load; harness modifies no other engine state); tuning = engine-default 12-TET, no SCL/KBM/MTS override, MPE off; randomness = never seeded, repeatability measured. Asset root pinned via `SURGE_DATA_HOME` to the pinned tree's `resources/data`. |
| 2 | Fetch/build script rejects upstream or submodule drift with a clear error | **PASS** | `oracle/fetch-and-build.sh`; transcript `reports/sxt-010/NEGATIVE-CONTROLS.txt`: wrong engine commit → refused exit 2; flipped submodule SHA (libs/JUCE) → refused exit 2; modified tracked engine file → refused exit 2 (stronger than required); restored tree → verify passes exit 0. The script never follows upstream silently. |
| 3 | Load report covers all 3,561 entries with per-entry status; failures recorded, never silently dropped | **PASS** | `reports/sxt-010/load-report.csv` — 3,561 data rows, path list exactly equal (set and order) to `corpus/census-v0.1/corpus-manifest.json`; 641 factory + 2,920 contributor (matches census denominators). Every row carries status, detail, elapsed_ms, engine commit, sample rate. Each file's on-disk git blob SHA-1 and size were re-verified against the census during the run (any mismatch aborts the run). Summary `reports/sxt-010/load-summary.json`: **ok 3561, failures 0**. |
| 4 | `Percussion/Snare Tight.fxp` resolved by native behavior (not repaired) | **PASS** | `load-summary.json` → `snare_tight.native_verdict = "loads_natively"`, detail empty. The file was loaded by the native loader (`SurgeSynthesizer.loadPatch`) byte-identical to the pinned tree (blob verified). The static parser's rejection is superseded by native behavior; the file was not modified. Independently reproduced under the python3.14 build as well. |
| 5 | One note captured through the real engine, reproducible under the recorded environment | **PASS** | `reports/sxt-010/first-capture/first-note.wav` (mono 16-bit, 96,000 smp, 48 kHz, 2.000 s, 192,044 bytes, sha256 `6c46343aa05a820e3616d65ca3046c5448d33edd4424ab8f4301d0d888541c63`) + `first-note.json`. Preset `resources/data/patches_factory/Basses/Sub 4.fxp` (census blob `47d1db8a36d4ff57fa260b927a31f7fb199f755f`, re-verified at capture time; chosen from census columns: Sine oscillator, Single scene, 0 non-Off FX, 0 modroutings, no embedded wavetable). Note 60, velocity 100, channel 0, detune 0, held (no note-off — tails are an SXT-012 concern). Repeatability **measured**: two renders in fresh engine instances are bit-identical (max abs diff 0.0). Reproducibility statement is scoped to the recorded environment in `oracle/manifest.json` (`environment` block); other hosts must re-run the harness rather than assume byte equality. |
| 6 | Negative control: different commit/submodule state is detected and refused | **PASS** | Same transcript as item 2 (`NEGATIVE-CONTROLS.txt`): controls A (commit), B (submodule), C (dirty tree) all demonstrably fail the gate they target, then the restored state passes. |

## Runtime selection record (preferred surgepy path — achieved)

- Preferred path used: **surgepy python binding**, built from the pinned tree
  (`build-py311/src/surge-python/surgepy.cpython-311-darwin.so`), driven by
  `oracle/run_load_report.py` and `oracle/capture_first_note.py`.
- Interpreter choice: python3.11.16 (numpy 1.26.4 available). python3.12/3.13 lack a numpy
  runtime here. python3.14 was **not** excluded by build failure: a full surgepy module
  build from the same pinned tree (`build-py314`) succeeded and imports with identical
  engine version and Snare-Tight load behavior (see `pybind11-python314-compile-probe.txt`
  for the header-level probe; both probes compile). 3.11 was kept for numpy availability
  and single-runtime consistency of the evidence.
- Environment pitfall documented: pybind11's default new-style FindPython resolves a broken
  anaconda interpreter (`/opt/homebrew/anaconda3`, missing include dir) even with
  `Python_ROOT_DIR`/`Python_EXECUTABLE` hints; transcript
  `findpython-interpreter-resolution.txt`. Workaround (build config only, no engine source
  change): `-DPYBIND11_FINDPYTHON=OFF` + explicit `PYTHON_EXECUTABLE`.
- Build-config finding: with `SURGE_BUILD_XT=OFF`/`SURGE_BUILD_FX=OFF`, configure fails in
  `src/cmake/pluginval.cmake` (unguarded AU pluginval targets). Worked around by
  configuring with the default XT/FX targets and building only the needed targets. No
  engine source was modified anywhere in this work.
- `surge-testrunner` also built from the pinned tree as a cross-check target
  (`build-py311/src/surge-testrunner/surge-testrunner`); its use for fixture rendering is
  future work (SXT-012), not exercised here.

## Load-run operational note

One earlier load attempt was interrupted (background process reaped by the session, not an
engine fault; entry `Landosonic/Pads/Unison Swell 1.fxp` loads fine on resume). The final
clean run above executed start-to-finish in one process (~42 s wall). The harness flushes
per-entry and supports `--start N` resume so a hard engine fault cannot silently drop
entries.

## Licensing / provenance

- `oracle/*` scripts: original to this repository, Apache-2.0 per `LICENSE`. No
  Surge-derived source, tables, assets, or presets copied into this repository. The
  harness imports the external GPL engine at runtime only.
- `first-note.wav` is this project's own render of a loaded preset (mono 16-bit, ~2 s,
  192 KB) — our render output, not redistributed upstream content.
- `surge-python-demo` / `surge-python` (GPL) were not consulted or copied; only the
  in-tree pinned `surgepy` binding and its test file were read for API usage
  (`createSurge`, `loadPatch`, `processMultiBlock`).

## Explicitly NOT established by this work

- NO_VERDICT on sound fidelity, preset quality, or musical usefulness — no listening
  record exists.
- NOT_RUN: normalized patch-graph export (SXT-011), render fixtures/repeatability package
  (SXT-012), effects analysis, wet-path coverage, polyphony/tail/reset behavior under
  performance, RTL work — all out of scope for SXT-010 per the issue's non-goals.
- Load `ok` means the native loader accepted the file at 48 kHz; it does not mean the
  preset's sound is reproduced by anything in this project.
- `oracle/manifest.json` runtime block records block size 32 and default scheduling as
  built; a full behavioral characterization of event scheduling/reset under every control
  input is future fixture work (SXT-012), so those manifest fields are declarations of the
  harness/engine configuration, not measured behavior under all inputs.
