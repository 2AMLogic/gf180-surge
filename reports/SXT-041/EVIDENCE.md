# SXT-041 evidence record — voice leaf: modulation behavior `slfo`

Branch: `feature/issue-75` · Issue: #75 (SXT-041) · Date: 2026-10-02

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).
Oracle installed on the dispatch worker via `oracle/fetch-and-build.sh
--prebuilt` (#232 / PR #299), prebuilt artifact sha256 `d2cc702913c4`.
Simulator: Icarus Verilog 13.0 (stable).

**Claim discipline.** This record advances the model→RTL exactness discipline
for the scene-LFO (SLFO) control plane and reports model-vs-reference
agreement numbers against `[PROPOSED]` budgets (PENDING-FREEZE). It
establishes **no** fidelity claim, **no** preset-support claim (supported
delta from this leaf: **0** — see Applicability), **no** musical-quality
claim, and **no** FPGA/gf180mcu synthesis, timing, area, power or
hardware-playback claim. `tb_slfo.sv` is an iverilog-simulated behavioral
schedule.

## What was built

| Deliverable | Artifact |
|---|---|
| Frozen scene-scope scheduling model | `model/voice/slfo_model.py` (+ freeze section in `model/voice/README.md`) |
| Fail-closed extractor + declared fixture routes | `model/voice/extract_slfo_inputs.py`, `model/voice/attacky_slfo_inputs.json`, `model/voice/attacky_slfo_fast_inputs.json` |
| Model runner (SXT-022 voice + 6 scene-LFO instances) | `model/voice/run_slfo_model.py` |
| Scene-scope fixture sequence (S2/S3 observable) | `model/voice/sequences/sxt041-slfo-overlap-v1.json` |
| Scene-LFO control-plane RTL + exactness harness | `rtl/voice/tb_slfo.sv`, `tools/compare_slfo_rtl_model.py` |
| Reference renderer (routes via host mod API) | `fixtures/render_slfo_fixture.py` |
| Negative controls (+ generated RTL mutants) | `tools/slfo_negative_controls.py`, `artifacts/rtl-mutants/*.sv` |
| Cost / applicability / harness probes | `tools/slfo_cost_report.py`, `tools/slfo_applicability_scan.py`, `tools/slfo_harness_failure_probe.py` |
| Tests (no oracle, no iverilog needed) | `tests/test_sxt041_slfo.py` (22 tests) |
| Artifacts | `reports/SXT-041/artifacts/` |

**No new arithmetic was frozen.** The pinned engine constructs scene LFOs
from the same `LFOModulationSource` class SXT-032 already froze, so
`slfo_model.py` *imports* `lfo_model` and reuses its phase accumulator,
`lfoeg_*` state machine, waveform evaluation, unipolar fold and magnitude
scaling verbatim. Duplicating them would create a second, driftable copy of a
frozen kernel. What this leaf freezes is the **scene-scope scheduling**
(S1..S5 below) and its one new state field, the `route_out` latch.

## The scene-scope delta (re-verified against the pin for this record)

Each claim below was read directly out of the pinned sources at the pinned
commit for this evidence pass — not inherited from the SXT-032 section.

| Axis | Scene (SLFO) behavior | Pinned citation | Control |
|---|---|---|---|
| ids | `ms_slfo1..6` = **23..28** (`ms_lfo1..6` = 17..22) | `ModulationSource.h` `modsources` enum | — |
| scope predicate | `isScenelevel()` **true**; `isVoiceModulator()` false *exactly* for the six SLFOs → routes land in `scene[].modulation_scene`, not `modulation_voice` | `ModulationSource.h:211`, `:252` | extractor refuses a route that lands in the wrong list |
| **S1** | ONE instance set per **scene**, shared by every voice (the voice borrows pointers); per-instance state still never merged | `SurgeVoice.cpp:325..330` | `--shared-instance`, `slfo_shared_mutant.sv` |
| **S2** | attack gated on `getNonReleasedVoices(scene) == 0`, evaluated **before** the new voice exists → a legato note-on does **not** restart a scene LFO | `SurgeSynthesizer.cpp:755`, count at `:628` (`v->state.gate`) | `--per-note-retrigger` |
| **S3** | release gated on the same predicate, evaluated **after** `SurgeVoice::release` clears the gate | `SurgeSynthesizer.cpp:1832` | `--per-note-retrigger` |
| **S4** | the scene route is **one block behind** the instance: the `modulation_scene` apply loop runs *before* the `n_lfos_scene` `process_block()` loop | `SurgeSynthesizer.cpp` `processControl` (~`:4634` apply, `:4648` process) | `--zero-delay-route`, `slfo_nodelay_mutant.sv` |
| **S5** | all six instances advance **every** block while the scene plays — no `modsource_doprocess` gate, including blocks with no voices and the renderer's settle blocks | `SurgeSynthesizer.cpp:4648` loop is unconditional | `--gated-process` |

**S4 is the one genuinely non-obvious behavior in this leaf, and the pin makes
it unambiguous**: the *original* pre-apply `n_lfos_scene` process loop is
still present **commented out** at `SurgeSynthesizer.cpp:4629..4630`,
immediately above the live apply loop. The asymmetry is real and deliberate —
`ms_modwheel` is `process_block()`-ed earlier in the same function, *before*
the apply loop, so SXT-035's modwheel route is **not** delayed. A reviewer
checking only "same class as lfo" would miss this; the `route_out` latch and
its mutant exist to pin it.

## Reference fixture (declared synthetic carrier) — see the deviation below

The leaf's three named carrier presets are **not renderable end-to-end** by
the landed voice arithmetic (Applicability), so the reference fixture is the
landed SXT-022 voice-slice preset `Basses/Attacky.fxp` (census blob
re-verified at extraction and at every render) **plus**, applied at runtime
through the engine's own APIs (the preset file is never modified):

* two definition overrides on SLFO2 (`setParamVal` on `scene.lfo[7]`):
  shape → `lt_square`, rate → 1.0. Without them all twelve LFO slots carry
  identical default definitions and per-instance separation is not
  *observable*;
* three scene modulation routes (`setModDepth01`), which the engine files in
  `scene[0].modulation_scene` **because `isScenelevel(ms_slfo*)` is true** —
  the placement is this leaf's subject matter and is re-verified at render
  time: SLFO1→Filter 1 Cutoff (0.5), SLFO1→Filter 1 Resonance (0.5),
  SLFO2→Filter 1 Resonance (0.25).

A second `fast` variant (SLFO1 rate 4.0, SLFO2 square rate 5.0) is the
declared rate/shape corner. Reference determinism: 3 fresh-instance repeats
per render, byte-identical (`deterministic: true` in every sidecar).

## Acceptance mapping (issue #75)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model with word lengths + op order documented | **PASS** | `model/voice/slfo_model.py` + the SXT-041 freeze section in `model/voice/README.md`: S1..S5 scheduling, the frozen op order (apply-from-latch → advance → re-latch), word lengths (per-instance **167 bits**, the only new field being the Q10.21 `route_out_latch`), frozen destination classes cutoff+resonance, frozen waveform set inherited from SXT-032, everything else fail-closed at extraction. Extractor **re-run against the live oracle for this record**: both committed sidecars reproduce **content-identical**. |
| 2 | Model-vs-pinned-engine dry-render budgets on the carrier fixtures | **FAIL against `[PROPOSED]` budgets on all 6 fixtures / PENDING-FREEZE** — and **DEVIATION: not run on the named carriers** (see below) | Achieved numbers recorded, not tuned (table below). Spectral bound PASSES on 4 of 6; the proposed max-abs (3,500 LSB) and RMS (≤ −46 dBFS) bounds FAIL on all 6. Same error class as SXT-022/SXT-032 (fixed-point quantization amplified by large filter-coefficient excursions). Budgets are `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`; the freeze decision belongs to #12 / SXT-013. |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS** | Integer equality, **zero mismatches on every leg**. Scene-LFO control plane (`tb_slfo.sv`) and the frozen SXT-022 voice datapath (`tb_voice.sv`, unmodified) — table below. Checkpoints cover phase, EG state, EG phase, EG value and routed output of **all six instances at every block boundary** (not only the routed ones — "all six advance every block" is part of the frozen schedule), plus the per-block route sums and the one-block `route_out` latch. |
| 4 | Cycle/state costs vs SXT-016 probes and SXT-015 | **PASS (recorded; divergence recorded, not reconciled)** | `artifacts/costs.txt`, `artifacts/cost-accounting.json`, measured on the exact RTL schedule (`seq-notes-repeated-v1`, 6,150 blocks + 375 settle): **198,900 slfo qmuls**, 6,525 bank advances, 30.48 qmul/advance, **1.0107 MAC per 48 kHz output sample**; 8 scene attacks / 8 scene releases; 3 routes into 2 destination classes applied once per block and shared by every voice. State **167 bits/instance → 1,002 bits/scene** for six instances with shared arithmetic. **Divergence:** SXT-016 has **no scene-LFO probe row** at this pin to reconcile against (the leaf's own cost note anticipated `[ESTIMATE] pending SXT-016 refinement`); these are the first concrete per-kernel numbers and are offered as SXT-016 refinement input. No technology claim. |
| 5 | Negative controls demonstrably FAIL (routing-zeroed per destination class AND source-swap) | **PASS — both required controls FAIL, plus 5 more** | `artifacts/negative-control.txt`, `artifacts/negative-controls.json`. Both issue-mandated controls fail the reference-budget check; see the control table. One control (`zero-delay-route`) is **audio-non-discriminating on this carrier** and is reported as such, carried in the control-plane/exactness domain instead — disclosed, not hidden. |

### Row 2 — achieved model-vs-reference numbers (recorded, not tuned)

Budgets: max-abs ≤ 3,500 LSB · RMS ≤ −46 dBFS · spectral corr ≥ 0.98
(`fs-log-floor-v2`, issue #110).

| fixture | frames | max\|Δ\| LSB | RMS Δ dBFS | spectral corr | verdict |
|---|---|---|---|---|---|
| seq-notes-repeated-v1 | 196,800 | 6,668 | −33.129 | 0.9987 ✓ | FAIL (max, rms) |
| seq-notes-coverage-v1 | 273,600 | 18,409 | −30.354 | 0.9974 ✓ | FAIL (max, rms) |
| seq-notes-holds-v1 | 297,600 | 12,822 | −30.824 | 0.9818 ✓ | FAIL (max, rms) |
| seq-modwheel-v1 | 182,400 | 14,077 | −31.179 | 0.9776 | FAIL (max, rms, spectral) |
| sxt041-slfo-overlap-v1 | 163,200 | 13,151 | −28.359 | 0.9820 ✓ | FAIL (max, rms) |
| fast-corner (rate/shape corner) | 163,200 | 41,539 | −17.890 | 0.7516 | FAIL (max, rms, spectral) |

The `fast-corner` row is the declared rate corner and is the **worst** case by
a wide margin: at SLFO1 rate 4.0 / SLFO2 rate 5.0 the cutoff excursion per
block is large, so the fixed-point/float32 divergence integrates fastest
there. Recorded as the corner it is, not excluded.

### Row 3 — RTL-vs-model exactness (integer equality, 0 mismatches everywhere)

| fixture | SLFO ckpt | SLFO fields | route sums | route latches | voice ckpt | voice fields | oscout | mono |
|---|---|---|---|---|---|---|---|---|
| seq-notes-repeated-v1 | 36,900 | 184,500 | 6,150 | 6,150 | 403 | 11,687 | 25,792 | 196,800 |
| seq-notes-coverage-v1 | 51,300 | 256,500 | 8,550 | 8,550 | 467 | 13,543 | 29,888 | 273,600 |
| seq-notes-holds-v1 | 55,800 | 279,000 | 9,300 | 9,300 | 255 | 7,395 | 16,320 | 297,600 |
| seq-modwheel-v1 | 34,200 | 171,000 | 5,700 | 5,700 | 75 | 2,175 | 4,800 | 182,400 |
| sxt041-slfo-overlap-v1 | 30,600 | 153,000 | 5,100 | 5,100 | 279 | 8,091 | 17,856 | 163,200 |
| fast-corner | 30,600 | 153,000 | 5,100 | 5,100 | — | — | — | — |

**Harness-failure discrimination (#188/#193).** `tb_slfo.sv` `$readmemh`s five
stimulus files; both load-failure shapes were **measured on Icarus 13.0 for
this leaf** (`artifacts/harness-failure-path.json`). An *absent* stimulus is
named by the pre-flight check and reports `comparison: NOT_RUN` before the
simulator runs. A *present-but-empty* stimulus opens fine, so neither
mechanism 1 nor 2 can fire; `tb_slfo.sv` therefore `$fatal`s on an all-`x`
control word, surfacing as a non-zero `vvp` exit and again `NOT_RUN`.
Measured **before** that guard was added, this leaf reproduced the #188/#193
blind spot exactly — 74 reported "mismatches" from a control memory that
never loaded. The healthy-run stdout of this testbench is empty, which is the
per-harness confirmation #193 requires before mechanism 2 may be relied on.

### Row 5 — negative controls (all counted controls demonstrably FAIL)

Baselines are the frozen model's **own** numbers, which already fail the
proposed max/rms budgets — so no control is ever graded against a "pass" the
model does not have.

| control | targets | audio vs baseline | control-plane | verdict |
|---|---|---|---|---|
| **routing-zeroed, cutoff** (required) | depth→0 per destination class | max 32,452 (base 13,151), rms −20.217 (−28.359), spec 0.7538 (0.9820) | route-sum blocks differing 5,099/5,100 | **FAIL** (degrades max, rms, spectral) |
| **routing-zeroed, reso** (required) | depth→0 per destination class | max 16,982, rms −26.319, spec 0.9687 | 5,099/5,100 | **FAIL** (all three) |
| **routing-zeroed, all routes** | depth→0 | max 33,570, rms −19.324, spec 0.7501 | 5,099/5,100 | **FAIL** (all three) |
| **source-swap** (required) | landed modwheel in place of the SLFO | max 23,426 (base 14,077), rms −22.135 (−31.179), spec 0.6587 (0.9776) | 5,549/5,700 | **FAIL** (all three) |
| **per-note-retrigger** | S2/S3 — voice-LFO attack/release applied to a scene LFO | max 27,560, rms −24.412, spec 0.7721 | route-sums 4,798/5,100; instance outputs 4,799 | **FAIL** (all three) |
| **gated-process** | S5 — advance only while a gated voice exists | max 13,150, rms −28.365, spec 0.9754 | route-sums 3,599/5,100; instance outputs 3,600 | **FAIL** (spectral) |
| **shared-instance** | S1 — one shared state set for all six | max 13,154, rms −27.892, spec 0.9821 | route-sums 5,095/5,100; instance outputs 5,096 | **FAIL** (max, rms) + fails the frozen control-plane trace |
| **zero-delay-route** | S4 — the one-block latch dropped | max 13,141, rms −28.393, spec 0.9823 — **audio-NON-DISCRIMINATING** | route-sum blocks differing **5,100/5,100** | **FAIL in the control-plane/exactness domain** (see note) |
| RTL mutant `slfo_broken_mutant.sv` | output round-half-up bias off by one shift | — | — | **FAIL** integer equality, 51 mismatches, first `block 901 slfo 1 output: model=2097065 rtl=2097064` |
| RTL mutant `slfo_nodelay_mutant.sv` | S4 latch dropped in RTL | — | — | **FAIL**, 42 mismatches, first `block 0 route_sum[0]: model=0 rtl=571025` |
| RTL mutant `slfo_shared_mutant.sv` | S1 state merged in RTL | — | — | **FAIL**, 43 mismatches, first `block 0 slfo 1 phase: model=178957 rtl=357914` |

**Honest note on `zero-delay-route`.** One engine block is 0.67 ms, and on
this carrier dropping the S4 latch moves the audio metrics by ~0.1% —
*within* the model's own error, so the audio leg does **not** discriminate it
and is reported as non-discriminating rather than counted as a pass. The
control is still live and still demonstrably fails, in the domain where the
behavior is actually observable: it differs from the frozen control-plane
trace on **5,100/5,100** route-sum blocks, and its RTL counterpart
(`slfo_nodelay_mutant.sv`) fails integer equality at block 0. This is the
S4-specific reason the leaf checkpoints the latch as its own field.

**Settle-replay probe (P8, not a control).** The renderer's 375 settle blocks
advance the scene LFOs (S5), so the runner replays them before t=0. On a
keytrigger fixture that replay must be a provable no-op: `--no-settle`
renders **bit-identically**. Recorded as a probe, not counted as a control.

## DEVIATION: the named carriers were not used (visible, not absorbed)

The acceptance item reads "budgets reported **on the carrier fixtures**". It
was **not** satisfied as literally written, and this record does not claim it
was. `artifacts/applicability-scan.json` (over the committed normalized
export, no oracle, not a support claim) finds:

* **0 of 3 named carriers are renderable end-to-end** by the landed voice
  arithmetic. Each is blocked independently of SLFO support — `Bad News`:
  3 active FX slots (types 1/6), filter block config `fbc=4` (not serial1),
  waveshaper type 4, scene lowcut −28.19 (not off), all three mixer paths
  active, osc type 2 (not Classic), filter unit types [1, 8]. `Rainy Day
  Dreamaway` and `Pluck 2 Pad Demon Sad` are blocked the same way.
* **All three route SLFO only to destinations OUTSIDE this leaf's frozen
  destination classes**, with an empty `destinations_inside_frozen_classes`
  for each: `Bad News` → `A Osc 1 Morph`; `Rainy Day Dreamaway` →
  `A Filter 1 FEG Mod Amount`, `A Filter EG Sustain`, `A Osc 1 Morph`,
  `A Osc 3 Sync`; `Pluck 2 Pad Demon Sad` → `A Highpass`,
  `A Osc 3 M1 Amount`, `A Osc 3 M2 Amount`, `FX S1 Mix`.
  So even with an unlimited voice
  datapath, the named carriers would not exercise the cutoff/resonance route
  classes this leaf freezes.

Consequently the model-vs-reference legs run on the **declared synthetic
fixture** described above. This is the same disposition the merged sibling
leaf SXT-032 took for the same structural reason (`reports/sxt-032/EVIDENCE.md`,
"Applicability boundary and coverage delta (honest)"), and it is disclosed
here rather than being quietly folded into a checked box.

**Bounded finding, routed per the issue's Stop/escalate section:** the
carrier-fixture clause of acceptance item 2 is **NOT_RUN** and cannot be run
until the voice slice covers the named carriers' topology (FX slots,
non-serial1 filter config, waveshaper, multi-osc mixer, non-Classic
oscillators) *and* the frozen destination classes are widened past
cutoff/resonance. Neither is in this leaf's scope (both are explicit
non-goals). Routed to **SXT-013 / #12** with the achieved numbers above; no
budget, destination class, or acceptance rule was weakened to produce a pass.

## Applicability boundary and coverage delta (honest)

**Supported-preset delta from this leaf: 0 presets.** Nothing here is a
support claim. Corpus context from the same scan (inventory only): 985 /
3,561 normalized presets route scene LFOs, 2,249 scene-list + 800 global-list
SLFO routes, most common SLFO destinations `A Pitch` (188) and `A Filter 1
Cutoff` (111); only **134** presets have at least one SLFO route inside this
leaf's frozen destination classes. The issue body's "36 newly-enabled
presets" is a requirement-attribution slate number, not a result of this
leaf, and is **not** claimed here.

Carried unresolved: the SXT-017 `slfo_definitions` budget-risk caveat and the
send-levels 3/4 exposure gap. Scene B / two-scene scheduling is not
exercised (the fixture is single-scene).

## Licensing / provenance

No Surge source, tables, or payloads were copied into this repository; the
pinned engine is cited by file and line only (read via the pinned commit).
The reference `.fxp` carrier is read from the external pinned oracle tree and
never modified. Original work Apache-2.0 (`LICENSE`); governed by #25 and
`docs/REUSE-AUDIT.md`. No file under `docs/byte-frozen-sources.json`'s
`live_pins` is touched by this change (verified: none of the live-pin
`covers`/`recorded_in` paths lie under `model/voice/` or name `lfo`), so no
committed PASS record is turned STALE. `lfo_model.py` is **reused by import,
not edited or copied**.

## Reproduce

Commands: `model/voice/README.md` § "Reproduce (SXT-041)". Every number in
this record was produced by re-running that sequence end-to-end on a Loom
dispatch worker (`loom-worker-2`) on 2026-10-02 with the `--prebuilt` oracle;
the oracle reference renders reproduce **bit-identically** (sha256-verified)
across independent runs, and `tests/test_sxt041_slfo.py` is **22 passed**
without oracle or simulator.
