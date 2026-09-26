# SXT-028e-sse evidence record — Distortion, SSE quad-waveshaper branch
# (FX models 3..7): frozen fixed model, exact RTL, per-instance
# `QuadWaveshaperState`, reference leg NOT_RUN

Branch: `feature/issue-121` · Issue: #121 (SXT-028e-sse) · Raised by: #57
(SXT-028e) finding F-028e-2 · Epic: #3 · Date: 2026-09-26

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz,
block size 32 (`oracle/manifest.json`). Algorithm authority: the
`useSSEShaper` branch of `src/common/dsp/effects/DistortionEffect.cpp` at
that pin, `src/common/FilterConfiguration.h:235` (`n_fxws = 8`,
`FXWaveShapers`), and
`libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce`
(`GetQuadWaveshaper`, `QuadWaveshaperState`, and the five reachable shapers
in `Effects.h` / `Saturators.h` / `Rectifiers.h` / `ADAA.h` /
`WaveshaperLUT.h` / `Fuzzes.h` / `DCBlocker.h`). Everything else in the
chain is the machinery SXT-028e (#57) already froze. Read and cited; no
code, tables or assets copied.

**Claim discipline.** This record advances exactly one of the three separate
claims: **(1) the RTL matches the frozen fixed-point model exactly**
(iverilog; demonstrated). It does **NOT** advance **(2)
model-vs-pinned-engine agreement** — that leg is **NOT_RUN** here (§3)
because no pinned oracle was reachable in the implementation environment —
and it does **NOT** advance **(3) the instrument sounds good** (no human
listening; #8/#9 BLOCKED-on-human). It establishes no preset-support claim,
no cost/area/timing/synthesis/hardware-playback claim, and it **freezes no
budget**. No generic substitute is used under any claim — NC-A and NC-A2
prove both a generic and the *sibling leaf's own shaper* are rejected.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (15 cases exact, 10/10 RTL mutant controls CONTROL-OK) | `rtl-exactness.json` |
| Shared #57 chain REUSED unchanged (bit-identical) | **PASS** | `tests/test_sxt028e_sse.py::test_shared_chain_is_bit_identical_to_sxt028e` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** (no oracle reachable; finding F-028e-sse-3) | §3 |
| Model-boundary agreement vs the independent float twin | **PASS** for FX models 3/5/6; **budget NOT met, at the measured sensitivity floor** for 4 and 7 (finding **F-028e-sse-4**) | §2, `negative-controls/` |
| Per-instance `QuadWaveshaperState` (two concurrent instances) | **PASS**; pooling mutant FAILS | `rtl-exactness.json` `prs-dual-*`, `mutant-wsshared`, `tests/…::test_per_instance_independence` |
| DC-offset probe + `/64` drive interpolation + `skipDriveNorm` | **PASS** (checkpointed, and three controls that "correct" them FAIL) | §4, §5 |
| Tails (declared 1600-block ringout span, incl. a mid-tail fx-rebuild reset) | **PASS** at the exactness boundary; one KNOWN-GAP recorded | §6 |
| Quad-waveshaper state bounded (issue stop/escalate clause) | **PASS** — 8 × Q24.43 + 2 bits = 65 B/instance delta; 0 B external | §7, `artifacts/buffer-requirement.json` |
| Constant inventory (DR-0012's reserved pass) | **DR-0014 PROPOSED**; the `FuzzTable<1>` re-derivation discharged BY BUILD against the *external* pinned headers (1025/1025 MATCH) | §8, `artifacts/fuzz-table-rederivation.json` |
| Negative controls live | **11/11 CONTROL-OK** model-side + **10/10** RTL-side | `negative-controls/`, `rtl-exactness.json` |
| Oracle extraction of fixture inputs | **BLOCKED** (fail-closed refusal recorded) | §1 |
| Newly-enabled presets supported | **0** (honest delta) | §9 |

## 0. Findings (routed, not resolved here)

**F-028e-sse-1 — `rcp_ps` is an estimate, and an implementation-defined one
(bounded deviation, routed to #12).** `DIGI_SSE2` (`rcp_ps(drive)`), `TANH`
(`rcp_ps(denom)`) and `ADAA` (`rcp_ps(dx)`) use the SSE reciprocal
*estimate*, specified only to ~12 bits of relative accuracy
(|rel err| ≤ 1.5·2⁻¹² ≈ 3.7e-4) and **not** bit-identical between x86
implementations, nor between x86 and simde-on-ARM — and the pinned evidence
host is arm64 macOS (`oracle/manifest.json`). The frozen model uses the
**exact** reciprocal, rounded once (`quad_shapers.py` DD-2). Consequence:
the model-vs-reference leg for FX models 4, 6 and 7 carries an extra term
bounded by that estimate error. The RTL-vs-model leg is unaffected (both
sides compute the exact reciprocal). Routed to SXT-017 (#12); no budget is
frozen here.

**F-028e-sse-2 — `QuadWaveshaperState::init` is indeterminate in the engine
(declared, bounded).** `DistortionEffect::init()` zeroes `wsState.R[i]` but
does **not** touch `wsState.init`, and `QuadWaveshaperState` has no
constructor, so on a freshly spawned effect that mask holds whatever the
allocation left there. Only `ADAA_FULL_WAVE` (FX model 6) reads it. The
frozen model pins it to ALL-ONES ("this is the first sample"), which is the
documented intent of the field (`ADAA.h`). Bound: the choice can change at
most the **first oversampled sample after each reset**, FX model 6 only —
the ADAA registers are written unconditionally, so nothing persists. The
`mutant-adaainit` RTL control flips the choice and FAILS the exactness
check, so the decision is pinned rather than incidental.

**F-028e-sse-3 — the reference leg could not be run (BLOCKED, routed to
#12).** `oracle/manifest.json` pins the executable oracle *outside* this
repository. No such checkout and no built `surgepy` exists in this
implementation environment, so no fixture was rendered from the pinned
engine, no model-vs-reference max/rms/corr number exists for this leaf, and
the oracle extraction of the carriers' `deactivated` / `extend_range` flags
is **BLOCKED**. Reported as **NOT_RUN**, never as a pass. Identical in kind
to #57's F-028e-1. Everything needed to run it is committed.

**F-028e-sse-4 — two of the five shapers make the sample-domain [PROPOSED]
budget an unattainable instrument (measured, routed to #12).** FX models 4
(`wst_digital`, a hard staircase quantizer) and 7 (`wst_fuzzsoft`, a
pseudo-random LUT) sit **inside** the Distortion feedback loop, so an
arbitrarily small arithmetic difference can flip a quantizer/LUT decision
and produce a full-step output change. Measured at the model boundary
(`negative-controls/negative-controls.json`, control NC-0b):

| FX model | shaper | model vs independent float twin | its own sensitivity floor | vs [PROPOSED] ≤ −46 dBFS |
|---|---|---|---|---|
| 3 | `SINUS_SSE2<false>` | −103.94 dBFS | −112.55 dBFS | **PASS** |
| 4 | `DIGI_SSE2` | −72.79 dBFS | −72.78 dBFS | **FAIL** (at the floor) |
| 5 | `OJD` | −104.04 dBFS | −112.36 dBFS | **PASS** |
| 6 | `ADAA_FULL_WAVE` | −105.67 dBFS | −114.18 dBFS | **PASS** |
| 7 | `TableEval<FuzzTable<1>,1024,TANH>` | −31.20 dBFS | −31.51 dBFS | **FAIL** (at the floor) |

The "sensitivity floor" column is the **same float twin compared with
ITSELF** after a one-Q13.18-LSB perturbation of `dNow` — a difference the
frozen drive word cannot even represent. For models 4 and 7 the frozen model
is no further from the twin than the twin is from itself under that nudge.
That the divergence is not a translation error is established separately and
tightly by the **open-loop** probe (NC-0): each of the five shapers,
fixed-point vs an independent float implementation of the same pinned
kernel, agrees to **≤ 2.44 LSB Q10.21** (worst case, FX model 7; models 3
and 4 are bit-exact) over a 20,000-point input × drive sweep with the
registers advancing.

**No budget is relaxed here and no leg is reported as a pass that did not
pass.** Choosing a metric that can discriminate for a chaotic quantizing
nonlinearity is SXT-017's decision (#12), not this leaf's.

**F-028e-sse-5 — FX model 7 (`wst_fuzzsoft`) has ZERO corpus reach.** The
active-Distortion-slot histogram, re-derived from
`corpus/normalized/graphs.jsonl` by
`tests/test_sxt028e_sse.py::test_corpus_reach_is_inventory_not_a_support_claim`,
is `{0: 418, 1: 27, 2: 2, 3: 13, 4: 8, 5: 6, 6: 1, 7: 0}` — 28 of 475 slot
instances (5.9 %) are in this leaf's scope, and **none of them uses model
7**. The algorithm is implemented (it is reachable from the UI and from any
future preset) and is exercised by synthetic corners, but no fixture record
exists and none is invented. Inventory only; not a support claim.

## 1. Fixtures, applicability boundary (fail-closed), refusals

None of the three B4-scope carriers SXT-028e named uses an SSE-branch model
— all three are model 0 — so this leaf selected its **own** carriers, one
per reachable FX model, from `corpus/normalized/graphs.jsonl`
(`tools/extract_distortion_sse_inputs.py`). No oracle was reachable
(F-028e-sse-3), so **no reference fixture was rendered**.

| FX model | shaper | carrier | census blob SHA-1 | status |
|---|---|---|---|---|
| 3 `wst_sine` | `SINUS_SSE2<false>` | `Damon Armani/Drums/Reverse Crash.fxp` | `de5c684d…` | graphs record written, **INCOMPLETE-BLOCKED-ON-ORACLE** |
| 4 `wst_digital` | `DIGI_SSE2` | `Damon Armani/Plucks/Trance Pluck.fxp` | `1bb5209f…` | graphs record written, **INCOMPLETE-BLOCKED-ON-ORACLE** |
| 5 `wst_ojd` | `OJD` | `Kinsey Dulcet/Guitars/Mutant Lo-Fi Acoustic Guitar Workstation.fxp` | `714821ee…` | graphs record written, **INCOMPLETE-BLOCKED-ON-ORACLE** |
| 6 `wst_fwrectify` | `ADAA_FULL_WAVE` | `Luna/Guitars/Awful FM Guitar.fxp` | `d71a9cfd…` | **REFUSED**: `fx_disable = 1` (non-zero). It is the ONLY model-6 instance in the corpus, so model 6 has no usable carrier. |
| 7 `wst_fuzzsoft` | `TableEval<FuzzTable<1>,…>` | — | — | **NO CARRIER EXISTS** (F-028e-sse-5) |

* **Oracle extraction: REFUSED** for all four carriers rather than inventing
  the missing flags. Transcript: `artifacts/extract-refusals-oracle.txt`.
* **Graphs cross-check: written, and deliberately unusable for a model
  run.** `--mode graphs` derives the 12 loader-normalized parameter values
  from the SXT-011 pinned-loader export, re-verifies each census blob SHA-1
  against `corpus/census-v0.1/corpus-manifest.json`, and writes
  `model/effects/fx_inputs/type-distortion-sse-*.json` with
  `extraction_status = INCOMPLETE-BLOCKED-ON-ORACLE` and the five
  oracle-only fields explicitly `null`. `DistortionSSEParams` **refuses**
  such a record; `tests/test_sxt028e_sse.py` asserts that refusal, so the
  incomplete record can never be silently promoted into a model run.
* The extractor also fails closed in the **other** direction: a Distortion
  slot whose FX model is 0..2 is refused here, because it belongs to #57.

Because no reference bus exists, the RTL/model exactness cases below are
driven by **declared synthetic stimuli and parameter corners**, not by
fixture replays. That is a weaker basis than a canonical-fixture replay and
it is stated as such — it bounds claim (1) only.

## 2. Frozen fixed-point model

`model/effects/type-distortion-sse/` — `sse_tables.py` (the two re-derived
table rows), `quad_shapers.py` (the five shapers, the state layout and the
four declared deviations), `distortion_sse_model.py` (the block schedule),
plus the freeze doc `README.md`.

**The shared chain is REUSED, and that is asserted, not claimed.** The
pre/post peak EQ, both instantized oversampled LP2B stages, the feedback
recurrence, the drive/outgain lipol ramps, the two-stage halfband
decimation, the ringout fade and every word format are **imported** from
`model/effects/type-distortion/distortion_model.py`. Running this leaf's
block schedule with the #57 table shaper substituted for the quad shaper
(the documented `chain_probe_shaper` verification hook) reproduces
`DistortionModel` **bit for bit** — every output sample over 24 blocks and
every one of the 66 shared checkpoint fields
(`test_shared_chain_is_bit_identical_to_sxt028e`). A future edit that
disturbs the shared chain fails that test.

Word formats added by this leaf (the #57 formats are unchanged): shaper
words, every shaper intermediate, the four quad-waveshaper registers,
`dNow`, `dD` and `dcOffset` are **Q24.43 s64**; the TANH numerator and
denominator alone are **Q40.23 s64** — the one place the pinned
`x·(27 + x²)` exceeds Q24.43's ±8.39e6 because |x| may reach the Q10.21 rail
(1024).

Declared deviations, bounded and stated (`quad_shapers.py` DD-1…DD-4 and
§0): SIMD lanes 2/3 are engine stack garbage and provably non-interacting;
`rcp_ps` is an estimate (F-028e-sse-1); `wsState.init` is indeterminate
(F-028e-sse-2); the Q24.43 drive-normalized input saturates below ~1.2e-4 of
drive and the model **counts** those events per instance rather than
assuming they did not happen; and, as in #57, the engine's ±1e-8 denormal
bias is ~0.02 LSB at Q10.21 and is therefore not representable.

**Independent cross-check of the fixed-point implementation** (NOT a
reference claim): `tools/distortion_sse_negative_controls.py` NC-0 compares
each shaper against an independent float implementation written from the
pinned sources — worst case **2.44 LSB Q10.21** over 20,000 points with
registers advancing — and NC-0b does the same through the whole chain, with
the results and the sensitivity floors in §0 (F-028e-sse-4).

## 3. Model vs pinned engine — NOT_RUN

| Case | max abs (LSB) | rms (dBFS) | spectral corr | tail | Verdict |
|---|---|---|---|---|---|
| (any fixture × any sequence) | — | — | — | — | **NOT_RUN** |

Budgets that *would* apply, unchanged from the issue and from SXT-023:
max ≤ 8,192 LSB Q10.21; rms ≤ −46 dBFS; spectral corr ≥ 0.98 —
**[PROPOSED], not frozen**; freeze gated on SXT-017 (#12). No number is
reported against them because none was measured. See F-028e-sse-3, and see
F-028e-sse-4 for why the metric itself is in question for FX models 4 and 7.

Reproduce on an oracle host (everything needed is committed):

```sh
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 \
    tools/extract_distortion_sse_inputs.py --mode oracle
# then render fixtures under SXT-012 policies (tools/render_fx_fixtures.py
# pattern) and compare the frozen model against the wet bus.
# Also re-run tools/check_fuzz_table_rederivation.py there: the pinned host
# is arm64 macOS / libc++, and the committed MATCH is libstdc++-only.
```

## 4. RTL vs frozen model — EXACT (iverilog)

`rtl/effects/type-distortion-sse/tb_distortion_sse.sv` +
`tools/compare_rtl_model_distortion_sse.py` → `rtl-exactness.json`
(status **PASS**). Two instances with fully independent state. The
quad-waveshaper registers, the `1/dNow` pre-scale, the `/64` drive
interpolation and the **DC-offset probe are computed in the RTL**, not
streamed — otherwise the controls that target them would grade the model
only. The control plane (drive/outgain RAW lipol targets, the feedback
coefficient, four coefficient sets, the activity/model flags), the twelve
halfband coefficients and the eleven designed shaper scalars are streamed
(DR-0002 clause 1, DR-0014 clause 1); a test asserts none of those eleven
values appears as a literal in the RTL source.

Compared with exact integer equality: every per-instance output sample
(**O**), every shaper-loop tap checkpoint (**X**: the post-`lp2` oversampled
L/R word at each of the first 4 base samples × 4 oversampling steps), and
every declared state checkpoint (**T**) — which for this leaf is #57's set
(feedback registers, both lipol targets, both peak-EQ coefficient lags, all
four TDF2 register pairs, all 144 halfband allpass state words) **plus all 8
quad-waveshaper registers, both `init` mask lanes, the end-of-block `dNow`
and the block's DC-offset probe result**, per instance — and the
frozen-revision pin.

Simulator: `Icarus Verilog version 13.0 (stable) (v13_0)` (recorded verbatim in
`rtl-exactness.json.sim_version`). Cases, as recorded:

| Case | blocks | inst | O samples | X taps | T checkpoints | T fields | Verdict |
|---|---|---|---|---|---|---|---|
| `prs-dual-128` — two instances, models 7 and 6, independent state | 128 | 2 | 16,384 | 34 | 18 | 3,384 | **exact** |
| `digital-reset24-48` — model 4: skipDriveNorm + the /64 drive interpolation, reset mid-render so the drive ramp restarts | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `sine-48` — model 3: the round-to-nearest SSE table index convention | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `prs-reset64-128` — core reset mid-render | 128 | 2 | 16,384 | 34 | 18 | 3,384 | **exact** |
| `model-3-sine` — FX model 3 SINUS_SSE2<false>: table gather with the round-to-nearest SSE index and DO_FOLD == false edge clip | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `model-4-digital` — FX model 4 DIGI_SSE2: skipDriveNorm, the internal rcp(drive) and the staircase quantizer | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `model-5-ojd` — FX model 5 OJD: all five disjoint breakpoint branches, negative feedback | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `model-6-fwrectify` — FX model 6 ADAA_FULL_WAVE: the two ADAA registers and the `init` first-sample mask | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `model-7-fuzzsoft` — FX model 7 TableEval<FuzzTable<1>,1024,TANH>: TANH Q40.23 rational, the 1025-word LUT and dcBlock | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `corners-deact-both` — both high-cuts deactivated (LP stages bypassed), drive 24 dB, feedback -0.9 | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `corners-extend-hot` — extended drive and both extended EQ gains, one high-cut deactivated, zero feedback | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `corners-lowdrive-sat` — DD-4 corner: extended drive -120 dB quantizes to ZERO in the Q13.18 ramp word, so the 1/dNow pre-scale takes the saturated-reciprocal path | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `corners-digital-hifb` — model 4 with feedback 0.95 — the loop gain the `skipDriveNorm` exception exists to protect | 48 | 1 | 3,072 | 7 | 4 | 752 | **exact** |
| `ringout-tail-1663` — declared tail span (1600-block ringout, model 7) | 1663 | 1 | 102,336 | 202 | 102 | 19,176 | **exact** |
| `reset-mid-tail-160-320` — fx-rebuild/panic reset 96 blocks into the ringout tail | 320 | 2 | 32,768 | 68 | 36 | 6,768 | **exact** |
| **total** | | | **201,664** | **415** | **218** | **40,984** | **PASS** |

Every one of those output samples, tap checkpoints and state-checkpoint
fields matched the frozen model with integer equality, and every case's
frozen-revision pin matched (`revision_pin.ok`). A single mismatched word
anywhere is a FAIL — there is no tolerance on this leg.

Per-instance state acceptance (issue #121): two concurrent instances with
different parameter sets *and* different SSE waveshaper models (7 and 6 —
the two that own `QuadWaveshaperState` registers) keep independent
histories, and the pooled mutant demonstrably FAILS. Reset/panic:
`prs-reset*` bulk-resets the core mid-render and `reset-mid-tail-*` does the
same **96 blocks into the ringout tail** — the engine's
`suspend() == init()` fx-rebuild path, including `wsState.R[i] =
setzero_ps()`. Both are exact per instance.

What the mid-tail reset case does and does not settle is unchanged from #57:
it pins the **model-side** semantics and proves the RTL implements them
identically. It does **not** establish that the pinned engine behaves this
way — mid-render patch change on the engine side remains BLOCKED by the
surgepy embedding limitation (`reports/sxt-024` §3) and is moot here because
no oracle ran at all.

## 5. Negative controls

**RTL mutant controls** (generated from the committed testbench by source
substitution; each is run on a stimulus bed chosen so the defect is
*reachable* — a control run where it cannot fire would be theatre):

| Control | bed | what it breaks | mismatched words | Verdict |
|---|---|---|---|---|
| `mutant-wsshared` | dual | per-instance QuadWaveshaperState pooled onto instance 0 | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-nodcoffset` | dual | the zero-input DC-offset subtraction dropped | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-dcprobe-live` | dual | DC probe run on the LIVE wsState instead of a throw-away | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-order` | dual | band1/band2 swapped (post-EQ applied pre-shaper) | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-dcblockfac` | dual | dcBlock pole 0.9999 replaced by 1.0 | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-adaainit` | dual | ADAA `init` first-sample mask forced false | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-drivestep128` | digital | dD = (dE - dS)/128 instead of the pinned /64 | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-diginorm` | digital | `skipDriveNorm` removed: DIGITAL double-divided by drive | 21 | **CONTROL-OK** (mutant FAILS) |
| `mutant-cvttrunc` | sine | SSE round-to-nearest-even int conversion replaced by truncation (the lookup_waveshape convention) | 21 | **CONTROL-OK** (mutant FAILS) |
| `stale-revision-pin` | dual | a stale/stub frozen-model revision reported as PASS | n/a (0 output mismatches — the pin itself refuses) | **CONTROL-OK** (REFUSES to report PASS) |

**Model-side controls** (`negative-controls/`, **ALL-CONTROLS-OK**, 11/11):
NC-0 open-loop shaper agreement (PASS), NC-0b closed-loop twin with the
per-model sensitivity floors (§0), NC-A generic single-rate tanh substitute
(FAIL → ADAPTED), **NC-A2 the sibling leaf's own `lookup_waveshape` shaper
substituted for `GetQuadWaveshaper`** (FAIL → ADAPTED; this is the single
most plausible real shortcut for this leaf — "models 3..7 are just other
waveshapes" — and it is refused), NC-B dropped tail (FAIL), NC-C wrong band
order (FAIL), NC-D pooled `QuadWaveshaperState` with the chain state left
per-instance (FAIL), NC-E stale revision pin (REFUSED), NC-F `/128` drive
step (FAIL), NC-G `skipDriveNorm` removed (FAIL), NC-H DC-offset probe
dropped (FAIL), plus the recorded KNOWN-GAP KG-1.

**NC-0b is a gate for FX models 3/5/6 and CHARACTERIZATION for 4 and 7 —
stated so it cannot be misread.** For models 4 and 7 the [PROPOSED]
sample-domain metric provably cannot discriminate below the measured
sensitivity floor (F-028e-sse-4), so that leg's "at or below the floor"
clause cannot fail in a way that would indicate a defect. **`CONTROL-OK` on
NC-0b therefore does not mean "FX models 4 and 7 verified."** What does
carry falsifiable weight for those two models is NC-0's open-loop shaper
probe (≤ 2.44 LSB Q10.21, §0) and the unconditional RTL-vs-frozen-model
exactness leg (§4). The scope is machine-readable in
`negative-controls/negative-controls.json` → NC-0b → `gate_scope`.

**Two controls are deliberately graded on a DIGITAL bed, and the reason is
itself a finding.** For FX models 3, 5, 6 and 7 the `1/dNow` pre-scale and
the shaper's own leading `x · drive` cancel algebraically, so `dNow` — and
therefore the `/64` interpolation step — is **not observable at the output**
for those models. It *is* observable for model 4, which is exactly the model
the pinned source singles out with `skipDriveNorm`. NC-F/NC-G and
`mutant-drivestep128` / `mutant-diginorm` are therefore graded on a model-4
bed, and the benign model-7 leg is recorded alongside so the reachability
limit is visible rather than implied. The structural claim itself is
asserted by
`tests/test_sxt028e_sse.py::test_drive_normalization_cancels_for_the_non_digital_models`.

## 6. Tails

**Declared tail span: `ringout_time` = 1600 blocks = 1.0667 s at 48 kHz**
(`DistortionEffect.h:48`), of which the last `ringout_end` = 320 blocks
apply the output-gain fade `ringoutMul = limit01((1600 − ringout − 1)/320)`.
Unchanged from #57, and reused rather than re-derived.

* **Exactness over the whole declared span**: the `ringout-tail-*` RTL case
  drives 1600 ringout blocks to completion and compares every output sample
  and checkpoint with integer equality — the fade included, and the
  `dcBlock` registers of FX model 7 tracked throughout.
* **Reset in the middle of the tail**: `reset-mid-tail-*` takes the
  fx-rebuild path 96 blocks into the ringout, with two instances, exact per
  instance.
* **Dropped-tail control (NC-B)**: truncating the render 1 block into the
  ringout — inside the measured live decay — FAILS the tail-region residual
  gate (≤ −20 dB relative to the reference tail RMS). CONTROL-OK.
* **KNOWN-GAP (KG-1, recorded, not a control)**: a *late* truncation (800
  blocks into the ringout) is **not** rejected by the whole-region residual
  gate, because the tail region's RMS is dominated by the early,
  high-energy part of the decay. Same gap as #57's KG-1 and
  `reports/stereo-comparator-tail-gate` (#111). What covers the full span
  instead is the integer-equality `ringout-tail-*` case above.
* Measured live decay for the NC-B parameter set (FX model 6, feedback 0.99,
  drive 45 dB): the output stays above 1 LSB Q10.21 for **1593 of the 1600**
  ringout blocks, so the window is not merely nominal.

## 7. External-memory traffic and state (SXT-015/016 conventions)

`tools/distortion_sse_buffer_report.py` → `artifacts/buffer-requirement.json`
(measured from the frozen model's own state layout and transaction
counters):

* Per-instance external writable state: **0 bytes**, 0 reads/sample, 0
  writes/sample, 0 MB/s. `QuadWaveshaperState` is four SIMD registers, not a
  delay line; like #57 this effect owns **no delay-line-class buffer**, so
  the rule "long buffers external-WRITABLE, never flash" stays vacuously
  satisfied.
* On-chip per-instance state: **198 × Q24.43 words + 6 × 32-bit words + a
  2-bit mask = 1,609 B**, of which **this leaf's delta is 8 × Q24.43 + 2
  bits = 65 B** (the #57 chain accounts for the other 190 Q24.43 words).
* **The issue's stop/escalate condition is NOT triggered.** The
  quad-waveshaper state is bounded and small, independent of block size,
  sample rate and FX model; and only registers 0 and 1 are touched by *any*
  of the five reachable shapers (measured, not asserted:
  `test_register_use_inventory_is_measured_not_asserted`), so a shared
  instance schedule needs 2 registers × 2 lanes of live context per
  Distortion slot. No escalation to #12 is required on state/cost grounds.
* Shared frozen ROM (not per-instance state): **2,049 words = 8,196 B**
  (1024 `wst_sine` + 1025 `FuzzTable<1>`); three of the five shapers need no
  table at all.
* Compute shape recorded for SXT-016: 4× oversampling ⇒ 4 shaper
  evaluations per sample per channel; one `1/dNow` reciprocal per
  oversampled step for models 3/5/6/7 (skipped for 4) plus one
  shaper-internal reciprocal for models 4, 6 and 7; one DC-offset probe per
  block per instance.
* Declared range saturation (DD-4): **0 events** across a 64-block render
  for every FX model — measured, not assumed. The dedicated
  `corners-lowdrive-sat` exactness case *does* reach the corner (drive
  extended to −120 dB quantizes to zero in the Q13.18 ramp word) and the RTL
  still matches the model exactly there.
* **Fit verdict: [PENDING-SXT-016].** This section reports measured demand
  only; it is not a cost, area, timing, power or synthesis claim.

## 8. Constant inventory (DR-0012's reserved pass, discharged)

`decision-records/0014-distortion-sse-quad-waveshaper-constants.md`
(PROPOSED) closes DR-0012's "Consequences" clause 3. Three classes:

* **11 quoted designed scalars** — OJD's four breakpoints and its two
  float32 denominators (note `1.f/(4*(1-0.9f))` is **2.4999995**, not 2.5,
  because `1 - 0.9f` is `0.100000024f`), the TANH rational's 9 and 27, the
  ADAA tolerance 1e-4, the dcBlock pole 0.9999 — quoted with provenance in
  `quad_shapers.py` and **streamed to the RTL** through the testbench init
  file, never duplicated there (DR-0002 clause 1). A test asserts none of
  the eleven appears as a literal in the RTL source.
* **2 re-derived table rows** — `wst_sine` (1024 words) from
  `sin((i−512)·π/512)`, and `FuzzTable<1>` (1025 words) from
  `x·(1−range) + U(−range, range)` with the header's own pinned
  `portable_minstd_rand(2112)`. The committed ROM is a build product of
  `sse_tables.py` and a test asserts it byte for byte.
* **6 structural powers of two** — not engine data; `localparam`s in the RTL.

**The `FuzzTable<1>` re-derivation claim is discharged BY BUILD, not by
assertion — against the pinned headers themselves, which stay outside this
repository.** The one implementation-defined step is the standard library's
uniform real-valued draw, which the pinned header does *not* pin (it only
de-typedefs the LCG). `tools/check_fuzz_table_rederivation.py` resolves an
**external** checkout of the pinned `sst-waveshapers` and
`sst-basic-blocks` (`ORACLE_SURGE_DIR`, `--sst-include`, or
`oracle/fetch-waveshaper-headers.sh`, which refuses to write inside this
repository), refuses to proceed unless each checkout's HEAD equals the
`oracle/manifest.json` pin, and compiles a ~15-line driver that is
**original to this repository** — it `#include`s those headers and
instantiates the library's own `LUTBase<1024, FuzzTable<1>>`. **No engine
expression is transcribed into this tree**; it is included, so the check
cannot be defeated by a transcription slip either. All 1025 float32 bit
patterns are compared against the generator: **MATCH, 1025/1025, 0
mismatches** (g++ 13.3.0 / libstdc++, pinned headers `dd12f31a…` /
`a32b8aec…`; `artifacts/fuzz-table-rederivation.json`).

**Status discipline:** without the external checkout the tool reports
**NOT_RUN** (exit 77) and on any drift from the pins **BLOCKED** (exit 78) —
neither is ever reported as a pass, and
`tests/test_sxt028e_sse.py::test_rederivation_checker_reports_not_run_without_the_pinned_headers`
asserts the NOT_RUN path live. A second live guard,
`::test_rederivation_checker_carries_no_engine_source_text`, fails if any
engine expression, constant or typedef is re-introduced into the tool.

**Limit, stated:** the build validates libstdc++ only. The libc++
equivalence is derived by reading its `generate_canonical` and is recorded
as **UNVERIFIED-BY-BUILD**; the pinned oracle host is arm64 macOS / libc++,
so re-running the tool there is a named follow-up (#135), not a completed
leg. If the check ever reports MISMATCH, the row must be re-classified as
quoted data by amending DR-0014 — it is a live guard on a
licensing-relevant claim.

## 9. Newly-enabled presets (honest delta)

**Supported stays 0.** The conjunction in `reports/coverage-v1/README.md`
still fails for every carrier at earlier gates, and this leaf adds its own:
model-vs-reference is **NOT_RUN** for this class (F-028e-sse-3); FX model 6
has no usable carrier and FX model 7 has no carrier at all
(F-028e-sse-5); and the sample-domain budget is not an attainable
instrument for models 4 and 7 (F-028e-sse-4).

**`reports/coverage-v1/leaf-verification.json` is deliberately NOT
modified.** Updating the ledger is a coverage-publication action, and
coverage publication is an explicit non-goal of #121 (it belongs to #22);
`main` also still carries the pre-existing republishability defect filed as
#125. More to the point, **nothing would change**: the `fx:Distortion` row
already names #121 as the sibling leaf for models 3..7, its
`model_vs_reference` is `NOT_RUN`, and this leaf's reference leg is
`NOT_RUN` too — so no coverage number moves in either direction. Nothing in
this record should be read as a coverage claim.

## 10. Follow-ups filed

* **#136 — SXT-028e-sse follow-up (F-028e-sse-1/3/4/5): oracle-host
  reference leg for the Distortion SSE quad-waveshaper branch.** Carries the
  whole NOT_RUN claim-(2) leg: the fail-closed oracle extraction of the
  three carriers' `deactivated`/`extend_range` flags, the SXT-012 fixture
  renders with tails, the achieved max/rms/corr numbers, the missing
  carriers for FX models 6 and 7 (which must become a *declared synthetic*
  patch or stay NOT_RUN, never a substituted carrier), and the `rcp_ps`
  estimate term. It also carries F-028e-sse-4's metric question forward to
  SXT-017 (#12) with an explicit instruction not to relax the budget.
* **#135 — SXT-028e-sse follow-up: discharge the `FuzzTable<1>`
  re-derivation on the pinned arm64/libc++ oracle host.** The committed
  build-discharge of DR-0014 clause 2 is libstdc++-only (§8); the pinned
  evidence host is arm64 macOS / libc++, where the equivalence is currently
  derived by *reading* `generate_canonical`. On MISMATCH the row must be
  re-classified from "re-derived" to "quoted data with provenance" by
  amending DR-0014 — a licensing-relevant classification, which is why it is
  tracked rather than assumed.

No follow-up is filed for F-028e-sse-2 (`QuadWaveshaperState::init` is
indeterminate in the engine): it is decided and pinned here, bounded to the
first oversampled sample after each reset for FX model 6 only, and held in
place by the `mutant-adaainit` RTL control.

## 11. What this record does NOT establish

- Any model-vs-reference agreement, any fidelity policy, or any frozen
  budget (SXT-017/#12). The reference leg is **NOT_RUN**, not "passing
  quietly", and F-028e-sse-4 explicitly reports a [PROPOSED] budget as
  **not met** for two FX models rather than relaxing it.
- Any preset-support or musical-quality claim; no human listening has
  occurred (#8/#9 BLOCKED-on-human). Essentiality of this feature remains
  **UNVERIFIED** — no SXT-014 ablation carrier exists for it.
- FPGA/gf180mcu synthesis, place-and-route, timing, power, area or hardware
  playback; the RTL is an iverilog-simulated behavioural schedule (version
  recorded in `rtl-exactness.json`).
- Anything about FX waveshaper models 0..2 (that is #57), about sibling
  effect classes, or about the engine's behaviour under a mid-render patch
  change.
- Repeatability of any engine render (none was produced), and any
  libc++-host equivalence of the `FuzzTable<1>` re-derivation (§8).

## 12. Reproduce

```sh
# anywhere with iverilog (RTL-vs-model exactness + RTL mutant controls)
IVERILOG=iverilog python3 tools/compare_rtl_model_distortion_sse.py

# anywhere (model-side negative controls, state/traffic, ROM + table checks)
python3 tools/distortion_sse_negative_controls.py
python3 tools/distortion_sse_buffer_report.py
python3 tools/gen_distortion_sse_rom.py --check

# the FuzzTable<1> build discharge (§8) needs the PINNED headers, which are
# GPL-3.0-or-later and are deliberately NOT in this repository. Fetch them
# externally, then run the check; without them it reports NOT_RUN.
oracle/fetch-waveshaper-headers.sh          # writes to ${TMPDIR:-/tmp}/sxt-oracle
python3 tools/check_fuzz_table_rederivation.py
# (or, on a host with a full pinned engine checkout:)
# ORACLE_SURGE_DIR=$HOME/oracle/surge python3 tools/check_fuzz_table_rederivation.py

# anywhere (fail-closed extraction: graphs cross-check + oracle refusal)
python3 tools/extract_distortion_sse_inputs.py --mode graphs
python3 tools/extract_distortion_sse_inputs.py --mode oracle    # refuses

# unit/integrity tests (both leaves: this one must not disturb #57)
python3 -m pytest tests/test_sxt028e_sse.py tests/test_sxt028e.py -q

# ORACLE HOST ONLY (the NOT_RUN leg of §3, and the libc++ leg of §8)
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 \
    tools/extract_distortion_sse_inputs.py --mode oracle
python3 tools/check_fuzz_table_rederivation.py     # on the arm64/libc++ host
```

## 13. Provenance / licensing

All files in this repository are original (Apache-2.0 per `LICENSE`). The
SSE quad-waveshaper structure is read and cited from the pinned
GPL-3.0-or-later trees (`DistortionEffect.cpp` and sst-waveshapers); no
Surge or SST source or assets are committed. The eleven designed shaper
scalars are quoted as data under
`decision-records/0014-distortion-sse-quad-waveshaper-constants.md`
(PROPOSED), the successor DR-0012 reserved for this branch; the two table
rows are re-derived from the pinned construction formulas and are not quoted
data.

The `FuzzTable<1>` build discharge (§8) is the one place engine source is
*executed*, and it executes it **where it lives**: the driver compiled by
`tools/check_fuzz_table_rederivation.py` is original to this repository and
only `#include`s the pinned headers from an **external** checkout, pinned by
SHA to `oracle/manifest.json`. Nothing GPL-licensed is transcribed,
embedded, or committed here, and
`tests/test_sxt028e_sse.py::test_rederivation_checker_carries_no_engine_source_text`
is a live guard on that. `oracle/fetch-waveshaper-headers.sh` refuses a
destination inside the repository for the same reason. No
distribution-license determination has been made for Surge-derived
material.
