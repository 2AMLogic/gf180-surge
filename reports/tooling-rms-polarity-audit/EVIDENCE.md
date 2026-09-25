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
