# SXT-028e evidence record — Distortion (multiband + waveshaper drive):
# frozen fixed model, exact RTL, per-instance state, reference leg NOT_RUN

Branch: `feature/issue-57` · Issue: #57 (SXT-028e) · Parent: #21 (SXT-028) ·
Date: 2026-09-25

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz,
block size 32 (`oracle/manifest.json`). Algorithm authority:
`src/common/dsp/effects/DistortionEffect.{h,cpp}` at that pin, plus the
shared machinery cited in `model/effects/type-distortion/README.md`
(Effect.h `slowrate`/`process_ringout`, FilterConfiguration.h
`FXWaveShapers`, sst-filters `BiquadFilter.h` and `HalfRateFilter.h`,
vembertech `lipol.h`, sst-waveshapers `WaveshaperTables.h` +
`SurgeStorage::lookup_waveshape`, `Parameter::get_extended`). Read and
cited; no code, tables or assets copied.

**Claim discipline.** This record advances exactly one of the three
separate claims: **(1) the RTL matches the frozen fixed-point model
exactly** (iverilog; demonstrated). It does **NOT** advance
**(2) model-vs-pinned-engine agreement** — that leg is **NOT_RUN** here
(§3) because no pinned oracle was reachable in the implementation
environment — and it does **NOT** advance **(3) the instrument sounds
good** (no human listening; #8/#9 BLOCKED-on-human). It establishes no
preset-support claim, no cost/area/timing/synthesis/hardware-playback
claim, and it **freezes no budget**. No generic substitute is used under
any claim — NC-A proves a generic is rejected.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (7 cases exact, 6/6 mutant controls CONTROL-OK) | `rtl-exactness.json` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** (no oracle reachable; finding F-028e-1) | §3 |
| Per-instance state (two concurrent instances) | **PASS** | `rtl-exactness.json` `prs-dual-*`, `tests/test_sxt028e.py` |
| Tails (declared 1600-block ringout span, incl. a mid-tail fx-rebuild reset) | **PASS** at the exactness boundary; one KNOWN-GAP recorded | §5, `rtl-exactness.json` `ringout-tail-*`, `reset-mid-tail-*` |
| External-memory traffic | **0 B, 0 words/sample** (measured); fit verdict **[PENDING-SXT-016]** | `artifacts/buffer-requirement.json` |
| Negative controls live | **7/7 CONTROL-OK** model-side + **6/6** RTL-side | `negative-controls/`, `rtl-exactness.json` |
| Oracle extraction of fixture inputs | **BLOCKED** (fail-closed refusal recorded) | §1 |
| Newly-enabled presets supported | **0** (honest delta) | §7 |

## 0. Findings (routed, not resolved here)

**F-028e-1 — the reference leg could not be run (BLOCKED, routed to #12).**
`oracle/manifest.json` pins the executable oracle *outside* this repository
(`expected_checkout` is a path on the oracle host, overridable with
`ORACLE_SURGE_DIR`). No such checkout and no built `surgepy` exists in this
implementation environment, so:

* no fixture could be rendered from the pinned engine;
* no model-vs-reference max/rms/corr number exists for this leaf;
* the oracle extraction of the fixture presets' `deactivated` /
  `extend_range` flags is **BLOCKED**.

Reported as **NOT_RUN**, never as a pass. This does not weaken the
acceptance rule — the reference budgets stay exactly as the issue states
them ([PROPOSED], freeze gated on SXT-017 #12); the leg is simply unmet and
is recorded as an open dependency of any future Distortion budget freeze.
Everything needed to run it is committed (`tools/extract_distortion_inputs.py
--mode oracle`, the frozen model, the comparator), so the leg is
reproducible on an oracle host without re-deriving the algorithm.

**F-028e-2 — the FX waveshaper `Model` parameter spans two subsystems; only
one is in this leaf (bounded scope, fail-closed).** `n_fxws = 8`
(`FilterConfiguration.h:235`). `DistortionEffect::process` routes
`ws >= wst_sine` — FX model indices **3..7** (sine, digital, ojd,
fwrectify, fuzzsoft) — through `GetQuadWaveshaper`, an sst-waveshapers SIMD
path with its own per-instance registers, a `1/dNow` drive normalization
(skipped for DIGITAL), a per-oversample drive interpolation, and a
zero-input DC-offset probe. That is a second algorithm, not a parameter of
this one, and the issue's rule is *one algorithm per leaf*. This leaf
freezes indices **0/1/2** (`lookup_waveshape`: soft, hard, asym) and
**REFUSES** 3..7 in both `DistortionParams` and `ws_tables.build_table`.

Corpus reach of the frozen scope (`corpus/normalized/graphs.jsonl`, active
Distortion slots, re-derived at 2026-09-25): **447 of 475 slot instances
(94.1 %)**, model-index histogram `{0: 418, 1: 27, 2: 2, 3: 13, 4: 8,
5: 6, 6: 1, 7: 0}`. All three of the issue's named B4-scope carriers use
model index 0. The 28 out-of-scope instances are **refused, not
approximated**: substituting a modelled shaper for an unmodelled one would
make the preset ADAPTED. Follow-up leaf filed (see §8); until it lands, no
preset whose Distortion slot uses model 3..7 may count toward
original-preset coverage.

**F-028e-3 — out-of-scope defect observed in `model/voice/voice_model.py`
(NOT fixed here).** The SXT-022 voice decimator `HalfbandD2` reconstructs
`out[n] = (A[2n] + B[2n+1]) * 0.5`. The pinned
`HalfRateFilter::process_block_D2` reconstructs `(B[2n] + A[2n+1]) * 0.5`
(lane 0 carries `cA`, lane 1 carries `cB`;
`va[i] = set_ps(cB[i], cA[i], cB[i], cA[i])`, and the reconstruction
broadcasts lane 1 of the even sample and adds lane 0 of the odd one — which
also matches the original `output = (filter_a.process(input) + oldout)*0.5`
comment preserved above that code). Measured with the M = 6 steep set, the
two orderings differ drastically in the stopband: at f = 0.3·fs the pinned
ordering rejects to **−110 dB** while the voice-model ordering leaves
**−3.45 dB** (i.e. no rejection). This leaf follows the pinned ordering;
the voice model is untouched (scope discipline) and a separate issue is
filed (§8) with this reproduction.

## 1. Fixtures, applicability boundary (fail-closed), refusals

No SXT-014 ablation carrier exists for this algorithm and no oracle was
reachable, so **no reference fixture was rendered** (F-028e-1). What was
done instead, and what it is not:

* **Oracle extraction: REFUSED.** `tools/extract_distortion_inputs.py
  --mode oracle` refuses for all three issue-named carriers rather than
  inventing the missing flags. Transcript:
  `artifacts/extract-refusals-oracle.txt`.
* **Graphs cross-check: written, and deliberately unusable for a model
  run.** `--mode graphs` derives the 12 loader-normalized parameter values
  from `corpus/normalized/graphs.jsonl` (the SXT-011 pinned-loader export —
  loader-normalized state, not raw `.fxp`), re-verifies each census blob
  SHA-1 against `corpus/census-v0.1/corpus-manifest.json`, and writes
  `model/effects/fx_inputs/type-distortion-{novuo,monsterfeedback,
  screamingsaw}.json` with `extraction_status =
  INCOMPLETE-BLOCKED-ON-ORACLE` and the five oracle-only fields
  (`preeq_highcut_deactivated`, `posteq_highcut_deactivated`,
  `preeq_gain_extend`, `posteq_gain_extend`, `drive_extend`) explicitly
  `null`. `DistortionParams` **refuses** such a record; `tests/test_sxt028e.py`
  asserts that refusal, so the incomplete record can never be silently
  promoted into a model run.

| Carrier | census blob SHA-1 | Distortion slot | model index | Chain classes | Complete-wet possible? |
|---|---|---|---|---|---|
| `patches_3rdparty/Argitoth/Leads/Screaming Saw.fxp` | `c811a9aa…` | ains1 | 0 (soft) | Distortion, Delay | yes (all landed/in-flight) |
| `patches_3rdparty/Argitoth/FX/Monster Feedback.fxp` | `2379e071…` | ains2 | 0 (soft) | EQ, Distortion, Delay, Reverb 1 | yes |
| `patches_3rdparty/A.Liv/Leads/Novuo.fxp` | `e688adfd…` | global1 | 0 (soft) | EQ, Chorus, **Reverb 2**, Delay, Distortion | **no** — Reverb 2 is not a landed class; refused fail-closed |

The "complete-wet possible" column is **derived, not asserted**: the
extractor reads the `landed` flags of the committed leaf table
(`reports/coverage-v1/leaf-verification.json`) and records the exact basis it
used in each JSON (`landed_classes_basis`). On this branch that basis is
`{Chorus, Delay, Distortion, EQ, Reverb 1}`. Note the deliberate asymmetry:
the Reverb 2 (#58) and Phaser (#59) leaves have **merged** to `main`, but
neither PR marked its class `landed` in that table, so the ledger — not the
git log — governs and Novuo stays refused. Fail-closed in the direction that
cannot overstate coverage. A model run for Novuo is impossible here anyway:
every record is `INCOMPLETE-BLOCKED-ON-ORACLE`.

Because no reference bus exists, the RTL/model exactness cases below are
driven by **declared synthetic stimuli and parameter corners**, not by
fixture replays. That is a weaker basis than the SXT-028c canonical-fixture
replays and it is stated as such — it bounds claim (1) only.

## 2. Frozen fixed-point model

`model/effects/type-distortion/distortion_model.py` (+ freeze doc
`model/effects/type-distortion/README.md`, table generator `ws_tables.py`).
Frozen words: audio and feedback registers Q10.21 s32; drive/outgain lipol
ramps Q13.18 s32; biquad coefficients/lags/TDF2 state and halfband allpass
coefficients/state Q24.43 s64; waveshaper table words Q2.29 s32.

Per-block schedule mirrors the pinned `DistortionEffect::process` order
exactly: `bi == 0` slow-rate coefficient pass (peak-EQ targets + instantized
oversampled LP2B coefficients, the latter built at `highcut/12 − 2` so a
base-rate `sampleRateInv` yields the 4×-rate corner) → `band1` lagged TDF2 →
`dS = drive.get_target()` then `drive.set_target_smoothed` →
`outgain.set_target_smoothed(db_to_linear(gain) · ringoutMul)` →
`drive.multiply_2_blocks` → 4× loop (`L = Lin + fb·L`, optional `lp1`
nolag, `lookup_waveshape`, optional `lp2` nolag) → `hr_a` 128→64 → `hr_b`
64→32 → `outgain.multiply_2_blocks_to` → `band2`. The effect is 100 % wet
(no mix parameter, no dry path).

Declared deviations (bounded, and the [PROPOSED] budgets that would absorb
them were NOT exercised here): engine float32/double arithmetic → Q-format
(≤ 1 LSB/op); control-rate formulas evaluated in double and quantized once;
the engine's ±1e-8 denormal bias is ~0.02 LSB at Q10.21 and is therefore
not representable (fixed point has no denormals, so the bias has no
function) — a ~−160 dBFS-class DC term.

Constant inventory (DR-0012, PROPOSED): the three waveshaper rows and every
coefficient build are **re-derived from pinned construction formulas**; the
only **quoted opaque constants** are the twelve order-6 halfband allpass
coefficients, which are streamed to the RTL rather than duplicated there
(DR-0002 clause 1). `tests/test_sxt028e.py::test_ws_rom_matches_generator`
asserts the committed ROM is byte-for-byte the generator's output, so it
can never drift into being an independent copy of engine data.

**Independent cross-check of the fixed-point implementation** (NOT a
reference claim): `tools/distortion_negative_controls.py` NC-0 runs an
independent *float* structural twin written from the pinned sources and
compares it to the frozen model over 96 blocks — **max 15.2 LSB Q10.21,
residual RMS −105.24 dBFS, spectral correlation 1.000000**. This shows the
fixed-point arithmetic is not the dominant error term and that the control
apparatus has resolving power; it says nothing about the pinned engine.

## 3. Model vs pinned engine — NOT_RUN

| Case | max abs (LSB) | rms (dBFS) | spectral corr | tail | Verdict |
|---|---|---|---|---|---|
| (any fixture × any sequence) | — | — | — | — | **NOT_RUN** |

Budgets that *would* apply, unchanged from the issue and from SXT-023:
max ≤ 8,192 LSB Q10.21; rms ≤ −46 dBFS; spectral corr ≥ 0.98 —
**[PROPOSED], not frozen**; freeze gated on SXT-017 (#12). No number is
reported against them because none was measured. See F-028e-1.

Reproduce on an oracle host (everything needed is committed):

```sh
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 \
    tools/extract_distortion_inputs.py --mode oracle
# then render fixtures under SXT-012 policies (tools/render_fx_fixtures.py
# pattern) and compare the frozen model against the wet bus.
```

## 4. RTL vs frozen model — EXACT (iverilog)

`rtl/effects/type-distortion/tb_distortion.sv` +
`tools/compare_rtl_model_distortion.py` → `rtl-exactness.json`
(status **PASS**). Two instances with fully independent state; the peak-EQ
coefficient-lag recurrence and TDF2 registers, the drive ramp, the 4×
feedback/shaper loop (table lookup and both instantized LP stages), both
halfband cascades, the outgain ramp and the post-EQ are audio-rate RTL. The
control plane (drive/outgain RAW lipol targets, the feedback coefficient,
four coefficient sets, the activity/model flags) and the twelve halfband
coefficients are streamed.

Compared with exact integer equality: every per-instance output sample
(**O**), every shaper-loop tap checkpoint (**X**: the post-`lp2`
oversampled L/R word at each of the first 4 base samples × 4 oversampling
steps), every declared state checkpoint (**T**: feedback registers, both
lipol targets, both peak-EQ coefficient lags, all four TDF2 register pairs,
and all 144 halfband allpass state words per instance), and the
frozen-revision pin.

Simulator: `Icarus Verilog version 13.0 (stable) (v13_0)` (recorded verbatim
in `rtl-exactness.json.sim_version`). Cases, as recorded:

| Case | blocks | inst | O samples | X taps | T checkpoints | T fields | Verdict |
|---|---|---|---|---|---|---|---|
| `prs-dual-160` (two parameter sets, models 0 and 1) | 160 | 2 | 20,480 | 42 | 22 | 3,872 | **exact** |
| `prs-reset80-160` (core reset at block 80) | 160 | 2 | 20,480 | 42 | 22 | 3,872 | **exact** |
| `corners-deact-both` (both high-cuts deactivated, drive 24 dB, fb −0.9) | 64 | 1 | 4,096 | 9 | 5 | 880 | **exact** |
| `corners-extend-asym` (model 2, extended drive + both EQ gains) | 64 | 1 | 4,096 | 9 | 5 | 880 | **exact** |
| `corners-hard-hifb` (model 1, feedback 0.99) | 64 | 1 | 4,096 | 9 | 5 | 880 | **exact** |
| `ringout-tail-1663` (64 driven blocks + the full 1600-block ringout) | 1663 | 1 | 102,336 | 202 | 102 | 17,952 | **exact** |
| `reset-mid-tail-160-320` (fx-rebuild reset 96 blocks into the tail) | 320 | 2 | 32,768 | 68 | 36 | 6,336 | **exact** |
| **total** | | | **188,352** | **381** | **197** | **34,672** | **PASS** |

Every one of those 188,352 output samples, 381 tap checkpoints and 34,672
state-checkpoint fields matched the frozen model with integer equality, and
every case's frozen-revision pin matched (`revision_pin.ok`). A single
mismatched word anywhere is a FAIL — there is no tolerance on this leg.

RTL mutant negative controls (each must FAIL): pooled per-instance feedback
state; band1/band2 order swapped; halfband A/B polyphase branches swapped;
the waveshaper lower rail zeroed; the table lerp dropped (nearest-entry
lookup); plus a stale frozen-revision pin — **all CONTROL-OK**.

Per-instance state acceptance (issue #57): two concurrent instances with
different parameter sets *and* different waveshaper model indices keep
independent histories (`prs-dual-*`, plus
`tests/test_sxt028e.py::test_per_instance_independence`), and the pooled
mutant demonstrably FAILS. Reset/panic: `prs-reset*` bulk-resets the core
mid-render, and `reset-mid-tail-*` does the same **96 blocks into the ringout
tail** — both are exactly the engine's `suspend() == init()` fx-rebuild path
(fresh constructor state: zeroed TDF2 and halfband registers, zeroed feedback
words, re-armed `first_run`, lipol ramps back to their plain `setvars(true)`
targets). Both are exact per instance.

What the mid-tail reset case does and does not settle: it pins the
**model-side** semantics of a patch change arriving while the effect is still
ringing out — the tail restarts from constructor state rather than continuing
— and proves the RTL implements that identically. It does **not** establish
that the pinned engine behaves this way, because *mid-render patch change on
the engine side remains **BLOCKED*** by the known surgepy embedding
limitation (host-thread `loadPatch`; documented in `reports/sxt-024` §3), and
is additionally moot here because no oracle ran at all (F-028e-1). The
specified semantics are read from `DistortionEffect::init`/`suspend` and
`spawn_effect`, not measured.

## 5. Tails

**Declared tail span: `ringout_time` = 1600 blocks = 1.0667 s at 48 kHz**
(`DistortionEffect.h:48`), of which the last `ringout_end` = 320 blocks
apply the output-gain fade
`ringoutMul = limit01((1600 − ringout − 1)/320)`; the host stops calling
`process` once `ringout >= 1600` (`Effect::process_ringout`). The model
takes `ringout` as an explicit per-block control input and folds
`ringoutMul` into the outgain target at control rate.

* **Exactness over the whole declared span**: the `ringout-tail-*` RTL case
  drives 1600 ringout blocks to completion and compares every output sample
  and checkpoint with integer equality — the fade included.
* **Reset in the middle of the tail**: the `reset-mid-tail-*` case takes the
  fx-rebuild path 96 blocks into the ringout, with two instances, and is
  exact per instance (§4).
* **Dropped-tail control (NC-B)**: truncating the render 1 block into the
  ringout — inside the measured live decay — FAILS the tail-region residual
  gate (≤ −20 dB relative to the reference tail RMS). CONTROL-OK.
* **KNOWN-GAP (KG-1, recorded, not a control)**: a *late* truncation (800
  blocks into the ringout) is **not** rejected by the whole-region residual
  gate, because the tail region's RMS is dominated by the early,
  high-energy part of the decay even though the signal is still above the
  Q10.21 LSB floor at the truncation point. Same class as the late-tail
  known gap of `reports/stereo-comparator-tail-gate` (#111). What covers the
  full span instead is the integer-equality `ringout-tail-*` case above.
* Measured live decay for the NC-B parameter set (feedback 0.99, drive
  45 dB): the output stays above 1 LSB Q10.21 for **1592 of the 1600**
  ringout blocks — this effect's feedback loop does sustain across most of
  the window at high feedback, so the window is not merely nominal.

## 6. External-memory traffic and state (SXT-015/016 conventions)

`tools/distortion_buffer_report.py` → `artifacts/buffer-requirement.json`
(measured from the frozen model's own per-instance transaction counters):

* Per-instance external writable state: **0 bytes**. Distortion owns **no
  delay-line-class buffer** — no ext reads, no ext writes, 0 words/sample,
  0 MB/s. The rule "long buffers live in external WRITABLE memory, never
  flash" is **vacuously satisfied**: there is nothing long to place, and all
  processing is on-chip by construction.
* On-chip per-instance state: **190 × Q24.43 words + 6 × 32-bit words =
  1,544 B** (2 peak-EQ biquads at 5 lag + 5 target + 4 TDF2 each = 28; 2
  instantized LP biquads at 5 coefficients + 4 TDF2 each = 18; 2 halfband
  decimators at 2 ch × 2 branch × 3 stages × 6 taps = 72 words **each**,
  144 together; then 2 feedback registers and 2 lipol ramps at 2 × 32 bit
  each). The word counts and the byte total are the report's own measured
  fields (`on_chip_state`), not a restatement.
* Shared frozen ROM (not per-instance state): **3,084 words = 12,336 B**
  (3 × 1024 waveshaper words + 12 halfband coefficients).
* Compute shape recorded for SXT-016: 4× oversampling ⇒ 4 shaper
  evaluations per sample per channel, 256 oversampled biquad-sample
  operations per block, 2,304 halfband allpass stage-updates per block.
* **Fit verdict: [PENDING-SXT-016].** This section reports measured demand
  only; it is not a cost, area, timing, power or synthesis claim.

## 7. Newly-enabled presets (honest delta)

The issue's upper bound: 304 B4-scope candidates (factory 45, contributor
259), 158 strict-FX-complete
(`reports/sxt-028/leaves/SXT-028e/newly-enabled.json`). After this leaf the
per-preset support status is **unchanged: supported stays 0**. The
conjunction in `reports/coverage-v1/README.md` still fails for every carrier
at earlier gates, and this leaf adds two of its own:

* model-vs-reference is **NOT_RUN** for this class (F-028e-1);
* Distortion slots using FX model 3..7 are **out of scope** (F-028e-2).

What this leaf adds to the ledger is the `fx:Distortion` class evidence for
claim (1) only, recorded in `reports/coverage-v1/leaf-verification.json`
with `model_vs_reference: NOT_RUN`.

**Publication deliberately NOT regenerated (and why).** Only the *input*
table (`leaf-verification.json`) is updated here; the derived
`reports/coverage-v1/{coverage.json,per-preset.csv}` are left untouched.
Coverage publication is an explicit non-goal of this issue (#22), and
re-running `tools/publish_coverage.py` on `main` as of `bbfb090` already
produces a ~4,000-line diff that has nothing to do with this leaf: four
evidence pins in the table (`reports/sxt-023/EVIDENCE.md`,
`reports/sxt-024/EVIDENCE.md`, `reports/SXT-028c/EVIDENCE.md`) no longer
match the files they pin, so the tool correctly downgrades those leaves to
STALE — a pre-existing condition of the published artifact, filed as **#125**
rather than absorbed into this diff. Consequence to state plainly: the
committed `coverage.json` does not yet reflect this leaf, and nothing in this
record should be read as a coverage claim.

## 8. Follow-ups filed

* **#121 — SXT-028e-sse: Distortion SSE quad-waveshaper branch (FX models
  3..7)**: a sibling leaf, because it is a distinct algorithm with its own
  per-instance `QuadWaveshaperState`, its own drive normalization and
  DC-offset probe, and its own constant inventory. Until it lands, presets
  whose Distortion slot uses those models are refused (F-028e-2).
* **#123 — SXT-022: voice `HalfbandD2` polyphase A/B branch assignment
  disagrees with the pinned `HalfRateFilter`** (F-028e-3): filed with the
  derivation and the measured stopband reproduction; not fixed here (scope
  discipline), and the issue explicitly requires a before/after measurement
  against the committed voice fixtures before any change.
* **#125 — SXT-029/#22 apparatus: `reports/coverage-v1/` is no longer
  republishable from its committed inputs** (four stale evidence pins,
  measured at `bbfb090`): found while updating the leaf table for this leaf,
  out of scope here (see §7), filed with the reproduction, the per-pin
  OK/STALE table and a failure control.

## 9. What this record does NOT establish

- Any model-vs-reference agreement, any fidelity policy, or any frozen
  budget (SXT-017/#12). The reference leg is **NOT_RUN**, not "passing
  quietly".
- Any preset-support or musical-quality claim; no human listening has
  occurred (#8/#9 BLOCKED-on-human). Essentiality of this feature remains
  **UNVERIFIED** — no SXT-014 ablation carrier exists for it.
- FPGA/gf180mcu synthesis, place-and-route, timing, power, area or hardware
  playback; the RTL is an iverilog-simulated behavioural schedule (version
  recorded in `rtl-exactness.json`).
- Anything about FX waveshaper models 3..7, about sibling effect classes, or
  about the SXT-022 voice decimator (F-028e-3 is a report, not a fix).
- Repeatability of any engine render (none was produced).

## 10. Reproduce

```sh
# anywhere with iverilog (RTL-vs-model exactness + RTL mutant controls)
IVERILOG=iverilog python3 tools/compare_rtl_model_distortion.py

# anywhere (model-side negative controls + buffer/traffic report)
python3 tools/distortion_negative_controls.py
python3 tools/distortion_buffer_report.py

# anywhere (fail-closed extraction: graphs cross-check + oracle refusal)
python3 tools/extract_distortion_inputs.py --mode graphs
python3 tools/extract_distortion_inputs.py --mode oracle    # refuses

# unit/integrity tests
python3 -m pytest tests/test_sxt028e.py -q

# ORACLE HOST ONLY (the NOT_RUN leg of §3)
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 \
    tools/extract_distortion_inputs.py --mode oracle
```

## 11. Provenance / licensing

All files in this repository are original (Apache-2.0 per `LICENSE`).
Distortion structure is read and cited from the pinned GPL-3.0-or-later tree
(`DistortionEffect.{h,cpp}` and the shared sst machinery); no Surge source
or assets are committed. The twelve order-6 halfband allpass coefficients
are quoted as data under
`decision-records/0012-distortion-halfband-and-waveshaper-tables.md`
(PROPOSED), the SXT-028e successor to the ratified DR-0002; the waveshaper
tables are re-derived from the pinned construction formulas and are not
quoted data. No distribution-license determination has been made for
Surge-derived material.
