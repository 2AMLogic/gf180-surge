# SXT-028f evidence record — Reverb 2 (sst-effects tank reverb): frozen fixed-point model, exact RTL, per-instance state; class-scope reference leg RAN (3 screened carriers; all 3 issue-named carriers REFUSED by the determinism gate)

Branch: `feature/issue-58` · Issue: #58 (SXT-028f) · Parent: #21 (SXT-028) ·
Date: 2026-09-25

**Reference leg added 2026-10-02 (issue #126, finding F-028f-1)** on a host
with the pinned prebuilt oracle installed by `oracle/fetch-and-build.sh
--prebuilt` (per-user cache keyed by the engine commit; see §3 for the
build provenance). §3 was **BLOCKED / NOT_RUN** before that date; it now
carries a graded `fx:Reverb 2` **class** verdict. §1's temposync and
`drift_asserted` fail-closed fields are resolved for the first time in the
same change. Nothing in §4–§8 changed, **no** preset-support, coverage or
musical-quality claim is created, and **no budget was widened or frozen**.

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz,
block size 32 (`oracle/manifest.json`). Algorithm authority:
`libs/sst/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b/include/sst/effects/Reverb2.h`
(the Surge `Reverb2Effect` at this pin is a thin `SurgeSSTFXBase` wrapper
around `sst::effects::reverb2::Reverb2<SurgeFXConfig>`;
`src/common/dsp/Effect.cpp:79-80` instantiates it for `fxt_reverb2`).
Supporting pinned headers read and cited: the same sst-effects pin's
`EffectCore.h` and `effects-shared/WidthProvider.h`;
`libs/sst/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96`
`BlockInterpolators.h` and `QuadratureOscillators.h`; the engine pin's
`src/common/dsp/effects/SurgeSSTFXAdapter.h`. Read + cited; **no source,
table or asset is copied into this repository**.

**Claim discipline.** This record advances exactly two claims, kept
separate and never inferred from one another:

* **(1) the RTL matches the frozen fixed-point model exactly** (iverilog,
  demonstrated — §4).
* **(2) model-vs-pinned-engine agreement for the `fx:Reverb 2` class, on
  three screened carriers × two sequences, against the [PROPOSED] SXT-023
  budgets** (§3). This is a **class** result measured at a declared input
  boundary (the engine's own per-slot-bypass bus), **not** a complete-wet
  preset result; the budgets it is graded against remain **proposals**, so
  every verdict is marked **PENDING-FREEZE** and the freeze stays gated on
  SXT-017 (#12) and the delay-semantics finding (#16).

It advances **no** claim of kind **(3) "it sounds good"** (no human
listening; #8/#9 remain BLOCKED-on-human). It establishes no preset-support
claim, no coverage claim, no cost or fit claim, no FPGA/gf180mcu synthesis,
timing, area or hardware-playback claim, and it freezes no budget.
Coverage is reported separately from agreement, in §7: **newly-enabled
presets stays 0.**

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact (incl. dual-instance) | **PASS** — 4 cases, 77,824 output samples, 160 per-sample tank checkpoints, 6,624 state fields | `rtl-exactness.json` |
| RTL negative controls live | **PASS** — 4 injected-defect mutants + 1 stale-revision control, all CONTROL-OK, each with a liveness predicate | `rtl-exactness.json` |
| Model-side negative controls live | **PASS** — 7/7 CONTROL-OK (the issue's five required + bypass + suspend) | `negative-controls/negative-controls.json` |
| Per-instance state (two concurrent instances) | **PASS** — disjoint regions, per-instance equality, pooled-region mutant FAILS | `rtl-exactness.json`, NC-D |
| Tails (present, decaying, dropped tail FAILs) | **PASS** — model-side declared-region tail gate | NC-B, `tests/test_sxt028f.py` |
| External-memory state + traffic | **PASS** (accounting) — 14,532,608 B/instance; 46 words/sample | `artifacts/buffer-requirement.json` |
| External-memory **fit** | **[PENDING-SXT-016] / not claimed** | §6 |
| Model ↔ pinned engine, `fx:Reverb 2` **class**, vs [PROPOSED] budgets | **PASS (PENDING-FREEZE)** — 6/6 cases (3 screened carriers × 2 sequences); worst achieved max 22.0 LSB (budget ≤ 8,192), worst rms −114.3 dBFS (budget ≤ −46), worst corr 0.99999999 (budget ≥ 0.98) | §3, `artifacts/compare-*.json` |
| Reference-backed negative controls (NC-A generic, NC-B dropped tail, NC-REF-0 vacuity) | **PASS** — 18/18 CONTROL-OK against real reference audio | §3, §5, `negative-controls/reference-controls.json` |
| Fixture renders (SXT-012 policies, 3× determinism gate) | **PASS for 3 screened carriers** (18 buses, `drift_asserted: 0`); **REFUSED for all 3 issue-named carriers** | §1, §3, `artifacts/determinism-gate.json` |
| Issue-named carriers (`Grant Me…`, `Novuo`, `Harp`) | **REFUSED** — 6/6 legs fail the 3× bit-identical gate; characterised as **source-side** (all-off dry bus already unstable, 20/20 distinct) | §3 |
| `rev2_predelay` temposync | **RESOLVED** — native loader read-back, `false` (not synced) for all six carriers | §1 |
| Model ↔ pinned engine, **complete wet preset** | **NOT_RUN / not claimed** — the graded boundary is the per-slot bypass bus, not the whole chain | §3, §8 |
| Newly-enabled presets supported | **0** (honest delta) | §7 |

## 1. Inputs, applicability boundary (fail-closed), refusals

`tools/extract_reverb2_inputs.py` extracts the Reverb 2 chain inputs from
**committed pinned evidence**, not from raw `.fxp` bytes: the SXT-011
normalized graphs (`corpus/normalized/graphs.jsonl`) are the native
loader's post-migration readback at the engine pin, and the census blob
SHA-1 is re-verified against `corpus/census-v0.1/corpus-manifest.json` at
extraction time (a mismatch aborts).

Parameter order is `Reverb2.h:40-57` (`predelay, room_size, decay_time,
diffusion, buildup, modulation, lf_damping, hf_damping, width, mix`) and
every extracted value is range-checked against its declared `paramAt`
range (`Reverb2.h:152-197`); an out-of-range value is a refusal, never a
clamp. All three issue-named carriers pass that cross-check, which is
independent corroboration of the mapping:

| Preset (issue-named carrier) | slot | chain | complete-wet? |
|---|---|---|---|
| `patches_3rdparty/A.Liv/Keys/Grant Me....fxp` | send1 | Reverb 2 + Delay | **no** (fail-closed, below) |
| `patches_3rdparty/A.Liv/Leads/Novuo.fxp` | send1 | EQ + Chorus + Reverb 2 + Delay + **Distortion** | **no** — Distortion is an unlanded sibling class (SXT-028e, #57) |
| `patches_3rdparty/Aleksey Zhehanov/Strings/Harp.fxp` | global1 | EQ + Reverb 2 | **no** (fail-closed, below) |

Three further carriers were added by #126 because **all three issue-named
ones are REFUSED by the empirical 3× render gate** (§3) — the same
precedent SXT-028c set, where the issue-named presets were likewise
refused and replaced by screened deterministic ones
(`reports/SXT-028c/EVIDENCE.md` §1). They are selected from the committed
corpus ledger by `tools/screen_reverb2_carriers.py` for the topology the
declared model input boundary requires — exactly one Reverb 2 instance, in
a **global** role, in the **last** active FX slot — and then confirmed
empirically by the gate:

| Preset (screened carrier, #126) | slot | chain (active slots) | 3× gate | complete-wet? |
|---|---|---|---|---|
| `patches_3rdparty/Luna/Bells/Taco Bell.fxp` | global1 (6) | Chorus + Reverb 2 | **PASS** | yes |
| `patches_3rdparty/Jacky Ligon/Soundscapes/Moire 1.fxp` | global2 (7) | Ensemble + Delay + Tape + Reverb 2 | **PASS** | **no** — Ensemble/Tape unlanded |
| `patches_3rdparty/TNMG/Bells/Mystical Creature.fxp` | global2 (7) | Flanger + Reverb 1 + EQ + Reverb 2 | **PASS** | **no** — Flanger unlanded |

The unlanded siblings in two of those chains do **not** weaken §3: the
model is fed the engine's own per-slot-bypass bus, so no sibling model is
required and no complete-wet claim is made for them (§3, §8).

**Screen result (`artifacts/carrier-screen.json`; inventory and
prioritisation only — NOT a support or coverage claim).** 49 of the 708
Reverb 2 carriers pass the static stage. Of those 49, **only 10 pass the
empirical 3× render gate** on `seq-poly-8-v1`; **39 are REFUSED for
nondeterminism.** The static screen therefore cannot replace the render
gate — the same finding SXT-028c recorded, reproduced here: all three
issue-named carriers pass every static criterion and are still refused by
the gate. The 10 that pass are not a coverage number; three of them are
the carriers used in §3 and the remaining seven are untested here.

Fail-closed reasons recorded in every emitted record
(`model/effects/fx_inputs/type-reverb 2-*.json`):

* **`rev2_predelay` temposync — RESOLVED 2026-10-02 (#126).** The
  per-parameter temposync flag is not part of the SXT-011 normalized graph,
  and the `.fxp` bytes are external GPL assets this repository
  deliberately does not carry, so without the oracle the record emitted
  `ts_predelay: null` and `Reverb2Params` **raised** rather than default it
  to "not synced". It is now read back from the **native loader** —
  `SurgeSynthesizer::getTempoSync` on `fx[slot].p[0]` after `loadPatch`,
  i.e. the authoritative post-migration state, never an `.fxp` byte
  reading — by `tools/extract_reverb2_inputs.py --oracle`. Result:
  **`false` (not synced) for all six carriers**, recorded with its
  provenance string in each record's `temposync_source`. The same pass
  reads back the master volume (`volume_f`, the de-amp constant at the
  model boundary) and **cross-checks all ten Reverb 2 parameter values**
  against the committed normalized graph; a mismatch beyond 1e-6 is a
  refusal, never a silent preference for one source. All six carriers
  agree, which is independent corroboration of the SXT-011 graph.
* **Determinism drift: `0` only where the gate actually passed.** The
  SXT-012 3× bit-identical render gate ran on the oracle host (§3).
  `drift_asserted: 0` for the three screened carriers; **`null` (NOT_RUN /
  REFUSED, never a pass) for all three issue-named carriers**, each
  carrying the measured divergence in its `determinism_gate.measured`
  block. (SXT-028c had independently recorded `Novuo.fxp` as REFUSED at
  extraction for drift ≠ 0 — `reports/SXT-028c/EVIDENCE.md` §1 — and the
  render gate now confirms that at the engine level.)
* Unlanded sibling FX classes in the chain, non-default `fx_bypass`,
  non-zero `fx_disable`, and any modulation route whose destination names
  an FX parameter each refuse the preset. `complete_wet_render_possible`
  therefore stays `false` for five of the six carriers and is **not** what
  §3 grades — §3's `reference_leg.usable` flag is a separate, narrower
  record (class scope at the per-slot-bypass boundary).

Corpus inventory (`artifacts/carrier-ledger.json`, **inventory and
prioritisation only — NOT a support or coverage claim**, AGENTS.md): 708
presets carry an active Reverb 2 slot; **47 carry two or more Reverb 2
instances** (so the per-instance-state acceptance has real carriers, not
only synthetic ones); 130 are strict-FX-complete against the currently
landed class set; 300 carry at least one FX-destination modulation route
and are therefore outside the frozen scope.

## 2. Frozen fixed-point model

`model/effects/type-reverb 2/reverb2_model.py` (+ the freeze document
`model/effects/type-reverb 2/README.md`). Frozen words: audio and every
external buffer word Q10.21 s32; the `widthS`/`mix` ramps and the four tap
gains Q13.18 s32; the six coefficient ramps, the eight one-pole registers
and the LFO Q24.43 s64. The per-sample schedule mirrors
`Reverb2::processBlock` exactly: mono input fold → predelay ring
(read-before-write) → four input allpasses at `diffusion.v` → per tank
block {`x += in`, two allpasses at `buildup.v`, one-pole lowpass at
`clamp(hf.v, 0.01, 0.99)`, one-pole highpass at `clamp(lf.v, 0.01, 0.99)`,
`(int)(mod.v·lfos[b]·256)`, delay (two output taps, then the sub-sample
interpolated recirculation read, then the write), tap MACs, `x *= decay.v`}
→ `_state = x` → ramp steps → mid/side width → mix crossfade.

Two pinned behaviours are reproduced deliberately and are load-bearing:

* **The LF-damping ramp is never stepped** (`Reverb2.h:478-483` steps every
  other ramp). Its `.v` therefore holds the *previous* block's target for
  the whole block. `tests/test_sxt028f.py::test_lf_damping_ramp_is_never_stepped`
  pins it against the HF ramp (identical class, identical code path, but
  stepped), and the RTL control `mutant-lfdamp` steps it and FAILs.
* **Suspend does not clear the tank.** `suspendProcessing()` is
  `initialize()` is `setvars(true)`, which only rebuilds the tap gains and
  calls `calc_size(1.f)`; only the constructor zeroes buffers, ramps and
  `_state`. `Reverb2Model.suspend()` / `.initialize()` separate the two
  paths and NC-G flags a clearing mutant.

Declared deviations (bounded; they are absorbed by the model-vs-reference
budgets, which this record does **not** measure): engine float32 audio
arithmetic → Q10.21 (≤ 1 LSB-class per op, the same class the landed
Delay/EQ/Reverb1/Chorus models declare); the coefficient ramps, one-pole
registers and LFO held Q24.43 where the engine holds float32, with the
`/32` ramp increment rounded once; the four tap MACs accumulate exactly and
round once where the engine rounds each product to float32; the two
halvings truncate toward zero (the repo's frozen convention); control-rate
transcendentals evaluated in double and quantised once, with explicit
float32 rounding wherever the engine stores a `float`.

Constant inventory: **no opaque designed constants.** Every constant is an
engine literal cited to its pinned line (`0.5508`, `db60 = 0.001`, the
tap-time / allpass / delay millisecond tables, the four tap-gain literals,
the `0.7`/`0.8`/`0.2` parameter scalings, the `[0.01, 0.99]` damping
clamps, `ω = 2π·2⁻²/sr`) or a formula re-derivation (`db_to_linear`, the
0.25/0.75 `lipol_sse` smoothing). No successor to DR-0003 is required.

### Declared allocation profile (and why the bench profile is legal)

| Profile | predelay | allpass ×12 | delay ×4 | words/instance |
|---|---|---|---|---|
| `ENGINE_PROFILE` (default, what §6 accounts) | 1,536,000 | 131,072 | 131,072 | 3,633,152 |
| `HARNESS_PROFILE` (RTL bench only) | 16,384 | 4,096 | 16,384 | 131,072 |

The reduced bench profile exists so two instances fit the simulator. It is
legal **only** because (a) the model **refuses** (`ProfileRefusal`) any
configuration whose ring would alias a live tap — no silent reduction —
and (b) `test_alloc_profile_equivalence` runs the same stimulus under both
profiles and requires **identical output, tank state and transaction
counts**. Both sides of every exactness comparison run the same profile.

## 3. Model vs pinned engine — **PASS (PENDING-FREEZE)**, `fx:Reverb 2` class, 3 screened carriers

**Status: RAN 2026-10-02** (issue #126, finding F-028f-1). Was BLOCKED /
NOT_RUN until then; the oracle is now installable on any worker by
`oracle/fetch-and-build.sh --prebuilt` (#232), which verifies a sha256 and
installs per-user under `~/.cache/gf180-surge-oracle/<engine-commit>/`.

### 3.0 Environment and provenance

Recorded in every artifact's `engine` block (`artifacts/determinism-gate.json`,
each `fixtures/*.json`):

| Field | Value |
|---|---|
| `engine_commit` | `58914e59c608ed4384ba6002e44c3465c58b2e71` (the SXT-010 pin) |
| `engine_version_string` | `1.4.HEAD.58914e59c` |
| `sample_rate` / `block_size_samples` | 48000 / 32 |
| `tempo_bpm` | 120 (pinned harness tempo; the transport is never changed) |
| `surgepy_module` | `surgepy.cpython-311-x86_64-linux-gnu.so` |

### 3.1 Reference-vs-reference repeatability (the 3× gate) — and what it REFUSED

`tools/render_reverb2_fixtures.py` inherits the SXT-012/023 fixture policy
from `tools/render_fx_fixtures.py` (fresh engine instance per bus,
census-blob-verified load, controller reset, 0.25 s settle,
block-quantized scheduling, identical tails, all-off dry bus with
read-back). Three legs per carrier × sequence, **tails included, nothing
truncated, faded or normalized**:

* **ORIGINAL (`-wet`)** — the preset's unmodified chain. This is the
  reference every number below is graded against and it is **never
  modified by the bypass legs** (AGENTS.md: "bypass tests must retain the
  unmodified wet reference").
* **PER-SLOT BYPASS (`-bypass-fx<slot>`)** — one render with **only** that
  Reverb 2 slot's type set to `Off`; every other slot keeps the preset's
  own value; read-back verified.
* **ALL-OFF DRY (`-dry`)** — all 16 FX-slot types `Off`, read-back
  verified.

Every committed bus is rendered **3× in fresh instances and must be
bit-identical (sha256)** or the fixture is REFUSED and nothing is
committed. Result: **18 buses committed across 3 carriers × 2 sequences,
all `bit_identical: true`, `drift_asserted: 0`.**

**Gate liveness (positive control).** A gate that refuses everything is
indistinguishable from a broken harness, so three SXT-028c carriers whose
wet sha256 is already committed are re-derived through this harness: all
three pass the 3× gate **and reproduce the committed hash byte-for-byte**
(`fmcombo`, `fmtwang2`, `alienappears` — `positive_control` rows). The
refusals below are therefore a property of the carriers, not of the host.

**All three issue-named carriers are REFUSED** (6/6 legs). Measured
divergence across the three repeats, written into the gate record rather
than paraphrased:

| Carrier | sequence | max abs divergence | peak abs | frames differing |
|---|---|---|---|---|
| `Grant Me….fxp` | `seq-notes-coverage-v1` | 1.811e−01 | 1.692e−01 | 273,600 / 273,600 |
| `Grant Me….fxp` | `seq-poly-8-v1` | 9.513e−02 | 2.362e−01 | 177,600 / 177,600 |
| `Novuo.fxp` | `seq-notes-coverage-v1` | 1.881e−01 | 4.220e−01 | 273,596 / 273,600 |
| `Novuo.fxp` | `seq-poly-8-v1` | 1.690e−01 | 4.095e−01 | 177,599 / 177,600 |
| `Harp.fxp` | `seq-notes-coverage-v1` | 7.426e−03 | 4.632e−01 | 142,040 / 273,600 |
| `Harp.fxp` | `seq-poly-8-v1` | 3.242e−03 | 3.302e−01 | 30,537 / 177,600 |

(These are run-to-run magnitudes, not stable alternatives: an independent
re-run of the whole gate produced a different hash triple for each leg.)

**The refusal is characterised, not merely asserted.** The interleaved
stress screen (`--stress 20`: 20 single renders per bus, each preceded by a
render of an RNG-using preset in the same process) shows all three named
carriers produce **20 distinct buffers out of 20 on the ALL-OFF DRY bus**.
Their nondeterminism therefore sits in the **voice path, upstream of every
FX slot** — it is a property of those presets, **not** of `fx:Reverb 2`,
and no choice of effect model could make them reproducible. The same
screen shows the three screened carriers stable on both buses (1 distinct
buffer in 20) and keeps a deliberately **bimodal** counter-example,
`Luna/MPE/Lap Harp.fxp`, which passes a 3× gate much of the time and still
settles on one of two distinct **wet** buffers while its dry bus stays
stable (FX-side). That control is why a single 3× PASS is recorded as
repeatability-under-this-environment and **never** as a determinism claim
on its own; it is intermittent by construction, so the test asserts the
bimodality was *observed*, not that it recurs on every sequence of every
run.

### 3.2 Declared model input boundary (why this is a CLASS result)

`model/effects/run_reverb2_model.py`. For a Reverb 2 that is the **last
active** FX slot in a **global** role:

```
wet    = clip8( A · Reverb2(X) )     the ORIGINAL unmodified chain
bypass = clip8( A · X )              the same chain, only that slot Off
model  = A · Reverb2Model( quantize_Q10.21( bypass / A ) )
```

with `A = db_to_linear(volume_f)` the read-back master amplitude. Since
nothing downstream of the slot differs between the two legs, `bypass` is
exactly the signal the engine feeds the Reverb 2, so what is graded is the
**`fx:Reverb 2` class** and not a stack of sibling models. Any other
topology is **REFUSED** rather than approximated — including the
issue-named `Novuo` carrier, whose Reverb 2 sits in a send slot with an
unlanded Distortion downstream. The model is run through the same 375-block
(0.25 s) silent settle as the engine side, so ramps, LFO and tank state
evolve identically before the first scheduled event. Declared boundary
error, absorbed by the budgets and never hidden: one Q10.21 round-half-up
after the de-amp, ≤ ½ LSB (≈ −132 dBFS class).

### 3.3 Achieved agreement (not tuned) vs the [PROPOSED] SXT-023 budgets

`tools/compare_reverb2_reference.py` → `artifacts/compare-<slug>__<seq>.json`.
No normalization, no time-warping, no reference switching, no per-patch
engine switching; raw per-sample differences at native level in Q10.21 LSB
(1 LSB = 2⁻²¹ ≈ 4.77e−7), plus the shared full-scale log-floor spectral
correlation (`fs-log-floor-v2`, issue #110). Values below are the **mono**
channel (the worst-case grading channel); per-channel L/R rows are in each
artifact. Budgets: **max ≤ 8,192 LSB · rms ≤ −46 dBFS · corr ≥ 0.98.**

| Carrier | sequence | max abs diff (LSB) | rms diff (dBFS) | spectral corr | best shift | tail gate | verdict |
|---|---|---|---|---|---|---|---|
| `tacobell` | `seq-notes-coverage-v1` | 9.000 | −118.663 | 0.999999996 | 0 | ok | PASS |
| `tacobell` | `seq-poly-8-v1` | 22.000 | −114.325 | 0.999999997 | 0 | ok | PASS |
| `moire1` | `seq-notes-coverage-v1` | 1.665 | −130.337 | 0.999999997 | 0 | ok | PASS |
| `moire1` | `seq-poly-8-v1` | 2.630 | −129.228 | 0.999999997 | 0 | ok | PASS |
| `mystical` | `seq-notes-coverage-v1` | 2.875 | −126.422 | 0.999999994 | 0 | ok | PASS |
| `mystical` | `seq-poly-8-v1` | 4.000 | −126.813 | 0.999999997 | 0 | ok | PASS |

Worst case over all six: **22.0 LSB** (0.27 % of the proposed max),
**−114.3 dBFS** (68.3 dB of margin), **corr 0.99999999**. `best_shift` is
0 in every case, i.e. the agreement is at zero lag and was not obtained by
sliding the renders.

**Every verdict is marked `PASS (PENDING-FREEZE)`** in its artifact: the
budgets and the wet-path tail-region gate are **proposals, not frozen
policy**, and the freeze is gated on SXT-017 (#12) and the delay-semantics
finding (#16). No budget was tuned to a measurement, and the comparator
refuses (NO_VERDICT, exit 2) rather than grade when the sidecar does not
declare a passing 3× gate, when the model render was produced against a
different wet reference, or when the tail region is not declared.

### 3.4 Wet tail-region gate (#93/#100)

The tail region is read from each fixture sidecar's **declared** values
(`wet.last_event_sample` + `render.tail_s` at `render.sample_rate`) —
never hard-coded, never inferred from silence; a missing or non-describing
sidecar is a refusal. Both legs of the stereo gate pass for all six cases
(mono and per-channel L/R): the tail RMS difference relative to the
reference tail is **at worst −85.97 dB** (budget −20 dB; `mystical` /
`seq-poly-8-v1`, L), and the 50-window decay curve deviates by at most
**0.0428 dB** (budget 1.0 dB; `tacobell`, L) with 0 windows over budget,
graded against the **declared** −100 dBFS floor rather than an inferred
one. The reference tail carries real energy in every case
(`tail_present`), so the gate is not passing on silence.

### 3.5 Reference-backed negative controls

`tools/reverb2_reference_controls.py` →
`negative-controls/reference-controls.json`. The §5 controls grade
model-vs-model; these re-run the two the issue names **against the real
pinned-engine reference bundle**, driven through the *same*
`run_reverb2_model.prepare` boundary as the graded model render itself, on
all 6 cases:

| Control | Result (6/6 cases) |
|---|---|
| **NC-REF-0** vacuity — the engine's own per-slot-bypass bus graded as if it were the model | **CONTROL-OK** — FAILS the budgets everywhere (max 82,915 – 545,336 LSB; rms −26.5 … −42.2 dBFS). Removing the Reverb 2 is detected, so the budgets are resolving the Reverb 2's own contribution and the PASS in §3.3 is **not vacuous** |
| **NC-A-REF** generic substitute (four feedback combs; no allpass diffusion, no damping, no predelay, no sub-sample read), **ADAPTED** | **CONTROL-OK** — still FAILS on real reference audio in all 6 cases: **max and rms fail in every case** (max 43,626 – 318,602 LSB vs 8,192; rms −30.3 … −41.2 dBFS vs −46), and corr additionally fails in 4 of 6 (0.906 – 0.958; it stays above 0.98 on the two `tacobell` cases, which is why the budget is a conjunction). A convenient generic reverb does **not** pass once a real reference is present, so the budgets are discriminating; **ADAPTED ≠ supported** |
| **NC-B-REF** dropped tail — the committed model render truncated at the declared tail offset, and separately zeroed across the declared tail region | **CONTROL-OK** — both FAIL the declared-region stereo tail gate that the full render passes, with the full-tail baseline asserted live first |

Had NC-A passed here, the finding would have been **the budgets, not the
leaf** (the issue's own stop clause). It did not: the generic's rms misses
by 4.8 – 15.7 dB and its max by 5–39×.

### 3.6 What §3 does not cover

* **Complete-wet preset agreement: NOT_RUN.** The graded boundary is the
  per-slot bypass bus, so sibling classes in these chains (Ensemble, Tape,
  Flanger, Reverb 1 …) are supplied by the engine, not modelled. No
  complete-wet, support or coverage claim follows from §3 — see §7, §8.
* **The three issue-named carriers carry no agreement number at all**
  (REFUSED at §3.1; no fixture and no `compare-*.json` exists for them,
  and `tests/test_sxt028f.py` asserts that absence).
* Mid-render patch-change/reset on the engine side stays BLOCKED by the
  known surgepy embedding limitation documented in
  `reports/sxt-024/EVIDENCE.md` §3. Reset semantics are exercised exactly
  on the RTL side (`prs-reset48-128` = bulk clear + constructor reset, the
  engine's fx-rebuild path) and the distinct *suspend* semantics are
  pinned model-side (§2, NC-G).

**Stop/escalate (per the issue's own clause):** no acceptance rule was
weakened and no budget widened to produce this result. The one place the
issue's exact inputs could not be honoured — the three named carriers — is
recorded as a REFUSAL with its measurement and its cause, not worked
around; see §9 F-028f-3 for the bounded follow-up.

## 4. RTL vs frozen model — **EXACT** (iverilog 13.0)

`rtl/effects/type-reverb 2/tb_reverb2.sv` +
`tools/compare_rtl_model_reverb2.py` → `rtl-exactness.json`
(status **PASS**, model revision `1a20c239…`). Two instances behind
disjoint external regions. Audio-rate in the RTL: the six lipol
recurrences (including the pinned "LF never steps" quirk), the LFO
magic-circle recurrence, the predelay ring, twelve allpass rings, four
delay rings with the sub-sample modulated read, eight one-pole filters, the
modulation truncation, the four tap MACs, the decay multiply, the width
matrix and the mix crossfade. Control-plane (streamed, declared in the
model README): six ramp targets, the LFO `dr`/`di` and its control-rate
renormalisation constant, the `widthS`/`mix` RAW targets, eight tap times,
twelve allpass lengths, four delay lengths, the predelay tap.

Compared with **integer equality**: every per-instance output sample (O);
every per-sample tank checkpoint (X: post-input-allpass signal, then per
tank block the modulation integer and both output taps, then the tank
accumulator — four samples per captured block); every declared state
checkpoint (T: all ring indices, configured lengths and tap times, the
eight one-pole registers, the tank, all six ramp v/target pairs, the LFO
`(r, i)`, the `widthS`/`mix` targets, the predelay tap, the three
per-region additive hashes and the per-instance external read/write
counters); and the frozen-revision pin.

| Case | Blocks | Inst | Stimulus | Result |
|---|---|---|---|---|
| `prs-dual-128` | 128 | 2 | PRS, serially chained, disjoint regions | **EXACT** |
| `prs-reset48-128` | 128 | 2 | same + bulk clear and constructor reset at block 48 | **EXACT** |
| `prs-corners-96` | 96 | 2 | parameter corners (min room / zero modulation / bypassed mix / full damping vs. large room / full modulation / no damping) | **EXACT** |
| `prs-sweep-256` | 256 | 2 | block-rate parameter sweep (the only class in which the coefficient ramps carry a non-zero increment) | **EXACT** |

Totals: 77,824 output samples, 160 per-sample tank checkpoints, 92 state
checkpoints, 6,624 state fields — all equal, zero mismatches.

RTL mutant negative controls (each **must** FAIL, and each carries a
*liveness predicate* so a control the stimulus never exercises is reported
`CONTROL-VACUOUS`, never banked as a pass):

| Mutant | Defect | Liveness predicate | Result |
|---|---|---|---|
| `mutant-shared` | the two instances' external regions pooled into one | always live | **CONTROL-OK** |
| `mutant-lfdamp` | the LF-damping ramp is stepped per sample | ramp increment ≠ 0 (measured 1.24e9 Q24.43) | **CONTROL-OK** |
| `mutant-modtrunc` | the modulation `(int)` cast rounds instead of truncating toward zero | 65,160 samples with a non-zero sub-sample fraction | **CONTROL-OK** |
| `mutant-tapgain` | tap gain 1 perturbed by one Q13.18 LSB | all eight output taps read non-zero data | **CONTROL-OK** |
| `control-stale-revision` | trace pinned to a different model revision | always live | **CONTROL-OK** (refused, never PASS) |

The liveness record is committed as `mutant_carrier_exercise` in
`rtl-exactness.json`. It is not decoration: the first run of this harness
reported `mutant-lfdamp` and `mutant-tapgain` as **CONTROL-BROKEN** because
a constant-parameter, 64-block stimulus never moved a ramp and never let a
tap read non-zero data. The carrier case was lengthened and a parameter
sweep added until both predicates held.

**Per-instance state acceptance (issue #58):** two concurrent instances
keep independent histories — disjoint external regions, per-instance
integer equality on outputs and on the three per-region hashes, and the
pooled-region mutant demonstrably FAILS the dual-instance check. 47 corpus
presets carry two or more Reverb 2 slots (§1), so the acceptance is not
limited to synthetic dual-slot cases; those carriers cannot be *rendered*
here only because the reference leg is blocked (§3).

## 5. Negative controls (model-side; each must FAIL its target check)

`tools/reverb2_negative_controls.py` → `negative-controls/negative-controls.json`.
Baseline sanity first (the unmutated model passes its own checks), then:

| Control | Result |
|---|---|
| **NC-A** generic substitute (four feedback combs, no allpass diffusion, no damping, no predelay, no sub-sample read) | **CONTROL-OK** — FAILs the [PROPOSED] agreement budgets; labelled **ADAPTED**, excluded from original-preset coverage |
| **NC-B** dropped tail (render truncated at the tail offset, and tail region zeroed) | **CONTROL-OK** — both FAIL the declared-region tail gate that the full render passes |
| **NC-C** wrong order (two serial instances A→B vs B→A) | **CONTROL-OK** — not bit-identical and outside the budgets |
| **NC-D** shared instead of per-instance state (pooled external region) | **CONTROL-OK** — instance A's state and history change |
| **NC-E** stale stub (frozen-revision pin) | **CONTROL-OK** — refused by the exactness harness and by the test suite |
| **NC-F** bypass transparency (mix = 0 exact; injected mix leak detected) | **CONTROL-OK** |
| **NC-G** suspend must not clear the tank (pinned semantics) | **CONTROL-OK** — a clearing mutant is flagged |

**Claim scope of §5, stated in the artifact itself:** every comparison in
this section is *model-vs-model* — the frozen model is its own reference.
These controls show the checks and the budget thresholds are live and that
the listed defects are detectable. On their own they establish nothing
about agreement with the pinned engine and no sound claim. **NC-A and
NC-B are additionally re-run against the real pinned-engine reference
bundle in §3.5** (`negative-controls/reference-controls.json`), where both
still FAIL the checks they target, alongside an NC-REF-0 vacuity control
showing the §3.3 PASS is not vacuous. NC-C/D/E/F/G remain model-side only.

## 6. External memory and traffic (SXT-015/016 conventions)

`tools/reverb2_buffer_report.py` → `artifacts/buffer-requirement.json`,
measured from the frozen model's own per-instance transaction counters and
cross-checked against the pinned structure:

* Per-instance external **writable** state: predelay 1,536,000 words +
  12 allpass rings × 131,072 + 4 delay rings × 131,072 = **3,633,152 ×
  32-bit words = 14,532,608 B = 13.859 MiB**. This confirms the SXT-015
  pinned entry for Reverb 2 **exactly**. It is by a wide margin the largest
  per-instance external resident of the effect classes landed so far
  (Chorus 1.00 MiB, Reverb 1 2.13 MiB, Delay 2.00 MiB).
* Traffic: **29 reads + 17 writes = 46 words/sample = 184 B/sample =
  8.83 MB/s per instance** at 48 kHz (1 predelay read/write; 12 allpass
  read/write; per delay 2 output taps + 2 interpolation reads + 1 write).
  Measured counters match the structural derivation exactly.
* On-chip small state ≈ **295 B/instance** (six ramps, eight one-pole
  registers, the LFO, the tank accumulator, two `lipol_sse` ramps, ring
  indices, configured lengths and tap times, counters and hashes). The wide
  products are combinational; the tap gains are frozen ROM.
* Long buffers are external **WRITABLE** memory; flash is never writable
  delay memory; all processing stays in-chip (plan section 3).

**Finding F-028f-2 (recorded, not silently fixed): the SXT-015 per-sample
traffic row for Reverb 2 is an over-estimate.** The shared table
(`model/resources/fx_classes.py`) carries 40 reads / 18 writes; the
structure measured here is 29 reads / 17 writes. Editing that table is
SXT-015/016 scope, not this leaf's, and over-estimating traffic is
*conservative* for a budget, so no SXT-016/017 result is invalidated by
the discrepancy. It is recorded in `sxt015_reconciliation`
(`traffic_agreement: false`) and asserted by the test suite so it stays
visible rather than quietly reconciled.

> **Disposition (2026-09-27, issue #127): DELIBERATELY RETAINED, not
> corrected — routed to #12.** The reconciliation was taken up under
> issue #127. Re-deriving `reports/sxt-017/cost-closure.json` with the
> measured 29 / 17 moves 4 of its 120 grid cells' `ext_bandwidth_fit`
> column from `EXCEEDS` to `within` (B4-broad and R0-ceiling-reference at
> 192 MHz / M18 + M32 / E1). A previously-failing check reading pass inside
> the artifact that #12's escalated profile-v1 freeze decides is exactly
> what #127's stop/escalate clause says not to bank, so the shared row is
> **held** at the conservative 40 / 18 pending #12, and the hold is now
> *declared* rather than merely observed:
> `model/resources/fx_classes.py` `_RETAINED_OVER_ESTIMATE_TX["reverb2"]`
> carries the measured figure, this artifact, the numeric cost of
> correcting it, and the unblocking condition. `sxt015_reconciliation`
> gained `traffic_direction` and
> `traffic_over_estimate_is_deliberate: true` plus a
> `traffic_retention_record`, and is phrased from the **live** table values
> so it cannot outlive the state it describes. Full before/after,
> attribution control, and the escalation:
> `reports/sxt-017/EVIDENCE.md` §10 and `reports/sxt-015/EVIDENCE.md` §7.
> Nothing in **this** leaf's own numbers changed: state 14,532,608 B and
> traffic 29 / 17 are as measured above.

**External-memory fit: [PENDING-SXT-016], NOT CLAIMED.**
`cyc_fxreverb2_frame` is still a placeholder
(`model/resources/params.py`), and SXT-017 profile v1 is **not frozen**
(#12: PR #109's cost closure found no candidate bundle meeting the budget
goal at any measured corner, STOP/ESCALATE fired, routed to an operator
decision). This leaf therefore supplies the residency and traffic inputs
that the freeze needs and makes **no** fit claim — exactly the disposition
the issue's SXT-017 callout requires.

## 7. Newly-enabled presets (honest delta)

**Supported stays 0 — including after §3.** Coverage is reported here
separately from agreement, and a PASS in §3 does not move it. The
conjunction in `reports/coverage-v1/README.md` still fails for every
carrier at other gates: the §3 result is **class** scope at the per-slot
bypass boundary and not a complete-wet preset result, the fidelity freeze
(#12) is open and escalated so the budgets §3 grades against are still
proposals, sibling FX classes in these chains are unlanded (Distortion
SXT-028e in `Novuo`; Ensemble/Tape in `moire1`; Flanger in `mystical`), the
voice stage is incomplete, and listening is BLOCKED-on-human (#8/#9) — **no
human listening has occurred for any carrier in this record.** The three
issue-named carriers additionally carry no reference result at all (§3.1).

What this leaf adds is the `fx:Reverb 2` **class** evidence of §3, §4 and
§6 — model-vs-engine agreement at a declared boundary, RTL-vs-model
exactness, and the external-memory accounting — plus the fail-closed input
records of §1. The issue's B4-scope upper bound (232 candidates) and the
708-carrier inventory of §1 are **not** support claims, and neither are
the six graded cases of §3.3.

## 8. What this record does NOT establish

- **Any frozen fidelity result.** §3 reports *achieved* numbers against
  **[PROPOSED]** budgets and is marked PENDING-FREEZE throughout; the
  freeze itself is SXT-017/#12's, escalated to an operator.
- **Any complete-wet preset agreement result** (§3.6): the graded boundary
  is the engine's per-slot bypass bus, so sibling classes in those chains
  are supplied by the engine rather than modelled.
- **Any reference result for the three issue-named carriers**
  (`Grant Me…`, `Novuo`, `Harp`) — all six legs are REFUSED by the 3×
  determinism gate (§3.1) and nothing is committed for them.
- Any preset-support, coverage, or musical-quality claim; **no human
  listening has occurred** (#8/#9), and six passing numeric comparisons
  establish nothing about how anything sounds. Essentiality remains
  UNVERIFIED — the issue records no SXT-014 ablation carrier for this
  algorithm.
- Any cost or fit claim: `cyc_fxreverb2_frame` is unpriced
  [PENDING-SXT-016].
- FPGA/gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware playback. The RTL here is an **iverilog-simulated behavioural
  schedule**, version recorded in `rtl-exactness.json`; it is not
  synthesised and no synthesis claim is implied.
- Anything about sibling effect classes (Distortion SXT-028e, Conditioner
  SXT-028b, …), or about the open SXT-023 delay-semantics finding (#16).
- **General repeatability of engine renders.** §3.1 establishes
  reference-vs-reference repeatability **for the committed buses, on this
  host, under this environment** — nothing wider. The `Lap Harp`
  counter-example shows a 3× PASS can be intermittent, so no carrier
  outside the committed set is claimed reproducible.
- Hardware capture alignment (none exists).

## 9. Bounded gaps and follow-up

1. **F-028f-1 — oracle-host reference leg. CLOSED 2026-10-02 (issue
   #126).** All of it ran on a worker with the prebuilt pinned oracle
   (#232): the `rev2_predelay` temposync read-back for all six carriers
   (§1), the SXT-012 fixture renders with tails under the 3× bit-identical
   gate (§3.1), the drift assertion, the model-vs-engine comparison against
   the [PROPOSED] budgets with the declared-region wet tail gate
   (§3.3/§3.4), and the reference-backed NC-A/NC-B/NC-REF-0 controls
   (§3.5). Residual, newly-opened gap: F-028f-3 below.
2. **F-028f-2 — SXT-015 traffic row** (§6): 40/18 vs the measured 29/17,
   state bytes agree exactly. **Filed as #127**, routed to SXT-015/016
   scope. **DISPOSITIONED 2026-09-27 (issue #127): retained deliberately,
   correction routed to #12.** The shared row is held at the conservative
   40/18 because re-deriving it moves four SXT-017 `ext_bandwidth_fit`
   cells `EXCEEDS` → `within` inside the record #12's escalated freeze
   decides; the hold is declared in
   `model/resources/fx_classes.py` `_RETAINED_OVER_ESTIMATE_TX`, surfaced in
   `sxt015_reconciliation.traffic_retention_record`, and asserted by
   `tests/test_sxt028f.py::test_buffer_requirement_record` plus
   `tests/test_sxt015_fx_classes.py`. Those assertions now pin the
   *disposition* (declared, conservative, with an unblocking condition) and
   go green either way, so landing the correction after the #12 decision
   needs no test rewrite. See §6 and `reports/sxt-017/EVIDENCE.md` §10.
3. **F-028f-3 — SXT-012 fixture policy for source-nondeterministic
   presets (OPEN).** All three issue-named carriers are REFUSED by the 3×
   gate, and the cause is upstream of every FX slot: their **all-off dry**
   bus is already unstable (20/20 distinct buffers under the stress
   screen). It is not rare — of the 49 statically-eligible Reverb 2
   carriers, only 10 pass the render gate (§1). SXT-028c hit the same wall
   and substituted screened carriers; SXT-028f has now done the same, so
   the precedent is being re-established leaf by leaf instead of decided
   once. **Filed as #310**, which asks for the policy decision plus a
   diagnostic of *what* varies in the voice path, and explicitly forbids
   widening the gate or counting a nondeterministic preset toward
   coverage. **Blocks:** any complete-wet or support claim for
   `Grant Me…`, `Novuo` and `Harp`. **Does not block:** §3's class-scope
   result on the screened carriers.

## 10. Reproduce

```sh
# anywhere with iverilog (RTL-vs-model exactness + RTL mutant controls)
IVERILOG=iverilog python3 tools/compare_rtl_model_reverb2.py     # ~3 min

# anywhere (model-side controls, buffer report, fail-closed extraction)
python3 tools/reverb2_negative_controls.py
python3 tools/reverb2_buffer_report.py
python3 tools/extract_reverb2_inputs.py --scan

# unit / integrity tests
python3 -m pytest tests/test_sxt028f.py -q
```

The §3 reference leg needs the pinned oracle. On any host:

```sh
./oracle/fetch-and-build.sh --prebuilt        # prints the three exports
export ORACLE_SURGE_DIR=... ORACLE_PYTHON=... LD_LIBRARY_PATH=...

# 1. fixture bundles + the 3x gate, its positive control and the stress
#    screen (~6 min; writes artifacts/determinism-gate.json and
#    artifacts/render-refusals.txt). --stress 20 is REQUIRED for the
#    committed record: it produces the flake and named-carrier rows.
"$ORACLE_PYTHON" tools/render_reverb2_fixtures.py --stress 20

# 2. temposync / master-volume read-back + fold in the gate record
"$ORACLE_PYTHON" tools/extract_reverb2_inputs.py --oracle

# 3. the frozen model over each reference bundle, then the comparison
for s in tacobell moire1 mystical; do
  for q in seq-notes-coverage-v1 seq-poly-8-v1; do
    python3 model/effects/run_reverb2_model.py --slug "$s" --seq "$q"
    python3 tools/compare_reverb2_reference.py --slug "$s" --seq "$q"
  done
done

# 4. the reference-backed negative controls (exits non-zero if any
#    control stops failing the check it targets)
python3 tools/reverb2_reference_controls.py

# optional: re-derive the deterministic-carrier screen of §1 (~1 min)
"$ORACLE_PYTHON" tools/screen_reverb2_carriers.py --render-gate
```

Steps 3 and 4 need no oracle once the bundles exist — they read the
committed fixtures.

## 11. Provenance / licensing

All files in this repository are original (Apache-2.0 per `LICENSE`). The
Reverb 2 structure was read and cited from the pinned GPL-3.0-or-later
`sst-effects`, `sst-basic-blocks` and Surge trees, which stay external; no
Surge source, tables, presets or assets are committed here, and no preset
payload is read by any tool in this leaf (the corpus contributions are the
committed SXT-011 normalized graphs and the SXT-010 census hashes). No
distribution-license determination has been made for Surge-derived
material.
