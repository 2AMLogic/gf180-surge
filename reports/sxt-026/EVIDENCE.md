# SXT-026 evidence record — Wavetable assets + playback: compiler manifest, frozen fixed model, exact RTL, external-residency traffic

Branch: `loom/sxt-026-wavetable` · Issue: #19 (SXT-026) · Date: 2026-09-21

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, mono (L+R)/2 evidence bus. Wavetable
authority: pinned `src/common/dsp/oscillators/WavetableOscillator.cpp`,
`src/common/dsp/Wavetable.cpp` (structure read and cited, never copied;
the 63 mip halfband constants are quoted as data under
[decision-records/0004](../../decision-records/0004-wavetable-asset-boundary.md)).

**Change note (2026-09-28, issue #180) — SXT-017 visible contract revision,
`decision-records/0018-wavetable-scene-decimation-placement.md`.** The two
scope gaps #176 declared as deviations 7–8 are now **closed by change**, not
by declaration, and this is the first change to this leaf's frozen model
arithmetic since it was frozen:

1. **The decimator and the master stage moved out of `wt_model.Slice` to one
   per-SCENE stage** (`wt_model.SceneDecimator`), persisting across voice
   death — the pinned engine's placement and the one the SXT-022 voice leaf
   already models and implements. No word length, Q format, rounding rule or
   coefficient changed; only *where* the stage runs and *how many* instances
   exist. **Three** of the nine committed renders moved (each by ≤ 1 int16
   LSB); six are byte-identical. **No verdict in section 3 moved** — the
   before → after for every fixture is published in section 3's change note,
   not silently replaced.
2. **RTL coverage now reaches the 48 kHz output.** The per-scene stage is
   implemented in `rtl/oscillators/wavetable/tb_wavetable.sv` (a scene is a
   shared resource, so it sits above the per-slot `wavetable_core.sv`, exactly
   as in `rtl/voice/tb_voice.sv`) and `tools/compare_wt_rtl_model.py` compares
   every 48 kHz `mono_block` sample at integer equality. Base **PASS**, 0
   mismatches, **132,000** 48 kHz samples compared on the full 4125-block
   pitch-extreme fixture; the new single-line scene-decimator mutant
   (`-DWT_SCENE_MUTANT_HB_ORDER`) **FAILS on the 48 kHz leg** (section 6).

The measurement that justified the move is unchanged and stays in section 2a
as the record of what the retired placement was worth — it is not a fidelity
claim, and the move was **not** made for fidelity (see section 2a's closing
paragraph).

**Change note (2026-09-27, issue #176).** Two scope gaps in this record were
closed, both documentation-and-measurement only — no model arithmetic, no RTL
behavior, and no verdict in this record changed. (1) Section 2 now states the
RTL-vs-model **scope boundary** explicitly: this leaf's RTL ends at the
2x-rate oscillator output and has no post-oscillator/48 kHz stage, so
`rtl_vs_model: PASS` was never a 48 kHz-output claim and no longer reads like
one. (2) New section 2a measures the frozen model's **per-slice** decimation
against the engine's **per-scene** placement on all nine committed fixtures.
`wt_model.Slice.process_block` was split into `scene_block()` +
`decimate_scene()` at that stage boundary so the measurement uses the frozen
model's own arithmetic; the split is structural only and all nine fixtures
render byte-identically across it. Issue #145 separately republished this
leaf's section 3 headline budget numbers after the #123 halfband
branch-order fix (see that section's own change note); the per-segment
decomposition and the section 4 discriminating experiments there remain the
pre-#123 numbers, as noted in that section.

**Claim discipline.** This record advances: (1) *RTL matches the frozen
fixed-point model exactly* — **covering the 2x-rate oscillator output, the
declared checkpoints, the traffic accounting, AND the 48 kHz render**
(every `mono_block` sample, per-scene stage included, with a live
scene-decimator mutant as its control; section 2, issue #180 — this replaces
the issue-#176 oscillator-only boundary, which is retired) — (iverilog-
simulated; integer equality, demonstrated), and (2) *the model reproduces the
pinned reference within
[PROPOSED] budgets on the workhorse and morph fixtures* (measured,
PENDING-FREEZE) — with **one bounded budget finding at deep-mip pitch
extremes** (section 4) that is NOT silently absorbed. It establishes
**no** preset-support claim, **no** musical-quality claim (no human
listening has occurred), **no** FPGA/gf180mcu synthesis, timing, area, or
hardware-playback claim, and **no** distribution-license determination
(#25). The RTL is an iverilog-simulated behavioral schedule with declared
traffic accounting, not synthesis-closed RTL.

## 0. Real presets (graphs.jsonl, not synthetic)

| Fixture carrier | wta record (normalized graph, authoritative) | Notes |
|---|---|---|
| `Argitoth/Drums/Kick.fxp` | `Basic/Triangle.wt` (`f49a2381…`), osc 1, scene 0 | All 16 FX slots are **Off in the patch's own state** — its wet sound is FX-free by patch data; nothing was substituted or bypassed. WT slice isolated by declared overrides (`mute_o1`, `mute_noise`, `fu1_off`) — test configuration, never an adapted preset, never a coverage claim. |
| `Argitoth/FX/Monster Feedback.fxp` | `Sampled/Banjo 1.wt` (`d610b7ca…`), osc 1 | Second carrier from a different bank; FX are present in the preset and are muted via the declared SXT-012 dry-bypass mechanism in `mf-*` fixtures only. |

Both appear in `corpus/normalized/graphs.jsonl` with resolved `res`
`[path, sha256]` records; the compiler verifies the external file against
the graph's hash at compile time (ABORT on mismatch).

## 1. Issue-#19 acceptance mapping

| # | Acceptance item (issue #19) | Status | Evidence |
|---|---|---|---|
| 1 | Asset identity verified by hash end-to-end; residency matches the accounting model (#10) | **PASS** | Manifest (`derived.wavetable_asset_manifests`: sha256, size, dims, mip/AA structure, interpolation, residency class) embedded in the patch image at compile; end-to-end `verify` re-hashes the external file (`manifest-image-verify.txt`, assets_checked=1 failures=0). NC-A: flipped payload → compile ABORT (exit 2, no image) AND verify ABORT (`nc-a-hash-abort.txt`). Payloads stay external (DR 0004); repo keeps hashes/manifests only (`test_no_wt_payload_committed_in_repo` guard). Residency: external asset memory + per-core frame cache — reconciled against SXT-016 `probe_osc__wavetable_*` rows in section 5. |
| 2 | Interpolation/morph/AA within declared budgets vs the pinned reference at pitch extremes | **PARTIAL — bounded budget finding recorded** | Workhorse + morph variants PASS the proposed bounds (section 3). Pitch extremes: low/mid (mip 0/2) track the reference; deep mips (5/6, notes 96/120) decorrelate immediately (corr −0.19/−0.01) — mechanism verified against pinned source as the engine's float32 phase pipeline (`WavetableOscillator.cpp:278–291,474`), NOT mip-table content (forced-mip0 control also decorrelates; model deep-vs-mip0 corr 0.995). Status vs proposed bounds: **MISS at deep-mip extremes**; escalation in section 4. |
| 3 | Maximum supported unison validated; beyond-limit rejected explicitly | **PASS** | `kick-wtfix-uni16` (MAX_UNISON=16) renders through the model and the RTL with 16 sub-voices; RTL matches the model exactly over the full fixture (section 2). `unison=17` → `run_model` exits 1 with an explicit "explicitly rejected (no clamp)" message (`nc-c-unison-overflow.txt`); the engine clamps silently (SXT-015 flagged 58 presets) — this product contract rejects, per the frozen-model README. |
| 4 | Sustained playback bandwidth measured with effects active; no underruns | **PASS (declared behavioral model)** | uni16 (worst case) full 2250 blocks with concurrent Reverb1 background bus traffic (SXT-016 pattern, 34 words/frame): `reverb_words=76500`, `underrun_blocks=0`, `max_frame_bus_cost` ≤ 32000 (`sustained-concurrent.txt`). Physical external traffic = frame fills + reverb ≈ 1.05 MB/s at the 48 MHz A-CLK candidate — within the SXT-016 E1 floor (8 MB/s). The logical 2-words/impulse demand is served by the on-chip frame cache, not the external bus. The bus/underrun model is DECLARED (behavioral costs), not cycle-accurate RTL — no timing claim. |
| 5 | Negative control: hash mismatch aborts; substituted table fails the reference-budget check | **PASS** | NC-A (above); NC-B model-side: forced deep-mip (`SXT026_NC_B_FORCE_MIP6`) fails the proposed budget on the workhorse while the correct model passes (`nc-b-mip-mutant.txt`); NC-B RTL: the committed mip-threshold mutant (`-DWAVETABLE_MUTANT_MIP`) FAILS RTL-vs-model exactness on the pitch-extreme fixture while the clean RTL passes (`rtl-exactness.txt`). NC-D RTL (#180): the single-line scene-decimator mutant (`-DWT_SCENE_MUTANT_HB_ORDER`) FAILS the same comparison **on the 48 kHz leg** while the clean RTL passes all 132,000 48 kHz samples (`rtl-exactness.txt`, section 6). All controls are live — each demonstrably fails the check it targets. |

## 2. RTL-vs-frozen-model exactness (integer equality)

**Declared scope (issue #180; the issue-#176 boundary is RETIRED) — read this
before the verdicts below.** This leaf's RTL-vs-model exactness claim now
covers the **2x-rate (96 kHz) oscillator output, the declared per-voice and
shared checkpoints, the external-traffic accounting, and the 48 kHz output**.
`rtl/oscillators/wavetable/tb_wavetable.sv` implements the per-scene stage —
per-slot o2 level and VCA × AEG gain ramp, scene out, ONE ±8 clip, ONE
`HalfbandD2` persisting across voice death, master, ±8 and ±1 clips — and
emits an `M` trace line per 48 kHz sample;
`tools/compare_wt_rtl_model.py` reads the model trace's `mono_block` and
compares every one of those samples at **integer equality**, on every block
including blocks with no live voice (the scene filter's post-voice-death
ring-out is compared too). The stage lives in the testbench rather than in the
per-slot `wavetable_core.sv` because a scene is a shared resource — the same
split `rtl/voice/tb_voice.sv` uses on the SXT-022 voice leaf. The landed scope
is machine-readable in the comparator's emitted `scope` field, in the two RTL
file headers, and in `model/oscillators/wavetable/README.md` (deviations 7–8,
both revised).

**The coverage claim carries its own control.** A 48 kHz comparison that
passes against a mutated decimator would cover nothing, so
`-DWT_SCENE_MUTANT_HB_ORDER` mutates a single line of the scene decimator's
reconstruction — the pre-#123 A-even/B-odd branch order that
`rtl/voice/voice_halfband_order_mutant.sv` isolates on the voice leaf — and
MUST FAIL the comparison **on the 48 kHz leg specifically**; the harness
refuses a mutant run whose only failures are elsewhere. Verdicts in section 6.

What this PASS still is **not**: it is claim (1) only — *the RTL matches the
frozen fixed-point model exactly*. It says nothing about model-vs-pinned-engine
fidelity (claim 2, section 3, [PROPOSED]/PARTIAL) and nothing about how the
leaf sounds (claim 3; no human listening has occurred).

Before #180 this leaf's RTL had no 48 kHz stage at all, `compare_wt_rtl_model.py`
did not read `mono_block`, and `rtl_vs_model: PASS` was oscillator-scoped —
declared deviation 8 of issue #176. That boundary was closed by an SXT-017
visible contract revision
(`decision-records/0018-wavetable-scene-decimation-placement.md`), not by
widening a claim.

`tools/compare_wt_rtl_model.py` compiles `rtl/oscillators/wavetable/`
with iverilog 11, runs `tb_wavetable.sv` from the model runner's stimulus
(init/ctrl/sinc-ROM/derived-table hex) and requires INTEGER EQUALITY of:
per-voice impulse-engine state at every declared checkpoint (oscstate,
state, last_level, mipmap), morph machinery (tableid, tableipol,
last_tableipol, l_shape), the hpf/output stage (osc_out, bufpos, hpf_prev),
every 64-sample oscillator output block, and the external-traffic
accounting (reads+fills must equal the model's declared words exactly;
any underrun block fails).

**RTL boundary and the scene decimator (raised by #145, declared by #176,
CLOSED by #180).** Historical statement, kept so the chain is auditable: this
leaf's RTL once contained **no** halfband/decimator logic under any name and
the comparator never read the model trace's `mono_block`, so the model's
post-oscillator stage (`wt_model.py` `Slice`: o2 level, VCA×AEG gain ramp,
scene out, ±8 clip, `HalfbandD2`, master, clip) had no RTL counterpart at all
and this leaf's "RTL == model" claim was scoped to the oscillator output.
Separately, that model stage was placed **per voice slice** where the pinned
engine places it **per scene** (`SurgeSynthesizer::halfbandA/B`,
`process_block_D2` on the summed `sceneout`).

Both points are now resolved by change rather than declaration. #176 measured
the placement difference (section 2a); #180 moved the stage to one per-scene
`wt_model.SceneDecimator` — the engine's placement, and the one
`model/voice/run_model.py` models and `rtl/voice/tb_voice.sv` implements — and
implemented that same stage in `tb_wavetable.sv`, so the 48 kHz output is now
compared at integer equality with a live single-line mutant as its control
(scope block above; verdicts in section 6). The state-lifetime asymmetry that
paragraph described — a per-slice filter's ring-out dying with the voice where
the engine's scene filter keeps ringing — no longer exists in this model: the
scene filter persists across voice death, and its post-death ring-out is part
of what the RTL comparison covers.

Transcript: `rtl-exactness.txt` (regenerated by
`tools/run_sxt026_checks.py` steps 6–7). Coverage: the full 4125-block
pitch-extreme fixture (notes 24/60/96/120 → mips **0/2/5/6** — the mip
window is what makes the RTL mutant control effective; the committed
sequence previously claimed mip5/6 coverage but its mip-2 window was not
exercised — fixed this branch, sequence re-rendered) and the full
2250-block MAX_UNISON fixture. Verdicts: base **PASS** with 0 mismatches
(kt: 2325 checkpoint records + 25575 state fields + 148800 oscillator
output samples + **132000 48 kHz `mono_block` samples** + exact
external-traffic reconciliation; uni16: 18736 checkpoint records + 74944
oscillator output samples + **72000 48 kHz `mono_block` samples** under
concurrent Reverb1 background traffic); the mip-threshold mutant **FAILS**
the same comparison (first divergence at the mip-2 window's first
checkpoint, block 768), and the scene-decimator mutant **FAILS** it on the
48 kHz leg from block 0 (section 6).

The 48 kHz leg is compared on **every** block, not only checkpoint blocks and
not only blocks with a live voice: the scene filter persists across voice
death, so its post-death ring-out is compared too. `run_sxt026_checks.py`
asserts the clean run's 48 kHz sample count equals `blocks × 32`, so an
absent or truncated 48 kHz trace fails instead of silently reducing coverage.

Determinism: identical reruns produce identical traces (pure integer
model + fixed stimulus; no time dependence).

## 2a. Per-slice vs per-scene decimation: measured (issue #176)

> **Status (issue #180): this measurement is the record of a placement that
> has since been RETIRED.** It is kept verbatim because it is the evidence on
> which the SXT-017 contract revision was decided — read the tense below as
> describing the *pre-#180* frozen model. The per-scene leg (leg B) measured
> here **is** the frozen model today; the per-slice leg (leg A) survives only
> as `measure_wt_decimation_stage.LegacyPerSliceStage`, a legacy
> re-implementation kept so this delta stays re-derivable, and the tool's
> fail-closed byte-identity gate now guards the per-scene leg against
> `run_model.py`. What actually moved when the revision landed is in section
> 3's #180 change note.

**Declared deviation, measured, not absorbed.** The frozen model instantiates
one `voice_model.HalfbandD2` **per voice slice** (`wt_model.Slice`) and
`run_model.py` sums the already-decimated slices. The pinned engine decimates
**once per scene** on the summed `sceneout`
(`SurgeSynthesizer::halfbandA/B` → `HalfRateFilter::process_block_D2`), which
is what `model/voice/run_model.py` models and `rtl/voice/tb_voice.sv`
implements. The filter is linear, so the two topologies differ only by
fixed-point rounding, by where the ±8 `sceneout` clip falls (per slice vs once
on the sum), by where the master gain and its clips fall, and by **state
lifetime** — a slice's filter state and its ring-out die with the voice, while
the engine's scene filter keeps ringing. Recorded as declared deviation 7 in
`model/oscillators/wavetable/README.md`.

Measurement: `tools/measure_wt_decimation_stage.py`, artifact
`artifacts/decimation-stage-per-slice-vs-per-scene.json`. **Model-vs-model
only** — both legs are this frozen model; no reference render is read, no
pinned engine is executed, and no budget is graded. Both legs are driven from
one shared upstream pass (`Slice.scene_block()`), so voice creation and death
fall on identical blocks and every difference is attributable to the
decimation stage alone. Leg A is verified **byte-identical to
`run_model.py`'s own render** of each case (fail-closed gate inside the tool),
so the numbers cannot come from a drifted re-implementation of the frozen leg.

| Fixture case | max abs Δ (int16 LSB) | RMS Δ dBFS | max abs Δ (Q10.21 LSB) | int16 frames differing | max live voices | blocks with a voice death |
|---|---|---|---|---|---|---|
| kick-wtfix / base | 0 | exact (0) | 1 | 0 | 1 | 1 |
| kick-wtfix-morph25 / base | 0 | exact (0) | 1 | 0 | 1 | 1 |
| kick-wtfix-morph75 / base | 0 | exact (0) | 1 | 0 | 1 | 1 |
| kick-wtfix / pitch-extremes | **1** | −121.40 | 2 | 84 | 2 | 3 |
| kick-wtfix-kt / pitch-extremes-hi | **1** | −119.93 | 2 | 144 | 2 | 4 |
| kick-wtfix-uni16 / unison16 | **1** | −112.13 | 7 | 473 | 2 | 1 |
| mf-wtfix / base | 0 | exact (0) | **38** | 0 | 1 | 1 |
| mf-wtfix-morph25 / base | 0 | exact (0) | 15 | 0 | 1 | 1 |
| mf-wtfix-morph75 / base | 0 | exact (0) | 2 | 0 | 1 | 1 |

One int16 LSB is 64 Q10.21 LSB, so the Q10.21 column is the finer reading;
"exact (0)" is a zero int16 residual (the JSON reports the comparators' finite
`rms_diff_dbfs` floor, −300.0, for it). **Worst case over all nine fixtures:
1 int16 LSB, −112.1 dBFS residual RMS, 38 Q10.21 LSB.** For scale, the
smallest [PROPOSED] `max_abs_diff_lsb` bound anywhere in section 3 is 3500 —
this placement difference is ~3500× below it, and it moves no row of the
section-3 matrix.

**Failure control (required by #176): PASS.** The control requires the
per-scene leg to differ from the per-slice leg on at least one case with
overlapping or released voices; bit-identical everywhere would mean voice
death was never exercised. All nine cases have a released voice that dies
mid-render, three (`pitch-extremes`, `pitch-extremes-hi`, `unison16`) also
carry overlapping voices, and **no** case is bit-identical (the tool exits 1
if any qualifying case is). The control is live, not a formality: it is
evaluated in the tool and recorded in the artifact's `failure_control` block.

**F-176-1 — where the two legs separate.** The rounding leg scales with
concurrency, exactly as a sum-of-roundings vs rounding-of-a-sum should: the
single-voice cases agree bit-for-bit at int16 (residual ≤ 1–2 Q10.21 LSB),
while the two-voice cases reach 1 int16 LSB on 84–473 frames. The
state-lifetime leg is visible only in the Q10.21 domain: after the last voice
dies, leg A is exactly zero by construction while leg B is still ringing, at a
peak of 1 Q10.21 LSB on the kick cases and 38/15/2 on the `mf-*` cases —
below one int16 LSB in every case, which is why the mf column's 38 never
reaches the int16 render.

**F-176-2 (bounded, routed out of this leaf).** That leg-B tail does not decay
to zero: the shared fixed-point `voice_model.HalfbandD2` has a **zero-input
limit cycle**. Driven with an impulse and then silence it settles to a
non-decaying ±26 Q10.21 LSB alternating-sign (Nyquist-rate) output; on
`mf-wtfix` the scene filter's post-death output peaks at 38 Q10.21 LSB, decays
to ±24 within ~100 frames, and then holds ±24 for the rest of the render
(71,776 frames after the death block). That is ≈ −98 dBFS and below one
int16 LSB, so it
never reaches an int16 render on its own — but it is a property of the
**shared** decimator class, so it applies equally to the SXT-022 voice leaf's
per-scene decimator and to every RTL copy of it (which reproduce it exactly,
since RTL == model). It is **not** caused by the per-slice/per-scene question
and is not fixed here; it is filed as issue #181 rather than absorbed.

**Disposition (SXT-017 visible-contract rule): option (b) in #176, then option
(a) in #180.** #176 declared the per-slice decimation and the oscillator-only
RTL boundary as explicit, bounded deviations (README deviations 7–8, section 2
above, and the `osc:Wavetable` ledger note) with the difference measured, and
routed option (a) — moving the stage to a per-scene placement shared with the
voice leaf and extending RTL coverage to the 48 kHz output — to issue #180 as
a change to the frozen model's numerical behavior, i.e. an SXT-017 contract
revision (#12). The measurement is what made that routing a decision rather
than a deferral: the placement is worth at most 1 int16 LSB on these fixtures,
so nothing in the section-3 budget matrix depended on it, and the remaining
reason to move it was RTL coverage of the 48 kHz output, not fidelity.

**#180 then took option (a)**, under
`decision-records/0018-wavetable-scene-decimation-placement.md`, and the
prediction held: three of the nine renders moved by ≤ 1 int16 LSB, six are
byte-identical, and no section-3 verdict moved (section 3's change note).
**Nobody may present that revision as a fidelity improvement** — the case for
it was RTL coverage and topological agreement with the engine. The numbers
above are the size of a *placement difference*, not of an error that was
fixed.

Reproduce:

```bash
ORACLE_SURGE_DATA=<pinned>/resources/data \
python3 tools/measure_wt_decimation_stage.py \
    --out reports/sxt-026/artifacts/decimation-stage-per-slice-vs-per-scene.json
```

## 3. Model-vs-reference budgets (PENDING-FREEZE, measured)

Comparator: `tools/compare_audio_reference.py` (dry policy; no
normalization, no time-warping, shift-0 primary). Full matrix in
`budget-metrics.json`. Proposed SXT-026 bounds on the workhorse
(max_abs ≤ 8000 LSB, rms ≤ −30 dBFS, spectral corr ≥ 0.92) and the
pre-registered SXT-022 proposal (3500 / −46 / 0.98) are BOTH evaluated;
neither is frozen.

| Fixture | max_abs LSB | rms dBFS | corr | sxt-026 bounds | sxt-022 proposal |
|---|---|---|---|---|---|
| kick-wtfix / base (workhorse) | 5841 | −36.0 | 0.923 | **PASS** | max_abs + rms MISS |
| kick-wtfix-morph25 / base | 5841 | −36.0 | 0.923 | **PASS** | max_abs + rms MISS |
| kick-wtfix-morph75 / base | 5841 | −36.0 | 0.923 | **PASS** | max_abs + rms MISS |
| kick-wtfix-uni16 / unison16 | 63576 | −11.6 | 0.958 | MISS | MISS |
| kick-wtfix-kt / pitch-extremes-hi | 48233 | −19.9 | 0.938 | MISS | MISS |
| kick-wtfix / pitch-extremes | 18459 | −24.7 | 0.909 | MISS | MISS |
| mf-wtfix / base | 50735 | −12.7 | 0.976 | MISS | MISS |
| mf-wtfix-morph25 / base | 40312 | −12.7 | 0.969 | MISS | MISS |
| mf-wtfix-morph75 / base | 11686 | −19.6 | 0.971 | MISS | MISS |

**Change note (issue #180, 2026-09-28): re-frozen after the decimator/master
stage moved from the voice slice to ONE per-SCENE stage** (SXT-017 visible
contract revision,
`decision-records/0018-wavetable-scene-decimation-placement.md`).
Every number above was re-derived; nothing was carried over.
**No row's verdict moved** under either bound set, and **no `max_abs LSB`
value moved at all**. Before → after, all nine, published rather than replaced
(`spectral_corr` and `rms_diff_dbfs` at full committed precision; sha256 is
the committed `artifacts/model-*.wav`):

| Fixture | render | corr before → after | rms dBFS before → after | sha256 |
|---|---|---|---|---|
| kick-wtfix / base (workhorse) | identical | 0.9234419021399706 → 0.9234419021399648 | −35.987 → −35.987 | `f5058ec9…` (unmoved) |
| kick-wtfix-morph25 / base | identical | 0.9225587741994460 → 0.9225587741994487 | −35.987 → −35.987 | `bc00b8bc…` (unmoved) |
| kick-wtfix-morph75 / base | identical | 0.9234419021399706 → 0.9234419021399648 | −35.987 → −35.987 | `f5058ec9…` (unmoved) |
| kick-wtfix-uni16 / unison16 | **moved** | 0.9576252433266804 → 0.9575967223340163 | −11.5513250 → −11.5513204 | `16a16cb8…` → `1649f0b1…` |
| kick-wtfix-kt / pitch-extremes-hi | **moved** | 0.9381369880261247 → 0.9381037550402566 | −19.8508601 → −19.8508603 | `614eb0e9…` → `350c8662…` |
| kick-wtfix / pitch-extremes | **moved** | 0.9091471178669477 → 0.9092110108499554 | −24.7420034 → −24.7420045 | `c2ead4c3…` → `7f04474b…` |
| mf-wtfix / base | identical | 0.9755512597793251 → 0.9755512597793249 | −12.659 → −12.659 | `7ec3ffd9…` (unmoved) |
| mf-wtfix-morph25 / base | identical | 0.9687487861068226 → 0.9687487861068206 | −12.724 → −12.724 | `e2265856…` (unmoved) |
| mf-wtfix-morph75 / base | identical | 0.9704886498945159 → 0.9704886498945166 | −19.599 → −19.599 | `c9ac29c6…` (unmoved) |

Reading the two kinds of movement, which are **not** the same thing:

- **Three renders moved**, each by **exactly 1 int16 LSB** peak, on 473
  (uni16), 144 (kt pitch-extremes-hi) and 84 (pitch-extremes) frames out of
  72,000 / 132,000 / 108,000. These are precisely the three fixtures section
  2a's measurement identified as carrying overlapping voices, and precisely
  the per-case frame counts it predicted — the re-freeze reproduced the
  prediction rather than discovering something new. The other six renders are
  **byte-identical**.
- **The six unmoved rows' `spectral_corr` still differs in the last 1–2
  significant digits.** That is *not* a topology effect: the render bytes and
  the reference bytes are identical on both sides, so it is last-ulp
  recomputation noise from re-running `compare_audio_reference.py` on a
  different host/NumPy than the #145 run that committed the previous values.
  It is recorded rather than hidden, and it is the reason the moved rows are
  quoted at full precision above instead of at the table's 3–4 digits.

**No verdict moved.** The workhorse/morph rows still PASS the SXT-026 proposed
bounds; the narrowest margin in the matrix — the workhorse spectral leg at
0.92344 against the 0.92 bound, margin 0.00344 — is unchanged to five decimal
places, so the row the SXT-017 record flagged as "the one to watch" did not
move. Every other row's MISS is unchanged. Per the #180 stop/escalate rule,
had any verdict moved it would have been routed to #12 rather than absorbed
here. **STALE (not re-measured by #180):** the per-segment decomposition below
and the section 4 discriminating experiments, which remain pre-#123 numbers
for the reasons the #145 note gives; #180 moved no fixture by more than 1
int16 LSB, so it does not change their standing either way. RTL-vs-model was
re-run and **extended**: base PASS with 0 mismatches now including 132,000
48 kHz `mono_block` samples, the mip-threshold mutant still FAILs, and the new
scene-decimator mutant FAILs on the 48 kHz leg (sections 2 and 6).

**Change note (issue #145, 2026-09-27): republished after the #123 halfband
branch-order fix — this leaf was NOT_RUN in #123 and is measured here.** The
wavetable slice's model output passes through the shared `HalfbandD2`
(`wt_model.py` `Slice`), so every model render moved. The #145 host has a
checkout of the pinned engine at `58914e59c…` with the external
`resources/data/wavetables` asset root (asset identity re-verified by the
model loader's sha256 gate and by `run_sxt026_checks.py` step 1), so the
renders were re-derived rather than left NOT_RUN. Attribution: the pre-#123
ordering (`tools/halfband_legacy_render.py`) re-renders **all nine**
committed pre-#145 model WAVs byte-identically, so the deltas are #123
alone. Before → after (max LSB / rms dBFS / corr): kick-wtfix base 5,841 /
−35.987 / 0.9268 → 5,841 / −35.987 / 0.9234; morph25 0.9267 → 0.9226;
morph75 0.9268 → 0.9234; uni16 63,579 / 0.9546 → 63,576 / 0.9576; kt-hi
47,262 / −20.31 / 0.9378 → 48,233 / −19.85 / 0.9381; pitch-extremes 18,447
/ 0.9057 → 18,459 / 0.9091; mf base 48,993 / 0.9720 → 50,735 / 0.9756; mf
morph25 39,321 / 0.9655 → 40,312 / 0.9687; mf morph75 11,628 / 0.9712 →
11,686 / 0.9705. **No verdict moved** under either bound set: the workhorse
rows still PASS the SXT-026 bounds (corr ≥ 0.92), but their spectral margin
**narrowed** from 0.0068 to 0.0026–0.0034 — this is the one leaf where the
corrected decimator lowered agreement on the headline rows, recorded as-is.
The sxt-022-proposal column now also shows the rms MISS on the workhorse
rows: the regenerated `budget-metrics.json` carries the corrected RMS-leg
polarity (PR #92 / #95; these 9 rows were audited there as flag-only flips),
not a #123 effect. NC-B was re-run and still FAILs (mutant corr 0.8872 vs
correct 0.9234; `nc-b-mip-mutant.txt`). **STALE (not re-measured):** the
per-segment decomposition just below and the §4 discriminating experiments
are pre-#123 numbers. RTL-vs-model exactness is unaffected by construction
(the wavetable RTL boundary ends at the oscillator output, before the
decimator — see §2 note) and was re-run: base PASS, 0 mismatches; the
mip-threshold mutant FAILs with 68 mismatches (unchanged). Full record:
`reports/halfband-republication/`.

Per-segment decomposition of the pitch-extreme fixture (new kt sequence):
n24 corr 0.930, n60 (mip 2) corr 0.956, n96 (mip 5) corr −0.189, n120
(mip 6) corr −0.006 — the collapse is confined to deep-mip segments and
is immediate within the note (first 2000 samples of n96: corr −0.398).

## 4. Bounded budget finding: deep-mip pitch extremes (escalation)

**Finding.** Model-vs-reference at deep mips (5/6) decorrelates beyond
any credible sample-domain budget. Discriminating experiments (all local,
/tmp, none committed as artifacts):

- Forced-mip0 model at n96 vs the same reference segment: corr −0.142 —
  **mip-table content is ruled out** as the dominant cause.
- Model deep-mips vs model mip0 at n96: corr 0.995 — on this carrier the
  AA tables barely change the audible result, so the divergence is in
  **phase/rate arithmetic at high pitch**, not AA table construction.
- Pinned source verification: the engine accumulates `oscstate` and forms
  `ipos` in **float32** (`WavetableOscillator.cpp:278,289–291,474–475`);
  at high pitch the per-sample impulse count is ~27×, so float32
  mantissa quantization of the phase pipeline dominates. The frozen model
  is exact-integer by contract (declared deviation 3 in
  `model/oscillators/wavetable/README.md`) and cannot track float32
  truncation without a visible contract revision.

**Status: recorded, not absorbed.** The acceptance item "within declared
budgets at pitch extremes" is NOT established at deep mips under the
proposed bounds. Options belong to the budget-freeze owner (SXT-017
visible contract revision, per plan section 6 and the SXT-022
pre-registration discipline): (a) reproduce the engine's float32 phase
pipeline in the frozen model (word-length and RTL consequences must be
re-frozen), or (b) declare a deep-mip comparison methodology (e.g.
envelope/spectral-domain budgets) instead of sample-domain correlation.
Neither is chosen here. The uni16 and mf misses on the wider fixture set
(same section 3 table) are the same class of finding at lower magnitude
and stay recorded against the SXT-022 proposal rather than silently
widening any budget.

## 5. Traffic: measured numbers, logical vs physical, SXT-016 reconciliation

Declared model (normative, `run_model.py` / tb header): external asset
reads = 2 words/impulse (morph frame pair: both `tid` and `target`
frames) + on-demand frame fills of frames actually read (4-byte f32
words, counted once per (mip, table) per slot; the frame cache persists
across voices — a new note on a loaded table does not re-fetch it). The
RTL reconciles EXACTLY (harness gate): `core_reads_words + core_fill_words
== ext_read_words` on every run. **Fixes this branch** (audio verified
unchanged; render equality checked byte-for-byte on every fixture):
(1) the model's fill accounting previously counted only the `tid` frame
of the pair (and keyed on `tableid` rather than the continuous-mode
interpolated `tid`); (2) the ctrl stream carried released voices'
records without their slotmask bit, desyncing the RTL stream at the
first note release; (3) ctrl records were emitted in creation order
while the testbench consumes slot-number order, pairing records to the
wrong slots once a new voice reuses a lower slot; (4) the testbench
never reset a core on voice creation — a reused slot inherited stale
state (now: `c_newvoice` re-latches init and zeroes slice state, and
the model's fill cache is per-slot persistent to match the physically
persistent on-chip frame cache). (5) the core's `frame_touched` cache-tag
array was declared and initialized for 6×16 entries while mip-6 table
tags index up to 7×16 — the out-of-range tags stayed X, so every mip-6
frame fill went uncounted (outputs were unaffected; traffic was short by
exactly the mip-6 pair).

Full-fixture totals (committed `traffic-*.json`):

| Fixture | blocks | impulses | ext words | fills words | reverb words | underruns | max frame bus cost |
|---|---|---|---|---|---|---|---|
| kick-wtfix / base | 3750 | 65589 | 133226 | 2048 | — | — | — |
| kick-wtfix-kt / pitch-extremes-hi | 4125 | 270303 | 543262 | 2656 | — | 0 | 790/32000 |
| kick-wtfix-uni16 / unison16 | 2250 | 859781 | 1723658 | 4096 | 76500 (34/frame) | **0** | 3052/32000 |

Logical-vs-physical: the logical demand (up to ~764 words/block at 16
unison) is served by the per-core frame cache; the EXTERNAL bus sees
only cache-cold frame fills + Reverb1 background (34 words/frame per the
SXT-016 Reverb1 pattern: 16 composite-tap r/w pairs + predelay 1r/1w) ≈
35.8 words/frame = 1.07 MB/s at the 48 MHz A-CLK candidate (2 cycles/
word, 7500 frames/s) — within the SXT-016 E1 floor (8 MB/s @48 MHz).
The frame budget constant (32000 bus-slots/frame) is a DECLARED harness
constant, not an achievable-clock claim — clock closure remains
SXT-016/SXT-017 scope.

Residency vs SXT-016 probe rows (`probe_osc__wavetable_blit…`):
`osc_state_bytes_per_unison` 512 B and `wt_working_set_bytes` 65536 B
(= 8 KiB mip0 for a 1024×2 f32 table — the probe's generic
49152 b/6 KiB estimate is per- mip0-frame; the measured active set here
is the 2-frame morph pair, 8 KiB) — same order, reconciled rather than
asserted; per-asset working sets are in the manifest (`mips`, `dims`).

## 6. Negative controls (all live; each fails the check it targets)

| Control | Transcript | Mechanism | Outcome |
|---|---|---|---|
| NC-A: substituted/flipped asset | `nc-a-hash-abort.txt` | `Triangle.wt` bytes flipped in a scratch root → compile `ABORT` (exit 2, no image emitted) and `verify` `HASH MISMATCH` ABORT (exit 2) | **PASS** (fails as designed) |
| NC-B model: wrong mip under budget | `nc-b-mip-mutant.txt` | `SXT026_NC_B_FORCE_MIP6` vs correct model on identical inputs; correct PASSES proposed corr/rms bounds, forced-mip6 corr falls below | **PASS** (fails as designed) |
| NC-B RTL: mip-threshold mutant | `rtl-exactness.txt` | `-DWAVETABLE_MUTANT_MIP` (mip-2 threshold halved) vs clean RTL on the pitch-extreme fixture (mip 2 window exercised) | **PASS** (mutant FAILS exactness; clean PASSes) |
| **NC-D RTL (#180): scene-decimator mutant** | `rtl-exactness.txt` | `-DWT_SCENE_MUTANT_HB_ORDER` — ONE line of the per-scene decimator's reconstruction swapped to the pre-#123 A-even/B-odd branch order (the same defect `rtl/voice/voice_halfband_order_mutant.sv` isolates on the voice leaf) vs clean RTL, same fixture and stimulus | **PASS** (mutant FAILS **on the 48 kHz leg**: first 48 kHz mismatches at block 0 `mono48[2] model=−4 rtl=−6`, `mono48[3] model=−15 rtl=35`, `mono48[4] model=548 rtl=911`; clean RTL PASSes all 132,000 48 kHz samples) |
| NC-C: unison overflow | `nc-c-unison-overflow.txt` | `unison=17` → explicit rejection exit 1, never clamped | **PASS** (fails as designed) |

**Why NC-D is load-bearing and not decorative.** Section 2's 48 kHz coverage
claim is only worth the control that can refute it: a comparison that PASSed
against a mutated decimator would be covering nothing. `compare_wt_rtl_model.py
--mutant-scene` therefore exits non-zero unless the comparison fails *and* at
least one of its failures is a `mono48` mismatch — a scene mutant that only
broke an oscillator checkpoint is refused, not counted.
`tools/run_sxt026_checks.py` step 6 asserts the same thing independently, and
also asserts that the **clean** run actually compared `blocks × 32` 48 kHz
samples, so a silently-empty 48 kHz leg cannot masquerade as a PASS.

## 7. Reproducibility

`python3 tools/run_sxt026_checks.py --asset-root <pinned resources/data>`
regenerates: the manifest image + end-to-end verify transcript (1), NC-A
(2), NC-B (3), NC-C (4), the budget matrix (5, reuses committed
reference renders), the RTL exactness **triple** (6 — clean build plus the
mip-threshold and scene-decimator mutants; regenerates stimulus in
/tmp, never committed), and the sustained concurrent run (7). Requires
the external pinned oracle for steps 1–5 reference re-checks; committed
`*-ref.wav` renders were produced by `tools/render_wt_reference.py`
(deterministic, 3 bit-identical repeats, sidecar JSONs committed).
`python3 -m pytest tests/test_sxt026_wavetable.py` — 12 tests,
deterministic; the 11 oracle-dependent tests skip (NOT_RUN, never pass)
when the external pinned oracle is absent (e.g. CI); the in-repo payload
guard always runs.

The nine committed `artifacts/model-*.wav` renders are regenerated by
`run_model.py` per fixture (`--inputs <inputs>.json --sequence <seq>`), and
`tests/test_wt_decimation_stage.py::test_leg_b_is_still_the_frozen_models_own_render`
re-derives all nine and asserts they are byte-identical to what is committed —
so a moved model cannot leave a stale WAV in this directory.

Environment: 48 kHz; engine pin above; iverilog 11; python 3.11+.
Executed against the pinned oracle tree (identical pin
`58914e59c608ed4384ba6002e44c3465c58b2e71`; the provisioned remote box
was unreachable for the entire session — deviation recorded in the PR —
so renders, simulations, and checks ran on the local pinned clone;
every artifact carries its identity sidecar and the checks script is
the environment-independent reproducer).

## 8. What this record does NOT establish

- No preset-support claim for `Kick.fxp`, `Monster Feedback.fxp`, or any
  preset: coverage claims require complete wet-preset fidelity
  (effects included) plus listening records. The fixture overrides are
  test configurations, not adapted presets, and count toward nothing.
- No musical-quality claim (no human listening has occurred).
- No gf180mcu/FPGA synthesis, timing, area, or hardware-playback claim;
  the RTL is a behavioral exactness schedule with declared traffic costs.
- No distribution-license determination: `.wt` payloads and the quoted
  mip halfband constants remain flagged into the open determination
  (#25) via decision-records/0004.
- Budget freeze: the proposed bounds and the SXT-022 proposal both remain
  PENDING-FREEZE; the section-4 finding must be resolved by the freeze
  owner, not by widening numbers here.
- **The 48 kHz RTL-vs-model PASS (issue #180) is claim (1) only.** It
  establishes that this leaf's RTL reproduces the frozen fixed-point model's
  48 kHz output exactly, under a live scene-decimator mutant. It establishes
  **nothing** about whether that model matches the pinned engine's 48 kHz
  output — that is claim (2), still PARTIAL against [PROPOSED] budgets
  (section 3) with the section-4 finding open — and nothing about how the leaf
  sounds (claim 3).
- **No claim that moving the decimator improved fidelity.** The move was made
  for RTL coverage and topological agreement with the engine
  (`decision-records/0018`); the measured placement difference was ≤ 1 int16
  LSB and the re-freeze moved three renders by exactly that, with no verdict
  change. Presenting #180 as a fidelity improvement would misread sections 2a
  and 3.
- **The per-scene placement being the engine's is not a claim that the scene
  arithmetic matches the engine's.** The model is Q10.21 fixed point where the
  engine's scene path is float32 — declared deviation 1, and the territory of
  the section-4 bounded finding, untouched by #180.
- **The committed `artifacts/model-*.wav` / `budget-metrics.json`**: section
  3's headline numbers were republished by #145 after the #123 halfband
  branch-order fix (see that section's own change note); the per-segment
  decomposition and the section 4 discriminating experiments there remain
  the pre-#123 numbers.
