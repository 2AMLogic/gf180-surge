# SXT-035 evidence record — voice leaf: modulation behavior modwheel

Branch: `loom/leaf-69-modwheel` · Issue: #69 (SXT-035) · Date: 2026-09-22

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).

**Claim discipline.** This record advances the model→RTL exactness discipline
for the scene-modwheel control path (controller → FAST_LINE smoothing → route
scaling → destinations) and reports model-vs-reference agreement numbers
under [PROPOSED] budgets (PENDING-FREEZE). It establishes **no** fidelity
claim, **no** preset-support claim (supported delta from this leaf: **0**,
see Applicability), **no** musical-quality claim, and **no**
FPGA/gf180mcu synthesis, timing, or hardware playback claim. `tb_mw.sv` and
`tb_voice.sv` are iverilog-simulated behavioral schedules.

## What was built

| Deliverable | Artifact |
|---|---|
| Frozen model extension (route vocabulary + VCA destination) | `model/voice/voice_model.py` (+ freeze section in `model/voice/README.md`) |
| Fail-closed fixture extractor + engine readbacks | `model/voice/extract_mw_inputs.py`, `model/voice/attacky_mw_inputs.json` |
| Model runner (route-table control pass + trace + RTL stimulus) | `model/voice/run_mw_model.py` |
| Modwheel control-plane RTL + harness | `rtl/voice/tb_mw.sv`, `tools/compare_mw_rtl_model.py` |
| Reference renderer (route via host mod API) | `fixtures/render_mw_fixture.py` |
| Negative controls | `tools/mw_negative_controls.py`, `rtl/voice/tb_mw_broken_mutant.sv` |
| Artifacts | `reports/sxt-035/artifacts/` |

**Extend, don't fork:** the landed `Modwheel` FAST_LINE smoother is reused
unchanged (one smoothing implementation); the landed SXT-022 v1 path, the
SXT-026a class paths, and the SXT-032 LFO runner are untouched. Landed
fixtures render **bit-identically** after the extension (verified against
the committed artifact hashes: SXT-022 v1 ×3, SXT-026a bells, SXT-032 LFO
×2 — all sha256-equal pre/post change).

## Reference fixture (declared synthetic carrier)

The leaf's named carrier presets are **not renderable end-to-end** by the
landed leaves (see Applicability), so per the SXT-032 sibling convention the
reference fixture is the landed SXT-022 voice-slice preset
`Basses/Attacky.fxp` (census blob `4675e423a7489b02f501f7763b4760f64ab035f9`,
blob re-verified at extraction and at every render):

* preset content: the preset's own modwheel routes — Filter 1 Cutoff
  34.425018 st, Filter 1 Resonance 0.383036 (engine readbacks, cross-checked
  against `graphs.jsonl` `md` rows) — active in BOTH the reference and the
  model;
* runtime addition (host modulation API `setModDepth01`, preset file
  untouched): ms_modwheel → scene A `vca_level` ("A VCA Gain"), normalized
  depth 0.4 → **raw depth 38.4 dB** (read back; param range ±48 dB). This is
  the new destination class this leaf freezes.

Determinism: 3 fresh-instance renders per sequence bit-identical (sidecars).
Reference determinism, scheduling, reset, tail and audio policies follow
`fixtures/render_fixture.py`.

## Acceptance mapping (issue #69)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model with word lengths + op order | **PASS** | Freeze section in `model/voice/README.md`: route vocabulary {Filter 1 Cutoff 308, Filter 1 Resonance 309, VCA Gain 298} (+ landed FM Depth 260, Sine class, CC-refused); Q10.21 words throughout; `param += qint(depth)·value` in md order into the local accumulator; VCA terms accumulate into the same `mod_vca_db` accumulator as velocity (engine localcopy semantics). Pinned-source citations recorded (ModulationSource.h `ControllerModulationSourceVector` FAST_LINE branch; SurgeStorage.h:2063 default; SurgeSynthesizer.cpp `channelController` case 1). Anything else fail-closed at extraction. |
| 2 | Model-vs-pinned-engine budgets on the fixtures (PENDING-FREEZE) | **FAIL vs [PROPOSED] budgets on all three fixtures / PENDING-FREEZE (recorded, not tuned)** | `artifacts/audio-*.json` (proposed bounds: max ≤ 3,500 LSB, RMS diff ≤ −46 dBFS, spectral corr ≥ 0.98): seq-notes-repeated-v1 passes the max (2,328 LSB) and spectral (0.9921) bounds but **FAILS the RMS bound** (−33.3 dBFS is louder than the ≤ −46 dBFS proposal) → `FAIL against proposed budgets`; it reproduces the landed SXT-022 numbers exactly, including that same RMS-leg failure (with no CC events the fixture reduces to the landed fixture bit-exactly — an invariance check, sha-compared). seq-notes-coverage-v1 misses max (4,760), RMS (−30.1 dBFS) and spectral (0.9791) exactly as the landed fixture does. *Re-grade note (issue #97):* this row originally read "PASS/PENDING-FREEZE (mixed)" with seq-notes-repeated-v1 passing all three bounds; its RMS leg was graded with the inverted `rms_diff_dbfs >= budget` comparison fixed in PR #92 and audited in issue #95 (`reports/tooling-rms-polarity-audit/`). The numeric metrics were unchanged by that re-grade; only the RMS-leg grading and the overall status moved. *Republication note (issue #145):* the numbers in this row are those of the model re-rendered after the #123 halfband fix (pre-#123: repeated 2,321 / 0.9874, coverage 0.9754, modwheel 0.9870); no verdict moved — see the #145 change note below. **seq-modwheel-v1 FAILS max and RMS (max 65,534 = int16 span; RMS −18.0 dBFS; spec 0.9875)**: the routed reference is intentionally driven into hard clipping (engine output peak 6.34 float; 16,398 WAV samples at full scale), and the model-vs-engine deviations concentrate in the FAST_LINE ramp windows (40/60 and 51/60 blocks right after CC dispatches vs 22/240 and 64/840 during later plateaus). Achieved numbers recorded, not tuned — same error class as the landed SXT-022 modwheel sequence (declared smoothing-order deviation + fixed-point quantization), amplified by the ×42 VCA-Gain swing the new route produces. Budget misses are the bounded finding for the SXT-013/#12 freeze; nothing here is weakened to pass. |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS (control plane, re-run at #145 HEAD) / voice-datapath pairing BLOCKED at HEAD (as-landed PASS is STALE)** | *#145 status:* the modwheel control plane (`tb_mw.sv`) re-ran at HEAD with identical counts and 0 mismatches on all three sequences. The voice-datapath pairing could NOT be re-run: `run_mw_model.py` emits the pre-SXT-034 init/ctrl layout and the post-SXT-034 `tb_voice.sv` refuses it at time 0 (`FATAL: uni count 0 outside 1..16`) — the incompatibility this record already noted for SXT-032, which also covers this runner; not caused by #123. `exactness-voice-*.json` remain the as-landed results and are **STALE** (follow-up [#175](https://github.com/2AMLogic/gf180-surge/issues/175)). As landed — integer equality, zero mismatches (box runs): modwheel control plane (`tb_mw.sv`): modwheel 5,700 / route-sum 1,847 / 5,541 sums; retrig 6,150 / 1,936 / 5,808; coverage 8,550 / 3,123 / 9,369. Frozen voice datapath (`tb_voice.sv`, corrected to the model order — see findings): modwheel 75 ckpt / 2,175 fields / 4,800 oscout / 182,400 mono; retrig 403 / 11,687 / 25,792 / 196,800; coverage 467 / 13,543 / 29,888 / 273,600. Checkpoints include the smoothed modwheel value at every block boundary and the per-voice routed sums (cutoff/reso/vca) for every running voice at every block. |
| 4 | Cycle/state costs vs SXT-016 probes and SXT-015 | **PASS (recorded; divergence note)** | Modwheel control plane, measured on the exact RTL schedule: 11,244 qmul / 5,700 blocks ≈ **0.062 MAC per 48 kHz sample** (2 qmul per block for the smoother + 3 per running-voice block for the route sums) — negligible against the voice path's 37.7–39.8 MAC/sample (SXT-022). Voice path on this leaf's stimulus: 7,182,314 qmul / 5,700 blocks = 39.3 MAC/sample (modwheel), 7,670,204 / 6,150 = 38.99 (retrig), 11,288,835 / 8,550 = 41.3 (coverage; two overlapping voices). **Reconciliation:** retrig reproduces the SXT-022 measurement (7,422,396) plus exactly the #48 mix1-blend additions (1,936 voice-blocks × 128 qmul = 247,808), confirming the datapath is otherwise untouched. State: 3 × 32-bit words (target/startingpoint/value = 96 bits) + a fixture-constant route ROM (2 words/route, 3 routes) + no per-voice state (the modwheel is a single scene-level source; per-voice state is only the routed sums' consumers in the voice path). **Divergence:** SXT-016 has no control-smoother probe row to reconcile against (the leaf's cost note anticipated `[ESTIMATE] pending SXT-016 refinement`); these are the first concrete numbers, offered as the SXT-016 refinement input. No technology claim of any kind. |
| 5 | Negative controls demonstrably fail | **PASS (all fail)** | `artifacts/negative-control.txt`, `negative-controls.json` (**re-run 2026-09-27**, see the regeneration note below; the numbers below are that run's): **routing-zeroed cutoff** (depth→0) RMS −13.9 dBFS / spec 0.9844; **routing-zeroed reso** RMS −17.967 dBFS / spec 0.9864 (SLIM spectral margin over the model's own 0.9875 — recorded as-is, not tuned, same caveat class as SXT-032's reso control; its RMS leg is also worse than the baseline's 4,106.7 LSB at 4,140.9 LSB, so it does not rest on the spectral leg alone); **routing-zeroed vca** RMS −11.8 / spec 0.8615; **smoothing-bypass** (FAST_LINE replaced by instant jump) — carried by a **control-plane discriminator** (issue #163), not by an audio metric: blocks-to-converge of the smoothed modwheel word after each of the 5 CC dispatches is **0 for the mutant vs 54 for the unmutated model** (declared FAST_LINE ramp 1/inv = 54.42 blocks; the leg trips below 27, so the margin is 27 blocks against the threshold and 54 blocks against the baseline). It reads `model_trace.json`'s `mw_pre`/`mw_value` records only — no reference audio, no `spectral_corr` value. Its whole-render audio legs do **not** carry it: RMS is *better* than the baseline's (−20.2 vs −18.0 dBFS) and the spectral margin is 0.0025 wide (0.9850 vs 0.9875) and definition-dependent (#110/#166). The windowed-rms variant of SXT-042's `note_windows()`/`windowed_rms()` pattern was evaluated and **also does not discriminate** here — over the five CC-transition windows the mutant's error is 10,354.9 LSB against the baseline's 15,561.3 LSB, because the routed reference saturates at the int16 span through most of the ramps (per-window numbers and saturated fractions recorded in `negative-controls.json` → `transition_window_rms`, explicitly marked "recorded only — NOT a discriminator"); **source-swap** (landed SXT-032 LFO1 bound in place of the modwheel, per-voice instances) RMS −10.1 / spec 0.7295 — dramatically worse; **out-of-class refusal**: route to 'A Highpass' (dest 303) → runner exit 2 naming the destination; the three named carriers → extractor exit 2 (transcripts in the control log); **RTL mutant** `tb_mw_broken_mutant.sv` (FAST_LINE da rounding `FQ`→`FQ−1`) FAILS integer equality (41 mismatches, first at block 300 — the first CC dispatch). On this fixture the max-abs metric saturates at the int16 span, so controls are additionally required to degrade a metric with headroom (RMS, spectral, or — for C2 — the control-plane ramp) vs the unmutated model; the leg that fired is now named per control in `beyond_model_error_via`, and `control_ok_without_spectral_leg` records that **every** control still holds with the whole-render spectral leg struck out entirely. **Failure control for the new C2 leg:** the unmutated baseline is run through the identical discriminator and does NOT trip it (min ramp 54 ≥ 27, recorded at `baseline.mw_ramp`); a baseline that tripped would void the whole record (the runner forces `overall_ok=false`). |

### Change note (issue #163, 2026-09-27): new C2 discriminator; scope of the re-run, and what is STALE

`artifacts/negative-control.txt`, `negative-controls.json`, `audio-nc-*.json`
and `exactness-mutant.json` were regenerated on 2026-09-27 to record the new C2
control-plane discriminator. **Only those files were re-run.** Everything else
in `artifacts/` still dates from the original 2026-09-22 run (commit
`f4ae059`), so the two sets are no longer from the same tree:

- The re-run picked up changes that landed on `main` after `f4ae059`, notably
  the halfband-D2 branch-index fix (#146), the SXT-037 LP12 coefficient-maker
  amendment, and two shared-comparator changes (#93, #100: tail-region gating
  and the `rms_diff_dbfs` floor). Row 5's metrics therefore differ slightly
  from the original run (e.g. baseline spectral 0.9870 → 0.9875,
  vca-zeroed 0.8556 → 0.8615, max-abs 38,461 → 38,478). **No verdict moved**:
  every control still FAILs its check and `overall_ok` is still `true`.
- The `audio-nc-*.json` files additionally pick up the RMS-leg polarity fix
  (PR #92 / issue #95). Their `proposed_budget_results.rms_diff_dbfs` flips
  `true → false`, which is the *correct* grading — the original files carried
  the inverted comparison. The overall verdict was `FAIL against proposed
  budgets` before and after.
- **STALE (NOT re-run) at #163:** `audio-seq-*.json`, `exactness-*.json` (other than
  the mutant), `model-seq-*.wav`, `costs.txt`, and the row 2/3/4 numbers that
  cite them are from `f4ae059` and predate the changes listed above. Row 2's
  `seq-modwheel-v1` spectral value (0.9870) is that stale artifact's number and
  no longer matches the re-run baseline (0.9875). A full SXT-035 re-evidence
  pass against current `main` is out of scope for #163 and is tracked
  separately; nothing here should be read as a re-qualification of rows 2–4.
- The re-run was performed on a host without the pinned oracle build. The three
  carrier refusals need only the pinned `.fxp` blobs (the refusal is decided
  from the in-repo `corpus/normalized/graphs.jsonl` after the census blob-SHA-1
  check), so those blobs were staged **outside the repository** from the pinned
  commit `58914e59…` via `ORACLE_SURGE_DIR`; all three reproduced their original
  refusal strings byte-for-byte. No engine source, asset, or preset was copied
  into this repository.

### Change note (issue #145, 2026-09-27): the #163 STALE set, republished

#145 re-ran what #163 left STALE: `model-seq-*.wav`, `audio-seq-*.json` and
`exactness-mw-*.json` are regenerated at the #145 HEAD (rows 2 and 3 now cite
them). Attribution: the pre-#123 ordering (`tools/halfband_legacy_render.py`)
re-renders all three committed pre-#145 WAVs **byte-identically**, so the
metric deltas below are the #123 fix alone. Full record:
`reports/halfband-republication/`.

| sequence | max\|Δ\| LSB | RMS Δ dBFS | spectral corr | overall |
|---|---|---|---|---|
| seq-notes-coverage-v1 | 4,760 → 4,760 | −30.138 → −30.139 | 0.9754 → 0.9791 | FAIL → FAIL |
| seq-notes-repeated-v1 | 2,321 → 2,328 | −33.327 → −33.328 | 0.9874 → 0.9921 | FAIL → FAIL |
| seq-modwheel-v1 | 65,534 → 65,534 | −18.040 → −18.039 | 0.9870 → 0.9875 | FAIL → FAIL |

* The coverage and modwheel JSONs also carry the corrected RMS-leg polarity
  (PR #92 / #95): `rms_diff_dbfs` flips `true → false`. Comparator
  correction, not #123; no overall verdict moved.
* Still **STALE / BLOCKED**: `exactness-voice-*.json` (voice-datapath pairing
  blocked, row 3) and `costs.txt` (its voice qmul counts come from that
  blocked pairing; the #123 fix changes which branch sample is summed, not the
  number of operations, so no count is expected to move — stated, not
  measured).
* The #163 negative-control set was already regenerated on a tree that
  contained #123 and is not re-run here.

## Engine-behavior findings (recorded, bounded)

1. **The modwheel is a single per-scene controller instance**
   (`SurgeSynthesizer.cpp:145`: one `ControllerModulationSource(storage.smoothingMode)`
   per scene; `channelController` case 1 sets the target on every scene's
   instance). Single-scene class ⇒ one instance — the model's single shared
   smoother is structural, not an approximation, inside the declared class.
2. **Routing-list order is not order-observable through surgepy**:
   after `setModDepth01`, `getAllModRoutings` returns the VCA row before the
   preset rows (insertion or id order is not exposed). All frozen
   destinations are distinct parameters accumulated additively, so the
   application order changes only intermediate saturating adds, which the
   fixture magnitudes never reach; the model declares md-array order.
3. **VCA Gain destination semantics**: 'A VCA Gain' modulates the
   `vca_level` parameter (dB domain, range ±48 dB) before `db_to_linear` —
   the same localcopy accumulation the landed velocity→VCA route uses, which
   is why the two share `mod_vca_db` in the model.
4. **Carrier modwheel destination inventory** (normalized graphs, scene-A
   routes, all 91 recovery-basis presets route the modwheel; corpus-wide
   1,406/3,561 presets route it in some scene): F1 Cutoff 31, F2 Cutoff 16,
   F1 Reso 14, F1 FEG-mod 13, FM Depth 11, F2 Reso 9, Amp-EG Attack 8,
   FEG Decay 8, LFO3 Amplitude 7, Feedback 6, Amp-EG Decay 6, LFO1
   Amplitude 6, FEG Sustain 6, VCA Gain 5, … — only Cutoff/Reso/VCA-Gain
   (+FM Depth on Sine presets, CC-refused) are inside this leaf's frozen
   classes.

## RTL corrections to the landed schedule (findings; landed claims unchanged)

Two latent `tb_voice.sv` deviations from the frozen model surfaced by this
leaf's wider parameter range, both corrected to the model order and both
verified bit-identical on every landed fixture (SXT-022 ×3, bells, retrig
re-run PASS 0 mismatches; model WAV sha256-equal pre/post):

1. **Scene ±8 hard-clip placement**: the RTL clamped after the halfband
   decimator; the engine/model clip the scene bus BEFORE decimation and
   again after master amplitude (README v1 step 7). Equivalent only while
   the scene never saturates — the landed fixtures never saturate; this
   leaf's ×42 VCA-Gain fixture does.
2. **Gain/output ramp product width**: `d_gain·(k+1)` in 32-bit
   self-determined width overflows once the VCA route drives `fbp_gain` to
   ~2^28; the model's big-int product is exact. The RTL now evaluates the
   ramp products at 64 bits.

Also recorded (not reconciled here): `run_lfo_model.py` still emits 32-word
slot records (pre-#48 layout) while `tb_voice.sv` streams 40-word records,
so the SXT-032 voice pairing cannot be re-run until its stimulus is
regenerated — SXT-032 owner.

## Applicability boundary and coverage delta (honest)

**Supported delta from this leaf: 0 presets.** None of the leaf's named
carriers can be rendered end-to-end yet, independent of modwheel support:
Rainy Day Dreamaway (filter config not serial-1, FX active, non-class oscs),
Pluck 2 Pad Demon Sad (filter config not serial-1, FX active),
Alone (mixer paths o1+o2+o3, Sine uni 9, FX active) — all refused by the
fail-closed extractor (transcripts in `artifacts/negative-control.txt`).
Even if the voice class were met, 86 of the 91 recovery presets route the
modwheel to at least one destination outside this leaf's frozen classes
(EG times, osc pitch/volume/width, Filter 2, FX sends, LFO amplitudes,
feedback, filter balance, waveshaper drive). The modwheel-isolated slice is
therefore verified on the declared synthetic fixture above, and the issue's
"91 newly-enabled / 821 corpus B4-predicted" recovery basis is
**attribution only — no preset becomes supported by this work**. What the
leaf DOES establish: the scene-modwheel modulator class (one shared
FAST_LINE source; route table {F1 Cutoff, F1 Reso, VCA Gain}) with exact
RTL and a reference-bounded model on the landed voice path. The remaining
destination classes, multi-scene smoothing, and multi-scene/FX integration
are the recorded boundary for later leaves.

## Deviations / known error sources (model vs reference)

All are the landed SXT-022 deviations acting on a wider, saturated swing,
plus:

1. **FAST_LINE stepping order** (declared, SXT-022): the model steps the
   smoother at the end of the control pass; the engine's exact interleaving
   with voice control passes is not observable through surgepy. On the
   staircase fixture the model-vs-engine deviations concentrate exactly in
   the ramp windows after each CC (diagnostic in acceptance item 2).
2. **Fixed-point vs float32 at the clip boundary**: the routed reference is
   clipped at the WAV layer (peak 6.34 float); quantization-noise differences
   flip individual clipped samples, so max-abs saturates at the int16 span.
   RMS/spectral bounds carry the comparison; both are recorded.
3. Route-depth provenance: the VCA-Gain fixture depth is a runtime readback
   (normdepth 0.4 → raw 38.4 dB), not preset content; the fixture is
   synthetic by construction and claims no corpus support.

## Licensing / provenance

Everything under `model/voice/`, `rtl/voice/`, `tools/compare_mw_rtl_
model.py`, `tools/mw_negative_controls.py`, `fixtures/render_mw_fixture.py`
and `reports/sxt-035/` is original to this repository (Apache-2.0 per
`LICENSE`). The pinned GPL engine was imported at runtime only; no Surge
source, tables, presets, or assets are copied into this repository. Method
(fail-closed extraction, exactness harness, negative-control patterns)
follows the landed SXT-022/SXT-026a/SXT-032 conventions. `run_model.py`'s
v1 adapter regained its `scene_octave`/`keytrack_root` words (regressed by
#48; the v1 path had become unrunnable) — verified bit-identical output.

## Explicitly NOT established by this work

* Any fidelity, preset-support, or preset-quality claim (no listening
  record; budgets not frozen; supported delta 0).
* Modwheel behavior at destinations outside {F1 Cutoff, F1 Reso, VCA Gain}
  (+FM Depth, landed), bipolar smoothing, other smoothing modes, multi-scene
  instances, modwheel→FX or →LFO routing, stereo field, effects interaction.
* Any FPGA/gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware playback result.
