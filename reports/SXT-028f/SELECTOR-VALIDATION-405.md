# SXT-028f reference-controls selector validation (issue #405)

Scope: `tools/reverb2_reference_controls.py --cases` handling only. No control
arithmetic, budget, pinned input, model byte or committed report changed. The
file is not in `docs/byte-frozen-sources.json` (checked before editing). No
support, fidelity, musical-quality or hardware claim moves.

## Selector refusals (execution coverage: 0 requested cases executed)

| selector | exit | status | report written |
|---|---|---|---|
| `no__such_case` | 2 | FAIL (NOT_RUN) unknown ID | no |
| `` (empty) | 2 | FAIL (NOT_RUN) empty token | no |
| `tacobell__seq-poly-8-v1,` | 2 | FAIL (NOT_RUN) empty token | no |
| `tacobell__seq-poly-8-v1,nope` (valid+unknown) | 2 | FAIL (NOT_RUN) unknown ID | no |
| duplicate ID | 2 | FAIL (NOT_RUN) duplicate | no (pytest) |

Diagnostic goes to stderr: "requested coverage did not execute; no controls
run and no report written (any existing <out> is NOT output of this
invocation)". No `status: PASS` line is printed.

## Executed runs (host: python via `uv run --no-project --with numpy`)

- Valid subset `tacobell__seq-poly-8-v1`: exit 0, 3 controls ok,
  `coverage: subset (1/6 declared cases executed)`, status PASS (agreement on
  the executed case only). Report `coverage` records declared / requested /
  executed IDs, counts, and `scope`.
- Omitted `--cases`: exit 0, `coverage: full (6/6 ...)`, status PASS (18 ok
  control lines; verdict semantics unchanged). Written to scratch only.

## Failure controls

- Legacy `cases=[]` / `status: PASS` artifact plus PASS stdout: still rejected
  by the registry adapter (`_accept_reverb2_reference`), unchanged.
- A subset PASS (stdout + report) is also rejected by the full-run adapter.
- run_case is replaced by a raising stub in the refusal test: proves no work
  runs for refused selectors.
- Real baseline/control failures still produce FAIL/nonzero (unchanged
  `all(r["ok"])` path); NOT_RUN: no deliberately broken control was injected
  in this change.

Tests: `tests/test_negative_controls_live.py -k reverb2` -> 6 passed (includes
the unchanged full registry run).
