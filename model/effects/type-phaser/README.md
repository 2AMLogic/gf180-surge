# SXT-028g frozen fixed-point model — Phaser (`model/effects/type-phaser/`)

Frozen reference for the SXT-028g RTL (`rtl/effects/type-phaser/`). The RTL
must match this model **exactly** (integer equality on every per-instance
output sample and at every declared checkpoint;
`tools/compare_rtl_model_phaser.py`).

Three claims, kept separate (AGENTS.md) — never infer one from another:

| # | Claim | Established by | Status for this leaf |
|---|---|---|---|
| 1 | RTL matches this frozen model exactly | `tools/compare_rtl_model_phaser.py` | **PASS** (`reports/SXT-028g/rtl-exactness.json`) |
| 2 | Model reproduces the pinned Surge engine within declared budgets | `tools/compare_phaser_reference.py` | **NOT_RUN** — no oracle in this environment; budgets are `[PROPOSED, not frozen]`, freeze gated on SXT-017 (#12) |
| 3 | The instrument sounds good | listening records only | **NO_VERDICT** — nothing here bears on it |

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`).
- Structure authority (READ + cited; **nothing copied** — the pinned trees are
  GPL-3.0-or-later and stay external, AGENTS.md licensing):
  - `libs/sst/sst-effects@adcac695…/include/sst/effects/Phaser.h`
    (`initialize`, `init_stages`, `setvars`, `processBlock`,
    `getRingoutDecay`, `legacy_freq` / `legacy_span`, the spread law and the
    `2/(i+1)` LFO shift, the ±32 clamp, the tone→cutoff map)
  - `…/include/sst/effects/EffectCore.h` (`slowrate = 8`,
    `useLinearWidth() == false` for the Surge FXConfig)
  - `…/include/sst/effects-shared/WidthProvider.h`
    (`setWidthTarget` / `applyWidth`)
  - `libs/sst/sst-basic-blocks@a32b8aec…/include/sst/basic-blocks/modulators/FXModControl.h`
    (LFO phase, stereo phase spread, the five deterministic shapes,
    `depthLerp`, `valueStereo`)
  - `…/dsp/BlockInterpolators.h` (`lipol<float,BS,true>`,
    `lipol_sse<32,false>`), `…/dsp/MidSide.h`
  - `libs/sst/sst-filters@e92d93a9…/include/sst/filters/BiquadFilter.h`
    (`calc_omega`, `coeff_APF` / `coeff_LP` / `coeff_HP`, `set_coef`,
    per-sample coefficient lag `d_lp = 0.004`, TDF2 mono `process_sample`
    and stereo `process_block`)
  - `surge@58914e5…/src/common/dsp/effects/SurgeSSTFXAdapter.h` and
    `PhaserEffect.{h,cpp}` (ctrl types, streaming migrations)

## Algorithm (frozen schedule, mirrors `Phaser::processBlock`)

`slowrate = 8`: `setvars()` runs on blocks where `bi == 0`, i.e. once per
8 blocks (256 samples). Everything else runs every block.

**Control pass (`setvars`, every 8th block)**

1. `rate = envelope_rate_linear(−mod_rate) · temposyncRatio(mod_rate) · 8`;
   `depth = clamp(mod_depth, 0, 2)`; `stereo = clamp(stereo, 0, 1)`.
2. LFO (`FXModControl<32>`, `rnd_dual_stereo`): with the rate **active**,
   `lfophase = fmod(lfophase + rate, 1)` and `thisphase[i] =
   fmod(lfophase + i·stereo·0.25, 1)`; with the rate **deactivated**, rate is
   0 and the phase is the static `clamp((mod_rate − (−7)) / (9 − (−7)), 0, 1)`
   window. Shape ∈ {sine (8192-entry table + lerp), triangle, saw, ramp,
   square}. Each shape sample is pushed into an output lipol and the depth
   into `depthLerp`.
   **Engine quirk, reproduced exactly:** the Phaser never calls
   `modLFO.process()`, so those lipols never advance and `valueStereo()`
   returns the *previous* slow block's waveform sample × the *previous*
   slow block's depth — except on the very first call, where the lipol
   `first_run` snap makes it the current one. This one-slow-block LFO
   latency is load-bearing and is covered by a checkpoint.
3. APF coefficients, `Q = 1 + 0.8·sharpness`:
   - `n_stages ≥ 2`: per stage *i*, `center_i = powf(2, (i+1)·2/n_stages)`,
     `ω = calc_omega(2·center + spread·center_i + (2/(i+1))·lfo[ch])`,
     `coeff_APF(ω, Q)` into biquad `2i+ch`.
   - `n_stages < 2` (legacy): `Phaser.h` loops `i < 2` over
     `legacy_freq/legacy_span` and so configures biquads 0..3, while
     `processBlock` runs only stage 0 (biquads 0 and 1). **Reproduced as
     pinned — this is engine behaviour, not a model simplification**, and
     the state inventory follows the allocation, not the usage.
4. `feedback.newValue(0.95f · feedback)`; `tone.newValue(clamp(tone, −1, 1))`;
   `widthS.set_target_smoothed(db_to_linear(width))`.
5. Tone → cutoffs, read from `tone.v` *after* `newValue` (i.e. the previous
   slow block's converged value): `clo = −12`, `cmid = 67`, `chi = −33`;
   `tone.v > 0` moves the **high-pass** from `chi` to `cmid`, otherwise it
   moves the **low-pass** from `cmid` to `clo`.
   `lp.coeff_LP(calc_omega(lpCutoff/12 − 2), 0.707)`,
   `hp.coeff_HP(calc_omega(hpCutoff/12 − 2), 0.707)`.

**Audio pass (every block, 32 samples)**

6. `mix.set_target_smoothed(clamp(mix, 0, 1))` — every block, not only on
   `setvars`.
7. Per sample: `feedback.process()`, `tone.process()` (`v += dv`);
   `dL = in_L + dL·feedback.v`, same for R; `clamp(±32)`; then the cascade
   `dL = apf[2s](dL)`, `dR = apf[2s+1](dR)` for `s = 0 … n_stages−1`
   (each APF is a MONO TDF2 with its own per-sample coefficient lag);
   `dL/dR` carry over to the next sample (the recursive node).
8. If `tone` is **not** deactivated: `lp.process_block(L, R)` then
   `hp.process_block(L, R)` (stereo TDF2, per-sample coefficient lag).
9. `applyWidth`: `M = (L+R)/2`, `S = (L−R)/2`, `S ·= widthS` ramp,
   `L = M+S`, `R = M−S`. `widthM` is **not** applied (`useLinearWidth()` is
   false for the Surge FXConfig).
10. `mix.fade_2_blocks_inplace`: `out = dry·(1−t) + wet·t`.

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| audio samples, the recursive node dL/dR, inter-stage cascade words | **Q10.21** signed 32-bit | range ±1024; the ±32 clamp sits well inside it |
| block-rate gain ramps (`widthS`, `mix`) | **Q13.18** signed 32-bit | `lipol_sse<32,false>` `current`/`target` |
| biquad coefficients, coefficient lags, TDF2 registers | **Q24.43** signed 64-bit | shared `delay_model.Biquad` (stereo tone filters) and `MonoBiquad` (APF units) |
| `feedback` / `tone` lipol `v`, `new_v`, `dv` | **Q24.43** signed 64-bit | `bs_inv` = 1/256 (feedback, `blockSize·slowrate`) and 1/32 (tone) — both exact powers of two |
| LFO phase, shape values, depth | **Q24.43** signed 64-bit | `lfophase` quantized once per slow block; the sine TABLE is kept on the engine's float32 grid |

Arithmetic rules (FROZEN, `../qmath.py`): exact products, round-half-up
`(p + 2^(s−1)) >> s`, saturating; **no floating point at audio run time**;
double precision only at control rate, quantized once.

## Per-instance state

One `PhaserState` holds: `dL`/`dR`, the `2·n_stages` MONO APF biquads
(5 coefficient lags + 5 targets + 2 TDF2 registers each), the stereo tone
`lp`/`hp` biquads, the `feedback` and `tone` lipols, the `widthS` and `mix`
ramps, the `FXModControl` phase + output lipols, and the slow-block counter
`bi`. Two configured Phaser slots are two `PhaserState` objects — state is
never shared (AGENTS.md; issue #59 acceptance). Arithmetic may be shared
only observably.

Exact inventory (`phaser_model.state_inventory`, bytes per instance):

| stages | biquad units | bytes |
|---|---|---|
| 1 (legacy) | 4 | 812 |
| 2 | 4 | 812 |
| 4 (default) | 8 | 1196 |
| 8 | 16 | 1964 |
| 16 (max) | 32 | 3500 |

## External memory

**The Phaser owns no delay line.** There is no long buffer, so audio-rate
external-memory traffic is **zero words/sample** — measured from the model's
own `ext_reads`/`ext_writes` transaction counters, not estimated
(`tools/phaser_buffer_report.py`). All state above is small on-chip state;
flash is never writable delay memory and none is used here.

The **cost/fit closure** over this inventory is **`[PENDING-SXT-016]`**: no
cycles-per-frame, schedule-fit or bundle-closure number is asserted by this
leaf, and profile v1 is not frozen (SXT-017, #12).

SXT-015 reconciliation: the corpus accounting carries the Phaser as
`class_state_unverified`, tier `no_long_buffer`, external `false`,
0 ext reads/writes per frame, with a conservative 8192-byte placeholder and
the note *"exact state sizing ESTIMATE-REF deferred to SXT-028"*. This leaf
**confirms** the tier and traffic and **supersedes** the byte placeholder
with the exact inventory (worst case 3500 B ≤ 8192 B, so the placeholder was
conservative).

## Tails

The declared tail span is `Phaser::getRingoutDecay()` **in blocks of 32**
(feedback-dependent: 1000 / 3000 / 5000 blocks, i.e. 0.667 / 2.0 / 3.33 s,
and **−1** when `|feedback| > 1` — possible self-oscillation, for which no
finite span can be declared and the tail check REFUSES).

An acceptance render must cover that span *after the input goes silent*, and
the captured tail must have decayed to the declared terminal floor by its
end. `tools/render_phaser_fixtures.py` refuses a sequence whose `tail_s` is
shorter than the span, so a dropped tail cannot enter the evidence; the
dropped-tail negative control (NC-B) demonstrates that a truncated render
FAILS both legs. Windows per corner:
`reports/SXT-028g/artifacts/tail-window.json`.

**Reset / panic**: `suspendProcessing()` routes to `initialize()` in
`Phaser.h` — the whole per-instance state is cleared, the ramps return to
their constructor/`initialize` state and the tail stops. `PhaserModel.reset()`
is that path, exercised by the `prs-reset48-128` RTL case.

**Patch change mid-tail**: the engine mutates the `FxStorage` values in
place; the running instance keeps `dL`/`dR`, every biquad register and every
ramp, and picks the new values up only at the next `setvars` (`bi == 0`)
boundary — so the tail *continues* rather than restarting.
`PhaserModel.set_params()` is that path, exercised by the
`prs-patch64-160` RTL case (input silent at block 48, parameters changed at
block 64 while the tail is still ringing). A stage-count change is refused:
it is the `init_stages` allocation path, outside the frozen scope.

## Declared control-plane boundary (model → RTL)

Streamed one word per line (`<slug>_ctrl.hex`), per instance per block:
flags (setvars / tone-active / stage count), the `mix` and `widthS` RAW
lipol targets (the RTL applies the 0.25/0.75 smoothing), the `feedback` and
`tone` `newValue` words, the tone `lp`/`hp` coefficient targets, and 5
coefficient targets per configured APF unit. The LFO phase accumulator, the
LFO shapes, the depth and the tone→cutoff map are control-plane. The RTL
computes everything audio-rate: the lipol `v += dv` recurrences, the
feedback multiply and ±32 clamp, the APF cascade with its per-sample
coefficient lags, the tone filters, the width matrix and the mix crossfade.

## Declared deviations (bounded; absorbed by the `[PROPOSED]` budgets)

* Engine float32 audio and lipol state → Q10.21 / Q24.43. The engine also
  re-rounds the cascade value to float32 between stages
  (`BiquadFilter::process_sample` returns `float`), so a per-stage grid
  round is structurally faithful; the **grid** differs (float32 *relative*
  vs Q10.21 *absolute*), which is the dominant declared deviation of this
  leaf. It is **not measured** here — claim 2 is NOT_RUN.
* `lfophase` held Q24.43 (engine float32), quantized once per slow block;
  the `fmod` wrap keeps the error bounded and non-accumulating.
* Control-rate formulas (`envelope_rate_linear`,
  `note_to_pitch_ignoring_tuning`, `db_to_linear`, `cos`/`sin`, the `powf`
  spread law, the LFO shapes) evaluated in double and quantized once; the
  engine evaluates them in float32 / table lookups. The LFO sine table is
  kept on the float32 grid.
* **Q13.18 lipol smoothing floor.** `set_target_smoothed` converges as
  `target ← round_half_up(0.25·f + 0.75·target)`, which *sticks at 2 LSB*
  for `f = 0` (round-half-up of 1.5 is 2), whereas the engine's float ramp
  underflows to 0. This bounds the fully-converged bypass residual; it is
  measured by negative control NC-E and is a property of the shared `Lipol`
  used by every effect model in this repository, not of the Phaser.

## Declared scope omissions (FAIL-CLOSED — these raise, never degrade)

* `mod_wave` 5 (Noise) and 6 (Sample & Hold): RNG-driven
  (`FXModControl` uses `sst::basic_blocks::dsp::RNG`). Not bit-reproducible
  against the pinned oracle without an RNG-stream pin, so the model and the
  extractor **refuse** them rather than substituting a deterministic shape.
  This is a bounded finding: it blocks only the affected carriers, and no
  acceptance rule was weakened to absorb it. Follow-up: **#122**.
* Parameter modulation INTO phaser parameters (fail-closed; the extractor
  refuses any preset with an FX-destination modulation route).
* The runtime `n_stages` change path (`init_stages` allocating new biquads
  mid-render): `n_stages` is block-constant in the frozen scope.

## Files

* `phaser_model.py` — the frozen model (+ `model_revision()`, the
  frozen-revision pin consumed by the RTL comparator; a stale harness
  refuses to PASS)
* `corners.py` — the synthetic parameter corners, written out as
  `../fx_inputs/type-phaser-synth-*.json`. **Synthetic corners are not
  preset extractions**: they carry `"source": "synthetic-corner"`,
  `"census_blob_sha1": null` and no support, coverage or fidelity claim.
  Preset-derived inputs come only from `tools/extract_phaser_inputs.py`.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). Structure read and
cited from the pinned GPL-3.0-or-later trees; **no code, tables or assets
copied**. Constant inventory — no opaque designed constants:

| Constant | Origin |
|---|---|
| `slowrate = 8`, `max_stages = 16`, `default_stages = 4` | cited literals (`EffectCore.h`, `Phaser.h`) |
| `legacy_freq = {1.5, 19.5, 35, 50}/12`, `legacy_span = {2, 1.5, 1, 0.5}` | cited literals (`Phaser.h`) |
| `0.95` feedback scale, `1 + 0.8·sharpness`, `±32` clamp | cited literals (`Phaser.h`) |
| `clo/cmid/chi = −12 / 67 / −33`, `/12 − 2` cutoff map | cited literals (`Phaser.h`) |
| rate window `[−7, 9]` (deactivated-rate phase) | cited literals (`Phaser.h`) |
| biquad `Q = 0.707`, lag `d_lp = 0.004` | cited literals (`BiquadFilter.h`) |
| LFO table size 8192, saw cut 0.98, square cut 0.01 | cited literals (`FXModControl.h`) |
| sine table, APF/LP/HP coefficient builds, `calc_omega`, `envelope_rate_linear`, `note_to_pitch_ignoring_tuning`, `db_to_linear`, the `powf` spread law | formula re-derivations from the cited sources, evaluated in double and quantized once |

## Reproduce

```sh
python3 model/effects/type-phaser/corners.py --write     # synthetic corners
python3 tools/compare_rtl_model_phaser.py                # claim 1 (runs here)
python3 tools/phaser_negative_controls.py                # 6 live controls
python3 tools/phaser_buffer_report.py                    # state + traffic
python3 tools/phaser_oracle_status.py                    # measured NOT_RUN record

# oracle host only (claim 2; NOT_RUN without a pinned-engine checkout)
python3 tools/extract_phaser_inputs.py
python3 tools/render_phaser_fixtures.py
python3 model/effects/run_phaser_model.py --slug <slug> --seq <seq>
python3 tools/compare_phaser_reference.py --slug <slug> --seq <seq>
```
