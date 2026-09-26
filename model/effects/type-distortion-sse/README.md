# SXT-028e-sse frozen fixed-point model — Distortion, SSE quad-waveshaper branch (`model/effects/type-distortion-sse/`)

Frozen reference for the SXT-028e-sse RTL
(`rtl/effects/type-distortion-sse/`). The RTL must match this model
**exactly** (integer equality at declared checkpoints and on every output
sample; `tools/compare_rtl_model_distortion_sse.py`). Model-vs-pinned-engine
agreement is a SEPARATE claim governed by [PROPOSED] error budgets that are
**not frozen** (SXT-017, #12) — and in this record that leg is **NOT_RUN**
(no pinned oracle was reachable; see `reports/SXT-028e-sse/EVIDENCE.md`).
Nothing here is a preset-support or musical-quality claim.

- Issue: [#121](https://github.com/2AMLogic/gf180-surge/issues/121)
  (SXT-028e-sse), raised by #57's finding F-028e-2
- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`)
- Waveshaper pin:
  `libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce`

## Scope: this leaf and #57 are complementary, never overlapping

`DistortionEffect::process` has **two** shaper branches and they are
different algorithms, not one algorithm with a parameter:

| FX `Model` | `WaveshaperType` | branch | leaf |
|---|---|---|---|
| 0, 1, 2 | `wst_soft`, `wst_hard`, `wst_asym` | `SurgeStorage::lookup_waveshape` (stateless table) | **SXT-028e (#57)** |
| 3..7 | `wst_sine`, `wst_digital`, `wst_ojd`, `wst_fwrectify`, `wst_fuzzsoft` | `GetQuadWaveshaper` (per-instance registers) | **this leaf** |

Each side **REFUSES** the other's indices, fail-closed, in both the params
class and the table builder. Routing one branch's model through the other's
shaper is an *ADAPTED* effect and is refused from original-preset coverage
(negative control NC-A2 demonstrates it FAILS).

## What this leaf adds, and what it REUSES

**REUSED UNCHANGED from `model/effects/type-distortion/distortion_model.py`**
(imported, not re-derived): the pre/post peak EQ, the two instantized
oversampled LP2B stages, the feedback recurrence `L = Lin + fb·L`, the
drive/outgain lipol ramps, the two-stage halfband decimation `hr_a → hr_b`,
the ringout fade, the `bi`-counter slow-rate coefficient pass, and every
word format.

That reuse is a **tested** property, not a comment.
`tests/test_sxt028e_sse.py::test_shared_chain_is_bit_identical_to_sxt028e`
runs this leaf's block schedule with the #57 table shaper substituted for
the quad shaper (via the documented `chain_probe_shaper` verification hook)
and requires the result to be bit-identical to `DistortionModel` at every
output sample and every checkpoint field.

**ADDED here** (steps 4 and 6b below), all of it per-instance state or
per-instance control flow:

* `QuadWaveshaperState` — `n_waveshaper_registers` = 4 registers × 2
  modelled SIMD lanes (Q24.43) plus a per-lane `init` mask. Two Distortion
  slots are two of these; the pooled mutant must FAIL.
* the `1/dNow` pre-scale, **skipped for `wst_digital`** (`skipDriveNorm`);
* the per-oversample drive interpolation `dNow += dD`;
* the zero-input DC-offset probe on a throw-away zeroed state at drive `dS`.

## Algorithm (frozen schedule, mirrors `DistortionEffect::process`)

1. `bi == 0` (every 8th block) → `setvars(false)` — **as #57**.
2. `band1.process_block` (lagged TDF2, base rate) — **as #57**.
3. `dS = drive.get_target()` (read **before** the update), then
   `drive.set_target_smoothed(dE)` where
   `dE = db_to_linear(get_extended(drive))`.
4. **SSE-branch control quantities** (this leaf):
   * `dD = (dE − dS) / (BLOCK_SIZE * dist_OS_bits)` = `(dE − dS)/64`.
     **Read that denominator again.** It is `BLOCK_SIZE * dist_OS_bits`
     = 32·2 = **64**, not `BLOCK_SIZE << dist_OS_bits` = 128, which is the
     number of oversampled steps the loop actually takes. The interpolation
     therefore *overshoots*: after 128 steps `dNow = 2·dE − dS`, not `dE`.
     Reproduced **as written** (issue #121). In Q13.18→Q24.43 the /64 is a
     left shift of 19 — exact, no rounding.
   * `dNow = dS` (block-local: it restarts from `dS` every block).
   * `dcOffset = wsop(zeroed throw-away state, 0, dS)` lane 0 — the probe
     zeroes **both** `R[i]` and `init`, unlike the live `init()`.
   * `skipDriveNorm = (ws == wst_digital)`.
5. `outgain.set_target_smoothed(db_to_linear(gain) · ringoutMul)` and
   `drive.multiply_2_blocks` — **as #57**.
6. Per base sample `k`, per oversampling step `s` (4×):
   a. `L = Lin + fb·L`; `R = Rin + fb·R`; optional `lp1.process_sample_nolag`
      — **as #57**;
   b. **(this leaf)** `sb = L` if `skipDriveNorm` else `L · (1/dNow)`;
      `out = wsop(wsState, sb, dNow)`; `L = out − dcOffset`;
      `dNow += dD`;
   c. optional `lp2.process_sample_nolag`; store to `bL/bR[4k + s]` — **as
      #57**. The engine's ±1e-8 denormal bias is below the Q10.21 LSB and is
      a declared, non-representable deviation (identical to #57's).
7. `hr_a.process_block_D2(128 → 64)` then `hr_b.process_block_D2(64 → 32)`
   — **as #57**.
8. `outgain.multiply_2_blocks_to` then `band2.process_block` — **as #57**.

The effect is **100 % wet**: `process` overwrites `dataL/dataR`. There is no
mix parameter and no dry path.

### A structural consequence worth stating

For FX models 3, 5, 6 and 7 the `1/dNow` pre-scale and the shaper's own
leading `x · drive` **cancel**, so `dNow` — and therefore the /64
interpolation step — is not observable at the output for those models. It
*is* observable for model 4, which is exactly the model the pinned source
singles out with `skipDriveNorm`. Every control that targets the drive
interpolation is therefore graded on a model-4 bed, where the defect is
reachable; grading it elsewhere would be a control that cannot fail.

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| audio samples, feedback registers `L`/`R` | **Q10.21** signed 32-bit | as #57 |
| block-rate gain ramps (`drive`, `outgain`) | **Q13.18** signed 32-bit | as #57 |
| biquad coefficients + lags + TDF2 state | **Q24.43** signed 64-bit | as #57 |
| halfband allpass coefficients + state | **Q24.43** signed 64-bit | as #57 |
| waveshaper table ROM words | **Q2.29** signed 32-bit | as #57 |
| **shaper words, all shaper intermediates, the 4 quad-waveshaper registers, `dNow`, `dD`, `dcOffset`** | **Q24.43** signed 64-bit | this leaf |
| **the TANH numerator and denominator only** | **Q40.23** signed 64-bit | this leaf — the one place the pinned `x·(27 + x²)` exceeds Q24.43's ±8.39e6 (|x| may reach the Q10.21 rail, 1024) |

Products are exact and rounded round-half-up to the target format, then
saturated (`model/effects/qmath.py` conventions). No floating point at audio
run time; double precision only at control (block) rate, quantized once.

## Per-instance state

One `DistortionSSEState` owns an entire #57 `DistortionState` **and** its
own `QuadWaveshaperState`. Measured per instance
(`tools/distortion_sse_buffer_report.py`): 198 × Q24.43 words + 6 × 32-bit
words + a 2-bit mask = **1,609 B**, of which this leaf's delta is **8 ×
Q24.43 + 2 bits = 65 B**. External writable memory: **0 bytes, 0
words/sample** — `QuadWaveshaperState` is four SIMD registers, not a delay
line. The issue's stop/escalate condition ("if the quad-waveshaper state
cannot be bounded in state/cost") is **not triggered**: the state is bounded,
small, and independent of block size, sample rate and FX model. Only
registers 0 and 1 are touched by any of the five reachable shapers.

## Declared deviations (bounded, stated, never silently absorbed)

Full text in `quad_shapers.py`; summarised here.

| id | what | bound | routed |
|---|---|---|---|
| DD-1 | only SIMD lanes 0/1 carry signal; lanes 2/3 are engine stack garbage and every operation is lane-wise | provably no influence on lanes 0/1 | — |
| DD-2 | `rcp_ps` is a ~12-bit *estimate* and implementation-defined; the model uses the exact reciprocal | relative ≤ 1.5·2⁻¹² ≈ 3.7e-4, FX models 4 and 7 only | F-028e-sse-1 → #12 |
| DD-3 | `wsState.init` is **indeterminate** in the engine (`init()` zeroes `R[i]` only); frozen here to "first sample" | at most the first oversampled sample after each reset, FX model 6 only | F-028e-sse-2 |
| DD-4 | the Q24.43 drive-normalized input saturates below ~1.2e-4 of drive | counted per instance (`sat_events`) and reported per case | — |
| — | the engine's ±1e-8 denormal bias is ~0.02 LSB at Q10.21 | ≤ 1 LSB Q10.21, as #57 | — |

Every one of those is a **model-vs-reference** term. None of them affects the
RTL-vs-model claim, which is integer equality on both sides of the same
frozen arithmetic.

## Constants

Inventoried in
`decision-records/0014-distortion-sse-quad-waveshaper-constants.md`
(PROPOSED), which discharges DR-0012's reservation for this branch:

* **11 quoted designed scalars** (OJD's four breakpoints and two
  denominators, TANH's 9 and 27, the ADAA tolerance, the dcBlock pole) —
  streamed to the RTL through the testbench init file, never duplicated
  there (DR-0002 clause 1);
* **2 re-derived table rows** (`wst_sine` 1024 words, `FuzzTable<1>` 1025
  words) — recomputed from the pinned construction formulas in
  `sse_tables.py`; the committed ROM is a build product and a test asserts
  it. The `FuzzTable<1>` re-derivation is discharged **by build**:
  `tools/check_fuzz_table_rederivation.py` compares all 1025 float32 bit
  patterns against a compile of the pinned headers themselves, taken from an
  **external** SHA-pinned checkout (MATCH, 1025/1025, libstdc++). No engine
  source text is transcribed or committed here; absent that checkout the
  tool reports NOT_RUN, never a pass;
* **6 structural powers of two** — not engine data, `localparam`s in the RTL.

## Declared scope omissions (fail-closed)

* FX model indices 0..2 — the #57 table branch. REFUSED.
* Parameter modulation INTO distortion parameters (block-constant
  parameters only; `ringout` is an explicit per-block input).
* Coverage publication (#22) and any budget freeze (#12).

## Reproduce

```sh
# RTL-vs-model exactness + the RTL mutant controls (needs iverilog)
IVERILOG=iverilog python3 tools/compare_rtl_model_distortion_sse.py

# model-side negative controls, state/traffic report, ROM + table checks
python3 tools/distortion_sse_negative_controls.py
python3 tools/distortion_sse_buffer_report.py
python3 tools/gen_distortion_sse_rom.py --check

# FuzzTable<1> build discharge: needs the pinned GPL-3.0-or-later headers,
# which are kept OUTSIDE this repository (NOT_RUN without them)
oracle/fetch-waveshaper-headers.sh
python3 tools/check_fuzz_table_rederivation.py

# fail-closed extraction (graphs cross-check; oracle mode refuses here)
python3 tools/extract_distortion_sse_inputs.py --mode graphs
python3 tools/extract_distortion_sse_inputs.py --mode oracle

python3 -m pytest tests/test_sxt028e_sse.py -q
```
