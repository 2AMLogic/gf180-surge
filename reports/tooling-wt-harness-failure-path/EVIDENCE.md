# Tooling record — `compare_wt_rtl_model.py` simulator-failure reporting (issue #182)

Branch: `feature/issue-182` · Issue: #182 (tooling; noticed while implementing
#176) · Base: `9a3aefd` · Date: 2026-09-27

**Claim discipline.** This record is about a *harness reporting path* and
nothing else. It makes **no** RTL-exactness, model-vs-reference, coverage, or
musical-quality claim, and it does **not** regenerate or re-grade any committed
artifact. The SXT-026 RTL-vs-model exactness claim continues to rest solely on
`reports/sxt-026/artifacts/rtl-exactness.txt`, which was **not** re-run here
(status NOT_RUN — see below).

## The defect

`tools/compare_wt_rtl_model.py` handled a non-zero `vvp` exit with
`fails.append(...)` before `fails` was bound anywhere in `main()`, then bound
`fails` from `compare()` two lines later:

```python
    if run.returncode != 0:
        fails.append("vvp exited rc=%d stderr=%s" % ...)   # unbound
    rtl = parse_traces(args.run_dir)
    checked, fails = compare(model_trace, rtl, args.max_blocks)   # rebound
```

So a simulator-level failure raised `UnboundLocalError` instead of producing
the harness's own `verdict: FAIL`, and even with `fails` bound the message
would have been discarded by the rebinding. Severity is low — nothing can
silently PASS, because the exception exits non-zero — but the *reason* a run
did not happen never reached the JSON summary, which is exactly what this
repo's evidence rules require of a NOT_RUN/FAIL.

## The fix

`fails` is initialized before the simulator call; the simulator's message goes
to its own `sim_fails` list which is merged into `fails`, and `compare()`'s
list is merged in rather than assigned over. `sim_fails` is also reported as
its own summary key so a transcript distinguishes "the simulator failed" from
"the comparison disagreed". One consequence had to be handled explicitly: with
the message now reaching `fails`, a dead simulator would otherwise have
satisfied the `--mutant` negative control (which exits 0 when the comparison
fails), so the mutant leg now requires a comparison failure **and** a
simulator that ran.

## Verification

| Check | Status | Where |
|---|---|---|
| `python3 -m pyflakes tools/compare_wt_rtl_model.py` — no undefined names | PASS | `artifacts/failure-path-control.txt` §1 (before: `163:9: undefined name 'fails'`; after: clean) |
| Failure control: broken simulator ⇒ `verdict: FAIL` with the simulator's stderr in `first_failures` | PASS | §2, control 2 (pre-fix traceback for the same control: control 1) |
| The `--mutant` negative control is not satisfied by a dead simulator | PASS | §2, control 3 |
| Regression: the PASS path and the comparison-mismatch path are unchanged | PASS | §3 (summaries identical apart from the new empty `sim_fails` key) |
| Regression: re-run the committed-PASS SXT-026 fixture | **NOT_RUN** | §4 — the stimulus is derived from the external pinned asset tree (never committed, decision-records/0004), absent on this host |
| Automated controls in CI | PASS | `tests/test_sxt026_wt_rtl_harness.py` (4 controls; the two failure-path controls fail on the pre-fix code with `UnboundLocalError`) |

The NOT_RUN row is **not** a pass. What can be said without re-running it is
recorded in §4: pre-fix, `main()` could only reach a printed verdict when the
simulator exited 0, so every committed transcript records a run on which the
new `sim_fails` list is empty — and with `sim_fails` empty the fixed code's
verdict, counts and both exit paths are identical to the pre-fix ones. The
issue's stop/escalate condition (a committed PASS resting on a discarded
simulator failure) therefore cannot have been triggered. That is an argument
about reachable paths in the pre-fix code, not a re-execution of the fixture.

## Bounded finding recorded, not fixed

The issue proposed "absent `rtl/init.hex`" as the broken-simulator mechanism.
Under Icarus 11 that does **not** produce a non-zero `vvp` exit: `$readmemh`
reports the open failure on **stdout** and the simulation still exits 0, and
the harness discards vvp's stdout. The run still fails closed (it FAILs on
missing trace lines) but again without naming the cause — the same class of
gap as #182 by a different mechanism. Left unfixed to keep this change to the
defect #182 names; see §5 and the follow-up issue linked from PR.

## Artifacts

| File | Content |
|---|---|
| `artifacts/failure-path-control.txt` | pyflakes before/after, the five controls (broken simulator pre-fix/post-fix, `--mutant`, real-`vvp` finding, healthy-simulator regression pair), and the NOT_RUN record for the committed fixture |

The scratch run directory (`/tmp/wt182-control`: synthetic `model_trace.json`,
stub simulators, compiled `tb_wt.vvp`) is deliberately not committed; the
transcript records the commands so it can be rebuilt.
