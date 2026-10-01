# Tooling audit — pre-fix shared-comparator `rms_diff_dbfs` polarity (issue #95)

Branch: `feature/issue-95` · Issue: #95 (tooling, follow-up from SXT-040 judge
review, PR #92) · Date: 2026-09-25

**Claim discipline.** This record is a read-only audit. It makes no fidelity,
RTL-exactness, coverage, or musical-quality claim of its own. It only
recomputes one budget leg (`rms_diff_dbfs`) from numbers already committed to
the repository and reports where the recorded flag and/or verdict disagree
with the corrected polarity. It does not modify `tools/compare_audio_reference.py`
(already fixed in PR #92) or any leaf's committed evidence/JSON.

## Background

`tools/compare_audio_reference.py` reported its rms budget leg as
`rms_diff_dbfs >= budget` — inverted. `rms_diff_dbfs` is the RMS level of the
*difference* waveform in dBFS (more negative = quieter diff = better); the
budget `<= -46 dBFS` requires the diff to be at least ~46 dB below full
scale, so the correct predicate is `rms_diff_dbfs <= budget`. PR #92
(commit `c0658747233c7a8c02036b1e178af9d8a75f105e`) fixed the predicate and
re-graded the SXT-040 (Sine) leaf's own evidence in place. That commit's
message explicitly routed every other leaf's pre-existing comparator JSON to
"a tool-lineage audit (follow-up issue)" — this is that audit.

## What was built

| Deliverable | Artifact |
|---|---|
| Audit script (read-only; recomputes the rms leg only) | `tools/audit_rms_polarity.py` |
| Committed audit report (deterministic, byte-stable) | `reports/tooling-rms-polarity-audit/artifacts/audit-report.json` |
| Unit tests: synthetic-pair predicate + end-to-end on the shipped comparator | `tests/test_rms_polarity_audit.py` |

## Method

1. Walk every committed `*.json` file under `reports/`.
2. Recursively locate every "row" — any (possibly nested) JSON object whose
   keys are a superset of the exact flat schema written by
   `tools/compare_audio_reference.py`'s `metrics` dict (`frames`,
   `ref_peak_lsb`, `model_peak_lsb`, `max_abs_diff_lsb`, `rms_diff_lsb`,
   `rms_diff_dbfs`, `rms_diff_at_shift0_lsb`, `best_shift`,
   `rms_diff_at_best_shift_lsb`, `spectral_corr`, `proposed_budgets`,
   `proposed_budget_results`, `verdict`) and which is **not** a `channels`/
   `leaf`-wrapped row from an independent per-leaf tool.
3. This distinguishes rows produced *directly* by the shared comparator from
   rows produced by tools that reimplement the same field names with their
   own (already-correct) polarity: `tools/compare_chorus_reference.py`
   (`worst["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"]`, SXT-028c) and
   `tools/compare_fx_reference.py` (same predicate, sxt-023). Both were
   checked by reading their source directly (not inferred) and are
   **confirmed immune** — no row from either is swept into this audit's
   affected set.
4. For every matched row, recompute `correct_rms_flag = rms_diff_dbfs <=
   proposed_budgets.rms_diff_dbfs` from the still-committed numeric value
   and budget. The `max_abs_diff_lsb` and `spectral_corr` legs are **never
   recomputed** — they are carried through at their committed values.
5. Recompute the row's overall verdict as
   `old_max_abs_flag AND correct_rms_flag AND old_spectral_flag`, and
   compare against the committed verdict string's `PASS`/`FAIL` prefix.
6. `reports/SXT-040/` (the leaf that PR #92 itself fixed and regenerated) is
   included in the scan for completeness, not excluded — it shows zero
   flips, which is an internal cross-check that the fix already landed
   cleanly there.

## Results

Reproduce with:

```
python3 tools/audit_rms_polarity.py \
  --out reports/tooling-rms-polarity-audit/artifacts/audit-report.json
```

| Metric | Value |
|---|---|
| JSON files scanned under `reports/` | 582 (post-commit; 581 before this report file existed) |
| Files containing at least one shared-comparator row | 49 |
| Rows audited | 57 |
| Rows whose `rms_diff_dbfs` flag flips under corrected polarity | 49 |
| Rows whose **overall verdict** flips | **3** |
| Parse errors | 0 |

Rms-flag flips by leaf (all pre-2026-09-24, all still `PASS`/`FAIL`-consistent
except the three below): `SXT-033` 10, `SXT-034` 9, `sxt-022` 3, `sxt-026` 9
(all 9 rows of `reports/sxt-026/artifacts/budget-metrics.json`), `sxt-026a` 1,
`sxt-032` 8, `sxt-035` 9. `reports/SXT-040/` and `reports/SXT-028c/` /
`reports/sxt-023/` (independent, already-correct tools): 0 flips.

For the 46 rows whose rms flag flips but whose overall verdict does **not**
flip, the recorded `max_abs_diff_lsb`/`spectral_corr` legs already
determined the same overall `PASS`/`FAIL` outcome under both polarities (most
commonly: those legs were already failing, so the row was already correctly
reported as `FAIL against proposed budgets`, and the rms flag was simply an
internal mislabel that never reached the surfaced verdict). Full per-row
detail (file, JSON path, `rms_diff_dbfs`, budget, old/correct flag, old/new
verdict) is in the committed `audit-report.json`.

### STOP: three landed leaves' overall verdicts flip PASS → FAIL

Per issue #95's stop/escalate clause, this audit does **not** re-grade these
rows. It stops and records the finding here.

| File | rms_diff_dbfs | Budget | Old verdict | Corrected verdict |
|---|---|---|---|---|
| `reports/sxt-022/artifacts/audio-seq-notes-repeated-v1.json` | −33.33 dBFS | ≤ −46 dBFS | PASS (PENDING-FREEZE) | **FAIL against proposed budgets** |
| `reports/SXT-034/artifacts/uni1-rep.json` | −33.33 dBFS | ≤ −46 dBFS | PASS (PENDING-FREEZE) | **FAIL against proposed budgets** |
| `reports/sxt-035/artifacts/audio-seq-notes-repeated-v1.json` | −33.33 dBFS | ≤ −46 dBFS | PASS (PENDING-FREEZE) | **FAIL against proposed budgets** |

All three rows are the *same underlying render* (the `seq-notes-repeated-v1`
same-pitch-retrigger sequence on the SXT-022 `Attacky.fxp` fixture):
`max_abs_diff_lsb` (2,321 ≤ 3,500) and `spectral_corr` (0.9874–0.9875 ≥
0.98) both already passed; only the rms leg was mislabeled `True` by the
inverted predicate (−33.3 dBFS is **louder**, not quieter, than the −46 dBFS
budget requires — it does not pass). SXT-034 bit-identically inherits the
SXT-022 render (uni=1 is a documented no-op) and SXT-035 likewise reduces to
the same render with no CC events; each leaf's own `EVIDENCE.md` currently
asserts the (incorrect) `PASS all three` / "passes all three proposed
bounds" language for this sequence:

* `reports/sxt-022/EVIDENCE.md` §Acceptance item 2: *"seq-notes-repeated-v1
  passes all three proposed bounds (max\|Δ\| 2,321 LSB; RMS −33.3 dBFS;
  spectral corr 0.9875)."*
* `reports/SXT-034/EVIDENCE.md` §4 table: *"uni1-regress | 2,321 | −33.3 |
  0.9874 | −4 | **PASS all three** (identical to the landed SXT-022
  metrics)"* and its §4 narrative *"uni1 passes all proposals."*
* `reports/sxt-035/EVIDENCE.md` §Acceptance item 2: *"seq-notes-repeated-v1
  passes all three proposed bounds (max 2,321 LSB; RMS −33.3 dBFS; spec
  0.9874)."*

These prose PASS claims are wrong under the corrected polarity and must be
re-graded — but **not inside this audit**. Follow-up: **issue #97** names all
three leaves and routes the re-grade through each leaf's own PR (or one
shared PR touching only those three `EVIDENCE.md` files plus a corrected
note, at the re-grading Builder's discretion). No number in *this* PR's
report has been altered to make that finding go away, and no leaf's
committed `EVIDENCE.md` is touched here.

## Acceptance mapping (issue #95)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Committed audit script + JSON report enumerating every affected file/row/old flag/recomputed flag; max_abs/corr legs untouched | **PASS** | `tools/audit_rms_polarity.py`, `reports/tooling-rms-polarity-audit/artifacts/audit-report.json` (57 rows, all three legs shown per row) |
| 2 | Open leaf → re-pin in its PR; landed leaf → bounded finding in its EVIDENCE + coverage pin update where the verdict is affected | **Routed, not applied here** | All affected leaves (SXT-022 #15, SXT-026/026a, SXT-032 #66, SXT-033, SXT-034 #68, SXT-035 #69) are landed/merged, not open PRs. The 46 flag-only flips do not change any surfaced verdict (bounded finding recorded above, no EVIDENCE edit needed). The 3 verdict flips are routed to follow-up issue #97 per the stop/escalate clause — **not applied inside this audit** |
| 3 | Deterministic, byte-stable re-run; unit test on synthetic pairs (silent-diff fails, quiet-diff passes, loud-diff fails under `<= -46`) | **PASS** | Re-running `tools/audit_rms_polarity.py` against the committed tree reproduces `audit-report.json` byte-for-byte (verified). `tests/test_rms_polarity_audit.py`: 9 tests — 3 on the audit's own predicate (silent-model-diff fails, quiet-diff passes, loud-diff fails), 2 on `audit_row` end-to-end recompute behavior (with/without a verdict flip), 1 on `find_rows`' wrapper exclusion, and 3 end-to-end against the actual shipped `tools/compare_audio_reference.py` on synthetic WAV pairs (silent-model/quiet-diff/loud-diff) |
| 4 | No silent re-grade: every verdict change visible in an evidence file, not only the audit report | **PASS** | The 3 verdict-flip rows are named, quoted (with their leaves' exact current EVIDENCE prose), and routed to issue #97 in this file — not silently absorbed into the audit JSON alone |

## Failure control

Verified directly (not merely asserted): temporarily re-inverting
`rms_leg_passes` in `tools/audit_rms_polarity.py` back to `>=` fails 5 of 9
tests in `tests/test_rms_polarity_audit.py`; separately, re-inverting the
predicate in the actual `tools/compare_audio_reference.py` fails the 3
end-to-end tests. Both files were restored to their correct (post-PR#92)
state before committing; `git diff` on both is empty relative to `main`.

## Stop/escalate

**Triggered.** Three landed leaves' overall verdicts (SXT-022 #15, SXT-034
#68, SXT-035 #69 — the shared `seq-notes-repeated-v1` baseline case) flip
PASS → FAIL under the corrected rms polarity. Per issue #95: this audit
reports the flip and does not re-grade it. Follow-up issue #97 tracks the
re-grade (EVIDENCE correction in each of the three leaves' own PR(s); no
coverage-promotion claim in this repository currently depends on this
specific row, but the affected leaves' A2/acceptance-item-2 language must be
corrected in place).

## Status update (dated, 2026-09-27, issue #157)

This report and the table immediately above are a **point-in-time record**
taken before issue #97 landed (commit `4e7bf63`, "Re-grade
seq-notes-repeated-v1 rms leg to FAIL in SXT-022/034/035 evidence (#97)").
That commit re-graded exactly the three rows named in the STOP table above —
`reports/sxt-022/EVIDENCE.md`, `reports/SXT-034/EVIDENCE.md`, and
`reports/sxt-035/EVIDENCE.md` (and their three JSON rows' `verdict`/
`proposed_budget_results.rms_diff_dbfs` fields; the underlying numeric
metrics were left untouched) — to state `FAIL against proposed budgets` on
the rms leg, matching the corrected `rms_diff_dbfs <= budget` polarity.
**Re-running `tools/audit_rms_polarity.py` against the current tree no
longer reports a verdict flip for those three rows** (`leaves_with_verdict_flip`
would be empty); this committed `audit-report.json` is intentionally left
unregenerated so the historical STOP finding above stays legible, rather than
silently disappearing. Issue #157 (this note) additionally re-grades the
`reports/coverage-v1/leaf-verification.json` ledger prose that depended on
the pre-fix reading of these rows and of the general rms-flag-flip class
recorded above (`voice:attacky-slice`, `voice:unison-stack`, `mod:modwheel`,
`mod:lfo`); no supported-preset count changed. The 46 flag-only (non-verdict)
flips recorded above — including all `reports/sxt-032/` (mod:lfo) rows and
the `reports/sxt-026/`, `reports/SXT-033/`, `reports/sxt-026a/` rows — remain
unregraded in their own EVIDENCE.md files as of this note; `mod:lfo`'s ledger
note is corrected here because its rms leg is asserted as a pass in the
ledger, but `reports/sxt-032/EVIDENCE.md` itself still carries the pre-fix
"RMS and spectral bounds PASS on all four sequences" prose and is left to
follow-up issue #177 (same class as #97, scoped only to the sxt-032 EVIDENCE
file) rather than corrected in this ledger-only issue. **[That last sentence
is superseded — see the #177 status update immediately below; the sxt-032
prose was re-graded by #145 before #177 was worked.]**

## Status update (dated, 2026-09-27, issue #177)

The `reports/sxt-032/EVIDENCE.md` prose re-grade routed to #177 by the #157
note above **had already landed** by the time #177 was worked. Commit
`94a90e0` ("#145: republish leaf artifacts invalidated by the #123 halfband
branch-order fix", PR #184) re-graded that record's acceptance row 2 from
"PASS/PENDING-FREEZE (mixed, honestly reported) | RMS and spectral bounds
PASS on all four sequences" to "FAIL vs [PROPOSED] budgets on all four
sequences", stating the rms leg as **FAIL on all four fixtures** (−32.8 /
−29.9 / −31.6 / −32.6 dBFS for repeated / coverage / holds / modwheel vs the
≤ −46 dBFS proposal) and attributing the rms-leg correction to the same
PR #92 / issue #95 polarity fix cited here; row 5's negative-control caveat
and the record's `#145` change-note table were re-graded with it. Because
#145 landed the polarity re-grade together with the #123 decimator
republication, the re-graded row carries the post-#123 numbers, not the
pre-#123 values #177's issue body quoted; the two corrections are separated
in that record's own change note.

Issue #177 therefore **verified rather than re-edited**. Checks performed on
the tree at `9a3aefd`:

* **Prose vs committed data (the issue's failure control).** Row 2's four rms
  values match `reports/sxt-032/artifacts/audio-{repeated,coverage,holds,
  modwheel}.json` `rms_diff_dbfs` (−32.803 / −29.897 / −31.557 / −32.646),
  every one of those files records
  `proposed_budget_results.rms_diff_dbfs: false` and
  `verdict: "FAIL against proposed budgets"`, and no rms pass is claimed
  anywhere in the record. The max-abs leg fails under both polarities, so no
  overall verdict moved.
* **Evidence pin.** `reports/coverage-v1/leaf-verification.json`'s `mod:lfo`
  evidence pin and `coverage.json`'s `inputs` entry both already hold the
  current `reports/sxt-032/EVIDENCE.md` digest `41a1fe58…` (re-pinned by
  #145's `evidence_pin_revisions` entry). `tools/publish_coverage.py`
  reproduces `coverage.json` byte-identically with no drift override, and
  `tools/coverage_negative_controls.py` reports `RESULT: PASS` (all five
  controls demonstrably fail the check they target).
* **No count or budget moved.** `mod:lfo`'s supported delta is 0 before and
  after, and the published headline `totals.supported` is unchanged. The
  bounds involved are `[PROPOSED-TO-BE-FROZEN-AT-PILOT]` placeholders owned by
  #12, so nothing frozen was touched and #177's stop/escalate condition
  (a supported-preset count or frozen-budget change) was not reached.

Still unregraded in their own EVIDENCE.md files, and outside #177's scope: the
flag-only flips in `reports/sxt-026/`, `reports/SXT-033/` and
`reports/sxt-026a/`. #157 re-graded only the four ledger notes it names
(`voice:attacky-slice`, `voice:unison-stack`, `mod:modwheel`, `mod:lfo`), so
those three leaves' own EVIDENCE records remain as-landed and no open issue
currently tracks them.

## What remains unproved

This audit establishes only that the recorded `rms_diff_dbfs` flags and, in
three cases, overall verdicts were computed with the pre-fix inverted
predicate. It does not re-verify the underlying renders, re-run the model or
RTL, or make any fidelity/coverage claim. The `sxt-026`/`sxt-026a` rows use
the SXT-022 `-46 dBFS` proposal embedded by the shared comparator itself;
`tools/run_sxt026_checks.py`'s own workhorse-budget check (`-30 dBFS`) is
computed independently in that script and was already correct polarity
(verified by reading its source) — this audit does not touch or re-derive
that separate acceptance path.

## Superseded by #110 (issue #164, 2026-10-01)

The "STOP" subsection's sentence "`max_abs_diff_lsb` (2,321 ≤ 3,500) and
`spectral_corr` (0.9874–0.9875 ≥ 0.98) both already passed" is this audit's
own present-tense claim (not one of the three verbatim leaf quotes
immediately below it, which stay untouched as a historical record of what
those `EVIDENCE.md` files asserted before #97's re-grade). It already
predates #123's halfband branch-order fix: the `seq-notes-repeated-v1`
render these three files share was re-rendered by #145, and its committed
spectral_corr is 0.9921 (sxt-022/sxt-035) / 0.9921 (SXT-034's `uni1-rep.json`,
0.992085) as of that fix — see each leaf's own `EVIDENCE.md` §4/#145-note.
PR #166 (issue #110, merged 2026-09-30) replaced the `spectral_corr`
definition again; per `reports/spectral-corr-fs-floor/artifacts/
regrade-ledger.{txt,json}` the current committed value for all three files
is **0.998840** (sxt-022: 0.998840 from 0.992074; SXT-034/sxt-035:
0.998840 from 0.992085) — still `>= 0.98`, so the spectral leg still
passes and the audit's STOP finding (the rms leg alone flips these three
rows PASS → FAIL) is unaffected either way.
