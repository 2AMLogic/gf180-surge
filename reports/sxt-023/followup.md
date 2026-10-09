# SXT-023 follow-up record — 2026-09-20 (PR "SXT-023 follow-up")

Branch `loom/sxt-023-delay-followup` · Issue #16 (OPEN; delay leaf) ·
Follows PR #44. This record APPENDS to `EVIDENCE.md` (which is preserved
verbatim); items below supersede the corresponding FAIL/OPEN rows where
stated. Claim discipline unchanged: no preset-support, no musical-quality,
no synthesis/hardware claim.

## 1. Delay RTL-vs-model exactness — now PASS (was A1 FAIL)

Root causes found and fixed in `rtl/effects/tb_fx.sv` (the EQ path of the
same tb was already exact; all defects were delay-specific; each confirmed
by per-stage bisection against the frozen model):

1. `LPIT_r` constant was the double complement `to_q(1 − f32(0.0001))`
   (0x7FFCB923A40) instead of the float32 pair value
   `f32(1.0f − 0.0001f)` → 0x7FFCB900000. The wrong pair summed to exactly
   2^43 and erased the engine's −64-ulp lag drift (dexie `tlv`/`trv`
   checkpoint drift, ±5 LSB class).
2. Delay sinc MAC rescale was `(acc + 2^20) >>> 22`; the frozen convention
   on the Q(21+29) accumulator is `(acc + 2^28) >>> 29` — a 128× tap-scale
   error (masked in the old artifacts by defects 3/4 pushing energy into
   saturation).
3. Metallic send return added `rl × send-INPUT`; the frozen model returns
   `insert_out + rl × send-FX-OUTPUT`. With the send delay at 100% mix over
   an empty line this showed as model/16.2 = send-gain on the dry path.
4. Width mid/side halving used `>>> 1` (floor) on negative sums; the frozen
   convention is `−(|d| >> 1)` (round-half-up): −1 LSB bias on odd negative
   sums.
5. Line-hash accumulate mixed `longint unsigned` with 32-bit signed words
   (zero-extended per the LRM unsigned context): every negative write delta
   inflated by 2^32.
6. Delay sinc accumulator widened to 64-bit (exact products).

Evidence (all committed under `artifacts-followup/`):

| run | scope | result |
|---|---|---|
| smoke (iverilog) | metallic + dexie, 240 settle + 16 render blocks = 8,192 samples (`tools/smoke_fx_exactness.py`) | PASS — 0 mismatches on 1,024 outputs + all checkpoint fields (incl. per-instance line hashes) |
| canonical (iverilog, full length) | metallic: 8,790 blocks, 547,200 outputs + 272 checkpoints / 8,704 fields | **PASS — 0 mismatches** (`exactness-followup-delay-metallic.json`) |
| canonical (iverilog, full length) | dexie: 8,790 blocks, 547,200 outputs + 136 checkpoints / 4,352 fields | **PASS — 0 mismatches** (`exactness-followup-delay-dexie.json`) |
| Verilator cross-check | metallic, 3,200 blocks = 102,400 samples, Verilator 5.052 | PASS + raw traces **byte-identical** to iverilog (same sha256) (`verilator-equivalence-medium.json`); iverilog remains canonical |

Coverage note: the two canonical runs match the EQ leaf's coverage class
(547,200 output samples each). `tools/compare_rtl_model_fx.py` gained
`--art-dir`, `--sim`, `--rtl-trace` (defaults unchanged).

## 2. Negative controls re-derived against the passing baseline

`tb_fx_shared_line.sv` and `tb_fx_mutant.sv` are regenerated from the fixed
tb (same mutations as PR #44). This resolves the review caveat that NC-a was
confounded by the failing baseline:

* **NC-a (shared line)**: FAIL — d0 read/write counters doubled (er 370,176
  = 2×185,088), d1 zeroed: the comparator now discriminates shared-state
  specifically on the delay path (`nc-a-followup-shared-line.json`).
* **NC-e (comparator mutant)**: FAIL at block-240 biquad lags, same numbers
  as PR #44 (`nc-e-followup-comparator-mutant.json`).

## 3. NC-b provenance — committed (was: artifacts not in repo)

`tools/run_ncb_nn_model.py` runs the committed NN negative-control model
over the committed dry fixtures and compares against the committed engine
wet buses; results reproducible from committed inputs only, no engine at
run time:

* metallic: max 132,177 / rms 15,382 LSB (−36.7 dBFS) — FAIL vs proposed
* dexie: max 41,068 / rms 4,473 LSB (−47.4 dBFS) — FAIL vs proposed

These supersede the unreproducible A7 quotes; the metallic/dexie numbers
match the judge's independent rerun in the PR #44 review. The recorded
caveat stands: while the frozen delay model itself misses the proposed
budgets (item 4), NC-b cannot discriminate frozen-vs-NN at budget
granularity; its gross-failure detection is not affected.

## 4. Model-vs-engine budget miss — diagnosis delivered (SXT-017 input)

Reproduced (−33.5 / −44.2 dBFS vs −46 proposed) and isolated:
`delay-budget-diagnosis.md` + `tools/diagnose_delay_budget.py` +
`tools/diagnose_delay_engine_probe.py` + artifacts under
`artifacts-followup/budget-diagnosis/`. Headlines:

* The PR #44 float32-lag-staircase hypothesis is **refuted**: emulating
  float32 lag arithmetic/storage and float32 sinc tables changes nothing.
* With LFO depth 0 on BOTH sides: dexie −109.6 dBFS (floor, max 41 LSB,
  corr 1.0000); metallic −53.3 dBFS — the **LFO term's presence** in the
  delay-time path is the dominant mechanism. The error is invariant to LFO
  rate (24× slower) and contribution scale (±10%), i.e. presence-class, not
  trajectory/word-length class.
* The static delay path meets the proposed −46 dBFS budget on both presets.
* Metallic's bounded static residual (−53.3, corr 0.9998) is declared open.
* No budget constant, frozen model file, or committed fixture was modified.

SXT-017 options and predicted effects are in the diagnosis note §3
(scope exclusion / impulse-probe micro-leaf / two-tier budget freeze).

## 5. Status after this follow-up

| item | before | after |
|---|---|---|
| Delay RTL-vs-model exactness | FAIL (open tb defect) | **PASS** (smoke + full-length canonical, iverilog; Verilator equivalence documented) |
| EQ RTL-vs-model / model-vs-engine | PASS | PASS (untouched; EQ suites not rerun) |
| Delay model-vs-engine budgets | FAIL (mechanism unknown) | FAIL (mechanism isolated to the LFO term's presence; float32-lag hypothesis refuted; routed to SXT-017 with options) |
| NC-b provenance | missing artifacts | committed runner + artifacts |
| NC-a discrimination | confounded by broken baseline | discriminating against passing baseline |

Still NOT established: any preset-support or musical-quality claim; delay
model-vs-engine within the proposed budgets (routed to SXT-017); any
synthesis/timing/hardware claim.

## Superseded by #110 (issue #164, 2026-10-01)

The `corr 1.0000` / `corr 0.9998` figures quoted in §4 above are from
`tools/diagnose_delay_budget.py`/`tools/diagnose_delay_engine_probe.py`
diagnostic renders under `artifacts-followup/budget-diagnosis/`, which are
"regenerable via the documented command; not committed"
(`delay-budget-diagnosis.md` §4) — they predate PR #166 (issue #110,
merged 2026-09-30)'s shared full-scale log-floor `spectral_corr` definition
and are superseded in the same sense as every other pre-#110 value in this
repository, but because they were never committed JSON artifacts they are
not part of `reports/spectral-corr-fs-floor/artifacts/regrade-ledger.{txt,json}`
and have no recorded post-#110 re-measurement. Re-running the cited tools
would produce the current numbers; nothing here is a frozen or re-verified
claim either way.

## Issue #16 increment (2026-10-08): word-length assumption record; engine probe BLOCKED

Scope of this section: deliverable 3 of the revised issue #16 (record the
word-length assumption for #12's cost-closure rerun) and an honest status for
deliverables 1-2. No model, RTL, fixture, or budget was changed.

### Word-length assumption this leaf was built against

Re-confirmed against `model/effects/delay/delay_model.py` (header, lines
47-49) and `model/effects/qmath.py` on this date:

| item | format / value |
|---|---|
| audio words and delay lines | Q10.21, signed 32-bit (LSB 2^-21) |
| sinc taps (table) | Q2.29, signed 32-bit |
| block-rate gain ramps | Q13.18, signed 32-bit |
| biquad, delay-time (lag), LFO state | Q24.43, signed 64-bit |
| sinc interpolator | FIRipol_N = 12 taps (`FIRIPOL_N`), FIRipol_M phases (`FIRIPOL_M`) |
| rounding | round-half-up to the target format; exact products |
| RTL sinc accumulator | exact 64-bit (Q10.21 x Q2.29 = 50 fractional bits, rounded to Q10.21) |
| line allocation | `MAX_DELAY + FIRIPOL_N` words per channel |
| ext-mem traffic per instance | 24 line reads + 2 line writes per sample = 768 reads + 64 writes per 32-sample frame (model `ext_reads += FIRIPOL_N * 2` per sample and `ext_writes += BLOCK * 2` per block in `DelayEffect.process_block`; matches the `artifacts/ext_mem_traffic.json` counters 6,750,720 reads / 562,560 writes = 8,790 blocks x 768 / x 64) |

Note: the "24 line reads + 64 writes per frame = 88 accesses/frame" wording
in `EVIDENCE.md` A6 and the `rtl/effects/delay/ext_mem_if.md` traffic table
mixes a per-sample read count with a per-block write count; per frame the
reads are 768, not 24. `ext_mem_traffic.json` also records
`frames_rendered: 8550` while its counters correspond to 8,790 blocks.
`EVIDENCE.md` is sha256-pinned and is not edited here; the correction is
tracked in #367.

The probe was not run, so nothing here is changed or justified by new
evidence. #12's rerun may revisit any of these; the reported budget misses
(metallic -33.5 dBFS, dexie -44.2 dBFS rms vs -46) were diagnosed as
LFO-to-delay-time presence, not as a word-length effect (static path with
depth 0: dexie -109.6 dBFS, metallic -53.3 dBFS; non-committed renders, not
re-measured here).

### Status of the remaining increment (this run)

| item | status | reason |
|---|---|---|
| d(t) engine impulse-train probe (deliverable 1) | BLOCKED | The pinned surgepy oracle is not available on this dispatch worker: no built `surgepy*.so` anywhere on the host, `/home/ubuntu/oracle-307` holds only an incomplete configure (no build products), `ORACLE_SURGE_DIR`/`ORACLE_PREBUILT_URL` are unset and the manifest `prebuilt` store is not reachable. A from-source JUCE/Surge build is not appropriate on this shared 8-vCPU host. No engine numbers were fabricated. |
| Model revision (deliverable 2) | NOT_RUN | Depends on the probe; revising the model without the engine trajectory would be tuning, not mirroring. |
| Delay model-vs-engine, metallic and dexie | FAIL (unchanged, from committed records; not re-run) | -33.5 / -44.2 dBFS rms vs -46; tail gate FAIL. |
| Delay RTL-vs-model exactness | PASS as recorded (PR #46); NOT_RUN here | no model change. |
| EQ regression | PASS as recorded; NOT_RUN here | no change. |
| NC-a / NC-b / NC-e re-derivation | NOT_RUN | no revised baseline to re-derive against. |

To resume: provision the prebuilt oracle (`oracle/fetch-and-build.sh --prebuilt`
with `ORACLE_PREBUILT_URL`) on a host that has it, then run the d(t) probe by
extending `tools/diagnose_delay_engine_probe.py`. If the probe plus a faithful
model revision cannot meet the budgets, the issue's stop clause applies:
leave the rows FAIL and route to #12 per `delay-budget-diagnosis.md` section 3.


## 2026-10-09 update (issue #16): remaining increment executed

Supersedes the 2026-10-08 status table above (the probe was BLOCKED there
because no oracle was available; it ran on this build). Full detail:
`delay-dt-probe.md`.

| item | status |
|---|---|
| d(t) engine probe (deliverable 1), `tools/probe_delay_dt_engine.py`, 3x determinism | PASS (run); records in `artifacts-followup/dt-probe/` |
| Model revision (deliverable 2): runner pre-roll 240 -> 375 blocks, load-time LFO step, float32-grid fused delay-time lag; tb mirrors | done |
| Delay model-vs-engine metallic / dexie (max, rms, corr, tail L/R/mono) | PASS / PASS (metallic -109.0 dBFS rms, dexie -130.3) |
| Delay RTL-vs-model, full-length iverilog, metallic and dexie | PASS, 0 mismatches / 547,200 samples each |
| EQ fm_bass_1 regression (both legs) | PASS (model output bit-unchanged; RTL 0 mismatches, 8,925 blocks) |
| NC-a shared line (500 blocks, metallic) | FAIL as required (control fires): 26 mismatches |
| NC-e one-digit RTL mutant | FAIL as required (control fires) |
| NC-b nearest-neighbour model | FAIL as required on both: metallic on mono budgets; dexie passes the mono budgets (rms -71.4) and fails only the new `--per-channel-budgets` leg (L/R max, corr; tail gate not tripped) |
| NC-c max-feedback corner (`tools/check_delay_maxfb_corner.py`) | PASS bounded, max 1.45, 0 saturated (model-side) |
| NC-d bypass | NOT_RUN (path untouched; PR #44 record stands) |
| Verilator equivalence on revised tb | NOT_RUN |
| `ext_mem_traffic.json` | not regenerated; counters unchanged by the revision, window length differs only by the 135 added settle blocks |

### Word-length assumption this leaf is built against (consumed by #12)

Confirmed against `model/effects/delay/delay_model.py` / `sinc_table.py`:
audio and delay lines Q10.21 (`A_FMT`, LSB 2^-21); gain ramps Q13.18
(`G_FMT`); sinc taps Q2.29 (`SINC_FMT`), FIRipol_N = 12, FIRipol_M = 256;
coefficient/lag/LFO/biquad words Q24.43 (`C_FMT`); exact products rounded
round-half-up; the 12-tap sinc accumulates exactly (RTL 64-bit) then rounds
once to Q10.21. **Change forced by the probe:** the delay-time lag value and
its target are held on the float32 grid inside the Q24.43 word (RNE at 24
significant bits, fused v*lpinv + (float)(t*lp)); this needs a 128-bit
exact product and a 24-bit-significand rounder in the lag datapath. The
delay-time target is rounded once to the float32 grid.
