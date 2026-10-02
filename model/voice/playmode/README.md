# SXT-043 frozen model — playmode submode `pm_mono_st_fp` (`model/voice/playmode/`)

Issue #77. Frozen reference for `rtl/voice/tb_pm_mono_st_fp.sv`. The RTL must
match this model **exactly** (integer equality at every declared checkpoint;
`tools/compare_pm_rtl_model.py`). Model-vs-pinned-engine agreement is a
separate claim, governed by **not-frozen** error budgets
(`tools/compare_audio_reference.py`); this leaf reports achieved numbers
only, per the SXT-022 convention and this repo's three-claims discipline
(CLAUDE.md).

Pinned engine: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
48 kHz, block size 32.

Carriers: `resources/data/patches_factory/Basses/{Bass 2, Bass 5,
Digibass}.fxp`. Inputs sidecars: `model/voice/playmode/inputs/{bass2,bass5,
digibass}.json` (`extract_inputs.py`, schema `sxt-043-playmode-inputs/1`).
Sequences: `fixtures/sequences/seq-notes-{coverage,repeated,holds}-v1.json`
(declared by #77) plus `fixtures/sequences/seq-mono-{fingered,reclaim}-v1.json`
(this leaf's generator, `fixtures/sequences/generate_pm_sequences.py` —
the declared sequences are all strictly non-overlapping note-on/note-off
pairs and therefore cannot reach a legato or reclaim transition; the two
added sequences exercise those paths explicitly).

## Declared model/RTL boundary

This RTL is the **articulation layer only**: the pm_mono_st_fp voice
allocation/legato/reclaim/release state machine, the amp-envelope state
machine (including `attackFrom(level)` and `uber_release`), the SLOW_EXP
velocity smoother, the keytrack word, and the portamento ramp. It does
**not** reimplement the oscillator/filter/output-staging audio datapath,
which is already covered integer-exactly by the landed SXT-022/026a/034/040
RTL (`rtl/voice/tb_voice.sv`) and is unchanged by this leaf. Per
`model/voice/playmode/run_model.py`'s own render loop, the model's audio
render (`model.wav`) exists **only** to anchor the model-vs-reference
budget check on the three carriers; it is a simplified per-voice mix
(`lvl * pfg * gain-ramp * outl`, SXT-022 halfband decimator) and does
**not** reproduce the landed `filter_chain` (fc_serial1 Mix1 blend /
IIR12-24 coupled-form clipgain state) that `tb_voice.sv` models exactly for
other leaves — that full-chain exactness claim belongs to the leaves that
introduced it and is not re-asserted here. This is why the model-vs-
reference budget numbers recorded below do not meet the proposed thresholds:
they are not tuned to pass, and the gap is attributable in part to this
declared simplification, not solely to fixed-point truncation.

## Word lengths (frozen for this leaf)

| quantity                                                    | format  |
|--------------------------------------------------------------|---------|
| key / pitch / pkey / portasrc_key / priorpkey                | Q10.21  |
| portaphase, envelope phase (aeg_phase), sustain level         | Q2.29   |
| oscillator omega / phase (shared SXT-026a/040 datapath only)  | Q3.28   |
| samples, gains, coefficients, velocity words, keytrack word   | Q10.21  |

Arithmetic rules are the frozen SXT-022 rules (`model/voice/README.md`):
integer two's-complement words, exact 64-bit products rounded round-half-up
to the target format and saturated to signed 32 bits; divisions only at
block rate (the constant-rate portamento factor).

## The one genuinely per-block transcendental: `glide_phase`

Every other block/event-rate transcendental this leaf needs (envelope rate
tables, the SLOW_EXP coefficient, `db_to_linear` gains) is evaluated ONCE
at fixture-constant time and streamed to the RTL as a plain precomputed
word — the frozen SXT-022 convention, unchanged. `glide_phase` (the
portamento curve lookup, `SurgeStorage.cpp` `glide_log`/`glide_exp`) is
different: it is re-evaluated every block while a glide is in flight, so it
cannot be reduced to one constant. The RTL
(`rtl/voice/tb_pm_mono_st_fp.sv`) reproduces it by evaluating the **same
pinned table formula** with SystemVerilog real-valued math ($ln), rounded
with the same round-half-up `qint_r` pattern `tb_voice.sv` already uses for
the Sine oscillator's `$cos`/`$sin` path (SXT-026a) — not a pre-quantized
ROM interpolated in fixed point, which would double-round (once building
the ROM word, once interpolating over it) and could differ from the
model's single-rounding result by up to 1 LSB. All three named carriers pin
`porta.options.curve == 0` (LINEAR), whose `glide_phase` branch is a pure
format shift with no transcendental at all — so the LOG/EXP table branch is
implemented and exercised by `tb_pm_mono_st_fp.sv`'s `glide_phase_rtl`
function, but it is not load-bearing for this leaf's three-carrier
accepted evidence.

## Declared RTL checkpoint vector (per pool slot, every block)

`STATE_WORD_ORDER` (`pm_mono_st_fp.py`), prefixed with the slot's `active`
flag: `active, gate, uberrelease, key, aeg_state, aeg_phase_q29,
aeg_output_q21, aeg_scalestage_q21, vel_value_q21, vel_target_q21,
kt_word_q21, portaphase_q29, portasrc_key_q21, pkey_q21, priorpkey_q21,
porta_doretrigger` — 16 words × 8 pool slots × every block. A slot with no
live voice reports all-zero (never stale/leftover register content); the
model's own run loop enforces this by filtering `scene.voices` to the
surviving set **before** building each block's checkpoint record (so a
voice that reaches `is_idle()` in the current block already reads as
inactive in that same block's checkpoint — not one block later).

## Allocation / articulation state machine (summary; full citations in
`pm_mono_st_fp.py`'s module docstring and per-method docstrings)

* **Voice pool**: 8 slots (`MonoStFpScene.POOL`), fail-closed on overflow
  (`Refuse` / RTL `$fatal` — not exercised by any committed fixture).
* **note_on**: `ALWAYS_HIGHEST`/`ALWAYS_LOWEST` priority can suppress voice
  creation entirely (ascending keystate scan, `range(0, 127)` — note the
  pinned asymmetry vs. the release-side descending scan below, preserved
  verbatim). Otherwise: the first **gated** voice (list/insertion order)
  legatos onto the new key and the scan stops; failing that, the **last**
  non-gated non-uberreleased voice found becomes the reclaim candidate
  (`monoVoiceEnvelopeMode != RESTART_FROM_ZERO`) — or, under
  `RESTART_FROM_ZERO`, every such voice is uber-released instead; failing
  both, a fresh voice is created.
* **note_off**: a release always re-scans the held keys
  (`range(127, -1, -1)`, descending) via the configured
  `monoVoicePriorityMode` and legatos the voice down to a still-held key
  instead of releasing it, whenever one exists.
* **legato** (single trigger): re-anchors portamento from the voice's prior
  pitch and changes its key; the envelope is untouched (that is what
  "single trigger" means) and the note-on's velocity is read but never
  applied.
* **reclaim**: captures the current AEG level, re-gates, re-keys, retargets
  the SLOW_EXP velocity smoother (not an immediate jump), restarts the
  attack from the captured level (`attackFrom(level)`, `a_s` shape
  0/1/2 all implemented), and re-anchors portamento from the voice's PRIOR
  key — which the pm_mono_st_fp-defining branch below overrides.
* **The pm_mono_st_fp-defining branch** (`Portamento.reset_from`): a
  new/reclaimed voice is anchored at its OWN pitch whenever `fingered`
  (true for this submode) or the portamento parameter is at its minimum —
  never at `last_key` — so a fresh note-on never glides however recently
  another key sounded. Dropping this branch (`--nc-anchor-last-key`) drives
  one of this leaf's own fixtures' pitch outside the declared [24, 148]
  range (`reports/SXT-043/artifacts/negative-control.txt` §2a) — the
  sharpest evidence available that the branch is load-bearing.
* **Per-instance state**: every `MonoVoice` owns its own `AegMono` /
  `VelocitySmoother` / `Portamento` / `SineOsc`. Nothing is shared across
  slots. All three declared carriers use `monoVoiceEnvelopeMode =
  RESTART_FROM_LATEST`, under which this state machine never produces two
  concurrently-alive voices (measured: `max_concurrent_voices == 1` on
  every carrier × every sequence in this leaf's fixture set) — so the
  generic shared-vs-per-instance negative control does not discriminate on
  this carrier set. Recorded as a coverage gap (not a false pass), the same
  pattern already accepted for SXT-036 (`reports/SXT-036/EVIDENCE.md`).

## Declared bounds (fail-closed)

* One MIDI channel, non-MPE, scene mode Single, no keyboard split, no
  sustain/sostenuto pedal (`monoPedalMode` unreachable by any committed
  sequence — all sequences are note-only).
* Standard tuning only (`qdiv`'s constant-rate factor assumes `quantStep =
  12`; microtuning is refused upstream of this leaf).
* Modulation route vocabulary: `{Velocity, Keytrack} -> A VCA Gain` only
  (the SXT-035/042 destination class); anything else refuses
  (`PmInputs.__init__`).
* The modeled audio slot is forced to the already-landed legacy Sine
  quadrature configuration (`fixture_config.py` — shape 0, FMmode 0,
  unison 1, retrigger on, lowcut/highcut at their OFF extremes, both
  filter units Off, waveshaper Off, scene lowcut off, every FX Off, fbc
  serial-1); the carrier's own `polymode`, `portamento` (value + all four
  options + tempo-sync), `monoVoicePriorityMode`, `monoVoiceEnvelopeMode`,
  amp envelope, scene octave, and gain staging are left intact and are
  exactly what is under test. This is a declared test configuration, never
  an adapted preset, and establishes no preset-support claim.

## Known finding: Digibass reference render is silent under this fixture configuration

Measured (not a model/RTL defect): rendering `Digibass.fxp` through the
pinned oracle with **only** the oscillator-1 type forced to Sine (no other
override applied) already produces an all-zero output buffer at every MIDI
key tested, on a fresh engine instance, for the untouched preset's raw
amp/filter/mixer settings otherwise. `Bass 2.fxp` and `Bass 5.fxp` (same
override sequence, same original `osc1 type == 2` as Digibass for `Bass
5.fxp`) render normally. Root cause not identified (bisected override-by-
override: silence appears immediately after the type-only change, before
any of this leaf's other 29 declared overrides are applied; not explained
by solo/mute state, FM switch, octave/pitch, or unison voice count, all of
which read identically to the working carriers). This blocks a meaningful
model-vs-reference budget comparison for Digibass specifically (the
reference is all-zero; `tools/compare_audio_reference.py` reports a
"comparison" against silence, not a fidelity measurement) and is tracked
separately rather than fixed here: issue #311. It does **not** affect this leaf's RTL-vs-model
exactness claim, which is purely a register-level comparison and was
verified 0-mismatch on Digibass exactly as on the other two carriers.
