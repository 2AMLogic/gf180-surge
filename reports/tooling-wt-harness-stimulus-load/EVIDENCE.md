# Tooling record — `compare_wt_rtl_model.py` stimulus-load reporting (issues #188, #194)

Branch: `feature/issue-188` · Issue: #188 (tooling; the remainder #182/#190
deliberately scoped out) · Base: `577eea9` · Date: 2026-09-27

Extended 2026-09-28 on branch `feature/issue-194` (base `8d44463`) with the
truncated-stimulus mechanism #188 deliberately left as a bounded finding —
see **"Truncated stimulus (issue #194)"** below. The #188 sections are left
exactly as they were written; nothing in them is re-graded.

**Claim discipline.** This record is about a *harness reporting path* and
nothing else. It makes **no** RTL-exactness, model-vs-reference, coverage, or
musical-quality claim, and it does **not** regenerate or re-grade any committed
artifact. The SXT-026 RTL-vs-model exactness claim continues to rest solely on
`reports/sxt-026/artifacts/rtl-exactness.txt`, which was **not** re-run here
(status NOT_RUN — `artifacts/stimulus-load-control.txt` §7).

## The defect

`tools/compare_wt_rtl_model.py` saw a simulator failure only through `vvp`'s
exit status and stderr. A stimulus file that never loaded is reported by Icarus
on **stdout**, and the simulation still exits **0**:

```
ERROR: .../tb_wavetable.sv:280: $readmemh: Unable to open rtl/wt_table.hex for reading.
```

The harness ran `vvp` with `capture_output=True` and discarded `run.stdout`
unconditionally, so the likeliest real operator error — a missing or truncated
`rtl/*.hex`, derived at run time from the external pinned asset tree and never
committed (decision-records/0004) — was reported as a *comparison
disagreement*: `verdict=FAIL sim_fails=[] mismatches=3
first_failures[0]="block 0 slot 0 voice 0: missing T line"`, with the missing
file's name appearing nowhere in the summary (measured on the real toolchain:
`artifacts/stimulus-load-control.txt` §1, control 1).

Two further mechanisms in the same family (folded into #188 by its own
2026-09-27 comment) exited by **traceback with no verdict JSON written at
all**: `subprocess.TimeoutExpired` from the `vvp` call and
`subprocess.CalledProcessError` from the `iverilog` compile. The pre-fix file
contained no `except` clause anywhere (§4).

## The fix

Four recognized simulator-level mechanisms, all landing in the `sim_fails` list
#182 introduced, and all setting the new `comparison: NOT_RUN` field:

1. **Declared inputs, checked before the simulator is invoked at all** —
   `model_trace.json` plus the five `rtl/*.hex` of the new `STIMULUS` table.
   This is the issue's checkbox-3 decision, taken **yes**: it is cheaper and
   more direct than pattern-matching simulator output and it names the exact
   file. The same table builds `vvp`'s command line, so the check cannot drift
   from what is actually passed. It does **not** replace mechanism 2 (a file
   can exist and still fail to open), so both are kept.
2. **`$readmemh: Unable to open` on `vvp`'s stdout, with rc=0** — matched
   narrowly, requiring both the `$readmem` token **and** `Unable to open`, and
   deliberately **not** a bare `ERROR:` prefix. A tail of `vvp`'s stdout is now
   retained in the summary (`sim_stdout_tail`) on failure, the way its stderr
   already was.
3. **Non-zero `vvp` exit** — the #182/#190 mechanism, unchanged.
4. **`CalledProcessError` / `TimeoutExpired`** (plus `OSError`, i.e. a missing
   `iverilog`/`vvp` binary) — caught and recorded, so the harness always writes
   a verdict with a reason instead of dying by traceback. A new `--timeout`
   flag (default 3600, the previous hard-coded value) makes the timeout leg
   exercisable.

When any of these fires, the comparison **and** the traffic reconciliation are
skipped: comparing model state against traces a run that never happened could
not have written is exactly the misreport this change exists to remove. The
verdict vocabulary is unchanged (every mechanism still fails closed as FAIL);
`comparison: PASS|FAIL|NOT_RUN` carries the distinction between "the
comparison ran and disagreed" and "the comparison never ran".

## Verification

| Check | Status | Where |
|---|---|---|
| Failure control: remove exactly one stimulus file ⇒ verdict names `rtl/wt_table.hex`, `comparison: NOT_RUN`, no "missing T line" | PASS | `artifacts/stimulus-load-control.txt` §1 (pre-fix, same run dir: `sim_fails=[] mismatches=3`, file unnamed) |
| Real `vvp` (Icarus 13.0), rc=0 with `$readmemh: Unable to open` on stdout ⇒ `sim_fails` names the file | PASS | §2, control 3 |
| **False-positive control**: a run whose stimulus loaded emits no `ERROR:`/`Unable to open` line on stdout at all, and the matcher adds nothing | PASS | §3, control 4 (measured on the real simulator) + control 5 (automated) |
| `CalledProcessError` from `iverilog` ⇒ `sim_fails` entry, not a traceback | PASS | §4, control 6 (pre-fix traceback for the same input) |
| `TimeoutExpired` from `vvp` ⇒ `sim_fails` entry, not a traceback (real over-running child) | PASS | §4, control 7 |
| Regression: a genuine non-zero `vvp` exit still reports correctly (#182/#190) | PASS | `tests/test_sxt026_wt_rtl_harness.py::test_simulator_failure_is_reported_as_fail_with_its_stderr` |
| Regression: the PASS path and the comparison-disagreement path are unchanged | PASS | §3 control 4 (real), `test_agreeing_trace_still_passes`, `test_comparison_mismatch_still_reported` |
| Automated controls in CI | PASS | `tests/test_sxt026_wt_rtl_harness.py` — 11 controls; **10 of them fail against the pre-fix harness** (§6) |
| Regression: re-run the committed-PASS SXT-026 fixture | **NOT_RUN** | §7 — stimulus derived from the external pinned asset tree, absent on this host |

The NOT_RUN row is **not** a pass. What can be said without re-running it is in
§7: on a run whose stimulus loaded and whose `vvp` exited 0, `sim_fails` is
empty (measured, §3 control 4), and with `sim_fails` empty every pre-existing
summary field and both exit paths are computed exactly as before — the summary
gains `comparison` and `sim_stdout_tail` and loses nothing.

Version attribution corrected (§5): every control here was measured on **Icarus
Verilog 13.0**, and #188 reproduced the same behavior on 12.0. The
"under Icarus 11" wording in
`reports/tooling-wt-harness-failure-path/artifacts/failure-path-control.txt` §5
is left as written — it records what that host measured — but the finding is
broader than it stated and is not cleared by a toolchain bump.

## Scope decision (issue #188, "enumerate them before scoping the fix")

Re-enumerated on this branch, not taken from the issue body:

```
$ grep -rl '_rtl_compile_common' tools/*.py | sort        # 11 files
tools/compare_classic_rtl_model.py   tools/compare_rtl_model_lp24.py
tools/compare_control_rtl.py         tools/compare_rtl_model_lpmoog.py
tools/compare_kt_rtl_model.py        tools/compare_rtl_model_rf_ains34.py
tools/compare_lfo_rtl_model.py       tools/compare_sine_rtl_model.py
tools/compare_mw_rtl_model.py
tools/compare_rtl_model.py           tools/compare_rtl_model_lp12.py
$ grep -n '_rtl_compile_common' tools/compare_wt_rtl_model.py   # (no output)
```

`tools/compare_wt_rtl_model.py` does its own inline `vvp` invocation and is not
among them. `tools/_rtl_compile_common.py::compile_and_run` uses `check=True`
throughout and therefore shares the blind spot (an exit-0 `$readmemh` failure
is invisible to `check=True` too), but each of those 11 harnesses has its own
verdict structure, its own notion of a trace, and would need its own
false-positive control before a matcher may touch its FAIL criterion.

**Decision: this PR is scoped to `tools/compare_wt_rtl_model.py` only** (the
file #188 names), and the shared helper is filed as **#193** with the
enumeration above. Changing 11 harnesses' FAIL criteria in a reporting fix,
without a per-harness healthy-run baseline, is precisely the risk #188's own
guardrail warns about.

## Bounded finding recorded, not fixed

A **truncated** (as opposed to absent or unopenable) stimulus file is still not
detected. Icarus reports it as `WARNING: … $readmemh(rtl/ctrl.hex): Not enough
words in the file for the requested range [0:262143]` — a length warning, not
an open failure, and one a healthy run is *expected* to emit (`ctrl_mem` is
declared `[0:262143]`). Matching it would flip genuinely passing runs to FAIL,
and the baseline needed to decide the question (which warnings a healthy
pinned-tree run emits) needs the external asset tree, absent here. Filed as
**#194** rather than guessed at; see §8 of the transcript.

> **Resolved 2026-09-28 (#194)** — the baseline was measured on a host that
> does have the pinned tree, and it confirms this section's reasoning was
> right to refuse a matcher: **all five** memories emit the warning on a
> genuinely PASSING run. The detection mechanism is therefore a content-level
> pre-flight check, not a matcher. See the section below.

## Truncated stimulus (issue #194)

Date: 2026-09-28 · Branch: `feature/issue-194` · Base: `8d44463` ·
Transcript: `artifacts/healthy-run-warning-baseline.txt` ·
Pinned asset tree: **present** on the executing host
(`ORACLE_SURGE_DATA=/home/ubuntu/scratch/sxt026-oracle/resources/data`;
both wavetable assets hash-match the fixtures' declared `wt_sha256`, and the
tree's `wavetables/` subset is enough for steps 6-7 of
`tools/run_sxt026_checks.py` but **not** for its oracle-render steps 1-5,
which stay NOT_RUN).

### The measurement the issue is gated on (§1 of the transcript)

A genuinely PASSING exactness run (`kick-wtfix-kt` /
`seq-wt-pitch-extremes-hi-v1`, 4125 blocks, `verdict=PASS comparison=PASS
mismatches=0`, Icarus 13.0) emits **one `$readmemh(<file>): Not enough words
in the file for the requested range [...]` WARNING per call site — all five of
them**:

| call site | memory | TB declares | file holds | warns on a PASSING run? |
|---|---|---|---|---|
| `tb_wavetable.sv:277` | `init_mem` | 64 | 40 | YES |
| `:279` | `ctrl_mem` | 262144 | 34878 | YES |
| `:280` | `wt_mem` | 131072 | 32736 | YES |
| `:281` | `sinc_tmp` (main) | 6144 | 3084 | YES |
| `:288` | `sinc_tmp` (deriv) | 6144 | 3072 | YES |

No subset of that text distinguishes a healthy run from a truncated one, at
any threshold: the warning fires in the healthy case for the *same* reason as
in the truncated case (the testbench's memory declarations are far larger than
any real stimulus). **Decision recorded: a stdout matcher is rejected, not
deferred.**

### The mechanism

A **content-level pre-flight check** (mechanism 5), beside the existence check
#188 added and before the simulator is invoked: each stimulus file's actual
hex-word count against the count the **model side** declares in the new
`rtl/stimulus_index.json`, which `model/oscillators/wavetable/run_model.py
--rtl` now writes beside the files it generates (word counts returned by
`write_hex`). The model knows each file's length by construction; the
testbench cannot supply it. A mismatch is a `sim_fails` entry naming that file
with both counts, and sets `comparison: NOT_RUN` like every other
simulator-level mechanism. The stimulus bytes are unchanged — the index is
purely additive (md5-verified, transcript §4).

A run dir with no usable index (tooling older than #194) is reported as
`stimulus_lengths.status: NOT_RUN` with the reason, **never** as a pass and
never as a failure: failing it closed would flip healthy runs to FAIL, the
exact outcome this issue forbids. Coverage is reported separately from
agreement — `stimulus_lengths.words` carries the measured and declared count
for every file either way.

### Verification

| Check | Status | Where |
|---|---|---|
| **Healthy-run baseline measured** on the live pinned tree, per memory | PASS | §1 (all 5 memories warn on a `verdict=PASS` 4125-block run) |
| Failure control: truncate exactly one file ⇒ `sim_fails` names `rtl/wt_table.hex` with both counts, `comparison: NOT_RUN`, simulator never invoked | PASS | §3 (half-file, 16368/32736) and §3 (32-word, 32704/32736) |
| **Known-good control**: the same untouched run dir still verdicts PASS with `sim_fails == []` and `stimulus_lengths: PASS`, identical `checked` counters to the pre-fix baseline | PASS | §4 |
| Pre-fix behavior on the same truncated dirs (the defect) | reproduced | §2 — half-file: `ValueError: invalid literal for int()` in `parse_traces`, **no verdict JSON**; 32-word: **verdict PASS**, file named nowhere |
| Regression: RTL mip-mutant negative control still fails the COMPARISON (not NOT_RUN) | PASS | §4 (`mismatches=68`, harness rc=0) |
| Automated controls | PASS | `tests/test_sxt026_wt_rtl_harness.py` — 16 controls; **5 fail against the pre-fix harness**, the 11 pre-existing #182/#188 controls still pass (§5) |
| Full repository suite | PASS | `python3 -m pytest -q tests` — 799 passed, 17 skipped |
| Re-grade of `reports/sxt-026/artifacts/rtl-exactness.txt` | **NOT_RUN** | §6 — not regenerated by this change; §1/§4's run is fresh evidence about the harness, not a new exactness claim |

### Bounded finding, not fixed here

The 32-word control (§2b) shows a truncated stimulus file could produce a
**passing** exactness transcript under the pre-fix harness, and that a pre-#194
verdict records no stimulus length at all — so the *format* of a committed
pre-#194 PASS transcript cannot by itself rule that out. This does **not**
show that `reports/sxt-026/artifacts/rtl-exactness.txt` was so produced: the
run regenerated from the pinned tree here has complete stimulus and PASSES.
The remaining narrow gap — `rtl-exactness.txt` carries only the fields step 6
of `tools/run_sxt026_checks.py` writes, not the new `stimulus_lengths` status —
is filed as its own issue rather than fixed in this change.

## Artifacts

| File | Content |
|---|---|
| `artifacts/stimulus-load-control.txt` | the real-toolchain before/after controls (missing file, unreadable file, healthy load), the two exception controls, the version measurement, the automated-suite result including its 10/11 failure against the pre-fix harness, the NOT_RUN record for the committed fixture, and the truncation finding |
| `artifacts/healthy-run-warning-baseline.txt` | #194: the pinned-asset-tree usability check, the per-memory healthy-run `$readmemh` warning inventory from a PASSING 4125-block run, the two pre-fix truncation reproductions (traceback / false PASS), the fixed-harness positive control, the known-good PASS re-run, the mutant re-run, and the automated-suite result including its 5/16 failure against the pre-fix harness |

The scratch run directory (`/tmp/wt188-control`: synthetic `model_trace.json`,
empty hex stimulus, compiled `tb_wt.vvp`) and the pre-fix harness copy
(`/tmp/wt188-prefix`) are deliberately not committed; the transcript records
the commands so they can be rebuilt.
