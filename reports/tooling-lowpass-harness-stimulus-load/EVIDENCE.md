# Tooling record — lowpass-family harness stimulus-load reporting (issue #209)

Branch: `feature/issue-209` · Issue: #209 (parent #201, grandparent #193;
precedent #188 / merged PR #202) · Base: `cca66f2` · Date: 2026-09-28 ·
Toolchain: Icarus Verilog 13.0 (stable) (v13_0), Python 3.12.3

**Claim discipline.** This record is about a *harness reporting path* and
nothing else. It makes **no** RTL-exactness, model-vs-reference, coverage, or
musical-quality claim, and it regenerates and re-grades **no** committed
artifact. The SXT-037 / SXT-038 / SXT-039 RTL-vs-model exactness claims
continue to rest entirely on their own committed exactness runs against
oracle-derived stimulus, which were **NOT re-run here (status NOT_RUN)** — the
external pinned asset tree (decision-records/0004) is not present on this
host, and none of the controls below need it.

Every model trace used below is *synthesized from whatever trace the testbench
under test actually produced* (or from that trace with exactly one sample
perturbed). That is deliberate and sufficient for a reporting control, and it
is **not** evidence that the RTL matches the frozen model: nothing here
compares the RTL against a model-derived expectation.

## The defect (pre-existing; inherited from the shared helper)

`tools/_rtl_compile_common.compile_and_run` drove these three harnesses'
`iverilog`/`vvp` steps with `check=True` throughout, which sees a non-zero exit
only. Issue #188 measured that Icarus reports a `$readmemh` target which fails
to open on the simulation's **STDOUT** while `vvp` still **exits 0**.
Reproduced live here, per leaf, with exactly one stimulus file
(`rtl/in.hex`) removed from an otherwise complete run dir
(`artifacts/stimulus-load-control.txt`, PART 1):

```
ERROR: .../rtl/voice/tb_lp12.sv:72:   $readmemh: Unable to open rtl/in.hex for reading.
ERROR: .../rtl/voice/tb_lp24.sv:79:   $readmemh: Unable to open rtl/in.hex for reading.
ERROR: .../rtl/voice/tb_lpmoog.sv:110: $readmemh: Unable to open rtl/in.hex for reading.
```

all three with `vvp rc=0`, and all three going on to write a
complete-looking trace from a memory that was never loaded. The harness then
parsed that trace and reported the run as an RTL-vs-model **disagreement**.

### A second, sharper consequence found in this leaf family

`tools/compare_rtl_model_lp24.py` has an `--expect {pass,fail}` axis and exits
`0` when the verdict matches `--expect`. `tools/lp24_negative_controls.py`
drives the committed RTL rounding mutant through
`compare_rtl_model_lp24.py --expect fail` and treats that as control **NC-D**.

A stimulus-load failure also produces `verdict: FAIL` — so before this change,
a run whose stimulus never loaded **satisfied the negative control**. Measured
live (`artifacts/stimulus-load-control.txt`, PART 2): with `rtl/init.hex`
removed, `tb_lp24.sv` reads `n_blocks` as x, writes an **empty but perfectly
parseable** trace, exits 0, and

```
PRE-migration (origin/main)    rc=0 verdict=FAIL comparison=None sim_fails=None
     ^^ rc=0 under --expect fail: the stimulus-load failure was ACCEPTED as a
        passing negative control
POST-migration (this branch)   rc=1 verdict=FAIL comparison=NOT_RUN
        sim_fails=["missing declared input: rtl/init.hex ..."]
```

That is a control that did not demonstrably fail the check it targets. It is
now fail-closed in two places: the harness exits non-zero on any `sim_fails`
regardless of `--expect`, and `nc_d` requires `comparison == "FAIL"` (the
comparison actually ran and disagreed) rather than `verdict == "FAIL"` alone.

## The fix

Each leaf opts into the shared helper's `report_sim_fails=True` /
`stimulus_files=` mode (added for #193 by merged PR #202) and gates its own
comparison on the result:

| Harness | Leaf | Declared stimulus | Reporting entry point |
|---|---|---|---|
| `tools/compare_rtl_model_lp12.py` | SXT-037 | `rtl/init.hex`, `rtl/ctrl.hex`, `rtl/in.hex` | `build_and_run_reporting()` |
| `tools/compare_rtl_model_lp24.py` | SXT-038 | same | inline in `main()` |
| `tools/compare_rtl_model_lpmoog.py` | SXT-039 | same | `build_and_run_reporting()` |

`lp12` and `lpmoog` keep their existing public `build_and_run()` with its
**legacy** contract (returns the trace path; raises on a non-zero
compile/run), because `tools/lp12_negative_controls.py`,
`tools/lpmoog_negative_controls.py`, `tools/run_sxt039_checks.py` and
`tests/test_sxt039_lpmoog.py` all consume that path. The reporting mode is a
second entry point, so no existing caller's contract moves.

Each summary gains `comparison` (`PASS` / `FAIL` / `NOT_RUN`), `sim_fails` and
`sim_stdout_tail`; every pre-existing key keeps its exact meaning.

## Controls

### 1. False-positive control FIRST, measured per leaf (#193's Stop/escalate)

Issue #188's guardrail: a matcher that turns a genuinely passing exactness run
into a FAIL is worse than the lost reason it recovers, and #188's measurement
on `tb_wavetable.sv` does **not** transfer to another testbench. Measured here
against real Icarus 13.0 on each leaf's real testbench **before** the matcher
was wired in (`artifacts/stimulus-load-control.txt`, PART 1, "healthy
stdout"):

| Leaf | Healthy-run stdout | Lines matching `$readmem` **and** `Unable to open` |
|---|---|---|
| `tb_lp12.sv` | 2× `$readmemh(...): Not enough words...` WARNING, `DONE qmuls=768 blocks=1 inputs=64`, `$finish` | **0** |
| `tb_lp24.sv` | 2× same WARNING, `DONE qmuls=1216 blocks=1 inputs=64`, `$finish` | **0** |
| `tb_lpmoog.sv` | 2× same WARNING, `DONE qmuls=576 blocks=1 inputs=64`, `$finish` | **0** |

No leaf's healthy run emits an `ERROR:`-prefixed line at all, so #193's
Stop/escalate condition ("if any harness's healthy run DOES emit
`ERROR:`-prefixed stdout lines, stop and record it") **does not fire** for any
of these three. The matcher stays the narrow `$readmem` + `Unable to open`
conjunction inherited from `compare_wt_rtl_model.py`; nothing was widened to a
bare `ERROR:` prefix.

This measurement is not frozen into a string and left to rot: it is re-run as
a live test (`tests/test_lowpass_rtl_harness_reporting.py::
test_live_healthy_run_does_not_trip_the_matcher`, one case per leaf), which
SKIPS — never silently passes — when `iverilog`/`vvp` are absent.

### 2. Failure control (#193's / #209's acceptance bar), per leaf

Remove exactly one stimulus file from an otherwise complete run dir; the
verdict must name **that file** and must not present the run as a model
disagreement. Measured for all three leaves
(`artifacts/stimulus-load-control.txt`, PART 1, case C):

```
[C missing rtl/in.hex] rc=1 verdict=FAIL comparison=NOT_RUN
                       checked={'samples': 0, 'checkpoints': 0, 'fields': 0}
    sim_fails[0]: missing declared input: rtl/in.hex (absent from the run dir; …)
```

`first_failures` contains no sample/checkpoint mismatch at all, and the
simulator is never invoked (mechanism 1 short-circuits pre-flight).

### 3. Known-good control, per leaf

The same leaf, the same complete run dir, must keep its **previous** verdict.
Verified by running the **pre-migration** harness (extracted from
`origin/main`) and this branch's harness over the identical run dir and
comparing every pre-existing summary key
(`artifacts/stimulus-load-control.txt`, PART 1, "[pre-migration]" vs "[A
complete+agree]"):

| Leaf | pre-migration | this branch | `verdict`/`checked`/`mismatches`/`first_failures` |
|---|---|---|---|
| lp12 | rc=0 PASS, checked `{samples:64, checkpoints:1, fields:12}` | rc=0 PASS, `comparison: PASS`, `sim_fails: []` | identical |
| lp24 | rc=0 PASS, checked `{samples:64, checkpoints:1, fields:14}` | rc=0 PASS, `comparison: PASS`, `sim_fails: []` | identical |
| lpmoog | rc=0 PASS, checked `{samples:64, checkpoints:1, fields:14}` | rc=0 PASS, `comparison: PASS`, `sim_fails: []` | identical |

### 4. A genuine disagreement is still a disagreement, per leaf

With complete stimulus and one model sample perturbed by 1 LSB, all three
report `verdict: FAIL` with `comparison: FAIL`, `sim_fails: []` and a
`first_failures[0]` naming the sample — i.e. the change does not swallow real
RTL-vs-model mismatches (PART 1, case B).

### 5. The new controls demonstrably fail the code they target

Running `tests/test_lowpass_rtl_harness_reporting.py` unchanged against a
clean `origin/main` checkout: **26 failed, 5 passed, 2 skipped.** The 5 that
pass there are exactly the ones asserting *preserved* behavior (the legacy
`build_and_run` raise contract, and the live per-leaf healthy/missing stdout
measurement, which is a property of the unchanged testbenches). Every control
that targets the new reporting path fails without it.

### 6. NC-D itself, both directions

- with `rtl/init.hex` removed → `control_ok: False`, message says
  `CONTROL-BROKEN` and names the simulator-level failure;
- with complete stimulus and the committed rounding mutant → `control_ok:
  True`, `comparison: FAIL` (real `iverilog`/`vvp`) — the tightened criterion
  does not break the control it protects.

## Reproduction

```
# new controls (this PR)
python3 -m pytest tests/test_lowpass_rtl_harness_reporting.py
#   -> 31 passed, 2 skipped   (the 2 skips: lp24 has no public build_and_run)

# the three leaves' own suites + the shared helper's + the two already-migrated
# leaves' reporting suites, all unchanged by this PR
python3 -m pytest tests/test_sxt037_lp12.py tests/test_sxt038_lp24.py \
                  tests/test_sxt039_lpmoog.py tests/test_rtl_compile_common.py \
                  tests/test_sxt021_rtl_harness_reporting.py \
                  tests/test_sxt022_rtl_harness_reporting.py
#   -> 95 passed

# whole suite
python3 -m pytest -q tests        # -> 862 passed, 19 skipped

# the two ad-hoc real-toolchain probes that produced artifacts/stimulus-load-control.txt
python3 reports/tooling-lowpass-harness-stimulus-load/artifacts/probe-reporting-controls.py
python3 reports/tooling-lowpass-harness-stimulus-load/artifacts/probe-expect-fail-hazard.py
```

The two probe scripts hard-code this worktree path and a
`/tmp/sxt209-baseline/tools` extract of `origin/main`
(`git archive origin/main tools | tar -x -C /tmp/sxt209-baseline`); they are
retained as the exact scripts that produced
`artifacts/stimulus-load-control.txt`, not as a maintained tool.

**Amendment (issue #216, 2026-09-28).** PART 1 case D's *pre-migration* line
originally read `rc=1 verdict=FAIL (<- the hazard this fixes)`. That verdict
was never produced by that run: case D keeps `rtl/init.hex`, so `n_blocks`
reads as 1, `tb_lp24.sv` writes `Y` lines valued `x`, and the pre-migration
harness dies parsing them (`ValueError: invalid literal for int() with base
10: 'x'`) without writing `--out` at all. `probe-reporting-controls.py`'s
`harness()` helper did not unlink `--out` before invoking the subprocess, so
it read back the *previous* (post-migration) case-D run's `verdict.json` — a
**STALE** read reported as a verdict. The correct status for that run is
**NO_VERDICT**. The helper now removes `--out` first (matching
`probe-expect-fail-hazard.py`, which already did), and the transcript line
reports `NO_VERDICT` with the parse error that caused it. Re-running the
corrected `probe-reporting-controls.py` reproduces every other PART 1 line
byte-for-byte, so no other case (A, B, C, the per-leaf `[pre-migration]`
known-good control, or case D's post-migration line) was a stale read. The
`--expect fail` hazard itself is measured only in PART 2, which is unchanged
and re-reproduced identically; no claim in this record moves.

## What remains unproved

- The other **5** real importers of `_rtl_compile_common.compile_and_run` still
  carry the pre-existing blind spot: `compare_kt_rtl_model.py`,
  `compare_mw_rtl_model.py`, `compare_lfo_rtl_model.py` (issue #207),
  `compare_classic_rtl_model.py`, `compare_sine_rtl_model.py` (issue #208).
  Their testbenches `$fatal` on a truncated init word or a ctrl-stream desync,
  so a healthy run needs a valid route-table / ctrl-stream fixture before its
  stdout can be measured at all — materially more work than this family
  needed, and #193's Stop/escalate condition forbids wiring the matcher in
  without that per-leaf measurement. Not started here; not claimed here.
- `tools/lp12_negative_controls.py` and `tools/lpmoog_negative_controls.py`
  call `crm.build_and_run(...)` (the legacy path) and then judge the mutant
  from `compare()` directly, never from the harness's summary — so they are
  structurally exposed to the same "a stimulus-load failure looks like a
  caught mutant" hazard measured above for NC-D, by a different route. Their
  behavior is **unchanged** by this PR (no regression), and the gap is
  recorded here rather than absorbed silently.
- Nothing here establishes claim (1), (2) or (3) for these leaves.
