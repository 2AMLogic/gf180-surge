# SXT-019 evidence record — reuse-substrate governance: provenance audit + decision-record index

Issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25) (SXT-019,
standing governance hub) · survey `docs/REUSE-AUDIT.md` · records
`decision-records/`.

This record covers **only** the bookkeeping/enforcement increment landed by
this PR. It establishes nothing about DSP, RTL, fidelity, preset support, or
sound. It does **not** ratify any decision record: 9 of the 11 records on disk
are `PROPOSED`/`ESCALATED` pending owner action, and this project still has no
distribution-license determination (`AGENTS.md`).

Tree audited: this PR's branch. Runtime: Python 3.12.3 (stdlib only), Linux.

## 0. What moved

| Acceptance item (#25) | Before | After |
|---|---|---|
| 4. "an audit pass (script or checklist in review) flags any vendored file without a provenance row; demonstrate it once on a deliberately unattributed file" | no script, no manifest — enforcement was review habit only | `tools/check_provenance.py` + `decision-records/provenance.json` + CI job `provenance-audit`; demonstrated in §3 below |
| 1–3 (per-issue adoption records, license/pin recorded in the adopting PR, GPL boundary enforced) | enforced by review only | still review-owned, now with machine checks behind them: a row is required at adoption time, must cite an existing indexed record, and must be corroborated by the file itself |
| `decision-records/README.md` index completeness | 11 records on disk, 7 rows (0004–0007 missing) | 11 rows; drift is now a CI failure (`index-missing-row`, `index-status-mismatch`, `index-date-mismatch`) |

Re-verified counts on the branch point (the curator's pass said "8 records on
disk, 0004–0007 missing"; that was stale — 0009/0010/0011 landed 2026-09-25):
`ls decision-records/*.md` → 11 records; the missing index rows were indeed
exactly 0004, 0005, 0006, 0007.

## 1. Tree audit — PASS

```
$ python3 tools/check_provenance.py
provenance audit of <worktree>
coverage: 1633 files scanned, 707 excluded by declared scope exclusions,
  11 decision records, 13 provenance rows covering 13 files, 8 exemptions
  excluded: .agents/ (41 files)
  excluded: .claude/ (91 files)
  excluded: .loom/ (575 files)
tripwire hits (declared + undeclared): foreign-license-text=2,
  foreign-source-language=1, self-declared-quotation=31,
  upstream-asset-extension=0

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
```

Coverage is reported separately from agreement: 1633 files scanned (this
branch, all new files staged), 707 **excluded** by the three declared scope
exclusions (`.loom/`, `.claude/`, `.agents/` — Loom-installed surfaces owned by
the upstream resync, recorded in the manifest as declared holes and printed on
every run).

The two declared `foreign-license-text` hits are the upstream attribution line
in `model/effects/aw-49/galactic_model.py` (row → DR-0006) and nothing else;
the single `foreign-source-language` hit is
`oracle/sxt038/lp24_ref_harness.cpp` (row → DR-0010).

## 2. First-run findings on the unmodified tree (the audit found real drift)

The first run against the pre-change tree produced **95 findings**, all real:

1. `index-missing-row` × 4 — records 0004–0007 on disk with no index row.
2. `unindexed-record-citation` × 90 — every file citing 0004/0005/0006/0007
   (model, rtl, compiler, tools, tests, reports) was citing a decision the
   index did not list.
3. `manifest-uncorroborated` × 1 — **a genuine mis-citation**:
   `model/voice/voice_model.py` attributed the 12 quoted sst-filters halfband
   coefficients to "decision-records/DR-0001", but DR-0001 is the *oracle
   automation source policy*; the record that authorizes those constants is
   [0002](../../decision-records/0002-halfband-coefficients.md). Fixed in this
   PR (the comment now names 0002, the submodule pin, and the license), and
   the audit's corroboration rule is what surfaced it.

## 3. Negative control per acceptance item 4 — demonstrated on deliberately unattributed files

Three unattributed files were injected into the real tree (a pasted GPL header
with a "transcribed from <pinned Surge commit>" table, a fake `.wt` payload,
and a copied `.cpp`), audited, then removed. The audit flagged all three
(exit 1):

```
FAIL: 5 provenance finding(s):
  [foreign-license-text] model/effects/vendored-probe/undeclared_coeffs.py
      gpl-body: … under the terms of the G⋯U G⋯l P⋯c L⋯e.
      C⋯t (C) 20⋯ Some Upstream Author…          [license body REDACTED]
  [foreign-license-text] model/effects/vendored-probe/undeclared_coeffs.py
      copyright line: … C⋯t (C) 20⋯ Some Upstream Author …
                                                  [copyright line REDACTED]
  [foreign-source-language] model/effects/vendored-probe/copied_kernel.cpp
      extension .cpp
  [self-declared-quotation] model/effects/vendored-probe/undeclared_coeffs.py
      transcribed-from: … constants transcribed from
      surge-synthesizer/surge@58914e59c6…
  [upstream-asset-extension] model/effects/vendored-probe/Bank Fake.wt
      extension .wt
```

The two license strings are redacted **because this audit forbids pasting a
foreign license body or copyright line into this repository without a
provenance row** — and `foreign-license-text` is deliberately not exemptible.
The first draft of this evidence record quoted the probe's header verbatim and
the audit failed it (2 findings on `reports/sxt-019/EVIDENCE.md`); the rule
applies to evidence prose exactly as it applies to source. The unredacted
strings are reproducible from §6 by re-running the injection.

After removal the tree returns to PASS (exit 0) and `git status` is clean of
the probe: the control files are deliberately **not committed**.

## 4. The audit's own failure detection — PASS (29/29 rules)

The false-negative failure mode (a rule that silently stops firing while CI
stays green) is itself tested:

```
$ python3 tools/check_provenance.py --negative-control
… one deliberate violation per rule, 29 rules + a clean-tree control …
PASS: all 29 rules fired on their deliberate violation, and the clean control
tree produced no findings.
```

**The audit applies to itself.** Staging the new files made the audit flag its
own source and test suite (a license body, an SPDX tag, a `0099` record
citation and a self-declared-quotation marker, all present as synthetic
control fixtures or pattern literals). Two of the three available responses
were rejected: exempting a non-exemptible rule, and special-casing the tool's
own path (a hole anyone could hide content in). Instead the fixtures and the
license-body patterns are assembled from string fragments at run time, so the
non-exemptible rules still apply to `tools/check_provenance.py` itself; only
the exemptible prose-marker rule is exempted for the three bookkeeping files
(manifest, tool, tests), each with a reason in the manifest. One detail worth
recording: a case-insensitive pattern matches its own spelled-out lowercase
prefilter, which is why the MPL prefilter is just `"mozilla"`.

Covered rules include: the four carriage tripwires; index missing/duplicate/
unknown row, status and date drift, numbering gap, unrecognized status
keyword; dangling and unindexed record citations; manifest missing/schema/
missing-field/unknown-class/stale-path/blanket-pattern/missing-record/
unindexed-record/uncorroborated; exemption missing-field/non-exemptible-rule/
stale/blanket-pattern; stale scope exclusion; and `scan-underflow` (a scan
below the manifest's declared floor of 1200 files fails instead of reporting a
clean tree). `--negative-control` also fails if any rule has **no** control,
so a rule added later cannot ship untested. CI runs the negative control
*before* the tree audit.

## 5. Test suite

```
$ python3 -m pytest -q tests/test_sxt019_provenance.py
14 passed
```

Covers: the committed tree audits clean; the CLI's JSON verdict and exit
codes; every manifest row cites an existing indexed record; the index lists
every record with matching status keyword and date; the 29-rule negative
control; every rule has a control; and synthetic-tree controls for an
unattributed GPL header, an unattributed `.wt` payload, an unattributed
`.cpp`, an unattributed self-declared quotation, a row pointing at the wrong
file, a blanket pattern, an attempt to exempt a non-exemptible rule, and a
partial scan.

Audit wall time on this tree: ~2.8 s (a naive first implementation took 47 s;
the scan now sniffs binaries before decoding and gates every regex behind a
lowercase substring prefilter — the negative control is what keeps that
optimization honest).

## 6. Reproducibility

```
python3 tools/check_provenance.py --negative-control   # 0 = every rule fires
python3 tools/check_provenance.py                      # 0 = PASS, 1 = findings
python3 tools/check_provenance.py --json               # machine-readable
python3 tools/check_provenance.py --limits             # declared limits
python3 -m pytest -q tests/test_sxt019_provenance.py
```

No engine tree, no network, no oracle host required.

## 7. What this record does NOT establish

- **Not proof that nothing was copied.** The audit enforces bookkeeping and
  detects the four carriage signals named above. Code copied with every marker
  and license header stripped, a re-typed constant table with no citation, or
  content under a declared scope exclusion (`.loom/`, `.claude/`, `.agents/`)
  is **not** detected. NOT_RUN for similarity matching against upstream trees:
  no such check exists here.
- **Not a ratification.** Records 0003–0004, 0006–0010 are PROPOSED and 0011
  is ESCALATED; the audit checks that a row cites a record, never that the
  owner agreed with it. The distribution-license determination remains open.
- **No DSP, fidelity, RTL-exactness, preset-support or sound claim** is
  touched by this work.
- The 13 provenance rows are this increment's inventory of known carriers,
  derived from the existing records and the tripwire scan. A carrier that
  predates the records and leaves no signal would be missing from it; adding
  one is an ordinary follow-up, not a contradiction of this record.
