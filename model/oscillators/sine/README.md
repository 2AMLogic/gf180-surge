# SXT-040 — frozen fixed-point Sine oscillator family model

Issue: #74 (SXT-040) · Model: `sine_model.py` · Runner: `run_model.py` ·
Inputs: `inputs/*.json` (`extract_inputs.py`, requires the external pinned
oracle) · Fixture overrides: `fixture_config.py` ·
RTL: `rtl/oscillators/sine/`

**Status: FROZEN for the SXT-040 RTL.** RTL-vs-model agreement must be EXACT
(integer equality at every declared checkpoint;
`tools/compare_sine_rtl_model.py`). Model-vs-pinned-engine agreement is
governed by [PROPOSED] budgets (see `reports/SXT-040/EVIDENCE.md`); nothing
here is a fidelity, support, or preset-quality claim.

Scope: the Sine oscillator family **beyond** the landed SXT-026a voice slice
(legacy path, FMmode 0, shape 0, unison 1, retrigger — frozen in
`model/voice/voice_model.py`). This leaf covers the family's submode
selector and unison machinery over the declared parameter classes observed
in the committed normalized graphs
(`corpus/normalized/graphs.jsonl`, sha256
`c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715`;
2,223 Sine slots):

| Class | Param | Engine type / range at the pin | Observed (corpus) |
|---|---|---|---|
| shape ("Mode") | p[0] | `ct_sineoscmode`, int [0, 31] | 0..31 except 3/5/7/22 (+ INT_MIN garbage in 15 slots — engine clamps/refuses per gate) |
| feedback | p[1] | `ct_osc_feedback_negative` [-1, 1], `get_extended` = 4·f (extend flag engine-read) | −1 .. 1 |
| behavior | p[2] | `ct_sinefmlegacy`, int {0 legacy, 1 modern} | 0: 590, 1: 1,633 |
| low cut | p[3] | `ct_freq_audible_deactivatable_hp` [-60, 70] | −60 (defaults) .. mid values |
| high cut | p[4] | `ct_freq_audible_deactivatable_lp` [-60, 70] | .. 70 (defaults) |
| unison detune | p[5] | `ct_oscspread` [0, 1], `get_extended` = 12·f | 0 .. 0.77 |
| unison voices | p[6] | `ct_osccount` [1, 16] | 1 .. 16 (+ garbage: engine clamps at osc init, gate refuses) |

Pinned structure (read and cited, structure never copied; the one quoted
data table — the wave_remap migration — carries license decision record
DR-0008):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 —

* `SineOscillator.cpp/.h` — init / prepare_unison / process_block (the
  fmlegacy 0-vs-1 dispatch) / process_block_legacy (FM and non-FM branches) /
  process_block_internal (omega ramp, feedback lags, playramp) /
  valueFromSinAndCosForMode<0..31> / applyFilter / handleStreamingMismatches
  (shape wave_remap); `lag<double>` = sst-basic-blocks `dsp/Lag.h`
  SurgeLag (default rate 0.004, newValue = setTarget with first-run snap)
* `OscillatorBase.h` — pitch_to_omega (2π·MIDI_0_FREQ·ntp/sr_os)
* sst-basic-blocks `QuadratureOscillators.h` — SurgeQuadrOsc (ctor r=0,
  i=−1; set_rate cos/sin + double 1/sqrt normalize)
* sst-basic-blocks `FastMath.h` — fastsin/fastcos (JUCE Pade rationals),
  clampToPiRange
* sst-basic-blocks `OscillatorDriftUnisonCharacter.h` — UnisonSetup
  (attenuation 1/√n, detune bias 2/(n−1) offset −1, **linear** pan law
  panL=1−d / panR=1+d — mono-inert: (panL+panR)/2 = 1), CharacterFilter
  (Warm/Neutral/Bright, `starting` warm start)
* sst-filters `BiquadFilter.h` — coeff_HP / coeff_LP2B (both with the
  ω>π identity guard), TDF2 process
* `SurgeVoice.cpp` — mono voice path (stereo = (fbc == fc_wide)); the
  modeled slot enters the serial-1 A path (fixture override pins
  route_o<slot> = 1; presets storing route 2 enter via the F2-mix B path
  with gain min(1, 1+filter_balance) — outside the declared slice)

## Declared parameter-class boundaries (fail-closed refusals)

The model raises (and the extractor refuses, exit 2) outside:

* unison outside 1..16 (engine clamps; this contract rejects, SXT-026 rule);
* absolute detune mode (`p[5].absolute`, engine-read — separate machine);
* scene drift ≠ 0 (determinism gate);
* retrigger off in fixture configurations (deterministic starts);
* FM routing into the modeled slot (fixture override pins `fm_switch` off);
  the modern fv = 32π·fmdepth³ machinery is implemented and checkpointed
  but never audible in the committed fixtures;
* analog envelope mode; decay shapes outside d_s ∈ {0, 1, 2}; attack
  shapes outside a_s ∈ {0, 1, 2} (extensions declared below);
* character Bright (Warm/Neutral declared);
* shape outside [0, 31] (int); behavior outside {0, 1};
* pitch outside [24, 148] (fractional pitch kept — the sine osc has no
  pitchmult word);
* scene-A modulation routes (scene AND voice tables) whose destination is
  not provably inert under the fixture overrides (muted osc, off filter
  units / waveshaper, FM depth with FM off) and whose source is not
  value-identically-zero across the declared fixture sequences (no
  controller events; velocity/keytrack/LFO sources are NOT value-zero).
  This gate refused Alone and Mystery 4 (velocity/keytrack/LFO routes into
  Amp EG, Pan, Osc Pitch/Feedback/Drift) — recorded as out-of-class, never
  adapted.

Applicability boundary: presets whose Sine content sits outside the
declared single-scene mono voice slice are NOT renderable by this leaf.
Isolation overrides (mute other paths, filters/FX/ws off, fbc serial1,
**route_o<slot> = 1**, FM off, scene Single, retrigger on, drift 0) are
test configurations, never adapted presets, never coverage.

## Word lengths (normative; shared with SXT-022/SXT-026/SXT-033)

| Quantity | Format | Notes |
|---|---|---|
| samples / coefficients / gains / lag states | Q10.21, signed 32-bit | round-half-up products (`vm.qmul`) |
| AEG phase / sustain / rates | Q2.29, 32-bit | SXT-022 family |
| **sine phase, omega, omegaPrior/Step/Curr** | **Q3.28** radians, 32-bit | SXT-026a family; single wrap `phase -= (phase > π)·2π` (modern non-FM), full `clampToPiRange` floor-wrap on the fb-shifted argument x |
| feedback / FM lags (SurgeLag) | Q10.21 | rate lp = 0.004, lpinv = 0.996 quantized once |
| `dplaying` (legacy playingramp step) | Q10.21 | `qint(f32(1/50·44100/48000))` |
| unison constants | float32 emulation at quantization time, then Q10.21 | attenuation 1/√n (`_f32(1.0/_f32(√n))`), bias 2/(n−1) (double ctor), per-voice detune `udet_f·(bias·v+offset)` in float32 op order |

## Operation order (normative, per 64-OS-sample block)

LEGACY (fmlegacy 0, non-FM branch):
1. per unison voice u: `omega_u` constant per instance (quantization time);
   `SurgeQuadrOsc::set_rate(omega)`: dr = cos w, di = sin w (double math on
   the float value, quantized once), normalize (r, i) with the double
   1/sqrt exactly as `SineCore.set_rate` (SXT-026a).
2. per OS sample k, per voice u: `r' = dr·r − di·i`, `i' = dr·i + di·r`
   (Q10.21 qmul per product, saturating); `out = shape<mode>(r, i)`;
   `t = (out·out_attenuation)·playingramp[u]`; mono acc += t (the linear
   UnisonSetup pan law makes (panL+panR)/2 = 1 exactly — mono-inert,
   declared); `if playingramp < 1: playingramp = min(1, +dplaying)`
   (playingramp[0] = 1, others 0 at init; retrigger).
3. per OS sample: nothing else (no lags on the legacy path).

MODERN (fmlegacy 1):
1. per voice u: omega_u; omega-ramp machine: first block anchors
   omegaPrior = omega (omegaPriorValid latch), `omegaStep =
   (omega − omegaPrior)/64` (half-up; inert at constant pitch),
   `omegaCurr = omega − 31.5·omegaStep` (half-up), then omegaPrior = omega.
2. `fb_val = get_extended(fb)·(extend ? 4 : 1)` quantized once; FB lag
   newValue (first-run snap), FMdepth lag newValue(0) (FM off).
3. per OS sample k: `fbv = |FB.v|`, `fbneg = FB.v < 0`; per voice u:
   `lv = lv1[u]` (fb_mode = deform_type = type_1 = 0 — see deviations),
   `fba = fbneg ? (lv·lv)·fbv : lv·fbv`,
   `x = clampToPi(phase[u] + fba)` (floor wrap, integer-exact),
   `s = fastsin(x)`, `c = fastcos(x)` (exact Pade rationals, ONE final
   round — SXT-026a convention), `out = shape<mode>(s, c)`;
   `ramp = 1 if (u == 0 or not firstblock) else k/64` (BLOCK_SIZE_OS_INV);
   `t = (out·ramp)·out_attenuation`; acc += t;
   `lv0[u] = lv1[u]; lv1[u] = out`;
   `phase += omegaCurr; phase -= (phase > π)·2π; omegaCurr += omegaStep`.
   After the voice loop: FMdepth.process(); FB.process()
   (`v = v·lpinv + target·lp`).
4. `firstblock = false` after the first block.

BOTH, after the sample loop:
5. applyFilter: lowcut `coeff_HP(ω/2, 0.707)` TDF2 biquad, then highcut
   `coeff_LP2B(ω/2, 0.707)` (coefficients constant per fixture — the
   per-block recompute of constant coefficients is constant; the engine's
   ω>π identity guards fire at the default −60/70 in every carrier).
6. CharacterFilter (Warm one-pole b0 = 1−(1−2·5000/48000)², a1 = filt;
   Neutral bypass via doFilter=false; `starting` warm start
   priors ← output[0]).

`shape<mode>(s, c)`: all 32 modes in the pinned SSE op order on Q10.21
words — sign compares exact, qmul for products of two non-trivial words,
`*2`/`*0.5` as saturating shift / half-up shift, ±1 multiplies exact,
abs exact, quadrant divides (25/27) exact-then-round-half-up by the
integer quadrant (`qdiv(..., fb=0)`).

## Declared deviations (model vs pinned engine, budget-absorbed)

1. Fixed Q10.21 words / Q3.28 phase vs engine float32 SSE / double phase
   (round-half-up vs float rounding).
2. fastsin/fastcos: exact integer Pade evaluation with ONE final round vs
   the engine's per-op float32 (SXT-026a convention).
3. The legacy quadrature recurrence accumulates exactly (Q10.21) vs the
   engine's float32 rotation — the SXT-026a/F-033-1 class; detuned
   unison stacks decorrelate (dominant term in the measured uni>1 rows).
4. Modern path: the engine narrows the double phase to float32 at the
   fastsin input (`(float)phase[u]`); the model keeps the Q3.28 word
   (finer; abs error ≤ float32 ulp at |phase| ≤ 2π ≈ 3.7e-7 rad).
5. `FB.v` lag in Q10.21 vs engine double — constant targets converge to
   the target word ±1 LSB.
6. Unison pan: the modeled voice folds (panL+panR)/2 = 1 structurally
   (exact under the linear pan law); the engine's per-lane float32
   accumulate-then-fold rounds differently (≤ 1 LSB class).
7. Frequency-domain tables (pitch_to_omega, filter coefficients, set_rate
   cos/sin) evaluated from the pinned construction formulas in double and
   quantized once; the engine lerps float32 tables / uses float libm.
8. `fb_mode` = `p[sine_feedback].deform_type` is 0 (type_1) for every
   corpus-reachable state: load_xml defaults it to type_1 (=0) for
   deform-option params and save_xml always writes 0 (no UI writer for
   sine feedback). A hand-authored `deform_type="1"` attribute on a sine
   feedback param would switch the lastvalue blend to (lv0+lv1)/2 —
   UNOBSERVABLE through surgepy (documented exposure gap, same pattern as
   the SXT-011 send-bus gap); the fb_mode-1 machinery is implemented
   (selectable at instantiation) but no corpus fixture exercises it.
9. Sign compares at quantization zero: values with |x| < 2^-21 quantize to
   the Q zero word and lose their sign (the engine's float32 compare sees
   the true sign); bounded by the affected mode's jump at the boundary.
10. `vm.qmul(s, c)` product underflow: |s·c| < 2^-21 rounds to ±0 and can
    flip a q13-style sign compare; unreachable from unit-circle (s, c)
    pairs where both are tiny.
11. ADSR extensions evaluated in double at the pinned op order (engine:
    float32 per op): attack shapes a_s 0 (√phase) / 2 (phase²), decay
    shape d_s 2 (cube-root two-limits form; no case-1 gates). The landed
    SXT-033 file is imported unchanged (`AdsrClassic`); the sine leaf
    subclasses (`AdsrSine`).

## Finding: sine-shape streaming migrations (normalized authority)

The raw `.fxp` shape is pre-migration. At the pin, two migrations apply in
order: (1) `SurgePatch::load_xml` rev≤27 remaps odd raw shapes 1..7 →
28..31; (2) `SineOscillator::handleStreamingMismatches` at rev≤12 applies
the 20-entry wave_remap {0,8,9,10,1,11,4,12,13,2,3,5,6,7,14,15,16,17,18,19}
(quoted as data from the pinned GPL-3.0-or-later
`src/common/dsp/oscillators/SineOscillator.cpp`, `streamingRevision <= 12`
block; license decision record
[DR-0008](../../../decision-records/0008-sine-wave-remap-table.md))
with a range check that resets anything ≥ 20 to 0 (so a rev≤12 file stored
as 7 → load_xml 31 → reset 0). Only the normalized (post-migration,
post-load) value is used — the committed extractor verifies the live
readback against the graphs.jsonl value. Negative control: rendering a
fixture with the raw pre-migration shape (SXT040_NC_SHAPE_RAWVALUE) fails
the reference-budget check (Arp 2: raw 1 → normalized 28 is the recorded
slate example).

## Files

* `sine_model.py` — the frozen model (importable)
* `run_model.py` — renders a fixture sequence, writes `model.wav`,
  `model_trace.json`, and the RTL stimulus (`rtl/*.hex`)
* `fixture_config.py` — declared fixture overrides (extractor + renderer)
* `extract_inputs.py` — fail-closed extraction from the pinned engine
* `inputs/*.json` — committed carrier extractions (census-blob verified)

## Reproduce

```sh
python3 model/oscillators/sine/run_model.py --inputs \
    model/oscillators/sine/inputs/tentacles.json \
    --sequence seq-notes-repeated-v1 --out-dir /tmp/run --rtl
python3 tools/compare_sine_rtl_model.py --run-dir /tmp/run
python3 tools/compare_audio_reference.py \
    --ref reports/SXT-040/artifacts/tentacles__seq-notes-repeated-v1-ref.wav \
    --model /tmp/run/model.wav
```
