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
pinned oracle with **only** the oscillator-1 type forced to Sine produces an
all-zero output buffer at every MIDI key tested on a fresh engine instance.
This blocks a meaningful model-vs-reference budget comparison for Digibass
(the reference is all-zero; `tools/compare_audio_reference.py` reports a
"comparison" against silence, not a fidelity measurement). Investigated
under issue #311; root cause identified below.

Root cause (investigated under issue #311; pinned engine
`surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, external checkout read
only, nothing copied here): **stale per-voice modulation routings that
survive an oscillator-type change and then land on an integer parameter of
the new oscillator type.**

- `Digibass.fxp` routes `Velocity -> A Osc 1 Morph` (depth 0.366964) and
  `Filter EG -> A Osc 1 Morph` (depth 0.223214) on osc 1 (a Wavetable
  oscillator, type 2). `Bass 5.fxp` and `Bass 2.fxp` have no routing into
  any osc-1 `p[]` parameter, which is the only difference that matters.
- Switching the type through the Python binding (`setParamVal` on the osc
  type) is queued by the engine and applied at the next `processMultiBlock`.
  The queued-type handler resets the oscillator's parameters to the new
  type's defaults and is written to call the engine's
  `clear_osc_modulation` only when the queued type differs from the
  parameter's current value; the binding has already written the new value
  to the parameter by then, so that clear is skipped on this path
  (inference from reading the code; the observed effect below agrees).
  Read back via `getAllModRoutings()` after the switch, both Digibass
  routings are still present, now named `A Osc 1 Shape` (the Sine
  oscillator's slot `p[0]`, an integer parameter), with `normdepth` 0 but
  the original `depth` intact.
- Per voice, the engine copies the parameter values into a union-typed
  scratch array and then adds each voice-modulation routing to it as a
  **float** regardless of the target's value type. The Sine oscillator then
  reads that slot as an **int** shape selector and dispatches over a switch
  that covers only shapes 0-31 with no default case. A float such as
  0.3 reinterpreted as an int is about 1.0e9, so no case runs and the
  oscillator leaves its output buffer untouched (code read; consistent with
  the interventions below, not separately instrumented).

Interventions (all fresh process, fresh engine instance, single note at
key 60 velocity 100, 256 blocks, pinned prebuilt oracle):

| Variant | Peak (float) |
|---|---|
| Digibass, osc1 -> Sine only (issue reproduction) | 0.0 |
| Digibass, set both Osc 1 Morph routing depths to 0 **before** the type switch, then switch | 0.3869, pitched output (dominant ~132 Hz at key 60 and ~264 Hz at key 72, the same one-octave-below-key offset as the Bass 5 Sine render at key 60 (~132 Hz); key 36 was not resolved by the ~12 Hz FFT bin width |
| Digibass, try to zero the routings **after** the switch | 0.0 (the target is no longer modulatable, the call is a no-op, routings still listed) |
| Bass 5 (osc1 type 2), osc1 -> Sine | 0.4879 |
| Bass 5, add `Velocity -> Osc 1 p[0]` (depth 0.3) **before** the switch, then switch to Sine | 0.0 |
| Bass 5, add that routing **after** the switch | 0.4879 (not added: Sine Shape is not modulatable) |

So a donor-patch-free reproduction exists: any preset whose osc-1 `p[]`
parameters are modulated, switched to Sine through this path, goes silent.

Why the earlier bisection also saw "audible" results and why the silence
looked intermittent: with the Sine oscillator never writing its output
buffer, what reaches the mixer is whatever that oscillator-buffer memory
already held. On a fresh engine it is zeros (silent). If a note was played
and finished before the switch, or other engine instances in the same
process ran before, the buffer can hold leftover non-Sine data. Observed:
playing one note, releasing it, then switching and playing gives a nonzero
render (peak ~0.09-0.25) whose dominant frequency is ~1.46 kHz at key 60
rather than the Sine fundamental, i.e. not a Sine. This is evidence for
that mechanism, not a proof of it (uninitialised/stale-memory behaviour was
not instrumented). It also means the "silent" result is only reliable on a
fresh engine instance with no prior note, which is exactly the fixture
condition. Do not read any nonzero Digibass-Sine render as valid.

What this does **not** change: the carrier fixture's reference leg for
Digibass remains a non-comparison (NOT A VALID COMPARISON, reference silent).
Deriving a valid Digibass reference needs the fixture override sequence to
remove osc-1 `p[]` modulation routings before it switches the type; that is
a change to a fixture/model file and a re-measure of #77's budget leg, left
to a separate decision (follow-up issue linked from the PR) rather than done
here. RTL-vs-model exactness (claim 1) for Digibass is unaffected.

Reproduction on the pinned commit, re-run for this finding (prebuilt
oracle, `$ORACLE_PYTHON` from `oracle/README.md` "Prebuilt oracle"): the
issue's script prints `peak: 0.0` (3 of 3 fresh processes, and 4 of 4
engine instances in one process). Re-check this after any engine re-pin.
Bass 2 / Bass 5 re-measured under the Sine switch: peaks 0.7472 and 0.4752
(audible, unaffected).

It does **not** affect this leaf's RTL-vs-model
exactness claim, which is purely a register-level comparison and was
verified 0-mismatch on Digibass exactly as on the other two carriers.

(The finding above is dated historical evidence from #311 and is kept
verbatim; the fixture revision below responds to it.)

## Fixture revision 2 (#329, 2026-10-07): osc-slot `p[]` routes cleared before the type switch

**Visible fixture revision, not a product-contract change.** The declared
isolation configuration is still a test configuration, never an adapted
preset, never preset coverage.

What changed (`fixture_config.py`, `FIXTURE_REVISION = 2`, override key
`osc_p_route_clear`; one shared sequence `configure_loaded` used by the
extractor, the reference renderer, the cut-activation probe and the
controls):

1. Immediately after `loadPatch`, every routing whose destination is one
   of the modeled slot's seven **original** `p[]` parameters -- matched by
   engine synth-side parameter id captured before the remap, never by
   display name -- is set to depth 0 through `setModDepth01` with its
   source scene/index preserved. Readback checks both `getModDepth01` and
   the **raw** depth from a fresh `getAllModRoutings()`; failure refuses.
   The original source/destination/depth/normalized depth, the readback
   and the reason are retained in `modulation_routes.osc_p_route_clear`.
2. Then the type switch, one settle block and the handle re-fetch, as
   before.
3. A post-switch guard refuses if any routing into the slot's `p[]` still
   carries a nonzero raw depth.
4. `modpin_zero` readback also checks the raw depth.

A defect in revision 1 that this exposes: the committed revision-1
`inputs/digibass.json` lists `Velocity` / `Filter EG -> A Osc 1 Shape` under
`pinned` ("depth zeroed"). They were **not** zeroed. The post-switch
`setModDepth01` is a no-op on the non-modulatable Sine Shape, and the
revision-1 readback compared `getModDepth01`, which reads 0 there while the
raw depth (0.367 / 0.223) stays intact. Revision 2 refuses in that state
instead of recording it.

Articulation under test is unaffected by construction: only routings whose
**destination** is an osc-slot `p[]` parameter are cleared. Those
parameters are overwritten by the pinned Sine slice anyway. Sources
(Velocity, Filter EG) and every amp/VCA, playmode, portamento and mono
priority/envelope parameter are untouched. Unknown routes still refuse.

Valid-reference gate (`reference_validity.py`, thresholds declared before
any measurement): a single fresh probe note (key 60, velocity 100, 1 s
hold) is accepted as a valid reference only if, on the held segment 0.30 to
0.80 s after note-on, its peak is at least 1e-3, its dominant frequency is
within ±25 cents of `440 * 2^((key + 12*(scene_octave + osc_octave) + pitch
- 69)/12)`, and at least half the segment's spectral power lies within ±100
cents of that frequency. For Digibass (scene octave -1) the expected f0 is
130.81 Hz. Peak alone is insufficient, so silence and a stale or
non-pitched buffer both fail. `tools/probe_pm_reference_validity.py` runs
the gate on the pinned oracle in three modes: `revised` (expected PASS),
plus two negative controls that replay the pre-#329 order,
`nc-retained-routes` (expected FAIL, silence) and `nc-stale-buffer`
(expected FAIL, not pitched). The controls get the retained-route order
only through a private hook that no production entry point passes.

Status at the time of this revision: the code change, the API-double
ordering/readback regression (`tests/test_sxt043_fixture_rev2.py`) and the
gate's synthetic-signal checks are done. **Every native leg is BLOCKED**:
the pinned oracle was not installed on the host that made the change.
That covers re-extraction, the revised Digibass reference and its pitch
gate, the three-carrier budgets, both negative controls, and RTL-vs-model
exactness on re-extracted inputs. Until those legs run, the committed
`inputs/*.json` and every `reports/SXT-043/artifacts/` record are
**fixture revision 1**, and the Digibass budget rows stay NOT A VALID
COMPARISON. `tools/render_pm_reference.py` refuses revision-1 inputs, so a
revision-1 sidecar cannot be paired with a revision-2 render. See
`reports/SXT-043/EVIDENCE.md`.

Hazard inventory (source inspection, 2026-10-07): this playmode fixture is
the only render path in the repository that **forces** an oscillator type.
The SXT-026a/040 Sine, classic and wavetable leaves read and gate on the
carrier's native type and do not rewrite it. In the committed normalized
corpus (`graphs.jsonl`), Digibass is the only one of the three carriers
with a routing into an osc-1 parameter: the two #311 routes, both to
synth-side id 225. Bass 2 and Bass 5 have none, and a test pins this.
There is a related but distinct pattern that this change does not address:
`tools/ablate_fx.py` swaps FX slot types through `setParamVal`. FX
parameters are float-valued, so the integer-selector failure mode does not
apply as described, and whether FX-param routings survive that swap was
not examined here.
