# Shared `HalfbandD2` zero-input limit cycle — declared bound (F-176-2, issue #181)

Issue: [#181](https://github.com/2AMLogic/gf180-surge/issues/181) (raised as
finding **F-176-2** by [#176](https://github.com/2AMLogic/gf180-surge/issues/176)
/ SXT-026, reported there, not resolved there).
Date: 2026-09-28.
Harness: `tools/measure_halfband_limit_cycle.py`.
Artifact: `artifacts/zero-input-limit-cycle-sweep.json`.

**Outcome.** `model/voice/voice_model.py::HalfbandD2` — the **shared** Q10.21
scene decimator modelling `sst::filters::HalfRate::HalfRateFilter(M = 6,
steep)::process_block_D2` — does not return to the zero state when its input
goes silent. Its round-half-up `qmul` gives the allpass recursion
`y[n] = x[n-2] + a·(x[n] − y[n-2])` a dead band with non-zero fixed points, so
after the last voice dies the filter holds a **permanent, non-decaying
output-Nyquist (period-2) output**. #176 saw one impulse case settle at ±26
Q10.21 LSB; one case is not a bound. Measured across a declared 315-case input
sweep, the worst settled amplitude is **36 Q10.21 LSB = 0.5625 int16 LSB ≈
−95.3 dBFS** — still **below one int16 LSB** (64 Q10.21 LSB), so the issue's
escalation clause did not fire.

**Disposition (SXT-017 visible-contract rule): option (a) — DECLARE.** The
limit cycle and this measured bound are now a declared property of the frozen
`HalfbandD2`, written where a reader of each affected leaf will meet it (§6).
Option (b) — changing the decimator's rounding so the zero-input state decays
to zero — is **not** done here: it changes the frozen model's numerical
behavior in every consumer and therefore needs an SXT-017 /
[#12](https://github.com/2AMLogic/gf180-surge/issues/12) contract-revision
record plus coordinated changes to four RTL files and re-measurement of every
affected leaf. No such record exists, and the issue's stop condition forbids
proceeding without it.

## Claim discipline (AGENTS.md)

This record advances exactly two claims and no others:

1. **A measured property of the frozen fixed-point model** — the zero-input
   settled amplitude of `HalfbandD2` over a declared input range (§2), with a
   live failure control (§4).
2. **RTL == frozen model, exact (integer equality)**, over that same sweep
   including the settled region, for all **four** RTL copies of the decimator
   (§3).

It establishes **no** model-vs-reference (fidelity) verdict, **no**
preset-support or musical-quality claim, and **no** FPGA / gf180mcu synthesis,
timing, power, area or hardware-playback result. No reference render is read
and the pinned engine is not executed anywhere in this record; the
float-versus-fixed contrast in §5 is an emulation of the model's own recursion,
explicitly **not** a pinned-kernel measurement (which is `NOT_RUN` here).

## 1. Method: the settled amplitude is measured EXACTLY, not extrapolated

A finite tail cannot distinguish "still ringing" from "will never stop". The
harness therefore does not read a tail at all:

* each case drives the decimator with its declared stimulus (32 blocks = 2,048
  input samples) and then cuts the input to zero;
* during the silence the filter's **full 72-word state** (`bx`/`by`/`ax`/`ay`,
  6 stages × 3 taps × 2 branches × 2 arrays) is hashed after every 64-sample
  engine block;
* when a state recurs, the block sequence between the two occurrences repeats
  **forever by construction** — the zero-input map is deterministic — so the
  recorded settled amplitude is a proof about the infinite future, not an
  observation about a finite render;
* the reported period is reduced to the minimal output period of that cycle;
* a case that reaches no recurrence inside the 4,096-block cap is reported
  **NO_VERDICT** (`settled_peak_q21: null`) and makes the tool exit non-zero.
  It is **never** reported as zero. **0 of 315 cases were NO_VERDICT.**

**Declared input range.** Every consumer clips the decimator's input to ±8.0 —
the engine's `sceneout` hard clip — immediately upstream (`model/voice/
run_model.py` `limit_i(±qint(8.0))`, `rtl/voice/tb_voice.sv` `clamp8`), so the
declared range is |x| ≤ 8.0 in Q10.21 and the sweep includes the range end.

## 2. The declared input sweep and its worst case — **MEASURED**

315 cases; every case is a stimulus followed by silence. Amplitudes span one
Q10.21 LSB (`1/2097152`) to the ±8.0 clip: `{1 LSB, 1e-4, 1e-3, 0.01, 0.1,
0.25, 0.5, 1.0, 2.0, 4.0, 8.0}`, in both signs for impulse and DC.
Frequencies are fractions of the 96 kHz **decimator input** rate — the
transition sits at 0.25 (the 48 kHz output Nyquist), so `< 0.25` is passband
and `> 0.25` is stopband — swept over 35 values from 0.002 to 0.5 including
both band edges (0.2495 / 0.25 / 0.2505) and the input-rate Nyquist (0.5).

| family | cases | worst settled peak (Q10.21 LSB) | cases settling to exactly 0 |
|---|---|---|---|
| impulse (both signs) | 22 | 26 | 2 |
| DC (both signs) | 22 | **36** | 2 |
| sine (35 freqs × 5 amps) | 175 | **36** | 5 |
| square (12 freqs × 3 amps) | 36 | **36** | 0 |
| two-tone (6 pairs × 2 amps) | 12 | **36** | 0 |
| seeded uniform noise (6 amps × 8 seeds) | 48 | **36** | 0 |
| **all** | **315** | **36** | **9** |

**Stated worst case: 36 Q10.21 LSB**, reached by 124 of the 315 cases
(alphabetically first: `dc a=+0.01`). In engineering units:

| quantity | value |
|---|---|
| worst settled peak | **36 Q10.21 LSB** |
| in int16 LSB (1 int16 LSB = 64 Q10.21 LSB) | **0.5625** |
| in dBFS | **−95.31** |
| above one int16 LSB? | **no** — escalation clause did not fire |
| period of every non-zero cycle | **2 output samples** (24 kHz = output Nyquist) |
| cases with a non-zero cycle | 306 / 315 |
| cases settling to exactly 0 | 9 / 315 |
| distinct settled peaks observed | 0, 1, 4, 5, 7, 8, 9, 10, 11, 13, 16, 17, 18, 19, 20, 25, 26, 27, 28, 33, 35, 36 |
| largest lead-in before the cycle is entered | **2,304 input samples** (36 blocks) |

Structure of the cycles, recorded because it is what a hardware idle-noise
claim would need: **every** non-zero cycle has output period 2, i.e. it is an
alternating-sign tone at exactly the 24 kHz output Nyquist. 294 of the 306 are
exactly antisymmetric (`[+p, −p]`); the remaining 12 are `[−p, p+1]`-shaped,
i.e. the same Nyquist tone with a **1-LSB DC offset** (cycle sum = 1), e.g.
`impulse a=+1e-4 → [−6, 7]` and `sine f=0.4050 a=0.01 → [+28, −27]`. The 9
cases that do settle to exactly zero are the 4 smallest-amplitude cases
(±1 Q10.21 LSB impulse and DC) and all 5 amplitudes at f = 0.5 (the input-rate
Nyquist, which the decimator's own structure annihilates).

The larger picture the per-case data shows: **the settled amplitude is set by
the state the filter happens to be left in, not by how loud or how band-limited
the stimulus was.** The 8.0-amplitude cases and the 0.01-amplitude cases reach
the same 36-LSB cycle; louder input only lengthens the lead-in (`dc a=+0.01`
enters its cycle after 320 input samples, `dc a=+8` after 1,472). That is why
one impulse case could not have bounded this and why the sweep is the
acceptance condition.

## 3. Do the RTL copies reproduce it exactly? — **CHECKED, PASS** (claim (1))

**There are four copies, not the three #181's body names.** The
[#180](https://github.com/2AMLogic/gf180-surge/issues/180) contract revision
(`decision-records/0018-wavetable-scene-decimation-placement.md`) landed while
this measurement was being made: it moved the wavetable leaf's decimator to a
per-scene stage and implemented it in
`rtl/oscillators/wavetable/tb_wavetable.sv`. That file is checked here too, and
the harness's copy list is asserted against a **scan of `rtl/`** rather than
being trusted as a hand-maintained list
(`tests/test_halfband_limit_cycle.py::rtl_files_containing_the_cascade`; the
leaves' declared single-mutation `*mutant*.sv` controls are excluded on purpose
— they must disagree). The scan keys on a `decimate_and_output` task carrying
the cascade's own state words, so a next copy written in that shape cannot be
silently left out; a copy that renamed those words could still evade it. The
scan is a guard against forgetting, **not** a proof of completeness, and the
same list also drives `artifacts/rtl-splice-provenance.txt` (§8), so a copy
count that changes without the transcript being regenerated fails CI.

Re-typing the cascade into a hand-written probe would only check the re-typing.
Instead each RTL copy's own `decimate_and_output` **cascade loop**,
**reconstruction assignment** and **arithmetic helper functions** are extracted
**verbatim** from the `.sv` file and spliced into a generated probe; the only
substitutions are that file's coefficient window (→ `HB_B[·]` / `HB_A[·]`) and
leading whitespace. Every one of the 315 declared cases is run through each
probe under `iverilog -g2012`, followed by exactly the silence the model needed
to reach its cycle **plus 8 further blocks**, so the compared window provably
contains the settled region and not merely the decay. Compared sample-for-sample,
integer equality:

| RTL copy | dialect | coefficient window | out samples | settled-region samples | settled-region mismatches | settled-peak disagreements | unexplained mismatches | verdict |
|---|---|---|---|---|---|---|---|---|
| `rtl/voice/tb_voice.sv` | `cfg32` | `cfg[28+i]` / `cfg[34+i]` | 577,760 | 90,720 | **0** | **0** | **0** | **PASS** |
| `rtl/oscillators/classic/tb_classic.sv` | `cfg32` | `cfg[68+i]` / `cfg[74+i]` | 577,760 | 90,720 | **0** | **0** | **0** | **PASS** |
| `rtl/oscillators/sine/tb_sine.sv` | `cfg32` | `cfg[57+i]` / `cfg[63+i]` | 577,760 | 90,720 | **0** | **0** | **0** | **PASS** |
| `rtl/oscillators/wavetable/tb_wavetable.sv` (#180) | `iw64` | `iw[43+hi]` / `iw[49+hi]` | 577,760 | 90,720 | **0** | **0** | **0** | **PASS** |

The three `cfg32` copies' cascade text is **identical** after coefficient-window
normalization, so that decimator is one implementation written out three times.
The wavetable copy is a **different dialect** — 64-bit allpass state, `iw[]`
coefficients, Verilog-2001 loop style, its own `q21`/`qround_s`/`clamp8_64`, and
the ±8 clip *inside* its cascade loop rather than upstream of it. Its cascade
**text** is therefore deliberately **not** compared against the other three
(that would be a false equivalence); what is compared is its **output** against
the same frozen model, which is the claim that matters. The artifact records the
text groups by sha256 and the per-dialect verdict rather than one
"identical everywhere" boolean.

The reconstruction lines are **not** identical, and the difference is reported
rather than normalized away:

| copy | reconstruction, verbatim |
|---|---|
| `tb_voice.sv` | `bl = qround1(chainb[2*k] + chaina[2*k+1]);` |
| `tb_classic.sv` | `bl = clamp8(qround1(chainb[2*k] + chaina[2*k+1]));` |
| `tb_sine.sv` | `bl = clamp8((chainb[2*k] + chaina[2*k+1] + 32'sd1) >>> 1);` |
| `tb_wavetable.sv` | `bl = qround_s(chain_b[2*hk] + chain_a[2*hk+1], 1);` |

The shared model class contains no ±8 clip at that point (the voice and
wavetable leaves apply the equivalent clip upstream of the decimator instead),
so on the loudest sweep cases the two oscillator copies clip where the model
does not: 3,675 of 577,760 samples on each, **all** of them satisfying "model
word outside ±8 and RTL word exactly at the clip", i.e. explained by that leaf's
own clip stage and not by decimator arithmetic. **0 unexplained mismatches, and
0 mismatches of any kind inside the settled region on all four copies** — the
settled amplitude is byte-identical between model and every RTL copy.

### Is the ring-out inside each leaf's own committed compared window?

The acceptance criterion asks this specifically, so it is answered per leaf by
**running that leaf's own committed comparator** on that leaf's own fixture and
reading its reported mono-sample count back against the render length — not by
inferring it from the sweep and not by reading the comparator's source:

| leaf | fixture | blocks after last voice death | ring-out inside the committed comparator's window? | post-death mono peak | comparator verdict (mismatches) |
|---|---|---|---|---|---|
| voice (SXT-022 / 026a / 034) | `seq-notes-repeated-v1` | 3,703 (118,496 samples) | **yes** — 196,800 mono samples compared = every sample of all 6,150 blocks | ±1 Q10.21 LSB, held for all 3,703 | `compare_rtl_model.py` **PASS** (0) |
| osc:Classic (SXT-033) | `horn / seq-notes-repeated-v1` | 3,519 (112,608 samples) | **yes** — 196,800 mono samples compared = every sample of all 6,150 blocks | ±2 Q10.21 LSB, held for all 3,519 | `compare_classic_rtl_model.py` **PASS** (0) |
| osc:Sine (SXT-040) | `tentacles / seq-notes-repeated-v1` | 3,702 (118,464 samples) | **yes** — 196,800 mono samples compared = every sample of all 6,150 blocks | **exactly 0** | `compare_sine_rtl_model.py` **PASS** (0) |
| osc:Wavetable (SXT-026, per-scene since #180) | `mf-wtfix / seq-notes-repeated-v1` | — | **NOT_RUN — not answered here** | — | `compare_wt_rtl_model.py`: the model render needs the **external** pinned wavetable asset root, absent on this host |

Two of those rows need stating plainly:

* **SXT-040 / `tentacles` shows exactly 0 after voice death.** That is this
  fixture's master gain quantizing the cycle away at the output, **not** an
  exemption for `tb_sine.sv`'s decimator — the same file's spliced cascade
  reproduces the 36-LSB cycle exactly in §3. Absence at one fixture's output is
  a fixture property.
* **SXT-026 (wavetable) is `NOT_RUN` — neither a pass nor an exemption.** #180
  changed the answer for this leaf mid-measurement. *Before* it, the leaf's RTL
  carried no decimator or 48 kHz stage and `compare_wt_rtl_model.py` did not
  read `mono_block` at all, so the ring-out region genuinely sat outside its
  compared window (the declared #176 boundary). *After* it, the per-scene stage
  is in `tb_wavetable.sv` and the comparator compares every 48 kHz `mono_block`
  sample on every block **including blocks with no live voice**, so the region is
  inside the window by construction of the comparator. This record does not
  convert that into a measured verdict: the model render needed to drive it
  requires the external pinned wavetable asset root (`decision-records/0004`),
  which this host does not have, so the leg is reported `NOT_RUN` with its
  reason. #180's own record states its measured base PASS (0 mismatches, 132,000
  48 kHz samples) from a host that had the asset. What this record *does*
  establish for that file is §3: its spliced cascade reproduces the settled
  amplitude exactly on all 315 declared cases.

The post-death mono peaks (1 and 2 Q10.21 LSB) are **smaller** than the 36-LSB
bound because they are measured after the master-amplitude stage, downstream of
the decimator; 36 LSB is the bound at the decimator's own output, which is where
the declared property lives.

## 4. Failure control — **PASS** (required by the issue)

The control the issue names: the same 315-case sweep run against
`ZeroedAtBlockBoundary`, a subclass whose `process()` resets the decimator's
state at every block boundary. If a measurement still reported a non-zero
settled amplitude under it, the harness would be observing the fixture rather
than the filter's own persistent state.

| control leg | result |
|---|---|
| control cases run | 315 |
| control cases with a non-zero settled amplitude | **0** (requirement: 0) |
| uncontrolled cases with a non-zero settled amplitude | **306** (requirement: > 0) |
| verdict | **PASS** |

The control is two-sided on purpose: it also fails closed when the
*uncontrolled* sweep finds nothing non-zero, because a control that drives
zero to zero demonstrates nothing. Transcript: `artifacts/failure-control.txt`.

## 5. Is it the recursion or the quantizer? — float64 contrast

Run on the same 306 cases that show a cycle, with the **same** recursion and
the **same** quoted coefficients (`vm.HALFBAND_A`/`HALFBAND_B`) in float64 and
the Q10.21 quantization removed, the tail after 2,048 blocks (131,072 input
samples) of silence peaks at **1.8e-322 in Q10.21 LSB units** (worst case
`dc a=+1e-4`) — i.e. it is decaying into float64 subnormals — and **all 306**
round to exactly 0 at Q10.21. The dead band comes from the quantizer, not from
the recursion or the coefficients, which is why this is declared as a
**word-length consequence of the Q10.21 freeze**.

**This is an emulation of the model's own recursion, not the pinned kernel.**
Executing the pinned `HalfRateFilter(M = 6, steep)` needs the external oracle
host (`oracle/sxt022/build_halfband_probe.sh`, which refuses to build inside
the repository); that host is unavailable here, so a **pinned-kernel zero-input
measurement is `NOT_RUN`** and is not assumed from this leg. The pinned kernel's
float32 arithmetic could in principle have a dead band of its own at a far
smaller scale; nothing here rules that in or out. (The existing pinned-kernel
harness in `reports/halfband-branch-order/` measured branch **ordering**, not
zero-input settling.)

## 6. Where the declaration is recorded (the third acceptance box)

Not only in this directory, and not only in `reports/sxt-026/`:

| file | what it now says |
|---|---|
| `model/voice/README.md` | §"DECLARED word-length consequence" under the frozen arithmetic rules (the rule-2 round-half-up rule that causes it), plus a pointer at block-schedule step 7. Covers SXT-022 / 026a / 032 / 034 / 035 / 042, which share this README. |
| `model/oscillators/classic/README.md` | word-length section: the declaration + this leaf's in-situ ±2 LSB result |
| `model/oscillators/sine/README.md` | word-length section: the declaration + why this leaf's in-situ 0 is a fixture property |
| `model/oscillators/wavetable/README.md` | limit-cycle note attached to declared deviation 7 (per-slice placement) |
| `reports/sxt-022/EVIDENCE.md` | deviation 6 (declared, with the in-situ numbers and the statement that no acceptance metric moves) |
| `reports/sxt-026a/EVIDENCE.md` | §9 disclosure |
| `reports/SXT-033/EVIDENCE.md` | finding F-033-4 |
| `reports/SXT-040/EVIDENCE.md` | finding F-040-6 |
| `reports/sxt-026/EVIDENCE.md` | F-176-2 disposition paragraph: option (a), with the measured bound replacing the single-impulse ±26 |
| `tests/test_halfband_limit_cycle.py` | keeps the declared bound and the declaration text true of the committed tree |

## 7. What this does and does not license

**Does:** state that a musically silent scene is not numerically silent, with
an exact bound (36 Q10.21 LSB at the decimator output; 24 kHz Nyquist tone;
0–2 Q10.21 LSB after master gain on the three measured fixtures) that any
future hardware idle-noise, idle-power or output-stage-gain claim must carry
forward. A −95 dBFS Nyquist tone is inaudible in an int16 render and can still
be a real measurement on hardware after an output stage's own gain.

**Does, precisely enough to be falsified:** 36 Q10.21 LSB is 0.5625 int16 LSB,
so `int(clip(x, −1, 1)·32767)` truncates the cycle to 0 unless the master
amplitude reaches 64/36 = 16/9 ≈ **1.7778**. That is the whole of the "cannot
reach an int16 render" statement — a bound with a stated crossing point, not a
claim that the cycle is harmless in general.

**Does not:**

* revise any budget, verdict or render. No committed leaf number changes as a
  result of this measurement, and none was re-derived to accommodate it.
* establish that the pinned engine settles to zero (§5 — `NOT_RUN`).
* bound `model/effects/type-distortion/distortion_model.py::HalfbandD2` or its
  SSE sibling. Those are a **different class** — `HalfRateFilter(M = 3)`,
  Q24.43 allpass state, oversampling rather than scene decimation — and their
  dead-band behavior is **not measured** here. No bound in this record applies
  to them.
* license option (b). Changing the arithmetic remains an SXT-017 / #12 contract
  revision affecting 5+ leaves and 4 RTL files.

## 8. Artifacts (this directory)

| artifact | content |
|---|---|
| `artifacts/zero-input-limit-cycle-sweep.json` | the whole measurement: per-case settled amplitudes for all 315 cases, the summary and stated worst case, the failure-control block, the float contrast, the spliced-RTL leg per copy, the in-situ leaf legs with each leaf's committed-comparator summary |
| `artifacts/failure-control.txt` | §4's transcript, including the control class verbatim and three mutated-input checks showing the control can FAIL |
| `artifacts/rtl-splice-provenance.txt` | §3's splice, for **all four** copies: each `.sv` file's sha256, its coefficient window, the verbatim cascade and reconstruction text, the generated probe's sha256, and the per-dialect / per-group text comparison (never one "identical everywhere" boolean) |

The generated probe testbenches are **deliberately not committed** (their banner
says so): they are derived files whose content is fully determined by the four
`.sv` sources plus the tool, and committing them would create a second copy of
the decimator's text that could drift from the one being checked. Their sha256s
are recorded so a reviewer can regenerate and compare.

`artifacts/rtl-splice-provenance.txt` is itself **generated**
(`tools/measure_halfband_limit_cycle.py --provenance`), and everything below its
`=== BEGIN DERIVED BODY ===` marker is re-derived byte-for-byte by
`tests/test_halfband_limit_cycle.py`
(`test_splice_provenance_declares_exactly_the_rtl_copies_under_test`,
`test_splice_provenance_body_is_reproducible_byte_for_byte`,
`test_splice_provenance_makes_no_cross_dialect_identity_claim`, with a live
synthetic-fifth-copy control). The hand-written version of this transcript went
stale the moment #180's fourth copy landed — it still said "three `.sv` files"
and still closed with a single "cascade text identical across copies: True",
i.e. the cross-dialect equivalence this record declines to assert. That failure
mode is now a test failure, not a silent one: adding, removing or editing a
spliced copy without regenerating the transcript fails CI.

## 9. Reproduce

```bash
# model sweep + required failure control + float contrast (~1 min)
python3 tools/measure_halfband_limit_cycle.py \
    --out /tmp/hblc.json

# + the verbatim-spliced RTL leg for all four copies (needs iverilog, ~4 min)
python3 tools/measure_halfband_limit_cycle.py --rtl --out /tmp/hblc.json

# + the in-situ leaf legs and each leaf's own committed comparator
# (this is the committed artifact; ~31 min, most of it the sine leaf's tb)
python3 tools/measure_halfband_limit_cycle.py --rtl --leaves --leaf-rtl \
    --out reports/halfband-limit-cycle/artifacts/zero-input-limit-cycle-sweep.json

python3 -m pytest tests/test_halfband_limit_cycle.py -q
```

Exit status is load-bearing: `1` if any case is NO_VERDICT, if the failure
control does not hold, or if the spliced-RTL leg is not exact; **`2` if the
worst settled amplitude reaches one int16 LSB**, which is the issue's
escalate-to-#12 condition rather than something the tool absorbs.

## 10. Licensing / provenance

`tools/measure_halfband_limit_cycle.py`, `tests/test_halfband_limit_cycle.py`
and this record are original to this repository (Apache-2.0, `LICENSE`). No
Surge or SST source, table, preset or asset is copied here, and no pinned GPL
code is compiled by this harness (the RTL leg splices **this repository's own**
`.sv` text). The twelve halfband allpass coefficients were already adopted under
`decision-records/0002-halfband-coefficients.md`; nothing new is adopted.
