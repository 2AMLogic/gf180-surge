# Issue #456 — decay-sweep coverage gate (note)

This note lives beside the #456 artifacts rather than in
`reports/sxt-024/EVIDENCE.md`: that record is hash-pinned by `docs/dag.json`
(node 17) and by `reports/coverage-v1/` (`coverage.json`,
`leaf-verification.json`), and this change does not alter any committed
SXT-024 verdict, so it does not re-stamp those pins. It is bookkeeping for the
gate only; it establishes no new fidelity, RTL, hardware, or quality claim.

## Per-case coverage

| Case | Coverage | Agreement |
|---|---|---|
| sweep decay −4…6, per-case coverage (#456) | **partial**: 6 of 7 cases grade the tail-level-tracking agreement | the decay −4 case is excitation-bounded — its tail falls below the −100 dBFS floor, so BOTH agreement checks are NOT_RUN there and it grades nothing |

## What the gate does

`tools/compare_reverb_model.py sweep` now declares its required case set from
the committed generator policy (`render_reverb_reference.py` default grid −4,
−2, 0, 1.879465, 3, 4.5, 6), refuses (NO_VERDICT, exit 2, no evidence
written) when a required case is missing or unusable, and never turns an
ungraded run into success: with no mandatory check gradeable anywhere it
exits NO_VERDICT, and a graded false check is FAIL. Coverage — required /
discovered / graded / unmeasurable, with per-case statuses and reasons — is
reported separately in `comparison/sweep-t60-coverage.json` (written by future
runs; the committed `sweep-t60.json` list predates the gate and is not
rewritten by it).

## Applied to the committed traces

On this host (python 3.12.3 / numpy 1.26.4, the #112 regeneration
environment) the gate reproduces every per-case value exactly
(`RETENTION.txt`) and reports coverage **partial**: six of the seven cases
grade the mandatory tail-level-tracking agreement, while the decay −4 case is
excitation-bounded — its tail falls below the −100 dBFS measurement floor, so
**both** agreement checks are NOT_RUN there and it grades nothing. Before #456
that vacuity was invisible: the old aggregate `all(...)` over only non-None
values returned success even on a fully ungraded sweep — demonstrated by the
fired controls in `NEGATIVE-CONTROLS.txt` (NC-456-C runs the pre-#456 tool
pinned to a fixed commit, see `negative_controls.py`).

The committed sweep verdict in `reports/sxt-024/EVIDENCE.md` is not
invalidated by this change; the partial coverage above is a bounded fixture
finding for the SXT-013 freeze (a decay −4 grade would need a stronger
short-decay excitation, i.e. an oracle re-render). Folding this note into
`EVIDENCE.md` is left to a change that re-derives the node 17 and coverage-v1
pins together.

## Identity validation (issue #458 review)

Discovery counts filenames, so a sidecar could masquerade under a required
name it does not belong to — one decay case renamed seven times graded as the
whole declared grid (demonstrated live in the #458 review and now by control
NC-456-G against the pinned pre-#456 tool). Each discovered case is now
validated before it is graded: the declared trace must equal the filename
stem, a required name must carry exactly the committed generator grid value
as its requested decay, the applied decay override must match the normalized
engine decaytime readback, and the applied override must equal the requested
value within the declared native readback tolerance (`1e-6`; the committed
traces' largest requested-vs-applied gap is 3.5e-07, ≈1.4 float32 ULP at
1.879). Any disagreement refuses (NO_VERDICT, exit 2) before either evidence
file is written; per-fit NOT_RUN exceptions and the legitimate
partial-coverage PASS are unchanged, and `RETENTION.txt` re-derives every
per-case value byte-identically under the validation. Controls NC-456-G
(renamed duplicates) and NC-456-H (relabelled trace/requested with the
applied/engine decay left behind) both refuse without overwriting prior
evidence; the live suite equivalents live in
`tests/test_sxt024_sweep_coverage.py`.
