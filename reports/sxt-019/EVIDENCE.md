# SXT-019 evidence record — reuse-substrate governance: provenance audit + decision-record index

Issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25) (SXT-019,
standing governance hub) · survey `docs/REUSE-AUDIT.md` · records
`decision-records/`.

This record covers **only** the bookkeeping/enforcement increment landed by
this PR. It establishes nothing about DSP, RTL, fidelity, preset support, or
sound. It does **not** ratify any decision record: 15 of the 18 records on disk
are `PROPOSED`/`ESCALATED`/`RECORDED` pending owner action, and this project
still has no distribution-license determination (`AGENTS.md`).

Tree audited: this PR's branch after merging `origin/main` `ce8c285` (merge
`e40669f`) plus the occurrence-scoped exemption commit that carries this
update; §1/§4/§5 were re-run on that tree. Runtime for the re-run: Python
3.14.7 (stdlib only), Darwin. The first-commit run (`d3e47ed`, §2/§3 history)
used Python 3.12.3 on Linux. The previous re-run (head `e6b5923a`, 16 records,
2000 files) is superseded by the numbers below. **§8 and §9 are later
increments** on the same tool, each audited against the `main` commit named in
its own heading; the §1/§4/§5 numbers above are not re-stated there except
where a count changed.

## 0. What moved

| Acceptance item (#25) | Before | After |
|---|---|---|
| 4. "an audit pass (script or checklist in review) flags any vendored file without a provenance row; demonstrate it once on a deliberately unattributed file" | no script, no manifest — enforcement was review habit only | `tools/check_provenance.py` + `decision-records/provenance.json` + CI job `provenance-audit`; demonstrated in §3, re-demonstrated after each later hardening increment in §8 and §9 |
| 1–3 (per-issue adoption records, license/pin recorded in the adopting PR, GPL boundary enforced) | enforced by review only | still review-owned, now with machine checks behind them: a row is required at adoption time, must cite an existing indexed record, and must be corroborated by the file itself |
| `decision-records/README.md` index completeness | 11 records on disk, 7 rows (0004–0007 missing) | 11 rows at the first commit; 18 rows / 18 records at the audited head (0012–0018 landed on `main` with their own index rows after the first commit); drift is now a CI failure (`index-missing-row`, `index-status-mismatch`, `index-date-mismatch`) |

Re-verified counts on the branch point (the curator's pass said "8 records on
disk, 0004–0007 missing"; that was stale — 0009/0010/0011 landed 2026-09-25):
`ls decision-records/*.md` → 11 records; the missing index rows were indeed
exactly 0004, 0005, 0006, 0007.

## 1. Tree audit — PASS

```
$ python3 tools/check_provenance.py
provenance audit of <worktree>
coverage: 2098 files scanned, 753 excluded by declared scope exclusions,
  18 decision records, 20 provenance rows covering 20 files, 9 exemptions
  excluded: .agents/ (42 files)
  excluded: .claude/ (94 files)
  excluded: .loom/ (617 files)
tripwire hits (declared + undeclared): foreign-license-text=4,
  foreign-source-language=2, self-declared-quotation=42,
  upstream-asset-extension=0

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
```

Exit 0; `--json` reports `"verdict": "PASS"` with 0 findings.

Coverage is reported separately from agreement: 2098 files scanned (the
committed tree, enumerated by `git ls-files`: 2851 tracked = 2098 scanned +
753 excluded), 753 **excluded** by the three declared scope exclusions
(`.loom/`, `.claude/`, `.agents/` — Loom-installed surfaces owned by the
upstream resync, recorded in the manifest as declared holes and printed on
every run).

The four declared `foreign-license-text` hits are the upstream attribution
lines in `model/effects/aw-49/galactic_model.py` (row → DR-0006) and
`model/effects/aw-4/logical4_model.py` (row → DR-0015), plus the two
`attribution-statement` rows restating the `libs/airwindows` MIT attribution
(`decision-records/0015-airwindows-logical-quoted-constants.md` and
`reports/SXT-028k/EVIDENCE.md`, both → DR-0015), and nothing else. The two
`foreign-source-language` hits are `oracle/sxt038/lp24_ref_harness.cpp`
(row → DR-0010) and `oracle/sxt022/halfband_d2_probe.cpp` (row → DR-0009).

**The one new exemption (9th) is occurrence-scoped.** Merging `main` brought
in `model/oscillators/classic/README.md` (#181), which cites the pinned Surge
commit ("read and cited, never copied") and says `tb_classic.sv` "carries a
verbatim copy" of this repository's **own** `voice_model.HalfbandD2`. That is a
self-copy, not third-party carriage: the testbench re-states the
project-authored D2 allpass arithmetic, and the DR-0002 coefficients reach it
as config words 68..79, not as literals. Without an answer the merged tree
FAILED with that one `self-declared-quotation` finding. It is answered by a
new, narrower exemption form: an exact `path` plus an `occurrences` list naming
the one sentence. Any other quotation marker in that README, including a
second "verbatim copy" in the same wording, still fails. Checked on the real
tree: appending "…is copied verbatim from the pinned upstream engine." to the
README made the audit FAIL (exit 1) on exactly that line, "outside the
occurrence(s) its exemption names". The line was then removed and was not
committed. The eight earlier exemptions are unchanged and remain whole-file.

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

## 4. The audit's own failure detection — PASS (29/29 rules + 6 scoped-exemption controls)

> Superseded in part by §8: the self-test now also runs 5 own-attribution
> `masking/*` controls, and the summary line quoted below reads
> "… all 6 occurrence-scoped exemption controls behaved, and all 5
> own-attribution masking controls behaved."

The false-negative failure mode (a rule that silently stops firing while CI
stays green) is itself tested:

```
$ python3 tools/check_provenance.py --negative-control
… one deliberate violation per rule, 29 rules + a clean-tree control,
  then 6 occurrence-scoped exemption controls …
PASS: all 29 rules fired on their deliberate violation, the clean control tree
produced no findings, and all 6 occurrence-scoped exemption controls behaved.
```

The six scoped-exemption controls are one positive control (the named own-copy
occurrence audits clean, so the exemption is not dead) and five that must still
fail: a foreign "copied verbatim" line and a foreign "transcribed from" table
in the same exempted file (`self-declared-quotation`, required to fire on that
file, not on the manifest); a named occurrence that no longer appears, and one
that contains no quotation marker (`exemption-stale`); and `occurrences` on a
glob (`exemption-bad-pattern`). A mutant that ignores the scoping (treats every
exemption as whole-file) makes `--negative-control` exit 2.

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
19 passed
```

Covers: the committed tree audits clean; the CLI's JSON verdict and exit
codes; every manifest row cites an existing indexed record; the index lists
every record with matching status keyword and date; the 29-rule negative
control; every rule has a control; and synthetic-tree controls for an
unattributed GPL header, an unattributed `.wt` payload, an unattributed
`.cpp`, an unattributed self-declared quotation, a row pointing at the wrong
file, a blanket pattern, an attempt to exempt a non-exemptible rule, and a
partial scan; plus (added in `f8715ff`) the `RECORDED` status keyword is
accepted while an unknown keyword still fails, and an `attribution-statement`
row answers only the tripwires it lists; plus (added with the #181 merge) an
occurrence-scoped exemption covers only its named occurrence, goes stale when
the occurrence leaves, cannot sit on a glob, and the committed
`model/oscillators/classic/README.md` exemption does not launder a foreign copy
appended to that README.

Audit wall time: ~2.8 s on the first-commit tree (Linux); on the audited head
the re-run measured ~1.5 s user CPU, ~1.6 s real on Darwin (a
naive first implementation took 47 s; the scan now sniffs binaries before
decoding and gates every regex behind a lowercase substring prefilter — the
negative control is what keeps that optimization honest).

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
- **Not a ratification.** Records 0003–0004, 0006–0010, 0012, 0014 and 0015
  are PROPOSED, 0011 is ESCALATED, and 0013, 0016, 0017 and 0018 are RECORDED
  with owner ratification pending; the audit checks that a row cites a record, never that the
  owner agreed with it. The distribution-license determination remains open.
- **No DSP, fidelity, RTL-exactness, preset-support or sound claim** is
  touched by this work.
- The 20 provenance rows are this increment's inventory of known carriers,
  derived from the existing records and the tripwire scan. A carrier that
  predates the records and leaves no signal would be missing from it; adding
  one is an ordinary follow-up, not a contradiction of this record.

## 8. Increment 2 (2026-09-30) — an own-attribution mask on the non-exemptible rule

Tree audited: `main` `4cf6104` plus this increment. Runtime: Python 3.12.3,
Linux (stdlib only).

**Finding.** `foreign-license-text` cannot be exempted (a foreign license body,
SPDX tag or copyright line must be answered by a provenance row), so the only
way to lose it is to make it stop firing. It did, in two layouts, both of which
audited **clean** before this increment:

| Injected shape | Before | After |
|---|---|---|
| our own copyright header, then a pasted foreign copyright line further down the file | PASS (no finding) | FAIL `foreign-license-text` |
| a foreign copyright line one line under prose naming `gf180-surge` | PASS (no finding) | FAIL `foreign-license-text` |
| our own `Apache-2.0` SPDX tag, then a pasted foreign SPDX tag | PASS (no finding) | FAIL `foreign-license-text` |
| our own copyright / SPDX header alone (positive control) | PASS | PASS (unchanged) |

Two independent causes, both in `tripwire_hits`:

1. **First-match-only.** The SPDX and copyright signals used `re.search`, so
   only a file's *first* notice was ever examined. Any own notice above a
   pasted upstream one ended the search.
2. **Proximity window.** A copyright line's holder was judged from a ±120-char
   window around the match. Any nearby mention of this project — an own header
   line, or ordinary prose containing `gf180-surge` — read as "this holder is
   us". The holder is now read from the notice's own line (`copyright_line`).

The pre-existing negative control could not catch either: its fixture file
contains *only* the foreign notice, which is the one layout both bugs leave
detectable.

**Controls (`masking/*`, in `--negative-control`, so CI runs them).** Three
must-fail controls (one per layout above) and two positive controls (our own
copyright / own SPDX alone must still audit clean — a rule that flags our own
headers would simply be switched off again). Non-vacuity was checked by
reverting both hunks in a scratch copy of the tool: the three must-fail
controls then report `did NOT fire … (found nothing)` and the self-test exits
2, while the two positive controls still pass.

```
$ python3 tools/check_provenance.py --negative-control     # exit 0
PASS: all 29 rules fired on their deliberate violation, the clean control tree
produced no findings, all 6 occurrence-scoped exemption controls behaved, and
all 5 own-attribution masking controls behaved.

$ python3 /tmp/pre_fix_check.py --negative-control          # exit 2 (both hunks reverted)
  FAIL  masking/foreign-copyright-under-our-own            … found nothing
  FAIL  masking/foreign-copyright-beside-a-project-mention … found nothing
  FAIL  masking/foreign-spdx-under-our-own                 … found nothing
  PASS  masking/our-own-copyright-alone-passes
  PASS  masking/our-own-spdx-alone-passes
```

**Re-demonstrated on the real tree (acceptance item 4).** Three unattributed
files injected into `main`'s tree — own-header-then-foreign-copyright,
own-SPDX-then-foreign-SPDX, and a "transcribed from <pinned Surge commit>"
table — then removed:

```
$ python3 tools/check_provenance.py
coverage: 2101 files scanned, … 18 decision records, 20 provenance rows …
tripwire hits: foreign-license-text=6, foreign-source-language=2,
  self-declared-quotation=44, upstream-asset-extension=0
FAIL: 3 provenance finding(s):
  [foreign-license-text]     model/pasted_upstream_helper.py   (copyright line, REDACTED)
  [foreign-license-text]     model/pasted_upstream_tag.py      (SPDX tag: GPL-3.0-or-later)
  [self-declared-quotation]  model/undeclared_quote.py         (transcribed-from)
exit 1
```

The first two would have been reported as PASS before this increment. Redaction
of the copyright line follows §3's rule. After removal the tree is PASS (exit
0) with `foreign-license-text=4`, i.e. the same four declared hits as `main`:
**no committed file changed status**, so this increment adds no new provenance
row and revises no decision record.

```
$ python3 -m pytest -q tests/test_sxt019_provenance.py
24 passed        # 19 before, +5: three masking shapes, the positive control,
                 # and a test that the masking controls are wired into the self-test
```

**What §8 does NOT establish.** It closes two specific masking paths; it is not
evidence that no other masking path exists, and every limit in §7 still stands
(a marker-free copy remains undetectable, and nothing here ratifies a decision
record or makes a distribution-license determination). Whether any file in the
repository's history ever carried such a masked notice was **NOT_RUN**: no
history scan was performed, only the current tree, which is PASS.

## 9. Increment 3 (2026-09-30) — the same masking one level in: notice, tag, phrase

Tree audited: `main` `bc931d6` plus this increment. Runtime: Python 3.14.7,
macOS (stdlib only); CI runs the same checks on Python 3.12 / ubuntu-24.04.

§8 closed two masking paths at the level of *which notice in a file* is
inspected. This increment audits one level in — *how a single notice, tag, or
phrase is read* — and finds four more layouts that audited **clean** on the
non-exemptible `foreign-license-text` rule while `--negative-control` still
reported all 29 rules firing:

| Injected shape | Before | After |
|---|---|---|
| a foreign copyright line naming this project in a parenthetical (`… <upstream holder> (adapted for gf180-surge)`) | PASS (no finding) | FAIL `foreign-license-text` |
| a foreign copyright line naming this project after a spaced hyphen (`… <upstream holder> - reworked for gf180-surge`) | PASS (no finding) | FAIL `foreign-license-text` |
| an SPDX expression whose leading operand is ours (`Apache-2.0 OR GPL-3.0-or-later`) | PASS (no finding) | FAIL `foreign-license-text` |
| a license body wrapped mid-phrase across a comment leader (`# This program is free` / `# software; …`; `* GNU GENERAL` / `* PUBLIC LICENSE`) | PASS (no finding) | FAIL `foreign-license-text` |
| four own-attribution layouts + a leaderless prose wrap (positive controls) | PASS | PASS (unchanged) |

Three independent causes, all in the signal layer:

1. **Holder read from the whole line.** §8 scoped the holder test to the
   notice's own line, but still searched that entire line for our name — so a
   pasted upstream notice suppressed itself merely by *mentioning* this
   project, which is exactly how a modified vendored file gets annotated. The
   holder is now read from the **holder field** (the name standing after the
   year, truncated at a parenthetical / bracket / dash / semicolon / URL /
   comment close), and our name must be the *first* name in that field
   (`own_copyright_holder`).
2. **SPDX tag compared as one token.** `SPDX_RE` captured only the first
   whitespace-delimited word, so every operand after the first was invisible.
   `Apache-2.0 OR <foreign>` is the standard dual-licence spelling, not an
   exotic evasion. The tag is now parsed as an expression — `id (AND|OR|WITH
   id)*` — and **every** operand is compared (`spdx_foreign_ids`).
3. **License bodies could not span a comment leader.** A pasted header is a
   comment block; `\s+` between two words does not span `"\n# "`, and the old
   multi-word prefilters (`"general public license"`, `"free software"`) did not
   survive the wrap either, so a header that broke mid-phrase carried no signal
   at all. Word gaps now accept same-line whitespace **or** a line break whose
   continuation begins with a comment leader, and each prefilter is a single
   word the regex cannot match without.

The §8 controls could not catch any of these: their fixtures pair an own notice
with a *separate* foreign one, which is the one shape all three bugs leave
detectable.

**Controls (`masking/*`, in `--negative-control`, so CI runs them).** Five new
must-fail controls (one per layout above) and five new positive controls — our
own copyright line with a parenthetical aside, the `The gf180-surge Authors`
spelling, a holder after a spaced hyphen, our own SPDX tag quoted mid-sentence,
and the declared leaderless-prose-wrap boundary. The positive half is not
optional: a rule that fires on our own header gets switched off, and the
protection goes with it.

```
$ python3 tools/check_provenance.py --negative-control     # exit 0
PASS: all 29 rules fired on their deliberate violation, the clean control tree
produced no findings, all 6 occurrence-scoped exemption controls behaved, and
all 15 own-attribution masking controls behaved.
```

**Non-vacuity — each new control fails when, and only when, its own fix is
reverted.** The three hunks were reverted independently in a scratch copy of the
tool and the five must-fail controls re-run against each:

```
== holder-field fix reverted ==
  FAIL  masking/foreign-holder-with-our-name-in-a-parenthetical  … found nothing
  FAIL  masking/foreign-holder-with-our-name-after-a-dash        … found nothing
  PASS  masking/compound-spdx-behind-our-own-operand
  PASS  masking/license-body-wrapped-across-a-comment-leader
  PASS  masking/license-title-wrapped-across-a-comment-leader
== SPDX-expression fix reverted ==
  FAIL  masking/compound-spdx-behind-our-own-operand             … found nothing
  (other four PASS)
== comment-leader gap reverted ==
  FAIL  masking/license-body-wrapped-across-a-comment-leader     … found nothing
  FAIL  masking/license-title-wrapped-across-a-comment-leader    … found nothing
  (other three PASS)
```

**Re-demonstrated on the real tree (acceptance item 4).** Three unattributed
files carrying the newly-detected shapes, injected into the tracked tree
(`git add -N` — `list_files` audits `git ls-files`, so untracked scratch is out
of scope by design), then removed:

```
$ python3 tools/check_provenance.py
coverage: 2103 files scanned, 754 excluded by declared scope exclusions,
  18 decision records, 20 provenance rows covering 20 files, 9 exemptions
tripwire hits: foreign-license-text=7, foreign-source-language=2,
  self-declared-quotation=43, upstream-asset-extension=0
FAIL: 3 provenance finding(s):
  [foreign-license-text] model/masked_a.py   (copyright line w/ parenthetical, REDACTED)
  [foreign-license-text] model/masked_b.py   (SPDX tag: GPL-3.0-or-later)
  [foreign-license-text] model/masked_c.py   (fsf-body, wrapped across '#')
exit 1
```

All three would have been reported as PASS before this increment. Redaction of
the copyright line follows §3's rule. After removal the tree is PASS (exit 0)
with `foreign-license-text=4` — the same four declared hits as `main`, so **no
committed file changed status**: this increment adds no provenance row and
revises no decision record. The `decision-records/README.md` index was
re-derived and is already complete (18 records on disk, 18 rows).

```
$ python3 -m pytest -q tests/test_sxt019_provenance.py
30 passed        # 24 before, +6: two foreign-holder shapes, the compound SPDX
                 # tag, the wrapped bodies, the own-attribution variants, the
                 # declared prose-wrap boundary, and a unit test of the SPDX
                 # expression parse
```

**What §9 does NOT establish.** It closes four more specific masking paths on
one rule. Every path was found by inspection, so this is **not** evidence that
no further path exists — only that these are now pinned by controls that fail
without their fix. Every limit in §7 stands, plus one made explicit in the
tool's `--limits` text: a **leaderless** prose wrap of a license *name* is
deliberately out of scope (it is not a comment-block paste, and the rule cannot
be exempted, so prose naming a license must not become an unanswerable
finding). Whether any file in the repository's history ever carried one of these
masked notices remains **NOT_RUN** — only the current tree was audited, and it
is PASS. Nothing here ratifies a decision record or makes a distribution-license
determination.


## 10. Increment 4 (2026-10-01) — four more families off the non-exemptible rule

Tree audited: `main` `fb377df` plus this increment. Runtime: Python 3.13,
Linux (stdlib only); CI runs the same checks on Python 3.12 / ubuntu-24.04.

The two concrete gaps the 2026-09-25 Curator pass named are closed on `main` and
were **re-derived here, not trusted**: `decision-records/*.md` → 18 records, and
`decision-records/README.md` carries 18 index rows with an empty symmetric
difference (diffed programmatically); `docs/REUSE-AUDIT.md` § "Adoption
mechanics" step 5 already names the tool, the manifest, the CI job and
`--limits`. Neither file is touched by this increment.

§8 closed two masking paths at the level of *which notice is inspected*; §9
closed four at the level of *how one notice, tag or phrase is read*. This
increment audits the same rule once more and finds **eight** further layouts
that audited **clean** on the non-exemptible `foreign-license-text` rule while
`--negative-control` reported all 29 rules firing and all 15 `masking/*`
controls behaving:

| Injected shape | Before | After |
|---|---|---|
| foreign holder behind a **bracketed** mention of this project (year, then `[gf180-surge] <upstream holder>`) | PASS (no finding) | FAIL `foreign-license-text` |
| the same behind a **parenthesised** mention (`(gf180-surge port) <upstream holder>`) | PASS (no finding) | FAIL `foreign-license-text` |
| the same after a **semicolon** (`; gf180-surge adaptation of <upstream holder>'s filter`) | PASS (no finding) | FAIL `foreign-license-text` |
| the same after an **em dash** (`— gf180-surge vendoring of <upstream holder>`) | PASS (no finding) | FAIL `foreign-license-text` |
| SPDX tag with a foreign operand after a **comma** (`Apache-2.0, GPL-3.0-or-later`) | PASS (no finding) | FAIL `foreign-license-text` |
| SPDX tag naming a foreign licence inside a **parenthetical** (`Apache-2.0 (upstream GPL-3.0-or-later)`) | PASS (no finding) | FAIL `foreign-license-text` |
| a notice carrying a holder but **no year** | PASS (no finding) | FAIL `foreign-license-text` |
| a holder list **wrapped** onto a continuation line carrying no keyword | PASS (no finding) | FAIL `foreign-license-text` |
| 7 own-attribution / prose layouts (positive controls) | PASS | PASS (unchanged) |

Four independent causes, all in the signal layer:

1. **The holder test fell back to the WHOLE LINE.** §9 read the holder from the
   holder *field* — but when that field opened with a delimiter (a bracket, a
   parenthesis, a semicolon, a dash) it held no name, and the code then searched
   the entire line, reinstating precisely the whole-line masking §8 and §9 had
   removed. The field is now walked **segment by segment** (`_holder_segments`),
   and — the load-bearing half — our name standing first is no longer
   sufficient: the segment must name **us and nobody else**. "Somebody else" is a
   capitalised token that is not our own name and not a collective/corporate/
   boilerplate suffix our own notice legitimately carries.
2. **The SPDX expression walk stopped at the first non-operator token.** That
   stop is deliberate (so our own tag quoted inside a sentence does not read the
   following prose as operands) — but it also discarded everything past it, so a
   comma list, a slash list and a parenthetical each hid a foreign operand in
   plain sight. `Apache-2.0, GPL-3.0-or-later` is a spelling a human writes, not
   an evasion. The remainder of the tag is now scanned for a licence id **by
   shape** (`FOREIGN_LICENSE_ID_RE`), which prose cannot satisfy.
3. **A yearless notice carried no signal at all.** `COPYRIGHT_RE` requires a
   four-digit year, so a pasted notice naming only a holder was invisible.
   `YEARLESS_COPYRIGHT_RE` now reads the keyword (or `©`) running straight into a
   capitalised holder name.
4. **A holder list could wrap.** The second holder on the next line carries no
   keyword, so nothing raised the signal; `_wrapped_holder_match` now reads a
   narrow continuation shape (a conjunction, then a capitalised name) under a
   notice already judged ours.

The §8/§9 controls could not catch any of these: their fixtures pair an own
notice with a *separate* foreign one, or put the mention inside a holder field
that already contains a name — the shapes all four bugs leave detectable.

**Controls (`masking/*`, inside `--negative-control`, so CI runs them).** Eight
new must-fail controls (one per layout above) and seven new positive controls:
our own notice trailed by `All Rights Reserved.`, trailed by a sentence pointing
at `LICENSE`, after a spaced hyphen with a capitalised parenthetical aside,
followed by an ordinary capitalised comment sentence, quoted mid-sentence inside
prose, plus this repository's `(a) … (b) … (c)` leg markers and prose *about*
copyright. The positive half is not optional and not cosmetic: this rule cannot
be exempted, so a false positive on our own attribution is an **unanswerable**
finding, and the only way to answer it is to switch the rule off.

```
$ python3 tools/check_provenance.py --negative-control     # exit 0
PASS: all 29 rules fired on their deliberate violation, the clean control tree
produced no findings, all 6 occurrence-scoped exemption controls behaved, and
all 30 own-attribution masking controls behaved.
```

**Non-vacuity — each control fails when, and only when, its own fix is
reverted.** The four fixes (five hunks: the segment walk and the only-holder
condition are separable) were reverted independently in a scratch copy of the
tool and the whole self-test re-run against each:

```
baseline (all hunks present):              exit 0, no failing control

revert A-i  segment walk  -> exit 2
    FAIL  masking/our-own-dash-holder-with-an-aside-passes
revert A-ii only-holder condition -> exit 2
    FAIL  masking/foreign-holder-behind-a-bracketed-project-name
    FAIL  masking/foreign-holder-behind-a-parenthesised-project-name
    FAIL  masking/foreign-holder-after-a-semicolon-project-name
    FAIL  masking/foreign-holder-after-an-em-dash-project-name
revert B    SPDX remainder scan -> exit 2
    FAIL  masking/spdx-foreign-operand-after-a-comma
    FAIL  masking/spdx-foreign-operand-in-a-parenthetical
revert C    yearless notice signal -> exit 2
    FAIL  masking/yearless-foreign-copyright-notice
revert D    wrapped holder-list continuation -> exit 2
    FAIL  masking/foreign-holder-on-a-wrapped-continuation-line
```

No revert failed a control belonging to another hunk, and reverting the segment
walk fails only a **positive** control — the segment walk exists to keep our own
notice from becoming a finding, not to catch anything.

**Re-demonstrated on the real tree (acceptance item 4, verbatim).** Four
deliberately unattributed files, one per new family, injected into the *tracked*
tree (`git add -N` — `list_files` audits `git ls-files`, so untracked scratch is
out of scope by design), then removed:

```
$ python3 tools/check_provenance.py
coverage: 2104 files scanned, 754 excluded by declared scope exclusions,
  18 decision records, 20 provenance rows covering 20 files, 9 exemptions
tripwire hits: foreign-license-text=8, foreign-source-language=2,
  self-declared-quotation=43, upstream-asset-extension=0
FAIL: 4 provenance finding(s):
  [foreign-license-text] model/masked_d.py  (copyright line, bracketed mention, REDACTED)
  [foreign-license-text] model/masked_e.py  (SPDX tag: GPL-3.0-or-later, after a comma)
  [foreign-license-text] model/masked_f.py  (copyright line, no year, REDACTED)
  [foreign-license-text] model/masked_g.py  (copyright line, wrapped holder list, REDACTED)
exit 1
```

The pre-increment tool was then run against **the same tree, with the same four
files still in it** — the direct before/after, not an inference:

```
$ git show HEAD:tools/check_provenance.py > /tmp/head_check_provenance.py
$ python3 /tmp/head_check_provenance.py --root .
tripwire hits: foreign-license-text=4, …
PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
exit 0
```

A tree carrying four unattributed files with foreign copyright/SPDX notices
audited **PASS** before this increment. Redaction of the copyright lines follows
§3's rule. After removal the tree is PASS (exit 0) with
`foreign-license-text=4` — the same four declared hits as `main`, so **no
committed file changed status**: this increment adds no provenance row and
revises no decision record.

```
$ python3 -m pytest -q tests/test_sxt019_provenance.py
37 passed        # 30 before, +7: the four delimiter-led holder layouts, the two
                 # SPDX-remainder shapes, the yearless and wrapped notices, the
                 # seven own-attribution/prose positive cases, a unit test of the
                 # remainder scan, a unit test of the holder test itself, and
                 # (§11) the wrapped-holder finding's locator
```

**What §10 does NOT establish.** It closes eight more specific masking paths on
one rule. Every one was found by **inspection**, so this is **not** evidence that
no further path exists — only that these are now pinned by controls that fail
without their fix. Every limit in §7 stands, plus two declared boundaries made
explicit in `--limits` and pinned by positive controls:

- a yearless notice written with a **bare `(c)`** is deliberately not matched —
  this repository marks enumerated legs `(a) … (b) … (c)` throughout its decision
  records and evidence reports, and matching those would make ordinary lettered
  lists unanswerable findings
  (`masking/lettered-list-markers-stay-out-of-scope`);
- the holder test reads **one segment** of the notice line, so a foreign name in
  a later segment of an otherwise-own notice *line* is not read as a second
  holder. A holder list wrapped onto the next **line** is matched
  (`masking/our-own-dash-holder-with-an-aside-passes`,
  `masking/foreign-holder-on-a-wrapped-continuation-line`).
  **Superseded by §12** (2026-10-01): this boundary is now closed for a two-word
  name shape before the segment's first sentence break; §12 states the two
  narrower limits that replace it.

No Surge- or GPL-derived content was copied into this repository by this
increment: every fixture is repo-invented synthetic text assembled at run time
(`Some Upstream Author`, `Chris Johnson / Airwindows` as a *name string* only),
and no file was adopted, so there is no new provenance row to record and no
licence decision to make. Whether any file in this repository's history ever
carried one of these masked notices remains **NOT_RUN** — only the current tree
was audited, and it is PASS. Nothing here ratifies a decision record or makes a
distribution-license determination.

## 11. Review fix — the wrapped-holder finding's locator was wrong

Review of §10 found that the wrapped-holder path, while it *fired* correctly,
reported a snippet quoting the **wrong bytes**. `_wrapped_holder_match` returned
a `re.Match` computed against `line` — a *slice* of the file text — so its
`.start()`/`.end()` were **line-relative**, while the caller's
`_snippet(text, match)` indexes the **full text**. On any wrapped-holder notice
more than a few lines into a file, the finding quoted unrelated code:

```
$ # 10 filler lines, then the wrapped-holder fixture
$ text[match.start():match.end()]
'1\nx ='                                           # not the holder name
$ _snippet(text, match)
'x = 1 x = 1 x = 1 x = 1 x = 1 x = 1 x = 1 x = 1 x'   # names nothing
```

This is a defect in the **evidence**, not merely in presentation. `Finding`
carries no line number, so `detail`'s snippet is the only locator a human has;
and `foreign-license-text` **cannot be exempted**, so the only way to answer one
of its findings is to go read the cited notice and add a provenance row. A
finding citing `x = 1 x = 1 …` is unanswerable — the exact failure mode §10
argues against.

**Fix.** `_wrapped_holder_match` now searches `text` directly with **absolute**
offsets, bounded to the continuation line (`HOLDER_WORD_RE.search(text, start +
continuation.end(), line_end)`). The snippet is now invariant to the notice's
depth in the file:

```
pad= 0 lines  offsets= 36, 41   [our own notice, then '# and <upstream holder>' — REDACTED]
pad=10 lines  offsets= 96,101   [identical snippet]
pad=30 lines  offsets=216,221   [identical snippet]
```

The snippet is redacted per §3's rule, and for the same reason §3 records: the
first draft of this section pasted it verbatim and **the audit failed this file**
(1 finding, `foreign-license-text` on `reports/sxt-019/EVIDENCE.md`) — a live
demonstration that the fixed path reports a real, locatable notice, since the
tool flagged the fixed snippet in evidence prose having been unable to flag the
broken one. The unredacted snippet is reproducible by re-running the unit test.

**The control could not have caught this, and now can.** Two gaps had to be
closed together, because either alone leaves the control vacuous:

1. `_run_case_controls` asserted only `f.rule` and `f.path`, never `f.detail`, so
   the control passed on a finding whose evidence pointed elsewhere. Cases may
   now carry an optional sixth element — a substring the firing finding's own
   `detail` must contain — and
   `masking/foreign-holder-on-a-wrapped-continuation-line` requires
   `'Chris Johnson / Airwindows'`.
2. The control's fixture was written at the **top** of the file, where
   line-relative and absolute offsets coincide — so even a `detail` assertion
   would have passed with the bug present. The fixture is now written **below a
   filler pad**, which is what makes the offsets diverge.

**Non-vacuity — the control demonstrably fails the check it targets.** The
absolute-offset fix was reverted in a scratch copy of the tool (fixture pad and
`detail` assertion left in place) and the whole self-test re-run:

```
baseline (fix present):   exit 0, no failing control
revert E  absolute offsets -> exit 2
    FAIL  masking/foreign-holder-on-a-wrapped-continuation-line
          … foreign-license-text fired on model/pasted_below_our_header.py but no
          finding quoted 'Chris Johnson / Airwindows' (details: '… copyright
          line: ROW_0 = [0, 0, 0] ROW_1 = [1, 1, 1] ROW_2 = [2, 2 — add a row …')
```

The reverted run's own transcript exhibits the garbage snippet, so the control
now fails *for the reason it exists*. A unit test
(`test_wrapped_holder_finding_locates_the_offending_holder`) pins the same
property directly at pads of 0 / 1 / 10 / 40 lines, independently of the audit
path.

Also corrected in this pass: the §10 `--negative-control` transcript read "all
29 own-attribution masking controls behaved" where the tool prints **30**
(15 baseline + 8 negative + 7 positive), and the §10 `pytest` count moved 36 →
37. Coverage and committed tripwire counts are unchanged — 2100 files scanned,
`foreign-license-text=4`, the same four declared hits as `main`, so **no
committed file changed status** and no provenance row or decision record is
added or revised.

**What §11 does NOT establish.** It fixes the locator for **one** finding family
and pins it with a control that fails without the fix. It is not a review of
every other finding's `detail` for offset correctness: the other five copyright
families return a match produced by `COPYRIGHT_RE`/`YEARLESS_COPYRIGHT_RE`
against the full text, so their offsets are absolute by construction, but that is
an argument from construction, not a control — only the wrapped family is
pinned by one. Every limit in §7 and §10 stands unchanged.

## 12. Increment 5 (2026-10-01) — the holder list continues past the delimiter

§10 closed the case where a foreign holder stands *behind* a bracketed,
parenthesised, semicolon- or dash-led mention of this project, and declared the
mirror case open: the holder test judged the **first** segment of the notice line
that held a name and returned, so anything past **that** segment's closing
delimiter was never read. That is the same
stop-as-soon-as-our-own-name-is-recognised shape as every earlier increment, one
segment to the right — and it is exactly how a part-vendored file gets
attributed in practice ("ours, with upstream credited in a parenthetical").

Four layouts audited **PASS** on `main` (`8dee975`) while `--negative-control`
reported all 29 rules firing and all 30 `masking/*` controls behaving. The notice
lines are redacted per §3's rule; `<ours>` is this project's own holder string
and `<upstream>` a synthetic upstream name:

| Injected notice line (redacted) | Before | After |
|---|---|---|
| year, then `<ours>; <upstream>` (semicolon) | PASS | FAIL `foreign-license-text` |
| year, then `<ours> (from <upstream>)` (parenthetical) | PASS | FAIL |
| year, then `<ours> — <upstream>` (em dash) | PASS | FAIL |
| year, then `<ours> - <upstream>` (spaced hyphen) | PASS | FAIL |
| 13 own-attribution / prose layouts (positive controls) | PASS | PASS (unchanged) |

**Fix.** `own_copyright_holder` keeps the segment walk, but once a segment is
judged ours it now also requires every **later** segment of the line to name no
second holder (`_second_holder_name`). Two bounds keep that from flagging our own
notices, which would be unanswerable on a rule that cannot be exempted:

1. a later segment is read as naming a holder only on a **two-word name shape** —
   two consecutive capitalised, non-neutral tokens — because an own aside carries
   at most one capitalised token in practice (`(SXT-019 governance)`,
   `(All Rights Reserved)`, `(see NOTICE)`) while a holder name is two or more;
2. only **before the segment's first sentence break**, because text after a full
   stop is prose, not a continuing holder list — our own notice quoted inside a
   sentence is followed by exactly that.

Both bounds are **declared limits, not closures**, and each is pinned by a
positive control: a single-token name in a later segment
(`masking/single-name-aside-stays-out-of-scope`) and a name written after a full
stop (`masking/prose-after-a-sentence-break-stays-out-of-scope`) are **not**
read as holders.

**Controls (`masking/*`, inside `--negative-control`, so CI runs them).** Four
negative, two positive; the four negative ones each require the firing finding's
own `detail` to quote the second holder, per §11's locator rule.

```
$ python3 tools/check_provenance.py --negative-control
PASS: all 29 rules fired on their deliberate violation, the clean control tree
produced no findings, all 6 occurrence-scoped exemption controls behaved, and
all 36 own-attribution masking controls behaved.                       # exit 0
```

**Non-vacuity — the controls fail when, and only when, this fix is reverted.**
The one-line later-segment check was reverted in a scratch copy of the tool
(`return not any(_second_holder_name(…))` -> `return True`) and the whole
self-test re-run:

```
baseline (fix present):                     exit 0, no failing control
revert later-segment check               -> exit 2
    FAIL  masking/second-holder-after-a-semicolon
    FAIL  masking/second-holder-in-a-parenthetical
    FAIL  masking/second-holder-after-an-em-dash
    FAIL  masking/second-holder-after-a-spaced-hyphen
```

No other control changed state, so the four new controls fail *for the reason
they exist* and nothing else depends on the hunk.

**Negative control demonstrated on the real tree (acceptance item 4, verbatim).**
Four deliberately unattributed files, one per layout, injected into the
**tracked** tree (`git add -N` — `list_files` audits `git ls-files`, so untracked
scratch is out of scope by design), then **removed**:

```
$ python3 tools/check_provenance.py
tripwire hits: foreign-license-text=8, …
FAIL: 4 provenance finding(s):
  [foreign-license-text] model/masked_h.py   (semicolon, REDACTED)
  [foreign-license-text] model/masked_i.py   (parenthetical, REDACTED)
  [foreign-license-text] model/masked_j.py   (em dash, REDACTED)
  [foreign-license-text] model/masked_k.py   (spaced hyphen, REDACTED)
exit 1
```

Then the **pre-change** tool against **the same tree with the same four files
still in it** — the direct before/after, not an inference:

```
$ git show HEAD:tools/check_provenance.py > /tmp/head_cp.py
$ python3 /tmp/head_cp.py --root .
tripwire hits: foreign-license-text=4, …
PASS … exit 0
```

A tree carrying four unattributed files, each with an upstream holder on its
copyright line, audited **PASS** before this increment. After removal the tree is
PASS (exit 0) with `foreign-license-text=4` — the same four declared hits as
`main`, so **no committed file changed status**: this increment adds no
provenance row and revises no decision record.

```
$ python3 -m pytest -q tests/test_sxt019_provenance.py
41 passed        # 37 before, +4: the four same-line holder-list layouts, the
                 # finding's locator, the two declared bounds, and a unit test of
                 # the holder test reading the whole holder side
```

**What §12 does NOT establish.** It closes one more masking family on one rule,
found by **inspection** — so four more closed is **not** evidence that no further
path exists, only that these four are pinned by controls that fail without their
fix. Every limit in §7 stands. The bare-`(c)` yearless boundary from §10 stands
unchanged. The two new bounds above are open by declaration: a **single-token**
second holder (`(portions Airwindows)`) and a holder written **after a sentence
break** are not detected. Whether any file in this repository's history ever
carried one of these notices remains **NOT_RUN** — only the current tree was
audited, and it is PASS. No Surge- or GPL-derived content was copied by this
increment: every fixture is repo-invented synthetic text assembled at run time,
with `Some Upstream Author` / `Chris Johnson` appearing as *name strings* only.
Nothing here ratifies a decision record or makes a distribution-license
determination.

## 13. Increment 6 (2026-10-01) — the mask was below the signal layer

Increments 2–5 (§8–§12) all hardened the **signal** layer: regexes, holder
parsing, SPDX operands, comment-leader wraps. Every one of them silently
assumed the file had already become text. It had not always.

`Tree.text()` classified a file as binary when **any NUL byte** appeared in its
first 8192 bytes, and `tripwire_hits()` returns immediately for such a file:

```python
text = tree.text(rel)
if text is None:
    return hits          # extension tripwires only — no content rule runs
```

So a file the sniff refused to decode was scanned by **no content rule at
all** — not `foreign-license-text` (non-exemptible), not the SPDX tag rule,
not the copyright-notice rule, not `self-declared-quotation`. And `.py` / `.sv`
are deliberately **not** in `FOREIGN_SOURCE_EXTS` (this repository authors
them), so no extension tripwire covered the gap either.

### Demonstrated on the real tree, before the fix

Three unattributed carriers, each with a complete foreign copyright line and
GPL body — one `.py` saved as UTF-16 (BOM), one `.sv` as BOM-less UTF-16-LE,
one plain-ASCII `.py` with a **single stray NUL** in a modeline:

```
$ python3 tools/check_provenance.py
tripwire hits: foreign-license-text=4, …          # unchanged from the clean tree
PASS … exit 0
```

**PASS, exit 0, counts unchanged.** None of these needs an exotic tool:
"Unicode" is a standard editor save, and one NUL byte is a one-character edit.

### After the fix — same three files

```
$ python3 tools/check_provenance.py
coverage: 2106 files scanned, …
  not content-scanned (undecodable payload): 335 files — extension tripwires only
tripwire hits: foreign-license-text=10, …
FAIL: 6 provenance finding(s):
  [foreign-license-text] model/masked_nul.py        (copyright line + gpl-body)
  [foreign-license-text] model/masked_utf16.py      (copyright line + gpl-body)
  [foreign-license-text] model/masked_utf16le.sv    (copyright line + gpl-body)
exit 1
```

Files removed afterwards; the tree is PASS (exit 0) at
`foreign-license-text=4` — the same four declared hits as `main`, so **no
committed file changed status**.

### What changed

`sniff_encoding()` resolves an encoding before anything is called binary: BOM-led
UTF-8/16/32; BOM-less UTF-16/32 admitted on a "decodes to mostly ASCII" test;
narrow text carrying sparse NULs (≤1%) admitted with the NULs dropped; anything
else still refused. Ten `.bin` files in `compiler/golden/` and `reports/` — own
compiled images with a short binary header over a JSON body — are now
content-scanned as a side effect (335 unscanned, was 345); they produce no
findings.

### Coverage is now disclosed, not silent

335 in-scope files reach the extension tripwires and nothing else, and **none**
of them is covered by an extension rule. That number was previously invisible: a
PASS did not say how much of the tree its content rules had actually read. Every
run now prints it, and `files_not_content_scanned` is in `--json`.

### Controls (non-vacuity checked both directions)

Four must-fail controls — `masking/utf16-bom-encoded-license-body`,
`…/utf16-le-bomless-…`, `…/utf16-be-bomless-…`,
`masking/stray-nul-byte-above-a-license-body` — each with a required locator in
the finding's own evidence. Reverting the decode fix alone makes **all four**
report `FAIL` and the self-test exit 2.

One positive control, `masking/notice-sealed-in-an-opaque-payload-stays-out-of-scope`,
guards the opposite failure: loosening the sniff into "decode everything" would
turn 264 renders and 8 tensors into garbage findings on a rule nobody can
exempt. Its payload embeds a real ASCII copyright notice inside binary data, so
it is **not vacuous** — it passes under the strict sniff and **fails** when the
sniff is over-loosened. (A first attempt using random bytes passed in both
directions and was replaced.)

```
$ python3 tools/check_provenance.py --negative-control
PASS: all 29 rules fired …, all 41 own-attribution masking controls behaved.
$ python3 -m pytest -q tests/test_sxt019_provenance.py
45 passed        # 41 before, +4
```

### What §13 does NOT establish

This closes one masking **layer**, found by inspection — so it is **not**
evidence that no further path exists, only that these four are pinned by
controls that fail without their fix. The lesson is the opposite of
reassuring: five consecutive increments audited the signal layer while the
layer beneath it was open, so "the layers already audited" does not bound
where the next mask lives.

Two residuals are open **by declaration**, not closed:

- a notice sealed inside an **opaque payload** is out of reach (335 files
  today, disclosed every run);
- the wide-encoding admission test is "mostly ASCII", so a UTF-16 file written
  wholly in a non-Latin script is refused. License notices are ASCII English;
  admitting everything would make the non-exemptible rule unanswerable.

Every limit in §7 stands, as do the declared bounds in §10 and §12. Whether any
file in this repository's history ever carried a wide-encoded or NUL-scuffed
notice is **NOT_RUN** — only the current tree was audited, and it is PASS. No
Surge- or GPL-derived content was copied by this increment: every fixture is
repo-invented synthetic text assembled at run time. Nothing here ratifies a
decision record or makes a distribution-license determination.

## 14. Increment 8 (2026-10-01) — the payload the previous increment declared out of reach

Base: `main` `78bbf38` (merge of #278). Runtime: Python 3.12.3, Linux.

Increment 6 (§13) made the decode layer honest about **encodings** and then
*declared* what was left: "a notice sealed inside an opaque payload is out of
reach", pinned by a positive control
(`masking/notice-sealed-in-an-opaque-payload-stays-out-of-scope`) and disclosed
as `files_not_content_scanned` — **335 files, 339 MiB** on this tree. That
declaration was wrong in two directions at once, and both were reachable without
any exotic tool:

- a **wrapper** is not opaque content, it is text one `read()` away. `.gz` is
  deliberately absent from `UPSTREAM_ASSET_EXTS` (this repository gzips its own
  evidence traces) and `_extension_suffix` strips it, so `pasted_helper.py.gz`
  matched no extension tripwire either; a zip or tar renamed `.dat` evades the
  archive extensions outright;
- an **embedded notice** is ordinary ASCII sitting inside binary data. A WAV
  `LIST/INFO` `ICOP` chunk is precisely where an upstream sample pack or an
  exported render states its holder.

### Demonstrated on the real tree, before the fix

Six deliberately unattributed files, each carrying a complete foreign copyright
line and GPL body (one also a `GPL-3.0-or-later` SPDX tag), injected into the
**tracked** tree (`git add -N`; `list_files` audits `git ls-files`, so untracked
scratch is out of scope by design) and run against the **pre-change** tool:

```
$ git show HEAD:tools/check_provenance.py > /tmp/head_check_provenance.py
$ python3 /tmp/head_check_provenance.py --root .
tripwire hits: foreign-license-text=4, …          # unchanged from the clean tree
PASS … exit 0
```

| injected file | carriage | pre-change |
|---|---|---|
| `model/…/masked_trace.json.gz` (gzipped JSON trace) | GPL body + foreign SPDX tag + copyright line | PASS |
| `compiler/golden/masked_bundle.dat` (zip renamed) | GPL body in member `Reverb1.h` | PASS |
| `compiler/golden/masked_sources.dat` (tar.gz renamed) | GPL body in member `vendor/filter.cpp` | PASS |
| `compiler/golden/masked_zip_in_gz.dat` (zip inside gzip) | GPL body, two wrappers deep | PASS |
| `fixtures/audio/masked_notice.wav` (real PCM WAV) | `ICOP` copyright chunk | PASS |
| `reports/sxt-019/masked_ref.f32` (float32 dump) | GPL body spliced mid-payload | PASS |

**PASS, exit 0, tripwire counts unchanged.** The only visible trace was
`not content-scanned` rising 335 → 341, and no gate reads that number.

### After the fix — same six files, same tree

```
$ python3 tools/check_provenance.py
  not content-scanned (no text in the payload at all): 6 files — extension tripwires only
  unwrapped by magic (compressed stream / archive): 23 files — members content-scanned
  scanned as extracted ASCII strings only: 312 files — a non-ASCII notice inside one would be missed
tripwire hits: foreign-license-text=16, …
FAIL: 12 provenance finding(s)   # every injected file, 1-3 findings each
exit 1
```

Files removed afterwards; the tree is **PASS (exit 0)** at
`foreign-license-text=4`, `self-declared-quotation=43` — the same counts as
`main`, so **no committed file changed status**.

### What changed

`Tree._read()` now answers a refused payload in two steps instead of giving up,
**without loosening the sniff** (decoding a render as prose is the other failure
direction, and §13's positive control still guards it):

1. **unwrap by magic, not by name** — gzip / bzip2 / xz streams, zip and tar
   archives, recursively (4 deep, so a `.tar.gz`, a zip inside a gzip and a
   gzipped member inside a zip all resolve), bounded by a 256 MiB inflation
   budget; each member is then decoded or harvested in its own right;
2. **harvest the payload's printable-ASCII runs** that carry a word
   (`[A-Za-z]{3,}`), joined with newlines, and run the ordinary content rules
   over that. Dropping a *wordless* run can only bring two surviving runs
   closer together, so it cannot break a phrase the rules would otherwise have
   matched. The UTF-8 © is normalised to `(c)` first, because it would
   otherwise end the run and take the copyright keyword with it.

### Coverage is reported per scan mode, not as one number

A strings-only read is weaker than a decode and now says so. On the clean tree:
335 payload files resolve to **19 unwrapped** (18 `.json.gz` traces + 1 `.npz`),
**310 scanned as extracted strings**, **6 with no ASCII run at all**; zero
truncated scans. `files_unwrapped_from_wrappers`,
`files_scanned_as_extracted_strings` and `payload_scans_truncated` are in
`--json`, and a truncated scan is printed per path — a scan that could not
finish must never look like one that passed.

### False positives were measured before this was written, not assumed

`foreign-license-text` **cannot be exempted**, so a false positive on one of
this repository's own 264 renders, 22 float dumps, 8 tensors or 18 gzipped
traces would be unanswerable — the rule would be switched off rather than
answered. All four content signals were run over all 335 payloads (339 MiB,
plus 145 MiB of gzip inflation) **before** the change was committed: **zero
hits**, with and without the word filter. Cost of the new layer: 3.9 s → 8.3 s
wall, 400 MB → 570 MB peak RSS (one audit of a 533 MiB tree).

### Controls (non-vacuity checked per hunk)

17 `payload/*` controls, 11 of which must fire with a required locator in the
finding's own evidence, 6 of which must stay clean. Each hunk was reverted
independently in a scratch copy and the whole self-test re-run:

```
baseline (all hunks present)        -> exit 0, no failing control
revert the unwrap step              -> exit 2, FAIL the 6 wrapper controls (gzip/xz/bzip2/zip/tar.gz/npz)
revert the string harvest           -> exit 2, FAIL wav-copyright-chunk, float-dump, opaque-payload, copyright-sign
revert the stream recursion         -> exit 2, FAIL payload/zip-inside-a-gzip-stream
revert the member recursion         -> exit 2, FAIL payload/gzipped-member-inside-a-zip
revert the © normalisation          -> exit 2, FAIL payload/copyright-sign-notice-in-a-payload
revert the word filter              -> exit 0 (precision/cost only — pinned by the real tree, not by a control)
```

`masking/notice-sealed-in-an-opaque-payload-stays-out-of-scope` is **inverted**
by this increment: the same fixture bytes are now
`payload/notice-embedded-in-an-opaque-payload` and must FIRE. The 6 positive
controls (a real PCM render, a float dump, an `.npy`-shaped tensor, an own
gzipped JSON trace, a wide-encoded notice inside a payload) replace it as the
guard on the unanswerable direction.

```
$ python3 tools/check_provenance.py --negative-control
PASS: all 31 rules fired …, all 40 own-attribution masking controls behaved,
all 11 discovery-layer controls behaved, and all 17 payload-layer controls behaved.
$ python3 -m pytest -q tests/test_sxt019_provenance.py
64 passed        # 57 before, +8 new, -1 inverted (the sealed-payload test)
```

### What §14 does NOT establish

- Found by **inspection**, like every increment before it: closing this layer is
  not evidence that no further path exists, only that these are pinned by
  controls that fail without their fix. The lesson of §13 is now sharper — the
  layer that hid a mask was the one the previous increment had **declared** out
  of reach, so a declared limit is not evidence the limit was necessary.
- Three residuals stay **declared, not closed**, each pinned by a positive
  control: a notice written in a WIDE encoding *inside* a binary payload (the
  harvest reads ASCII; only the UTF-8 © spelling is normalised, because the
  Latin-1 byte occurs constantly in PCM data); a wrapper whose members carry no
  marker at all (covered only by the extension tripwires — unwrapping reads
  member CONTENT, member NAMES are not tripwired); and an inflation that hits
  the 256 MiB / 4-deep budget, which is disclosed per path rather than silently
  truncated.
- A PASS remains **bookkeeping and carriage-signal coverage only** (§7): a
  marker-free copy and a re-typed constant table with no citation are still
  undetectable, as is anything under the declared scope exclusions (`.loom/`,
  `.claude/`, `.agents/` — 758 files).
- It ratifies nothing: 18 records on disk, most still
  PROPOSED / RECORDED / ESCALATED, and this project has made **no
  distribution-license determination**.
- Whether any file in this repository's **history** ever carried a wrapped or
  embedded notice is **NOT_RUN** — only the current tree was audited.
- No Surge-, GPL- or otherwise third-party-derived content was copied into this
  repository by this increment. Every fixture is repo-invented synthetic data
  built at run time (PCM from an LCG, float dumps, archives assembled in
  memory); `Some Upstream Author` appears only as a name string inside synthetic
  notices.

## 15. Increment 9 (2026-10-01) — the names inside the wrapper the last increment opened

Base: `main` `cd2f169` (merge of #282, which landed increment 8). Runtime:
Python 3.12.3, Linux. Status: **PASS** on this branch; it ratifies nothing and
establishes nothing about DSP, RTL, fidelity or sound.

Increment 8 (§14) unwrapped wrappers by magic and content-scanned their
members, then *declared* the remainder: "a wrapper whose members carry no
marker at all is covered only by the extension tripwires — unwrapping reads
member CONTENT, and member NAMES are not tripwired". That declaration was
wrong in the same way §14's was wrong about §13's: the extension tripwires
judge the **outer** name, which a `.dat` rename evades outright, so a wrapper
of marker-free upstream content was covered by **nothing at all**. And
marker-free is the normal case, not the exotic one — a `.wt` wavetable payload
states no copyright, and a source file with its header stripped states nothing
either.

### Demonstrated on the real tree, before the fix

Five deliberately unattributed wrappers, each carrying **no license text, no
copyright line and no SPDX tag anywhere in it** — the member NAME is the only
signal in the file — injected into the **tracked** tree (`git add -N`;
`list_files` audits `git ls-files`, so untracked scratch is out of scope by
design) and run against the **pre-change** tool:

```
$ git show HEAD:tools/check_provenance.py > /tmp/head_cp.py
$ python3 /tmp/head_cp.py --root .
  not content-scanned (no text in the payload at all): 9 files — extension tripwires only
  unwrapped by magic (compressed stream / archive): 21 files — members content-scanned
tripwire hits (declared + undeclared): external-symlink-target=0,
  foreign-license-text=4, foreign-source-language=2, self-declared-quotation=43,
  submodule-reference=0, upstream-asset-extension=0

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
$ echo $?
0
```

| injected unattributed file | what it carries | before | after |
|---|---|---|---|
| `compiler/golden/masked_wavetables.dat` (zip renamed) | member `wavetables/Bank Sine.wt`, payload is opaque bytes | PASS | FAIL `wrapper-member-name` |
| `compiler/golden/masked_sources.dat` (tar.gz renamed) | member `vendor/Reverb1.cpp`, header stripped | PASS | FAIL |
| `reports/sxt-019/masked_asset.dat` (gzip renamed) | gzip FNAME header `Bank Sine.wt` — its only name | PASS | FAIL |
| `compiler/golden/masked_zip_in_gz.dat` (zip inside gzip) | the same `.wt` member, two wrappers deep | PASS | FAIL |
| `fixtures/audio/masked_wrapped_member.dat` (zip) | member `Bank Sine.wt` that is itself a gzip of `meta.json` | PASS | FAIL |

### After the fix — same five files, same tree

```
$ python3 tools/check_provenance.py
  unwrapped by magic (compressed stream / archive): 21 files — members
    content-scanned, 31 member name(s) read and judged
tripwire hits (declared + undeclared): …, wrapper-member-name=5

FAIL: 5 provenance finding(s):
  [wrapper-member-name] compiler/golden/masked_sources.dat
      … wrapper member 'vendor/Reverb1.cpp' (foreign-language source, extension .cpp)
  [wrapper-member-name] compiler/golden/masked_wavetables.dat
      … wrapper member 'wavetables/Bank Sine.wt' (upstream asset / opaque bundle, extension .wt)
  [wrapper-member-name] compiler/golden/masked_zip_in_gz.dat
      … wrapper member 'wavetables/Bank Sine.wt' (upstream asset / opaque bundle, extension .wt)
  [wrapper-member-name] fixtures/audio/masked_wrapped_member.dat
      … wrapper member 'Bank Sine.wt' (…), carried at 'Bank Sine.wt!meta.json'
  [wrapper-member-name] reports/sxt-019/masked_asset.dat
      … wrapper member 'Bank Sine.wt' (upstream asset / opaque bundle, extension .wt)
$ echo $?
1
```

Each finding names the offending **member**, and the nested case names both the
member and the label it was carried at — the `detail` snippet is the only
locator a human has, and this rule cannot be exempted. The five files were then
removed; the tree audits clean again (exit 0, numbers in §15 "Tree audit"
below).

### What changed

Three hunks, each pinned by the control that fails when it alone is reverted
(measured by monkeypatching the hunk out and re-running the group):

1. **The member name travels with its payload.** `_unwrap_archive` now returns
   `[(name, payload)]` (zip `info.filename`, tar `info.name`) and
   `unwrap_payload` returns `[(label, payload)]`, so the walker that already
   existed carries names instead of discarding them. One mechanism, not a
   second walker. Reverting it: all six must-fail controls fail.
2. **A gzip's FNAME header is parsed** (`_gzip_header_name`, RFC 1952 §2.3.1).
   `gzip.GzipFile` reads that field and throws it away with no public API, and
   it is the only name a single-stream wrapper has. Reverting it:
   `wrapper/gzip-fname-header-names-an-asset` fails.
3. **Every component of a nested label is judged** (`member_name_signals`
   splits on the join). Judging the label whole reads `Bank Sine.wt!meta.json`
   as a `.json` — the same "stop at the first answer" shape increments 2–5
   closed on the license rule. Reverting it:
   `wrapper/outer-member-name-not-masked-by-the-inner-one` fails.

The check runs **before** the content rules' `text is None` early return,
because a marker-free wrapper has no text at all:
`test_marker_free_asset_member_reaches_no_content_rule` asserts
`tree.text(rel) is None` while `wrapper-member-name` is the one rule that
fires, so moving the check below that return would silently restore the whole
mask and fail a test rather than passing quietly.

Coverage for the new layer is reported, not assumed: `wrapper_member_names_read`
(31 with the fixtures in place, 26 on the clean tree) is printed on every run
and in `--json`, so "no member name offended" cannot be confused with "no
member name was examined" — a wrapper the audit cannot open contributes none.

### Coverage is not blanket: the rule must be declared

`wrapper-member-name` is **not** in `_structural_tripwire_rules`, so a
provenance row naming the file does not absorb it implicitly: the row must list
it in `covers`. Both directions are controlled —
`wrapper/asset-member-answered-by-a-row-passes` (row with `covers` → clean) and
`wrapper/a-row-without-covers-does-not-clear-it` (the *same* row without
`covers` → still fails). That is deliberate: a row filed for one reason (an
evidence bundle, a golden archive) must not silently cover an upstream member
name added to it later. It is also non-exemptible —
`test_wrapper_member_name_cannot_be_exempted` shows an exemption attempt
produces `exemption-non-exemptible-rule` **and** leaves the finding standing.

### False positives were measured before this was written, not assumed

`wrapper-member-name` cannot be exempted, so a false positive on one of this
repository's own wrappers would be *unanswerable* — the rule would be switched
off rather than answered. All 19 wrappers in the tracked tree were enumerated
and every name they carry was judged **before** the change was committed:

| | count | member-name extensions seen | hits |
|---|---|---|---|
| gzipped evidence traces (`*.json.gz`, `*.hex.gz`) | 18 | 9 `.json`, 6 `.hex` (3 streams carry no FNAME) | 0 |
| `.npz` tap fixture | 1 | 11 `.npy` | 0 |
| **total** | **19** | **26 names** | **0** |

Both shapes are kept as positive controls with real payloads —
`wrapper/own-gzipped-trace-with-an-fname-stays-clean` (a gzip whose header
really does carry `trace_…json`, which is what `gzip <file>` writes by default)
and `wrapper/own-npz-members-stay-clean`. Both stay clean under every hunk
reversion too, so neither passes merely because the fix is present.

Cost of the whole audit over this 533 MiB tree, same host, same runtime, two
runs of each tool back to back: **8.10 / 8.30 s → 8.27 / 8.15 s** wall, peak RSS
**572 MB → 571 MB**. The wall-clock delta is within run-to-run noise on this
shared 8-core host, and no extra inflation is performed: a member name is a
string the zip/tar reader has already produced, and the gzip FNAME parse reads
the header bytes that were read anyway. Reported as the interval actually
measured rather than as a single figure, because a sub-noise delta must not be
quoted as if it were resolved.

### Controls and tests

```
$ python3 tools/check_provenance.py --negative-control
PASS: all 32 rules fired on their deliberate violation, the clean control tree
produced no findings, all 6 occurrence-scoped exemption controls behaved, all 40
own-attribution masking controls behaved, all 11 discovery-layer controls
behaved, all 17 payload-layer controls behaved, and all 9 wrapper-member-name
controls behaved.
$ echo $?
0
```

Non-vacuity of the new group (9 controls: **6 must-fail, 3 must-stay-clean**),
checked against the **pre-change** tool on synthetic trees built by the same
mutators: all **six** must-fail cases audited **clean** (exit 0), and two of the
three must-stay-clean cases audited clean.
`wrapper/asset-member-answered-by-a-row-passes` is the one case the old tool
does not merely pass — it reports `manifest-schema`, because the row declares a
`covers` rule that tool has no concept of, which is itself the expected answer.

```
$ python3 -m pytest tests/test_sxt019_provenance.py -q
72 passed
```

Seven of those tests are new (`test_wrapper_member_name_is_judged_like_a_committed_path`,
`test_marker_free_asset_member_reaches_no_content_rule`,
`test_outer_member_name_is_not_masked_by_what_it_wraps`,
`test_gzip_header_name_is_parsed_and_absent_when_unset`,
`test_our_own_wrapper_shapes_still_audit_clean`,
`test_real_tree_member_names_are_read_and_none_offend`,
`test_wrapper_member_name_cannot_be_exempted`), and two existing unit pins were
updated for the walker's `(name, payload)` return shape.

### Tree audit (clean tree, after the fixtures were removed)

```
$ python3 tools/check_provenance.py
coverage: 2128 files scanned, 759 excluded by declared scope exclusions,
  18 decision records, 20 provenance rows covering 20 files, 9 exemptions
  unwrapped by magic (compressed stream / archive): 19 files — members
    content-scanned, 26 member name(s) read and judged
tripwire hits: …, upstream-asset-extension=0, wrapper-member-name=0

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
$ echo $?
0
```

### What §15 does NOT establish

- Found by **inspection**, like every increment before it. That this mask is
  closed is not evidence that no further path exists — only that these three
  hunks are pinned by controls that fail when each alone is reverted. The
  pattern is now three increments deep: §13 declared a limit, §14 found a mask
  inside it, §14 declared a limit, and this increment found a mask inside
  **that**. A declared limit is not evidence the limit was necessary.
- Two residuals stay **declared, not closed**, each pinned by a positive
  control: a notice written in a WIDE encoding *inside* a binary payload
  (`payload/wide-encoded-notice-in-a-payload-stays-out-of-scope`), and an
  inflation that hits the 256 MiB / 4-deep budget — a wrapper the audit cannot
  open (that budget, or a corrupt stream) yields no member names either, which
  is why the name count is reported per run.
- A member name is judged by the **same two extension sets** as a committed
  path, so a member type this repository authors (`.json`, `.hex`, `.npy`,
  `.py`, `.sv`) is not a signal. An upstream file renamed to one of those
  inside an archive is **not** detected — the identical residual that applies
  to a file's own name, not a new one.
- Member names are read from the wrappers the audit can **open**. A corrupt or
  truncated stream carries none; the partial read is disclosed, never counted
  as a pass.
- A PASS remains **bookkeeping and carriage-signal coverage only** (§7): a
  marker-free copy committed under an ordinary name, and a re-typed constant
  table with no citation, are still undetectable, as is anything under the
  declared scope exclusions (`.loom/`, `.claude/`, `.agents/` — 759 files).
- It ratifies nothing: 18 records on disk, most still
  PROPOSED / RECORDED / ESCALATED pending owner ratification, and this project
  has made **no distribution-license determination**.
- Whether any file in this repository's **history** ever carried an
  unattributed wrapper member is **NOT_RUN** — only the current tree was
  audited.
- No RTL, model, fidelity, preset or sound claim is touched by this increment.
- No Surge-, GPL- or otherwise third-party-derived content was copied into this
  repository by it. Every fixture is repo-invented synthetic data built at run
  time (archives assembled in memory, an opaque byte pattern generated by
  arithmetic); `Bank Sine.wt` and `vendor/Reverb1.cpp` appear only as member
  NAME strings inside synthetic archives, with no upstream payload behind them.

## 16. Increment 10 (2026-10-01) — the notice re-saved in a wide encoding, inside the payload §14 declared out of reach

Base: `main` `1aa4f43` (post-#285, which landed increment 9). Runtime: Python
3.12.3, Linux. Status: **PASS** on this branch; it ratifies nothing and
establishes nothing about DSP, RTL, fidelity or sound.

Increment 8 (§14) harvested the printable-ASCII runs of a payload the encoding
sniff refuses, and then *declared* the remainder:

> the harvest reads ASCII, so a notice written in a WIDE encoding *inside* a
> binary payload stays out of reach
> (`payload/wide-encoded-notice-in-a-payload-stays-out-of-scope`)

That declaration was wrong in the same way §14's was wrong about §13's, and
§15's about §14's. A UTF-16 save is what an ordinary editor's "Unicode" option
produces — it is not an exotic carriage — and the sniff already decodes a file
that is wide-encoded *throughout*. What no layer did was read a payload that is
mostly binary with a wide-encoded notice spliced into it: 310 files on this tree
were read as ASCII runs only, and the coverage line said as much
("a non-ASCII notice inside one would be missed") without anything acting on it.

### Demonstrated on the real tree, before the fix

Five deliberately unattributed files, each carrying a complete foreign copyright
line **and** GPL body re-encoded, injected into the **tracked** tree
(`git add -N`; `list_files` audits `git ls-files`, so untracked scratch is out of
scope by design) and run against the **pre-change** tool:

```
$ git show HEAD:tools/check_provenance.py > /tmp/head_cp_i10.py
$ python3 /tmp/head_cp_i10.py --root .
coverage: 2133 files scanned, 759 excluded by declared scope exclusions,
  18 decision records, 20 provenance rows covering 20 files, 9 exemptions
  not content-scanned (no text in the payload at all): 10 files
  unwrapped by magic (compressed stream / archive): 19 files — 26 member name(s)
  scanned as extracted ASCII strings only: 311 files
tripwire hits (declared + undeclared): external-symlink-target=0,
  foreign-license-text=4, foreign-source-language=2, self-declared-quotation=43,
  submodule-reference=0, upstream-asset-extension=0, wrapper-member-name=0

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
$ echo $?
0
```

The tripwire counts are **identical to the clean tree's** — the five files
changed nothing at all.

| injected unattributed file | carriage | before | after |
|---|---|---|---|
| `fixtures/audio/masked_wide_notice.wav` (real PCM WAV) | notice UTF-16-LE inside the `data` chunk | PASS | FAIL `foreign-license-text` ×2 |
| `reports/sxt-019/masked_wide_be.f32` (float32 dump) | the same notice in UTF-16-**BE**, spliced mid-payload | PASS | FAIL ×2 |
| `compiler/golden/masked_wide_utf32.dat` (opaque payload) | the same notice in UTF-32-LE | PASS | FAIL ×2 |
| `reports/sxt-019/masked_wide_bom.f32` (float32 dump) | BOM-led UTF-16 (`\xff\xfe`), spliced mid-payload | PASS | FAIL ×2 |
| `reports/sxt-019/masked_wide_member.json.gz` (gzip) | an opaque **member** with a UTF-16-LE notice in it | PASS | FAIL ×2 |

### After the fix — same five files, same tree

```
$ python3 tools/check_provenance.py
  not content-scanned (no text in the payload at all): 6 files
  unwrapped by magic (compressed stream / archive): 20 files — 26 member name(s)
  scanned as extracted strings only: 314 files
  wide-encoded (UTF-16/UTF-32) runs harvested from payloads and judged: 77
tripwire hits (declared + undeclared): …, foreign-license-text=14, …

FAIL: 10 provenance finding(s):
  [foreign-license-text] compiler/golden/masked_wide_utf32.dat
      … gpl-body: <the GPL redistribution sentence, elided here>
  [foreign-license-text] compiler/golden/masked_wide_utf32.dat
      … copyright line: <the synthetic holder line, elided here>
  [foreign-license-text] fixtures/audio/masked_wide_notice.wav        (×2)
  [foreign-license-text] reports/sxt-019/masked_wide_be.f32           (×2)
  [foreign-license-text] reports/sxt-019/masked_wide_bom.f32          (×2)
  [foreign-license-text] reports/sxt-019/masked_wide_member.json.gz   (×2)
$ echo $?
1
```

Each finding quotes the offending notice, which is the only locator a human has
for answering a rule that cannot be exempted. **Those two snippets are elided
above on purpose**: quoted verbatim they made *this document* carry a notice, and
the audit flagged `reports/sxt-019/EVIDENCE.md` itself for it on the first run —
the rule is non-exemptible and applies to the evidence record exactly as it does
to everything else. The five files were then removed; the tree audits clean again
(exit 0, numbers under "Tree audit" below).

### What changed

The runs are found by their **shape**, not by a name or a declaration, and
without loosening the sniff at all — decoding a render as prose is the other
failure direction, and §13's positive control still guards it. An ASCII code
point in UTF-16/UTF-32 is one data byte plus NUL padding, so a wide run is a run
of NULs in one of the two half-stride streams whose matching data bytes are all
printable:

```
utf-16-le  'H\0e\0'   NULs at odd offsets,  data at even
utf-16-be  '\0H\0e'   NULs at even offsets, data at odd
utf-32-le  'H\0\0\0'  NULs at odd offsets,  and the data stream is itself
utf-32-be  '\0\0\0H'    NUL-padded, so one more halving step resolves it
```

Looking for the **padding** rather than for alternating pairs is what makes this
affordable: `\x00{6,}` has a literal prefix, so the regex engine finds candidates
at memchr speed instead of restarting a character class at every byte.

Six hunks. Five are pinned by a control that fails when **it alone** is reverted
(measured by reverting each in a scratch copy of the tool and re-running the
whole self-test); the sixth is a precision hunk pinned by measurement on real
data, and says so.

| reverted hunk | self-test result |
|---|---|
| baseline (all present) | exit 0, no control fails |
| H1 the wide harvest runs at all | exit 2, **all 9** `payload/wide-*`,`utf32-*` must-fail controls fail |
| H2 a wrapper's members are harvested too | exit 2, `payload/wide-notice-inside-a-wrapper-member` |
| H3 the second halving step (UTF-32) | exit 2, `payload/utf32-le-…`, `payload/utf32-be-…` |
| H4 the inner step needs an all-NUL other half | exit 0 — **precision only**, see below |
| H5 both data windows (odd alignment) | exit 2, `payload/wide-holder-line-at-an-odd-offset` |
| H6 0xA9 admitted inside a wide run | exit 2, `payload/wide-encoded-copyright-sign-notice` |

No reversion failed another hunk's control, and **every must-stay-clean control
stayed clean under all six**.

- **H5 is a coverage fix, not tidiness.** A notice lands on an odd byte offset as
  often as an even one, and at an odd offset each code unit's data byte sits on
  the *other* side of its padding. The first version of this layer read one
  window and was caught by a unit test asserting every alignment; the control
  that pins it in CI had to be built so the run's **first character** is
  load-bearing — a bare holder line with no `(c)` marker, where the reading one
  unit late is "opyright 2019 …" and matches no prefilter at all.
- **H4 is pinned by the real tree, not by a control.** Dropping it leaves the
  committed tree PASS with identical tripwire counts, so no control fails — but
  the wide-run count goes from **71 to 978**, i.e. 14× more unvalidated decimated
  noise fed to a non-exemptible rule. Synthetic LCG "PCM" does not reproduce it
  (real renders are correlated, LCG noise is not), so the pin is
  `test_wide_run_coverage_is_reported_for_the_real_tree`'s `<= 300` bound on
  `wide_encoded_runs_harvested`, which fails at 978 and has 4× headroom for tree
  growth.

### False positives were measured before this was written, not assumed

`foreign-license-text` **cannot be exempted**, so a false positive on one of this
repository's own renders would be *unanswerable* — the rule would be switched off
rather than answered. And the hazard here is specific and severe: **a quiet
16-bit PCM sample is a low byte beside a NUL high byte, which is byte-for-byte
what a UTF-16-LE string looks like**, and this repository's renders are mostly
quiet. The first design measured (an alternating-pair regex with a ratio test)
produced **69,096** word-bearing "wide runs" over the tree's payloads, and cost
34 s.

Measured on the committed tree with the design that shipped:

| | value |
|---|---|
| payload files scanned as strings | 310 (338.9 MiB) |
| wide-encoded runs harvested and judged | **71**, all from 34 `.wav` renders |
| longest harvested run | 28 chars (`'(^ljbWTUXY[\]]]]]]\\[YWTNE7 '`) |
| hits on the four content signals | **0** |
| committed tripwire counts | **unchanged**: `foreign-license-text=4`, `foreign-source-language=2`, `self-declared-quotation=43`, `upstream-asset-extension=0`, `wrapper-member-name=0` |

Cost, two runs of each tool back to back on this shared 8-core host:

```
pre-change:  9.14 s / 9.36 s wall, 573,064 / 572,924 KB peak RSS
this change: 12.22 s / 12.72 s wall, 573,176 / 573,116 KB peak RSS
```

So ≈ +3.2 s wall (+35 %) and **no measurable memory cost** — the same order as
the ASCII harvest that was already being paid (4.5 s of the pre-change run).

One false positive *was* found by this measurement, and it was in this file's own
prose rather than in a payload: a comment written with a literal © followed by a
capitalised word read as a copyright line, and `tools/check_provenance.py` is
**not** exempt from `foreign-license-text`. Fixed the way every fixture here
already was — the sign is derived from its byte constant
(`COPYRIGHT_SIGN_CHAR`) and the prose says "the sign spelling (U+00A9)" — not by
exempting anything.

### Controls and tests

```
$ python3 tools/check_provenance.py --negative-control
PASS: all 32 rules fired on their deliberate violation, the clean control tree
produced no findings, all 6 occurrence-scoped exemption controls behaved, all 40
own-attribution masking controls behaved, all 11 discovery-layer controls
behaved, all 27 payload-layer controls behaved, and all 9 wrapper-member-name
controls behaved.
$ echo $?
0
```

The payload group is now **27 controls (21 must-fail, 6 must-stay-clean)**, up
from 17. Nine new must-fail cases (UTF-16-LE, UTF-16-BE, UTF-32-LE, UTF-32-BE, an
odd offset, a bare holder line at an odd offset, a BOM-led notice inside a real
render's data chunk, a wrapper member, and the sign spelling) and two new
must-stay-clean cases (a **quiet** PCM render; a base64-carried notice, the new
declared residual). Increment 8's
`payload/wide-encoded-notice-in-a-payload-stays-out-of-scope` is **inverted** on
the same fixture bytes and is now `payload/wide-encoded-notice-in-a-payload`,
which must FIRE.

Non-vacuity against the **pre-change** tool, on synthetic trees built by the same
mutators: all **nine** new must-fail cases audited **clean (exit 0)**, and both
new must-stay-clean cases audited clean before and after. So each was a mask, not
a case the old tool answered differently.

```
$ python3 -m pytest -q tests/test_sxt019_provenance.py
75 passed                      (72 before)

$ python3 -m pytest -q tests
1269 passed, 19 skipped        (1266 before)

$ python3 -m compileall -q tools corpus/census-v0.1     # OK
$ python3 tools/check_census_consistency.py             # exit 0
$ python3 tools/compile_backlog_dag.py --check          # exit 0
```

Three tests are new: `test_wide_encoded_notice_in_a_payload_is_flagged` (seven
carriages, end to end), `test_wide_run_harvest_reads_each_encoding_and_refuses_decimated_noise`
(the unit-level admission test, every encoding at **every byte alignment**, the
narrow runs shown to be empty for the same bytes, and the sign normalisation),
and `test_wide_run_coverage_is_reported_for_the_real_tree` (the layer runs on
this repository, and the H4 precision bound). Two existing tests were updated:
the wide fixture moved from the "stays clean" list to the flagged one, and a
quiet render plus the base64 residual took its place there.

**TDD.** The failing case came first: the five masked files were injected into
the tracked tree and shown to audit PASS / exit 0 / unchanged counts under the
pre-change tool *before* any code was written; the eleven firing `payload/*`
controls were added next and only then made to pass.

### Tree audit (clean tree, after the fixtures were removed)

```
$ python3 tools/check_provenance.py
coverage: 2128 files scanned, 759 excluded by declared scope exclusions,
  18 decision records, 20 provenance rows covering 20 files, 9 exemptions
  not content-scanned (no text in the payload at all): 6 files
  unwrapped by magic (compressed stream / archive): 19 files — 26 member name(s)
  scanned as extracted strings only: 310 files
  wide-encoded (UTF-16/UTF-32) runs harvested from payloads and judged: 71
tripwire hits: …, foreign-license-text=4, self-declared-quotation=43,
  upstream-asset-extension=0, wrapper-member-name=0

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
$ echo $?
0
```

No committed file changed status: the counts are the same as `main`'s.

### What §16 does NOT establish

- Found by **inspection**, like every increment before it. That this mask is
  closed is not evidence that no further path exists — only that five of its six
  hunks are pinned by controls that fail when each alone is reverted, and the
  sixth by a measurement on real data. The pattern is now **four increments
  deep**: §13 declared a limit, §14 found a mask inside it; §14 declared two,
  §15 found a mask inside one and this increment found a mask inside the other.
  A declared limit is not evidence the limit was necessary.
- Two residuals stay **declared, not closed**, each pinned by a positive
  control: a notice carried in a **TRANSFORMED** encoding — base64 here, and any
  other re-coding that is not the bytes of its characters
  (`payload/base64-encoded-notice-stays-out-of-scope`) — and an inflation that
  hits the 256 MiB / 4-deep budget, disclosed per path as a `TRUNCATED payload
  scan`.
- A wide run is admitted on an "its characters are ASCII" test, so a notice
  wide-encoded in a **non-Latin script** is refused, exactly as it is at the
  decode layer; license notices are ASCII English, and admitting everything
  would turn every render into garbage findings on a non-exemptible rule. A run
  shorter than `MIN_WIDE_RUN_UNITS` (6 code units) is dropped, the same declared
  floor the ASCII harvest applies in bytes.
- Reading both data windows means a real text is often read **twice**; the
  coverage count counts runs *read and judged*, duplicates included, and is not
  a count of distinct strings.
- A PASS remains **bookkeeping and carriage-signal coverage only** (§7): a
  marker-free copy committed under an ordinary name, and a re-typed constant
  table with no citation, are still undetectable, as is anything under the
  declared scope exclusions (`.loom/`, `.claude/`, `.agents/` — 759 files).
- It ratifies nothing: 18 records on disk, most still
  PROPOSED / RECORDED / ESCALATED pending owner ratification, and this project
  has made **no distribution-license determination**.
- Whether any file in this repository's **history** ever carried a wide-encoded
  notice inside a payload is **NOT_RUN** — only the current tree was audited.
- No RTL, model, fidelity, preset or sound claim is touched by this increment.
- No Surge-, GPL- or otherwise third-party-derived content was copied into this
  repository by it. Every fixture is repo-invented synthetic data built at run
  time (PCM from an in-file LCG, float dumps, archives assembled in memory), and
  `Some Upstream Author` appears only as a name string inside synthetic notices,
  carrying no upstream code, table or asset.

## 17. Increment 11 (2026-10-01) — the set that was never enumerated: the git index boundary

Base: `main` `892c516` (post-#288, which landed increment 10). Runtime: Python
3.12.3, Linux. Status: **PASS** on this branch; it ratifies nothing and
establishes nothing about DSP, RTL, fidelity or sound.

Every increment from §13 to §16 worked on how an entry is **read** — the
encoding sniff, the by-reference discovery layer, wrappers, embedded notices,
wide encodings. This one is below all of them: which entries are **enumerated**
at all.

`list_entries` reads `git ls-files -s`, so the audited set is the git **index**,
not the working tree. That was never declared as a limit — it was written down
once, in §16, as a definition:

> `list_files` audits `git ls-files`, so untracked scratch is out of scope by
> design

The design is right. Auditing a developer's scratch files by default would put
unanswerable findings on a **non-exemptible** rule. What was wrong is that the
boundary was **silent**: nothing in the run said a file in the tree had been
skipped, and the file count was identical either way — so "no unattributed file
is here" and "one is here, unlooked at" produced byte-identical coverage.

### Demonstrated on the real tree, before the fix

One deliberately unattributed file — a complete foreign copyright line, a
foreign SPDX tag **and** a GPL body — written to `model/_scratch_unattributed_demo.py`
in the real tree and left unstaged, run against the **pre-change** tool:

```
$ git show HEAD:tools/check_provenance.py > /tmp/head_cp_i11.py
$ python3 /tmp/head_cp_i11.py --root .
coverage: 2128 files scanned, 759 excluded by declared scope exclusions,
  18 decision records, 20 provenance rows covering 20 files, 9 exemptions
tripwire hits (declared + undeclared): external-symlink-target=0,
  foreign-license-text=4, foreign-source-language=2, self-declared-quotation=43,
  submodule-reference=0, upstream-asset-extension=0, wrapper-member-name=0

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
$ echo $?
0
```

`2128 files scanned` and every tripwire count are **identical to the clean
tree's**. The file changed nothing at all, and the output disclosed nothing.

This is the exact shape acceptance item 4 names ("demonstrate it once on a
deliberately unattributed file"): prior demonstrations (§3, §16) had to `git add`
the fixture first, which is the step the finding is about.

### After the fix — the same tree, same file, same place

Default run (the boundary is kept, and now disclosed):

```
$ python3 tools/check_provenance.py
  present in the working tree but NOT in the git index: 1 entries — not audited
    by any rule; re-run with --include-untracked to audit them
      not audited (not in the index): model/_scratch_unattributed_demo.py

PASS: every carriage signal is answered by a provenance row or a declared
exemption, and the decision-record bookkeeping is self-consistent.
$ echo $?
0
```

Opt-in run (the boundary crossed on demand):

```
$ python3 tools/check_provenance.py --include-untracked
  present in the working tree but not in the git index: 1 entries — AUDITED
    (--include-untracked)

FAIL: 3 provenance finding(s):
  [foreign-license-text] model/_scratch_unattributed_demo.py
      foreign license/copyright text without a provenance row: gpl-body: …
  [foreign-license-text] model/_scratch_unattributed_demo.py
      foreign license/copyright text without a provenance row:
      SPDX-License-Identifier tag: GPL-3.0-or-later …
  [foreign-license-text] model/_scratch_unattributed_demo.py
      foreign license/copyright text without a provenance row: copyright line: …
$ echo $?
1
```

The file was then removed and the tree re-audited: `0 entries` un-indexed,
**PASS**, `git status --porcelain` showing only this increment's two source
files.

### The change

Three hunks, all at the enumeration layer; no rule was added, removed or
loosened, and the real tree's tripwire counts are unchanged
(`foreign-license-text=4`).

1. `list_untracked()` — `git ls-files --others --exclude-standard`, guarded by
   `_is_git_checkout()` so a non-checkout tree (every synthetic control tree,
   and `--negative-control`'s) reports **zero** rather than an enclosing
   repository's view of itself. Without that guard a synthetic tree created
   inside a checkout would report every file as un-audited while every rule had
   in fact run on it.
2. Coverage: `entries_present_but_not_in_the_index` (the paths, not just a
   count) and `untracked_entries_audited`, in `--json` and on the text report —
   **printed even when zero**, and naming up to 10 paths, for the same reason
   `wrapper_member_names_read` and `wide_encoded_runs_harvested` are printed:
   "none present" and "never looked" must not look alike.
3. `--include-untracked` adds those entries as ordinary ones, so every rule
   runs on them.

### Controls

Seven `coverage/*` controls run inside `--negative-control`. They are the
**only** controls in this tool that assert on coverage rather than on findings,
and they have their own runner because of it: the default behaviour under test
is deliberately *"produce no finding"*, so a findings-based control would be
satisfied by the very silence this increment removes.

| Control | Must |
|---|---|
| `coverage/unstaged-carrier-is-disclosed-not-silently-skipped` | name the carrier in `entries_present_but_not_in_the_index`, and **not** flag it |
| `coverage/fully-staged-tree-reports-zero` | still report the count, as zero |
| `coverage/gitignored-scratch-is-neither-counted-nor-audited` | hold the declared sub-boundary |
| `coverage/unstaged-path-inside-a-declared-scope-exclusion` | not re-count an already-disclosed hole |
| `coverage/non-git-tree-reports-zero-and-still-audits-everything` | report zero **and** still fire on the walked carrier |
| `coverage/unstaged-carrier-is-audited-when-included` | fire `foreign-license-text` under `--include-untracked` |
| `coverage/ignored-path-stays-out-even-when-included` | keep the sub-boundary on the opt-in path |

**Non-vacuity**, checked by reverting each hunk alone in the working file and
re-running `--negative-control`:

- revert hunk 1 (`list_untracked` returns `[]`) → `unstaged-carrier-is-disclosed-not-silently-skipped`
  **FAILs** (`entries_present_but_not_in_the_index=[]`) and
  `unstaged-carrier-is-audited-when-included` **FAILs**; self-test exits `2`.
  Both fail because hunk 1 is the shared enumeration both paths read.
- revert hunk 3 (`--include-untracked` stops adding entries) → **only**
  `unstaged-carrier-is-audited-when-included` FAILs; all five disclosure
  controls still PASS. Self-test exits `2`.

### Verification run on this branch

```
$ python3 tools/check_provenance.py                   -> PASS  (exit 0)
$ python3 tools/check_provenance.py --negative-control -> PASS  (exit 0)
   32/32 rules, 6 scoped-exemption, 40 masking, 11 discovery,
   27 payload, 9 wrapper-member-name, 7 index-boundary coverage controls
$ python3 -m pytest -q tests/test_sxt019_provenance.py -> 85 passed
```

### What this increment does NOT establish

- **The boundary is narrowed and disclosed, not removed.** The default audited
  set is still the git index. A PASS on a dirty working tree now *says* what it
  did not look at; it does not look at it.
- **Ignored paths stay out, by declaration.** `.gitignore` is this repository's
  own statement that a path is not part of it, and build output would otherwise
  drown the signal. Pinned by two controls, on both the default and opt-in
  paths.
- **History is still out of reach.** Whether any file was ever committed and
  later removed is **NOT_RUN** — then and now, only the current tree is audited.
- **Found by inspection**, like every increment before it, and by running
  acceptance item 4's own demonstration in the one layout it had never been run
  in. That this residual is closed is not evidence no further one exists; the
  pattern is now **five increments deep** — §16 wrote this boundary down as a
  design decision and it turned out to be an undeclared limit.
- A PASS remains **bookkeeping and carriage-signal coverage only** (§7). No
  committed file changed status: no provenance row is added, no decision record
  is revised or ratified (18 records, most still PROPOSED / RECORDED /
  ESCALATED), and this project has made **no distribution-license
  determination**.
- No RTL, model, fidelity, preset or sound claim is touched.
- No Surge-, GPL- or otherwise third-party-derived content was copied into this
  repository by this increment. The demonstration file was synthetic, written
  and deleted inside this session; `Some Upstream Author` is a name string in a
  synthetic notice, carrying no upstream code, table or asset.

## 18. Increment 12 (2026-10-01) — inside §15's own fix: the gzip members whose names were never read

Base: `main` `9eca4e7` (the resync chore on top of `03e4758`/#290, which landed
increment 11). Runtime: Python 3.12.3 (stdlib only), Linux. Status: **PASS** on
this branch; it ratifies nothing and establishes nothing about DSP, RTL,
fidelity, preset support or sound. Issue
[#286](https://github.com/2AMLogic/gf180-surge/issues/286).

Every increment from §13 to §17 went one layer *below* the last. This one went
**back inside** §15's own fix. §15 added `wrapper-member-name`, the only signal a
marker-free wrapper member has. For an archive it read every member's name. For
a **stream** it read the name once:

```python
inner, truncated = _unwrap_stream(raw, kind, limit)   # inflates EVERY member
label = _gzip_header_name(raw) if kind == "gzip" else None   # reads ONE name
```

A gzip may be **concatenated** — `cat a.gz b.gz > c.gz` is a valid gzip file —
and every member carries its own FNAME header. So members 2..n were inflated and
content-scanned but never **named**, and the rule became order-dependent: the
same two members swapped were caught.

### Demonstrated before the fix, on the fixture, with the base commit's own tool

The fixture is a two-member gzip: member 1 named `notes.json` carrying ordinary
JSON, member 2 named `Bank Sine.wt` carrying a marker-free wavetable payload —
no notice, no copyright line, nothing but the name. Written to
`compiler/golden/wavetables.dat` (so the file's own extension is innocuous too)
in a skeleton tree, audited by `git show 9eca4e7:tools/check_provenance.py`:

```
$ git show 9eca4e7:tools/check_provenance.py > /tmp/base_cp_i12.py
   fixture: _gzip_with_name("notes.json", …) + _gzip_with_name("Bank Sine.wt", …)

second-member-names-a-.wt  BASE 9eca4e7  findings=CLEAN                  names_read=1
second-member-names-a-.wt  AFTER         findings=['wrapper-member-name'] names_read=2
first-member-names-a-.wt   BASE 9eca4e7  findings=['wrapper-member-name'] names_read=1
first-member-names-a-.wt   AFTER         findings=['wrapper-member-name'] names_read=2
own-two-member-trace       BASE 9eca4e7  findings=CLEAN                  names_read=1
own-two-member-trace       AFTER         findings=CLEAN                  names_read=2
```

The two middle rows are the whole finding stated as the property it violated:
**the same two members in the other order already fired**. The last row is the
false-positive direction — two of this repository's own `.json` trace members in
one stream, which must read as two names and stay clean.

`unwrap_payload` directly, on the same fixture:

| | member names returned | payload bytes inflated |
|---|---|---|
| `9eca4e7` | `['notes.json']` | 1038 |
| this branch | `['notes.json', 'Bank Sine.wt']` | 1038 |

**Content coverage was never the gap** — identical bytes, both tools. Every
member was already inflated and string-scanned, so a member carrying a licence
notice was caught by `foreign-license-text` either way. Only the NAME layer
undercounted, and `wrapper_member_names_read` could not disclose it: a two-name
stream reported `1`, which is exactly what a one-name stream reports. The tell
was order-dependence, not coverage.

### The change

Two hunks in `tools/check_provenance.py`; no rule added, removed or loosened.

1. `_gzip_members(raw, limit)` — walks the stream member by member with
   `zlib.decompressobj(wbits=16+MAX_WBITS)`, which stops at each member's own
   trailer and hands the remainder back as `unused_data` (the only boundary a
   concatenated stream has; `gzip.GzipFile` inflates straight through them, which
   is why it cannot be asked where member 2's header starts). Returns
   `[(FNAME|None, payload)]` per member, or `None` for a stream that is not
   cleanly parseable — the same answer, and the same fall-through to the string
   harvest, that `BadGzipFile` produced before.
2. `unwrap_payload` routes `gzip` through it and labels **each** member, instead
   of reading one FNAME per stream. `bzip2`/`xz` still go through
   `_unwrap_stream`; neither format carries a member name, so there is nothing
   there to read.

### The inflation budget and its truncation disclosure are unchanged

This is the increment's **stop/escalate** clause (#286: *"if closing it would
require tracking member boundaries in a way that changes the inflation budget's
accounting, stop and declare it instead — do not weaken the truncation
disclosure to make the name walk fit"*). It did not. One `remaining` counter is
threaded across the members of one stream, exactly as `_unwrap_archive` already
threads one across a zip's or a tar's members, so the **per-stream total is
still `limit`** and the first member that exceeds what is left truncates there
and reports it. `MAX_UNWRAPPED_BYTES` is `268435456` before and after.

Re-derived by inflating the two-member fixture at both tools across the
thresholds around its own size (1038 bytes):

```
limit=    1   base 1 bytes TRUNCATED   | new 1 bytes TRUNCATED
limit=   14   base 14 bytes TRUNCATED  | new 14 bytes TRUNCATED   (member-1 boundary)
limit=   20   base 20 bytes TRUNCATED  | new 20 bytes TRUNCATED   (inside member 2)
limit= 1037   base 1037 bytes TRUNCATED| new 1037 bytes TRUNCATED
limit= 1038   base 1038 bytes ok       | new 1038 bytes ok
limit= 1039   base 1038 bytes ok       | new 1038 bytes ok
```

Byte-for-byte identical totals, and `truncated` flips at the identical
threshold, so `payload_scans_truncated` names exactly the same scans it did
before. A scan the budget stops is still reported **TRUNCATED**, never as a
pass. Pinned live by
`test_concatenated_gzip_keeps_the_inflation_budget_accounting`, which lowers
`MAX_UNWRAPPED_BYTES` to 20 and asserts both halves.

### Real-tree census, re-derived (not quoted)

```
tracked gzip streams:        18
member-count histogram:      {1: 18}        <- every one single-member
streams carrying an FNAME:   15  (3 carry none)
truncated member walks:      []
all wrapper member names read: 26  {.json: 9, .hex: 6, .npy: 11}
```

**Current exposure is zero**: no committed file in this repository is a
multi-member stream, so no committed file changed status. That is why this was
closed *before* it mattered rather than after. The count is re-derived live by
`test_real_tree_gzip_streams_are_all_single_member` instead of being asserted in
prose, so a future multi-member commit moves it.

Whole-tree audit, same tree, both tools — **byte-identical coverage**:

```
$ python3 /tmp/base_cp_i12.py --root .     -> PASS (exit 0)
$ python3 tools/check_provenance.py --root . -> PASS (exit 0)

  coverage: 2128 files scanned, 759 excluded, 18 decision records,
    20 provenance rows covering 20 files, 9 exemptions
  unwrapped by magic: 19 files — 26 member name(s) read and judged
  tripwire hits: foreign-license-text=4, foreign-source-language=2,
    self-declared-quotation=43, wrapper-member-name=0,
    upstream-asset-extension=0, external-symlink-target=0, submodule-reference=0
```

### Controls and tests

One must-fail control added to the `wrapper/*` set, taking it from 9 to 10:

| Control | Must |
|---|---|
| `wrapper/second-member-of-a-concatenated-gzip-names-an-asset` | fire `wrapper-member-name` quoting `Bank Sine.wt` |

Its two existing own-wrapper positive controls
(`own-gzipped-trace-with-an-fname-stays-clean`, `own-npz-members-stay-clean`)
and the other seven must-fail cases are **unchanged and still behave**.

**Non-vacuity**, checked in both directions:

- On `9eca4e7`'s tool the new fixture audits **CLEAN** (table above) — so the
  control is not satisfied by pre-existing behaviour.
- Reverting the name walk alone in the working file (keep `_gzip_members`, but
  label members 2..n `None`, reproducing the one-name-per-stream read) →
  **exactly one** control FAILs,
  `wrapper/second-member-of-a-concatenated-gzip-names-an-asset`; self-test exits
  `2`.

Six tests added to `tests/test_sxt019_provenance.py`: both names and both
payloads returned; the rule fires in **either** member order (the property, not
one example); the coverage counter reports `2`; the budget accounting and its
truncation disclosure survive a lowered `MAX_UNWRAPPED_BYTES`; a corrupt or
trailing-garbage gzip is *not* read as a wrapper (so it falls through to the
string harvest rather than reading as clean); and the real tree's
single-member census.

### Verification run on this branch

```
$ python3 tools/check_provenance.py                    -> PASS  (exit 0)
$ python3 tools/check_provenance.py --negative-control -> PASS  (exit 0)
   32/32 rules, 6 scoped-exemption, 40 masking, 11 discovery,
   27 payload, 10 wrapper-member-name, 7 index-boundary coverage controls
$ python3 -m pytest -q tests/test_sxt019_provenance.py -> 91 passed
```

### What §18 does NOT establish

- **The name layer is now order-independent for gzip; it was never the only
  layer.** A member whose name is innocuous and whose content carries no marker
  is still invisible to this rule, exactly as a committed file with those two
  properties is. That is the standing limit of a carriage-signal audit, not a
  new one.
- **Two residuals remain declared, not closed**, unchanged by this increment and
  each still control-pinned: a notice carried in a TRANSFORMED encoding
  (base64, or any re-coding that is not the bytes of its characters), and an
  inflation that hits the unwrap budget — a wrapper the audit cannot open
  yields no member names either. This increment did **not** add a third: it
  closed the gap rather than declaring it, which is why `tools/check_provenance.py`'s
  DECLARED LIMITS section still says "two".
- **Found by inspection**, during review of #285 — the increment that
  introduced the rule. The pattern is now **six increments deep**, and this one
  is the first to find the gap *inside* a previous increment's fix rather than
  in a layer beneath it. That this residual is closed is not evidence no further
  one exists.
- **Zero committed files changed status.** No provenance row is added, no
  decision record is revised or ratified (18 records, most still PROPOSED /
  RECORDED / ESCALATED), and this project has made **no
  distribution-license determination**.
- No RTL, model, fidelity, preset or sound claim is touched. A PASS remains
  bookkeeping and carriage-signal coverage only (§7).
- No Surge-, GPL- or otherwise third-party-derived content was copied into this
  repository by this increment. Both fixtures are synthetic: `Bank Sine.wt` is a
  **name string** in a gzip header, and the payload under it is a generated
  marker-free byte pattern already in the tool, carrying no upstream code,
  table or asset.
