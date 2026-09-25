# SXT-039 evidence record — voice leaf, filter algorithm: LP Legacy Ladder

Branch: `feature/issue-73` · Issue: #73 (SXT-039) · Date: 2026-09-25

Engine pin (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, filter
submodules `libs/sst/sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6`
and `libs/sst/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96`
(`oracle/manifest.json`); 48 kHz engine, filter stage at `dsamplerate_os`
96 kHz, OS block 64. Algorithm authority: pinned `FilterConfiguration.h`
(`fut_lpmoog` id 3, "LP Legacy Ladder", 4 declared subtypes),
`FilterCoefficientMaker_Impl.h` (`MakeCoeffs` → `Coeff_LP4L`, `FromDirect`),
`QuadFilterUnit_Impl.h` (`LPMOOGquad<subtype>`, `GetQFPtrFilterUnit`),
`sst-basic-blocks Clippers.h` (`softclip8_ps`), `SurgeStorage.cpp/.h`
(`note_to_pitch_ignoring_tuning` + its table construction formulas),
`SurgeVoice.cpp` (the `cutoffA` keytrack/env-mod arithmetic, the per-voice
`FBP` zero-init, the type/subtype-change `memset` + `CM.Reset()` path, and
the per-block register/coefficient read-back) — **read and cited, never
copied**.

**Claim discipline.** This record advances exactly two of the three claims,
and bounds the second one precisely:

1. *The RTL matches the frozen fixed-point model exactly* — iverilog-simulated
   integer equality on all 11 fixtures (§2). **PASS.**
2. *The model reproduces the pinned reference within [PROPOSED] budgets* —
   measured against the **pinned kernel** (the pinned `sst-filters` /
   `sst-basic-blocks` code at the pinned submodule commits, compiled
   standalone outside this repository, DR-0009), **not** against a full-engine
   render. Achieved numbers recorded, nothing tuned (§3). **PARTIAL /
   PENDING-FREEZE**, with two recorded findings (§4). The
   **engine-integrated leg is NOT_RUN** (§6).
3. *The instrument sounds good* — **no listening record exists**; nothing here
   speaks to it.

It establishes **no** preset-support claim (§7), **no** fidelity verdict, and
**no** gf180mcu/FPGA synthesis, timing, area, power or hardware-playback
claim. The RTL is an iverilog-simulated behavioural schedule, not
synthesis-closed.

## 0. Scope, carriers and what drives the fixtures

Leaf scope as implemented: **one algorithm** (`fut_lpmoog`) with **all four
engine-declared subtypes** at the pin — `st_lpmoog_6dB`(0) → ladder tap
`R[0]`, `12dB`(1) → `R[1]`, `18dB`(2) → `R[2]`, `24dB`(3) → `R[3]` (the pinned
kernel is one ladder with four output taps) — its coefficient construction
(`Coeff_LP4L` + `FromDirect`), its per-unit register state (5 registers,
per-instance, never shared), and the **keytrack / env-mod path**
(`cutoffA = cutoff + keytrack·(pitch − keytrack_root) + envmod·fenv`,
pinned `SurgeVoice::process_block`). Declared parameter scope, word lengths
and op order: `model/voice/filter_lpmoog/README.md` (the freeze doc).

Observed corpus inventory (`corpus/normalized/graphs.jsonl`, sha256
`c90424d9…`; informational, **not** a support claim): 725 LP Legacy Ladder
instances — 6 dB 76, 12 dB 66, 18 dB 44, 24 dB 539.

| fixture | carrier instance (real normalized corpus entry) | what it covers |
|---|---|---|
| `king-b1` | `Bluelight/Pads/King.fxp` scene B, filter 1 (24 dB) | live keytrack 0.829 (root 60) + env-mod −8.74, reso 0.378 |
| `king-b2` | `Bluelight/Pads/King.fxp` scene B, filter 2 (24 dB) | the **second instance** of the same scene: high reso 0.828, no keytrack/env-mod (per-instance state pair) |
| `chords` | `Damon Armani/Pads/House Of Chords.fxp` scene A, filter 2 (24 dB) | cutoff 70 st ⇒ the pinned `gg` clamp (0.187), reso 0 |
| `disturb` | `Inigo Kennedy/Atmospheres/Disturbances.fxp` scene A, filter 1 (6 dB) | subtype 0 tap, live keytrack 0.415 (root 94) + env-mod +18.75 |
| `sub12db`, `sub18db` | declared subtype overrides on the King-B1 plane | the two subtypes no carrier in the issue's set uses (12 dB / 18 dB taps) |
| `reso1` | declared corner | resonance 1.0 ⇒ the `q = 2.15` ceiling, step drive |
| `cut-hi` / `cut-lo` | declared corners | above the `gg` clamp / far below the cutoff span (`0.5/t_b1⁴` guard branch) |
| `hot` | declared corner | over-unity drive into the pinned `softclip8` first stage |
| `toggle` | declared corner | subtype changes mid-render ⇒ the engine reset path (`memset` + `CM.Reset()`) |

**What drives them, and what that does and does not prove.** Every fixture is
assembled by `model/voice/filter_lpmoog/fixtures.py` from committed data
only, and the SAME float32 control plane and input samples feed both legs
(model and pinned kernel), so the two can never silently diverge in their
inputs:

* **control plane** — the carriers' real normalized filter-unit parameters
  (`cut`, `res`, `keytrack`, `envmod`, `subtype`, scene `keytrack_root`) read
  out of `graphs.jsonl` at fixture-build time (never hand-copied numbers);
* **note plane** — the issue's declared sequences (`seq-notes-repeated-v1`,
  `seq-notes-coverage-v1`): per-block pitch for the keytrack term, and a
  voice-creation reset at every note-on;
* **filter EG** — a **DECLARED piecewise-linear trajectory**, not an engine
  readback. The filter-envelope definition state is absent from normalized
  schema rev 1.0.0 and reading it requires the pinned engine, which this
  worker does not have (§6). Every spec and artifact carries
  `fenv_source: declared-trajectory`. Consequence, stated plainly: the
  env-mod **arithmetic** is referenced; the carriers' real envelope
  **shapes** are not;
* **stimulus** — the committed SXT-037 tap bundles' filter-unit **INPUT**
  streams (real pinned-engine voice audio at the filter-stage boundary,
  `reports/sxt-037/artifacts/bundle-*/units.bin`), with a declared gain, plus
  deterministic synthetic drives for the corners. Only the INPUT column is
  read; those bundles' LP 12 dB **output** column is a different algorithm and
  is never a reference here (asserted by a test).

These are **test configurations**, never adapted presets, and they promote no
preset to supported.

## 1. Acceptance mapping (issue #73)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model, word lengths + op order documented | **PASS** | `model/voice/filter_lpmoog/README.md` (scope table, word table incl. the Q2.29 coefficient-plane freeze with both measured variants, coefficient construction, per-sample schedule, stability argument); `filter_lpmoog_model.py` |
| 2 | Model-vs-pinned-engine dry-render budgets on the carriers (achieved, not tuned) | **PARTIAL / PENDING-FREEZE** | §3: 11 budget JSONs against the **pinned kernel** (DR-0009). L1 coefficient budgets PASS everywhere; L2 max/rms PASS on every carrier and corner except `cut-lo`; the spectral-corr proposal misses on 9/11 rows (finding F-039-1). The **engine-integrated leg is NOT_RUN** (§6) — this is the item's bounded gap, recorded, not papered over |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS** | §2: 159,744 output samples + 2,496 checkpoints (34,944 state/coefficient fields), zero mismatches; committed single-constant mutant FAILS the same comparison |
| 4 | Cycle/state costs recorded vs SXT-016 probes / SXT-015 accounting | **PASS (recorded; divergence noted)** | §5 and `artifacts/costs.json`: 9 MAC/OS-sample/instance, 0 audio-rate divisions, 160 bits of register state; no SXT-016 probe exists for this type — nearest rows recorded, not reconciled away |
| 5 | Negative controls must demonstrably fail | **PASS (all controls failed as designed)** | `artifacts/negative-control.txt` / `.json`: wrong-subtype ×3 and wrong-algorithm (the **landed** LP 12 dB/Driven biquad) ×2 all FAIL the reference budget by 2–5 orders of magnitude; 5 out-of-scope requests REFUSED; the RTL mutant FAILS exactness while the clean testbench passes |

## 2. RTL-vs-frozen-model exactness (integer equality)

`tools/compare_rtl_model_lpmoog.py` compiles `rtl/voice/tb_lpmoog.sv` with
iverilog (13.0) and requires INTEGER EQUALITY of every output sample and,
at every block checkpoint, the subtype, the five ladder registers `R[0..4]`
and the eight-word coefficient plane `C[0..7]`.

| fixture | output samples | checkpoints | state+coef fields | verdict |
|---|---|---|---|---|
| king-b1 | 16,384 | 256 | 3,584 | **PASS** |
| king-b2 | 16,384 | 256 | 3,584 | **PASS** |
| chords | 20,480 | 320 | 4,480 | **PASS** |
| disturb | 20,480 | 320 | 4,480 | **PASS** |
| sub12db | 12,288 | 192 | 2,688 | **PASS** |
| sub18db | 12,288 | 192 | 2,688 | **PASS** |
| reso1 | 12,288 | 192 | 2,688 | **PASS** |
| cut-hi | 12,288 | 192 | 2,688 | **PASS** |
| cut-lo | 12,288 | 192 | 2,688 | **PASS** |
| hot | 12,288 | 192 | 2,688 | **PASS** |
| toggle | 12,288 | 192 | 2,688 | **PASS** |
| **total** | **159,744** | **2,496** | **34,944** | **zero mismatches** |

The RTL's own MAC counter cross-checks the model's: 147,456 `qmul` calls on
king-b1 on both sides. Artifacts: `artifacts/rtl-*.json`.

## 3. Model-vs-reference budgets (pinned kernel; PENDING-FREEZE, measured)

Reference: the pinned coefficient maker and `LPMOOGquad` kernel at the pinned
submodule commits, compiled standalone **outside** this repository and driven
through the engine's own call sequence (`MakeCoeffs` → `updateState` →
64 kernel calls → register/coefficient read-back, with the float32 `cutoffA`
arithmetic and a tuning provider reproducing
`SurgeStorage::note_to_pitch_ignoring_tuning` from the pinned table formulas).
Decision record, pin enforcement and the exact scope of the resulting claim:
**DR-0009**. Comparator: `tools/compare_lpmoog_model.py` (no normalization, no
time-warping, no per-case metric switching).

[PROPOSED] budgets — a faithful port of the SXT-037 filter-leaf proposal class
to this leaf's words, **not** frozen policy and **not** tuned against achieved
numbers: L1 coefficients max ≤ 4096 / rms ≤ 1024 Q2.29 LSB (= 16 / 4 LSB in
the SXT-037 Q10.21 statement); L2 audio max ≤ 4096 LSB, rms ≤ 256 LSB,
log-spectral correlation ≥ 0.999 (Q10.21).

| fixture | L1 C max/rms (Q2.29) | L2 max/rms (Q10.21) | L2 rms vs ref peak | corr | ref peak | L1 / L2 |
|---|---|---|---|---|---|---|
| king-b1 | 282 / 83.3 | 6 / 0.95 | −121.3 dB | 0.99481 | 1,100,124 | PASS / **FAIL (corr only)** |
| king-b2 | 268 / 109.4 | 54 / 25.67 | −103.4 dB | 0.99091 | 3,794,222 | PASS / **FAIL (corr only)** |
| chords | 16 / 5.7 | 3 / 0.67 | −122.7 dB | 0.99963 | 922,656 | PASS / **PASS** |
| disturb | 38 / 4.8 | 39 / 8.89 | −101.9 dB | 0.99748 | 1,110,213 | PASS / **FAIL (corr only)** |
| sub12db | 282 / 82.6 | 13 / 2.12 | −117.4 dB | 0.99339 | 1,571,594 | PASS / **FAIL (corr only)** |
| sub18db | 282 / 82.6 | 12 / 1.87 | −116.3 dB | 0.99277 | 1,224,626 | PASS / **FAIL (corr only)** |
| reso1 | 282 / 112.5 | 394 / 106.88 | −93.1 dB | 0.99903 | 4,845,603 | PASS / **PASS** |
| cut-hi | 160 / 60.9 | 2 / 0.65 | −124.4 dB | 0.99257 | 1,073,161 | PASS / **FAIL (corr only)** |
| cut-lo | 160 / 61.1 | 1,146 / 404.88 | −9.0 dB | 0.00000 | 1,146 | PASS / **FAIL (F-039-2)** |
| hot | 268 / 109.4 | 57 / 36.83 | −110.0 dB | 0.99648 | 11,617,631 | PASS / **FAIL (corr only)** |
| toggle | 282 / 81.4 | 18 / 2.29 | −119.0 dB | 0.99217 | 2,039,370 | PASS / **FAIL (corr only)** |

Reading this honestly: **every carrier row passes the max and rms proposals
with three to four orders of magnitude of margin** (residual rms −93 to
−125 dBFS relative to the reference peak; per-block register agreement within
1–128 LSB, reported in each JSON but not budgeted). The two failure classes
are §4. No bound was widened and no number was tuned; the coefficient-word
choice that moved these numbers was made on an a priori range argument before
any budget comparison and BOTH variants are published (freeze doc table).

Stability: every fixture, including `reso1` (q ceiling) and `hot` (over-unity
drive), reports **STABLE** with state peaks far from saturation, consistent
with the structural bound in the freeze doc (softclip8-limited stage 0,
contractive one-pole stages 1..3).

## 4. Bounded findings (recorded, not absorbed)

**F-039-1 — the spectral-correlation proposal is unattainable at this
boundary (quantization-floor class; same family as SXT-040 F-040-2 and the
SXT-033 finding 2).** Nine of eleven rows miss `corr ≥ 0.999` while their
sample agreement is at −100 to −125 dBFS. A 4-pole lowpass output has an
enormous dynamic range: in the stopband the reference itself sits at the
±1-LSB quantization floor of the comparison word, and the log-spectral metric
weights those bins equally with the passband. The metric, not the model, is
what fails here — as the two rows that DO pass show (`chords`: cutoff at the
clamp, so almost no stopband; `reso1`: a hot resonant signal that lifts the
whole spectrum above the floor). Resolution — a floor-aware spectral metric,
a level-relative bound, or dropping the metric at stage boundaries — belongs
to the #12 freeze owner. This leaf reports the achieved numbers and does not
propose a weaker bound to pass.

**F-039-2 — low-cutoff quantization dead zone in the frozen Q10.21 register
word.** Below an effective cutoff of about **−86 semitones** (≈1.4 Hz,
measured: `artifacts/deadzone-sweep.json`) the per-stage increment
`round(C[1]·(prev − R))` of the 24 dB tap falls below half an LSB, the
trailing ladder stages stop advancing, and the model outputs **exact
silence** where the pinned kernel still produces a tiny residue. The `cut-lo`
fixture (cutoffA ≈ −96…−100 st) sits inside that zone: reference peak
1,146 LSB (−65 dBFS), model output identically 0, so the row fails the L2
budget outright (max 1,146 / rms 405). Three facts bound it: (a) the 6 dB tap
is unaffected across the whole swept range; (b) the regime is **below the
engine's own cutoff parameter span** ([−60, +70] st) and is reachable only by
pushing `cutoffA` far below it through keytrack/env-mod; (c) widening the
coefficient word does **not** fix it (identical numbers with Q10.21 and Q2.29
coefficients) — it is a register-word effect and would need a much wider
state word, which is a freeze-level cost decision, not a leaf one. Routed to
SXT-013/#12 with the measured threshold; **not** clamped, hidden, or
budget-adjusted.

**F-039-3 — the declared filter-EG trajectory is not the carriers' envelope.**
The env-mod arithmetic is exercised and referenced, but with a declared
trajectory (§0), because the filter-EG definition state needs the pinned
engine. Any later claim about these carriers' *actual* modulated cutoff paths
needs the engine-integrated leg (§6).

## 5. Costs (planning numbers, not technology claims)

Measured from the frozen schedule (`tools/count_lpmoog_model_qmuls.py` →
`artifacts/costs.json`), at the declared 1 MAC/cycle assumption (A-DSP-1c):

* **9 MAC / OS sample / instance** — 6 coefficient products (input gain,
  feedback, and the four stage updates sharing `C[1]`) + 3 `softclip8`
  products — plus 11 saturating adds and **zero audio-rate divisions**
  (A-ALU-2 holds for this leaf; `qdiv` appears only in the block-rate
  `FromDirect`). One `make_coeffs` per 64-sample block.
* **State**: 5 × 32-bit registers per instance (160 bits) + the 16 × 32-bit
  streamed coefficient plane; the coefficient maker's `tC[8]` lives in the
  control plane.
* **Divergence, recorded not reconciled**: no SXT-016 probe exists for
  `fut_lpmoog`. The nearest planning rows —
  `probe_filter__svf_tdf2_block_coeffs__a24__m32__onchip` (1,536,000
  cyc/frame, 192 B state) and `probe_filter__k35_ladder_tanh_poly__a24__m32__onchip`
  (3,840,000 cyc/frame, 584 B) — are per-kernel numbers at their own declared
  assumptions, and SXT-015's cost profile is `placeholder-v0`. An
  SXT-016-class probe for this type is **required before any profile freeze**
  (the issue's own cost note). No timing, clock, area or power claim.

## 6. What is NOT_RUN, and why (engine-integrated leg)

The **engine-integrated leg is NOT_RUN**: a real carrier render through the
whole pinned voice path — the engine's own filter-input signal, its own
filter-EG trajectory, its own per-block `cutoffA` — captured at the filter
boundary by the DR-0005 tap. It needs an oracle host with the pinned engine
built (surgepy) and the tap patch; the worker dispatched for this issue has
neither, and building the full engine there is neither sanctioned by its host
rules nor reproducible. **NOT_RUN is reported as NOT_RUN** — never as a pass,
and never quietly folded into the kernel numbers, which is why every artifact
carries `leg: L2-kernel …`.

What the kernel leg **does** cover: the algorithm and all four subtypes, the
coefficient construction and its smoothing, the register semantics and reset
paths, the read-back, and the cutoff control arithmetic. What it does **not**
cover: the carriers' real signals and envelope shapes, the surrounding voice
chain, and anything about the engine's integration of this filter.

A follow-up issue is filed for the engine-integrated leg; this leaf's
`model_vs_reference` ledger status is **PARTIAL**, and the leaf is **not**
support-ready.

## 7. Coverage delta (honest)

**Zero presets are promoted to supported by this leaf.** No headline status in
`reports/coverage-v1/` changes: the carriers still need unlanded features
(their full voice graphs, other filter types, FX), the fidelity-freeze gate
(#12) is still BLOCKED, and the fixtures here are stage-level test
configurations. What the leaf adds is the verified LP Legacy Ladder
arithmetic — frozen model, exact RTL, and measured kernel-reference numbers
per declared subtype. Ledger: `filter_type:LP Legacy Ladder` in
`reports/coverage-v1/leaf-verification.json` (`rtl_vs_model: PASS`,
`model_vs_reference: PARTIAL`) with an evidence-hash pin.

## 8. Reproducibility

```sh
python3 tools/run_sxt039_checks.py        # steps 1-3, oracle-free
python3 -m pytest tests/test_sxt039_lpmoog.py
```

Step 1 re-runs all 11 RTL exactness runs plus the mutant control (stimulus
hex is never committed); step 2 regenerates the budget matrix from the
COMMITTED reference streams and fails if any committed number moved (a STALE
artifact is a failure, never a silent overwrite); step 3 re-runs the negative
controls. Regenerating the reference streams themselves (a pin bump, a new
fixture) needs pinned checkouts:

```sh
python3 tools/render_lpmoog_reference.py --cases all \
    --sst-filters <pinned sst-filters> --sst-basic-blocks <pinned sst-basic-blocks> \
    --out-dir reports/SXT-039/artifacts
```

which sha256-verifies every pinned header before building and refuses (exit 3)
on any drift or on a work directory inside this repository. Environment used
for this record: Linux x86-64, g++ 13 (`-O2 -std=c++20 -msse4.2`, native SSE —
no SIMDE), iverilog 13.0, python 3.12 (model renders are pure integer Python).

## 9. Licensing / provenance

Everything under `model/voice/filter_lpmoog/`, `rtl/voice/tb_lpmoog.sv`,
`rtl/voice/lpmoog_broken_mutant.sv`, `tools/*lpmoog*`,
`tests/test_sxt039_lpmoog.py` and `reports/SXT-039/` is original to this
repository (Apache-2.0 per `LICENSE`). No Surge/SST source, table or asset is
copied here: the algorithm is re-derived from the cited pinned bodies and
construction formulas. The reference harness — original glue that `#include`s
the pinned GPL-3.0-or-later headers — is generated, built and run **outside**
the repository and is never committed; the tool refuses to write inside the
tree. Visible license decision: **DR-0009**
(`decision-records/0009-pinned-kernel-reference-harness.md`, PROPOSED pending
owner ratification), following the DR-0005 precedent. The committed reference
streams are this project's own renders, the same disposition as the SXT-037
tap bundles. Method only (no code) follows the landed SXT-022/SXT-037/SXT-040
leaf patterns; the landed SXT-037 LP 12 dB model is imported **only** as the
wrong-algorithm negative control.

## 10. Explicitly NOT established by this work

* Any preset-support or preset-quality claim; the fixtures are test
  configurations and count toward nothing.
* Any fidelity verdict: every §3 number is PENDING-FREEZE and owned by #12.
* Full-engine agreement for this filter: the engine-integrated leg is
  NOT_RUN (§6), and the carriers' real filter-EG shapes and voice signals are
  unexercised.
* Behaviour outside the declared scope: non-12-TET tuning, `f2_cutoff_is_offset`
  unit-2 coupling, `fc_wide` stereo duplication of the unit, resonance or
  cutoff modulation sources beyond the modelled keytrack/env-mod path, and the
  low-cutoff regime below ≈−86 st (F-039-2).
* Any gf180mcu/FPGA synthesis, place-and-route, timing, power, area or
  hardware-playback result.
