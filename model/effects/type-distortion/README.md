# SXT-028e frozen fixed-point model — Distortion (`model/effects/type-distortion/`)

Frozen reference for the SXT-028e RTL (`rtl/effects/type-distortion/`). The
RTL must match this model **exactly** (integer equality at declared
checkpoints and on every output sample;
`tools/compare_rtl_model_distortion.py`). Model-vs-pinned-engine agreement is
a SEPARATE claim governed by [PROPOSED] error budgets that are **not frozen**
(SXT-017, #12) — and in this record that leg is **NOT_RUN** (no pinned oracle
was reachable; see `reports/SXT-028e/EVIDENCE.md`).

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`)
- Structure authority (READ + cited; nothing copied):
  `src/common/dsp/effects/DistortionEffect.{h,cpp}` — `init` / `setvars` /
  `process`, `dist_OS_bits = 2`, `ringout_time = 1600`, `ringout_end = 320`.
  Shared machinery: `src/common/dsp/Effect.{h,cpp}` (`slowrate = 8`,
  `Effect::process_ringout`), `src/common/FilterConfiguration.h:235`
  (`n_fxws = 8`, `FXWaveShapers`), sst-filters `BiquadFilter.h`
  (`calc_omega` / `coeff_peakEQ` → `coeff_orfanidisEQ` / `coeff_LP2B` /
  `coeff_instantize` / `process_block` / `process_sample_nolag`),
  sst-filters `HalfRateFilter.h` (`HalfRateFilter(3, steep)::process_block_D2`),
  `vembertech/lipol.h` → `lipol_sse<32,false>`, sst-waveshapers
  `WaveshaperTables.h` + `SurgeStorage::lookup_waveshape`,
  `Parameter::get_extended`.

## Algorithm (frozen schedule, mirrors `DistortionEffect::process`)

1. `bi == 0` (every 8th block) → `setvars(false)`: `band1`/`band2` peak-EQ
   coefficient **targets** from `coeff_peakEQ(calc_omega(freq/12), bw,
   get_extended(gain))`; `lp1`/`lp2` **instantized** coefficients from
   `coeff_LP2B(calc_omega(highcut/12 − 2), 0.707)` — the `− 2` shifts the
   scaled frequency two octaves down so a base-rate `sampleRateInv` yields
   the right corner at the 4× oversampled rate. `bi = (bi + 1) & 7`.
2. `band1.process_block` (lagged TDF2, base rate, stereo, shared coefficients).
3. `dS = drive.get_target()` (read **before** the update), then
   `drive.set_target_smoothed(db_to_linear(get_extended(drive)))`.
   `dS`/`dD`/`dNow` only matter on the SSE-shaper branch, which is outside
   the frozen scope — they are recorded in the control plane and unused here.
4. `outgain.set_target_smoothed(db_to_linear(gain) · ringoutMul)` where
   `ringoutMul = limit01((1600 − ringout − 1)/320)` once `ringout > 1280`.
5. `drive.multiply_2_blocks` (in place, base rate).
6. Per base sample `k`, per oversampling step `s` (4×):
   `L = Lin + fb·L`; `R = Rin + fb·R`; optional `lp1.process_sample_nolag`;
   `lookup_waveshape(model, ·)`; optional `lp2.process_sample_nolag`;
   store to `bL/bR[4k + s]`. The engine's ±1e-8 denormal bias is below the
   Q10.21 LSB and is a declared, non-representable deviation.
7. `hr_a.process_block_D2(128 → 64)` then `hr_b.process_block_D2(64 → 32)`.
8. `outgain.multiply_2_blocks_to` then `band2.process_block` (post-EQ).

The effect is **100 % wet**: `process` overwrites `dataL/dataR`. There is no
mix parameter and no dry path.

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| audio samples, feedback registers `L`/`R` | **Q10.21** signed 32-bit | range ±1024 |
| block-rate gain ramps (`drive`, `outgain`) | **Q13.18** signed 32-bit | lipol_sse 0.25/0.75 smoothing |
| biquad coefficients + lags + TDF2 state | **Q24.43** signed 64-bit | shared `delay_model.Biquad` family |
| halfband allpass coefficients + state | **Q24.43** signed 64-bit | 12 coefficients, 144 state words/instance |
| waveshaper table words | **Q2.29** signed 32-bit | `ws_tables.py`, re-derived from formulas |

Arithmetic rules (FROZEN, `qmath.py`): exact products, round-half-up,
saturating; no floating point at audio run time; double precision only at
control rate, quantized once.

## Per-instance state

One `DistortionState` holds: `band1`, `band2` (lag + target + TDF2
registers), `lp1`, `lp2` (instantized coefficients + TDF2 registers), `hr_a`
and `hr_b` (each 2 ch × 2 branch × 3 stages × 6 taps), the two feedback
registers `L`/`R`, the `drive` and `outgain` lipol ramps, and `bi`. Two
configured Distortion slots are two `DistortionState` objects — nothing is
shared (AGENTS.md; issue #57 acceptance;
`tools/distortion_negative_controls.py` NC-D and the RTL `mutant-shared`
control both demonstrably FAIL when the state is pooled).

**No external memory.** Distortion owns no delay-line-class buffer:
`tools/distortion_buffer_report.py` measures 0 external reads and 0 external
writes per sample from the model's own counters. The rule "long buffers in
external WRITABLE memory, never flash" is vacuously satisfied — there is
nothing long to place. The cost-fit verdict remains **[PENDING-SXT-016]**.

## Declared control-plane boundary (model → RTL)

Streamed one word per line (`<case>_ctrl.hex`), per instance per block:
drive RAW lipol target (Q13.18 — the RTL applies the 0.25/0.75 recurrence),
outgain RAW lipol target (Q13.18, with `ringoutMul` already folded in), the
feedback coefficient (Q10.21), `band1`/`band2` coefficient targets and
`lp1`/`lp2` instantized coefficients (4 × 5 × Q24.43), and a flags word
(bit0 `lp1` active, bit1 `lp2` active, bits 2–3 the waveshaper model index).
The RTL computes everything audio-rate: the peak-EQ coefficient lag
recurrence and TDF2 state, the drive ramp, the 4× feedback/shaper loop
(including the table lookup and both instantized LP stages), both halfband
cascades, the outgain ramp and the post-EQ.

The twelve halfband allpass coefficients are streamed through the init file
(DR-0002 clause 1: the RTL carries no independent copy). The waveshaper ROM
(`rtl/effects/type-distortion/ws_q29.hex`, 3 × 1024 Q2.29 words) is generated
by `ws_tables.py` from the pinned construction formulas; its digest is
recorded in `reports/SXT-028e/artifacts/buffer-requirement.json` and checked
by `tests/test_sxt028e.py`.

## Declared scope omissions (fail-closed)

* **Waveshaper models 3..7** (`wst_sine`, `wst_digital`, `wst_ojd`,
  `wst_fwrectify`, `wst_fuzzsoft`) take `DistortionEffect::process`'s
  `useSSEShaper` branch (`ws >= wst_sine`): `GetQuadWaveshaper` with its own
  per-instance registers, drive normalization (`dInv`, skipped for DIGITAL),
  per-step drive interpolation `dNow += dD`, and a zero-input DC-offset
  probe. That is a separate subsystem, not a parameter of this one.
  `DistortionParams` and `ws_tables.build_table` **REFUSE** those indices —
  no generic substitute. Corpus reach of the frozen scope (models 0/1/2,
  `corpus/normalized/graphs.jsonl`, active Distortion slots):
  **447 of 475 slot instances**, including all three of the issue's named
  B4-scope carriers. Follow-up issue for the SSE branch: see
  `reports/SXT-028e/EVIDENCE.md` §8.
* Parameter modulation INTO distortion parameters (parameters are
  block-constant; `ringout` is an explicit per-block control input).
* The ±1e-8 denormal bias (below the Q10.21 LSB; fixed point has no
  denormals, so the bias has no function).

## Files

* `distortion_model.py` — frozen model (+ `model_revision()` frozen-revision
  pin consumed by the RTL comparator; a stale harness refuses to PASS)
* `ws_tables.py` — waveshaper lookup tables, re-derived from the pinned
  construction formulas (no opaque constants)

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). Structure read and
cited from the pinned GPL-3.0-or-later tree; no code or assets copied.
Constant inventory:

* **Re-derived (no decision record needed, `sinc_table.py` class):** the
  three waveshaper table rows (`tanh`, the hard-clip power law,
  `shafted_tanh`), the Orfanidis peak-EQ and LP2B coefficient builds,
  `calc_omega`, `db_to_linear`, `note_to_pitch_ignoring_tuning`,
  `get_extended`'s 3×/5× multipliers, the 0.004 biquad coefficient-lag pair,
  the 0.25/0.75 lipol smoothing, Q = 0.707, and the ringout fade formula.
* **Quoted opaque constants (decision record required):** the twelve
  order-6 halfband allpass coefficients (soft and steep sets) —
  `decision-records/0012-distortion-halfband-and-waveshaper-tables.md`,
  the SXT-028e successor to the ratified DR-0002 (the M = 6 steep set).
