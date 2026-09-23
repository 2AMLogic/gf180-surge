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
| 2 | Model-vs-pinned-engine budgets on the fixtures (PENDING-FREEZE) | **PASS/PENDING-FREEZE (mixed, honestly reported)** | `artifacts/audio-*.json`: seq-notes-repeated-v1 passes all three proposed bounds (max 2,321 LSB; RMS −33.3 dBFS; spec 0.9874) and reproduces the landed SXT-022 numbers exactly (with no CC events the fixture reduces to the landed fixture bit-exactly — an invariance check, sha-compared). seq-notes-coverage-v1 misses max (4,760) and spectral (0.9754) exactly as the landed fixture did. **seq-modwheel-v1 FAILS max and RMS (max 65,534 = int16 span; RMS −18.0 dBFS; spec 0.9870)**: the routed reference is intentionally driven into hard clipping (engine output peak 6.34 float; 16,398 WAV samples at full scale), and the model-vs-engine deviations concentrate in the FAST_LINE ramp windows (40/60 and 51/60 blocks right after CC dispatches vs 22/240 and 64/840 during later plateaus). Achieved numbers recorded, not tuned — same error class as the landed SXT-022 modwheel sequence (declared smoothing-order deviation + fixed-point quantization), amplified by the ×42 VCA-Gain swing the new route produces. Budget misses are the bounded finding for the SXT-013/#12 freeze; nothing here is weakened to pass. |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS** | Integer equality, zero mismatches (box runs): modwheel control plane (`tb_mw.sv`): modwheel 5,700 / route-sum 1,847 / 5,541 sums; retrig 6,150 / 1,936 / 5,808; coverage 8,550 / 3,123 / 9,369. Frozen voice datapath (`tb_voice.sv`, corrected to the model order — see findings): modwheel 75 ckpt / 2,175 fields / 4,800 oscout / 182,400 mono; retrig 403 / 11,687 / 25,792 / 196,800; coverage 467 / 13,543 / 29,888 / 273,600. Checkpoints include the smoothed modwheel value at every block boundary and the per-voice routed sums (cutoff/reso/vca) for every running voice at every block. |
| 4 | Cycle/state costs vs SXT-016 probes and SXT-015 | **PASS (recorded; divergence note)** | Modwheel control plane, measured on the exact RTL schedule: 11,244 qmul / 5,700 blocks ≈ **0.062 MAC per 48 kHz sample** (2 qmul per block for the smoother + 3 per running-voice block for the route sums) — negligible against the voice path's 37.7–39.8 MAC/sample (SXT-022). Voice path on this leaf's stimulus: 7,182,314 qmul / 5,700 blocks = 39.3 MAC/sample (modwheel), 7,670,204 / 6,150 = 38.99 (retrig), 11,288,835 / 8,550 = 41.3 (coverage; two overlapping voices). **Reconciliation:** retrig reproduces the SXT-022 measurement (7,422,396) plus exactly the #48 mix1-blend additions (1,936 voice-blocks × 128 qmul = 247,808), confirming the datapath is otherwise untouched. State: 3 × 32-bit words (target/startingpoint/value = 96 bits) + a fixture-constant route ROM (2 words/route, 3 routes) + no per-voice state (the modwheel is a single scene-level source; per-voice state is only the routed sums' consumers in the voice path). **Divergence:** SXT-016 has no control-smoother probe row to reconcile against (the leaf's cost note anticipated `[ESTIMATE] pending SXT-016 refinement`); these are the first concrete numbers, offered as the SXT-016 refinement input. No technology claim of any kind. |
| 5 | Negative controls demonstrably fail | **PASS (all fail)** | `artifacts/negative-control.txt`, `negative-controls.json`: **routing-zeroed cutoff** (depth→0) RMS −13.9 dBFS / spec 0.9842; **routing-zeroed reso** spec 0.9858 (SLIM margin over the model's own spec 0.9870 — recorded as-is, not tuned, same caveat class as SXT-032's reso control); **routing-zeroed vca** RMS −11.8 / spec 0.8556; **smoothing-bypass** (FAST_LINE replaced by instant jump) spec 0.9844 — note its RMS is *better* than the baseline's (−20.2 vs −18.0): the bypass changes the error, it does not fix it; **source-swap** (landed SXT-032 LFO1 bound in place of the modwheel, per-voice instances) RMS −10.1 / spec 0.7283 — dramatically worse; **out-of-class refusal**: route to 'A Highpass' (dest 303) → runner exit 2 naming the destination; the three named carriers → extractor exit 2 (transcripts in the control log); **RTL mutant** `tb_mw_broken_mutant.sv` (FAST_LINE da rounding `FQ`→`FQ−1`) FAILS integer equality (41 mismatches, first at block 300 — the first CC dispatch). On this fixture the max-abs metric saturates at the int16 span, so controls are additionally required to degrade a metric with headroom (RMS or spectral) vs the unmutated model — recorded per control. |

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
