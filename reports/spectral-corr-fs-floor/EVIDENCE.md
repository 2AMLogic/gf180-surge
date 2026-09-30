# Shared full-scale log-floor `spectral_corr` (evidence record)

Issue: #110 · Parent: #12 (SXT-017 pilot freeze) · Characterized in #100
(`reports/stereo-comparator-tail-gate/` section 6) · Date: 2026-09-27;
regraded 2026-09-30 on post-#145 `main` (section 6)

Tools changed: `tools/compare_audio_reference.py` (the one shared definition:
`spectral_corr`, `SPECTRAL_CORR_*`, `FULL_SCALE_*`; legacy kept only as
`spectral_corr_legacy_log1p` for the regrade record),
`tools/compare_chorus_reference.py` and `tools/compare_fx_reference.py` (now
delegate to the shared function with float32 full scale 1.0),
`tools/stereo_tail_gate_checks.py` (#100 leg 4 pinned to the legacy metric;
diff classifier knows `METRIC-#110`). New: `tools/spectral_corr_fs_floor_checks.py`
(legs 1-6 below), `tools/regrade_spectral_corr.py` (regrade ledger,
attributed against `main` as this branch merged it -- section 6),
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
| One definition in every comparator grading the shared 0.98 budget | **PASS** (shared function; stereo tools delegate; tests pin it) | `tests/test_spectral_corr_fs_floor.py` (10 definition tests + 7 attribution tests, section 6) |
| Unit invariance: same signal on int16 and float32 buses gives the same value | **PASS** (behemoth +-1 LSB: 0.999980 on both; legacy 0.927389 vs 0.999999) | `artifacts/unit-sweep.txt` (leg 1) |
| Frame gating alone does not fix the empty-bin case | **Confirmed** (behemoth +-1 LSB, gated legacy 0.9274); gating is not part of the definition | `artifacts/unit-sweep.txt` |
| Dry re-run parity: pre-#110 tool (`main`'s, at the base) vs this tool on every committed dry pair differ only in #110-owned fields | **PASS** (37/37; 0 unexplained) | `artifacts/dry-parity.{txt,json}` (leg 3) |
| Re-rendered control artifacts: the non-spectral diffs come from the re-render, not the metric | **PASS** (21/21; every re-render reproduces `main`'s committed non-spectral metrics exactly; SXT-042 runner-added `windowed_rms_lsb` recomputed equal on the same render) | `artifacts/rerender-proof.{txt,json}` (leg 4) |
| #93 and #100 tail-gate control legs under the new metric | **PASS** (#93 leg 2: 8/8 as required; #100 leg 2: 17/17 CONTROL-OK); every carried leg and header field of both summaries byte-identical to `main`'s record | `artifacts/tail-gate-controls.txt` (leg 5) |
| Regrade ledger: every committed diff against `main` classified | **PASS** (102 artifacts regenerated; 0 UNEXPLAINED; 28 carrying `spectral_corr` not regenerated, each with a reason) | `artifacts/regrade-ledger.{txt,json}` (leg 6) |
| Verdict / control-status flips against `main` | **2, named below**, both caused by #110 | `artifacts/regrade-ledger.txt` |
| SXT-035 C2 `smoothing-bypass` spectral discrimination | **FINDING (no status change)**: the spectral leg does not discriminate this control under the new metric; since #163 (on `main`) C2 rests on the control-plane `mw-ramp` discriminator, so `control_ok` and `overall_ok` stay true | `artifacts/rerender-proof.txt`, `reports/sxt-035/artifacts/negative-controls.json` |
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
value. On the committed renders as of `main` at the section 6 base (after
#145 re-rendered them), three pairs change their spectral-leg outcome
somewhere within [-110, -90] dBFS:

| Pair | -90 | **-100** | -110 |
|---|---|---|---|
| SXT-033 crush seq-notes-coverage-v1 | 0.9717 | **0.9796** | 0.9855 |
| SXT-033 crush seq-notes-repeated-v1 | 0.9754 | **0.9828** | 0.9886 |
| SXT-040 badnews seq-notes-repeated-v1 | 0.9833 | **0.9752** | 0.9735 |

Crush-coverage's spectral-leg FAIL depends on the declared floor: at -110 it
would pass (its verdict stays FAIL either way, on max and rms). The two
verdicts #110 moves (section 2) are floor-insensitive in [-110, -90]
(edges-coverage 0.9987-0.9991, popcorn2k-coverage 0.9904-0.9918). The
SXT-035 C2 spectral leg would discriminate again only at -120 dBFS. The
floor was **not** moved for any case (#110 stop condition). *(The
2026-09-27 table named SXT-040 popcorn2k-coverage and sxt-032 modwheel as
floor-sensitive. That was on the pre-#145 renders, and neither is
floor-sensitive on the current ones.)*

**Sensitivity consequence the freeze must weigh.** A broadband residual now
starts to miss 0.98 at about -68 dBFS in every tool (leg 1: koala2 0.9834 and
behemoth 0.9511 at -68 dBFS; fmcombo 0.9595 and alienappears 0.9300 at
-68 dBFS). Before, the int16 tool missed at -92 dBFS and the float tools at
-44 to -56 dBFS. The metric is more lenient than before on the int16 tool and
stricter on the float tools.

## 2. Verdict and control-status flips against `main` (2, both #110)

Cause is attributed by counterfactual (`regrade_spectral_corr.cause_of_flip`).
Both flips are decisive on the spectral leg. With the old spectral flag, the
verdict would be the old one. The ledger diffs against `main` as this branch
merged it (section 6), so these are exactly the verdicts that merging #110
moves on today's `main`.

| Artifact | Field | Before -> after | Spectral legacy -> adopted |
|---|---|---|---|
| `reports/SXT-033/artifacts/budget-edges-seq-notes-coverage-v1.json` | verdict | **FAIL -> PASS** | 0.9744 -> 0.9990 |
| `reports/SXT-040/artifacts/budget-popcorn2k-seq-notes-coverage-v1.json` | verdict | **FAIL -> PASS** | 0.9666 -> 0.9908 |

Both are PASS (PENDING-FREEZE) against `[PROPOSED]` budgets only. The
2026-09-27 record listed four #110 verdict flips. SXT-033 edges-repeated and
SXT-040 popcorn2k-repeated are no longer #110's: #145 already moved both to
PASS on `main` under the legacy metric, and they stay PASS under this one.
The SXT-040 badnews x2 artifacts stay **FAIL** (0.9700 / 0.9752), as #110
predicted.

**SXT-035 C2 (#163): finding, no status flip.** The smoothing-bypass
control's rms is better than the unmutated baseline. Under the new metric its
spectral leg is not worse at -80, -90, -100 or -110 dBFS (leg 4), so the
spectral leg no longer discriminates it: `beyond_model_error_via` moves from
`['spectral', 'mw-ramp']` to `['mw-ramp']`. Since #163 landed on `main`, C2
rests on the control-plane `mw-ramp` discriminator (blocks-to-converge after
each CC dispatch), which still trips (margin 27 blocks). So
`smoothing-bypass.control_ok` and `overall_ok` stay **true**. The
2026-09-27 record's `true -> false` flip on both fields predates #163 and no
longer happens.

**Spectral-leg moves with no verdict change** (another leg still fails;
leg 2 and the ledger's `BUDGET-#110` rows): legacy PASS -> FAIL on SXT-033
crush-coverage, SXT-034 uni4 repeated, sxt-035 modwheel, and the sxt-035
baseline / cutoff-zeroed / reso-zeroed / smoothing-bypass controls (all of
which FAIL, as they must, on max/rms). Legacy FAIL -> PASS on SXT-040
tentacles x2, sxt-022 coverage, and sxt-035 coverage.

## 3. Regenerated artifacts (102) and how they were checked

Every one differs from `main`'s committed record only in classes the ledger
explains (totals over all 102: SPECTRAL 213, DEFINITION 81, SCHEMA-#100 245,
BUDGET-#110 13, VERDICT 9, ULP 34, HOST-PATH 10, RUN-METADATA 10). The
SCHEMA-#100 leaves are all additions: the sxt-023 records `main` still holds
in their pre-#100 shape, re-emitted by the #100-gated tool. HOST-PATH leaves
are scratch or checkout prefixes only. RUN-METADATA is the #110
`partial_reruns` note in the two tail-gate summaries.

The regenerated JSONs were produced by the reports' own runners and
comparators in the same working tree (section 6 names each producer for the
58 that `main` had also republished). They are checked by re-run:

- **Dry int16 pairs.** Leg 3 runs the pre-#110 tool (`main`'s, materialized
  from the base) and this tool on every committed dry pair. Outputs differ only
  in `spectral_corr`, `spectral_corr_definition`,
  `proposed_budget_results.spectral_corr`, and a `verdict` whose spectral flag
  moved. Separately, `tests/test_halfband_republication.py` re-derives the
  28 committed budget JSONs from their committed renders with this tool and
  passes.
- **Stereo float32 pairs** (SXT-028c x6, sxt-023 x2 + nc-b x2, #100 rerun and
  controls). Recomputing `spectral_corr` per channel with the tool's own
  reader reproduced every committed value exactly (17/17).
- **Negative-control artifacts whose model render is not committed**
  (SXT-040, SXT-033, sxt-032, sxt-035, SXT-042 controls). These were re-rendered
  by their leaf runners. Leg 4 runs the pre-#110 tool on the **same** re-render
  and shows the only differences are #110-owned fields. Every re-render
  reproduced `main`'s committed non-spectral metrics exactly (re-render
  drift 0 keys; SXT-042's 2 keys are the runner-added `windowed_rms_lsb`,
  recomputed equal), so the ledger has no `RE-RENDER` rows this time. Every
  control keeps its required status.
- **sxt-023 records.** These were pre-#100 and are now re-emitted by the
  #100-gated tool, so they also gain the #100 tail-gate keys (`SCHEMA-#100`).

Full per-artifact class counts and every changed value:
`artifacts/regrade-ledger.{txt,json}`.

## 4. Carrying `spectral_corr` but NOT regenerated (28), and other carried items

Each JSON has a reason in the ledger:

- **NOT-MIGRATED** (their own per-leaf metric copy or a different budget
  family; routed #165): sxt-028a (aw-49, float32 log1p, 0.98 family),
  SXT-028e / SXT-028e-sse (distortion NCs), SXT-028f (reverb2 NCs), and
  the SXT-039 (x11) and sxt-037 (x1) L2 legs (0.999 family). These values are under the
  **legacy** definition and must not be compared with the #110 values.
- **STALE (cannot be re-graded here)**: `SXT-034/artifacts/uni2-poly.json`,
  `uni16-smoke.json` (their reference renders live on the pinned remote oracle
  and are not committed). Also `SXT-034/artifacts/nc2-*.json`: #145
  republished them on a host holding the NC-2 mutant inputs, which are not
  committed, so they cannot be re-rendered here. Their spectral values are
  legacy and STALE until re-run with those inputs.
- **HISTORICAL** (not current verdicts): #145's
  `halfband-republication/artifacts/republication-record.json`, #146's
  `halfband-branch-order/artifacts/before-after-fixtures.json`, and #100's
  `spectral-corr-sweep.json` (explicitly the legacy metric).

Not JSON, so outside the ledger, and named here instead:

- **STALE: `reports/sxt-026/artifacts/nc-b-mip-mutant.txt`** keeps `main`'s
  legacy-metric numbers. Its mutant render (`SXT026_NC_B_FORCE_MIP6`) reads
  the pinned wavetable asset root, which is not on the host that ran this
  regrade. `budget-metrics.json` in the same leaf **is** regenerated, from
  committed renders.
- **Carried verbatim from `main`**: the three sxt-035 `carrier-*` refusal
  rows in `negative-controls.json` / `negative-control.txt`. They need the
  pinned oracle, and this host refused all three only for "preset not
  found", not for the class reasons the record states. They carry no
  spectral value.
- `reports/sxt-026a/artifacts/compare__sxt025-accept-v1.json`: only its three
  `full_render` `spectral_corr` values are recomputed. A full re-run also
  moved non-spectral tail and rms floats by up to 5e-7 relative (host float
  differences against `main`'s record), and those are not #110's to change.

## 5. What is STALE after this PR, and what remains unproved

- **Pinned prose.** The leaf `EVIDENCE.md` records for SXT-033, SXT-034,
  SXT-028c, SXT-040, SXT-042, sxt-022, sxt-023, sxt-025, sxt-026, sxt-026a,
  sxt-032, sxt-035, and the #93/#100 tail-gate records quote pre-#110 spectral
  values. So do the `leaf-verification.json` notes for `osc:Sine` ("spectral
  corr missed everywhere") and `mod:modwheel`. With respect to the metric,
  this prose is **STALE**; the regenerated JSON artifacts are authoritative.
  It is not rewritten here because every file is sha256-pinned; the refresh
  and re-pin are routed to #164. That now includes the #145 change notes
  those leaves gained on `main` (for example SXT-033 / SXT-040's
  `FAIL -> PASS (PENDING-FREEZE)` rows and their spectral margins), which
  quote legacy-metric values. **No leaf `verification` status changes**:
  `osc:Sine` and `osc:Classic` stay PARTIAL, and `mod:modwheel` stays
  NO_VERDICT.
- **Not decided here:** adoption. Whether the freeze adopts this definition,
  this floor, and the 0.98 budget is #12's decision. Any budget freeze, any
  fidelity or support claim, and SXT-035 C2's replacement discriminator
  (#163) also remain open.

## 6. Merge onto post-#145 `main` and the attribution fix (2026-09-30)

**What happened.** The 2026-09-27 regrade was rebased onto `main` after
#111 (b2834e9). Its PR re-review found that the leg-5 summary merge
(`_merge_summary`) started every tail-gate summary from a hard-coded
pre-#111 SHA (`8ade1d1`). Once the branch sat on a `main` that had #111,
each leg-5 run silently reverted #111's carried legs and header fields. In
the stereo summary those were `sxt028c_rerun`, `rms_diff_dbfs_floor`,
`other_stereo_comparators_rerun`, `amended_by_issue`,
`proposed_tail_budget`, `run_utc` and `repo_head`, plus the #111 header
line of `negative-controls.txt`. In the shared summary they were
`dry_rerun_parity`, `run_utc` and `repo_head`. The ledger could not see
the revert, because it skipped every leaf equal to that same stale base.
**So the 2026-09-27 line "Net effect on this PR's own claims: none" was
wrong.** It held for the #110 flips and the `spectral_corr` values, but
not for those carried legs, which that record did not mention.

**Fix (tools).** Both tools now attribute against one base: `main` as this
branch last merged it (`git merge-base HEAD origin/main`). It is resolved at
run time, recorded in `artifacts/checks-summary.json` (`base_rev`), and
never pinned. Derivation fails loudly if it cannot resolve, is not an
ancestor of HEAD, or equals HEAD.
- `_merge_summary` starts from `main`'s record at that base, and leg 5 FAILS
  if any carried leg or top-level field of what it wrote differs from it
  (`carried_mismatches`). This run: **byte-identical** for both summaries.
- The ledger diffs the working tree against the same base, so a leaf put
  back to an older value is a diff that must classify. An artifact the
  branch adds or deletes is UNEXPLAINED, not skipped.
- `SCHEMA-#100` / `SCHEMA-#111` are additions only. A changed value never
  classifies as schema.
- Tests: the committed tail-gate summaries' carried fields equal `main` at
  the recorded base. A live negative control asserts that the same leg
  merged onto `8ade1d1` FAILS that check. Plus unit tests for the classifier
  and base resolution.

**Merge (artifacts).** `main` had moved 129 commits. Among them, #145
re-rendered every committed model artifact behind the shared scene
decimator (and republished its budget JSONs and negative-control sets under
the legacy metric), and #163 gave SXT-035 C2 a control-plane discriminator.
58 artifacts conflicted. Each was taken from `main` and regenerated on the
merged tree by its own producer:
- The 27 dry budget JSONs: `compare_audio_reference.py` on the committed
  renders.
- SXT-033 / SXT-040 controls: `run_sxt033_checks.py` / `run_sxt040_checks.py`
  step 3.
- sxt-032 / sxt-035 / SXT-042 control sets: `lfo_negative_controls.py`,
  `mw_negative_controls.py`, `kt_negative_controls.py`.
- SXT-034 NC-1: the two commands in its `negative-control.txt`.
- sxt-026 `budget-metrics.json`: `run_sxt026_checks.py` step 5, from
  committed renders.
- sxt-026a: `compare_integration.py`, spectral values only (section 4).

RTL-exactness JSONs rewritten as a side effect of the NC runners were
restored to `main`'s bytes. Their new fields come from `main`'s own tooling
and are not #110's.

**Base of this record:** `baba823b266ef6740aa360cda07d8b4967b02fe4`
(`artifacts/checks-summary.json`, `artifacts/regrade-ledger.json`).

