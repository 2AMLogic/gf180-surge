# 0018 — The SXT-026 wavetable decimator and master stage move from the voice slice to a per-SCENE stage, and RTL coverage extends to the 48 kHz output (#180 → SXT-017 #12)

- **Status:** RECORDED CONTRACT REVISION — in force at the enforcement points
  named below. **Owner ratification pending** for the freeze consequence,
  which is routed to SXT-017
  ([#12](https://github.com/2AMLogic/gf180-surge/issues/12)). Supersedes
  nothing; amends the disposition recorded in
  `reports/sxt-026/EVIDENCE.md` §2a (issue #176, option (b)).
- **Date:** 2026-09-28
- **Issue:** [#180](https://github.com/2AMLogic/gf180-surge/issues/180)
- **Raised by:** SXT-026 ([#19](https://github.com/2AMLogic/gf180-surge/issues/19))
  via [#176](https://github.com/2AMLogic/gf180-surge/issues/176) (option (a),
  deliberately deferred there)
- **Routes to:** SXT-017 ([#12](https://github.com/2AMLogic/gf180-surge/issues/12))
- **Evidence:** `reports/sxt-026/EVIDENCE.md` §2, §2a, §3;
  `reports/sxt-026/artifacts/decimation-stage-per-slice-vs-per-scene.json`;
  `reports/sxt-026/artifacts/rtl-exactness.txt`;
  `model/oscillators/wavetable/README.md` declared deviations 7–8.

## Why this record exists at all

`model/oscillators/wavetable/wt_model.py` is **FROZEN for the SXT-026 RTL**:
RTL-vs-model agreement is integer equality, so any change to the model's
numerical behaviour re-freezes the pair and moves every committed render
derived from it. This repository treats such a change as a *visible contract
revision*, not an implementation detail (`AGENTS.md`; plan §6; the discipline
already applied by [0011](0011-profile-v1-budget-escalation.md),
[0013](0013-fx-modulation-rng-stream.md),
[0016](0016-int16-tail-shape-leg-floor.md) and
[0017](0017-int16-wet-tail-shape-grading-fixture.md)). This record is
therefore written **before** the model is changed, and #180's implementing PR
lands it as its first commit; the git history is the ordering evidence.

## Context

The frozen SXT-026 model placed the 96 kHz → 48 kHz decimator
(`voice_model.HalfbandD2`) and the master-gain stage **inside** the per-voice
slice (`wt_model.Slice`), and
`model/oscillators/wavetable/run_model.py` summed the already-decimated
slices. The pinned engine runs them **once per scene** on the summed
`sceneout` (`SurgeSynthesizer::halfbandA/B` →
`HalfRateFilter::process_block_D2`), which is what this repository already
models in `model/voice/run_model.py` and implements in `rtl/voice/tb_voice.sv`.

Two coupled consequences followed from the per-slice placement, both declared
by #176 rather than absorbed:

- **Declared deviation 7** — the placement itself. The filter is linear, so
  the two topologies differ only by fixed-point rounding, by where the ±8
  `sceneout` clip falls, by where the master gain and its clips fall, and by
  **state lifetime**: a per-slice filter's state and its ring-out die with the
  voice, where the engine's scene filter keeps ringing.
- **Declared deviation 8** — the RTL coverage boundary.
  `rtl/oscillators/wavetable/` implemented the oscillator only, so the leaf's
  `rtl_vs_model: PASS` was *oscillator-scoped* and the model's 48 kHz
  `mono_block` had no RTL counterpart to be compared against at all.

## What was measured before deciding

`tools/measure_wt_decimation_stage.py`
(`reports/sxt-026/artifacts/decimation-stage-per-slice-vs-per-scene.json`),
model-vs-model, both legs driven from ONE shared upstream pass, all nine
committed SXT-026 fixtures:

| worst over nine fixtures | value |
|---|---|
| max abs Δ, int16 LSB | **1** |
| residual RMS | **−112.1 dBFS** |
| max abs Δ, Q10.21 LSB (pre-int16) | **38** (one int16 LSB = 64) |

The smallest [PROPOSED] `max_abs_diff_lsb` bound anywhere in the leaf's budget
matrix is 3,500, so the placement sits ~3,500× below it.

**The case for this revision is therefore NOT fidelity.** It is (1) RTL
coverage of the 48 kHz output, which deviation 8 says does not exist today,
and (2) topological agreement with the pinned engine and with the SXT-022
voice leaf, so the two leaves' scene paths are one schedule rather than two.
Nobody may present this revision as a fidelity improvement, and no fidelity
verdict is claimed by it.

## Decision

1. **The decimator and the master stage move out of `wt_model.Slice` to one
   per-SCENE stage** (`wt_model.SceneDecimator`), in the pinned engine's
   order: sum the **unclipped** 96 kHz per-slice `sceneout` contributions →
   ONE ±8 clip → ONE `HalfbandD2` for the scene, **persisting across voice
   death** → master gain → ±8 clip → ±1 clip → one int16 conversion. This is
   the identical statement order `model/voice/run_model.py` already uses
   (mono bus: the engine's `(L+R)/2` with `L == R` reduces to `L` exactly).
2. **No word length, Q format, rounding rule or coefficient changes.** The
   arithmetic primitives are the shared `voice_model` ones, unchanged: Q10.21
   samples/coefficients, round-half-up products, `HalfbandD2` with the
   `decision-records/0002` coefficients, `qround(x, 1)` reconstruction. What
   changes is *where* the stage runs and *how many* instances exist, not any
   number in it.
3. **RTL coverage extends to the 48 kHz output.** The per-scene stage is
   implemented in `rtl/oscillators/wavetable/tb_wavetable.sv` (the scene is a
   testbench-level resource shared by the four slot cores, exactly as in
   `rtl/voice/tb_voice.sv`), emits an `M` trace line per block, and
   `tools/compare_wt_rtl_model.py` compares it against the model trace's
   48 kHz `mono_block` at **integer equality**. Declared deviations 7 and 8
   are revised to state what landed.
4. **The comparison must be proven to cover the new stage.** A single-line
   mutant of the scene decimator's reconstruction branch order
   (`-DWT_SCENE_MUTANT_HB_ORDER`, the pre-#123 A-even/B-odd ordering that
   `rtl/voice/voice_halfband_order_mutant.sv` isolates on the voice leaf) MUST
   **FAIL** the 48 kHz comparison while the clean RTL PASSes. A 48 kHz
   comparison that passes against a mutated decimator covers nothing and is
   refused.
5. **Every moved number is published, never silently replaced.** All nine
   committed fixtures are re-rendered through the new topology and
   `reports/sxt-026/EVIDENCE.md` §3 carries an explicit before → after for
   each of them.
6. **No budget verdict may be absorbed here.** #180's stop/escalate condition
   is in force: if the re-freeze moved a committed budget verdict, that
   movement is routed to #12 and is not accepted inside the implementing PR.
   The predicted movement is **none** (item "What was measured" above); the
   Confirmation section below records what actually happened.
7. **No product goal, budget bound or acceptance rule is weakened.** The
   [PROPOSED] bounds stay exactly as pre-registered, the section-4 deep-mip
   finding stays open and unabsorbed, and `model_vs_reference` stays
   `PARTIAL`.

## What re-freezes

| Re-frozen surface | Consequence |
|---|---|
| `model/oscillators/wavetable/wt_model.py` | `Slice` loses `halfband`/`master`/`decimate_scene()`/`process_block()`; `scene_block()` becomes the slice's block entry and returns the unclipped 96 kHz scene contribution. New `SceneDecimator` holds the single per-scene filter and the master stage. Word lengths: **unchanged**. |
| `model/oscillators/wavetable/run_model.py` | Sums the 96 kHz contributions and drives one `SceneDecimator`; `mono_block` in `model_trace.json` becomes the final ±1-clipped Q10.21 mono (previously the ±8-clipped pre-conversion sum), matching the voice leaf's trace convention. |
| RTL stimulus (`init.hex`, `ctrl.hex`) | `init.hex` gains words 40–54: `lvl` (o2 level), `outl` (scene out), `master`, halfband `B0..B5`, halfband `A0..A5`. The per-slot `ctrl.hex` record grows 7 → **9** words with the VCA×AEG gain-ramp endpoints (`gain_start`, `gain_d`) — the same control-plane class as the already-streamed `hpf_start`/`hpf_d`. Any consumer of the old layout must be regenerated, never re-interpreted. |
| `rtl/oscillators/wavetable/tb_wavetable.sv` | Gains the scene stage (per-slot o2 level → VCA×AEG gain ramp → scene out → sum → ±8 clip → `HalfbandD2` → master → clips) and the `M` trace line. `wavetable_core.sv` is **unchanged**: the oscillator schedule does not move. |
| `tools/compare_wt_rtl_model.py` | Reads `mono_block` and compares the 48 kHz output at integer equality; `SCOPE` is rewritten from "does not cover the 48 kHz output" to the landed coverage. |
| Committed renders | `reports/sxt-026/artifacts/model-*.wav` (nine), `traffic-*.json` (re-emitted; the oscillator/traffic path is untouched), `budget-metrics.json`, and `reports/coverage-v1/` (EVIDENCE re-pin). Reference renders (`*-ref.wav`) are **not** touched — no new engine render is made and the oracle is read only for the hash-verified `.wt` payloads. |
| Not re-frozen | `model/voice/voice_model.py` (shared primitives, untouched), the SXT-022 voice leaf, `rtl/voice/*`, every other leaf's model or RTL, the [PROPOSED] budget bounds, and the engine pin. |

## Which committed renders move

Predicted, from the measurement above: **all nine model renders may move by at
most 1 int16 LSB**, and **no row of `reports/sxt-026/EVIDENCE.md` §3 changes
verdict** under either the SXT-026 proposed bounds or the pre-registered
SXT-022 proposal. The narrowest margin in that matrix is the workhorse
spectral-correlation leg (0.9234 against a 0.92 bound, margin 0.0034), so that
leg is the one to watch; a 1-LSB sample-domain change is ~3 orders of
magnitude below what would close it.

## Confirmation

**PENDING at the time this record is committed** — deliberately. This record
is committed BEFORE the model change (see "Why this record exists at all"), so
the confirmation numbers cannot exist yet. They are filled in by a later commit
of the same PR, from the actual re-render, and the authoritative before → after
table lives in `reports/sxt-026/EVIDENCE.md` §3's change note. If any budget
verdict had moved, item 6 above would have fired and this PR would have stopped
rather than filling this section in.

## Options the owner must choose between (item 6 above is what landed)

| Option | What it revises | Quantified consequence |
|---|---|---|
| **R-A** land the per-scene placement and the 48 kHz RTL coverage | the frozen SXT-026 model's numerical behaviour; the RTL stimulus layout | Nine renders re-published, ≤1 int16 LSB each, no verdict moved (Confirmation above). Buys: the 48 kHz output becomes an exactness-covered stage with a live mutant, and this leaf's scene path becomes the same topology as the engine's and the voice leaf's. **This is what landed.** |
| **R-B** keep the declared deviations (the #176 option (b) status quo) | nothing | Costs: the 48 kHz output stays with **no RTL counterpart at all**, so no amount of passing on this leaf can ever be a 48 kHz claim, and the leaf keeps a topology the engine does not have. Buys: no re-freeze. Rejected here because it leaves a stage uncovered, not because it was wrong. |
| **R-C** move the stage but leave the RTL oscillator-only | the model only | Halves the value for the same re-freeze cost: the renders move and the coverage gap stays. Explicitly refused by #180 ("a partial landing must say which half remains"). |
| **R-D** reproduce the engine's float32 scene arithmetic as well | word lengths, and every leaf sharing `voice_model` | Out of scope here and much larger: it is the §4 deep-mip finding's option (a) and would re-freeze every leaf that shares the primitives. Not taken; §4 stays open. |

## Consequences

- `reports/sxt-026/EVIDENCE.md` gains a dated change note and revised §2/§2a,
  and its §3 matrix is republished with before → after per fixture;
  `reports/coverage-v1/` is re-pinned (`evidence_pin_revisions`, issue 180) as
  hash bookkeeping — **no verification status in that ledger moves**
  (`rtl_vs_model` stays PASS, now 48 kHz-inclusive rather than
  oscillator-scoped; `model_vs_reference` stays PARTIAL).
- `tests/test_wt_decimation_stage.py` is inverted where it asserted the *old*
  placement: the structural check that `rtl/oscillators/wavetable/` contains
  no decimator now asserts that it **does**, and the check that the comparator
  never reads `mono_block` now asserts that it **does**. Those tests were
  written to fail exactly here, which is why they are revised in the same PR
  rather than deleted.
- `tools/measure_wt_decimation_stage.py` keeps both legs and swaps which one
  is the frozen model: the per-slice leg becomes a **legacy re-implementation**
  (the same device `tools/halfband_legacy_render.py` uses for #123
  attribution), and the fail-closed byte-identity gate now guards the
  per-scene leg against `run_model.py`.
- `reports/halfband-republication/artifacts/republication-record.json` records
  `head_model_sha256` for the nine SXT-026 renders as of #145. Those nine
  hashes are now historical for three cases; the record is a dated #145
  artifact and is **not** rewritten. `tests/test_halfband_republication.py`
  does not cover this leaf (its budget JSON has a different shape), so nothing
  there goes stale silently.
- Nothing here establishes fidelity, preset support, preset quality, musical
  usefulness, area, timing, power, or any FPGA/gf180mcu result. The 48 kHz
  RTL-vs-model PASS is claim (1) only — *the RTL matches the frozen
  fixed-point model exactly*. It says nothing about claim (2) (model vs the
  pinned engine, still [PROPOSED]/PARTIAL) and nothing about claim (3) (how it
  sounds; no human listening has occurred).

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). The pinned
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71` tree is
**read and cited only** for the stage's placement and order
(`src/common/SurgeSynthesizer.cpp` `halfbandA`/`halfbandB`,
`src/common/dsp/utilities/HalfRateFilter.h` `process_block_D2`); no Surge
source, table or asset is copied here by this record or by the change it
authorizes. The halfband coefficients used are the already-recorded ones from
[0002](0002-halfband-coefficients.md); no new third-party constant is
introduced, so no additional license decision record is required. The `.wt`
payloads stay external and hash-verified (`decision-records/0004`); this
repository has made **no** distribution-license determination (#25).
