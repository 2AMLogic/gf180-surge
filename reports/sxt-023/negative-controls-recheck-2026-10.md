# SXT-023 negative-control and RTL re-check (issue #16) — run 2026-11-02

Evidence/regression re-run only. No model, RTL, budget, fixture or tool was
changed. Source tree: `main` @ `27b74f7` (contains #452 comparator refusals and
the #508 reference contract). Host: linux x86_64 dispatch worker, Icarus Verilog
13.0, Verilator 5.050 (`--build-jobs 2`). No Surge oracle on this host; nothing
was rendered. All new artifacts: `artifacts-followup/recheck-2026-11/`.

Three things are kept separate below and no row is inferred from another:
**(A)** RTL-vs-frozen-model (must be exact), **(B)** controls that must fail,
**(C)** model-vs-reference, which is only *cited*, not re-claimed.

## A. RTL vs frozen model (current `tools/compare_rtl_model_fx.py`)

| Row | Status | Evidence |
|---|---|---|
| Verilator full-length, Delay metallic (8,550 compared blocks, 547,200 outputs, 272 checkpoints / 8,704 fields) | PASS, 0 mismatches | `verilator-full-metallic.json`; raw trace sha256 `643af13b...` = committed record |
| Verilator full-length, Delay dexie (547,200 outputs, 136 / 4,352) | PASS, 0 mismatches | `verilator-full-dexie.json`; trace sha256 `56b0440e...` = committed record |
| EQ RTL fm_bass_1, iverilog (canonical), full length (547,200 outputs, 136 checkpoints / 4,080 fields) | PASS, 0 mismatches | `iverilog-full-eq-fm_bass_1.json` |
| EQ RTL fm_bass_1, Verilator, full length | PASS, 0 mismatches | `verilator-full-fm_bass_1.json` |
| sim-vs-sim, metallic first 3,200 blocks (2,825 compared; coverage `partial` by construction) | PASS in both simulators; raw traces byte-identical, sha256 `4a55567d...` | `simvssim-medium-{iverilog,verilator}-metallic.json` |
| Delay iverilog full-length | not re-run (recorded PASS in #508; unchanged per issue) | `reference-contract.md` section 4 |

The pre-#452 records counted `blocks_compared` as the window bound (3,200);
the current comparator reports blocks actually compared after the 375-block
pre-roll (2,825). Same 180,800 outputs / 92 checkpoints / 2,944 fields.

## B. Negative controls (each must fail the check it targets)

| Control | Status | Evidence |
|---|---|---|
| Baseline for NC-a/NC-e: unmutated `tb_fx.sv`, same 500-block window | PASS, 0 mismatches (so a FAIL below is caused by the mutant) | `nc-baseline-unmutated-500.json` |
| NC-a shared line (`tb_fx_shared_line.sv`, metallic, 500 blocks) | FAIL as required: 26 mismatches, first at block 375 d0 line hash / `ext_reads` doubled (288,768 model vs 577,536 RTL) and d1 untouched (0) | `nc-a-shared-line.json` |
| NC-e one-digit mutant (`tb_fx_mutant.sv`, metallic, 500 blocks) | FAIL as required: 26 mismatches, first at block 375 biquad state (`hp0` -16530860432502 vs ...797) | `nc-e-comparator-mutant.json` |
| NC-b nearest-neighbour model, metallic, `--per-channel-budgets` | FAIL as required: mono max/spectral_corr, all six L/R legs, tail gate (L -13.51 dB, R -14.49 dB vs -20) | `nc-b/nc-b-metallic.json` |
| NC-b nearest-neighbour model, dexie, `--per-channel-budgets` | FAIL as required, only on the per-channel leg: mono budgets all pass (the known non-discrimination), L/R max_abs and spectral_corr fail; tail gate not tripped | `nc-b/nc-b-dexie.json` |
| NC-b discrimination baseline: frozen model, same comparator and flags, both fixtures | PASS (both) — the failing legs above are not comparator artifacts | `nc-b/baseline-frozen-{metallic,dexie}.json` |
| NC-c max-feedback corner (model-side) | PASS bounded: max 1.44999, 0 saturated of 111,360 samples | `nc-c-maxfb-corner.json` |
| NC-d bypass (model-side, fm_bass_1) | PASS: 0 mismatches / 571,200 samples; discrimination check (A = 1.0 - 1 LSB) fires with 74,864 mismatches | `nc-d-bypass.json` |

No control failed to fire. NC-a/NC-e used `--max-blocks 500` as in the
2026-10-09 records, so only 5 / 2 blocks are compared before the first
divergence region; this is partial coverage, stated, and sufficient because the
control must merely fail the check.

## C. Other required rows

| Row | Status | Evidence |
|---|---|---|
| ext-mem traffic re-derived (dexie) | PASS: 6,854,400 reads / 571,200 writes = 8,925 blocks x 768 / x 64 (24 reads + 2 writes per sample per instance). Model-side counters only; no RTL, latency or hardware measurement | `ext-mem-traffic-dexie.json`; `tests/test_sxt023_delay_traffic_basis.py` PASS |
| Word-length record vs source | CONFIRMED, no correction: `delay_model.py` `A_FMT` Q10.21, `G_FMT` Q13.18, `C_FMT` Q24.43, sinc Q2.29 with FIRipol_M 256 / N 12 (`sinc_table.py`), float32-grid lag (RNE at 24 significant bits), round-half-up elsewhere. Matches `followup.md` 2026-10-09 section | n/a, no new `followup.md` section needed |
| Targeted tests | PASS: 69 passed (`test_sxt023_delay_traffic_basis`, `test_compare_rtl_model_fx_window`, `test_byte_frozen_sources`, `test_frozen_artifact_basis`) | local run, single process |

Regenerating NC-c, NC-d and ext-mem through their tools rewrote the existing
`*-rerun-issue16.json` files byte-identically (`git status` clean for tracked
files); the new copies in `recheck-2026-11/` are the dated records.

## What this does not establish

- **Darwin-reference agreement** (claim 2): not re-run. Cited only from
  `reference-contract.md` sections 2 and 4 (PASS on the committed
  darwin-arm64 fixtures, re-run 2026-10-20). The NC-b "frozen model passes"
  baseline compares the frozen model to those same committed fixtures with the
  stricter per-channel leg; it is a control, not a new fidelity claim, and the
  budgets remain PROPOSED / PENDING-FREEZE.
- **Linux x86_64 variance**: unchanged and explicit. The unfused-lag engine
  build still FAILs the d(t) probe for the fused model
  (`artifacts-followup/dt-probe/`); it is not reclassified PASS and not a second
  required behavior. Not re-measured here.
- **Substitute-reference qualification** (contract section 3): NOT_RUN. No
  oracle on this host; no new acceptance fixture was rendered.
- **Darwin module hash / FP flags / direct d(t)** (contract 1.2): out of scope,
  unproved.
- Controls NC-c and NC-d are model-side only. No synthesis, place-and-route,
  timing, hardware, preset-support or musical-quality claim is made.
- `EVIDENCE.md` (sha256-pinned) was not edited.
