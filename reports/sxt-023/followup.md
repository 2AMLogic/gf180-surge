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
