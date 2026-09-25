# SXT-038 evidence record — voice leaf: filter algorithm LP 24 dB

Branch: `feature/issue-72` · Issue: #72 (SXT-038) · Date: 2026-09-25

Engine pin (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`;
filter submodule `libs/sst/sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6`
with `libs/sst/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96`
(`oracle/manifest.json`).  Coefficient-maker configuration
`(dsamplerate_os, BLOCK_SIZE_OS) = (96000, 64)`.  LP 24 dB authority:
`FilterCoefficientMaker_Impl.h` (`MakeCoeffs` fut_lp24 dispatch, `Coeff_LP24`,
`Coeff_SVF`, `Map4PoleResonance`, `resoscale`, `clipscale`, `boundFreq`,
`ToCoupledForm`, `ToNormalizedLattice`, `FromDirect`, `db_to_linear`),
`QuadFilterUnit_Impl.h` (`SVFLP24Aquad`, `IIR24CFCquad`, `IIR24Bquad`),
`QuadFilterUnit.h` (subtype→kernel table), `FilterConfiguration.h`
(`fut_lp24` = 2, `fut_subcount` = 3), `SurgeVoice.cpp` (`SetQFB`/`GetQFB`,
`sampleRateReset`, the `CM.Reset()` + `FBP` zero path) and
`SurgeStorage.cpp` (`init_tables`, `note_to_pitch_ignoring_tuning`,
`note_to_omega_ignoring_tuning`) — **read and cited, never copied**.

**Claim discipline.** This record advances exactly two claims:
(1) *the RTL matches the frozen fixed-point model exactly* — iverilog-simulated,
integer equality, 11/11 cases, **PASS**; and (2) *the model reproduces the
pinned filter code within [PROPOSED] budgets* — measured, PENDING-FREEZE,
**7/11 cases PASS with 4 recorded misses** (§3, §4).  It establishes **no**
fidelity-policy freeze, **no** preset-support claim, **no** musical-quality
claim (no listening record exists), and **no** FPGA/gf180mcu synthesis,
timing, area, power, or hardware-playback claim.  The RTL is an
iverilog-simulated behavioural schedule, not synthesis-closed.

## 0. What the reference is — and the gap that is NOT closed

The executable oracle pinned by SXT-010 is a built `surgepy` on a macOS
evidence host.  **That host and that build are not available in the
environment this leaf was implemented in** (a Linux dispatch worker with no
Surge checkout and a host policy that forbids installing JUCE's system
dependencies).  A full-engine preset render was therefore impossible.

| Leg | Status |
|---|---|
| Full-engine preset render / oracle tap (SXT-037 DR-0005 class) | **NOT_RUN** — F-038-1 |
| Pinned filter submodule at the filter-stage boundary (DR-0009) | **RUN** — §3 |
| RTL vs frozen model | **RUN** — §2 |
| Human listening | **NOT_RUN** (out of scope for this leaf) |

**F-038-1 (bounded finding, open).** The reference used here is the pinned
*filter code* — `FilterCoefficientMaker` + the per-subtype quad kernel at the
pinned submodule commit, driven through the pinned voice-path per-block
sequence (`MakeCoeffs` → `updateState` → 64 kernel calls →
`updateCoefficients`) — **not** the full engine.  The surrounding voice graph
(oscillators, mixer, waveshaper, routing) and the carrier presets' own
modulation state (filter EG, LFOs) are not executed.  Consequences:
the control plane is a **declared fixture trajectory** (§1), and no statement
here is a preset-fidelity statement.  Nothing about this gap is worked
around: it is named in DR-0009, in every bundle `meta.json`
(`"kind": "pinned-filter-submodule"`, `"note": "…NOT a full-engine preset
render"`), and in §7.  When an oracle host is available, the same committed
case files and control planes drive a tap leg without changing the model or
the RTL.

## 1. Leaf scope, carriers and the control plane

One algorithm (`fut_lp24`), **all three engine-declared subtypes**:
`st_Standard`(0)→`SVFLP24Aquad`, `st_Driven`(1)→`IIR24CFCquad`,
`st_Clean`(2)→`IIR24Bquad`.  Observed corpus inventory (informational, not a
support claim): 842 presets carry an LP 24 dB unit — 596 Standard / 319
Driven / 81 Clean instances.  Declared parameter scope, frozen word lengths,
op order and the stability argument: `model/voice/filter_lp24/README.md`.

Carriers are real normalized corpus entries, extracted fail-closed from
`corpus/normalized/graphs.jsonl` (sha256 `c90424d9…`, verified at extraction)
by `model/voice/filter_lp24/extract_inputs.py`; the committed case files are
`reports/SXT-038/artifacts/cases/*.json`.

| case | preset (census blob) | scene/unit | subtype | cut / res / kt / em (ktR) |
|---|---|---|---|---|
| `edges` | `Argitoth/Rhythms/Edges Rhythm.fxp` (`099e8829…`) | B / 1 | **Driven** | 0.637 / 0.774 / 0 / 0 (60) |
| `chords-clean` | `Damon Armani/Pads/House Of Chords.fxp` (`ceaa96a8…`) | A / 1 | **Clean** | 70.0 / 0.0 / 0 / 0 (60) |
| `chords-std` | same preset | B / 1 | **Standard** | 70.0 / 0.0 / 0 / 0 (60) |
| `brass` | `Damon Armani/Plucks/Main Brass.fxp` (`53776653…`) | A / 1 | **Standard** | 70.0 / 0.0 / 0 / 0 (60) |
| `phase1` | `patches_factory/Sequences/Phase 1.fxp` (`52f18c7c…`) | A / 1 | **Driven** | 6.375 / **1.0** / 0.493 / 27.77 (60) |
| `major7mk2` | `patches_factory/Chords/Major 7 MkII.fxp` (`3bfc43d0…`) | B / 1 | **Clean** | −2.429 / 0.828 / 0.429 / 17.49 (60) |

The first three rows are the carriers named in issue #72 (all four instances
of them).  **All three named carriers store `kt = em = 0`**, so on their own
they hold the coefficient plane static after the first block and would never
exercise the keytrack/env-mod path, the `FromDirect` smoothing recursion, or
the per-sample `C += dC` reload.  `phase1` and `major7mk2` were added from
the issue's own recovery-basis list precisely to exercise those paths (and,
in `phase1`, resonance 1.0 as *stored by a real factory preset*).

Corners (derived, declared in the extractor): `edges-reso1` (res→1.0
self-oscillation), `edges-cut-hi` / `edges-cut-lo` (the pinned `boundFreq`
clamp edges +75 / −55), `edges-toggle` (mid-render Driven→Clean: `CM.Reset()`
+ `FBP` zero + `FromDirect` FirstRun, and the clipgain register moving from
`R[2]` to `R[4]`), `phase1-substd` (the third subtype at a live
keytrack/env-mod control plane).

**Control plane (declared boundary, identical for both legs).**  The
SurgeVoice arithmetic `cutoff_a = cutoff + kt·(note − ktR) + em·FEG`
(`SetQFB`, cited) is outside this leaf, as in the landed SXT-037 leaf.
`case_plan.py` evaluates it per block from the carrier's own normalized
parameters and the committed fixture sequences
(`fixtures/sequences/seq-notes-coverage-v1.json`, `…-holds-v1.json`), one
note segment per `note_on` event, each segment beginning with the engine's
voice-creation reset.  The FEG shape is a **declared fixture trajectory**
(A 20 ms, D 100 ms, S 0.5, note-off at 70 % of the segment, R 150 ms) — *not*
the preset's envelope, which is absent from the SXT-011 graph schema and
reachable only through the pinned engine (F-038-1).  It is a test
configuration, never an adapted preset, and both legs consume the identical
float32 words; the runner REFUSES if a bundle's control words differ from a
freshly rebuilt plan (live control NC-E).

**Stimulus (declared).**  The filter input signal is the real engine
voice-path signal captured at the filter-unit **input** boundary by the
SXT-037 oracle tap (DR-0005) and committed there
(`reports/sxt-037/artifacts/bundle-{badnews,rainy,t9}/units.bin`, sha256
verified on every load).  It is used as a *stimulus*, not as a reference; the
carriers' own audio is unavailable without the oracle (F-038-1).  Every
stimulus word is an integer whose float32 image is exact (`|q| < 2²⁴`,
enforced in both the Python loader and the C++ harness), so the two legs
provably see the same input.

## 2. RTL vs frozen model — EXACT

`rtl/voice/tb_lp24.sv` (iverilog 13, `-g2012`), stimulus emitted by the
frozen model (declared control-plane boundary: block-start `C[8]`/`dC[8]` +
subtype + reset flag streamed; inputs as Q10.21 words).  Integer equality at
every output sample and every declared checkpoint (end-of-block `R[0..4]`,
`C[0..7]`):

| case | samples | checkpoints | state/coef fields | verdict |
|---|---|---|---|---|
| edges | 124,416 | 1,944 | 27,216 | **PASS (0 mismatches)** |
| chords-clean | 124,416 | 1,944 | 27,216 | **PASS** |
| chords-std | 124,416 | 1,944 | 27,216 | **PASS** |
| brass | 124,416 | 1,944 | 27,216 | **PASS** |
| phase1 | 124,416 | 1,944 | 27,216 | **PASS** |
| major7mk2 | 124,416 | 1,944 | 27,216 | **PASS** |
| edges-reso1 | 24,576 | 384 | 5,376 | **PASS** |
| edges-cut-hi | 24,576 | 384 | 5,376 | **PASS** |
| edges-cut-lo | 24,576 | 384 | 5,376 | **PASS** |
| edges-toggle | 49,152 | 768 | 10,752 | **PASS** |
| phase1-substd | 24,576 | 384 | 5,376 | **PASS** |
| **total** | **921,600** | **14,400** | **201,600** | **0 mismatches** |

Artifacts: `artifacts/rtl-*.json`.  All three subtypes, both clipgain
register maps, the mid-render subtype toggle, both `boundFreq` clamp edges
and the self-oscillation corner run the same exact RTL schedule.  Control
NC-D (§6) shows the harness FAILs on a single-constant RTL mutation.

## 3. Model vs pinned filter code — [PROPOSED] budgets, achieved numbers

Budgets declared before the runs (`tools/compare_lp24_model.py`):
`L1 max|ΔC| ≤ 16 LSB` absolute **and** scale-relative,
`L2 max ≤ 4096 LSB`, `L2 rms ≤ 256 LSB`, stability `STABLE`.
Spectral correlation (≥ 0.999) is **reported but not gating** — SXT-037
recorded that metric as mis-scaled for filtered-voice spectra; both verdicts
(`verdict`, `verdict_including_spectral`) are emitted in every
`artifacts/compare-*.json` so nothing is hidden.  All numbers are Q10.21 LSB
on the leaf's own output, provider `surge-lut`.

| case | subs | L1 max (≤16) | L1 first-run only | L2 max (≤4096) | L2 rms (≤256) | dB rel ref peak | corr | L2b max / rms | model peak | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| brass | 0 | **0** | 0 | **3** | **0.7** | −130.4 | 0.9996 | 3 / 0.7 | 2,247,196 STABLE | **PASS** |
| chords-std | 0 | **0** | 0 | **2** | **0.7** | −125.5 | 0.9990 | 2 / 0.7 | 1,296,464 STABLE | **PASS** |
| chords-clean | 2 | **0** | 0 | **4** | **0.9** | −122.8 | 0.9964 | 4 / 0.9 | 2,097,152 STABLE | **PASS** |
| edges | 1 | **3** | 3 | **52** | **6.9** | −89.7 | 0.9763 | 9 / 2.1 | 9,875,152 STABLE | **PASS** |
| edges-cut-hi | 1 | **1** | 1 | **3** | **0.7** | −91.9 | 1.0000 | 3 / 0.7 | 45,414 STABLE | **PASS** |
| edges-cut-lo | 1 | **0** | 0 | **1** | **0.4** | −70.0 | 0.9952 | 1 / 0.4 | 4,820,123 STABLE | **PASS** |
| edges-toggle | 1,2 | **10** | 10 | **24** | **4.1** | −86.2 | 0.9881 | 4 / 0.9 | 3,905,061 STABLE | **PASS** |
| major7mk2 | 2 | 38 ★ | 29 | **1,194** | **169.0** | −74.8 | 0.9888 | 899 / 97.7 | 10,764,330 STABLE | **FAIL** (L1 only) |
| edges-reso1 | 1 | **3** | 3 | 5,086 ★ | 1,489.4 ★ | −57.3 | 1.0000 | 470 / 151.3 | 72,278,133 STABLE | **FAIL** (L2) |
| phase1 | 1 | 34 ★ | 5 | 14,471 ★ | 2,945.6 ★ | −52.6 | 0.9935 | 5,031 / 1,097.7 | 64,639,446 STABLE | **FAIL** |
| phase1-substd | 0 | 32 ★ | 0 | 17,242 ★ | 4,006.0 ★ | −50.3 | 0.9991 | 19,289 / 2,974.6 | 3,767,609 STABLE | **FAIL** |

`L2b` = the attribution leg: the model kernel driven by the **pinned**
coefficient plane, isolating kernel arithmetic from coefficient
construction.  Per-case verdicts: `artifacts/compare-*.json`; summary
`artifacts/budget-summary.json`.  **7/11 PASS, 4 recorded misses.**  Per the
fidelity policy these are input to the SXT-013/#12 freeze, NOT a fidelity
verdict in either direction, and **no budget was widened**.

### Reading (honest)

* **Every static-cutoff case is at the quantization floor** (L2 max 1–52 LSB,
  −70 to −130 dB).  The three carriers named in the issue all sit here.
* **The misses cluster on exactly two mechanisms**, both quantified:

  **F-038-2 — coefficient-smoothing drift is bounded by blockSize/2 = 32 LSB
  by construction.**  On every moving-coefficient case the L1 error splits
  cleanly: first-run-only (pure construction) error is 0–5 LSB for
  `phase1`/`phase1-substd`, while the full-run error is 32–34 LSB.  The cause
  is structural, not a modelling slip: `dC = (tC − C)/64` is quantized to the
  same Q10.21 word as `C` and then applied 64 times per block, so `C` can
  drift up to 64 × ½ LSB = 32 LSB from `tC` within one block, and the pinned
  per-block copy-back makes the drift persistent.  `major7mk2`'s 38 LSB is
  the one case where construction dominates (29 LSB first-run: the Clean
  lattice's `q1·q2` divisions at resonance 0.83).  Routed to SXT-013/#12 and
  SXT-016 as a **coefficient word-length question** (a wider `dC`
  accumulator, not a wider budget).  It was NOT fixed here because the
  Q10.21 universal word is the landed SXT-022 convention this leaf inherits,
  and changing it is a cross-leaf decision.
  **It also would not rescue the L2 misses** — see F-038-5.

  **F-038-5 — at ρ ≈ 1 the L2 error is kernel-state quantization, not the
  coefficient plane.**  `phase1` (a factory preset that stores resonance
  1.0), `edges-reso1` and `phase1-substd` place the pole essentially on the
  unit circle (the coupled-form `ar` reaches 1.0013; the Standard path's `Q1`
  goes negative), held bounded only by the pinned clipgain contraction.  The
  L2b legs show the error survives a perfect coefficient plane —
  `phase1` 5,031 LSB and `phase1-substd` 19,289 LSB with the pinned
  coefficients — i.e. a ~5·10⁻⁷ state quantum integrated over a marginally
  expansive loop.  Both legs stay **bounded and STABLE** (largest model state
  peak 72,278,133 LSB = 3.4 % of the s32 range), which is the corner's
  declared criterion, but the per-sample budget is missed and is recorded,
  not tuned away.

### Provider-independence leg (DR-0009 item 5)

The same cases rendered against sst-filters' own `BasicTuningProvider`
(`--provider exact`, zero input from this repository) instead of the
engine's table semantics:

| case | L1 max | L2 max | L2 rms |
|---|---|---|---|
| brass | 0 | 3 | 0.7 |
| chords-clean | 2 | 4 | 0.9 |
| edges | 46 | 694 | 96.9 |
| major7mk2 | 217 | 1,232 | 243.9 |
| phase1-substd | 32 | 17,207 | 3,990.8 |
| phase1 | 527 | 855,403 | 202,349.5 |

This is **not** a second fidelity claim; it measures how much the tuning
provider matters.  Two readings: (a) where the cutoff lands on an exact
semitone (`brass`, `chords-*` at +70 st) the two providers coincide, which is
why those rows are unchanged; (b) at resonance 1.0 (`phase1`) the provider
choice moves the output by 4.5 orders of magnitude, because the
self-oscillating trajectory is chaotic in the pole position.  The engine's
provider is `SurgeStorage`'s interpolated table (cited), so `surge-lut` is
the faithful leg and `exact` is the control — **F-038-6**: any future leaf
that models a resonant filter on exact trigonometry instead of the engine's
tables will disagree with the engine by orders of magnitude at the resonance
corner.

## 4. Stability corners — both legs

* **Reference leg:** finite, bounded outputs at resonance 1.0 (`phase1` peak
  0.599, `edges-reso1` peak 0.518), at both `boundFreq` clamp edges
  (`edges-cut-hi` 0.0136, `edges-cut-lo` 0.00061) and across the subtype
  toggle (0.0397) — per-bundle `meta.json` `run.peak_abs_out`.
* **Model leg:** `stability_verdict = STABLE` on all 11 cases; largest state
  peak 72,278,133 LSB (3.4 % of the s32 range) at `edges-reso1`.
* The monitor is not decorative: it reports UNSTABLE on saturation and on
  sustained exponential growth (unit-tested, `tests/test_sxt038_lp24.py`).

## 5. Costs vs SXT-016 probes and SXT-015 accounting (divergences recorded)

Measured from the frozen schedule (`qmul_count`, cross-checked against the
RTL's `qmul_count`), per instance per OS sample:

| subtype | kernel | MAC/OS-sample | ≈ MAC per 48 kHz sample (2× OS) |
|---|---|---|---|
| Standard | `SVFLP24Aquad` | **19** | 38 |
| Driven | `IIR24CFCquad` | **22** | 44 |
| Clean | `IIR24Bquad` | **28** | 56 |

plus ≤ 8 coefficient adds per sample and one block-rate `make_coeffs` per 64
OS samples.  State: 5 × 32-bit registers + 16 × 32-bit coefficient/delta
words = **672 bits per instance**.

SXT-016 planning row
`probe_filter__svf_tdf2_block_coeffs__a24__m32__onchip`:
**32 cycles/sample**, 32 mul + 32 add per sample, `state_ram_bits` = **192**,
replacing the SXT-015 placeholder `cyc_filter_unit_frame` = 150.  **Recorded
divergences, not reconciled away:**

1. The probe prices a **2-pole** SVF-class unit at 24-bit audio words; this
   leaf is the **4-pole** type, whose Standard kernel alone needs 19 MAC per
   OS sample = 38 per 48 kHz sample, i.e. **above** the probe's 32
   cycles/sample envelope at A-DSP-1c (one 32×32 MAC per cycle), and the
   Clean kernel needs 56.  A per-type SXT-016 row for `fut_lp24` is required
   before any closure statement; this leaf does not make one.
2. State is **672 bits** here (32-bit words, coefficient plane included) vs
   the probe's **192-bit**, register-only, 24/32-bit accounting — a 3.5×
   divergence driven by the two cascaded sections' five registers and by
   storing `C[8]`/`dC[8]` per instance (which the pinned per-voice `FBP` +
   `CM` likewise do).
3. The probe assumes A-SCHED-1 (scalar single lane); the pinned engine runs
   four voices per SIMD lane.  Not modelled here either way.

No gf180mcu synthesis, area, timing or power number is claimed or implied.

## 6. Negative controls (each must FAIL the check it targets)

`artifacts/negative-control.txt` (transcript) and
`artifacts/negative-controls.json`; the tool exits 0 only if **every** control
failed as designed.  **14/14 CONTROL-OK.**

| Control | Result |
|---|---|
| **NC-A wrong subtype** (the issue's required control) — Standard carrier forced to Driven; Driven forced to Clean; Clean forced to Standard | **CONTROL-OK** — budget FAIL on all three: max 444,409 / 180,951 / 642,014 LSB (rms 74,439 / 54,346 / 28,273), i.e. 2–4 orders of magnitude above the in-scope rows |
| **NC-B wrong algorithm** (the issue's required control) — the landed LP 12 dB leaf's `LP12CoeffMaker` + `LP12Unit` (`model/voice/filter_lp12`) substituted for LP 24 dB on the same control plane | **CONTROL-OK** — budget FAIL: `edges` max 217,485 LSB (rms 42,800), `phase1` max 1,862,200 LSB (rms 716,422) |
| **NC-C applicability boundary** — subtype 3 (maker and kernel), resonance 1.5 and −0.25, cutoff ±300 st, and a case file declaring `fut_lp12` | **CONTROL-OK** — all 7 REFUSED (exit-2 class); out-of-scope input is never silently clamped |
| **NC-D RTL mutant** — `rtl/voice/lp24_broken_mutant.sv`, one constant changed (qmul round-half-up bias 2²⁰ → 2¹⁹) | **CONTROL-OK** — exactness FAIL, 31 mismatches from block 0 |
| **NC-E control-plane tamper** — one block's cutoff word shifted by +1 st in the reference bundle | **CONTROL-OK** — runner REFUSES, proving the both-legs-same-control-plane guard is live rather than assumed |

## 7. What this leaf establishes — and what it does not

**Establishes:** the LP 24 dB filter leaf itself — a frozen fixed-point model
with documented word lengths and op order, RTL-vs-model **EXACT** over
921,600 samples and 201,600 checkpoint fields across all three subtypes and
the reload path (§2); measured agreement with the pinned filter code at the
filter-stage boundary with achieved numbers and two quantified findings
(§3); bounded/STABLE behaviour at the resonance and clamp corners on both
legs (§4); a fail-closed applicability boundary; and a live control set
(§6).

**Does not establish:** any full-engine comparison (F-038-1), any complete
preset render, any preset-support or fidelity claim, any fidelity-budget
freeze, any listening or musical-quality judgement, and any FPGA/gf180mcu
synthesis, place-and-route, timing, area, power or hardware-playback result.
The issue's recovery-basis attribution (49 slate-basis presets, 459/1,685
corpus B4-predicted) is a **requirement attribution**, not a coverage claim:
it stays gated on #12/#48, and `fixture_verified_paths` is deliberately
empty.  Coverage-ledger entry `filter_type:LP 24 dB`:
`rtl_vs_model: PASS`, `model_vs_reference: PARTIAL` (7/11 cases within
[PROPOSED] budgets, PENDING-FREEZE, findings recorded),
`fixture_verified_paths: []`.

### Findings index

| ID | Finding | Routed to |
|---|---|---|
| F-038-1 | No executable oracle in this environment; the reference is the pinned filter submodule, not the full engine | DR-0009; a tap leg when an oracle host is available |
| F-038-2 | Coefficient-smoothing drift is structurally bounded by blockSize/2 = 32 LSB in the Q10.21 universal word | SXT-013/#12 (budget form), SXT-016 (coefficient word length) |
| F-038-3 | The landed SXT-037 LP12 model builds `Coeff_SVF`'s `F1` with sample rate 48 000, whereas the pin configures the coefficient maker with `dsamplerate_os` = 96 000 | #71 (sibling leaf) — **not changed here** |
| F-038-4 | The landed SXT-037 LP12 model uses Surge's dB lookup table for `clipscale`, whereas sst-filters' `clipscale` calls its own exact `pow(10, 0.05·x)` | #71 (sibling leaf) — **not changed here** |
| F-038-5 | At ρ ≈ 1 the L2 misses survive a perfect coefficient plane: they are kernel-state quantization in the 32-bit word | SXT-013/#12, SXT-016 |
| F-038-6 | Modelling a resonant filter on exact trigonometry instead of the engine's interpolated tables diverges by orders of magnitude at the resonance corner | future filter leaves; recorded here with numbers |

F-038-3 and F-038-4 were found by building this leaf against the pinned
source and are reported, not silently fixed: SXT-037 is landed evidence and
amending it belongs to #71, not to this PR.

## 8. Licensing / provenance

All files added by this leaf — `model/voice/filter_lp24/*`,
`rtl/voice/tb_lp24.sv`, `rtl/voice/lp24_broken_mutant.sv`,
`oracle/sxt038/*`, `tools/{render_lp24_reference,compare_rtl_model_lp24,
compare_lp24_model,lp24_negative_controls,run_sxt038_checks}.py`,
`tests/test_sxt038_lp24.py` and `reports/SXT-038/*` — are original to this
repository (Apache-2.0, `LICENSE`).  No Surge/sst source, table, preset or
asset is copied into this repository: engine structure and table
*construction formulas* are cited by file and symbol.  The reference harness
binary is a GPL-3.0-or-later combined work built into an external directory
(`~/.cache/sxt038-oracle` by default; the build script refuses a path inside
the repository), never committed and never distributed.  Licensing decision:
**decision-records/0009** (PROPOSED — pending owner ratification).  This
repository has made no distribution-license determination.

## 9. Artifacts and reproduction

Committed under `reports/SXT-038/artifacts/`: `cases/*.json` (11 case files),
`bundle-*/meta.json` (11, each pinning the harness source sha256, both
submodule SHAs, the compiler, and the sha256 of every stream it produced),
the full reference streams (`coeffs.jsonl`, `units.bin`, `regs.bin`) for four
representative bundles (`edges` — Driven, `chords-clean` — Clean, `brass` —
Standard, `edges-toggle` — reload), `rtl-*.json` (11 exactness verdicts),
`compare-*.json` + `budget-summary.json` (11 budget rows),
`negative-control.txt` / `negative-controls.json`.  Streams for the other
seven bundles are not committed because they are regenerated **byte-identically**
by the command below (verified against the committed sha256s by step 1 of the
runner) — unlike the SXT-037 tap bundles, this reference needs no oracle host.

```sh
python3 tools/run_sxt038_checks.py      # steps 0-5; needs git, network, g++ (C++20), iverilog
python3 -m pytest tests/test_sxt038_lp24.py
```

Runner status at this branch's tip (full run, ~2 min):

```
0_cases_match_corpus       PASS
1_reference_render         PASS
1_reference_byte_stable    PASS
2_model_legs               PASS
3_rtl_exactness            PASS (all cases exact)
4_budgets                  7/11 cases PASS the [PROPOSED] budgets (4 recorded misses)
5_negative_controls        PASS (all controls failed their target check)
```

Environment for the numbers above: Linux x86-64, g++ 13.3.0
(`-O2 -std=c++20 -msse4.2 -ffp-contract=off -DSIMDE_UNAVAILABLE`), iverilog
13.0, python 3.12.  Reference-dependent budget checks are deliberately NOT
pytest cases, so an absent reference can never be reported as a pass.
