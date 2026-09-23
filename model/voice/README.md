# SXT-022 frozen fixed-point voice model (`model/voice/`)

Frozen reference for the SXT-022 RTL (`rtl/voice/tb_voice.sv`). The RTL must
match this model **exactly** (integer equality at every declared checkpoint;
`tools/compare_rtl_model.py`). Model-vs-pinned-engine agreement is a separate
claim governed by error budgets, which are **not frozen** — SXT-022 reports
achieved numbers only.

- Preset: `resources/data/patches_factory/Basses/Attacky.fxp`
  (census blob `4675e423a7489b02f501f7763b4760f64ab035f9`)
- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`)
- Inputs: `attacky_inputs.json` (engine-read state missing from
  `graphs.jsonl` schema rev 1.0.0) + modulation routings from
  `corpus/normalized/graphs.jsonl`

## SXT-026a extension (issue #48) — generalized voice class, FROZEN

The frozen class is extended (issue-body scope candidates: Sine oscillator,
IIR24 coupled-form filter, velocity modulation routes, scene FM routing with
muted FM sources, scene width at unison 1). The v1 (Classic/LP12) arithmetic
below is unchanged; class-v1 fixtures render bit-identically. Schema-2 input
sidecars (`*_inputs.json`, `extract_inputs_v2.py`) carry the parameterization;
`InputsV2` enforces the class fail-closed (`Refuse` → exit 2).

### Declared class bounds (fail-closed)

* As v1: single scene A, poly playmode, serial-1, waveshaper/lowcut off,
  o1-only mixer path, filter unit 2 Off, drift 0, portamento off, pan 0,
  pfg 0, vca_velsense 0, character Warm/Neutral, digital envelopes
  (`mode 0`, `d_s 0`; attack shape `a_s 1` or instant), osc1 keytrack on /
  pitch offset 0 / unison 1 / retrigger on.
* Filter unit 1: LP 12 dB **or LP 24 dB**, subtype Driven; `fu.keytrack` 0.
* Osc 1 Classic (v1 paths; sync 0, scene octave 0) **or Sine** with
  `sine_shape(mode) == 0`, `sine_FMmode == 0` (legacy path only), unison 1,
  retrigger on; lowcut/highcut in [−60, 70] (modeled biquads); the legacy
  path makes `sine_feedback` inert (never read) — any value accepted.
* Sine + `fm_switch == 2` (`fm_3to2to1`): muted Sine oscs 2/3 run as the FM
  source chain (osc2 FM'd by osc3, osc1 by osc2; `db_to_linear(fm_depth)`
  depth). `fm_switch == 0`: oscs 2/3 are not processed at all (engine
  process_block conditions) and osc1 runs the quadrature recurrence.
  FM depth must be **constant for the fixture**: sequences carrying CC/controller
  events are refused for Sine presets (the preset's modwheel scene route
  targets FM Depth).
* Modulation route vocabulary (order = md arrays): voice routes
  velocity(1)/keytrack(2) → {fu1 cutoff 308, fu1 reso 309, fu1 feg-mod-amt
  310, vca gain 298, fu2 314/315/318 (inert, unit off)}; scene routes
  modwheel(6) → {fu1 cutoff/reso (v1), FM depth 260}. Anything else refuses.
* Keytrack modsource output = `(state.pitch − keytrack_root)/12`, set at
  voice creation and refreshed AFTER each control pass's route application
  (declared 1-control-pass lag; constant per voice in this class).
* Scene octave `oct`: `state.pitch = key + 12·oct`; per-osc pitch adds
  `12·osc.octave`. Rendered pitches must lie in [24, 148].
* Scene width is structurally inert in this class (serial-1: the width path
  is only read for fc_stereo/fc_wide — SurgeVoice.cpp; A/B oracle probe
  committed in `reports/sxt-026a/`).
* Mono bus: L and R identical end-to-end (pan 0, width inert, serial-1
  route filter sends oscs to L only).

### Frozen Sine arithmetic (pinned: SineOscillator.cpp legacy path, FMmode 0)

1. Non-FM block (quadrature): `set_rate(omega)` — `dr = cos w`, `di = sin w`
   (double math, quantized once to Q10.21), then normalize `(r, i)`:
   `n = 1/sqrt(r² + i²)` (double on the Q words), re-quantize; init state
   `r = 0, i = −1` (retrigger). Per OS sample: `r' = dr·r − di·i`,
   `i' = dr·i + di·r` (Q10.21 qmul round-half-up per product).
   Value (mode 0) = `r`.
2. FM block: phase accumulator **Q3.28 radians**, init 0 (retrigger); per OS
   sample `phase += omega + qmul(fm_depth, master[k]) << (28−21)`, wrapped by
   the pinned `clampToPiRange` (integer-exact: `y = phase + π_q28`,
   `k = floor(y / 2π_q28)`, `phase = y − 2π_q28·k − π_q28`); value =
   `fastsin(phase)` (mode 0). `fastsin/fastcos` are the pinned JUCE Pade
   rationals evaluated in **exact integer arithmetic** (engine: float32 per
   op) with ONE final round-half-up to Q10.21 — this introduces a
   **declared audio-rate division**, diverging from cost assumption A-ALU-2
   (recorded for SXT-016; the RTL implements it as a wide behavioral
   divider).
3. `omega = 2π·MIDI_0_FREQ·note_to_pitch(pitch)/96000` (table formula per
   the declared deviation) quantized to Q3.28.
4. `applyFilter` (per block, in place): lowcut `coeff_HP(ω/2, 0.707)` TDF2
   biquad, then highcut `coeff_LP2B(ω/2, 0.707)` TDF2 biquad (coefficients
   constant per preset, `calc_omega` table formula), then the shared
   CharacterFilter (v1 component, per-osc state). FM sources are the
   fully processed (post-filter, post-character) blocks.
5. Output staging: pan 1/attenuation 1/playing-ramp 1 reduce to the identity;
   mixer level lag is level 1.0 (first-run snap).

### Frozen LP 24 dB/Driven arithmetic (pinned: Coeff_LP24, IIR24CFCquad)

* Coefficient maker as v1 except `Map4PoleResonance(Driven)`:
  `reso *= max(0, 1 − max(0, (f−58)·0.05))`, then `Q2inv = 1 − 1.05·clamp(reso, 0.001, 1)`
  (clamps RESO, not `t`). Same `resoscale`, `boundFreq`, `clipscale`,
  `ToCoupledForm`, `FromDirect` smoothing.
* Per OS sample: two coupled-form sections sharing C[0..7] — section 1 over
  `(f2_r0, f2_r1)` with input `x`, section 2 over `(f4_r0, f4_r1)` with
  input `y`; ONE clipgain state `f_clip = max(0.1, 1 − C7·y2²)` applied to
  all four registers; output `y2`.
* Serial-1 Mix1 blend (fc_serial1 ProcessFBQuad): `x = in·(1−Mix1) + FU1(in)·Mix1`
  with `Mix1 = min(1, 1 − bal)` (v1 presets: bal 0 ⇒ exact identity).
  Mix2 = min(1, 1+bal) = 1 for bal ≥ 0; unit 2 off ⇒ B-path input 0.

### Frozen parameterization boundary (model → RTL)

* `init.hex` words 0–39: unchanged v1 layout. Appendix 40+: `osc_kind`,
  `fu_poles`, `fm_depth`, `fm_mode`, `mix1`, `pitch_off1..3`, and per-osc
  lowcut/highcut biquad coefficients (hp/lp × 3, b0 b1 b2 a1 a2).
* `ctrl.hex` slot records grow 32 → 40 words: append `fvel`, `kt_word`,
  `sine_omega1..3` (Q3.28). Classic voices stream zeros there.
* Checkpoints: unchanged list + `f4_r0`, `f4_r1` (trace format 2).

### Applicability / negative controls

`InputsV2`/`run_model.py` REFUSE (exit 2) anything outside the class: e.g.
Mono-playmode presets (Quickspit — arithmetic overlap only, never a fixture),
other oscillator/filter types, out-of-vocabulary routes, CC events on Sine
presets, out-of-range pitches. The wrong-parameterization RTL mutant
(`rtl/voice/voice_wrongparam_mutant.sv`, forces `fu_poles` 12) must FAIL
exactness on LP24 fixtures; the v1 qmul-bias mutant must still FAIL.

## Frozen word lengths (v1)

| Domain | Format | Notes |
|---|---|---|
| samples, filter state, coefficients, gains, sinc table | **Q10.21** (signed 32-bit) | range ±1024; headroom for the filter's clipgain path |
| envelope phase / sustain / rates | **Q2.29** (signed 32-bit) | rates are control-plane words computed from the pinned rate table |
| `pitchmult_inv` | **Q13.18** | declared pitch range [24, 148] (asserted) |
| sinc sub-sample fraction (`lipol`) | 16-bit integer | derivative table pre-scaled by 1/65536 |
| Sine phase / omega (SXT-026a) | **Q3.28** (signed 32-bit, radians) | 2^-28 rad; drift ≤ 3e-3 rad over the longest fixture |

Arithmetic rules (FROZEN):

1. Every value is a Python `int` in two's-complement Q-format. No floating
   point at run time.
2. Products are exact 64-bit, then rounded **round-half-up** back to the
   target format: `r = (a*b + (1 << (s-1))) >> s`, `s = fa+fb-fq`, and
   saturated to the signed 32-bit range.
3. Divisions exist only at coefficient (block) rate (`qdiv`, round-half-up)
   — consistent with cost assumption A-ALU-2 (no audio-rate division).
4. The sinc sub-sample position truncates toward zero, matching the engine's
   `(unsigned int)` cast.
5. Frequency-domain conversions (note_to_pitch family, envelope-rate and dB
   tables) are evaluated in double precision against the pinned table
   *formulas* and quantized once (declared deviation: the engine lerps
   float32 tables; agreement is within one float32 ulp and is part of the
   model-vs-reference budget).

## Frozen block schedule (one 32-sample engine block)

1. **Dispatch**: events with `ceil(t/32) <= b` fire now. `note_on` creates a
   voice (constructor: envelopes `attack_from(0)`, one envelope step, ramp
   anchors, oscillator init with `oscstate = 0`, lags instantized).
   `note_off` releases the matching gated voice (envelope `release()`).
   `cc1` sets the modwheel FAST_LINE target.
2. **Voice control pass** (per voice, creation order): envelope step (amp
   then filter), modulated `cutoff_a = cut + depth*mw + envmod*feg_out`,
   `reso_a`, ramp targets `fbp_gain = db_to_linear(vca)*aeg_out`,
   `fbp_outl = 0.5*volume^3` (megapan(0) = 1, vs = 0).
3. **Oscillator block** (64 OS samples): `pitchmult_inv`, lag steps
   (`v += 0.05*(target - v)`), hpf target `min(integrator_hpf, 0.995^invt)`
   with a per-sample linear ramp `prev + round(d*(k+1)/64)`,
   `while oscstate < a_cov: convolute()`, `oscstate -= a_cov`, then the
   extraction loop (leaky integrator `osc_out = osc_out*hpf + ob - mdc*oa`,
   DC accumulator `mdc += dcbuffer`, character biquad), buffer clear,
   `bufpos` advance, wrap copy.
4. **Convolute** (per impulse): `ipos = trunc(oscstate*pitchmult_inv << 24)`,
   `delay = (ipos>>24) & 0x3f`, phase `m = (ipos>>16) & 0xff`,
   `lipol = ipos & 0xffff`; 4-impulse state machine (general sub/shape
   case); 12-tap windowed-sinc accumulation
   `ob += (sinc[m+k] + lipol*sincD[m+k]) * g`; DC-buffer impulse at
   `base + FIRoffset`; per-state rate update; `oscstate += rate` (max 0).
5. **Coefficient plane**: `MakeCoeffs(cutoff_a, reso_a)` for
   `fut_lp12/st_Driven` (boundFreq, Map2PoleResonance, ToCoupledForm with the
   `ai >= 8*1.19e-7` floor, `clipscale`), then `FromDirect` smoothing
   (`tC += 0.2*(N - tC)`, `dC = (tC - C)/64`; first run: `C = N`, `dC = 0`).
6. **Filter chain per OS sample** (fc_serial1, mixer level constant):
   `C[i] += dC[i]` (saturating), `IIR12CFC` coupled-form step with per-sample
   clipgain state `f_clip = max(0.1, 1 - C7*y^2)`, serial-1 routing (mix1 =
   mix2 = 1), per-sample gain/output ramps `start + round(d*(k+1)/64)`,
   scene accumulate (L and R identically — mono bus, pan = 0).
7. **Scene/output**: hard clip ±8 (declared engine default), halfband D2
   (M=6 steep; single pass — the R lane is identical on the mono bus),
   master amplitude (converged after settle), hard clip ±8, mono
   `(L+R)/2` with L == R, int16 conversion
   `int(clip(x, -1, 1) * 32767)` (truncation toward zero).

## Declared control-plane boundary (model → RTL)

Block-rate coefficient generation stays in the model and is streamed to the
RTL: envelope RATES (rate-table outputs), `pmi`, `pitchmult`, `a_cov`, hpf
target, filter `C[8]`/`dC[8]`, gain/output ramp targets, modwheel value,
master amplitude. The RTL reproduces the envelope state machines and the
complete audio-rate datapath, and must equal the model at every declared
checkpoint (state after blocks 0, 1, every 64th block, and every block of a
released voice) plus every output sample.

## Declared scope omissions (fail-closed in code where feasible)

* Scene drift: extracted and asserted **0** (determinism gate) — drift LFO
  noise cannot enter the slice; the RTL implements no RNG.
* Oscillators 2/3 are muted and retrigger-flagged; their free-running init
  consumes engine RNG but cannot affect audio (no noise/FM paths active).
* LFO1 processes in the engine but has no modulation destinations — omitted.
* Velocity → VCA gain is 0 (`vs = 0`) — velocity path omitted.
* Voice polyphony limited to 8 slots; portamento inactive (`porta` at min).
* Character filter supports Warm/Neutral only (preset is Warm).
* Envelope digital mode only, `a_s = 1`, `d_s = 0` (preset values).

## SXT-034 unison stack extension (frozen)

Extension of this model to unison stacks >1 voice (leaf #68, SXT-034),
cited from the pinned tree (read, not copied):

* `ClassicOscillator.cpp init` — per-voice init loop; `n_unison = limit(p[uni], 1, MAX_UNISON)`
  (engine clamps; the model REJECTS outside 1..16 — never a silent clamp),
  retrigger-on → `oscstate[i] = syncstate[i] = 0`, retrigger-off →
  `oscstate[i] = syncstate[i] = 0.5·rand_01()·ntpi(detune_i)` (wall-clock
  random in the engine; the model consumes DECLARED draw words — SXT-012
  quantified-variation class),
* `ClassicOscillator.cpp prepare_unison` +
  `sst-basic-blocks OscillatorDriftUnisonCharacter.h UnisonSetup` —
  `out_attenuation = 1/sqrt(n)` (Q10.21, quantized once; = 1.0 exactly at
  n=1), `detune_bias = 2/(n-1)` (n>1), `detune_offset = -1` (n>1),
* `ClassicOscillator.cpp convolute/process_block` — per-voice detune
  `detune_v = spread_ext·(bias·v + offset)` with `spread_ext = qint(12·f)`
  (ct_oscspread; drift asserted 0, no detune modulation in the fixtures),
  per-voice `t_v = ntpi_tuningctr(detune_v + l_sync)` and
  `t_inv_v = qdiv(1, t_v)` are BLOCK-RATE constants (streamed in the
  control plane; the engine recomputes them per call with `mech::rcp` —
  declared deviation: exact division vs SSE rcp approximation),
  voice-major fill loop `while oscstate_v < a_cov: convolute(v)` into the
  SINGLE shared `ob`/`dcb` buffer pair (engine memsets one oscbuffer per
  oscillator; unison adds impulse state machines, not buffers),
* unison pan spread is INERT in this slice: the oscillator's `stereo` flag
  is `is_wide = (fbc == fc_wide)` (SurgeVoice.cpp), not unison-driven; the
  fixtures are serial-1. `panLaw` satisfies `(panL+panR)/2 == 1` per voice
  (verified from UnisonSetup) — its mono cancellation is exact if a future
  leaf widens the bus.

Op order (per convolute, normative): unchanged SXT-022 order with
`g = qmul(g, out_attenuation)` inserted after the impulse-height state
machine and before the sinc accumulation; per-voice state replaces the
scalars (oscstate/state/last_level/pwidth/pwidth2/dc_uni are per-voice; the
impulse buffers, `mdc`, `osc_out`, `osc_out2`, hpf, filter chain and
envelopes are per voice SLOT, unison-invariant).

Declared max unison: **MAX_UNISON = 16** (SurgeStorage.h engine constant,
profile-v1 cap). Beyond-cap unison raises and renders nothing (NC-3).

Resource multiplication (honest): unison N multiplies the impulse state
machines (6 words/voice) and the convolute activity (~N×, modulated by the
per-voice detune rates); it does NOT multiply the impulse buffers (shared
by engine design), the voice filter chain, mixer, or scene decimator.

### Composition with SXT-026a (voice generality) and SXT-033 (classic slice) on the merged model

This section is the post-rebase freeze note (branch rebased onto the tree
that landed SXT-026a via #86, SXT-033 via #87, SXT-035 via #89 and
SXT-028a via #90); it states how the SXT-034 per-voice `t`/`t_inv`
constants compose with the overlapping oscillator semantics those leaves
froze. It is a documentation decision, not a git resolution.

1. Per-voice `t`/`t_inv` vs the SXT-033 sync machine — the SAME freeze
   decision. SXT-033's classic slice (`model/oscillators/classic/`) freezes
   `t_u[u] = ntpi_tuningctr(detune_u + min(l_sync, 156 − pitch))` as
   quantization-time constants per voice instance; SXT-034 freezes
   `t_v = ntpi_tuningctr(detune_v + l_sync_init)` the same way. They agree
   because the v1/v2 voice classes REFUSE sync ≠ 0 at load (SXT-026a gate:
   "classic sync param p[4] not 0"), so `l_sync` instantizes and stays 0,
   the lag machinery (`l_sync += 0.05·(t_sync − l_sync)`) is carried but
   inert, and `min(l_sync, 156 − pitch)` degenerates to 0 in both. Neither
   leaf models runtime sync modulation of `t`; a future leaf that lifts the
   sync refusal must re-open BOTH freezes together (the per-voice constants
   and the impulse-rate consumption are shared schedule).

2. Drift — refused at 0 on all sides. #86's determinism gate refuses
   scene drift ≠ 0; SXT-034 asserts drift 0 and takes detune only from the
   static `ct_oscspread` path (no detune modulation routed); SXT-033 gates
   its drift-LFO identically. No unison/drift interaction is modeled
   anywhere on the merged tree.

3. The SXT-033 pitch-helper finding — LIVE at uni>1, kept un-absorbed, and
   now ALSO routed from this leaf. SXT-033 documented that the landed
   SXT-022 helpers (`voice_model.ntpi_tuningctr` / `ntpi_ignoring_tuning`)
   interpolate the fractional semitone with a term 12000× steeper and
   sign-flipped vs the pinned `table_two_to_the_minus` construction
   (`classic_model.py` carries the corrected helper; the finding was
   "routed, not absorbed"). In the SXT-022 slice the flawed fractional term
   is INERT (its argument is identically 0 → the term is exactly 1), and
   the uni=1 regression is pinned byte-identical to the SXT-022 artifact
   (sha `6a73bb9a…`) — which is why THIS model keeps the SXT-022 helper.
   At uni>1 the argument `detune_v + l_sync` is NONZERO for every detuned
   voice, so the flawed term is LIVE in this leaf's `t_v`/`t_inv_v`. This
   leaf does not tune around it: the uni>1 max/spectral budget misses
   (EVIDENCE §4) are reported WITH the flawed term in the model, and the
   finding is routed to the SXT-013/#12 freeze together with SXT-033's
   finding as a named candidate contributor. Resolution (adopting the
   corrected helper into `voice_model.py`) belongs to the freeze owner;
   it would break the uni=1 byte-identity pin at 0 LSB (the term is
   exactly 1 at argument 0 — the artifact sha is unaffected) and change
   uni>1 numbers only.

4. Merged control-plane word map (normative; this is the resolved overlap
   of the two appendices that both targeted word 40 on their branches):
   init words 0..39 are the frozen v1 layout; 40..77 the SXT-026a
   parameterization appendix (osc_kind, fu_poles, fm_depth, fm_mode, mix1,
   pitch offsets, per-osc hp/lp biquads); 78..127 the SXT-034 unison
   appendix (uni count 78, out_attenuation 79, per-voice
   t/t_inv/init-oscstate at 80+3u); 128.. the per-creation init-draw table
   (count at 128, sets at 129+16·set). Ctrl slot word 31 (v1 "reserved")
   now carries `draw_set_index` for created voices; words 32..39 remain
   the SXT-026a fvel/kt/sine-omega group.

5. SXT-034 inside the SXT-026a classes. `InputsV2` carries the unison
   inputs at their class identity — `n_unison = 1`, `spread = 0`,
   `retrigger = on` (the #86 uni/rt gates refuse anything else; declared
   draws are a v1-override mechanism and `InputsV2.next_draw` fails loud).
   Classic-kind V2 voices therefore exercise the full per-voice machinery
   at the uni=1 identity (bit-identical: `out_attenuation = 1.0` exactly,
   detune 0); sine-kind voices have no unison path. Uni>1 fixtures remain
   v1-class declared overrides as declared in §2 of the SXT-034 evidence.

## Files

* `voice_model.py` — the frozen model (importable; see module docstring)
* `run_model.py` — renders a fixture sequence, writes `model.wav`,
  `model_trace.json`, and the RTL stimulus (`rtl/*.hex`)
* `extract_inputs.py` / `attacky_inputs.json` — fail-closed extraction of
  the normalized voice inputs from the pinned engine (SXT-022 base slice)
* `extract_uni_inputs.py` / `attacky_uni*_inputs.json` — SXT-034: the same
  extraction with the declared unison-voices override applied and read
  back (test configuration on the census-verified carrier)
* `render_uni_reference.py` — SXT-034: pinned-engine reference renders
  under the declared override (SXT-012 render policies)
* `sequences/sxt034-*.json` — leaf-local sequences (smoke; non-retrigger
  draw mechanism fixture)

## Reproduce

```sh
python3 model/voice/run_model.py --sequence seq-notes-repeated-v1 \
    --out-dir /tmp/run
python3 tools/compare_rtl_model.py --run-dir /tmp/run
python3 tools/compare_audio_reference.py \
    --ref fixtures/render-out/reference-dry.wav --model /tmp/run/model.wav
```

---

# SXT-032 frozen fixed-point LFO modulator slice (`lfo_model.py` + `tb_lfo.sv`)

Leaf #66 (SXT-032, mod behavior `lfo`, modsource ids 17..22 = ms_lfo1..6).
The LFO is a CONTROL-RATE modulator: one output value per 32-sample engine
block, evaluated inside `SurgeVoice::calc_ctrldata` **before** the envelopes
step (`lfo[0]` always; LFOs 2..6 iff routed — `prepareModsourceDoProcess`
recomputes that gate from the live routings every block; empirically verified
on the pinned oracle: a routed LFO2 processes with its own definition). Voice
creation attacks all six instances and the constructor's `calc_ctrldata<true>`
pass skips LFO-sourced routes (`applyModulationToLocalcopy<noLFOSources>`).

## Frozen word lengths (SXT-032 additions)

| Domain | Format | Notes |
|---|---|---|
| LFO phase, LFO-EG phase/levels | **Q2.29** | same envelope-phase family as SXT-022 |
| waveform values (`io2`) | **Q4.27** | sine/tri/square/ramp internal domain |
| wst_sine table | **Q10.21** | 1024 entries, float32-rounded construction |
| routed modulation output | **Q10.21** | `env_val · magnf · io2` |

## Frozen op order (one block, one instance)

1. `phase += frate` (Q2.29; `frate = envelope_rate_linear_nowrap(-rate)`,
   streamed control word); single wrap at 2^29 (frate < 1 declared).
2. LFO-EG state machine `lfoeg_delay -> attack -> hold -> decay -> stuck`
   (+ release on voice release, gated by `release < val_max(8)`), linear
   segments against `sustain`; rates are streamed per-stage words.
3. Waveform eval (frozen set): **sine** = wst_sine warp lookup at
   `x = 2 − 4·phase` (`t = x·256 + 512`, trunc index, Q10.21 lerp; deform 0
   makes bend3 the identity), **tri** = `−1 + 4·min(p, 1−p)`, **square** =
   sign of `p − (0.5 + 0.5·deform)`, **ramp** = `1 − 2·p`. Everything else is
   refused by the extractor (noise/snh = engine RNG; stepseq = grid outside
   normalized schema rev 1.0.0; mseg/formula not exposed by surgepy;
   lt_envelope; deform ≠ 0 on the type_3 shapes needs runtime sin).
4. Unipolar fold `0.5 + 0.5·io2`; output `(env_val · magnf · io2)` with
   `magnf = limit(magnitude, −3, 3)` (get_extended is the identity for
   ct_lfoamplitude); round-half-up to Q10.21.
5. Attack: EG-min flags (quantized-time facts, streamed like the SXT-022
   instant-attack flags), trigger-mode phase restart
   (keytrigger/freerun-at-songpos-0 both anchor at `start_phase`), then the
   unconditional shape adjustment (tri bipolar `+0.25`, sine unipolar
   `+0.75`).

Route application (voice level, after the envelope step, per
`applyModulationToLocalcopy`): `localcopy[dst] += depth · output` for the
frozen destination classes **Filter 1 Cutoff** and **Filter 1 Resonance**
only; any other destination class is fail-closed.

## Declared scope omissions (SXT-032; recorded, never guessed)

* rate `temposync` / `deactivated` flags are not observable through surgepy;
  the frozen model implements the non-temposync, non-deactivated paths (at
  the pinned 120 BPM the temposync rate formula agrees with the table path
  up to the declared table-lerp deviation).
* LFO-parameter destinations, pitch/volume/morph/keytrack/... destinations,
  scene LFOs (ms_slfo1..6), step-seq grids, MSEG/Formula, noise/S&H, and
  deform ≠ 0 bends are outside the slice (extractor refuses).
* Double-precision rate/table evaluations quantize once (same declared
  deviation as SXT-022); the engine's float32 phase accumulation vs the
  fixed-point phase is part of the model-vs-reference budget.

## Files (SXT-032)

* `lfo_model.py` — frozen LFO model (importable)
* `extract_lfo_inputs.py` — fail-closed extractor + fixture routes
* `attacky_lfo_inputs.json` — committed extraction (census-blob verified)
* `run_lfo_model.py` — runner (SXT-022 trace schema + LFO records + RTL hex)
* `rtl/voice/tb_lfo.sv` — LFO control-plane RTL (exactness:
  `tools/compare_lfo_rtl_model.py`; the SXT-022 `tb_voice.sv` audio datapath
  is UNCHANGED and runs against the LFO-influenced streamed control words)

---

# SXT-035 frozen scene-modwheel route extension (`run_mw_model.py` + `tb_mw.sv`)

Leaf #69 (SXT-035, mod behavior `modwheel`, pinned modsource id
6 = `ms_modwheel`). This section generalizes the landed SXT-022 modwheel path
(controller → FAST_LINE smoothing → route scaling → destinations); it does
not fork it. Landed fixtures (SXT-022 v1, SXT-026a bells, SXT-032 LFO)
render **bit-identically** after this extension (verified against the
committed artifact hashes).

## Pinned-source citations (read, not copied)

* `src/common/ModulationSource.h` `ControllerModulationSourceVector`
  (NDX=1): `set_target(f)` stores `target = f; startingpoint = value`;
  `process_block` → `processSmoothing(FAST_LINE, …)`:
  `sampf = samplerate/44100; da = (target − startingpoint)/(50·sampf)`;
  `b = target − value`; `if |b| < |da|: value = target else value += da`.
  `bipolar = false` → the modwheel output range is [0, 1].
* `src/common/SurgeStorage.h:2063`: `smoothingMode = FAST_LINE` is the
  storage default (the constructor argument for the scene modwheel).
* `src/common/SurgeSynthesizer.cpp` `channelController` case 1:
  `fval = value·(1/127)`; `set_target(fval)` on **every scene's**
  `modsources[ms_modwheel]` (single-scene class ⇒ one instance).
* `src/common/SurgeSynthesizer.cpp` `process`/`processControl`: the scene
  modwheel `process_block()` runs once per engine block behind
  `modsource_doprocess[ms_modwheel]` (always true for a routed modwheel).
  The exact interleaving with voice control passes is not observable through
  surgepy; the **declared order (unchanged from SXT-022)** is: controller
  events dispatch → per-voice control passes read the CURRENT value → the
  smoother steps at the end of the block.

## Frozen model additions (word lengths unchanged)

* The landed `Modwheel` class (Q10.21 `value`, `target`, `startingpoint`;
  `inv = qint(1/(50·48000/44100))`; FAST_LINE step exactly as cited) is
  reused unchanged — the smoothing algorithm exists exactly once.
* Scene-modwheel route vocabulary (destination ids = normalized `md` ids):
  **Filter 1 Cutoff (308), Filter 1 Resonance (309), VCA Gain (298)**, plus
  the landed FM-Depth (260, Sine class, CC-refused). Route application per
  control pass: `param += qint(depth) · value` (Q10.21 `qmul`, saturating
  add), in `md`-array order, into the local parameter accumulator before
  use; `mod_vca_db` accumulates velocity- and modwheel-sourced VCA terms in
  the same accumulator (engine `applyModulationToLocalcopy` localcopy
  semantics), consumed by `db_to_linear` in the gain target. Anything else
  is refused at extraction (fail-closed).
* Route-depth words are the normalized `md` raw depths (`qint(r[5])`), same
  provenance rule as the landed cutoff/reso routes; runtime fixture routes
  are engine readbacks (`getModDepth` raw + `getNormalizedDepth`) recorded in
  the committed sidecar.
* RTL schedule notes (SXT-035 findings; `tb_voice.sv` corrected to the
  frozen model order — landed fixtures bit-identical before/after):
  (1) the per-sample gain/output ramp products are evaluated at 64 bits
  (`d_gain·(k+1)` overflows the 32-bit self-determined width once the
  VCA-Gain route drives `fbp_gain` to ~2^28); (2) the ±8 scene hard clip is
  applied BEFORE the halfband decimator (v1 step 7), not after it — the two
  placements are equivalent only while the scene bus never saturates, and
  the landed fixtures never saturate. Both corrections mirror the frozen
  model exactly; the model did not change.
* Known landed inconsistency (recorded, not reconciled here):
  `run_lfo_model.py` still emits 32-word slot records (pre-#48 layout)
  while `tb_voice.sv` streams 40-word records; re-running the SXT-032
  voice pairing requires regenerating its stimulus in the v2 layout
  (SXT-032 owner).
* Declared scope (unchanged omissions plus): per-scene modwheel instances
  beyond scene A, bipolar/LEGACY/SLOW_EXP/FAST_EXP smoothing modes,
  modwheel→LFO-amplitude / EG-times / osc pitch-volume-width / FX-send
  destinations (present on the leaf's carriers — refused, see
  `reports/sxt-035/`), modwheel-as-a-mod-destination. Multi-scene smoothing
  (one instance per scene, stepped per scene) is out of the single-scene
  class.
