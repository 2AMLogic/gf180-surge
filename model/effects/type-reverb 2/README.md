# SXT-028f frozen fixed-point model — Reverb 2 (`model/effects/type-reverb 2/`)

Frozen reference for the SXT-028f RTL (`rtl/effects/type-reverb 2/`). The
RTL must match this model **exactly** (integer equality at declared
checkpoints, on every per-sample tank checkpoint and on every output
sample; `tools/compare_rtl_model_reverb2.py`). Model-vs-pinned-engine
agreement is a **separate** claim, governed by [PROPOSED] error budgets
that are **not frozen**; it is **NOT_RUN** in this leaf (no oracle host —
see `reports/SXT-028f/EVIDENCE.md` §3). Neither claim says anything about
how the effect sounds.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`).
- Structure authority (READ + cited; nothing copied):
  `libs/sst/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b/include/sst/effects/Reverb2.h`
  (constants `:63-74`; `allpass` `:76-87`/`:263-284`; `delay`
  `:89-101`/`:286-319`; `predelay` `:103-123`; `onepole_filter`
  `:125-134`/`:321-335`; `calc_size` `:348-382`; `setvars` `:384-397`;
  `processBlock` `:399-490`), the same pin's `EffectCore.h` and
  `effects-shared/WidthProvider.h`,
  `libs/sst/sst-basic-blocks@a32b8aec…` `BlockInterpolators.h`
  (`lipol<float,32,true>`, `lipol_sse<32,false>`) and
  `QuadratureOscillators.h` (`SurgeQuadrOsc<float>`), plus
  `src/common/dsp/effects/SurgeSSTFXAdapter.h` and
  `src/common/dsp/effects/Reverb2Effect.h` in the engine pin
  (`Reverb2Effect` is a thin `SurgeSSTFXBase` wrapper — the sst header is
  the algorithm authority; `Effect.cpp:79-80` instantiates it for
  `fxt_reverb2`).
- Parameter order is cross-checked against the committed pinned normalized
  state (`corpus/normalized/graphs.jsonl`, SXT-011) for the three
  issue-named carriers; every value is range-checked against the declared
  `paramAt` range and a value outside it is a refusal
  (`tools/extract_reverb2_inputs.py`).

## Algorithm (frozen schedule, mirrors `Reverb2::processBlock`)

1. **Control pass, once per block.** `scale = powf(2, room_size)`;
   `calc_size(scale)` recomputes eight tap times, twelve allpass lengths
   and four delay lengths from the engine's millisecond literals through
   `msToSamples` (float32 `a = sr·ms·0.001f`, `b = a·scale`, `(int)b`);
   `decay = powf(0.001, 0.5508·scale / (4·2^decay_time))`; the six
   `lipol<float>` ramps take new targets (`decay`, `0.7·diffusion`,
   `0.7·buildup`, `0.8·hf_damping`, `0.2·lf_damping`,
   `modulation·sr·0.001·5`); `widthS`/`mix` take **smoothed** `lipol_sse`
   targets (`0.25·f + 0.75·target`); the LFO rate is re-set every block
   with the constant `ω = 2π·2⁻²/sr`, which also **renormalises** the
   `(r, i)` vector; `pdt = clamp((int)(sr·2^predelay·tsRatioInv), 1,
   1151999)`.
2. **Per sample.** `in = (L+R)·0.5` → predelay ring read at `k − pdt`
   (read-before-write) → four input allpasses at `diffusion.v`. Then
   `x = _state` and for each of the four tank blocks: `x += in`; two
   allpasses at `buildup.v`; one-pole lowpass at
   `clamp(hf.v, 0.01, 0.99)`; one-pole highpass at
   `clamp(lf.v, 0.01, 0.99)`; `modulation = (int)(mod.v·lfos[b]·256)` with
   `lfos = [r, i, −r, −i]`; the delay's two output taps are read, then the
   sub-sample interpolated recirculation read at
   `k − len + (modulation ≫ 8)` (+1) weighted by the 8-bit fraction, then
   the write; `outL += tapL·gainL[b]`, `outR += tapR·gainR[b]`;
   `x *= decay.v`. Finally `_state = x` and the ramps step.
3. **Block tail.** `applyWidth` (mid/side, side scaled by the `widthS`
   ramp, mid intact) then the `mix` crossfade `dry·(1−t) + wet·t`.

### Two pinned behaviours that are load-bearing and easy to "fix" wrongly

* **The LF-damping ramp is never stepped.** `Reverb2.h:478-483` calls
  `process()` on `_decay_multiply`, `_diffusion`, `_buildup`,
  `_hf_damp_coefficent`, `_lfo` and `_modulation` — but **not** on
  `_lf_damp_coefficent`. Its `.v` therefore holds the *previous block's*
  target for the whole block (`newValue` assigns `v = new_v` first). The
  model reproduces this exactly; `mutant-lfdamp` in
  `tools/compare_rtl_model_reverb2.py` steps it and must FAIL.
* **Suspend does not clear the tank.** `suspendProcessing()` is
  `initialize()` is `setvars(true)`, which only rebuilds the tap gains and
  calls `calc_size(1.f)`. Only the constructor zeroes the buffers, the
  ramps and `_state`. `Reverb2Model.suspend()` reproduces that;
  `Reverb2Model.initialize()` is the constructor + init path (the engine's
  fx-rebuild). NC-G in `tools/reverb2_negative_controls.py` flags a
  clearing mutant.

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| audio samples, every external buffer word | **Q10.21** signed 32-bit | predelay, 12 allpass rings, 4 delay rings |
| block-rate gain ramps (`widthS`, `mix`) and the four tap gains | **Q13.18** signed 32-bit | tap gains quantised once from the float32 literals `1.5f/4`, `1.2f/4`, `1.0f/4`, `0.8f/4` |
| six coefficient ramps (`v`/`new_v`/`dv`), one-pole registers, LFO `r`/`i`/`dr`/`di` | **Q24.43** signed 64-bit | engine holds float32 |
| delay sub-sample interpolation | 8-bit fraction, exact 64-bit accumulator | `(d1·f1 + d2·f2)` rounded once |
| modulation cast | truncation toward zero of the exact Q86 product ×256 | mirrors the engine's `(int)` cast |

Arithmetic rules (FROZEN, `qmath.py`): exact products, round-half-up
`(p + 2^(s−1)) ≫ s`, saturating; **no floating point at audio run time**;
double precision only at control rate, quantised once, with explicit
float32 rounding wherever the engine stores a `float`.

The two halvings — the `(L+R)·0.5` input fold and the mid/side encode —
**truncate toward zero**, the repo's frozen halving convention
(`model/effects/type-chorus`).

## Per-instance state and the allocation profile

One `Reverb2State` owns: one flat external region (the predelay ring, the
twelve allpass rings, the four delay rings), all ring indices and
configured lengths, the eight one-pole registers, the tank accumulator
`_state`, the six coefficient ramps, the LFO, the two `lipol_sse` ramps,
three per-region additive integrity hashes and the external transaction
counters. **Two configured Reverb 2 slots are two `Reverb2State` objects
over two disjoint regions; nothing is shared** (AGENTS.md, plan section 3).
Arithmetic may be shared only observably.

| Profile | predelay | allpass ×12 | delay ×4 | words/instance | bytes |
|---|---|---|---|---|---|
| `ENGINE_PROFILE` (default) | 1,536,000 | 131,072 | 131,072 | 3,633,152 | 14,532,608 (13.859 MiB) |
| `HARNESS_PROFILE` (RTL bench only) | 16,384 | 4,096 | 16,384 | 131,072 | 524,288 |

The reduced bench profile exists so two instances fit the simulator. It is
legal **only** while every ring stays longer than its longest live tap:
`_calc_size` and the predelay clamp raise `ProfileRefusal` otherwise (no
silent reduction), and `tests/test_sxt028f.py::test_alloc_profile_equivalence`
runs the same stimulus under both profiles and requires **identical
output**. Transaction *counts* are identical under both profiles; only
addresses (and therefore the region hashes) differ, and both sides of the
exactness comparison run the same profile.

## Declared control-plane boundary (model → RTL)

Streamed one word per line (`ctrl.hex`), per instance per block, in this
frozen order: six `lipol<float>` RAW targets (decay, diffusion, buildup,
hf-damp, lf-damp, modulation — the RTL owns the `v = new_v; dv = Δ/32`
recurrence and the pinned "lf never steps" quirk); the LFO `dr`, `di` and
the control-rate renormalisation constant `n` (the per-sample magic-circle
recurrence is audio-rate in the RTL; the reciprocal square root is a
control-rate scalar); the `widthS` and `mix` RAW `lipol_sse` targets (the
RTL applies the 0.25/0.75 smoothing); the eight tap times; the twelve
allpass lengths; the four delay lengths; the predelay tap. Everything else
— rings, filters, modulation truncation, interpolation, MACs, width,
crossfade — is audio-rate RTL.

## Declared scope omissions (fail-closed)

* **Parameter modulation INTO Reverb 2 parameters.** `Reverb2Params`
  refuses a per-sample trajectory. 300 of the 708 corpus Reverb 2 carriers
  carry at least one FX-destination modulation route
  (`reports/SXT-028f/artifacts/carrier-ledger.json`) and the extraction
  refuses them.
* **Temposync of `rev2_predelay` when the flag is UNRESOLVED.**
  `Reverb2Params` raises rather than assume "not synced".
* Sample rates other than 48 kHz; `onSampleRateChanged` is the
  initialize path and is not otherwise modelled.

## Files

* `reverb2_model.py` — the frozen model (+ `model_revision()`, the frozen
  revision pin every harness checks; a stale harness refuses to PASS).
* `README.md` — this freeze document.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). The Reverb 2
structure was **read and cited** from the pinned GPL-3.0-or-later
`sst-effects` / `sst-basic-blocks` / Surge trees; **no source, table or
asset is copied here**. Constant inventory (no opaque designed constants):
every constant is either an engine literal cited to its pinned line
(`0.5508`, `db60 = 0.001`, the tap-time millisecond table, the allpass and
delay millisecond tables, the four tap-gain literals, `0.7`/`0.8`/`0.2`
parameter scalings, the `[0.01, 0.99]` damping clamps, `ω = 2π·2⁻²/sr`) or
a formula re-derivation (`db_to_linear`, the 0.25/0.75 lipol smoothing).
No distribution-license determination has been made for Surge-derived
material.
