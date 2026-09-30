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

### DECLARED word-length consequence: the scene decimator does not settle to zero (F-176-2, issue #181)

`HalfbandD2` — the shared Q10.21 scene decimator (step 7 below) used by every
consumer of this model — **has a zero-input dead band and therefore does not
return to the zero state after its input goes silent.** Rule 2's round-half-up
`qmul` gives the allpass recursion `y[n] = x[n-2] + a·(x[n] − y[n-2])` a
fixed point at a non-zero state, so after the last voice dies the decimator
holds a *permanent* alternating-sign (output-Nyquist, period-2) output instead
of decaying to 0. This is **declared as a property of the frozen model**
(SXT-017 option (a)), not a defect to be silently fixed: changing it is a
contract revision owned by SXT-017 / [#12](https://github.com/2AMLogic/gf180-surge/issues/12).

Declared bound, measured over a declared input sweep (315 cases: impulse, DC,
sine, square, two-tone and seeded noise, amplitudes from 1 Q10.21 LSB to the
±8.0 `sceneout` clip that every consumer applies upstream, frequencies from
0.002 to 0.5 of the 96 kHz decimator input rate including the whole stopband;
each case followed by silence, each settled amplitude obtained **exactly** by
zero-input state recurrence rather than by observing a finite tail):

| quantity | value |
|---|---|
| **worst settled peak** | **36 Q10.21 LSB** = 0.5625 int16 LSB ≈ **−95.3 dBFS** |
| period of every non-zero cycle | 2 output samples (24 kHz, the output Nyquist) |
| cases with a non-zero cycle | 306 / 315 (9 settle to exactly 0) |
| largest lead-in before the cycle is entered | 2,304 input samples (36 blocks) |
| worst case above one int16 LSB? | **no** (one int16 LSB = 64 Q10.21 LSB) |

Consequences that follow, and only these:

* **It cannot reach an int16 render at any master gain below 64/36 = 16/9 ≈
  1.7778.** 36 Q10.21 LSB is 0.5625 int16 LSB, so `int(clip(x,−1,1)·32767)`
  truncates it to 0 unless the master amplitude reaches that crossing point
  (one int16 LSB is 64 Q10.21 LSB). Measured in situ after the last
  voice dies: **±1** Q10.21 LSB on `seq-notes-repeated-v1` (voice leaf), **±2**
  on `horn / seq-notes-repeated-v1` (Classic), **0** on `tentacles /
  seq-notes-repeated-v1` (Sine).
* **It is not a defect of the recursion.** The same recursion with the same
  quoted coefficients in float64 decays to 1.8e-322 (float64 subnormals) over
  the same silence, so the dead band is the quantizer. Whether the *pinned*
  float32 kernel settles to zero is **NOT_RUN** — it needs the external oracle
  host and is not assumed.
* **RTL reproduces it exactly** (claim (1)). All **four** committed RTL copies
  of the cascade — `rtl/voice/tb_voice.sv`,
  `rtl/oscillators/classic/tb_classic.sv`, `rtl/oscillators/sine/tb_sine.sv`
  and, since the #180 contract revision moved that leaf's decimator to a
  per-scene stage, `rtl/oscillators/wavetable/tb_wavetable.sv` — were spliced
  verbatim and matched the model over the settled region with 0 mismatches. The
  ring-out region is inside the committed compared window of the voice, Classic
  and Sine leaves (measured by re-running their own comparators); the wavetable
  leaf's comparator now compares every 48 kHz sample too, but that leg is
  **NOT_RUN** here — its model render needs the external pinned asset root.
* **A musically silent scene is not numerically silent.** Any future hardware
  idle-noise, idle-power or output-stage-gain claim must carry this forward: a
  permanent 24 kHz tone at −95 dBFS is inaudible in an int16 render and can
  still be a real measurement after an output stage's own gain.

Evidence, per-case amplitudes, the RTL check and the failure control:
`reports/halfband-limit-cycle/EVIDENCE.md`
(`tools/measure_halfband_limit_cycle.py`). **Not** covered by that bound:
`model/effects/type-distortion*/`'s own `HalfbandD2` is a different class
(`HalfRateFilter(M=3)`, Q24.43 state, oversampling rather than scene
decimation) and is unmeasured.

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
   The halfband D2 stage does **not** settle to zero on zero input — see the
   declared ≤ 36 Q10.21 LSB zero-input limit cycle above (F-176-2, #181).

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
* Formerly-recorded landed inconsistency (resolved by #175): `run_lfo_model.py`
  and `run_mw_model.py` used to emit slot records / `init.hex` short of the
  layout `tb_voice.sv` streams; both runners now emit the full SXT-034
  unison appendix + draw table (`run_model.py`'s reference layout), so the
  voice-datapath pairing is re-runnable at HEAD for both leaves.
* Declared scope (unchanged omissions plus): per-scene modwheel instances
  beyond scene A, bipolar/LEGACY/SLOW_EXP/FAST_EXP smoothing modes,
  modwheel→LFO-amplitude / EG-times / osc pitch-volume-width / FX-send
  destinations (present on the leaf's carriers — refused, see
  `reports/sxt-035/`), modwheel-as-a-mod-destination. Multi-scene smoothing
  (one instance per scene, stepped per scene) is out of the single-scene
  class.

# SXT-042 frozen keytrack modsource (`run_kt_model.py` + `tb_kt.sv`)

Leaf #76 (SXT-042, mod behavior `keytrack`, pinned modsource id
2 = `ms_keytrack`). This section generalizes and freezes the keytrack
plumbing landed under SXT-026a (#48) as its own leaf with an exact RTL
slice and live negative controls; it does not fork it. Landed fixtures
(SXT-022 v1 ×3, SXT-026a bells smoke + canonical, SXT-035 modwheel ×3)
render **bit-identically** after this extension (verified against the
committed artifact hashes).

## Pinned-source citations (read, not copied)

* `src/common/ModulationSource.h`: `modsources` enum, `ms_keytrack = 2`.
* `src/common/dsp/SurgeVoice.cpp`:
  - voice ctor: `modsources[ms_keytrack] = &keytrackSource;` followed by
    **`keytrackSource.set_output(0, 0.f);`** — the source starts at ZERO
    (unlike `velocitySource.init(0, state.fvel)`, which starts at the real
    value) — then `applyModulationToLocalcopy<true>()` and
    `calc_ctrldata<true>(0,0)` both run with keytrack = 0;
  - `calc_ctrldata`: `memcpy(localcopy, paramptr)` →
    `applyModulationToLocalcopy()` (reads the value installed by the
    PREVIOUS pass) → … → `state.pitch = state.pkey + state.scenepbpitch` →
    `modsources[ms_keytrack]->set_output(0, (state.pitch −
    (float)scene->keytrack_root.val.i) * (1.f/12.f))`.  This is the
    declared 1-control-pass lag, and its initial value is 0;
  - `applyModulationToLocalcopy`: `localcopy[dst].f += depth ·
    source_output · (1 − muted)` over `scene->modulation_voice` in array
    order (the normalized `md` order);
  - `switch_toggled()` recomputes the same keytrack expression and
    re-applies ONLY the keytrack rows into `localcopy` after the ctor's
    `calc_ctrldata`; in this class keytrack routes reach filter parameters
    only, which the ctor pass does not propagate, so the model's ctor pass
    is unaffected (verified: render bit-identical).
  - **Distinct quantity, do not conflate**: `float keytrack = state.pitch −
    keytrack_root` (raw semitones) is the *filter keytrack parameter* path
    (`localcopy[id_kta].f * keytrack`); the frozen class pins
    `fu.keytrack == 0`, so it is inert here. The ms_keytrack MODSOURCE is
    the same difference divided by 12.

## Frozen model additions (word lengths unchanged)

* **Keytrack word** (`voice_model.keytrack_word`): Q10.21,
  `qint((pitch_voice − keytrack_root)/12)`, one round-half-up at
  quantization time. `pitch_voice = key + 12·scene_octave` (portamento off,
  bend 0, `scenepbpitch` reduces to the octave term in this class).
  **Per voice instance**, never shared: one 32-bit word per voice.
* **Initialisation and refresh**: the word is **0** for a voice's first
  control pass and is refreshed to the pitch-derived value at the END of
  every control pass, exactly as cited above. Because pitch is constant per
  voice in this class, every later pass reads the same value, so inverting
  the refresh point is bit-inert here — an inertness probe records that
  (`reports/SXT-042/artifacts/negative-control.txt`), it is not a control.
* **Integer-exact RTL equivalent** (`tb_kt.sv kt_word_of`): with
  `n = pitch_voice − keytrack_root` an integer,
  `kt = floor((n·2^20 + 3) / 6)` (floor toward −inf). This is exact because
  `n·2^21/12` has fractional part 0, 1/3 or 2/3 and can never be a rounding
  tie; the model and the RTL are held to integer equality on it.
* **Destination class**: `{308 Filter 1 Cutoff, 309 Filter 1 Resonance,
  310 Filter 1 FEG Mod Amount}` live, `{314, 315, 318}` accepted-inert
  (filter unit 2 is Off in the class). Keytrack → `298 VCA Gain` is the most
  common corpus keytrack destination but is **not** in the frozen class
  (`VOICE_ROUTE_VOCAB[KEYTRACK_SRC]`), and everything else is refused.
* **Route application**: `param = sat(param + qmul(qint(depth), value))` in
  `md`-array order over the merged velocity+keytrack route list, into the
  localcopy accumulators (`mod_cutoff`, `mod_reso`, `mod_envmod`,
  `mod_vca_db`); `qmul` is Q10.21 round-half-up with int32 saturation.
  Depth words are the normalized `md` raw depths (`qint(r[5])`).
  `kt_route_sums` (cutoff/reso/feg-mod) are observation-only checkpoints.
* **The route pass is fail-closed in its own right** (not only at parse
  time): an unrecognised destination reaching `_apply_voice_routes` raises
  `Refuse` instead of being dropped.
* **F-042-2 (fixed here)**: the classic-kind branch of
  `VoiceV2._calc_ctrldata` previously read the raw parameters and never ran
  the voice-route pass, so a classic-kind fixture carrying velocity/keytrack
  routes would have dropped them silently. Both kinds now run one route
  pass. No landed fixture carried such a route, so every landed render is
  unchanged (verified bit-identical).

## Declared control-plane boundary (model → RTL, SXT-042 slice)

* `kt_init.hex`: `[total_blocks, keytrack_root, scene_octave, cutoff_q,
  reso_q, envmod_q, vca_q, n_routes]`.
* `kt_routes.hex`: `(src_code, dest_code, depth_q21)` per route in `md`
  order (`src` 0 = velocity, 1 = keytrack; `dest` 0..6 = fu1 cutoff / fu1
  reso / fu1 feg-mod / vca gain / unit-2 ×3).
* `kt_ctrl.hex`: per block `[b]` + per slot `[active, key, fvel_q21]`. The
  RTL derives the keytrack word itself from `key`; it is not streamed.
* Checkpoints (integer equality, every running voice, every block):
  `kt_word`, the three `kt_route_sums`, and `mod_cutoff` / `mod_reso` /
  `mod_envmod` / `mod_vca_db`.

## Declared scope omissions (SXT-042; recorded, never guessed)

Keytrack → VCA Gain / pan / volume / osc parameters / EG times / LFO
amplitudes / FX (all present in the corpus — refused, see
`reports/SXT-042/`), filter-unit-2 destinations as live paths, scene B,
pitch-bend or portamento contributions to `state.pitch` (which would make
the 1-control-pass lag observable), and MPE/tuning-dependent `octaveSize`.
Keytrack as a modulation DESTINATION is not modeled.

# SXT-036 velocity / release-velocity route extension (frozen; #70)

Model: `model/voice/run_vel_model.py` (`VelVoice` over `VoiceV2`); RTL
control-plane schedule: `rtl/voice/tb_vel.sv`; exactness harness:
`tools/compare_vel_rtl_model.py` (+ `tools/compare_rtl_model.py` on the
unchanged datapath); evidence `reports/SXT-036/EVIDENCE.md`.

Pinned facts (surge@58914e59c608ed4384ba6002e44c3465c58b2e71, cited, not
copied): `SurgeVoice.cpp` ctor sets `state.fvel = velocity/127`,
`velocitySource.init(0, fvel)`, `releaseVelocitySource.set_output(0, 0)`;
`SurgeVoice::release()` sets the release-velocity source to
`releasevelocity/127`; `applyModulationToLocalcopy` does
`localcopy[dst] += depth * source` after scene modulation. Modsource ids:
`ms_velocity` = 1, `ms_releasevelocity` = 30.

Word lengths and op order (all Q10.21, 32-bit, saturating adds):

1. `vel_q = qint(midi/127) = (midi*2^22 + 127) // 254` (round-half-up,
   exact integer form; asserted equal to the float quantizer for 0..127).
   Latched at voice construction; `relvel_q` = 0 at construction, set to
   `vel_q(release_midi)` on release (same block's control pass reads it).
2. Per control pass, per voice: scene modwheel routes first (landed SXT-035
   table), then voice routes in `md` order: `term = qmul(qint(depth), src)`
   (Q10.21 `qmul`, round-half-up, saturating); `param = sat(param + term)`.
   The per-destination sums of terms are the RTL checkpoint words.
3. Destination class (frozen): Filter 1 Cutoff 308, Filter 1 Resonance 309,
   Filter 1 FEG Mod Amount 310, VCA Gain 298 (`mod_vca_db`, shared with the
   modwheel VCA term). Anything else is refused (exit 2).
4. Per-instance state: one `{vel_q, relvel_q}` pair per voice slot; never
   shared across voices or scenes. VCA-Gain velocity terms make the
   constructor gain anchor (`SetQFB(0,0)`) per-voice; it is streamed in
   `tb_voice.sv` slot word 37 under flags bit 4 (legacy stimuli never set
   bit 4: landed fixtures unchanged).
5. Fixture: `attacky_vel_inputs.json` holds DECLARED synthetic route depths
   on the landed Attacky class; they are NOT engine readbacks (no oracle on
   the authoring host, #96) and must be re-extracted or confirmed on an
   oracle host (#232) before any reference-budget number is produced.
   `model/voice/audit_vel_carriers.py` records, from `graphs.jsonl` + the
   census alone, why the fixture substitutes Attacky for the carriers named by
   #70: none of those carriers has an `ms_releasevelocity` route at all, and
   only `Bad News.fxp` has a velocity route inside the frozen destination
   class. Attacky itself has none, hence declared routes.
6. Stimuli: `tools/vel_declared_coverage.py` runs the three
   `fixtures/sequences/seq-notes-*` sequences named by #70 through this model
   and both exactness harnesses. They are monophonic, so they do NOT
   discriminate rule 4 (per-instance state) — `tools/vel_negative_controls.py`
   reports those two controls `NOT_RUN` on such a stimulus rather than passing
   them, and the overlapping leaf-local `sxt036-vel-overlap-v1` sequence stays
   the per-instance-state carrier. The same driver also renders
   `seq-poly-8-v1`, the only polyphonic note fixture committed in
   `fixtures/sequences/`, and measures that it holds eight voices at a single
   velocity/release velocity, so no committed shared fixture discriminates
   rule 4 either.
7. Parameter corners (frozen; driver `tools/vel_param_corners.py`, transcript
   `reports/SXT-036/artifacts/param-corners.{txt,json}`, stimulus
   `model/voice/sequences/sxt036-vel-corners-v1.json`):
   * **Source-word domain.** `vel_q` is a 128-entry table; it is checked
     EXHAUSTIVELY (all 128 words, RTL `vel_rom` lifted verbatim out of
     `rtl/voice/tb_vel.sv` vs the model quantizer), not only at the corners.
     `vel_q(0) = 0`, `vel_q(127) = 2^21` exactly. Velocities 1/63/126 give ODD
     words (16513 / 1040319 / 2080639), which is what makes a depth of exactly
     ±0.5 an exact round-half-up tie.
   * **Destination extents (derived, not read back).** `depth_raw /
     depth_normalized` in `corpus/normalized/graphs.jsonl` gives each
     destination's full extent, agreeing across hundreds of independent rows:
     308 = 130.0 (2914 rows, 0.19 % spread), 309 = 1.0 (874 rows), 310 = 192.0
     (483 rows), 298 = 96.0 (838 rows). Observed normalized depth range of both
     sources over the whole corpus: [−1, +1]. These are corpus-pipeline values
     and therefore FALSIFIABLE PREDICTIONS for the oracle host (#232), never
     reference values.
   * **Declared corner set.** normalized depth ±1 (`depth_raw` = ±extent),
     mixed sign (velocity +1 / release velocity −1), the smallest nonzero model
     depth (`depth_q` = ±1), the rounding-tie depth ±0.5, and the largest
     `|depth_raw|` each source/destination pair actually shows in the corpus.
   * **Checkpoint-word precondition.** The per-destination route sum is a
     32-bit signed word in the RTL; the frozen checkpoint definition holds
     while `|sum| ≤ 2^31−1`. Worst declared corner: 805,306,368 (both sources
     at full scale onto 310, the widest destination), i.e. **2.67× headroom**.
     Beyond ≈2.67× full-scale depth the RTL word wraps while the model's
     Python sum does not; that is outside the declared range, is demonstrated
     by the `over-range-accumulator` control, and is recorded rather than
     designed around.
   * **Controls at the corners.** the `round-trunc` RTL mutant must FAIL on the
     tie corner (it does: 44 mismatches) and the `rom-floor` mutant must FAIL
     the exhaustive ROM check (it does: 63 of 128 entries). A corner set that
     could not distinguish round-half-up from truncation would not be freezing
     the rounding rule.
8. State rules, their controls, and the scene boundary (fourth increment;
   census `tools/vel_state_coverage.py` -> `reports/SXT-036/artifacts/
   state-coverage.{txt,json}`):
   * **Construction re-initialization (frozen).** A voice slot is reused. The
     cited ctor sets `state.freleasevel = 0` /
     `releaseVelocitySource.set_output(0, 0)`, so `relvel_q[slot]` is cleared
     ON CREATE and the previous occupant's release velocity is never inherited
     (`tb_vel.sv` create branch; model `VelVoice.__init__`). The power-on reset
     of all eight slot register pairs is a DIFFERENT thing and is unchanged.
     Controls: `--stale-slot-relvel` (model) and the `stale-slot-reinit` RTL
     mutant, both of which must FAIL exactness (they do: 42 mismatches each,
     first at block 1200 slot 0 `relvel_q` model=330260 vs rtl=0).
   * **Release-latch timing (frozen).** `SurgeSynthesizer::releaseNote` stamps
     `state.releasevelocity` and calls `release()` before the next block, so
     the release-velocity word is visible to THAT block's control pass. Control:
     the `release-one-block-late` RTL mutant moves the latch after the control
     pass and must FAIL (it does: 15 mismatches on the leaf-local stimulus, 3
     on `seq-notes-holds-v1`).
   * **Scene boundary — what is NOT established.** The frozen destination class
     is scene A only (308/309/310/298). A scene-B destination is REFUSED, not
     folded in: control R2 replays the real route the named carrier
     `House Of Chords.fxp` carries (`ms_velocity` -> 502 `B Osc 1 Sync`, scene
     index 1) and the runner must exit 2. That is a refusal, not a
     demonstration: this leaf's model instantiates ONE scene, so the "state is
     never shared across scenes" half of #70's per-instance rule has **no live
     control here** and is NOT claimed. It needs a second scene in the model
     (outside this leaf) to become testable.
   * **Stimulus preconditions and measured coverage.** Three preconditions
     decide whether these controls can fire: `per_instance` (>=2 concurrent
     voices with distinct source words), `slot_reuse` (a slot reused after a
     nonzero release velocity) and `release_word` (a running voice released
     with a nonzero release-velocity word). Measured over every committed note
     sequence: exactly ONE shared fixture (`seq-notes-holds-v1`) carries any
     nonzero MIDI release velocity at all, and NO shared fixture satisfies
     `per_instance` or `slot_reuse`. On a stimulus whose precondition is unmet
     the control is reported NOT_RUN with the reason named, never as a pass;
     the leaf-local `sxt036-vel-overlap-v1` is the only committed stimulus that
     satisfies all three.
9. Cost rule and its accounting boundary (fifth increment; driver
   `tools/vel_cost_accounting.py` -> `reports/SXT-036/artifacts/
   cost-accounting.{txt,json}`; counters in `rtl/voice/tb_vel.sv`, `OPS` line):
   * **Measured cost law (frozen).** `route evaluations = routes × per-voice
     control passes`, with exactly **1 × 32×32→64 multiply + 1 × 64-bit
     rounding add + 2 × 64-bit saturation compares + 1 × 32-bit accumulate**
     per evaluation, and one event-rate `vel_rom` read per note-on and per
     note-off. Verified on five stimuli and across a 0..6 route-table sweep
     (each run also checked EXACT against the model as a positive control);
     controls K1/K2/K3 must and do mispredict.
   * **Cycles are not measured here.** Op counts are; a cycles figure is only
     DERIVED under two explicitly named readings of the SXT-016 assumptions
     (A-DSP-1c / A-ALU-1), reported as the bracket **2..8 cycles per
     evaluation**, and is never a probe result or a technology claim.
   * **SXT-015 shape divergence — recorded here, then DISPOSITIONED in #239.**
     The accounting used to charge every modulation row **once per frame**,
     while both sources here are PER-VOICE, so their rows are voice-list rows
     whose work scales with LIVE VOICES: at the accounting's own worst-case
     voice count the row-evaluation count is 12.25× / 4.46× / 7.00× the row
     count for `Bad News` / `Rainy Day Dreamaway` / `House Of Chords`, and
     1.00× for the fixture carrier `Attacky` (no voice rows — which is why the
     divergence was invisible on the fixture). Decision #239 took that shape:
     `mod_cycles = _modroute_evaluations(g, worst_voices) ×
     cyc_modroute_frame`, a global/scene row once per frame and a voice row
     once per worst-case live voice per frame. This tool now CROSS-CHECKS the
     accounting against the measured shape per carrier (`shape_resolution` in
     `cost-accounting.json`) instead of recording a gap.
   * **What still diverges (recorded, not reconciled).** The per-evaluation
     CONSTANT: 15 accounted cycles against the 2..8 derived bracket. 15 is a
     `placeholder` param that no SXT-016 probe replaces (asserted over all 76
     committed probe records) and only a probe may pin it; #239 deliberately
     did not. Nothing here is tuned to agree.
   * **State.** 8 slots × {`vel_q`, `relvel_q`} × 32 b = **512 bits**, and the
     count is load-bearing because the scene-wide-register mutant FAILS
     exactness (read back from the committed control transcript, K6). SXT-015
     still has **no separate** modulation-source state row; #239 decided that
     per-voice source registers are declared INSIDE `voice_base_state_bytes`
     (whose `estimate_ref` now enumerates them; 4096 B unchanged), and this
     leaf's 8 B/voice for two sources is a lower bound on a full source set,
     never a row value. SXT-016 re-derives that bucket.
   * **Pins, fail closed.** The comparison is pinned to SXT-015
     `sxt-015-accounting/1.1.0` / `placeholder-v0` / params digest
     `a639d3115ae1a0ca` / `cyc_modroute_frame = 15` (re-recorded for #239 from
     the live model — the constant was never re-tuned); drift REFUSES
     (exit 2) so the comparison is re-recorded against the new model rather
     than silently carried forward, and `tests/test_sxt036_vel_cost.py` fails
     in CI if the live model moves.
10. Oracle gate and the frozen backfill plan (sixth increment; driver
   `tools/vel_oracle_status.py` -> `reports/SXT-036/artifacts/
   oracle-status.json` + `oracle-backfill.txt`):
   * **The gate is measured, not asserted.** Acceptance items 2 and 5 of #70
     are oracle-dependent and stay `NOT_RUN`; what the sixth increment freezes
     is *how that verdict is established*. Measured gate on the dispatch host:
     **`UNAVAILABLE`**.
   * **Strict reading (frozen).** The oracle counts as present only when ALL
     of: the checkout directory exists; it is a git work tree; its HEAD equals
     the SXT-010 pin `58914e59c608ed4384ba6002e44c3465c58b2e71`; and the
     imported `surgepy` module file lives INSIDE that checkout. Four statuses
     are distinguished rather than collapsed — `AVAILABLE`, `PIN_MISMATCH`,
     `UNPINNED_SURGEPY`, `UNAVAILABLE` — so a wrong-commit checkout is refused
     rather than silently reported as merely absent. A bare `import surgepy`
     (the reading increments 1–5 used) is explicitly NOT sufficient, and the
     probe records both readings so the difference stays falsifiable.
   * **Status vocabulary, fail closed.** A leg this driver did not run may
     carry only `{NOT_RUN, RUNNABLE, BLOCKED}`; `PASS` is not in the
     vocabulary and an injected `PASS` raises (control O6). An available
     oracle makes a leg `RUNNABLE` — running it remains a separate act.
   * **Legs split by gate.** `blob-verify-carriers` needs the pinned CHECKOUT
     only; the other four (`extract-fixture-depths`, `render-reference`,
     `compare-budgets`, `reference-budget-controls`) additionally need a built
     `surgepy`. The cheapest leg — the one that turns today's
     `blob_verified: false` into a real payload hash — is therefore not
     bundled behind the expensive one.
   * **Named-tool resolution.** Every tool path #70 names is resolved against
     the committed tree on each run. `tools/render_fixture.py`, named by the
     issue body and by earlier revisions of the evidence record, **does not
     exist**; it resolves to `fixtures/render_fixture.py` (SXT-012 harness),
     with `fixtures/render_mw_fixture.py` and `model/voice/extract_mw_inputs.py`
     as the per-leaf patterns to copy. A bogus name reports `MISSING`
     (control O7), so the table cannot rubber-stamp.
   * **Predictions are derived, never restated.** The backfill predictions are
     read out of `carrier-route-audit.json` and `param-corners.json`; a
     disagreement between them, a missing source, or a corpus pin that no
     longer matches #70 REFUSES (exit 2). A disagreement observed on the
     oracle host is a corpus-pipeline or cited-reading finding — never a
     tuning opportunity.
   * **Necessary, not sufficient.** The gate checks HEAD against the pin; it
     does not revalidate submodule SHAs, build flags, or the pinned
     interpreter. Those remain `oracle/fetch-and-build.sh`'s job.
