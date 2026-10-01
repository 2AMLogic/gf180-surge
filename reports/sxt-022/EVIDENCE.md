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
| 1 | RTL vs frozen model: internal state equality at declared checkpoints (exact) | **PASS** | All three sequences, integer equality, zero mismatches: `exactness-seq-notes-coverage-v1.json` (467 checkpoints, 16,345 state fields, 29,888 osc samples, 273,600 mono samples), `exactness-seq-notes-repeated-v1.json` (403/14,105/25,792/196,800), `exactness-seq-modwheel-v1.json` (75/2,625/4,800/182,400) — re-run at the #145 HEAD after the #123 decimator fix (field counts grew because SXT-026a/SXT-034 added per-checkpoint fields after this record first published 12,609/10,881/2,025; checkpoint and sample counts are unchanged). Checkpoints = state after blocks 0, 1, every 64th block, and every block of a released voice: envelope state machines (state/phase/output ×2), oscillator impulse-engine state (oscstate, impulse state, last_level, pwidth, pwidth2, dc_uni, dc, osc_out, osc_out2, bufpos), filter registers (f_r0, f_r1, f_clip), end-of-block coefficients C[8], plus the 64-sample oscillator output block and **every** 48 kHz output sample. |
| 2 | Model vs upstream reference: declared budget metrics pass on the fixture set; raw subtraction not required where free-running phase/noise applies | **FAIL vs [PROPOSED] budgets on all three sequences / PENDING-FREEZE (recorded, not tuned)** | `audio-*.json` (proposed bounds: max\|Δ\| ≤ 3,500 LSB, RMS diff ≤ −46 dBFS, spectral corr ≥ 0.98): seq-notes-repeated-v1 passes the max\|Δ\| (2,328 LSB) and spectral (corr 0.9921) bounds but **FAILS the RMS bound** (−33.3 dBFS is louder than the ≤ −46 dBFS proposal) → `FAIL against proposed budgets`. seq-notes-coverage-v1 (max 4,760; RMS −30.1 dBFS; spec 0.9791) **fails all three proposed bounds** (max, RMS and spectral); seq-modwheel-v1 (max 12,686; RMS −32.3 dBFS; spec 0.9802) **fails the max and RMS bounds** and passes the spectral bound. *Republication note (issue #145):* these are the numbers of the model re-rendered after the #123 halfband branch-order fix; the pre-#123 renders measured 2,321 / 0.9875 (repeated), 4,760 / 0.9753 (coverage) and 12,677 / 0.9784 (modwheel, spectral then a MISS) — see the change note below. No overall verdict moved. *Re-grade note (issue #97):* this row originally read "PASS/PENDING-FREEZE (mixed)" with seq-notes-repeated-v1 passing all three bounds and the other two failing only max/spectral; those RMS legs were graded with the inverted `rms_diff_dbfs >= budget` comparison fixed in PR #92 and audited in issue #95 (`reports/tooling-rms-polarity-audit/`). The numeric metrics are unchanged; only the RMS-leg grading and the overall status moved. These budgets are `[PROPOSED-TO-BE-FROZEN-AT-PILOT]` placeholders — per the fidelity policy DRAFT nothing here is a fidelity verdict; the achieved numbers and the proposal misses are recorded for the SXT-013 freeze, not tuned away. Alignment: best RMS shift is 0 to −4 samples on two sequences (well inside the 32-sample scheduling granularity) and −2 on modwheel — the model is sample-locked to the reference render (no free-running phase: retrigger on, drift 0; 3× fresh-instance reference renders bit-identical, sha `9966433b…`). See "Deviations / known error sources". |
| 3 | Chosen preset is a real normalized corpus entry, not synthetic | **PASS** | Factory `Basses/Attacky.fxp`; normalized entry quoted above; census blob re-verified at extraction and at every render (`render_fixture.py` census check; extractor refuses on mismatch). |
| 4 | Cycle/state costs recorded against SXT-016 probe estimates | **PASS (recorded; reconciliation = divergence note)** | Measured qmul counts of the exact RTL schedule (1 MAC/cycle assumed, A-DSP-1c): coverage 10,889,091 qmul / 8,550 blocks = **39.8 MAC per 48 kHz sample**; repeated 7,422,396 / 6,150 = **37.7**; modwheel 6,945,898 / 5,700 = **38.1** (one active voice; fixture material C2/C4/C6 through the octave −1). Non-MAC ops are not cycle-accurately scheduled in this behavioral slice and are reported as normalized op counts only. State: **11,520 bits** for the slice as scheduled (per-slot impulse buffers 2×140×32 = 8,960 mono [probe assumed stereo: 3×1,120-word buffers = 10,080], 32 scalar state words, shared halfband 1,536, plus control words), vs probe `classic_blit` `state_ram_bits` 10,274 per osc slot. Reconciliation vs SXT-016 `probe_osc__classic_blit__ph24__a24__m32__onchip.json` (**divergence recorded, not agreement**): the probe estimates the oscillator kernel alone (52.0 cycles/sample at C4, 175.8 at the MIDI-120 worst corner, stereo out, 24-bit audio words, osc-only scope); this slice measures the integrated mono voice (osc + mixer + filter + gains + halfband decimator + master) at fixture pitches with 32-bit words. The numbers are therefore **not directly comparable**; the probe remains the per-kernel planning number and this measurement is the integrated-slice reference point for SXT-016 refinement. No technology claim of any kind. |
| 5 | Negative control: a single deliberately mutated RTL state must fail the exactness check | **PASS (control demonstrably fails)** | `artifacts/negative-control.txt`: `voice_broken_mutant.sv` = the testbench with the qmul round-half-up bias constant mutated by one shift (`<<20` → `<<19`) — committed, single-constant mutation. The harness **FAILs** (98 mismatches within block 0; exit 1). |

### Change note (issue #145, 2026-09-27): republished after the #123 halfband branch-order fix

The #123 fix (`HalfbandD2` reconstructs `(B[2n] + A[2n+1])·0.5`, per the
pinned kernel; `reports/halfband-branch-order/`) moved every model render in
this directory. #145 re-rendered all three sequences at HEAD, re-ran
RTL-vs-model exactness and the shared comparator, and replaced
`model-*.wav`, `audio-*.json` and `exactness-*.json`. Attribution: the
pre-#123 ordering (`tools/halfband_legacy_render.py`) re-renders all three
committed pre-#145 WAVs **byte-identically** from the committed tree, so the
delta below is the #123 fix alone. Full record:
`reports/halfband-republication/`.

| sequence | max\|Δ\| LSB | RMS Δ dBFS | spectral corr | legs max/rms/spec | overall |
|---|---|---|---|---|---|
| seq-notes-coverage-v1 | 4,760 → 4,760 | −30.138 → −30.139 | 0.9753 → 0.9791 | F/F/F → F/F/F | FAIL → FAIL |
| seq-notes-repeated-v1 | 2,321 → 2,328 | −33.327 → −33.327 | 0.9875 → 0.9921 | P/F/P → P/F/P | FAIL → FAIL |
| seq-modwheel-v1 | 12,677 → 12,686 | −32.284 → −32.283 | 0.9784 → 0.9802 | F/F/F → F/F/**P** | FAIL → FAIL |

* The seq-modwheel-v1 spectral leg crosses the proposed 0.98 floor (MISS →
  PASS); its overall verdict does not move.
* The regenerated coverage/modwheel JSONs also carry the corrected
  `rms_diff_dbfs` polarity (PR #92 / #95 / #97): their committed
  `proposed_budget_results.rms_diff_dbfs` read `true` under the inverted
  comparison and now read `false`. That is the already-audited comparator
  correction reaching the JSON, not a #123 effect; this row's prose was
  already re-graded by #97.
* RTL-vs-model exactness **PASS** (0 mismatches) on all three sequences at
  HEAD (row 1 above).
* Unchanged: the reference renders, the budgets (still `[PROPOSED]`, owned
  by #12), and every claim this record does not make.

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
   spectral correlation (0.979–0.992) and RMS (−30 to −33 dBFS) bound the
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
6. **The scene decimator does not settle to zero on silence** (F-176-2, issue
   [#181](https://github.com/2AMLogic/gf180-surge/issues/181), DECLARED —
   SXT-017 option (a)). The shared `voice_model.HalfbandD2` (`README.md` step
   7) has a round-half-up dead band, so after this leaf's last voice dies the
   decimator holds a permanent output-Nyquist (period-2) cycle rather than
   decaying to 0. Declared bound over a 315-case input sweep: **36 Q10.21 LSB
   = 0.5625 int16 LSB ≈ −95.3 dBFS**, i.e. below one int16 LSB, so it cannot
   reach this leaf's int16 render on its own and **no metric in the acceptance
   mapping above is affected**. In situ on `seq-notes-repeated-v1`: ±1 Q10.21
   LSB held for all 3,703 blocks (118,496 output samples) after the last voice
   death; that region is **inside** `tools/compare_rtl_model.py`'s compared
   window (every M line of every block) and `tb_voice.sv` matches it exactly.
   The float64 recursion with the same coefficients decays to 1.8e-322 (float64
   subnormals) over the same silence, so this
   is a consequence of the Q10.21 freeze, not of the pinned recursion. Changing
   the decimator's arithmetic is a contract revision owned by SXT-017 /
   [#12](https://github.com/2AMLogic/gf180-surge/issues/12) and is **not** done
   here. Evidence: `reports/halfband-limit-cycle/EVIDENCE.md`.

## Escalations / hand-offs

1. **Budget proposal misses** (coverage, modwheel sequences vs the proposed
   max/RMS/spectral bounds; the repeated-note sequence vs the proposed RMS
   bound only — re-graded under issue #97) are recorded as input to the SXT-013 freeze — either
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

## Superseded by #110 (issue #164, 2026-10-01)

PR #166 (issue #110, merged 2026-09-30) replaced the native-unit `log1p`
`spectral_corr` definition used in the acceptance table (item 2) and the
#145 change-note table above with one shared full-scale log-floor
definition in every comparator. Every `spectral_corr` value quoted above is
the pre-#110 figure and is superseded; full attribution:
`reports/spectral-corr-fs-floor/artifacts/regrade-ledger.{txt,json}`.

| sequence | corr (pre-#110) | corr (#110) | spectral leg | overall verdict |
|---|---|---|---|---|
| seq-notes-coverage-v1 | 0.9791 | 0.9985 | MISS → PASS (no overall effect: max+rms already FAIL) | FAIL → FAIL |
| seq-notes-repeated-v1 | 0.9921 | 0.9988 | PASS → PASS | FAIL (rms only) → FAIL (rms only), unchanged |
| seq-modwheel-v1 | 0.9802 | 0.9914 | PASS → PASS | FAIL (max+rms) → FAIL (max+rms), unchanged |

The acceptance-item-2 sentence "seq-notes-coverage-v1 ... fails all three
proposed bounds (max, RMS and spectral)" is superseded: under #110 its
spectral leg now passes, so it fails only max and rms. No overall verdict
in this record moves, and no `verification` status in
`reports/coverage-v1/leaf-verification.json` moves (the voice gate stays
`model_vs_reference` graded as recorded there).
