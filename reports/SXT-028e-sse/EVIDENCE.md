# SXT-028e-sse evidence record — Distortion, SSE quad-waveshaper branch
# (FX models 3..7): frozen fixed model, exact RTL, per-instance
# `QuadWaveshaperState`, reference leg RUN on declared-synthetic carriers

Branch: `feature/issue-121` · Issue: #121 (SXT-028e-sse) · Raised by: #57
(SXT-028e) finding F-028e-2 · Epic: #3 · Date: 2026-09-26

**Amended 2026-10-02 by #136** (the oracle-host reference leg), on a Linux
x86-64 dispatch worker with the prebuilt pinned oracle of #232/#299
(`~/.cache/gf180-surge-oracle/58914e59…/linux-x86_64`). What changed: the
oracle extraction of the three corpus carriers now succeeds (§1), and §3 is
no longer NOT_RUN — it carries measured model-vs-pinned-engine numbers on
**declared synthetic** carriers, with every corpus carrier render-REFUSED
and recorded as such. Nothing in §2, §4, §5, §6, §7 or §8 was re-derived:
the frozen model is byte-identical (`model_revision()` unchanged) and the
RTL leg was not re-run.

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

**Claim discipline.** This record advances **(1) the RTL matches the frozen
fixed-point model exactly** (iverilog; demonstrated) and, since #136,
reports a **measured** result for **(2) model-vs-pinned-engine agreement**
(§3) — a *result*, not an *advance of a support claim*: every carrier that
produced a number is **declared synthetic**, so claim (2) here has **zero
corpus reach** (F-028e-sse-8), and two of the three proposed budgets are
**not met** for several shapers and are reported as not met. It does
**NOT** advance **(3) the instrument sounds good** (no human listening;
#8/#9 BLOCKED-on-human). It establishes no preset-support claim, no
cost/area/timing/synthesis/hardware-playback claim, and it **freezes no
budget**. No generic substitute is used under any claim — NC-A and NC-A2
prove both a generic and the *sibling leaf's own shaper* are rejected, on
the reference leg as well as at the model boundary.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (15 cases exact, 10/10 RTL mutant controls CONTROL-OK) | `rtl-exactness.json` |
| Shared #57 chain REUSED unchanged (bit-identical) | **PASS** | `tests/test_sxt028e_sse.py::test_shared_chain_is_bit_identical_to_sxt028e` |
| Model ↔ pinned engine vs [PROPOSED] budgets, **declared-synthetic carriers** | **MEASURED, MIXED** — rms and corr met for FX models 3/5/6 (rms −64.4…−74.6 dBFS, corr ≥ 0.999996) and **not met** for 4 and 7; the **peak** budget is met by **no** carrier above 0 dB drive (F-028e-sse-7) | §3, `artifacts/compare-*.json`, `artifacts/reference-leg.json` |
| Model ↔ pinned engine, **corpus carriers** | **NOT_RUN, confirmed with a stronger basis (#314)** — all **28** in-scope corpus slot instances (not only the three #121 picked) have a recorded terminal refusal: 27 by the static screens, 1 by the measured #136 determinism gate. Admitted carriers: **0**; coverage numbers do not move (finding **F-028e-sse-8**) | §1.1, `artifacts/slot-census.json`, `artifacts/slot-census.txt`, `artifacts/render-refusals.txt` |
| Reference-leg negative controls live | **5/5 CONTROL-OK** (NC-A, NC-A2, NC-SHARED, NC-B, NC-C) | §3, `artifacts/reference-leg.json` |
| Model-boundary agreement vs the independent float twin | **PASS** for FX models 3/5/6; **budget NOT met, at the measured sensitivity floor** for 4 and 7 (finding **F-028e-sse-4**) | §2, `negative-controls/` |
| Per-instance `QuadWaveshaperState` (two concurrent instances) | **PASS**; pooling mutant FAILS | `rtl-exactness.json` `prs-dual-*`, `mutant-wsshared`, `tests/…::test_per_instance_independence` |
| DC-offset probe + `/64` drive interpolation + `skipDriveNorm` | **PASS** (checkpointed, and three controls that "correct" them FAIL) | §4, §5 |
| Tails (declared 1600-block ringout span, incl. a mid-tail fx-rebuild reset) | **PASS** at the exactness boundary; one KNOWN-GAP recorded | §6 |
| Quad-waveshaper state bounded (issue stop/escalate clause) | **PASS** — 8 × Q24.43 + 2 bits = 65 B/instance delta; 0 B external | §7, `artifacts/buffer-requirement.json` |
| Constant inventory (DR-0012's reserved pass) | **DR-0014 PROPOSED**; `FuzzTable<1>` build check against the *external* pinned headers: libstdc++ **MATCH** 1025/1025; libc++ on an *alternate* host **MISMATCH** 305/1025 at default flags (MATCH with `-ffp-contract=off`); pinned-host leg **NOT_RUN** (#135). The row is therefore **re-classified as quoted data with provenance** (DR-0014 clause 3 amendment, conservative); `wst_sine` stays re-derived | §8, `artifacts/fuzz-table-rederivation*.json` |
| Negative controls live | **11/11 CONTROL-OK** model-side + **10/10** RTL-side | `negative-controls/`, `rtl-exactness.json` |
| Negative-control record reproducible | **PASS on one host, NOT across hosts** for the *metric* fields only — verdicts/statuses/`rtl-exactness.json`/`buffer-requirement.json` are host-stable (finding **F-028e-sse-6**) | §0, `negative-controls/negative-controls.json` → `environment` |
| Oracle extraction of fixture inputs | **PASS** — three carriers `COMPLETE` from the pinned loader's normalized state (F-028e-sse-3 closed); the model-6 carrier stays REFUSED on its own `fx_disable` screen | §1, `artifacts/extract-refusals-oracle.txt` |
| Model's silent-pre-roll boundary | **RESOLVED BY MEASUREMENT** (two engine-side invariances); the wrong boundary is live control NC-C | §3, `artifacts/settle-boundary.json` |
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

*Re-stated against measured data (#136).* The reference leg of §3 ran on a
**Linux x86-64** host, not the arm64 macOS host the original record
anticipated, so the `rcp_ps` term in it is x86 SSE's own estimate rather
than simde-on-ARM's. Measured: FX model 6 (`ADAA_FULL_WAVE`, the one
`rcp_ps` user whose metric is not also swamped by F-028e-sse-4's chaos)
lands at rms **−71.2 / −74.6 dBFS** and corr **≥ 0.999996**, i.e. inside
the [PROPOSED] rms and corr budgets *with* the estimate term present —
indistinguishable, at this instrument's resolution, from FX models 3 and 5,
which use no reciprocal estimate at all (−64.4…−74.4 dBFS). So the extra
term is **not** the dominant error for model 6 on this host. That is **not**
a bound on the arm64 host: this measurement constrains one implementation of
`rcp_ps`, and the finding stays OPEN and routed to #12 until the same leg is
run on the arm64 evidence host (follow-up filed, §10). For models 4 and 7
the term is unmeasurable here — F-028e-sse-4's decision-flipping dominates
by orders of magnitude.

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

**F-028e-sse-3 — CLOSED 2026-10-02 (#136).** As originally recorded: no
pinned oracle was reachable in the #121 implementation environment, so no
fixture was rendered, no max/rms/corr existed, and the oracle extraction of
the carriers' `deactivated` / `extend_range` flags was BLOCKED. The
prebuilt pinned oracle of #232/#299 made all of it reachable on an ordinary
dispatch worker. Both halves are now discharged: the three corpus carriers
extract `COMPLETE` from the loader's normalized state (§1) and the
reference leg is RUN with recorded numbers (§3). Closing this finding
closes only *"the leg could not be run"* — it asserts **no agreement**: the
numbers it produced are mixed, they are on declared-synthetic carriers
only, and F-028e-sse-1/4/7/8 carry what remains open.

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

*Re-stated against measured data (#136) — the prediction held.* The
reference leg now measures the same two shapers **against the pinned engine
itself**, through the complete wet chain, instead of against a float twin
at the model boundary:

| FX model | shaper | achieved rms (reference leg, two sequences) | vs [PROPOSED] ≤ −46 dBFS | corr vs ≥ 0.98 | samples over the 8,192-LSB peak budget |
|---|---|---|---|---|---|
| 4 | `DIGI_SSE2` | **−45.39 / −43.45 dBFS** | **FAIL** (by 0.6 / 2.6 dB) | 0.9971 / 0.9914 **PASS** | 4.93 % / 6.95 % |
| 7 | `TableEval<FuzzTable<1>,1024,TANH>` | **−31.38 / −31.99 dBFS** | **FAIL** | 0.879 / 0.823 **FAIL** | **71.7 % / 72.5 %** |

FX model 7's achieved −31.4 / −32.0 dBFS sits on top of the **−31.20 dBFS**
model-boundary figure above, whose own sensitivity floor is **−31.51 dBFS**
— i.e. against the real engine the frozen model is *still* no further away
than the independent float twin is from itself under a perturbation the
frozen drive word cannot represent. The two measurements were taken by
different harnesses against different references and agree to ~0.5 dB. The
median per-sample difference tells the two failures apart: FX model 4 is at
**0.5–0.6 LSB** (a few percent of samples blow out), FX model 7 at
**≈ 17,200 LSB** (the LUT index disagrees nearly everywhere). Both remain
**routed to SXT-017 (#12)** and neither is reported as a pass; no budget
was moved, and no region was excluded to improve either number.

**F-028e-sse-5 — FX model 7 (`wst_fuzzsoft`) has ZERO corpus reach.** The
active-Distortion-slot histogram, re-derived from
`corpus/normalized/graphs.jsonl` by
`tests/test_sxt028e_sse.py::test_corpus_reach_is_inventory_not_a_support_claim`,
is `{0: 418, 1: 27, 2: 2, 3: 13, 4: 8, 5: 6, 6: 1, 7: 0}` — 28 of 475 slot
instances (5.9 %) are in this leaf's scope, and **none of them uses model
7**. The algorithm is implemented (it is reachable from the UI and from any
future preset) and is exercised by synthetic corners, but no fixture record
exists and none is invented. Inventory only; not a support claim.

*Re-stated against measured data (#136).* The reference leg did **not**
invent a corpus carrier for model 7 and did not fold it into another
model's number. It built a **declared synthetic** carrier (`syn-m7`,
`tools/distortion_sse_synthetic.py`) in the pinned engine, labelled
`carrier_kind = DECLARED-SYNTHETIC` and `corpus_reach = NONE` in every
artifact it touches, and reported its numbers on their own row (§3). The
same treatment was given to FX model 6, whose single corpus instance is
still REFUSED on its own `fx_disable = 1` screen. The histogram is
unchanged by any of this; the declared-synthetic carriers add **zero**
corpus reach, and
`tests/test_sxt028e_sse.py::test_reference_leg_carriers_are_declared_synthetic_everywhere`
is a live guard that no `compare-*.json` can quietly claim otherwise.

**F-028e-sse-6 — these metric numbers are exact under a declared
environment, and only under it (measured in #243; the verdicts are not).**
`negative-controls/negative-controls.json` now carries an `environment`
block: interpreter, numpy, platform, and a sha256 `stimulus_digest` over
every stimulus sample the run rendered.

Measured across two libm implementations, not asserted. Regenerating this
record from a byte-for-byte **unmodified** tree:

| Regeneration host | `max_abs_diff_lsb` / `rms_diff_*` | `spectral_corr` | verdicts / `ok` / statuses |
|---|---|---|---|
| Linux, **glibc 2.41**, CPython 3.14.7, numpy 2.5.3 (aarch64) | **all byte-identical** to the committed record | 12 fields move, ≤ **8.1e-16** relative | **byte-identical** |
| macOS 27, **Apple libm**, CPython 3.14.7, numpy 2.4.2 (arm64) | **43 fields move**, FX-model-7 legs by up to **12 %** | 12 more fields move, ≤ 2.3e-16 | **byte-identical** |

So the record was originally taken on a **glibc** host, and two mechanisms —
**neither of them in the frozen model** — account for every moved field:

1. **The INPUT is libm-dependent.** `stimulus()`
   (`tools/distortion_negative_controls.py`) is built with libm `sin` at
   phases running to ~118 rad, where libm is **not** correctly rounded: 252
   of this harness's 6,144 `sin` evaluations are 1 ULP off the correctly
   rounded value under Apple libm. A different libm therefore hands the
   harness a *different input* before any model code runs. The two libms'
   `stimulus_digest` values differ outright
   (`ed759d67…` glibc vs `41f51e16…` Apple libm, same architecture, same
   interpreter, same source bytes). Substituting a correctly rounded `sin`
   (mpmath, 200-bit) for libm's and changing nothing else reproduces the
   same drift signature and the same worst-case field: the **FX-model-7**
   legs by up to **14 %** relative — the F-028e-sse-4 chaos now amplifying a
   1-ULP *input* change — FX models 3/5/6 by ≤ 4.2e-9, and the
   model-independent controls by ≤ 1e-13. FX model 4's
   `max_abs_diff_lsb` / `rms_diff_*` do not move at all; `wst_digital`'s
   staircase absorbs the perturbation.
2. **`spectral_corr` is numpy.** It is an rfft plus sum reductions, so its
   last 1–2 bits follow the numpy build's reduction order. It moves by
   ≤ 8.1e-16 relative even between two runs whose compared signals are
   *bit-identical* and whose stimulus digests match — it is the only field
   that does. Bounded by the recorded `numpy` version, not by the digest.

This is **not** run-to-run nondeterminism: two runs of the same code on one
host are byte-identical. It is also **not** sensitive to dead code — the
zero-caller helper deleted from `sse_tables.py` in #243 changes this record
in exactly two fields, both of them `model_revision`, with all 282 others
byte-identical against an unmodified tree on the same host. And it does not
reach the other two artifacts: `rtl-exactness.json` (iverilog 13.0) and
`artifacts/buffer-requirement.json` each regenerate **byte-identical** on
*both* hosts, so their only delta here is `model_revision` and its 8-hex
`rtl_trace`/`expected` echoes.

Consequently this record is regenerated **in its original glibc
environment**, and the committed delta for #243 is: two `model_revision`
fields, the new `environment` block, and 12 `spectral_corr` fields at
≤ 8.1e-16 (numpy 2.5.3 vs the original recording numpy). Nothing else moved.

Same stimulus digest ⇒ the `max`/`rms` fields must reproduce byte-for-byte,
and a `max`/`rms` diff under a *matching* digest is a regression; a differing
digest **explains** such a diff and is not itself one. `spectral_corr`
carries the numpy residue above on top of that.
`tests/test_sxt028e_sse.py` re-derives the digest rather than trusting the
record, reports **NOT_RUN** (skip) — never a pass — on a host whose libm
disagrees, and carries a live negative control proving the digest moves
under a 1-ULP change to one input sample. Because the record is glibc-taken,
that check is **live in CI** and NOT_RUN on an Apple-libm workstation.

**F-028e-sse-7 — the sample-domain PEAK budget is not an attainable
instrument for *any* shaper in this branch above 0 dB drive (measured in
#136, routed to #12).** F-028e-sse-4 above reports two shapers for which
the *rms* budget cannot discriminate. The reference leg shows the
`max_abs_diff_lsb ≤ 8,192` clause is weaker still: **every** declared
synthetic carrier misses it, including FX models 3, 5 and 6 whose rms and
corr are met comfortably. The declared drive-sensitivity family (FX model
3, one instance, identical in everything but drive; `syn-d{0,6,12,18}-m3`,
`seq-poly-8-v1`) isolates the mechanism:

| drive | max abs (LSB) | samples over 8,192 LSB | rms (dBFS) | corr |
|---|---|---|---|---|
| 0 dB | **10.5** | **0** / 177,600 | −113.64 | 1.000000 |
| 6 dB | 66,345 | 261 (0.147 %) | −58.43 | 1.000000 |
| 12 dB | 188,471 | 310 (0.175 %) | −50.48 | 1.000000 |
| 18 dB | 355,513 | 370 (0.208 %) | −47.09 | 0.999998 |

At 0 dB drive the whole chain agrees to **10.5 LSB** — so this is not a
wiring, de-amp, clip or halfband error, and the harness is sound (that row
is the harness anchor). What grows with drive is the *steepness* of the
waveshaper: a sub-LSB fixed-point residue arriving at a steep part of the
curve leaves as a large sample excursion, and the excursions stay **rare**
(≤ 0.21 % of samples; median difference 0.02 LSB) rather than becoming a
level or spectral error — which is why rms and corr stay met while the peak
clause does not. A single-sample maximum therefore measures *where the
curve is steepest*, not how closely the model tracks the engine. Whether
the effect-slice budget should keep an unconditioned peak clause, replace
it with a percentile/exceedance clause, or scale it with drive is
**SXT-017's (#12) decision, not this leaf's**. The clause is reported as
**not met**; it was not relaxed, re-scaled or dropped here, and every
`compare-*.json` carries the exceedance count alongside the max so the
difference between "missed by 29 samples" and "missed by 72 % of samples"
cannot be lost.

**F-028e-sse-8 — claim (2) for this leaf has ZERO corpus reach: every
corpus carrier is render-REFUSED (measured in #136, routed to #12/#22).**
The reference leg attempted all three corpus carriers × both sequences
before building anything synthetic, and all six attempts were refused with
measured reasons (`artifacts/render-refusals.txt`):

| carrier | FX model | refusal |
|---|---|---|
| `Damon Armani/Drums/Reverse Crash.fxp` | 3 | its **all-off dry bus fails the 3× bit-identical determinism gate** |
| `Damon Armani/Plucks/Trance Pluck.fxp` | 4 | `drift = 1.0`; two non-muted oscillators with retrigger off; modulation into `FX A1 Mix` and `FX S1 Drive`; **unlanded `Conditioner`** in the active chain |
| `Kinsey Dulcet/.../Mutant Lo-Fi Acoustic Guitar Workstation.fxp` | 5 | modulation into `FX S1 Drive`; a non-muted oscillator with retrigger off |

None was worked around: no screen was relaxed, no modulation was frozen to
a constant, and the unlanded `Conditioner` was **not** replaced by a
generic. A determinism refusal is a statement about the *preset*, not about
this host: `artifacts/harness-host-control.json` re-renders the committed
SXT-028c `fmcombo` wet bus on this worker's prebuilt oracle and reproduces
its committed sha256 **exactly** (`89d42e51…`), three times over.
Consequently **every number in §3 is on a declared synthetic carrier**, and
no preset — not one — gains any support claim from this leaf. Routed to
SXT-017 (#12) for the budget question and to coverage publication (#22) for
the reach question; the follow-up for admissible corpus carriers is in §10.

**F-028e-sse-8 re-stated by #314 (2026-10-05): from "the three carriers
tried were refused" to "the corpus contains none".** The full per-slot
census (§1.1) shows that no active Distortion slot with FX model 3..7 in
`corpus/normalized/graphs.jsonl` is admissible: 28 of 28 are refused with
a recorded reason, FX model 7 has zero instances. Consequence for #22:
the SSE branch has **no** corpus reach, so no preset can gain a
model-vs-reference claim from this leaf and no coverage number can move;
claim (2) for FX models 3..7 stays on declared-synthetic carriers
(§3) until the pinned corpus or the refusal policies change (the latter
is #310/SXT-017's decision, not this record's). Scope of the basis:
see §1.1 "What the census does and does not prove".

## 1. Fixtures, applicability boundary (fail-closed), refusals

None of the three B4-scope carriers SXT-028e named uses an SSE-branch model
— all three are model 0 — so this leaf selected its **own** carriers, one
per reachable FX model, from `corpus/normalized/graphs.jsonl`
(`tools/extract_distortion_sse_inputs.py`). Since **#136** the oracle
extraction RUNS; the render-admissibility verdict in the right-hand column
is the *measured* one from §0 F-028e-sse-8, not a screen read off the
export.

| FX model | shaper | carrier | census blob SHA-1 | extraction | reference render |
|---|---|---|---|---|---|
| 3 `wst_sine` | `SINUS_SSE2<false>` | `Damon Armani/Drums/Reverse Crash.fxp` | `de5c684d…` | **COMPLETE** (oracle) | **NOT_RUN** — dry bus fails the 3× determinism gate |
| 4 `wst_digital` | `DIGI_SSE2` | `Damon Armani/Plucks/Trance Pluck.fxp` | `1bb5209f…` | **COMPLETE** (oracle) | **NOT_RUN** — drift ≠ 0, retrigger-off oscillators, modulation into FX params, unlanded `Conditioner` |
| 5 `wst_ojd` | `OJD` | `Kinsey Dulcet/Guitars/Mutant Lo-Fi Acoustic Guitar Workstation.fxp` | `714821ee…` | **COMPLETE** (oracle) | **NOT_RUN** — modulation into `FX S1 Drive`, retrigger-off oscillator |
| 6 `wst_fwrectify` | `ADAA_FULL_WAVE` | `Luna/Guitars/Awful FM Guitar.fxp` | `d71a9cfd…` | **REFUSED**: `fx_disable = 1` (non-zero). It is the ONLY model-6 instance in the corpus, so model 6 has no usable carrier. | **NOT_RUN** |
| 7 `wst_fuzzsoft` | `TableEval<FuzzTable<1>,…>` | — | — | **NO CARRIER EXISTS** (F-028e-sse-5) | **NOT_RUN** |

* **Oracle extraction: COMPLETE for the three admissible carriers** and
  still REFUSED for the model-6 one, on its own `fx_disable` screen rather
  than on host availability. Transcript:
  `artifacts/extract-refusals-oracle.txt`.
  The five oracle-only fields come from the loader's **normalized** state
  via a `savePatch` round-trip of the loaded patch — not from the raw
  pre-migration `.fxp`, which CLAUDE.md declares non-authoritative, and not
  from re-implementing `handleStreamingMismatches` here. `surgepy` exposes
  no `getDeactivated`, which is exactly why the round-trip is used. Four
  fail-closed cross-checks must all agree or the extraction refuses: the
  live `getExtend` getters (3 flags), the raw `.fxp` attribute plus the
  documented migration rule (all 5), the twelve parameter values against
  the committed SXT-011 `graphs.jsonl` export at its own 6-decimal
  precision, and the engine's FX slot types against the export's.
* **Graphs cross-check: still written, still deliberately unusable for a
  model run.** `--mode graphs` derives the 12 loader-normalized parameter
  values oracle-free and writes a record with the five oracle-only fields
  explicitly `null`; `DistortionSSEParams` **refuses** such a record. That
  refusal is still live-tested — now as a mutation of each COMPLETE record
  (`test_committed_fx_inputs_are_complete_from_the_pinned_loader` blanks
  each of the five fields in turn and requires a refusal), so the
  fail-closed path cannot rot now that the committed records are complete.
* The extractor also fails closed in the **other** direction: a Distortion
  slot whose FX model is 0..2 is refused here, because it belongs to #57.

The RTL/model exactness cases below are driven by **declared synthetic
stimuli and parameter corners**, not by fixture replays (they were frozen
in #121, before any reference bus existed, and #136 did not re-run them).
That is a weaker basis than a canonical-fixture replay and it is stated as
such — it bounds claim (1) only. The reference buses #136 *did* render are
likewise synthetic (F-028e-sse-8); they bound claim (2) only, and neither
bound transfers to the other.

### 1.1 Per-slot corpus census (#314, F-028e-sse-8)

`tools/census_distortion_sse_slots.py` enumerates **every** active
Distortion slot with FX model 3..7 over `corpus/normalized/graphs.jsonl`,
one row per (preset, slot) — never per preset — and writes
`artifacts/slot-census.json` / `.txt` (re-derived by
`tests/test_sxt028e_sse_slot_census.py`, which also recomputes the 28 keys
independently of the tool).

| FX model | slot instances | REFUSED-STATIC | REFUSED-EMPIRICAL (#136, measured) | admitted |
|---|---|---|---|---|
| 3 `wst_sine` | 13 | 12 | 1 (`Reverse Crash`: dry-bus 3× gate) | 0 |
| 4 `wst_digital` | 8 | 8 | 0 | 0 |
| 5 `wst_ojd` | 6 | 6 | 0 | 0 |
| 6 `wst_fwrectify` | 1 | 1 (`fx_disable = 1`) | 0 | 0 |
| 7 `wst_fuzzsoft` | 0 | — | — | — (zero-instance model, recorded separately; no synthetic row) |
| **total** | **28** | **27** | **1** | **0** |

Per-row reasons (`fx_disable`, FX-parameter modulation, non-muted
oscillator with retrigger off, unlanded active-chain classes such as
`Conditioner`, `Airwindows`, `Reverb 2`, `Freq Shift`, `Nimbus`) are in
`artifacts/slot-census.txt`. Several rows are refused for an unlanded
class even where an SSE slot is otherwise unremarkable; none was
substituted.

**What the census does and does not prove.**

* The static screens are evaluated from the committed normalized graphs
  (the same values `_render_screens` reads via `getParamVal`), by an
  oracle-free mirror of those screens. The scene `drift` screen is **not**
  evaluable from the normalized schema and is recorded NOT_EVALUATED; it can
  only add refusals, so it cannot rescue any row.
* No row survived the static screens except `Reverse Crash`, whose
  empirical refusal was measured on the pinned oracle in #136 (harness
  control PASS). Its quoted hashes vary run to run by definition; the
  reason is what is retained.
* **NOT_RUN in this change:** no oracle host was available to this builder
  (`surgepy` absent, arm64 darwin, no prebuilt URL), so the 3× gates were
  not re-run for any row, no fixture bundle or `compare-*.json` was
  produced, and the five reference-leg negative controls were not
  re-exercised (there is no new carrier to apply them to; the committed
  5/5 CONTROL-OK of §3.4 stands for the synthetic legs only). Because 27
  rows are refused *before* any render, an oracle host cannot change their
  outcome; only the `Reverse Crash` verdict rests on an oracle run, and
  that run is #136's.
* `tools/render_distortion_sse_fixtures.py` is **unchanged**: its
  `CORPUS_CARRIERS` list is no longer the selector of record. The census
  is, and since nothing is statically admissible there is nothing further
  for that tool to consume.

**Mirror/oracle screen parity (#336).** `tests/test_sxt028e_sse_slot_census.py`
now pins the oracle-free mirror (`preset_screens`) against the committed
oracle-read screens. For each `model/effects/fx_inputs/type-distortion-sse-*.json`
record carrying `render_screens`, the expected reasons are built from the
record alone (`refusal_reasons` minus `drift = ` entries, plus the renderer's
unlanded-class reason from `unlanded_classes_in_chain`, spelled with the
census `--` separator) and compared with the mirror run on the single
`graphs.jsonl` row joined by `preset_path`, using the record's own
`landed_classes_basis`. Missing/duplicate graph joins and an empty population
fail.

* Checked-record population (coverage): 3 records, `reversecrash` (empty
  reasons), `mutantlofiacoustic` (FX modulation + retrigger), `trancepluck`
  (FX modulation, two retrigger reasons, oracle-only drift excluded, unlanded
  `Conditioner`). Parity: **PASS** for all 3; no divergence, so the
  F-028e-sse-8 basis above is unchanged.
* Failure control: a mirror wrapper dropping `retrigger off` reasons makes the
  same parity assertion fail on both committed records containing such a
  reason (mismatch diagnostic lists mirror vs oracle reasons): **PASS**
  (control demonstrably fails). Missing/duplicate-graph fail-closed: **PASS**.
* Commands: `python3 -m pytest -q tests/test_sxt028e_sse_slot_census.py` run
  with Python 3.12.3 in a throwaway venv (system python lacks pytest): 12
  passed. `python3 tools/census_distortion_sse_slots.py --check`: PASS
  (artifact freshness only; not a screen-parity statement).
* Not established: screen policy correctness (#310), the drift screen (stays
  NOT_EVALUATED in the mirror), any render, fidelity, preset-support or
  musical-quality claim.

## 2. Frozen fixed-point model

`model/effects/type-distortion-sse/` — `sse_tables.py` (the generator for
the two table rows: `wst_sine`, re-derived, and `FuzzTable<1>`, classified
quoted data with provenance per DR-0014 clause 3 as amended, §8), `quad_shapers.py` (the five shapers, the state layout and the
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

## 3. Model vs pinned engine — MEASURED (#136), declared-synthetic carriers

Budgets, unchanged from the issue and from SXT-023: max ≤ 8,192 LSB Q10.21;
rms ≤ −46 dBFS; spectral corr ≥ 0.98 — **[PROPOSED], not frozen**; freeze
gated on SXT-017 (#12). **Every number below is RECORDED, NOT TUNED**: the
comparator has no threshold of its own (it imports SXT-028c's constants),
the tail region is read from the fixture sidecar's declared values
(#93/#100), and a FAIL is written out as a FAIL.

**Read the carrier column first.** All of them are **DECLARED SYNTHETIC**
(F-028e-sse-8): patches constructed in the pinned engine from
`patches_factory/Basses/FM Combo.fxp`, not corpus presets. They carry **no
corpus reach, no preset-support claim and no musical-quality claim**. Every
corpus carrier was attempted and refused (§1, §0 F-028e-sse-8).

### 3.1 Primary legs — the unmodified `original` wet bus

Metrics are on the mono sum (the worst channel-wise figures are in the
per-leg JSON); `best_shift = 0` for every row, so nothing is time-aligned.

| FX model | shaper | carrier | sequence | max abs (LSB) | over 8,192 LSB | rms (dBFS) | corr | tail rel (dB) | verdict vs [PROPOSED] |
|---|---|---|---|---|---|---|---|---|---|
| 3 | `SINUS_SSE2<false>` | `syn-m3` | notes-coverage | 30,558 | 135 (0.049 %) | **−69.50** | **1.000000** | −100.64 | FAIL (peak only) |
| 3 | `SINUS_SSE2<false>` | `syn-m3` | poly-8 | 40,817 | 186 (0.105 %) | **−64.37** | **1.000000** | −97.48 | FAIL (peak only) |
| 4 | `DIGI_SSE2` | `syn-m4` | notes-coverage | 143,097 | 13,491 (4.93 %) | −45.39 | 0.997111 | −15.83 | **FAIL** (peak, rms, tail) |
| 4 | `DIGI_SSE2` | `syn-m4` | poly-8 | 171,788 | 12,345 (6.95 %) | −43.45 | 0.991445 | −14.34 | **FAIL** (peak, rms, tail) |
| 5 | `OJD` | `syn-m5` | notes-coverage | 21,424 | 29 (0.011 %) | **−74.37** | **1.000000** | −101.71 | FAIL (peak only) |
| 5 | `OJD` | `syn-m5` | poly-8 | 29,693 | 46 (0.026 %) | **−70.12** | **1.000000** | −97.79 | FAIL (peak only) |
| 6 | `ADAA_FULL_WAVE` | `syn-m6` | notes-coverage | 21,538 | 29 (0.011 %) | **−74.58** | **0.999999** | −93.03 | FAIL (peak only) |
| 6 | `ADAA_FULL_WAVE` | `syn-m6` | poly-8 | 29,817 | 25 (0.014 %) | **−71.17** | **0.999996** | −89.66 | FAIL (peak only) |
| 7 | `TableEval<FuzzTable<1>,1024,TANH>` | `syn-m7` | notes-coverage | 105,141 | 196,306 (**71.75 %**) | −31.38 | 0.879277 | −2.81 | **FAIL** (all four) |
| 7 | `TableEval<FuzzTable<1>,1024,TANH>` | `syn-m7` | poly-8 | 111,181 | 128,691 (**72.46 %**) | −31.99 | 0.823193 | −1.32 | **FAIL** (all four) |

Drive-sensitivity family (FX model 3, one instance, `seq-poly-8-v1`) — the
table is in §0 F-028e-sse-7. Its 0 dB row (`syn-d0-m3`: **10.5 LSB**,
−113.64 dBFS, corr 1.000000, 0 samples over the peak budget) is the
**harness anchor** and the only leg that meets all three proposed budgets.

What the two stimuli show: no verdict flips between them, and the ordering
of the shapers is the same under both, so nothing here is an artifact of
one note pattern.

**Honest reading.** FX models 3, 5 and 6 reproduce the pinned engine's wet
bus at **−64 to −75 dBFS rms with spectral correlation indistinguishable
from 1**, and their tails track to ≈ −90…−102 dB relative; they miss only
the unconditioned peak clause, and only on ≈ 0.01–0.11 % of samples
(F-028e-sse-7). FX models 4 and 7 miss the rms clause — and, for 7, the
correlation clause as well — at the sensitivity floor F-028e-sse-4
predicted. **No budget was relaxed, no region was excluded, and no FAIL was
re-described as a pass.**

### 3.2 Per-slot bypass legs (FX model 3, `seq-poly-8-v1`)

Each leg switches exactly ONE Distortion slot Off in the engine and removes
the same slot from the model chain. The unmodified `original` wet reference
is untouched by these legs — it is still committed and still the bus §3.1
grades against.

| leg | active Distortion slot | max abs (LSB) | over 8,192 LSB | rms (dBFS) | corr | tail gate |
|---|---|---|---|---|---|---|
| `bypass-fx0` | `send1` only (drive 6 dB, inside its own feedback loop) | **950** | **0** | **−94.93** | **1.000000** | PASS |
| `bypass-fx4` | `ains1` only (drive 12 dB) | 40,543 | 173 (0.097 %) | −64.83 | 1.000000 | PASS |

`bypass-fx0` meets **all three** proposed budgets — the second independent
leg (with the 0 dB anchor) that does — which is what makes the peak-clause
failures elsewhere readable as a drive/steepness effect rather than a
chain-wiring error.

### 3.3 The settle boundary was MEASURED, not chosen

The fixture render runs a 0.25 s (375-block) settle before the first note.
Whether the **effect** must be pre-rolled through it or only the **synth**
(whose settle is already baked into the all-off dry bus the model reads) is
worth 73 dB on the anchor carrier — more than the whole budget — so it was
settled by measurement, in `artifacts/settle-boundary.json`:

| probe | result |
|---|---|
| A: engine wet bus, 375-block settle vs 3750-block settle | **byte-identical** (`deca8b7a…`) — the engine's effect state does not evolve during a silent settle |
| B: synthetic carrier constructed in place vs saved to `.fxp` and re-loaded into a fresh instance | **byte-identical** — A is the engine's behaviour for an ORDINARY loaded preset, not an artifact of this leaf's construction |
| C: frozen model vs engine, 0-block silent pre-roll | **10.5 LSB / −113.64 dBFS** |
| C: frozen model vs engine, 375-block silent pre-roll | 672,130 LSB / −40.08 dBFS |

So the engine's Distortion enters the first audio block with its control
plane still in the `init()` state (both lipols and both peak-EQ /
high-cut coefficient sets at zero), and the declared pre-roll is **0
blocks**. This is a property of the **harness**
(`model/effects/run_distortion_sse_model.py`, new in #136), not of the
frozen model: no byte of `model/effects/type-distortion-sse/` changed and
`model_revision()` is unchanged. The wrong boundary is kept live as control
**NC-C** below, so it cannot silently come back.

### 3.4 Negative controls on the reference leg — 5/5 CONTROL-OK

Graded on `syn-m5` / `seq-poly-8-v1` against the unmodified `original` wet
bus. **Each MUST FAIL**; a reference leg whose controls pass is measuring
the wrong thing, and `reference-leg.json` sets `controls_ok = false` and
refuses to present its primary numbers as agreement if any one of them
passes.

| control | substitution | max abs (LSB) | rms (dBFS) | corr | tail rel (dB) | required | result |
|---|---|---|---|---|---|---|---|
| **NC-A** | a generic single-rate `tanh` (no oversampling, no halfband, no pre/post EQ, no feedback, no quad-waveshaper state) in place of the frozen chain | 1,344,899 | −13.52 | 0.900155 | −6.15 | FAIL | **CONTROL-OK** |
| **NC-A2** | the **sibling leaf's own** `lookup_waveshape` table shaper substituted for `GetQuadWaveshaper`, chain otherwise untouched | 243,750 | −26.80 | 0.983611 | −23.01 | FAIL | **CONTROL-OK** |
| **NC-SHARED** | ONE shared effect instance driving both the `ains1` and the `send1` slot (shared instead of per-instance state) | 1,830,054 | −11.97 | 0.443628 | −4.15 | FAIL | **CONTROL-OK** |
| **NC-B** | the whole declared tail region (3,750 blocks) dropped (zeroed) from the model render | 824,997 | −34.48 | 0.994656 | **0.00** | FAIL the **tail** gate | **CONTROL-OK** |
| **NC-C** | the wrong settle boundary: the 375-block synth settle also run through the effect (§3.3) | 944,522 | −37.47 | 0.999994 | −97.79 | FAIL | **CONTROL-OK** |

NC-A2 is the sharpest of these: it is not a convenient generic but *this
project's other committed Distortion shaper*, and it still misses the
budget by 19 dB of rms. NC-C is the one that would have silently corrupted
every number in §3.1 had it not been measured — note that it passes the
tail gate and keeps corr at 0.999994, so only the rms/peak clauses catch
it.

### 3.5 Reproducibility of the engine side

Within a run, every fixture leg passed the **3× bit-identical** determinism
gate (`determinism_gate.per_leg_sha256_all` in each sidecar; 48 leg-renders
over 14 bundles). **Across runs**, the whole fixture set was rendered a
second time into a separate directory on the same host: **36 / 36 WAVs
byte-identical**, and all 14 sidecars identical apart from the output paths
they were told to write. `artifacts/render-refusals.txt` reproduces in its
rows and reasons but **not** byte-for-byte, by construction: a
"determinism gate failed" row quotes that run's three differing hashes,
which is the finding itself. The transcript says so in its own header.

Host/harness control: `artifacts/harness-host-control.json` re-renders the
committed SXT-028c `fmcombo` wet bus through this worker's prebuilt oracle
and reproduces its committed sha256 exactly (`89d42e51…`), so a determinism
REFUSAL above is a statement about the preset, not about this host. The
renderer refuses to render or refuse anything else if that control fails.

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
* **2 generated table rows** — `wst_sine` (1024 words) from
  `sin((i−512)·π/512)`, and `FuzzTable<1>` (1025 words) from
  `x·(1−range) + U(−range, range)` with the header's own pinned
  `portable_minstd_rand(2112)`. The committed ROM is a build product of
  `sse_tables.py` and a test asserts it byte for byte. *As first recorded
  both rows were classified re-derived; as amended (DR-0014 clause 3, #135,
  below) only `wst_sine` is re-derived and `FuzzTable<1>` is classified
  **quoted data with provenance**, conservatively, pending the NOT_RUN
  pinned-host leg.*
* **6 structural powers of two** — not engine data; `localparam`s in the RTL.

**The `FuzzTable<1>` re-derivation claim is checked BY BUILD, not by
assertion — against the pinned headers themselves, which stay outside this
repository.** (The libstdc++ build MATCHes, below; the libc++ leg that
follows does not at default flags, so the claim is not established and the
row is re-classified as quoted data — see the libc++ paragraph.) The one implementation-defined step is the standard library's
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

**libc++ leg (#135): alternate-environment observation; pinned-host leg
NOT_RUN.** `oracle/manifest.json` (`environment`) freezes the oracle host as
macOS 26.5.1 (Build 25F80), Apple clang 21.0.0 (clang-2100.1.1.101), target
arm64-apple-darwin25.5.0. The libc++ transcripts below were NOT produced
there: they ran on an arm64 macOS host at Darwin 27.0.0 (`RELEASE_ARM64_T6050`,
macOS 27.0.1) with Apple clang version 21.0.0 (clang-2100.3.34.2), libc++
(`_LIBCPP_VERSION` 220106), against the pinned headers `dd12f31a…` /
`a32b8aec…`, simde `71fd833d…` fetched by `oracle/fetch-waveshaper-headers.sh`
into an external directory. They are retained as **alternate-environment
observations** and do **not** discharge the pinned-host acceptance leg,
which is **NOT_RUN**; #135 stays open for it. Each transcript records this
itself (`environment.scope`, `environment.pinned_host_acceptance =
NOT_RUN`), computed by the tool against the manifest, and records the
standard library from a macro probe that uses the driver's exact flags and
include path (`stdlib_detection`). Both compared 1025 entries:

| flags | status | mismatches | transcript |
|---|---|---|---|
| `-O2 -std=c++20` (compiler default) | **MISMATCH** | 305 (first at index 2) | `artifacts/fuzz-table-rederivation-libcxx-arm64.json` |
| `-O2 -std=c++20 -ffp-contract=off` (diagnostic) | **MATCH** | 0 | `artifacts/fuzz-table-rederivation-libcxx-arm64-fpcontract-off.json` |

The libstdc++ transcript (`fuzz-table-rederivation.json`) is retained
unchanged. Cause, on that alternate host: Apple clang fuses
`x * (1 - range) + draw` into an FMA by default; with contraction off the
libc++ draw sequence reproduces the generator bit for bit. So on that host
the libc++ `generate_canonical` reading is confirmed by build, and the tool's
default-flags verdict is **MISMATCH**. DR-0014 clause 3 (amended) therefore
**conservatively** re-classifies the `FuzzTable<1>` row as quoted data with
provenance (class (a)): the "re-derived" claim is not established on any
libc++ build observed. **Not established:** the verdict under the pinned
toolchain (clang-2100.1.1.101 may contract differently), and whether the
pinned oracle's real build uses contraction (its flags are not in
`oracle/manifest.json`); the model/RTL values are unchanged. The tool
(`tools/check_fuzz_table_rederivation.py`, not byte-frozen) gained
`--cxxflag`, a flag-faithful standard-library probe (a failed probe is
recorded `UNKNOWN`, never guessed), and the environment-scope record; the
stale "UNVERIFIED-BY-BUILD" and "re-derived" wording in the byte-frozen
`model/effects/type-distortion-sse/sse_tables.py` docstring is left
unedited and is superseded by this section and DR-0014.

## 9. Newly-enabled presets (honest delta)

**Supported stays 0 — and #136 running the reference leg does not change
that by one preset.** The conjunction in `reports/coverage-v1/README.md`
still fails for every carrier at earlier gates, and this leaf's own gates
still fail:

* model-vs-reference is measured **only on declared synthetic carriers**;
  **every corpus carrier is render-REFUSED** (F-028e-sse-8) — since #314
  that covers all 28 in-scope slot instances (§1.1), so no corpus
  preset has a reference comparison at all and none can be obtained without
  changing a policy or the corpus;
* FX model 6 has no usable corpus carrier and FX model 7 has none at all
  (F-028e-sse-5) — the synthetic carriers built for them add no reach;
* the rms budget is not met for FX models 4 and 7 (F-028e-sse-4) and the
  peak budget is met by no carrier above 0 dB drive (F-028e-sse-7);
* the `Trance Pluck` chain contains an **unlanded `Conditioner`**, so even
  if its other screens passed, a *complete-wet* comparison for that preset
  is not yet constructible without substituting a generic — which this
  project refuses.

**`reports/coverage-v1/leaf-verification.json` is deliberately NOT
modified.** Updating the ledger is a coverage-publication action, and
coverage publication is an explicit non-goal of #121 and of #136 (it
belongs to #22); `main` also still carries the pre-existing
republishability defect filed as #125. More to the point, **nothing in the
ledger would change**: the `fx:Distortion` row's `model_vs_reference` turns
on a *corpus* carrier comparison, and there is still none. Nothing in this
record should be read as a coverage claim.

## 9b. Arm64 macOS re-run of the reference leg (#317) -- BLOCKED / NOT_RUN

Run 2026-10-09 on an arm64 macOS host (Darwin 27.0.1, Apple clang from Xcode
27.0), pinned engine built from source with `oracle/fetch-and-build.sh`
(drift gate PASS). Records: `artifacts-arm64-macos/` (committed *alongside*
the x86-64 set in `artifacts/`; the x86-64 set is unchanged).

| Acceptance item | Status | Why |
|---|---|---|
| Harness/host control reproduces SXT-028c sha256 | **FAIL** | re-render is deterministic on this host (3/3 identical, `1382316462c8...`) but is `701aa330...`, not the committed `89d42e51...`. The whole run is therefore NOT_RUN downstream, as the issue requires. |
| Settle-boundary probe re-run, invariances re-derived | **NOT_RUN** | probe aborts on the synthetic-construction refusal below; no `settle-boundary.json` produced |
| 14 primary legs max/rms/corr | **NOT_RUN** | no fixture could be rendered (control FAIL; synthetic construction refused) |
| Per-shaper delta for FX models 4, 6, 7 | **NOT_RUN** | no arm64 numbers exist; none is inferred from x86-64 |
| F-028e-sse-1 re-stated | **UNCHANGED, still OPEN** | the `rcp_ps` term on simde-on-ARM is still unmeasured |
| NC-A, NC-A2, NC-SHARED, NC-B, NC-C still FAIL | **NOT_RUN** | no comparison ran |

Facts established on this host:

1. **Oracle build.** The committed configure defaults to a 10.15 deployment
   target and fails to compile with this SDK. The build used
   `-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0`, no engine source change. Its
   effect on render bytes is unmeasured. The engine is an unpatched pin
   (`1.4.HEAD.58914e59c`), whereas the committed control bus was rendered
   by `1.4.sxt037-tap.ff8b4dba4` on x86-64 Linux.
2. **Cross-host render repeatability (new result; §11's disclaimer now has a
   data point).** The SXT-028c FM Combo wet bus does NOT reproduce
   byte-for-byte across hosts. An unaligned sample-for-sample diagnostic
   (`control-diagnostic.py`) gives rms difference 5.77e-3 against rms 8.94e-2
   (about -24 dB), max 0.085. Not attributed: libm, FMA contraction, the
   deployment-target deviation and the tap-build difference are all
   untested candidates, and none is asserted.
3. **Synthetic construction fails closed.** `extract_distortion_sse_inputs.py
   --mode synthetic` refused all 9 carriers: the engine's read-back of
   `preeq_freq_f` is 6 binary32 ULPs from the value set (bound 4). The bound
   was not relaxed. Whether this is host libm, the build deviation, or
   something else is not determined.
4. Oracle-mode extraction of the corpus carriers ran and is identical to the
   committed records.

Unproved: everything the issue asked for. No arm64 max/rms/corr, no `rcp_ps`
bound, no negative-control result on this host. Metric questions remain
routed to #12; the host-repeatability result is the new fact. Suggested next
step (not done here): attribute the control difference by measurement, e.g.
build the committed tap variant or compare the same build on both hosts.

## 10. Follow-ups filed

* **#136 — SXT-028e-sse follow-up (F-028e-sse-1/3/4/5): oracle-host
  reference leg for the Distortion SSE quad-waveshaper branch.**
  **DONE 2026-10-02** (this amendment). Carried the whole NOT_RUN claim-(2)
  leg: the fail-closed oracle extraction of the three carriers'
  `deactivated`/`extend_range` flags (now COMPLETE, §1), the SXT-012
  fixture renders with tails over the declared 1600-block ring-out window
  (§3.5), the achieved max/rms/corr numbers (§3.1), declared-synthetic
  carriers for FX models 6 and 7 rather than a substituted one
  (F-028e-sse-5), and the `rcp_ps` term (F-028e-sse-1, now measured on x86
  and still open for arm64). F-028e-sse-3 is **closed**; F-028e-sse-1 and
  -4 are **re-stated against measured data and stay routed to #12**, and
  the leg raised two further findings, F-028e-sse-7 (the peak clause) and
  F-028e-sse-8 (zero corpus reach). No budget was relaxed.
* **#314 — an admissible corpus carrier for the SSE branch.** **DONE
  2026-10-05 as the "none exists" outcome** (§1.1): all 28 in-scope slot
  instances carry a recorded terminal refusal, FX model 7 has zero
  instances, admitted carriers = 0, no budget or screen touched, support
  count unchanged. Claim (2) still rests entirely on declared synthetic
  patches. Oracle-host re-run of the Reverse Crash dry-bus gate: NOT_RUN
  here (no oracle on the builder host).
* **#317 — re-run the reference leg on the arm64 macOS evidence host.**
  F-028e-sse-1's `rcp_ps` term is
  implementation-defined; §3 measured x86 SSE's estimate. The arm64
  simde path is unmeasured, and it is the host `oracle/manifest.json`
  names. **Attempted 2026-10-09: BLOCKED/NOT_RUN, see §9b** (control FAIL,
  synthetic construction refused).
* **#318 — audit every leaf's `run_*_model.py` for the §3.3
  silent-pre-roll boundary.** `run_chorus_model.py` and the SXT-023
  `run_fx_model.py` pattern pre-roll the model through the
  fixture settle. For an effect whose zero-input response is not its
  initialized state, that is worth tens of dB (73 dB here). Whether any
  landed sibling leaf's committed numbers are affected is a question this
  leaf cannot answer for them.
* **#135 — (OPEN; pinned-host leg NOT_RUN. Alternate-environment
  observations recorded in §8: MISMATCH at default flags, MATCH with
  `-ffp-contract=off`; row conservatively re-classified.) SXT-028e-sse
  follow-up: discharge the `FuzzTable<1>`
  re-derivation on the pinned arm64/libc++ oracle host.** The committed
  build checks are a libstdc++ MATCH and, on an alternate arm64 macOS /
  libc++ host (not the pinned one), a default-flags MISMATCH (305/1025) and
  a `-ffp-contract=off` MATCH (§8). The libc++ `generate_canonical` reading
  is thus confirmed by build on that alternate host, but no transcript
  exists from the pinned oracle host (macOS 26.5.1 / clang-2100.1.1.101).
  Applying the MISMATCH rule conservatively, DR-0014 clause 3 (amended)
  already re-classifies the row from "re-derived" to "quoted data with
  provenance"; what remains open is the pinned-host verdict, which would
  decide whether that conservative re-classification can ever be revisited.
  It is a licensing-relevant classification, which is why it is tracked
  rather than assumed.

No follow-up is filed for F-028e-sse-2 (`QuadWaveshaperState::init` is
indeterminate in the engine): it is decided and pinned here, bounded to the
first oversampled sample after each reset for FX model 6 only, and held in
place by the `mutant-adaainit` RTL control.

## 11. What this record does NOT establish

- Any fidelity policy or any frozen budget (SXT-017/#12). The reference
  leg is now RUN, but **mixed**: F-028e-sse-4 reports the rms clause as
  **not met** for FX models 4 and 7, and F-028e-sse-7 reports the peak
  clause as **not met by any carrier above 0 dB drive**, rather than
  relaxing either.
- Any model-vs-reference agreement **for a corpus preset**. Every corpus
  carrier is render-REFUSED (F-028e-sse-8); §3's numbers are all on
  declared synthetic patches and carry zero corpus reach.
- Any claim about `rcp_ps` on the arm64 macOS evidence host: §3 ran on
  Linux x86-64 (F-028e-sse-1).
- Anything about the sibling leaves' own settle boundaries (§3.3 is a
  measurement of *this* leaf's harness against *this* effect).
- Any preset-support or musical-quality claim; no human listening has
  occurred (#8/#9 BLOCKED-on-human). Essentiality of this feature remains
  **UNVERIFIED** — no SXT-014 ablation carrier exists for it.
- FPGA/gf180mcu synthesis, place-and-route, timing, power, area or hardware
  playback; the RTL is an iverilog-simulated behavioural schedule (version
  recorded in `rtl-exactness.json`).
- Anything about FX waveshaper models 0..2 (that is #57), about sibling
  effect classes, or about the engine's behaviour under a mid-render patch
  change.
- Repeatability of an engine render **beyond this one host**: §3.5's
  3×-within-a-run and twice-across-runs results are from a single Linux
  x86-64 worker. Cross-host render repeatability is not established here.
- The `FuzzTable<1>` re-derivation verdict on the pinned oracle host
  (macOS 26.5.1 / clang-2100.1.1.101): **NOT_RUN** (#135). The §8 libc++
  transcripts are alternate-environment observations only.
- Whether the pinned oracle's own build contracts FMAs (so which
  `FuzzTable<1>` values it holds) (§8).

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

# anywhere (fail-closed extraction cross-check, oracle-free)
python3 tools/extract_distortion_sse_inputs.py --mode graphs

# per-slot corpus census (#314), oracle-free; --check reports PASS/STALE
python3 tools/census_distortion_sse_slots.py --check

# unit/integrity tests (both leaves: this one must not disturb #57)
python3 -m pytest tests/test_sxt028e_sse.py tests/test_sxt028e.py -q

# --- THE REFERENCE LEG OF §3 (needs the pinned oracle) --------------------
# Any fleet worker can install the prebuilt, sha256-verified pinned oracle
# per user and print the three exports to source (#232 / PR #299):
oracle/fetch-and-build.sh --prebuilt        # or ORACLE_PREBUILT=1
export ORACLE_SURGE_DIR=~/.cache/gf180-surge-oracle/58914e59.../linux-x86_64
export ORACLE_PYTHON=~/.cache/gf180-surge-oracle/58914e59.../venv/bin/python
export LD_LIBRARY_PATH=~/.cache/gf180-surge-oracle/58914e59.../cpython-3.11.16/lib

# 1. oracle extraction of the corpus carriers (writes COMPLETE records)
$ORACLE_PYTHON tools/extract_distortion_sse_inputs.py --mode oracle
# 2. the declared-synthetic carrier records
$ORACLE_PYTHON tools/extract_distortion_sse_inputs.py --mode synthetic
# 3. the settle boundary (§3.3) — run BEFORE trusting any number below
$ORACLE_PYTHON tools/probe_distortion_sse_settle_boundary.py
# 4. fixture bundles: corpus attempts + refusals, then the synthetic
#    bundles, with the harness/host control and the 3x determinism gate
$ORACLE_PYTHON tools/render_distortion_sse_fixtures.py
# 5. the whole leg: primary + per-slot bypass + the five negative controls
$ORACLE_PYTHON tools/run_distortion_sse_reference_leg.py
#    (add --reuse-model to re-grade existing model renders in place)

# ARM64/libc++ ORACLE HOST ONLY (the §8 leg, and F-028e-sse-1's open half)
# The pinned-host leg (manifest environment) is NOT_RUN. On the alternate
# Darwin 27.0.0 / clang-2100.3.34.2 host these gave the §8 results; each
# transcript's `environment` block says which kind of host it ran on.
CXX=clang++ python3 tools/check_fuzz_table_rederivation.py \
    --out <json>                     # alt host: MISMATCH 305/1025
CXX=clang++ python3 tools/check_fuzz_table_rederivation.py \
    --cxxflag=-ffp-contract=off --out <json>   # alt host: MATCH 1025/1025
```

## 13. Provenance / licensing

The code in this repository is original (Apache-2.0 per `LICENSE`). The
SSE quad-waveshaper structure is read and cited from the pinned
GPL-3.0-or-later trees (`DistortionEffect.cpp` and sst-waveshapers); no
Surge or SST source code or assets are committed. Quoted engine **data**
is committed under
`decision-records/0014-distortion-sse-quad-waveshaper-constants.md`
(PROPOSED), the successor DR-0012 reserved for this branch, and is
classified there as *quoted data with provenance*: the eleven designed
shaper scalars and, as amended by DR-0014 clause 3 (#135), the
`FuzzTable<1>` table row (1025 words; `sst-waveshapers@dd12f31a…`,
`Fuzzes.h` + `WaveshaperLUT.h`, GPL-3.0-or-later). That row is reproduced
by the generator in `sse_tables.py` and is carried in the generated ROM
`rtl/effects/type-distortion-sse/ws_sse_q29.hex`; its re-classification is
conservative, pending the pinned-host leg (NOT_RUN, §8). Only the
`wst_sine` row remains classified as re-derived from its pinned construction
formula and not quoted data. These are classifications for the visible
record; they make no distribution-license determination.

**The #136 reference-leg artifacts add no new licensing posture.** The
fixture WAVs under `fixtures/` are *renders produced by* the external
pinned engine, of a patch constructed from the bundled factory preset
`patches_factory/Basses/FM Combo.fxp` — the same preset whose renders
SXT-028c already commits, under the same unresolved
distribution-license determination this repository has not made. No preset
file, engine source, table or asset is copied into this repository by this
amendment: the synthetic carrier is described by a *recipe*
(`tools/distortion_sse_synthetic.py`: slot types, twelve parameter values
per slot, one send level) plus the base preset's census blob SHA-1, which
is re-verified against the oracle host at render time. The extraction's
`savePatch` round-trip is written to a temporary directory and never
committed.

The `FuzzTable<1>` build discharge (§8) is the one place engine source is
*executed*, and it executes it **where it lives**: the driver compiled by
`tools/check_fuzz_table_rederivation.py` is original to this repository and
only `#include`s the pinned headers from an **external** checkout, pinned by
SHA to `oracle/manifest.json`. No GPL-licensed source text is transcribed,
embedded, or committed by that tool (the quoted *data* above is classified
separately under DR-0014), and
`tests/test_sxt028e_sse.py::test_rederivation_checker_carries_no_engine_source_text`
is a live guard on that. `oracle/fetch-waveshaper-headers.sh` refuses a
destination inside the repository for the same reason. No
distribution-license determination has been made for Surge-derived
material.
