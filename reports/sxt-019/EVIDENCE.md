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
