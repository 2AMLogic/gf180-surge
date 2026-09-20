# SXT-022 evidence record — first dry voice slice

Branch: `loom/sxt-022-dry-voice` · Issue: #15 (SXT-022) · Date: 2026-09-20

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).

**Claim discipline.** This record advances exactly one of the three claims:
the *model→RTL exactness discipline demonstrated end-to-end on real preset
audio (dry; diagnostic milestone, NOT the wet acceptance gate)*. It
establishes **no** fidelity claim (budgets are proposals; nothing is frozen),
**no** preset-support claim, **no** musical-quality claim, and **no**
FPGA/gf180mcu synthesis, timing, or hardware playback claim. The RTL is an
iverilog-simulated behavioral schedule, not synthesis-closed RTL.

## Chosen preset and rationale

**`Basses/Attacky.fxp`** (factory, rev 9; census blob
`4675e423a7489b02f501f7763b4760f64ab035f9`; graphs.jsonl line under
`corpus/normalized/graphs.jsonl`, sha256-of-file recorded in
`fixtures/manifest.json`'s source corpus).

Selection was **forced, not tuned**: a fail-closed search over all 3,561
normalized graphs (`corpus/normalized/graphs.jsonl`, sha256
`c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715`) for the
B4-broad voice gates in minimal form — single scene (mode Single, scene A),
poly playmode, all 16 FX slots Off, filter config Serial 1 (no feedback),
waveshaper Off, lowcut at off, one mixer path active, that oscillator
Classic-or-Sine with unison 1 and **retrigger on** (determinism gate; scene
drift extracted and asserted 0), filter unit 2 Off — returns **exactly one**
preset in the entire corpus: `Basses/Attacky.fxp`. Its graph:

* OSC1 **Classic**, unison 1, retrigger on, keytrack, octave −1,
  shape 0.0, width1 0.140178, width2 0.329464, **Sub Mix 1.0** (full sub),
  sync 0; oscs 2/3 muted Classic (retrigger irrelevant: muted + no shared
  RNG consumers — determinism verified empirically below).
* Filter unit 1 **LP 12 dB, subtype Driven** (coupled-form biquad + clipgain),
  cut −14.325 st, res 0, keytrack 0, **env mod 96 st**; unit 2 Off.
* Modulation (scene, from graphs.jsonl `md`): **modwheel → Filter 1 Cutoff
  (34.425 st)** and **modwheel → Filter 1 Resonance (0.383)**.
* vca 3.600002 dB, vca_velsense 0, pan 0, width 0, pfg 0 dB, character Warm,
  playmode Poly, polylimit 16 (rev≤15 migration, recorded in `g.mi`).

The corpus contains **no** minimal-shape preset with a Sine oscillator or an
SVF-Standard filter at this gate set — the smallest real voice graph is this
one. State missing from graphs.jsonl (ADSR values, scene volume 0.973214,
drift 0, LFO1 detail, master volume −2.025745 dB loader default) was read
from the engine after `loadPatch` at 48 kHz by
`model/voice/extract_inputs.py` (fail-closed; census blob re-verified) and
committed as `model/voice/attacky_inputs.json`.

## Deliverables

| Deliverable | Artifact |
|---|---|
| Frozen fixed-point model | `model/voice/voice_model.py` (+ freeze doc `model/voice/README.md`) |
| Model inputs | `model/voice/attacky_inputs.json`, `model/voice/extract_inputs.py` |
| Model runner (WAV + trace + RTL stimulus) | `model/voice/run_model.py` |
| RTL schedule + harness | `rtl/voice/tb_voice.sv` (behavioral, iverilog `-g2012`) |
| Exactness harness | `tools/compare_rtl_model.py` |
| Audio comparison | `tools/compare_audio_reference.py` |
| Artifacts | `reports/sxt-022/artifacts/` (model+reference WAVs, exactness + audio metrics JSONs, negative-control transcript) |
| License decision record | `decision-records/0002-halfband-coefficients.md` |

## Acceptance mapping (issue #15)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | RTL vs frozen model: internal state equality at declared checkpoints (exact) | **PASS** | All three sequences, integer equality, zero mismatches: `exactness-seq-notes-coverage-v1.json` (467 checkpoints, 12,609 state fields, 29,888 osc samples, 273,600 mono samples), `exactness-seq-notes-repeated-v1.json` (403/10,881/25,792/196,800), `exactness-seq-modwheel-v1.json` (75/2,025/4,800/182,400). Checkpoints = state after blocks 0, 1, every 64th block, and every block of a released voice: envelope state machines (state/phase/output ×2), oscillator impulse-engine state (oscstate, impulse state, last_level, pwidth, pwidth2, dc_uni, dc, osc_out, osc_out2, bufpos), filter registers (f_r0, f_r1, f_clip), end-of-block coefficients C[8], plus the 64-sample oscillator output block and **every** 48 kHz output sample. |
| 2 | Model vs upstream reference: declared budget metrics pass on the fixture set; raw subtraction not required where free-running phase/noise applies | **PASS/PENDING-FREEZE (mixed, honestly reported)** | `audio-*.json`: seq-notes-repeated-v1 passes all three proposed bounds (max\|Δ\| 2,321 LSB; RMS −33.3 dBFS; spectral corr 0.9875). seq-notes-coverage-v1 (max 4,760; RMS −30.1 dBFS; spec 0.9753) and seq-modwheel-v1 (max 12,677; RMS −32.3 dBFS; spec 0.9784) **fail the proposed max/spectral bounds**. These budgets are `[PROPOSED-TO-BE-FROZEN-AT-PILOT]` placeholders — per the fidelity policy DRAFT nothing here is a fidelity verdict; the achieved numbers and the proposal misses are recorded for the SXT-013 freeze, not tuned away. Alignment: best RMS shift is 0 to −4 samples on two sequences (well inside the 32-sample scheduling granularity) and −2 on modwheel — the model is sample-locked to the reference render (no free-running phase: retrigger on, drift 0; 3× fresh-instance reference renders bit-identical, sha `9966433b…`). See "Deviations / known error sources". |
| 3 | Chosen preset is a real normalized corpus entry, not synthetic | **PASS** | Factory `Basses/Attacky.fxp`; normalized entry quoted above; census blob re-verified at extraction and at every render (`render_fixture.py` census check; extractor refuses on mismatch). |
| 4 | Cycle/state costs recorded against SXT-016 probe estimates | **PASS (recorded; reconciliation = divergence note)** | Measured qmul counts of the exact RTL schedule (1 MAC/cycle assumed, A-DSP-1c): coverage 10,889,091 qmul / 8,550 blocks = **39.8 MAC per 48 kHz sample**; repeated 7,422,396 / 6,150 = **37.7**; modwheel 6,945,898 / 5,700 = **38.1** (one active voice; fixture material C2/C4/C6 through the octave −1). Non-MAC ops are not cycle-accurately scheduled in this behavioral slice and are reported as normalized op counts only. State: **11,520 bits** for the slice as scheduled (per-slot impulse buffers 2×140×32 = 8,960 mono [probe assumed stereo: 3×1,120-word buffers = 10,080], 32 scalar state words, shared halfband 1,536, plus control words), vs probe `classic_blit` `state_ram_bits` 10,274 per osc slot. Reconciliation vs SXT-016 `probe_osc__classic_blit__ph24__a24__m32__onchip.json` (**divergence recorded, not agreement**): the probe estimates the oscillator kernel alone (52.0 cycles/sample at C4, 175.8 at the MIDI-120 worst corner, stereo out, 24-bit audio words, osc-only scope); this slice measures the integrated mono voice (osc + mixer + filter + gains + halfband decimator + master) at fixture pitches with 32-bit words. The numbers are therefore **not directly comparable**; the probe remains the per-kernel planning number and this measurement is the integrated-slice reference point for SXT-016 refinement. No technology claim of any kind. |
| 5 | Negative control: a single deliberately mutated RTL state must fail the exactness check | **PASS (control demonstrably fails)** | `artifacts/negative-control.txt`: `voice_broken_mutant.sv` = the testbench with the qmul round-half-up bias constant mutated by one shift (`<<20` → `<<19`) — committed, single-constant mutation. The harness **FAILs** (98 mismatches within block 0; exit 1). |

## Fixture set

Three committed SXT-012 library sequences rendered through the pinned-engine
fixture harness (`render_fixture.py --preset-file "Basses/Attacky.fxp"`,
census-blob verified, dry bus = wet here because the preset has no FX —
engine dry/wet sha identical, recorded in the render output). Reference
determinism: 3 fresh-instance renders of seq-notes-repeated-v1 bit-identical
(sha256 `9966433b815933ddda875235cd2a1125dc995cdd6e7dbdc7b8ad4ef7b821d667`),
consistent with the SXT-012 determinism classes (retrigger on, scene drift 0).

| sequence | frames | use |
|---|---|---|
| `seq-notes-coverage-v1` | 273,600 | registers C2/C4/C6, velocities, holds, releases |
| `seq-notes-repeated-v1` | 196,800 | same-pitch retrigger (voice re-create on a live slot) |
| `seq-modwheel-v1` | 182,400 | modwheel staircase under a held note (exercises the CC1 → cutoff/resonance modulation paths from the preset's real `md` routings) |

## Deviations / known error sources (model vs reference)

All are declared in `model/voice/README.md`; none is silently absorbed:

1. **Quantization vs float32**: the engine computes the voice path in
   float32; the model uses Q10.21 fixed words with round-half-up. The pluck's
   fast filter sweep (env mod 96 st over ~33 ms) magnifies small coefficient
   and table-lookup differences into per-sample phase deviations; the
   spectral correlation (0.975–0.988) and RMS (−30 to −33 dBFS) bound the
   audible effect, the per-sample max does not.
2. **Frequency-domain tables**: the engine lerps float32 tables; the model
   evaluates the pinned construction formulas in double and quantizes once
   (≤1 ulp class differences).
3. **Sinc sub-sample position**: engine computes `2^24·oscstate·pmi` in
   float32 (24-bit mantissa) and truncates; the model truncates an exact
   integer product (finer) — sub-sample impulse jitter differences.
4. **Modwheel smoothing order**: FAST_LINE stepping is declared at the end of
   the control pass; the engine's exact interleaving with voice creation is
   not observable through surgepy. The modwheel sequence's best-fit shift of
   −2 samples and its max deviation likely include this.
5. **CharacteristicFilter starting state** and the osc DC-buffer tap
   (`FIRoffset`) are dead parameters for this preset (sub mix 1.0 ⇒
   `dc_uni ≡ 0`); the committed mutant exercise shows such constants can be
   inert — the negative control uses a constantly-active constant instead.

## Escalations / hand-offs

1. **Budget proposal misses** (coverage, modwheel sequences vs the proposed
   max/spectral bounds) are recorded as input to the SXT-013 freeze — either
   the freeze justifies tighter model numerics (e.g. float32-table emulation)
   or sets different budgets; per AGENTS.md this decision is not made here.
2. **Mono-bus scope**: this slice models the mono sum (preset pan/width 0,
   serial-1, no width path). Stereo field behavior is untouched (SXT-012
   already notes stereo fixtures are future work).
3. **`state.keep_playing`/voice-death timing**, modsource step order, and
   polyphony >1 voice summation order are declared scheduling approximations
   whose effect is bounded by the reported metrics on this fixture set; a
   sample-accurate harness (SXT-012 limitation note) would sharpen them.

## Licensing / provenance

Everything under `model/voice/`, `rtl/voice/`, `tools/compare_*.py` and
`reports/sxt-022/` is original to this repository (Apache-2.0 per `LICENSE`).
The pinned GPL engine was imported at runtime only. The single adopted data
constant set (twelve halfband allpass coefficients) is covered by
`decision-records/0002-halfband-coefficients.md`; all other numeric tables
are recomputed from cited construction formulas in the pinned tree. No Surge
source, presets, or assets are copied into this repository. Method template
(float→fixed→RTL exactness harness structure) follows the issue's
reusable-substrate pointer (gf180-torchsynth@6532ec08) as *method only*; no
sibling code was copied.

## Explicitly NOT established by this work

* Any fidelity, preset-support, or preset-quality claim (no listening
  record; budgets not frozen).
* Any FPGA/gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware playback result; all cost numbers are op counts of a simulated
  sequential schedule under named assumptions (A-DSP-1c, A-ALU-1).
* Effects behavior (SXT-023/024), wet-path acceptance (SXT-025),
  wavetable oscillators (SXT-026), polyphony >1 simultaneous voice summing
  order verification, stereo field, tempo behavior.
* Exact agreement of the model with the engine (the model is a fixed-point
  quantization; agreement is budget-bounded, budgets unfrozen).
