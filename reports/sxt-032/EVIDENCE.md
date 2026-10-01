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
| 2 | Model-vs-pinned-engine budgets on the fixtures (PENDING-FREEZE) | **FAIL vs [PROPOSED] budgets on all four sequences / PENDING-FREEZE (re-graded by #145; recorded, not tuned)** | The spectral bound PASSES on all four sequences (0.9972 / 0.9884 / 0.9874 / 0.9915, repeated / coverage / holds / modwheel); the proposed **max-abs bound FAILS on all four** (achieved 5,626 / 18,030 / 16,070 / 16,069 LSB vs proposed 3,500) and the proposed **RMS bound FAILS on all four** (−32.8 / −29.9 / −31.6 / −32.6 dBFS vs ≤ −46 dBFS). *Republication/re-grade note (issue #145):* this row originally read "PASS/PENDING-FREEZE (mixed)" with "RMS and spectral bounds PASS on all four" and max 5,062 / 17,998 / 15,506 / 15,505; the RMS legs were graded with the inverted `rms_diff_dbfs >= budget` comparison (PR #92, audited in #95 — this leaf's 8 flag flips were recorded there as flag-only because the max leg already failed every row), and the numbers are those of the pre-#123 decimator. Both corrections are applied by #145's regeneration and are separated in the change note below; no overall verdict moved (every row was and is `FAIL against proposed budgets`). Achieved numbers recorded, not tuned — same error class as the SXT-022 voice slice (fixed-point quantization amplified by large filter-coefficient excursions; here the LFO sweeps cutoff ±65 st). Budgets are `[PROPOSED-TO-BE-FROZEN-AT-PILOT]` placeholders; the freeze decision belongs to #12. |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS** | Integer equality, zero mismatches: LFO control plane (`tb_lfo.sv`) — repeated 1,976 checkpoints / 9,880 fields / 1,936 route-sum records; coverage 3,168/15,840/3,123; holds 4,408/22,040/4,388; modwheel 1,852/9,260/1,847 (unaffected by the #175 runner fix below — re-verified unchanged). Frozen voice datapath (`tb_voice.sv`) on the LFO-influenced control words — **re-run at HEAD 2026-09-27 (issue #175)**: repeated 403 ckpt/11,687 fields/25,792 osc samples/196,800 mono; coverage 467/13,543/29,888/273,600; holds 255/7,395/16,320/297,600; modwheel 75/2,175/4,800/182,400 (`reports/sxt-032/artifacts/exactness-voice-{coverage,repeated,holds,modwheel}.json`). **Supersedes a STALE result**: the 2026-09-22 as-landed numbers this row previously reported (repeated 403/10,881/25,792/196,800; coverage 467/12,609/29,888/273,600; holds 255/6,885/16,320/297,600; modwheel 75/2,025/4,800/182,400) were produced by `run_lfo_model.py` emitting the pre-SXT-034 `tb_voice.sv` stimulus layout; after the SXT-034 merge the harness fataled at time 0 (`$readmemh`/`uni count` errors) and could not be re-run — see #145 (found this gap for the SXT-032 leaf) and #175 (fixed `run_lfo_model.py`'s stimulus writer to emit the SXT-034 unison appendix + draw table, matching `model/voice/run_model.py`'s reference layout; `tb_voice.sv` and the frozen model were NOT modified). The field-count increase (+934 per run) is the per-unison-voice `U` checkpoint lines the SXT-034 comparator adds, not a schedule change; `model.wav` renders are byte-identical before/after the runner fix (sha256-verified). `rtl/voice/voice_broken_mutant.sv` FAILS integer equality on the regenerated coverage run dir (99 mismatches, first at block 0), confirming the check still discriminates. Checkpoints include **LFO phase, EG state, EG phase, EG value, routed output and the routed cutoff/reso sums at every block boundary** of every processed instance (all six instances on voice-creation blocks). |
| 4 | Cycle/state costs vs SXT-016 probes and SXT-015 | **PASS (recorded; divergence note)** | LFO control plane measured on the exact RTL schedule (repeated, 6,150 blocks, 1 concurrent voice): **13,592 qmul** ≈ 0.045 MAC per 48 kHz sample — negligible against the voice path's 37.7–39.8 MAC/sample (SXT-022; the voice-path count 7,422,396 reproduces SXT-022's repeated measurement exactly, confirming the audio datapath is untouched). State ≈ 146 bits/instance (phase 29, EG phase 29, env_val 30, release-start 30, state 3, output 22, flags 3) → 876 bits per voice for six instances with shared arithmetic. **Divergence:** SXT-016 has **no LFO probe row** to reconcile against (the leaf's cost note anticipated `[ESTIMATE] pending SXT-016 refinement`); these measurements are the first concrete per-kernel numbers and are offered as the SXT-016 refinement input. No technology claim of any kind. |
| 5 | Negative controls demonstrably fail | **PASS (all five fail)** | `artifacts/negative-control.txt`, `artifacts/negative-controls.json`: (re-run at the #145 HEAD) **routing-zeroed (cutoff)** max 20,592 LSB / spec 0.898 vs model 5,626 / 0.997 — 3.7× worse; **routing-zeroed (reso)** max 7,027 / RMS −31.7 dBFS / spec 0.991 — fails the budget check, but the margin over the model's own error is SLIM (model: 5,626 / −32.8 dBFS / 0.997; the true model also fails the max and RMS proposals, so this control's "FAIL" is not by itself discriminating — reso contribution is subtle at this depth; recorded as-is, not tuned); **source-swap** (modwheel bound in place of the LFO, modwheel staircase sequence) max 21,502 / spec 0.833; **free-running confusion** (phase anchored at t=0 instead of the per-voice keytrigger restart) max 22,565 / spec 0.866 — note: in poly mode every voice owns a fresh LFO instance, so the observable keytrigger semantics ARE the per-voice phase restart; the first cut of this control ("skip the restart") was a no-op and was replaced; **RTL mutant** `lfo_broken_mutant.sv` (output round-half-up bias `<<5`→`<<4`) FAILS integer equality (41 mismatches, first at block 90). |

### Change note (issue #145, 2026-09-27): republished after the #123 halfband branch-order fix

`model-*.wav`, `audio-{coverage,repeated,holds,modwheel}.json`,
`exactness-lfo-*.json` and the negative-control set (`negative-control.txt`,
`negative-controls.json`, `audio-nc-*.json`, `exactness-mutant.json`) were
regenerated at the #145 HEAD. Attribution: the pre-#123 ordering
(`tools/halfband_legacy_render.py`) re-renders all four committed pre-#145
WAVs **byte-identically**, so the metric deltas below are the #123 fix alone.
Full record: `reports/halfband-republication/`.

| sequence | max\|Δ\| LSB | RMS Δ dBFS | spectral corr | overall |
|---|---|---|---|---|
| seq-notes-coverage-v1 | 17,998 → 18,030 | −29.900 → −29.897 | 0.9837 → 0.9884 | FAIL → FAIL |
| seq-notes-repeated-v1 | 5,062 → 5,626 | −32.809 → −32.803 | 0.9928 → 0.9972 | FAIL → FAIL |
| seq-notes-holds-v1 | 15,506 → 16,070 | −31.585 → −31.557 | 0.9834 → 0.9874 | FAIL → FAIL |
| seq-modwheel-v1 | 15,505 → 16,069 | −32.696 → −32.646 | 0.9877 → 0.9915 | FAIL → FAIL |

* Separate from #123: the regenerated JSONs carry the corrected RMS-leg
  polarity (PR #92 / #95): `rms_diff_dbfs` flips `true → false` on all four,
  which is why row 2 now reads FAIL on RMS. No overall verdict moved.
* Voice-datapath RTL pairing (row 3): BLOCKED when #145's measurements were
  taken (stimulus-format incompatibility with the post-SXT-034
  `tb_voice.sv`, routed to #175). #175 has since fixed the runner and re-run
  the pairing at HEAD (row 3, PASS); that re-run is #175's evidence, not
  #145's, and it was made on a tree that already contained #123.
* Negative controls: all five still FAIL their check (`overall_ok` true).

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

## Superseded by #110 (issue #164, 2026-10-01)

PR #166 (issue #110, merged 2026-09-30) replaced the native-unit `log1p`
`spectral_corr` definition used throughout the acceptance table and the
#145 change note above with one shared full-scale log-floor definition in
every comparator. Full attribution: `reports/spectral-corr-fs-floor/
artifacts/regrade-ledger.{txt,json}`.

| row | corr (pre-#110) | corr (#110) |
|---|---|---|
| seq-notes-coverage-v1 (`audio-coverage.json`) | 0.9884 | 0.9981 |
| seq-notes-repeated-v1 (`audio-repeated.json`) | 0.9972 | 0.9989 |
| seq-notes-holds-v1 (`audio-holds.json`) | 0.9874 | 0.9978 |
| seq-modwheel-v1 (`audio-modwheel.json`) | 0.9915 | 0.9933 |
| routing-zeroed cutoff (`audio-nc-cutoff-zeroed.json`) | 0.8983 | 0.8053 |
| routing-zeroed reso (`audio-nc-reso-zeroed.json`) | 0.9907 | 0.9811 |
| source-swap (`audio-nc-source-swap.json`) | 0.8328 | 0.6617 |
| free-running confusion (`audio-nc-free-running.json`) | 0.8658 | 0.7311 |

No verdict moves: all four sequences stay FAIL (max/rms already miss), and
all five negative controls stay FAIL with the same PASS/FAIL-discrimination
classification as recorded above (routing-zeroed reso's spectral leg stays
above 0.98, so it is still non-discriminating on that leg alone, the same
caveat already recorded). No `verification` status in
`reports/coverage-v1/leaf-verification.json` moves.
