# Shared full-scale log-floor `spectral_corr` (evidence record)

Issue: #110 · Parent: #12 (SXT-017 pilot freeze) · Characterized in #100
(`reports/stereo-comparator-tail-gate/` section 6) · Date: 2026-09-27

Tools changed: `tools/compare_audio_reference.py` (the one shared definition:
`spectral_corr`, `SPECTRAL_CORR_*`, `FULL_SCALE_*`; legacy kept only as
`spectral_corr_legacy_log1p` for the regrade record),
`tools/compare_chorus_reference.py` and `tools/compare_fx_reference.py` (now
delegate to the shared function with float32 full scale 1.0),
`tools/stereo_tail_gate_checks.py` (#100 leg 4 pinned to the legacy metric;
diff classifier knows `METRIC-#110`). New: `tools/spectral_corr_fs_floor_checks.py`
(legs 1-6 below), `tools/regrade_spectral_corr.py` (regrade ledger; rebased
2026-09-27 onto post-#161 `main` -- see the section 2 rebase note for its
added `REBASE` class and identity-keyed control-list diffing),
`tests/test_spectral_corr_fs_floor.py`. Contract text:
`contracts/fidelity-policy-DRAFT.md` section 2.3.

**Claim discipline.** This is a **metric-definition / tooling** record. It
proposes one `spectral_corr` definition as a visible contract revision to the
SXT-017 freeze. It also shows exactly which committed artifacts, verdicts, and
controls that definition moves. It makes **no** model-vs-reference fidelity
claim, **no** RTL claim, **no** preset-support or coverage claim, and **no**
sound-quality claim. It **freezes nothing**: the definition, the -100 dBFS
floor, and the 0.98 budget all stay `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`.
Adoption is the #12 freeze decision. A PASS below means only that the
spectral leg and the other proposed budgets are met on that render pair.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| One definition in every comparator grading the shared 0.98 budget | **PASS** (shared function; stereo tools delegate; tests pin it) | `tests/test_spectral_corr_fs_floor.py` (10 tests) |
| Unit invariance: same signal on int16 and float32 buses gives the same value | **PASS** (behemoth +-1 LSB: 0.999980 on both; legacy 0.927389 vs 0.999999) | `artifacts/unit-sweep.txt` (leg 1) |
| Frame gating alone does not fix the empty-bin case | **Confirmed** (behemoth +-1 LSB, gated legacy 0.9274); gating is not part of the definition | `artifacts/unit-sweep.txt` |
| Dry re-run parity: pre-#110 tool vs this tool on every committed dry pair differ only in #110-owned fields | **PASS** (37/37; 0 unexplained) | `artifacts/dry-parity.{txt,json}` (leg 3) |
| Re-rendered control artifacts: the non-spectral diffs come from the re-render, not the metric | **PASS** (21/21; SXT-042 runner-added `windowed_rms_lsb` recomputed equal on the same render) | `artifacts/rerender-proof.{txt,json}` (leg 4) |
| #93 and #100 tail-gate control legs under the new metric | **PASS** (#93 leg 2, #100 leg 2 8/8 CONTROL-OK) | `artifacts/tail-gate-controls.txt` (leg 5) |
| Regrade ledger: every committed diff classified | **PASS** (106 artifacts regenerated; 0 UNEXPLAINED; 28 carrying `spectral_corr` not regenerated, each with a reason) | `artifacts/regrade-ledger.{txt,json}` (leg 6) |
| Verdict / control-status flips | **15, named below** (6 caused by #110; 9 caused by #111's tail-shape leg, disclosed) | `artifacts/regrade-ledger.txt` |
| Live negative control lost | **FINDING**: SXT-035 C2 `smoothing-bypass` is not live under the new metric (routed #163) | `artifacts/rerender-proof.txt` |
| Any fidelity / support / quality claim | **none made** | this section |

Run: `python3 tools/spectral_corr_fs_floor_checks.py` (all legs; leg 4 needs
the scratch control re-renders under `--renders-root`, otherwise its rows are
NOT_RUN, never PASS). Stamp: `artifacts/checks-summary.json`.

## 1. The definition

See `contracts/fidelity-policy-DRAFT.md` section 2.3 and the
`SPECTRAL_CORR_*` block in `tools/compare_audio_reference.py`:
non-overlapping Hann 4096 frames. Magnitude `m = |rfft(frame*w)| / (FS*sum(w)/2)`,
with the bus's declared full scale FS (int16: 32767 LSB; float32: 1.0).
Per-bin value `ln(max(m, 10^(-100/20)))`. No frame gating. Pearson correlation
over all (frame, bin) pairs. Budget >= 0.98 (value unchanged). `full_scale`
is a required argument, so no caller can silently fall back to a native unit.

**Where the floor came from.** The -100 dBFS per-bin floor is the value named
in #110's issue body, and #100 evaluated it before this regrade. It was not
tuned to any case. The floor-sensitivity table (leg 2) shows how outcomes
move for -80 through -120 dBFS so a reviewer can see what depends on the
value. Four pairs change their spectral-leg outcome somewhere within
[-110, -90] dBFS:

| Pair | -90 | **-100** | -110 |
|---|---|---|---|
| SXT-040 popcorn2k seq-notes-coverage-v1 | 0.9907 | **0.9838** | 0.9789 |
| SXT-040 badnews seq-notes-repeated-v1 | 0.9833 | **0.9752** | 0.9735 |
| SXT-033 crush seq-notes-repeated-v1 | 0.9626 | **0.9720** | 0.9811 |
| sxt-032 seq-modwheel-v1 | 0.9790 | **0.9809** | 0.9831 |

Popcorn2k-coverage's PASS depends on the declared floor: at -110 it would
FAIL. SXT-035 C2 would be live again at -120 dBFS. The floor was **not**
moved for either case (#110 stop condition).

**Sensitivity consequence the freeze must weigh.** A broadband residual now
starts to miss 0.98 at about -68 dBFS in every tool (leg 1: koala2 0.9834 and
behemoth 0.9511 at -68 dBFS; fmcombo 0.9595 and alienappears 0.9300 at
-68 dBFS). Before, the int16 tool missed at -92 dBFS and the float tools at
-44 to -56 dBFS. The metric is more lenient than before on the int16 tool and
stricter on the float tools.

## 2. Verdict and control-status flips (15: 6 by #110, 9 by #111's rebase)

Cause is attributed by counterfactual (`regrade_spectral_corr.cause_of_flip`).
Each of the 6 #110 flips below is decisive on the spectral leg. With the old
spectral flag, the verdict would be the old one.

**Rebase note (2026-09-27).** This branch was rebased onto `main` after #161
merged (#111's windowed decay-curve tail-shape leg, plus an unrelated
SXT-028c evidence re-pin). `tools/regrade_spectral_corr.py`'s `--base-rev`
predates both #110 and #111, so re-running it against the rebased tree
surfaced 9 additional flips that are #111's, not #110's: 6 are the
`known_gap_probes` -> `late_tail_controls` field rename (3 probes x
`status`+`verdict`; a schema change already on `main` before this branch's
own commit), and 3 are `control-tail-decays-too-fast-fmcombo.json`'s
tail-region-gate `ok` fields (mono + L + R), which the decay-curve leg #111
added now (correctly) fails where the pre-#111 tool did not check shape at
all. None of the 6 #110 flips below moved, and
`regrade_spectral_corr.py` gained a `REBASE` class (a leaf identical to
`origin/main` at the rebase point is unaffected by #110, whatever changed it
against the older `--base-rev`) plus identity-keyed list diffing (`control`
name, not position) so #111's three inserted late-tail controls do not
misalign the classifier against every control after them.

| Artifact | Field | Before -> after | Spectral legacy -> adopted |
|---|---|---|---|
| `reports/SXT-040/artifacts/budget-popcorn2k-seq-notes-coverage-v1.json` | verdict | **FAIL -> PASS** | 0.9606 -> 0.9838 |
| `reports/SXT-040/artifacts/budget-popcorn2k-seq-notes-repeated-v1.json` | verdict | **FAIL -> PASS** | 0.9789 -> 0.9839 |
| `reports/SXT-033/artifacts/budget-edges-seq-notes-coverage-v1.json` | verdict | **FAIL -> PASS** | 0.9635 -> 0.9940 |
| `reports/SXT-033/artifacts/budget-edges-seq-notes-repeated-v1.json` | verdict | **FAIL -> PASS** | 0.9728 -> 0.9946 |
| `reports/sxt-035/artifacts/negative-controls.json` | `smoothing-bypass.control_ok` | **true -> false** | control 0.9844 -> 0.9741 vs baseline 0.9870 -> 0.9710 |
| `reports/sxt-035/artifacts/negative-controls.json` | `overall_ok` | **true -> false** | (follows from C2) |

The two SXT-033 edges artifacts were pre-#92 records. When re-emitted, their
`proposed_budget_results.rms_diff_dbfs` flag also moves to the corrected (#95)
predicate. The ledger classifies that separately as `RMS-FLAG-#95`, and the
spectral leg stays decisive even with the corrected rms flag. The SXT-040
badnews x2 artifacts stay **FAIL** (0.9700 / 0.9752), as #110 predicted.

**SXT-035 C2 (routed #163).** The smoothing-bypass control was "beyond the
model's own error" only on the legacy spectral leg, by 0.0026 (rms was never
worse than baseline). Under the new metric it is not worse at -80, -90, -100,
or -110 dBFS. The record now says `CONTROL FAILURE`. This is reported as-is,
not repaired here.

**Spectral-leg moves with no verdict change** (another leg still fails;
leg 2): legacy PASS -> FAIL on SXT-033 crush x2, SXT-034 uni4 repeated, and
sxt-035 modwheel. Legacy FAIL -> PASS on SXT-040 tentacles x2, sxt-022
modwheel and coverage, and sxt-035 coverage.

## 3. Regenerated artifacts (106) and how they were checked

(101 of these carry a #110-caused change, exactly as in the pre-rebase
record; the other 5 --
`reports/coverage-v1/{coverage,leaf-verification}.json` and
`reports/stereo-comparator-tail-gate/artifacts/sxt024-rerun/{click-wet,
hardreset-midpatch-wet,preset-notes-coverage-wet}.json` -- are regenerated
only because #161 also touched them; every leaf diff on those 5 classifies
`REBASE` or `SCHEMA-#111`, none `SPECTRAL`/`BUDGET-#110`/`VERDICT`.)

The regenerated JSONs were produced by the reports' own runners and
comparators before this record was written, in the same working tree. This
record does not rely on how they were produced. They are checked by re-run:

- **Dry int16 pairs.** Leg 3 runs the pre-#110 tool (materialized from
  `8ade1d18`) and this tool on every committed dry pair. Outputs differ only
  in `spectral_corr`, `spectral_corr_definition`,
  `proposed_budget_results.spectral_corr`, and a `verdict` whose spectral flag
  moved. Separately, re-running this tool on each dry pair that has a matched
  committed JSON reproduced that JSON exactly (20/20 comparable).
- **Stereo float32 pairs** (SXT-028c x6, sxt-023 x2 + nc-b x2, #100 rerun and
  controls). Recomputing `spectral_corr` per channel with the tool's own
  reader reproduced every committed value exactly (17/17).
- **Negative-control artifacts whose model render is not committed**
  (SXT-040, SXT-033, sxt-032, sxt-035, SXT-042 controls). These were re-rendered
  by their leaf runners. Leg 4 runs the pre-#110 tool on the **same** re-render
  and shows the only differences are #110-owned fields. The residual drift
  against the committed record (for example sxt-035 `vca-zeroed` max 38461 ->
  38478 LSB) is the re-render's, visible under the old tool too, and is
  classified `RE-RENDER` in the ledger. Every such control except SXT-035 C2
  keeps its required status.
- **sxt-023 records.** These were pre-#100 and are now re-emitted by the
  #100-gated tool, so they also gain the #100 tail-gate keys (`SCHEMA-#100`).

Full per-artifact class counts and every changed value:
`artifacts/regrade-ledger.{txt,json}`.

## 4. Carrying `spectral_corr` but NOT regenerated (28)

Each has a reason in the ledger:

- **NOT-MIGRATED** (their own per-leaf metric copy or a different budget
  family; routed #165): sxt-028a (aw-49, float32 log1p, 0.98 family),
  SXT-028e / SXT-028e-sse (distortion NCs), SXT-028f (reverb2 NCs), and
  the SXT-039 (x11) and sxt-037 (x1) L2 legs (0.999 family). These values are under the
  **legacy** definition and must not be compared with the #110 values.
- **STALE (cannot be re-graded here)**: `SXT-034/artifacts/uni2-poly.json`,
  `uni16-smoke.json` (their reference renders live on the pinned remote oracle
  and are not committed). Also `SXT-034/artifacts/nc2-*.json`: the NC-2 mutant
  inputs were not committed, and a reconstruction does not reproduce the
  committed render. Their spectral values are pre-#110 and are STALE until
  re-run on the oracle host.
- **UNCHANGED-BY-DEFINITION**: `sxt-026a/artifacts/audio-smoke-bells-dry.json`
  (3904 frames, shorter than one 4096 frame; both definitions give 0.0 for
  unequal sub-frame renders).
- **HISTORICAL** (not current verdicts): the #146
  `halfband-branch-order/artifacts/before-after-fixtures.json` and the #100
  `spectral-corr-sweep.json` (explicitly the legacy metric).

## 5. What is STALE after this PR, and what remains unproved

- **Pinned prose.** The leaf `EVIDENCE.md` records for SXT-033, SXT-034,
  SXT-028c, SXT-040, SXT-042, sxt-022, sxt-023, sxt-025, sxt-026, sxt-026a,
  sxt-032, sxt-035, and the #93/#100 tail-gate records quote pre-#110 spectral
  values. So do the `leaf-verification.json` notes for `osc:Sine` ("spectral
  corr missed everywhere") and `mod:modwheel`. With respect to the metric,
  this prose is **STALE**; the regenerated JSON artifacts are authoritative.
  It is not rewritten here because every file is sha256-pinned; the refresh
  and re-pin are routed to #164. **No leaf `verification` status changes**:
  `osc:Sine` and `osc:Classic` stay PARTIAL, and `mod:modwheel` stays
  NO_VERDICT.
- **Not decided here:** adoption. Whether the freeze adopts this definition,
  this floor, and the 0.98 budget is #12's decision. Any budget freeze, any
  fidelity or support claim, and SXT-035 C2's replacement discriminator
  (#163) also remain open.
