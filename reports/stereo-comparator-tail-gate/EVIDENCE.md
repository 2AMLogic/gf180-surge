# Stereo effect-slice comparators: wet-path tail gate, and the two metric findings (evidence record)

Issue: #100 · Parent: #21 (SXT-028 expansion) · Follows #93 (shared-comparator
tail gate, PR #99) · Date: 2026-09-25

Tools changed: `tools/compare_chorus_reference.py` (SXT-028c),
`tools/compare_fx_reference.py` (sxt-023), `tools/compare_reverb_model.py`
(sxt-024), `tools/compare_audio_reference.py` (shared; new `rms_dbfs` floor
and `stereo_tail_gate` helper). Checks runner: `tools/stereo_tail_gate_checks.py`.
Tests: `tests/test_stereo_tail_gate.py` (plus updated
`tests/test_sxt028c.py`, `tests/test_tail_gate.py`).

**Claim discipline.** This is a **tooling / verification-mechanism** record.
It establishes that the stereo comparators now apply the #93 tail-gate legs
over a *declared* tail region and refuse without one, that no landed verdict
changed status as a result, and what the two metric decisions are. It makes
**no** new model-vs-reference fidelity claim, **no** RTL claim, **no**
preset-support or coverage claim, and **no** sound-quality claim (no human
listening). It **freezes no budget**: every budget, including the tail budget,
stays `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`, with the freeze gated on SXT-017 #12 and
the shared delay-semantics decision #16.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Stereo comparators read the tail region from the sidecar's declared values and refuse without them | **PASS** (4 refusal controls, exit 2 / NO_VERDICT) | `artifacts/negative-controls.txt` |
| Stereo wet verdict = budgets AND gate (covered, ref tail present, model tail present, relative residual; mono sum **and** L **and** R) | **PASS** | `artifacts/negative-controls.txt`, `tests/test_stereo_tail_gate.py` |
| Failure control: zeroed / far-too-fast / one-channel-dropped / truncated model tail FAILS on a stereo fixture | **CONTROL-OK** (12/12 required-FAIL renders FAIL; 20/20 controls overall) | `artifacts/negative-controls.txt`, `artifacts/control-*.json` |
| SXT-028c: six committed cases re-run under the gate | **6/6 PASS → PASS**; 0 verdict changes; 0 unexplained diffs; artifacts regenerated | `artifacts/sxt028c-rerun.txt`, `reports/SXT-028c/artifacts/compare-*.json` |
| sxt-023 (3) and sxt-024 (3) re-run under the gate | **0 verdict changes** (records not rewritten; re-runs retained) | `artifacts/sxt023-sxt024-rerun.txt`, `artifacts/sxt02{3,4}-rerun/` |
| `rms_diff_dbfs` exact-agreement decision | **Clamp to −300.0** (all emitters); 1 affected artifact regenerated; every committed `reports/**/*.json` strict-parses | `artifacts/rms-floor.txt`, `reports/shared-comparator-tail-gate/` |
| `spectral_corr` sensitivity characterized; recommendation | **Characterized; metric NOT changed**; recommendation filed for the freeze (#110) | `artifacts/spectral-corr-sweep.{txt,json}` |
| Late-tail truncation | **KNOWN GAP**: the gate does not catch it (filed #111) | `artifacts/negative-controls.txt` ("KNOWN-GAP probes") |
| Any fidelity / support / quality claim | **none made** | this section |

## 1. What changed

1. **Declared tail region, never hard-coded, never silence-inferred.**
   `compare_chorus_reference.py` previously graded the last `tail_s=2.0` s
   (hard-coded), gating on *reference*-tail presence alone.
   `compare_fx_reference.py` had no tail leg. Both now read the region
   from the effect-slice sidecar through the shared `declared_tail_region()`:
   `render.frames`, `render.tail_s` (2.5 s), `render.sample_rate`, giving the region
   `[frames − tail_s·sr, frames)`. For the SXT-028c / sxt-023 fixtures this is
   [153600, 273600) on seq-notes-coverage-v1 and [57600, 177600) on
   seq-poly-8-v1. The sidecar is also checked against the reference render
   (sample rate, frame count, declared wet sha256).
2. **Refusal.** A missing sidecar, a sidecar that does not declare
   `tail_s`/`frames`/`sample_rate`, a STALE frame count, or a sha256 mismatch
   gives verdict `NO_VERDICT (refused)` with exit 2, and nothing is graded.
   `compare_fx_reference.py` also refuses a `-dry`-named reference.
3. **Same legs as the shared gate, per channel.** The new
   `compare_audio_reference.stereo_tail_gate()` applies the #93 `tail_check`
   (shape-identical) to the mono sum (`tail_check`) and to each of L and R
   (`tail_check_lr`). The gate passes only when all three pass, because a stereo
   model can drop one channel's tail while the mono sum keeps energy. The budget
   is the shared `PROPOSED_TAIL` (`tail_rms_rel_db ≤ −20 dB`).
4. **Verdict** = three proposed budgets AND gate. The FAIL text names the failing
   legs. Exit status: 0 for any graded verdict (unchanged for existing
   consumers such as `tools/run_ncb_nn_model.py`, which reads `verdict`), 2 for
   refusal.
5. **`compare_reverb_model.py`** (a different tool shape: model in the loop,
   trace sidecars) gains the same gate as an **additional** `checks.tail_gate`
   over the trace sidecar's declared `render.frames`/`render.tail_s`. Its own
   `tail_rms_rel` check (sequence-derived window, stricter −50 "dB" budget,
   floor guard) is unchanged. `--out-dir` was added so the case can be re-run
   without overwriting the committed sxt-024 records. #108 (filed during an
   earlier pass on this issue) asks whether to unify this tool's tail check onto
   the shared shape. This change adds the shared-shape gate without touching the
   bespoke checks; the remaining #108 questions (graceful refusal when the
   sequence file cannot give `t0`, and whether to regenerate the sxt-024
   records) stay with #108/#112.

## 2. SXT-028c re-run (the six committed cases): no verdict changed

`python3 tools/stereo_tail_gate_checks.py --write-artifacts` (leg 1) compares
each committed artifact at `b326bc0` (the pre-#100 record) with the gated
tool's output and attributes every changed key.

| Case | old gate (2.0 s, ref-presence) | declared region | tail residual mono / L / R (dB, ≤ −20) | Status before → after |
|---|---|---|---|---|
| alienappears × notes | present, −54.90 dB (not graded) | [153600, 273600) | −53.84 / −54.23 / −54.09 | PASS → **PASS** |
| alienappears × poly-8 | present, −59.83 dB | [57600, 177600) | −60.25 / −60.36 / −60.37 | PASS → **PASS** |
| fmcombo × notes | present | [153600, 273600) | −73.46 / −73.57 / −73.37 | PASS → **PASS** |
| fmcombo × poly-8 | present | [57600, 177600) | −83.29 / −82.83 / −83.61 | PASS → **PASS** |
| fmtwang2 × notes | present | [153600, 273600) | −70.48 / −67.55 / −70.79 | PASS → **PASS** |
| fmtwang2 × poly-8 | present | [57600, 177600) | −83.94 / −85.81 / −82.78 | PASS → **PASS** |

Per-case key diff (full list in `artifacts/sxt028c-rerun.txt`): `SCHEMA(added)`
(the gate fields), `SCHEMA(removed)` (the hard-coded 2.0 s
`channels.tail_mono` block), `SCHEMA(version)` 1 → 2, `VERDICT-TEXT` (PASS
text now names the gate; status unchanged), `TAIL-WINDOW`
(`tail_check.tail_rms_rel_db` now measured over the declared 2.5 s region),
and `ULP` (last-digit `spectral_corr` drift on this host). **Unexplained: 0.
Verdict-status changes: 0.** The stop/escalate clause did not trigger.
The smallest margin is alienappears × notes, which clears the −20 dB proposal by
about 34 dB. The change is also recorded in `reports/SXT-028c/EVIDENCE.md` §3.

## 3. Failure controls (each must fail the check it targets)

Leg 2 builds control renders from the **committed model renders** of
SXT-028c fmcombo × notes, SXT-028c alienappears × notes (Reverb1 → Chorus,
a long tail), and sxt-023 fm_bass_1 (the fx comparator's one PASS case):

| Control | fmcombo (chorus) | alienappears (chorus) | fm_bass_1 (fx) | pre-#100 chorus tool |
|---|---|---|---|---|
| baseline (committed model render) | PASS | PASS | PASS | — |
| drop-full-tail (region zeroed, L+R) | **FAIL** (gate: model tail silent; + max, rms) | **FAIL** (gate; + max, corr) | **FAIL** (gate; + max, rms) | FAIL (budgets) |
| tail-decays-too-fast (extra exp decay τ 0.4 s) | **FAIL** (max; gate −30.1 dB passes) | **FAIL** (gate −8.9 dB; + max) | **FAIL** (max; gate −21.2 dB passes) | FAIL (max) |
| drop-right-tail (R region zeroed) | **FAIL** (gate R + mono; + max, rms) | **FAIL** (gate R + mono; + max) | **FAIL** (gate R + mono; + max) | FAIL (budgets) |
| truncate-at-tail-start | **FAIL on the gate alone** (all 3 budgets PASS) | **FAIL on the gate alone** | **FAIL on the gate alone** | **PASS** (the loophole) |

Refusals (all exit 2, NO_VERDICT): chorus with a missing sidecar, undeclared
`tail_s`, STALE `frames`, and wet sha256 mismatch; fx with a missing sidecar.
**20/20 controls behaved as required.** Committed control outputs:
`artifacts/control-drop-full-tail-fmcombo.json`,
`artifacts/control-tail-decays-too-fast-{fmcombo,alienappears}.json`.

What the controls show honestly:
* The truncation control is the one where the gate alone does the work. The
  pre-#100 chorus tool PASSed it, because both renders were cut to the shorter
  length and compared bit-exactly.
* On the chorus-only carriers (fmcombo, fmtwang2) the "tail" falls from about
  −25 dBFS to below −100 dBFS within about 300 ms (short chorus delay, little
  feedback). An extra τ 0.4 s decay therefore moves little tail energy: the
  verdict still FAILs, but on the max budget, and the gate passes (−30.1 dB).
  The −20 dB relative proposal is not the leg that catches that control on
  those carriers.
* **KNOWN GAP (#111), recorded, not a control:** the residual leg integrates
  over the whole region, so it is dominated by the early tail. On
  alienappears, zeroing the tail from 40% or 60% of the region onward
  **PASSES every budget and the gate** (max 4498 / 1102 LSB, tail residual
  −21.1 / −33.4 dB). The reference there is still about −68 to −96 dBFS. A
  tail-shape (windowed decay-curve) leg is follow-up work in #111. Until it
  lands, a late-tail defect is not excluded by this gate.

## 4. sxt-023 and sxt-024 re-run: no verdict changed, records not rewritten

`artifacts/sxt023-sxt024-rerun.txt` (leg 5). These leaves' committed
artifacts predate the gate and are **not** rewritten here. Each record carries a
change note, and the gated outputs are retained under
`artifacts/sxt023-rerun/` and `artifacts/sxt024-rerun/`.

* sxt-023 (`compare_fx_reference.py`): fm_bass_1 (EQ) PASS → PASS (tail
  −92.40 dB). metallic FAIL → FAIL and dexie FAIL → FAIL, with the gate
  **adding** a failing leg (metallic mono −8.10, L +0.42, R −0.49 dB; dexie
  mono −12.60, L −4.20, R −4.37 dB). The per-channel delay tails are not
  reproduced, which is further input to #16/#12. The only other diffs are
  last-ULP values.
* sxt-024 (`compare_reverb_model.py`): click PASS, preset PASS, hardreset FAIL
  (`tail_rms_rel`, the already-recorded factory-default-regime finding), all
  unchanged. The new gate passes on all three (−110.1 / −106.0 / −88.3 dB).
  **The gated output minus `tail_gate` is byte-identical to the pre-#100 tool's
  output on the same host**, so the gate adds exactly one check. Separately,
  the committed click/preset records do not reproduce bit-for-bit with the
  *pre-#100* tool on this NumPy 2.4 host (`send_gain` float32 cube under NEP 50,
  and fields the tool gained after those records were written). That is
  pre-existing and independent of #100, changes no verdict, and is filed as
  #112.

## 5. Decision: `rms_diff_dbfs` under exact agreement → clamp to a finite floor

`20·log10(0) = −inf` was serialized by Python's `json` as the non-standard
token `-Infinity`, which strict parsers (jq, `JSON.parse`, serde) reject.
**Decision: clamp to `RMS_DIFF_DBFS_FLOOR = −300.0`**
(`compare_audio_reference.rms_dbfs`, used by all three emitters: shared mono,
chorus, fx).

* Semantics: a value at the floor means "residual RMS ≤ 1e-15 of full
  scale, including exact agreement". Nonzero values above the floor are
  unchanged byte for byte: 37/37 dry cases stay byte-identical against the
  pre-#100 tool (`reports/shared-comparator-tail-gate/artifacts/rerun-dry-cases.txt`).
  The smallest nonzero residual the committed renders can produce is far above
  the floor (one int16 LSB over 10^7 frames is about −160 dBFS).
* Grading is unchanged: `≤ −46 dBFS` is true for both −inf and −300.
* Affected committed artifacts: exactly one,
  `reports/shared-comparator-tail-gate/artifacts/tailgate-truncate-at-tail-start.json`
  (`-Infinity` → `-300.0`). It was regenerated by re-running
  `tools/tail_gate_checks.py`, and the #93 record carries a change note. Leg 3
  strict-parses **every** committed `reports/**/*.json`, and none is rejected
  after regeneration. `reports/sxt-024` uses `+1e-30` guards and never emitted
  the token.
* Exact-agreement controls (leg 3): shared, chorus, and fx each emit `-300.0`,
  strict-JSON clean, verdict PASS.

## 6. `spectral_corr` characterization and recommendation (metric NOT changed)

The sweep is in `artifacts/spectral-corr-sweep.{txt,json}`, leg 4. The perturbation
is a deterministic ternary {−1, 0, +1} × k native LSB (a splitmix64 hash of the
sample index), applied everywhere, only in quiet frames (reference frame RMS
< 1 LSB), or only in loud frames.

Findings:

1. **The metric depends on units.** `log1p(|X|)` puts the log knee at |X| = 1
   in the tool's *native* unit. That is one int16 LSB in the shared comparator
   and full scale in the float stereo tools. The same name and the same 0.98
   budget therefore measure different things, about 50 dB apart:

   | residual (rms dBFS) | koala2 (int16) | behemoth (int16) | fmcombo (float) | alienappears (float) |
   |---|---|---|---|---|
   | −92 (±1 int16 LSB) | **0.9576** (miss) | **0.9274** (miss) | — | — |
   | −80 | 0.9161 (±4) | 0.8590 (±4) | 1.0000 (±256 Q10.21) | 0.9999 |
   | −68 | 0.8391 | 0.7639 | 0.9995 | 0.9980 |
   | −56 | 0.6945 | 0.6379 | 0.9934 | **0.9730** (miss) |
   | −44 | 0.4575 | 0.4824 | **0.9254** (miss) | 0.7350 |

2. **Near-empty bins drive it, not only silent frames.** Behemoth has
   *no* quiet frames and still misses 0.98 at a −92 dBFS residual: the sparse
   high-frequency bins of a bass render sit below the int16 knee. On koala2,
   quiet-only perturbation (15 of 66 frames) drops the metric to 0.9484 at a
   −98.6 dBFS residual.
3. **It decides real verdicts today.** Four committed verdicts fail on
   `spectral_corr` **alone** (max and rms inside budget): SXT-040 badnews ×
   coverage 0.9298 (rms −61.7 dBFS), badnews × repeated 0.9456 (−71.0),
   popcorn2k × coverage 0.9606 (−47.5), popcorn2k × repeated 0.9789 (−49.2).
   SXT-040 already records the level dependence (F-040-2; SXT-033 finding 2).
4. **Candidate treatments** (evaluated, not adopted):
   * *Frame gating by reference energy* (frames with reference RMS ≥ −80 dBFS):
     fixes the quiet-frame case (koala2 quiet-only goes to 1.0000) but **not** the
     empty-bin case (behemoth stays at 0.9274). Insufficient on its own.
   * *Full-scale log floor*, `log(max(|X| / (FS·Σwin/2), 10^(−100/20)))`, the
     same in every tool: unit-invariant (at −80 dBFS it gives 0.9996 int16 and
     0.9995 float). On the four SXT-040 cases it gives 0.9700 / 0.9752 /
     **0.9838 / 0.9839**, so it would flip popcorn2k × 2 from FAIL to PASS.

**Recommendation for the pilot freeze:** replace the native-unit `log1p` with a
full-scale-referenced log magnitude with a **declared** per-bin floor,
identical in every comparator. Frame gating is optional on top of that, not
a fix on its own. **Not adopted here:** the change re-grades committed verdicts
(popcorn2k × 2 at least), and the floor value is itself a budget, so it belongs
to the SXT-017 freeze (#12) as a visible contract revision. It is filed as **#110**,
with the requirement that every affected committed artifact is regenerated in
the same PR.

## 7. What this record does NOT establish

- Any frozen budget, including `PROPOSED_TAIL` (still unexercised as a
  *design* choice: this record shows its known weakness in §3).
- Any model-vs-reference fidelity beyond the already-landed records. The
  re-runs re-grade existing renders and add no new model output.
- Any preset-support, coverage, or musical-quality claim. No human listening
  took place.
- That late-tail defects are caught (they are not, #111), or that
  `spectral_corr` is a sound acceptance metric at its current definition
  (#110).
- Reproducibility of the sxt-024 click/preset records bit-for-bit on NumPy 2
  (#112).

## 8. Reproduce

```bash
python3 tools/stereo_tail_gate_checks.py --write-artifacts   # legs 1-5 (leg 5 runs the reverb model: ~15 min)
python3 tools/stereo_tail_gate_checks.py --legs 1,2,3,4       # fast legs only
python3 tools/tail_gate_checks.py --baseline-rev b326bc00eaa81bbad74ee71c004f3ae86983f569   # #93 record re-run
python3 -m pytest tests/test_stereo_tail_gate.py tests/test_tail_gate.py tests/test_sxt028c.py -q
```

Scratch renders go under `/tmp/sxt-stereo-tail-gate/` and are never committed.
The committed evidence is the transcripts, the per-control and per-case JSONs,
and `artifacts/checks-summary.json`.
