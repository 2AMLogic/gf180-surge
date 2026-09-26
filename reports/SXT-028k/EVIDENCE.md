# SXT-028k evidence record — Airwindows "Logical" (streamed id 4): frozen fixed-point model, exact RTL, per-instance state; reference leg NOT_RUN (no oracle host)

Branch: `feature/issue-63` · Issue: #63 (SXT-028k) · Parent: #21 (SXT-028) ·
Epic: #3 · Plan §6 · Date: 2026-09-26

Engine pin (external; the executable reference is **not** in this
repository): `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
48 kHz, block size 32 (`oracle/manifest.json`).

Algorithm authority, read and cited, **never copied**:

* `libs/airwindows/src/Logical4Proc.cpp` (`processReplacing`) and
  `libs/airwindows/src/Logical4.{h,cpp}` — the vendored Airwindows subtree,
  **MIT, (c) 2018 Chris Johnson** (`libs/airwindows/LICENSE`,
  `libs/airwindows/README.md`);
* `libs/airwindows/src/AirWinBaseClass_pluginRegistry.cpp` — the `id++`
  streamed-id registry (MIT subtree);
* `src/common/dsp/effects/airwindows/AirWindowsEffect.{h,cpp}` and
  `src/common/dsp/Effect.h` — the shared adapter and its `OnePoleLag`
  parameter plane (Surge, **GPL-3.0-or-later**);
* `sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96`
  `include/sst/basic-blocks/dsp/Lag.h` (`SurgeLag`/`OnePoleLag`).

Licence decision record (required before merge, AGENTS.md):
[`decision-records/0015`](../../decision-records/0015-airwindows-logical-quoted-constants.md)
— quoted-constant inventory, attribution, and the finding that this subtree
is MIT rather than GPL-3.0-or-later as record 0006 described it.

**Claim discipline.** This record advances exactly one claim: **(1) the RTL
matches the frozen fixed-point model exactly** (iverilog, demonstrated). It
does **not** advance **(2) model-vs-pinned-engine agreement** — that leg is
**NOT_RUN** here (§3) — and it advances **no** claim of kind **(3) "it
sounds good"** (no listening; #8/#9 remain BLOCKED-on-human). It establishes
no preset-support claim, no coverage claim, no cost or fit claim, and no
FPGA/gf180mcu synthesis, timing, area or hardware-playback claim. It freezes
no budget: reference budgets stay **[PROPOSED, not frozen]**; #12 (SXT-017)
owns that freeze and is currently routed to the product owner.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Algorithm identity: adapter `p[0]` → exactly streamed id 4 | **PASS** | §2, `tests/test_sxt028k.py::test_algorithm_identity_is_id_4_only` |
| Frozen model ↔ RTL exact | **PASS** — 17 cases, 435 blocks, 27,840 output words, 69,600 checkpoint fields, 0 mismatches | `rtl-exactness.json` |
| Per-instance state (two concurrent instances) | **PASS** — real dual carrier (`Moogy Reese.fxp`, ains2 + global1); pooling mutant FAILS | `rtl-exactness.json` (`dual-moogy`, `NC_SHARED_STATE`) |
| Tails (gain-recovery span; dropped tail FAILs) | **PASS** | `artifacts/tail-window.json`, `tail-silence` / `tail-resume` / `reset-mid`, NC-D, `NC_TAIL_KILL` |
| RTL negative controls live | **PASS** — 5 injected-defect mutants, all CONTROL-OK, each with a declared blind spot | `rtl-exactness.json` |
| Stale-stub control (frozen-revision pin) | **PASS** — a stale pin is REFUSED, never passed | `rtl-exactness.json.stale_pin_control` |
| Model-side negative controls live | **PASS** — 7/7 CONTROL-OK (the issue's five required + bypass + quirk-fix) | `negative-controls/negative-controls.json` |
| Saturation events at the frozen words | **0** across all 17 cases (audio, control plane and reciprocal guards) | `rtl-exactness.json.cases[*].model_side` |
| State residency + external traffic (accounting) | **PASS** — 818 B/instance on-chip, **0 B external**, 0 reads/0 writes per frame, 6,650 B shared ROM | `artifacts/state-cost.json` |
| External-memory / cost **fit** | **[PENDING-SXT-016] / not claimed** | §6 |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** — no oracle host reachable | §3 |
| Fixture renders under SXT-012 policy (3× determinism gate) | **NOT_RUN** — needs the oracle host | §3 |
| Oracle parameter readback cross-check | **BLOCKED** — extractor refuses rather than inventing it | §1, `artifacts/extract-refusals-oracle.txt` |
| Musical quality / essentiality | **NO_VERDICT** — listening pending (#9) | — |
| Newly-enabled presets **supported** | **0** (honest delta) | §7 |

## 1. Inputs, applicability boundary (fail-closed), refusals

`tools/extract_aw4_inputs.py` extracts from **committed pinned evidence**,
never from raw `.fxp` bytes: `corpus/normalized/graphs.jsonl` (SXT-011) is
the native loader's post-migration readback at the engine pin, and the
census blob SHA-1 is re-verified against
`corpus/census-v0.1/corpus-manifest.json` at extraction time (mismatch
aborts). Recorded per carrier: `census_blob_reverified: true`,
`census_vs_graphs_sha_drift: 0`.

Five carrier records are emitted
(`model/effects/fx_inputs/aw-4-*.json`), covering the three issue-named
B4-scope carriers plus two added for coverage of the model's own corners:

| Slug | Preset | Slot(s) | `ratioselector` | why |
|---|---|---|---|---|
| `acoustic-snare` | `Cybersoda/Drums/Acoustic Snare.fxp` | ains2 | 1 | issue-named carrier |
| `dad` | `Exquis MPE/Ambiance/Dad.fxp` | global1 | 0 | issue-named carrier; the commonest shape |
| `3x101` | `Exquis MPE/Basses/3x101.fxp` | global1 | 1 | issue-named carrier; ratio fraction 2.4e-4 — immediately above a selector boundary |
| `bass-guitar-5` | `Slowboat/Basses/Bass Guitar 5.fxp` | global1 | 2 | ADDED: a real carrier that activates stage C (and therefore quirk Q2) |
| `moogy-reese` | `Exquis MPE/Basses/Moogy Reese.fxp` | ains2 **and** global1 | 1, 1 | ADDED: the corpus's real **dual-instance** carrier |

Fail-closed boundaries, recorded in every emitted record and never assumed
away:

* **`complete_wet_render_possible: false` for every carrier.** Each chain
  contains at least one FX class with no landed leaf (Conditioner, Reverb 2,
  Waveshaper, …). This leaf's evidence is slot-boundary only, in every case.
* **Two-level FX-modulation screen, both live.** (1) A modulation route into
  *this* leaf's own Logical slot parameters **refuses** the record — the
  frozen model has no representation for a moving FX parameter. (2) A route
  into any *other* FX slot is recorded and independently sets
  `complete_wet_render_possible: false`. Level 2 is deliberately weaker than
  the sibling aw-49 extractor's blanket rule, so each record also carries
  `strict_any_fx_route_screen`, showing exactly what the stricter rule would
  have done; nothing the strict rule blocks is claimed here.
* **Oracle readback is BLOCKED, not defaulted.** `--mode oracle` needs a
  built `surgepy` at `ORACLE_SURGE_DIR`; none is reachable, so the tool
  refuses all five carriers rather than invent the authoritative post-load
  readback. Transcript: `artifacts/extract-refusals-oracle.txt` (5 REFUSED,
  0 written). `extraction_status` is
  `COMPLETE-FOR-MODEL-PENDING-ORACLE-CROSSCHECK` — not "complete".
* **Determinism drift is NOT_RUN**, not 0: the SXT-012 3× bit-identical
  render gate needs the oracle host.

Corpus inventory (**inventory and prioritisation only — NOT a support or
coverage claim**, AGENTS.md): 120 active Logical slots across 115 presets,
of which 5 presets carry two concurrent Logical instances. So the
per-instance acceptance has real carriers, not only synthetic ones.

## 2. Algorithm identity and the frozen model

`AirWinBaseClass_pluginRegistry.cpp` assigns streamed ids with a monotonic,
append-only `id++`: `0 AD Clip · 1 Block Party · 2 Butter Comp ·
3 Compresaturator · 4 **Logical**`. The shared adapter dispatches `p[0]` to
that id and maps `p[1..5]` to Logical's five parameters (Threshold, Ratio,
Attack, Makeup Gain, Mix), setting `p[6..11]` to `ct_none`; A and D are
bipolar and none is integral, so all five take the adapter's `OnePoleLag`
path. This leaf models id 4 and nothing else — there is no dispatch table in
the model at all, which the test suite asserts.

The frozen model is `model/effects/aw-4/logical4_model.py` with the freeze
document `model/effects/aw-4/README.md`. Structure: three cascaded,
stereo-**linked** ButterComp stages, each preceded by its own Desk
"Power Sag" nonlinearity, with `ratioselector = floor(sqrt(B²·15+1)−1)`
selecting 1/2/3 active stages and the fractional part crossfading into the
last one. Frozen words: `a48` (48-bit, 35 frac) audio; `c96` (96-bit, 53
frac) gain/control plane; `t64` (64-bit, 43 frac) detector targets and
per-stage speed coefficients; `s96` (96-bit, 54 frac) sag accumulators —
exactly one fraction bit more than `c96` so the pinned `/offset` (= /2 at
48 kHz) is **exact**; `k31` control-plane coefficients. Round-half-up with
an arithmetic shift, saturating stores, **counted** saturations. No floating
point in the audio path.

**Four pinned quirks are reproduced deliberately**, each with a live control
(§5): Q1 the sag-line `+499` mirror against a 500-sample `gcount` period
(tap age is 3, not 2, at `gcount` 498/499); Q2 stage C's right channel
updating the **left** positive target while reading `targetposCR`, which
nothing ever writes (so `calcpos ≡ 1.0` on that side); Q3 stage C indexing
with `offsetB` while dividing by `offsetC` (arithmetically identical at
48 kHz, recorded so it is not tidied); Q4 `divisorC` not scaling with
attack, so stage C's decay/attack pair is not complementary
(`remainder[2] + divisor[2] ≠ 1`, asserted).

**Declared deviations** (bounded; they are model-vs-**reference**
contributors and are *not* measured by this record):

1. the pinned libm `sin` / `1−cos` in the bridge rectifier are replaced by
   two derived 806-word Q1.31 tables with one linear interpolation
   (`model/effects/aw-4/tables.py`); worst-case interpolation error
   `(1/512)²/8 = 4.8e-7` (−126 dBFS). Model and RTL evaluate the *same*
   table with the *same* arithmetic, so this is **not** a model-vs-RTL
   contributor;
2. `inputSample / compoutgain` becomes a multiply by a control-plane
   `inv_compoutgain` word quantised once to Q5.31 (relative error ≤ 2⁻³²);
3. float32/double engine arithmetic → the frozen integer words (≤ 1
   LSB-class per op, the class every landed leaf declares);
4. the adapter's `OnePoleLag` parameter ramp is declared control plane at
   its converged target; the ~0.3 s post-load ramp from 0 is covered by the
   render settle policy (the aw-49 precedent);
5. `long double fpOld` — see F-028k-4.

**Fail-closed scope**: 48 kHz only (the sag tap geometry depends on it);
declared input envelope `|x| ≤ 64.0` at the slot boundary; no parameter
modulation into this leaf's own FX params; missing/null/out-of-range
parameters refuse. Every one of these raises `Refuse` and is tested.

## 3. Model-vs-pinned-engine agreement — NOT_RUN

`artifacts/oracle-status.json`:

| Leg | Status | Why |
|---|---|---|
| `oracle_parameter_readback` | **BLOCKED** | `tools/extract_aw4_inputs.py --mode oracle` refuses; no built `surgepy` at `ORACLE_SURGE_DIR` |
| `fixture_renders_sxt012` | **NOT_RUN** | needs the oracle host |
| `reference_repeatability_3x_gate` | **NOT_RUN** | no renders to repeat |
| `model_vs_pinned_engine_agreement` | **NOT_RUN** | no reference render exists, so **no max/rms/corr number exists** |

Budgets remain **[PROPOSED, not frozen]** and are *not* achieved here — a
budget cannot be "met" by a leg that did not run. No `compare-*.json`
artifact exists in `reports/SXT-028k/`, and `tests/test_sxt028k.py` asserts
that none appears while the leg is NOT_RUN, so a later reader cannot mistake
a stale file for agreement. The [PROPOSED] SXT-023 effect-slice thresholds
appear in this leaf **only** as a substitution detector inside the
model-vs-model negative controls (§5); that use is labelled as such in the
record itself.

When an oracle host is available the leg is: `--mode oracle` extraction
(authoritative post-load readback, cross-checked against the graphs
records), slot-boundary renders of the five carriers under SXT-012 policy
including the declared tail span, the 3× determinism gate, then max/rms/corr
against the frozen model. Tracked with the sibling leaves' oracle-host
follow-up, #126.

Unlike the sibling aw-49 leaf, **no tap-instrumented engine build is
needed**: Logical has no RNG-seeded or wall-clock-dependent state
(`Logical4()` initialises every register deterministically, `fpFlip` starts
`true`, and the float `processReplacing` at this pin does no dithering or
noise shaping), so the adapter boundary alone is sufficient and an
unmodified pinned build can be used.

## 4. RTL-vs-frozen-model exactness — PASS

`rtl/effects/aw-4/logical4_core.sv` (+ `tb_logical4.sv`), Icarus Verilog
13.0, driven by `tools/compare_rtl_model_aw4.py`. Integer equality of every
output word and of a per-block, per-instance checkpoint covering all 24
control registers, the 12 detector targets, the 12 `avg`/`nvg` registers,
the 6 sag accumulators, the 24 sag ring words, `gcount` and `fpFlip`.

**17 cases, 435 blocks, 27,840 output words, 69,600 checkpoint fields, 0
mismatches.** All three `ratioselector` shapes are exercised, plus:

| Case | What it pins |
|---|---|
| `sel0-dad`, `sel1-snare`, `sel2-bass` | the three real carrier shapes (1/2/3 active stages) |
| `sel1-edge-3x101` | ratio fraction 2.4e-4, immediately above a selector boundary |
| `sel2-hot`, `clip-corner` | the ±36 hard clip engaged (511 clip events measured, asserted non-zero) |
| `sagclamp-corner` | the sag `control > 1` clamp branch engaged (34 events) |
| `wrap-1024` | 1,152 samples — crosses the 500-sample `gcount` period twice, so quirk Q1's age-3 tap is exercised repeatedly |
| `dc-asym` | sustained DC offset: drives one polarity's target toward its 1e-6 floor — the `c96` range case |
| `defaults`, `halfmix`, `extreme-lo`, `extreme-hi` | loader defaults, the wet/dry branch, and both extremes of every named parameter |
| `tail-silence`, `tail-resume` | the declared gain-recovery tail, and a second burst *after* it |
| `reset-mid` | panic/reset mid-tail restores the constructor state exactly |
| `dual-moogy` | the two Logical slots `Moogy Reese.fxp` actually carries, on two instances with disjoint state |

**Zero saturation events** were recorded in any case, at any frozen word,
including the reciprocal's int64 guard (`recip_saturations = 0` everywhere).
The guards are counted fail-closed paths, not routine ones.

The harness is pinned to the frozen-model revision: the model's revision
word is written into `cfg.hex` word 0 and echoed on the trace's `R` line. A
mismatch makes the comparator **REFUSE (exit 2)**, never PASS — see §5 NC-E.

`tools/compare_rtl_model_aw4.py` counts 108,288 reciprocal evaluations
across the suite. This is a **cost input**, recorded as F-028k-2, not a fit
claim: the harness uses the language `/` operator because its job is
exactness, not scheduling.

## 5. Negative controls — every one demonstrably FAILS the check it targets

### 5.1 RTL mutants (`rtl/effects/aw-4/logical4_mutants.sv`)

The mutant file does **not** re-implement the core: it `` `include ``s the
real `logical4_core.sv` with exactly one fault-injection macro selected, so
a control cannot drift away from the RTL it is a control for. Compiling it
with *no* defect selected is refused (`$fatal`), and the test suite asserts
the clean build defines none of the macros.

| Mutant | Defect | Case | Result | Declared blind spot |
|---|---|---|---|---|
| `NC_SHARED_STATE` | both instances read/write instance 0's state (the `tb_fx_shared_line.sv` defect) | `dual-moogy` | **FAIL** — 1,472 output + 2,426 checkpoint mismatches | — |
| `NC_SWAP_STAGES` | the A→B→C cascade evaluated in the wrong order (same-class permutation) | `sel2-bass` | **FAIL** — 1,536 + 1,846 | **cannot** be detected at `ratioselector 0`: permuting a one-element cascade is a no-op (measured on `sel0-dad`: undetected) |
| `NC_TAIL_KILL` | the plausible "nothing to do on silence" optimisation freezes the state on a zero block, dropping the tail | `tail-resume` | **FAIL** — 512 + 3,439 | **cannot** be detected without a silent block (measured on `sel1-snare`: undetected) — which is exactly what makes the declared tail span load-bearing rather than decorative |
| `NC_FIX_Q1` | quirk Q1 "fixed" to a constant 2-sample tap | `wrap-1024` | **FAIL** — 1,304 + 1,091 | a run shorter than one `gcount` period never reaches 498/499 |
| `NC_FIX_Q2` | quirk Q2 "fixed" so stage C's right channel updates its own target | `sel2-bass` | **FAIL** — 1,535 + 616 | **cannot** be detected while stage C is inactive (measured on `sel0-dad`: undetected) |

Each blind spot is measured and recorded rather than asserted, so a reader
can see which case a control actually depends on.

### 5.2 Model-side controls (`tools/aw4_negative_controls.py`, 7/7 CONTROL-OK)

Claim scope of this file is **model-vs-model only**; the frozen model is the
reference in every comparison, and the [PROPOSED] thresholds are used as a
substitution detector, not as an agreement verdict.

| Control | Result |
|---|---|
| **NC-A wrong order** — two same-class Logical slots swapped in series | **CONTROL-OK**: not bit-identical, and outside the [PROPOSED] thresholds (max 0.243, corr 0.996) |
| **NC-B shared state** — the two instances' histories pooled | **CONTROL-OK**: changes instance A's output **and** its state digest |
| **NC-C generic substitute** — a convenient generic peak compressor swapped in | **CONTROL-OK**: labelled **ADAPTED**, **refused from original-preset coverage**, and FAILS the thresholds |
| **NC-D dropped tail** — render truncated before the declared gain-recovery span, then resumed | **CONTROL-OK**: the resumed burst changes |
| **NC-E stale/silent stub** | **CONTROL-OK** ×3: an all-zero stub FAILS the thresholds (the check is not vacuous); the comparator **REFUSES** a harness pinned to a stale revision; and the revision word hashes the model **and** the tables, so editing either invalidates every committed pin |
| **NC-F bypass transparency** — `E_mix = 0` | **CONTROL-OK**: bit-exact dry, **and** an injected 1-LSB wet leak is detected, so the bypass check is live. The unmodified wet reference is retained throughout |
| **NC-G quirk fixes** — Q1 and Q2 "fixed" model-side | **CONTROL-OK**: both quirks are load-bearing |

**Recorded finding F-028k-3** (from NC-G): the quirk "fixes" change the
output but stay *inside* the [PROPOSED] SXT-023 effect-slice thresholds, so
a reference-agreement check at those thresholds would **not** discriminate
them. Only the exactness leg catches them. Routed to #12 as an input to the
budget freeze; it is not a reason to widen or narrow any budget here.

## 6. State residency, external memory, cost — [PENDING-SXT-016]

`artifacts/state-cost.json` (regenerable: `python3
model/effects/aw-4/logical4_model.py`; the test suite fails if the artifact
drifts from the frozen model).

* **External writable memory: 0 bytes. External traffic: 0 reads, 0 writes
  per frame.** The pinned `dL/bL/cL[1000]` arrays are *allocation*, not
  reachable state: only taps of age 2 and 3 are ever read (quirk Q1), so
  each line is a 4-word ring. This is **proved, not assumed** —
  `PinnedIndexSagLine` is a literal 1000-word transcription of the pinned
  indexing and `tests/test_sxt028k.py::test_compacted_sag_ring_matches_pinned_indexing`
  runs both over more than two full `gcount` periods (both wrap samples
  crossed repeatedly) and requires bit-exact agreement. Reporting the
  6,000-word allocation would misstate the cost; shrinking it *without* the
  proof would be a different algorithm.
* **On-chip per-instance state: 6,538 bits = 818 B**, itemised in
  `model/effects/aw-4/README.md`. Two concurrent slots = two disjoint
  records; nothing is pooled.
* **Shared read-only ROM: 6,650 B** (2 × 806 Q1.31 words), shared by every
  concurrent instance. ROM is never a substitute for writable state.
* Flash is not involved: this algorithm has no delay/reverb-class buffer,
  and flash could not substitute for writable state if it had one.
* **The fit verdict is [PENDING-SXT-016]** and is not claimed here. No
  number is invented.

## 7. Coverage — reported separately from agreement

**Newly supported presets: 0.** Nothing in this record makes any preset
supported. The issue's B4-scope candidate count (30 contributor presets, 0
factory) is an **upper bound on FX-scope candidacy**, not coverage: every
extracted carrier has `complete_wet_render_possible: false` because of
unlanded sibling FX classes, the voice stage and scheduling are out of
scope, and profile v1 (#12) is unfrozen. Support additionally requires the
model-vs-reference leg, which is NOT_RUN.

`reports/coverage-v1/leaf-verification.json` is **not** regenerated here:
coverage publication is #22 (SXT-029) and is an explicit non-goal of this
issue. Its `airwindows_leaves["4"]` row therefore still reads
`landed: false`; that row is stale in the same way the merged sibling leaves
#58/#59/#60/#61/#62/#64 left theirs, and it is #22's job to re-publish, not
this leaf's. Named here so the staleness is visible rather than silent.

## 8. Findings

* **F-028k-1 — the gain plane needs 96 bits, and that is a cost input.**
  `target` is a convex combination of values ≥ the squared polarity floor
  `1e-6`, so `calc = 1/target² ≤ 1e12` and the four-control sum `≤ 4e12`.
  That floor is **reachable** — a sustained one-polarity input drives the
  opposite target to it (the `dc-asym` case exists for this), so the range
  cannot be traded away. Meanwhile `totalmultiplier` is routinely ~1e-2, so
  a 64-bit Q42.21 word would quantise it at 4.8e-7 — a 4e-5 *relative* gain
  error dominating every other error term. Thirteen decades of dynamic range
  in one linear fixed-point word is 96 bits. A log-domain or block-floating
  control path would likely be much cheaper; it is named as future work and
  routed to #12 as a cost input. **Not** a fit or infeasibility claim.
* **F-028k-2 — arithmetic cost.** Each active stage needs two 128/64
  reciprocals per sample per channel: 12 per frame per instance at
  `ratioselector 2`, plus one table-interpolated `sin`/`1−cos` per stage per
  channel. A real implementation needs a sequential divider (or F-028k-1's
  log-domain path). Routed to #12 as a cost input; not a fit claim.
* **F-028k-3 — the [PROPOSED] budgets would not discriminate the pinned
  quirks.** See §5.2. Routed to #12.
* **F-028k-4 — a reference-side architecture dependence.** The pinned source
  declares `long double fpOld`, so `inputSample * fpOld` is evaluated in
  x87 80-bit on i386/x86-64 and in binary64 or binary128 elsewhere. The
  *reference* therefore differs by architecture; the frozen model quantises
  `fpOld`/`fpNew` once to Q1.31 and is architecture-independent. Recorded as
  a repeatability caveat for SXT-012/SXT-013: reference renders for this
  algorithm must pin the oracle-host architecture, exactly as they pin the
  commit.
* **F-028k-5 — `libs/airwindows` is MIT, not GPL-3.0-or-later.** Record 0006
  characterised the same vendored subtree as GPL-3.0-or-later; the subtree
  carries its own MIT `LICENSE` (c) 2018 Chris Johnson, stated again in its
  `README.md`. Recorded in DR-0015 with attribution retained. No SXT-028a
  decision, artifact or verdict changes — the finding is strictly more
  permissive than what 0006 assumed. The project's distribution-licence
  determination remains open (#25 / AGENTS.md).
* **The float transcription is not an oracle.**
  `model/effects/aw-4/float_transcription.py` is a second double-precision
  transcription used as a *structural* cross-check and as the ADAPTED
  substrate for NC-C. It shares the *reading* of the pinned source with the
  frozen model, so a misreading common to both would not be caught. It
  supports no fidelity claim, and the test suite asserts this record never
  cites it as one.

## 9. Reproduce

```sh
python3 model/effects/aw-4/logical4_model.py        # state + buffer report
python3 model/effects/aw-4/tables.py                # table self-test + .hex
python3 tools/extract_aw4_inputs.py                 # fail-closed extraction
python3 tools/aw4_evidence_artifacts.py             # state-cost / tail-window / oracle-status
python3 tools/compare_rtl_model_aw4.py --write-report   # RTL-vs-model exactness
python3 tools/aw4_negative_controls.py --write-report   # model-side controls
python3 tools/aw4_evidence_artifacts.py --check     # refuse a stale artifact
python3 -m pytest -q tests/test_sxt028k.py
# oracle host only (currently NOT_RUN / BLOCKED):
ORACLE_SURGE_DIR=... python3 tools/extract_aw4_inputs.py --mode oracle
```

## 10. What remains unproved

* Model-vs-pinned-engine agreement for this algorithm: **NOT_RUN**. No
  max/rms/corr number exists, at any budget.
* Every budget cited here is **[PROPOSED, not frozen]**; #12 owns the freeze
  and is routed to the product owner.
* Cost/fit, external-memory profile fit, polyphony and scheduling:
  **[PENDING-SXT-016]** / out of scope.
* No synthesis, place-and-route, timing, area, gf180mcu or hardware-playback
  result of any kind. The RTL is simulated only.
* Preset support: **0**. Musical quality and essentiality: **NO_VERDICT**,
  listening pending (#9).
