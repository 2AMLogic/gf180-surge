# Wet-path tail gate: tail-shape (windowed decay-curve) leg (evidence record)

Issue: #111 · Parent: #21 (SXT-028 expansion) · Found while building #100
(stereo comparator tail gate); affects the #93 shared gate too · Date:
2026-09-26

Tool changed: `tools/compare_audio_reference.py` (`PROPOSED_TAIL`,
new `tail_decay_curve`, `tail_check`, `stereo_tail_gate`). The change reaches
every comparator that uses the shared gate: the mono shared tool (`--path
wet`), `compare_chorus_reference.py` (SXT-028c), `compare_fx_reference.py`
(sxt-023), `compare_reverb_model.py` (sxt-024 `tail_gate` check) and
`compare_phaser_reference.py` (SXT-028g, whose reference legs are NOT_RUN, so
it has no landed gated verdict). Checks runner:
`tools/tail_shape_leg_checks.py`. It also re-runs `tools/tail_gate_checks.py`
(#93) and `tools/stereo_tail_gate_checks.py` (#100). Tests:
`tests/test_tail_shape_leg.py` (plus tightened `tests/test_stereo_tail_gate.py`
and `tests/test_sxt028c.py`).

**Claim discipline.** This is a **tooling / verification-mechanism** record.
It establishes three things: the wet-path tail gate now carries a tail-shape
leg on the mono path and on the mono sum, L and R of the stereo gate; the
late-tail truncations that used to pass now FAIL; and no landed verdict
changed status. It makes **no** model-vs-reference fidelity claim, **no** RTL
claim, **no** preset-support or coverage claim, and **no** sound-quality claim
(no human listening). It **freezes no budget**. The new budget is
`[PROPOSED-TO-BE-FROZEN-AT-PILOT]` like the others, and the freeze is gated on
SXT-017 #12 and #16.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Late-tail probes from the issue (alienappears, tail zeroed from 40% and 60% of the declared region) FAIL the full verdict | **CONTROL-OK**. Both FAIL. The pre-#111 tool PASSed both. | `artifacts/late-tail-controls.txt`, `reports/stereo-comparator-tail-gate/artifacts/negative-controls.txt` |
| The shape leg does the work: the three global budgets and the whole-region residual leg PASS, and the verdict FAILs on the shape leg alone | **CONTROL-OK** on 8 controls (6 stereo, 2 mono) | `artifacts/late-tail-controls.txt` |
| Failure control: the committed model render keeps passing | **PASS**. Worst window deviation is 0.01 dB over 50 graded windows (mono, L and R). | `artifacts/late-tail-controls.txt` |
| Six SXT-028c cases re-run | **6/6 PASS → PASS**. Worst deviation is 0.21 dB (fmtwang2 poly, R). | `artifacts/landed-verdict-rerun.txt`, `reports/SXT-028c/artifacts/compare-*.json` |
| sxt-023 (3) and sxt-024 (3) re-run | **0 status changes**. sxt-023 is FAIL/PASS/FAIL and sxt-024 is PASS/PASS/FAIL, as before. The tail-gate result is also unchanged on all six. | `artifacts/landed-verdict-rerun.txt` |
| #93 shared-comparator controls re-run | **8/8 unchanged** (PASS 1, FAIL 4, REFUSE 3). Dry output is byte-identical to the pre-#111 tool. | `artifacts/landed-verdict-rerun.txt`, `reports/shared-comparator-tail-gate/artifacts/` |
| The floor is a declared budget, never inferred from silence | **PASS** (`PROPOSED_TAIL["decay_curve_floor_dbfs"]`, reported in every `tail_decay_curve`) | `tests/test_tail_shape_leg.py` |
| Any fidelity, support or quality claim | **none made** | this section |

Run: `python3 tools/tail_shape_leg_checks.py` at repo HEAD `8ade1d18`
(the pre-change base; working-tree tools), numpy 2.4.1, 2026-09-26. Overall
**PASS**. The pre-change comparison rev is `PRE_111_REV =
8ade1d184d1b26f94caa9b3fa3bfbbab2069ff9e`, read with `git show`.

## 1. What changed

The pre-#111 gate integrated the residual RMS over the **whole** declared
tail region and compared it with the reference tail RMS (−20 dB). A decaying
tail's energy sits almost entirely in its first few hundred ms, so that leg
could not see a defect in the late tail.

`tail_check` now also runs `tail_decay_curve` over the declared region:

* The region is cut into windows of `decay_curve_window_s`, starting at the
  declared tail offset. A final partial window is graded too.
* Each window's RMS level is taken in dBFS for the reference and the model
  (`rms_dbfs`, so a silent window is −300 dBFS).
* Only windows whose **reference** level is at or above
  `decay_curve_floor_dbfs` are graded.
* Every graded window must meet `|model_db − ref_db| ≤
  decay_curve_max_dev_db`. The test is two-sided: a tail that stops early
  fails, and so does a tail that fails to decay.
* If **no** reference window reaches the floor, the tail shape cannot be
  graded, and the leg FAILs closed. It never passes vacuously.

`tail_check` also reports the per-leg results `tail_rms_rel_ok` and
`tail_decay_curve_ok`, so a record shows which leg decided. `stereo_tail_gate`
applies the leg to the mono sum and to L and R, with full scale `1/lsb`. The
mono tool applies it with the int16 full scale, 32767 (the same value as
`rms_diff_dbfs`). Dry comparisons are untouched. The #93 dry-parity leg
re-ran every committed dry case against the pre-#111 tool:
**BYTE-IDENTICAL**.

### Budget (declared, `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`)

| Key | Value | Rationale |
|---|---|---|
| `decay_curve_window_s` | 0.05 | The sxt-024 `decay_curve` window (`BUDGETS["window_s"]`). |
| `decay_curve_floor_dbfs` | −100.0 | A declared constant in **full-scale** units, so it means the same thing for int16 and float buses. It is not derived from the render's own noise floor or silence. It equals the sxt-024 floor. |
| `decay_curve_max_dev_db` | 1.0 | The sxt-024 `decay_curve` value. It sits just above 0.92 dB (−20·log10(1 − 10^−1)), the largest level deviation a window whose own residual met the existing −20 dB relative budget can show. So it is consistent with, not looser than, the residual budget. |

These values were chosen from that rationale before the re-runs were graded.
None was adjusted after seeing a result. The pre-existing `tail_rms_rel_db =
−20.0` is unchanged.

## 2. Late-tail controls (`artifacts/late-tail-controls.txt`)

The stereo controls come from the **committed** SXT-028c alienappears ×
seq-notes-coverage-v1 model render (Reverb1 → Chorus; declared region
[153600, 273600), the fixture named in the issue). The mono controls come from
the committed SXT-012 wet fixtures. There the model is the reference itself, so
the mono baseline PASS is a tool self-test, not a fidelity result. Every
control is also run through the **pre-#111 tool**, materialized from
`PRE_111_REV`.

| Control | Required | Now | Pre-#111 tool | Budgets | Residual leg | Residual | Shape leg worst dev (graded windows) |
|---|---|---|---|---|---|---|---|
| `stereo/baseline` (committed model) | PASS | PASS | PASS | PASS | PASS | −53.84 dB | 0.01 dB (50) |
| `stereo/zero-late-tail-from-30%` | FAIL | FAIL | FAIL | FAIL | FAIL | −15.67 dB | 242.26 dB (50) |
| `stereo/zero-late-tail-from-40%` | FAIL | **FAIL** | PASS | PASS | PASS | −21.12 dB | 238.12 dB (50) |
| `stereo/zero-late-tail-from-60%` | FAIL | **FAIL** | PASS | PASS | PASS | −33.40 dB | 223.89 dB (50) |
| `stereo/zero-late-tail-from-80%` | FAIL | **FAIL** | PASS | PASS | PASS | −44.49 dB | 212.42 dB (50) |
| `stereo/zero-late-tail-from-90%` | FAIL | **FAIL** | PASS | PASS | PASS | −49.10 dB | 207.88 dB (50) |
| `stereo/late-tail-decays-too-fast` (extra τ 0.2 s from 40%) | FAIL | **FAIL** | PASS | PASS | PASS | −26.72 dB | 63.88 dB (50) |
| `stereo/right-channel-late-tail-drop` (R zeroed from 60%) | FAIL | **FAIL** | PASS | PASS | PASS | −39.05 dB | 6.77 dB mono sum; R 224.31 dB fails, L 0.01 dB passes (50) |
| `mono/behemoth/baseline` (self) | PASS | PASS | PASS | PASS | PASS | exact | 0.00 dB (50) |
| `mono/behemoth/zero-late-tail-from-40%` | FAIL | FAIL | FAIL | FAIL | FAIL | −14.41 dB | 256.56 dB (50) |
| `mono/behemoth/zero-late-tail-from-60%` | FAIL | FAIL | FAIL | FAIL (spectral_corr) | PASS | −22.51 dB | 250.04 dB (50) |
| `mono/behemoth/zero-late-tail-from-95%` | FAIL | **FAIL** | PASS | PASS | PASS | −43.29 dB | 232.19 dB (50) |
| `mono/koala2/zero-late-tail-from-44%` | FAIL | **FAIL** | PASS | PASS | PASS | −54.00 dB | 218.11 dB (23) |
| `mono/koala2/zero-late-tail-from-46%`: **characterization, not a control** | — | PASS | PASS | PASS | PASS | −72.31 dB | 0.00 dB (23) |

13/13 controls behaved as required. **Bold** marks the 8 renders that the
pre-#111 tool let through as PASS and that the shape leg now FAILs on its own.
The 30% probe and the mono 40% and 60% controls already failed before #111
(max budget, residual, or `spectral_corr`), so they are listed but not counted
as evidence for the new leg.

**The floor's limit (characterization, never counted as evidence).** Koala
2's tail falls below −100 dBFS after about 46% of the region. The zeroed span
from 46% sits at about −114 dBFS (not digital silence). The shape leg does not
see it, **by construction**: the floor is declared, and a defect below it is
not graded. The row exists so that this limit is on the record and not
implied away.

## 3. Landed-verdict re-run (`artifacts/landed-verdict-rerun.txt`)

"Before" is the committed record at `PRE_111_REV`. "After" is the re-run with
the new leg (leg 0 regenerates the canonical records). Verdict-status changes
are **0 of 20**. Tail-gate changes under an unchanged status: **none**.

| Case | Before | After | Tail gate before → after | Shape leg worst dev, dB (graded windows) |
|---|---|---|---|---|
| SXT-028c alienappears × seq-notes-coverage-v1 | PASS | PASS | PASS → PASS | mono 0.01 (50) / L 0.01 (50) / R 0.01 (50) |
| SXT-028c alienappears × seq-poly-8-v1 | PASS | PASS | PASS → PASS | 0.00 (50) / 0.00 (50) / 0.00 (50) |
| SXT-028c fmcombo × seq-notes-coverage-v1 | PASS | PASS | PASS → PASS | 0.02 (6) / 0.01 (6) / 0.02 (6) |
| SXT-028c fmcombo × seq-poly-8-v1 | PASS | PASS | PASS → PASS | 0.01 (6) / 0.01 (6) / 0.01 (6) |
| SXT-028c fmtwang2 × seq-notes-coverage-v1 | PASS | PASS | PASS → PASS | 0.09 (7) / 0.08 (7) / 0.10 (7) |
| SXT-028c fmtwang2 × seq-poly-8-v1 | PASS | PASS | PASS → PASS | 0.10 (9) / 0.02 (9) / 0.21 (9) |
| sxt-023 dexie | FAIL | FAIL | FAIL → FAIL | 1.68 (30) / 2.32 (31) / 1.84 (31): the shape leg also fails |
| sxt-023 fm_bass_1 | PASS | PASS | PASS → PASS | 0.00 (4) / 0.00 (4) / 0.00 (4) |
| sxt-023 metallic | FAIL | FAIL | FAIL → FAIL | 12.12 (48) / 13.97 (50) / 8.86 (50): the shape leg also fails |
| sxt-024 click-wet | PASS | PASS | PASS → PASS | 0.00 (108) / 0.00 (108) / 0.00 (108) |
| sxt-024 preset-notes-coverage-wet | PASS | PASS | PASS → PASS | 0.00 (88) / 0.00 (89) / 0.00 (87) |
| sxt-024 hardreset-midpatch-wet | FAIL (`tail_rms_rel`) | FAIL (`tail_rms_rel`) | PASS → PASS | 0.00 (35) / 0.00 (35) / 0.00 (35) |
| #93 full-tail-within-budget | PASS | PASS | PASS → PASS | 0.79 (23), see finding F1 |
| #93 drop-full-tail | FAIL | FAIL | FAIL → FAIL | 268.94 (23) |
| #93 tail-decays-too-fast | FAIL | FAIL | FAIL → FAIL | 220.71 (23) |
| #93 truncate-at-tail-start | FAIL | FAIL | FAIL → FAIL | not graded (region not covered) |
| #93 undeclared-wet-path / no-sidecar / stale-sidecar | REFUSE | REFUSE | n/a | not graded (refused) |
| #93 drop-full-tail-second-preset | FAIL | FAIL | FAIL → FAIL | 270.79 (50) |

On sxt-023 dexie and metallic, the verdict *text* now also names the
shape-leg reasons. Their status was already FAIL (budgets and the residual
leg), so no status moved. That is recorded here explicitly, not left to a
silent diff. The sxt-023 and sxt-024 leaf records themselves are not
rewritten. The gated re-runs are retained under
`reports/stereo-comparator-tail-gate/artifacts/sxt02{3,4}-rerun/`, as in #100.

**The stop/escalate condition did not trigger.** No landed verdict flipped,
and no budget was tuned.

## 4. Bounded findings

* **F1: int16 near-LSB margin (pilot-freeze input; no verdict affected).**
  The #93 `full-tail-within-budget` control adds ±1 LSB dither to the first
  half of Koala 2's tail. Its late graded windows sit between about −90 dBFS
  (1 int16 LSB RMS is −90.3 dBFS) and the −100 dBFS floor. There, ±1 LSB
  moves the window level by up to **0.79 dB** against the 1.0 dB budget. It
  still PASSes, but the margin comes from quantization, not tail shape. A real
  int16 model with ±1 LSB rounding differences could fail the shape leg in
  windows within about 10 dB of 1 LSB. The float/s24 buses (SXT-028c,
  sxt-023, sxt-024) do not show this: their LSB (2^-21 ≈ −126 dBFS, s24 2^-23 ≈
  −138 dBFS) is at least 26 dB below the floor. The floor is **not** moved here, because moving it would be tuning.
  Whether the int16 floor should sit above the quantization-dominated region
  is a pilot-freeze (SXT-017) decision, filed as #160.
* **F2: #100 leg-5 assertion went stale on main (fixed here, attributed).**
  Re-running `tools/stereo_tail_gate_checks.py` on the **unmodified**
  pre-#111 tree (extracted with `git archive` at `PRE_111_REV`) already FAILs
  leg 5. Its "gated output minus `tail_gate` == pre-#100 tool output"
  comparison reports False on all three sxt-024 cases. The only differing key
  is `tail_window`, the transparency block that #108 added to
  `compare_reverb_model.py` after the #100 record was committed. It is not an
  entry in `checks` and not a verdict input. The comparison now also excludes
  `tail_window`, and it records the excluded keys
  (`excluded_keys_for_gate_only_comparison`). Any other difference still FAILs
  the leg. This is not caused by #111. It had to be fixed so that the #100
  re-run the issue asks for could be recorded honestly.
* **F3: the floor limit (by construction).** See §2. A late-tail defect
  whose reference level lies below the declared floor is not seen.

## 5. Reproduce

```
python3 tools/tail_shape_leg_checks.py        # legs 0,1,2; regenerates
                                              # reports/{shared,stereo}-comparator-tail-gate/
                                              # and reports/SXT-028c/artifacts/compare-*.json
python3 -m pytest -q tests/test_tail_shape_leg.py tests/test_stereo_tail_gate.py \
    tests/test_tail_gate.py tests/test_sxt028c.py
```

## 6. What remains unproved

* Nothing here says any model reproduces any reference, any RTL matches any
  model, or any preset is supported or sounds good.
* The three shape-leg values (window, floor, max deviation) and the existing
  residual budget are proposals. The committed model renders that pass the
  other legs deviate by 0.21 dB or less. The two committed renders that
  deviate more (sxt-023 dexie and metallic) already FAIL on the budgets and
  the residual leg. So no committed render yet tests the 1.0 dB value at its
  edge. The values must be re-argued at the pilot freeze (SXT-017 #12, #16),
  including F1.
* Defects below the declared floor (F3), and per-window *spectral* shape
  changes at unchanged level, are outside this leg.
