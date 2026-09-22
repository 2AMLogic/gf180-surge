# SXT-032 evidence record — voice leaf: modulation behavior LFO

Branch: `loom/leaf-66-lfo` · Issue: #66 (SXT-032) · Date: 2026-09-22

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).

**Claim discipline.** This record advances the model→RTL exactness discipline
for the LFO modulator slice and reports model-vs-reference agreement numbers
under [PROPOSED] budgets (PENDING-FREEZE). It establishes **no** fidelity
claim, **no** preset-support claim (supported delta from this leaf: **0**,
see Applicability), **no** musical-quality claim, and **no**
FPGA/gf180mcu synthesis, timing, or hardware playback claim. `tb_lfo.sv` is
an iverilog-simulated behavioral schedule.

## What was built

| Deliverable | Artifact |
|---|---|
| Frozen fixed-point LFO model | `model/voice/lfo_model.py` (+ freeze section in `model/voice/README.md`) |
| Fail-closed extractor + fixture routes | `model/voice/extract_lfo_inputs.py`, `model/voice/attacky_lfo_inputs.json` |
| Model runner (SXT-022 voice + 6 LFO instances) | `model/voice/run_lfo_model.py` |
| LFO control-plane RTL + harness | `rtl/voice/tb_lfo.sv`, `tools/compare_lfo_rtl_model.py` |
| Reference renderer (routes via host mod API) | `fixtures/render_lfo_fixture.py` |
| Negative controls | `tools/lfo_negative_controls.py`, `rtl/voice/lfo_broken_mutant.sv` |
| Artifacts | `reports/sxt-032/artifacts/` |

## Reference fixture (declared synthetic carrier)

The leaf's named carrier presets are **not renderable end-to-end** by the
landed leaves (see Applicability), so the reference fixture is the landed
SXT-022 voice-slice preset `Basses/Attacky.fxp` (census blob
`4675e423a7489b02f501f7763b4760f64ab035f9`, blob re-verified at extraction
and at every render) **plus two modulation routes added at runtime through
the engine's own host modulation API** (`setModDepth01` — the routing is
created in the engine's live `modulation_voice` list; the preset file is
untouched):

* LFO1 (ms_lfo1) → A Filter 1 Cutoff, normalized depth 0.5 → **depth 65.0 st**
* LFO1 (ms_lfo1) → A Filter 1 Resonance, normalized depth 0.5 → **depth 0.5**

Depths are read back from the engine (`getModDepth01` + routing
`getDepth()`) and recorded in `model/voice/attacky_lfo_inputs.json`; the
model consumes exactly those words. The preset's own modwheel routes
(34.425 st / 0.383) remain active in both reference and model. Reference
determinism: 3 fresh-instance renders per sequence bit-identical (sidecars).

## Acceptance mapping (issue #66)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model with word lengths + op order | **PASS** | `model/voice/lfo_model.py`; freeze section in `model/voice/README.md`; frozen waveform set sine(deform 0)/tri(deform 0)/square/ramp(deform 0), frozen destination classes Cutoff+Resonance; everything else fail-closed at extraction. |
| 2 | Model-vs-pinned-engine budgets on the fixtures (PENDING-FREEZE) | **PASS/PENDING-FREEZE (mixed, honestly reported)** | RMS and spectral bounds PASS on all four sequences; the proposed **max-abs bound FAILS on all four** (achieved 5,062 / 17,998 / 15,506 / 15,505 LSB vs proposed 3,500). Achieved numbers recorded, not tuned — same error class as the SXT-022 voice slice (fixed-point quantization amplified by large filter-coefficient excursions; here the LFO sweeps cutoff ±65 st). Budgets are `[PROPOSED-TO-BE-FROZEN-AT-PILOT]` placeholders; the freeze decision belongs to #12. |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS** | Integer equality, zero mismatches: LFO control plane (`tb_lfo.sv`) — repeated 1,976 checkpoints / 9,880 fields / 1,936 route-sum records; coverage 3,168/15,840/3,123; holds 4,408/22,040/4,388; modwheel 1,852/9,260/1,847. Frozen voice datapath (`tb_voice.sv`, UNCHANGED schedule) on the LFO-influenced control words — repeated 403 ckpt/10,881 fields/25,792 osc samples/196,800 mono; coverage 467/12,609/29,888/273,600; holds 255/6,885/16,320/297,600; modwheel 75/2,025/4,800/182,400. Checkpoints include **LFO phase, EG state, EG phase, EG value, routed output and the routed cutoff/reso sums at every block boundary** of every processed instance (all six instances on voice-creation blocks). |
| 4 | Cycle/state costs vs SXT-016 probes and SXT-015 | **PASS (recorded; divergence note)** | LFO control plane measured on the exact RTL schedule (repeated, 6,150 blocks, 1 concurrent voice): **13,592 qmul** ≈ 0.045 MAC per 48 kHz sample — negligible against the voice path's 37.7–39.8 MAC/sample (SXT-022; the voice-path count 7,422,396 reproduces SXT-022's repeated measurement exactly, confirming the audio datapath is untouched). State ≈ 146 bits/instance (phase 29, EG phase 29, env_val 30, release-start 30, state 3, output 22, flags 3) → 876 bits per voice for six instances with shared arithmetic. **Divergence:** SXT-016 has **no LFO probe row** to reconcile against (the leaf's cost note anticipated `[ESTIMATE] pending SXT-016 refinement`); these measurements are the first concrete per-kernel numbers and are offered as the SXT-016 refinement input. No technology claim of any kind. |
| 5 | Negative controls demonstrably fail | **PASS (all five fail)** | `artifacts/negative-control.txt`, `artifacts/negative-controls.json`: **routing-zeroed (cutoff)** max 20,591 LSB / spec 0.899 vs model 5,062 / 0.993 — 4× worse; **routing-zeroed (reso)** max 7,102 / RMS −31.7 dBFS — fails the budget check, but the margin over the model's own error is SLIM (reso contribution is subtle at this depth; recorded as-is, not tuned); **source-swap** (modwheel bound in place of the LFO, modwheel staircase sequence) max 21,501 / spec 0.833; **free-running confusion** (phase anchored at t=0 instead of the per-voice keytrigger restart) max 22,565 / spec 0.869 — note: in poly mode every voice owns a fresh LFO instance, so the observable keytrigger semantics ARE the per-voice phase restart; the first cut of this control ("skip the restart") was a no-op and was replaced; **RTL mutant** `lfo_broken_mutant.sv` (output round-half-up bias `<<5`→`<<4`) FAILS integer equality (41 mismatches, first at block 90). |

## Engine-behavior findings (recorded, bounded)

1. **`modsource_doprocess` is recomputed per block** by
   `SurgeSynthesizer::prepareModsourceDoProcess` (called from `process`),
   from the live routing lists: LFO1 always processes
   (`SurgeVoice::calc_ctrldata` line comment), LFOs 2..6 process iff routed,
   step-seq LFOs iff their trigmask is non-zero. A near-identical computation
   in `updateUsedState()` IS dead code in this pin (its only caller
   `isModsourceUsed` is only called from the GUI editor); the initially
   suspected "dead LFO2-6 path" was **disproven empirically** on the oracle
   (routing LFO2→cutoff changes the render, and the render follows LFO2's
   own rate when the definition is changed via `setParamVal`) — probe
   transcripts retained in the branch history. Model consequence: the model
   processes routed LFOs 2..6 exactly like the engine.
2. **Carrier LFO destination inventory** (normalized graphs, voice-bus
   routes): Edges Rhythm routes LFO1→Osc1 Pitch/LFO1→F1 Cutoff/LFO1→F2
   Cutoff (scene A) and LFO2→F1 Cutoff, LFO3→F1 Cutoff+Reso (scene B);
   King routes LFO2→F1 Keytrack and LFO1→Osc1 Morph; Rainy routes
   LFO1→scene Pitch. Corpus-wide, 2,878 / 3,561 normalized presets route
   voice LFOs; top destination classes: Pitch (2,745), Volume (2,332),
   Cutoff (1,663), Morph (999). Only Cutoff and Resonance are inside this
   leaf's frozen destination classes.
3. **Carrier LFO definitions** (post-load, fail-closed extractor): Edges
   routes step-seq LFOs (grid state outside normalized schema rev 1.0.0 —
   recorded gap) and a tri LFO with deform −0.171 (type_3 bend, outside the
   frozen waveform arithmetic); King and Rainy route sine LFOs
   (rate 2.775/0.919/2.390, magnitude 0.61–0.78 — inside the frozen set).

## Applicability boundary and coverage delta (honest)

**Supported delta from this leaf: 0 presets.** None of the leaf's named
carriers can be rendered end-to-end yet, independent of LFO support: Edges
Rhythm and King are two-scene (`sm=2`) with active FX (types 5/6/1/2) and
non-Classic oscillator types; Rainy Day Dreamaway is single-scene but has
active FX and Wave/FM-family oscillators; all are outside the landed
single-scene/Classic/LP12/no-FX voice arithmetic (#15) and the voice-slice
generalization #48 is still open. The LFO-isolated slice is therefore
verified on the declared synthetic fixture above, and the leaf's "122
newly-enabled presets / 1,223 corpus B4-predicted" recovery basis is **attribution
only — no preset becomes supported by this work**. What the leaf DOES
establish: the LFO modulator class (one algorithm, six per-instance state
sets, two destination classes) with exact RTL and a reference-bounded model
on the landed voice path; pitch/volume/morph/keytrack destinations, scene
LFOs, step-seq grids, MSEG/Formula and the multi-scene/FX integration are
the recorded boundary for the later voice-scope (SXT-026a/#48) and
integration (#18) leaves.

## Deviations / known error sources (model vs reference)

All are the SXT-022 deviations acting on a wider cutoff excursion, plus:

1. Fixed-point LFO phase/waveform arithmetic vs engine float32 (phase
   accumulation, warp lerp, output scaling); bounded by the reported metrics.
2. LFO `temposync`/`deactivated` flags not observable through surgepy — the
   frozen model implements the non-temposync/non-deactivated paths; at the
   pinned 120 BPM (ratio 1, songpos 0) the temposync rate formula agrees
   with the table path up to the declared table-lerp deviation. Recorded
   gap, same discipline as the SXT-011 send-level gap.
3. Route-depth provenance: fixture depths are runtime readbacks (65.0 st /
   0.5), not preset content; the fixture is synthetic by construction and
   claims no corpus support.

## Licensing / provenance

Everything under `model/voice/`, `rtl/voice/`, `tools/compare_lfo_
rtl_model.py`, `tools/lfo_negative_controls.py`, `fixtures/render_lfo_
fixture.py` and `reports/sxt-032/` is original to this repository
(Apache-2.0 per `LICENSE`). The pinned GPL engine was imported at runtime
only. The single adopted data constant set (1024-entry wst_sine table) is
**recomputed from the cited construction formula** in the pinned tree
(`WaveshaperTables.h`), not copied; no Surge source, presets, or assets are
copied into this repository. Method (fail-closed extraction, exactness
harness, negative-control patterns) follows the landed SXT-022/SXT-023
conventions.

## Explicitly NOT established by this work

* Any fidelity, preset-support, or preset-quality claim (no listening
  record; budgets not frozen; supported delta 0).
* LFO behavior at tempos other than the pinned 120 BPM, tempo-synced LFOs,
  free-running transport (songpos > 0), noise/S&H/step-seq/MSEG/Formula
  modulators, LFO→pitch/volume/morph/keytrack routing, scene LFOs
  (ms_slfo1..6), stereo field, effects interaction.
* Any FPGA/gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware playback result.
