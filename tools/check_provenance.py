#!/usr/bin/env python3
"""SXT-019 provenance audit — governance issue #25, acceptance item 4.

Flags any file that carries (or admits carrying) third-party-derived content
without a provenance row, and keeps the `decision-records/` bookkeeping
self-consistent. The rules this enforces come from `AGENTS.md` ("copying
Surge-derived code, tables, or assets into this repository requires a visible
license decision record before merge"; "record file/table-level provenance
before adopting any third-party code, table, or asset") and from
`docs/REUSE-AUDIT.md` § "Adoption mechanics".

The audit has four groups of checks:

  1. **Decision-record index integrity** — every `decision-records/NNNN-*.md`
     has exactly one row in the `README.md` index, every row resolves to an
     existing record, and each row's status keyword and date match the
     record's own header fields. (A missing row is how this issue's own
     staleness happened; the check makes recurrence a CI failure.)
  2. **Citation integrity** — every `decision-records/NNNN` / `DR-NNNN`
     citation anywhere in the scanned tree resolves to a record that exists
     and is indexed. A PR cannot claim a license decision record that is not
     there. Read from every byte view the citing entry has (increment 16),
     because a citation published only by the index is still published.
  3. **Provenance manifest integrity** — `decision-records/provenance.json`
     rows are exact and current: the path exists, the class is known, the
     cited decision record exists and is indexed, and the file itself
     corroborates the row (it cites the record, or the pinned upstream
     commit the row names) — in every byte view that file has, since a row is
     a claim a commit publishes and the published bytes have to carry what it
     claims (increment 16). Stale rows, blanket patterns, and exemptions
     that match nothing all fail.
  4. **Undeclared-carrier tripwires** — content signals that a file carries
     third-party material. A tripwire hit must be answered by a provenance
     row (or, for the one exemptible rule, by an explicit exemption with a
     reason — optionally scoped to named *occurrences* of the quotation
     vocabulary in one file, so a later foreign quotation elsewhere in the
     same file still fails; a named occurrence must match EXACTLY ONCE in
     that file, so the same sentence re-used for a foreign referent is
     reported as ambiguous instead of being exempted along with it). These
     read BOTH byte sources an entry can have — its working-tree copy and,
     when the two are not known to match, its STAGED blob, which is what
     `git commit` publishes (increment 14). The tripwires are deliberately
     high-precision:
       * `foreign-license-text`        — foreign license body, non-Apache
                                         SPDX tag, or foreign copyright line.
                                         EVERY notice in a file is inspected;
                                         each notice's holder is read from its
                                         own HOLDER FIELD (the name after the
                                         year), which must name US AND NOBODY
                                         ELSE — in that segment or in any later
                                         segment of the same line; a notice may
                                         carry no year at all, or wrap its
                                         holder list onto a continuation line;
                                         every operand of an
                                         SPDX *expression* is compared and the
                                         remainder of the tag is scanned for a
                                         license id by shape; and a license
                                         body is matched across the comment
                                         leader a pasted header wraps on — so
                                         our own attribution, above a pasted
                                         upstream header or named inside it,
                                         does not mask it
       * `upstream-asset-extension`    — Surge/third-party asset or opaque
                                         binary-bundle extensions
       * `foreign-source-language`     — source languages this repository
                                         does not author
       * `wrapper-member-name`         — a wrapper (gzip/bzip2/xz stream, zip
                                         or tar, nested) carrying a MEMBER
                                         NAME in either extension set above:
                                         a `.wt` wavetable inside an archive
                                         renamed `.dat`, a stripped `.cpp`
                                         inside a tar, a gzip whose FNAME
                                         header is the only name it has. The
                                         member payload itself states nothing,
                                         so its name is the whole signal; each
                                         component of a nested label is judged,
                                         so an outer name is not masked by what
                                         it wraps; and EVERY member of a
                                         concatenated gzip stream is named, so
                                         the rule does not depend on which
                                         member was written first
       * `self-declared-quotation`     — the repo's own quotation vocabulary
                                         ("quoted as data", "QUOTED",
                                         "transcribed from", "vendored", …)
                                         co-occurring with an upstream
                                         citation                (exemptible)
       * `submodule-reference`         — a committed submodule gitlink (or, in
                                         a non-git tree, a nested repository
                                         checkout): content in the build tree
                                         that is in no file of this one
       * `external-symlink-target`     — a tracked symlink whose target leaves
                                         the audited tree (absolute, escaping
                                         via `..`, unresolvable here, or inside
                                         a declared scope exclusion)

DECLARED LIMITS — read before quoting this tool as evidence:

  * A PASS is **not** proof that no third-party content was copied. Code
    copied with every marker stripped, a re-typed constant table with no
    citation, or content under a path excluded from scope (printed on every
    run) will not be detected. The tool enforces *bookkeeping*, and detects
    the carriage signals listed above; it does not perform similarity
    matching against upstream trees.
  * A PASS says nothing about whether a decision record's *reasoning* is
    right, or whether the owner has ratified it. Most records are PROPOSED.
  * The `foreign-license-text` signal reads *notices*, not licenses. Because the
    rule cannot be exempted, a false positive on our own attribution would be an
    unanswerable finding — so four boundaries are declared deliberately, each
    pinned by a control, rather than closed:
      - a LEADERLESS prose wrap of a license NAME is not matched (it is not a
        comment-block paste, and ordinary prose naming a license must not become
        a finding) — `masking/leaderless-prose-wrap-stays-out-of-scope`;
      - a yearless notice written with a bare `(c)` is not matched, because this
        repository marks enumerated legs "(a) … (b) … (c)" throughout its
        decision records and evidence reports —
        `masking/lettered-list-markers-stay-out-of-scope`;
      - a LATER segment of an otherwise-own notice line is read as naming a
        second holder only on a TWO-WORD name shape, and only before the
        segment's first sentence break. A single-token name after our own holder
        (`… 2AM Logic (generated from Verilog)`) and a name written after a full
        stop (`… 2AM Logic; see NOTICE. Chris Johnson's constants are quoted …`)
        are therefore NOT read as holders: an own aside carries at most one
        capitalised token in practice, and text after a full stop is prose, not a
        continuing holder list — `masking/single-name-aside-stays-out-of-scope`,
        `masking/prose-after-a-sentence-break-stays-out-of-scope`,
        `masking/our-own-dash-holder-with-an-aside-passes`.
    A holder list continuing past a delimiter on the SAME line, and one wrapped
    onto the next LINE, are both matched —
    `masking/second-holder-after-a-semicolon`,
    `masking/foreign-holder-on-a-wrapped-continuation-line`.
  * The two by-reference rules judge the ENTRY, not its bytes, and what they
    establish is bookkeeping only: that a submodule or an escaping symlink is
    *declared*. The referenced tree is never scanned — a declared submodule's
    contents are outside every content rule, exactly as the external pinned
    oracle is. An in-tree symlink to in-scope content is not a signal at all
    (`CLAUDE.md -> AGENTS.md` is this repository's own shape, pinned by
    `discovery/in-repo-symlink-to-a-regular-file-passes`). Because the row IS
    the description, what the row must say is now checked (increment 13): it
    must carry `class: external-reference` — the class the vocabulary and the
    manifest's own notes already named for these two rules, while any row at
    the path used to cover them — and a `pinned_commit`, which was optional,
    and whose absence also short-circuited the gitlink comparison so that
    deleting the field defeated the wrong-commit control. A declared scope
    exclusion does not hide such an entry either: it withholds CONTENT from the
    content rules, and a gitlink has none of its own, so a submodule under an
    excluded prefix is judged (and disclosed as
    `by_reference_entries_inside_declared_exclusions`, printed even when zero)
    rather than dropped before any rule sees it — the converse of the escape
    `symlink_escape()` already reports for a link INTO the same prefix. What
    stays DECLARED, not closed: for an escaping link the row is corroborated by
    nothing but itself. The resolved upstream bytes are not required to cite one
    of this repository's decision records — requiring that would mean editing
    upstream bytes, which is #25's question and not this tool's — and a verdict
    that depended on whether the external tree happened to be checked out
    locally (PASS in CI, FAIL on a developer box, same committed tree) is the
    thing increment 13 removed, not the thing it answered.
  * Content rules read three KINDS of text, and a run reports how much of the
    tree each one covered (`files_unwrapped_from_wrappers`,
    `files_scanned_as_extracted_strings`, `files_not_content_scanned`,
    `wrapper_member_names_read`):
    decoded text; a wrapper's members, unwrapped by magic (gzip/bzip2/xz
    streams, zip and tar archives, nested — so a gzipped source file, or an
    archive renamed `.dat`, is read rather than counted as opaque); and, for a
    payload that is still not text, the RUNS it carries — printable-ASCII ones,
    which is how a notice spliced into a render or a WAV `LIST/INFO` copyright
    chunk is found, and WIDE-encoded ones (UTF-16/UTF-32, either byte order,
    BOM or not), which is how a notice re-saved as "Unicode" and spliced into
    the same payload is found (increment 10; `wide_encoded_runs_harvested` is
    reported per run, so a payload whose wide runs were never examined does not
    look like one that carried none). A wrapper's member NAMES are judged too
    (increment 9), which is the only signal a marker-free member has — EVERY
    member's, including each member of a CONCATENATED gzip stream, of which
    increment 9 read only the first (increment 12). Two
    residuals here are declared, not closed, each pinned by a positive control:
      - a run harvest reads text at a fixed stride, so a notice carried in a
        TRANSFORMED encoding — base64, and any other re-coding that is not the
        bytes of its characters — stays out of reach
        (`payload/base64-encoded-notice-stays-out-of-scope`). In the NARROW
        harvest only the UTF-8 © spelling is normalised, because the bare
        Latin-1 byte occurs constantly inside PCM and float data; inside a wide
        run that byte must arrive NUL-padded within an otherwise printable
        NUL-padded run, so it is admitted there
        (`payload/wide-encoded-copyright-sign-notice`);
      - an inflation that hits the 256 MiB budget (a total over the whole
        unwrap of one entry, not a per-level ceiling) or the 4-deep wrapper
        limit is reported as a TRUNCATED payload scan on every run and in
        `--json`, which is a disclosed partial read, not a pass. A wrapper the
        audit cannot open at all (a corrupt stream) likewise yields no member
        names, and the coverage line reports how many names were read so "none
        offended" and "none examined" do not look alike.
    A PRECISION residual sits beside them: harvested runs are fed to EVERY
    rule, not only to the four carriage signals, and a bookkeeping rule is
    cheap enough for binary noise to satisfy by accident even though a license
    body is not. `RECORD_CITATION_RE` is the measured case — a real tensor in
    this tree carries a `dR` + `90459` run (fragmented here so this docstring
    is not itself a dangling citation), which reads as a citation of a
    non-existent record. The word filter (`RUN_WORD_RE`) is what keeps it
    out, and that is precision only in the sense that it drops WORDLESS runs:
    it is load-bearing for this tree's PASS, and is pinned by
    `payload/citation-shaped-noise-run-stays-clean` rather than by the tree
    alone.
    A member name is judged by the same two extension sets as a committed path,
    so a member type this repository authors (`.json`, `.hex`, `.npy`) is not a
    signal — the same boundary, and the same residual, as for a file's own name:
    an upstream member renamed to one of those is not detected here.
    Relatedly, both the encoding sniff and the wide-run harvest admit text on an
    "its characters are ASCII" test, so a UTF-16 notice written wholly in a
    non-Latin script is refused either way; license notices are ASCII English,
    and admitting everything would turn every render into garbage findings on a
    non-exemptible rule. A wide run must also be at least
    `MIN_WIDE_RUN_UNITS` code units long, the same declared floor the ASCII
    harvest applies in bytes. All four of those per-file counts describe the
    WORKING-TREE view of each entry; a second, staged view of the same entry is
    read by the same three kinds of text and counted on its own line
    (`staged_payloads_content_scanned`, increment 14), so a file whose staged
    bytes were read is not confused with one whose working copy was.
  * The audited SET is the git INDEX, not the working tree. An entry present on
    disk but not in the git index is scanned by no rule at all — until increment 11 that
    was silent, and an unattributed file carrying a GPL body, a foreign SPDX tag
    and a foreign copyright line, dropped into `model/` and left unstaged,
    audited PASS with a file count identical to the clean tree's. The boundary
    is kept, because auditing a developer's scratch files by default would put
    unanswerable findings on a non-exemptible rule, but it is no longer silent:
    every run reports `entries_present_but_not_in_the_index` (printed even when
    zero, and naming the paths, so "none present" and "never looked" do not look
    alike), and `--include-untracked` audits them as ordinary entries — which is
    how acceptance item 4's own demonstration is run against a working tree
    without staging the fixture first. Two sub-boundaries are declared with it:
    an IGNORED file is not counted and not audited either way (`.gitignore` is
    this repository's own statement that a path is not part of it, and build
    output would otherwise drown the signal —
    `coverage/gitignored-scratch-is-neither-counted-nor-audited`), and a path
    inside a declared scope exclusion is not counted here because it is already
    disclosed as a hole. What a DEFAULT run does not reach is history: whether a
    file was ever committed and later removed is outside every rule here, and is
    reachable only with `--commits` (see the last bullet).
  * An occurrence-scoped exemption is matched by LITERAL WORDING, so it cannot
    tell two identically-worded sentences apart. The rule is therefore
    uniqueness, not disambiguation: a named occurrence matching more than once
    in its file is an `exemption-ambiguous` finding (the exemption is not
    applied at all) and must be re-written with enough surrounding text to name
    one place — `scoped-exemption/duplicate-occurrence`.
  * The audited SET came from the index, but until increment 14 the audited
    BYTES came from the working tree — `root / rel`, opened with `open()`. The
    two disagree exactly when it matters: `git commit` commits the INDEX. So
    `git add` on a file carrying a GPL body, a foreign SPDX tag and a foreign
    copyright line, followed by overwriting the working-tree copy with innocuous
    text (or deleting it), audited **PASS** with coverage identical to a clean
    tree's, while the staged blob — the bytes the commit would publish — was read
    by nothing. Both byte sources are now read for any entry whose index blob is
    not known to equal its working-tree bytes: the working-tree view, because an
    unstaged paste into a tracked file must keep firing before a `git add` (that
    local run is what the audit is most used for), and the STAGED view, read from
    the index blob. A finding from the staged view says so in its evidence, since
    "the working copy is clean, the committable bytes are not" changes what the
    author must do. The divergence is reported on every run as
    `entries_whose_staged_content_differs_from_the_working_tree` (printed even
    when zero, naming the paths), with
    `staged_entries_absent_from_the_working_tree` for the subset whose only read
    is the staged one. The divergence set is git's own index-vs-working-tree
    comparison, so a difference a CRLF/clean filter introduces is not called
    divergence — and when it is, the only cost is an extra scan of the
    committable bytes. Added to it are the entries git was TOLD not to compare:
    `assume-unchanged` and `skip-worktree` both make `diff-files` report an entry
    clean however its working copy differs, so their staged bytes are read rather
    than assumed (`staged/assume-unchanged-does-not-stop-the-staged-read`). Three
    boundaries stay declared here: a gitlink has no blob in this repository, so
    its staged content is by-reference in both views exactly as before
    (`staged/a-gitlink-is-not-read-as-a-staged-blob`); a divergent path inside a
    declared scope exclusion is not counted, for the same reason increment 11
    does not count one; and a default run still reads only what the index and the
    working tree hold NOW — a blob reachable from history but from neither of
    those is read only by `--commits` (last bullet), never by a default run.
  * Increment 14 moved the carriage rules (group 4) onto both byte views. The
    ANSWERS to them did not follow, and that was the next mask: `load_manifest`
    opened `root / MANIFEST_REL` directly, and the record headers, the index
    table and the manifest corroboration all read the working-tree view. So an
    answer could be published by no commit at all — `git add` the carrier, then
    write its provenance row to `provenance.json` on disk WITHOUT staging it,
    and the audit passed with the carrier's own bytes identical in both views,
    while the commit published the carrier and a manifest that does not mention
    it. The same held for an unstaged exemption, an unstaged scope exclusion, an
    unstaged index row and an unstaged widening of a row's `covers`. Increment 15
    runs the same four groups a SECOND time with every read resolved to the
    committable bytes, and only when `decision-records/` actually diverges — so
    a tree whose bookkeeping is staged, or has no unstaged edits, takes that path
    not at all. Reported on every run as `divergent_bookkeeping_files` (printed
    even when empty, naming the paths) with `committed_answer_set_findings`, and
    a finding from that pass says the ANSWER SET is what differs, because "your
    file is undeclared" is both wrong and unactionable when the row is written
    and merely unstaged. Note the deliberate asymmetry: a carriage QUESTION is
    asked of both views, because an unstaged paste into a tracked file must fire
    before a `git add`; an ANSWER is accepted only from the view that raised the
    question, because an answer is a claim this repository publishes. Three
    boundaries stay declared: the committable tree is the index, so an untracked
    file is judged by pass one or by `--include-untracked` and never here (a
    finding against a tree no commit publishes would be noise on a
    non-exemptible rule); a record or manifest present in the index and absent
    or altered on disk is still loud in the other direction too
    (`record-header-missing`, a stale/uncorroborated row), never a silent pass;
    and in a DEFAULT run history is as far out of reach as before — a row that
    answered a carrier in some earlier commit is not consulted, and neither is one
    that will; `--commits` judges each commit against its own bookkeeping rather
    than lifting that boundary.
  * Increments 14 and 15 between them moved group 4 onto both byte views and the
    four groups' ANSWER SET onto the committable bookkeeping. Neither reached the
    two places where a BOOKKEEPING group reads an ENTRY's own content as the
    EVIDENCE for its judgement — `check_citations` (group 2) and a provenance
    row's corroboration (group 3) — and that was the next mask. Both read the
    tree's default view alone, and neither increment's trigger covers them:
    group 4 enumerates views for its own rules, and pass two fires only when
    `decision-records/` diverges, which it does not when the divergent entry is
    the CARRIER. So with bookkeeping identical in both views: `git add` the
    declared carrier with its provenance statement stripped and leave the citing
    copy on disk, and the row stayed corroborated by bytes no commit publishes;
    stage it uncited and delete the working copy, and the only bytes a commit
    publishes were read by no bookkeeping check at all (the working-tree view
    yields no text, and that answered for the staged view too); stage a citation
    of a record that does not exist and clean the working copy, and the published
    claim resolved against nothing. All three audited PASS, with the carrier
    disclosed as divergent and found clean by group 4 — correctly, since the
    staged bytes carry no carriage signal; the defect is in what answers the
    bookkeeping, not in what the bytes carry. Increment 16 reads both checks
    against every view the entry has, through the one `entry_views` definition
    group 4 now shares, and reports `staged_views_read_as_bookkeeping_evidence`
    on every run, empty included — before it, that set was always empty while the
    divergence list was not, and nothing said so. The direction is deliberately
    AND, not either: the committable bytes must carry the provenance a published
    row claims, and the working-tree copy must too, because an unstaged edit that
    strips a citation while the row stands is what a pre-commit run is for
    (`evidence/a-dangling-citation-on-disk-only-still-fires`,
    `evidence/a-stripped-provenance-statement-on-disk-only-still-fires`, which
    are exactly the controls that fail if the staged view replaces the
    working-tree one instead of joining it). Two boundaries stay declared: "no
    text in this view, so the row is the record" is now a PER-VIEW statement but
    still a boundary — a declared binary payload is corroborated by nothing in
    either view, as before, or every opaque declared asset would become a finding
    the moment its bytes were touched
    (`evidence/a-declared-binary-payloads-row-is-corroborated-in-neither-view`);
    and an escaping symlink's row is corroborated by nothing but itself in both
    views, for the reason increment 13 declared, not because of which view is
    read.
  * Every masking path closed here was found by inspection, one increment at a
    time. That two specific paths, then five, then eight, then four more were
    closed is not evidence that no further path exists — only that these are
    pinned by controls that fail when, and only when, their own fix is
    reverted. Increment 6 sat BELOW the signal layer (a file the sniff refused
    to decode was scanned by no content rule at all); increment 7 sat below
    THAT, at discovery — a committed submodule gitlink pinning the GPL engine,
    and a symlink into the external oracle tree, were both read as "undecodable
    payload" and audited clean; increment 8 went back to the payload increment 6
    had declared out of reach and found a WRAPPER (a gzipped source file, an
    archive renamed `.dat`) and an EMBEDDED notice (a WAV copyright chunk, a
    notice spliced into a float dump) hiding behind that declaration; increment
    9 did the same to increment 8's own declaration, which held that a wrapper
    whose members carry no marker is covered by the extension tripwires — it is
    not, because those judge the OUTER name, and a zip of `.wt` wavetables
    renamed `.dat` carries no marker anywhere in it; increment 10 did the same to
    increment 8's OTHER declaration, which held that a notice written in a WIDE
    encoding inside a payload was out of reach — a "Unicode" save is an ordinary
    editor default, and the run is found by its NUL padding without loosening the
    sniff at all. So the layer a masking path lives in is not bounded by the
    layers already audited, and a DECLARED limit is not evidence that the limit
    was necessary — four increments running, the next mask was inside the
    previous increment's own declared residual. Increment 11 went below
    increment 7's layer again: not how an entry is READ, but which entries are
    ENUMERATED at all — and found the one residual that had never been declared
    anywhere, because it looked like a definition of the tree rather than a
    limit on reading it. Increment 12 went back INSIDE increment 9's own fix
    rather than below it: the member-name read was complete for an archive and
    partial for a stream, because a gzip may be CONCATENATED and only the first
    member's FNAME was taken. Nothing disclosed the partial read —
    `wrapper_member_names_read` counted 1 for a two-name stream, which looks
    exactly like a one-member stream — so the tell was order-dependence, not
    coverage. Increment 13 did the same to increment 7: not whether a
    by-reference entry is FOUND (it is, and the rule fires) but whether the row
    that answers it describes anything — a row carrying no pin, or a class
    saying it carries no upstream content at all, satisfied the rule by
    existing at the path, and an exclusion prefix swallowed the entry outright.
    The tell here was neither coverage nor order but ANSWERABILITY: each of
    these trees audited clean while referencing a whole other repository, and
    one of them did so only on the machines where that repository was absent.
    Increment 14 went below increment 11 in the same direction:
    increment 11 settled WHICH ENTRIES are enumerated, and the layer under it is
    WHICH BYTES an enumerated entry is read as. Increment 7 had already moved the
    discovery rules onto the index (an entry's mode, a gitlink's pinned commit);
    the content rules never followed, so for seven increments the tool judged the
    working-tree copy while the index held what a commit would publish. The tell
    was not a finding or a count — both were identical to a clean tree's — but the
    mismatch between two layers of the same tool, one reading the index and one
    reading the disk. Increment 15 went INSIDE increment 14's own fix, the way
    increment 12 went inside increment 9's: increment 14 moved the QUESTIONS onto
    the committable bytes and left the ANSWERS on disk, so the tool was asking
    about one tree and answering from another. The tell was not order, coverage
    or answerability but SYMMETRY — increment 14's own disclosure line printed
    `decision-records/provenance.json` among the divergent entries while nothing
    read the divergent copy as an answer, and a declared residual in this very
    section asserted that the split was "safe in the one direction that matters"
    on the strength of one direction having been checked. Two of the trees that
    exposed it were not constructions at all: `_patch_manifest` had been writing
    fixture answers to disk without staging them, so two of this tool's own
    pre-existing discovery controls were passing on a row no commit published.
  * The audited SET had been walked down one axis — the working tree, the index,
    the committable bytes, the committable answers — and every one of those reads
    the repository as it stands NOW. The set nobody enumerated is the one a clone
    actually carries: every tree every commit publishes. This repository merges
    with MERGE COMMITS (squash and rebase merges are disabled on the forge), so
    every intermediate commit of every merged branch stays reachable from `main`,
    and a carrier added by one commit and deleted by a later one is published
    content that no tree audit, in any of those four views, ever reads.
    `--commits <rev-range>` (increment 17) audits each commit in a range as its
    own tree: that commit's entries (`git ls-tree -r`), that commit's blobs, and
    the ANSWERS from the `decision-records/` bookkeeping THAT COMMIT publishes —
    increment 15's asymmetry one step out, since a later commit's apology is not
    retroactive. Each finding is deduplicated per (rule, path, blob), attributed
    to the earliest commit in range that published it, and classified by its
    standing at the range tip: answered there (declared in a later commit), the
    bytes gone there, the path gone there (published then removed — the shape no
    audit of the current tree can see), or still unanswered there (the tree audit
    fails too). Five boundaries are DECLARED, not closed: (1) only the carriage
    question is asked of history — a historical commit's own index/README/row
    self-consistency is the current tree's obligation, and judging a months-old
    README table against today's conventions would bury the carriage signal under
    bookkeeping churn, so a row that grants coverage is accepted there without its
    corroboration being re-litigated; (2) the rules applied are TODAY's, so a
    finding is "what the current rule set says about bytes this history
    published", never "a violation of the rule in force at the time"; (3) a commit
    none of whose parents published a manifest has no answer set to be judged
    against and is reported as NOT judged (`commits_not_judged_no_answer_set_yet`,
    naming the commits) — in a merge-commit history that is most of a branch
    forked before the manifest landed, which is why the test is the PARENTS and
    not the calendar; deleting the manifest does not buy that silence
    (`history/deleting-the-answer-set-does-not-silence-a-commit`), and such a
    commit's own content is judged again at the merge commit that lands it; (4)
    commits OUTSIDE the given range are NOT_RUN, not clean — including everything
    a `git clone` can reach by other refs; (5) every limit above applies to each
    tree judged here, so a PASS over history is still bookkeeping, not proof that
    no third-party content was ever copied.
  * Coverage (files scanned, rows checked) is reported separately from
    agreement (findings), per `AGENTS.md`.

Self-test: `--negative-control` rebuilds a synthetic tree, injects one
deliberate violation per rule, and requires every rule to fire. A rule that
silently stops firing — the false-negative failure mode that would otherwise
pass review unnoticed — fails the self-test, and therefore CI. It also runs the
occurrence-scoped exemption controls and the `masking/*` controls, which pin
every known way the non-exemptible `foreign-license-text` rule was disarmed
without any rule being removed — our own attribution above a pasted upstream
notice, or named inside one; a foreign holder standing behind a bracketed,
parenthesised, semicolon- or dash-led mention of this project; a compound SPDX
expression led by our own licence, or one whose foreign operand sits past the
end of the parseable expression; a notice carrying a holder but no year; a
holder list continuing past a delimiter on the same line, or wrapped onto a
continuation line; a license body wrapped across a comment leader — together
with the positive cases that keep the fixes from flagging our own headers or
ordinary prose. The `discovery/*` controls do the same for the layer below:
a committed gitlink, a nested repository in a non-git tree, an escaping
symlink, a gitlink inside a declared scope exclusion, and either by-reference
entry answered by a row of the wrong class or by a row with no `pinned_commit`
must each produce a finding, a declared one must not — including an excluded
gitlink, whose finding has to be answerable where it fires, and a declared
escaping link, which must pass identically whether or not its external target
resolves on the machine running the audit — and a plain
in-tree symlink must stay clean. The `payload/*` controls cover the layer below
THAT: a license body inside a gzip/bzip2/xz stream, a zip or tar renamed
`.dat`, a wrapper nested inside a wrapper, an `.npz` member, a WAV `ICOP`
copyright chunk, a notice spliced into a float dump and one written with the
sign spelling must each produce a finding; so must the same notice re-encoded
UTF-16-LE, UTF-16-BE, UTF-32-LE, UTF-32-BE, BOM-led inside a real render's data
chunk, inside a wrapper member, and written with the sign spelling in a wide run
(increment 10) — while a real PCM render, a QUIET one (whose every sample is a
low byte beside a NUL, the byte shape a UTF-16-LE string also has), a float
dump, an `.npy` tensor and this repository's own gzipped JSON trace must all
stay clean, because a false positive on one of those would be unanswerable on a
rule that cannot be exempted. The `wrapper/*` controls cover the NAMES inside those same
wrappers, where no content signal exists to find: a `.wt` member in a zip
renamed `.dat`, a stripped `.cpp` in a tar, a gzip whose FNAME header is its
only name, the SECOND member of a concatenated gzip whose FNAME names a `.wt`
(increment 12), an asset member two wrappers deep, and a `.wt` member that is
itself a gzip (whose outer name must not be masked by the inner one) must each
produce a finding; a row declaring `covers` must clear it and the same row WITHOUT
`covers` must not; and this repository's own gzipped trace carrying an FNAME,
plus an `.npz` of `.npy` members, must stay clean. The `coverage/*` controls
(increment 11) are the only ones that assert on COVERAGE rather than on
findings, because the default behaviour they pin is deliberately "produce no
finding": an unstaged, unattributed carrier must be NAMED in
`entries_present_but_not_in_the_index` and must not be flagged; a fully staged
tree must still print the count, as zero; an ignored path and one inside a
declared scope exclusion must be neither counted nor audited; a non-git tree
(where every file is walked) must report zero AND still flag the carrier; and
under `--include-untracked` the same carrier must produce a
`foreign-license-text` finding while the ignored path stays out. The `staged/*`
controls (increment 14) assert on findings AND coverage together, because the
increment has two halves that must both hold: a carrier staged and then cleaned
on disk, one staged and then deleted, one hidden behind `assume-unchanged`, and a
staged wrapper whose member NAME is the only signal must each produce a finding
that NAMES the staged content as its source; while an unstaged paste into a
tracked file must still fire as a working-tree finding (reverting the
working-tree read in favour of the index read fails exactly this one), a fully
staged tree must print the count as zero, an ordinary innocuous edit must be
counted and read but never flagged, a divergence inside a declared scope
exclusion must be neither counted nor read, and a gitlink must stay a
by-reference entry rather than becoming a staged blob. The `committed/*`
controls (increment 15) do the same for the ANSWER SET: a provenance row written
to disk and not staged, an existing row deleted from the index only, an unstaged
exemption, an unstaged scope exclusion, an unstaged index row and an unstaged
widening of a row's `covers` must each produce a finding that NAMES the
committable answer set as its source; so must a manifest `git rm --cached` left
on disk, where the committable answer set is nothing at all (the one shape whose
trigger is the untracked leg rather than the divergence leg, and the only one
that fails when the read-from-disk sentinel is spelled `None`); while the same
row staged as well must stay silent (otherwise the increment is a tool nobody can
use), a fully staged tree must print the list as empty, an ordinary file's
divergence must not open a second answer set at all, and a bookkeeping edit that
changes no answer must be disclosed and produce nothing. The `evidence/*`
controls (increment 16) do it once more for the EVIDENCE a bookkeeping judgement
reads out of an entry, where the bookkeeping itself agrees in both views so the
committed pass never runs: a declared carrier staged with its provenance
statement stripped, the same one staged uncited and then deleted from disk (whose
working-tree view yields no text, which used to answer for the staged bytes too),
and a citation of a nonexistent record staged and then cleaned off disk must each
produce a finding that NAMES the staged content AND be reported in
`staged_views_read_as_bookkeeping_evidence`; while the same two defects written
on DISK only must keep firing unlabelled (these are the two that fail if the
staged view replaces the working-tree one), a divergent carrier that states its
provenance in both views must be read in both and flagged in neither, and a
declared binary payload — which has no text in either view — must be disclosed,
not read, and not flagged. The `history/*` controls (increment 17) are the only
ones that build real COMMITS, because the behaviour under test has no
representation outside a commit graph, and each one asserts on BOTH audits: the
tree audit of the final checkout must be CLEAN (otherwise the case proves
nothing about history) while the history audit must fire. A GPL body added by one
commit and deleted by the next, an upstream-asset EXTENSION in the same shape (it
is the structural half, and a primary-view gate spelled `== WORKTREE_VIEW` makes
every extension and by-reference rule unreachable in a commit tree), an escaping
symlink whose target has to be read from the commit's own blob, a carrier
declared one commit LATE, and the same bytes republished at a path with a
different extension must each produce a finding naming the commit; while a
carrier declared in the SAME commit as its row, and an in-repo symlink to in-scope
content (resolving it against the checkout instead of the commit invents a finding
on a non-exemptible rule), must produce none; a commit that DELETES the manifest
alongside its carrier must be judged with no answers and have that deletion
disclosed; a commit older than the first manifest must be disclosed as NOT judged
rather than flagged; and a range that resolves to no commits must be an error, not
an empty PASS.

Usage:
    python3 tools/check_provenance.py                # audit this repository
    python3 tools/check_provenance.py --root DIR     # audit another tree
    python3 tools/check_provenance.py --json         # machine-readable report
    python3 tools/check_provenance.py --include-untracked   # audit unstaged files too
    python3 tools/check_provenance.py --commits origin/main..HEAD  # published history
    python3 tools/check_provenance.py --negative-control

Exit codes: 0 = PASS, 1 = findings (FAIL), 2 = the audit itself could not run
(or a negative control did not fire).

Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The audit itself lives in nine sibling modules (a behavior-preserving
# split; no rule, message or output line changed). This file is the CLI and
# the import surface every existing caller already uses: the names below are
# re-exported so `import check_provenance` keeps resolving all of them,
# including the 22 that the byte-frozen `check_provenance_controls` imports.
from check_provenance_driver import (  # noqa: F401
    TIP_ABSENT,
    TIP_ANSWERED,
    audit,
    audit_history,
    report,
    report_history,
)
from check_provenance_manifest import (  # noqa: F401
    FROM_DISK,
    load_manifest,
    scope_exclusion_prefixes,
)
from check_provenance_payload import (  # noqa: F401
    COPYRIGHT_SIGN_CHAR,
    GZIP_MAGIC,
    MAX_UNWRAPPED_BYTES,
    MEMBER_JOIN,
    PRINTABLE_RUN_RE,
    RUN_WORD_RE,
    _InflationBudget,
    _gzip_header_name,
    _gzip_members,
    _wide_runs,
    harvest_payload,
    harvest_strings,
    sniff_encoding,
    unwrap_payload,
)
from check_provenance_records import (  # noqa: F401
    parse_index,
    parse_records,
    status_keyword,
)
from check_provenance_register import (  # noqa: F401
    QUOTED_RECORD_RE,
    REGISTER_EXCEPTION_COLUMNS,
    REGISTER_EXCEPTION_SECTION,
    REGISTER_EXCLUSION_COLUMNS,
    REGISTER_EXCLUSION_SECTION,
    REGISTER_GPL_SECTION,
    REGISTER_INCOMPLETE_REVISION,
    REGISTER_MIT_SECTION,
    REGISTER_REL,
    REGISTER_REVISION_RE,
    REGISTER_ROW_COLUMNS,
    check_register,
    parse_register,
)
from check_provenance_rules import (  # noqa: F401
    BY_REFERENCE_CLASS,
    INDEX_REL,
    KNOWN_CLASSES,
    MANIFEST_REL,
    RECORD_DIR_REL,
    REPO_ROOT,
    RULES,
    SCHEMA_VERSION,
    TRIPWIRE_RULES,
)
from check_provenance_signals import (  # noqa: F401
    AuditError,
    CAVEAT,
    RECORD_CITATION_RE,
    foreign_copyright_match,
    occurrence_regex,
    own_copyright_holder,
    spdx_foreign_ids,
)
from check_provenance_tree import (  # noqa: F401
    COMMITTED_VIEW,
    STAGED_VIEW,
    Tree,
    WORKTREE_VIEW,
    entry_views,
    list_entries,
    list_staged_divergent,
    list_untracked,
    parse_gitmodules,
    read_index_blob,
)
from check_provenance_tripwires import (  # noqa: F401
    _extension_suffix,
    _snippet,
    member_name_signals,
    symlink_escape,
    tripwire_hits,
)


# --- cli ---------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", default=str(REPO_ROOT), help="tree to audit (default: this repository)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument(
        "--negative-control",
        action="store_true",
        help="self-test: every rule must fire on a deliberate violation",
    )
    parser.add_argument(
        "--limits", action="store_true", help="print the declared detection limits"
    )
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help=(
            "also audit entries present in the working tree but not in the git "
            "index (ignored files still excluded); the default audits the index "
            "only and discloses the count it skipped"
        ),
    )
    parser.add_argument(
        "--commits",
        metavar="REV-RANGE",
        help=(
            "audit the PUBLISHED HISTORY of a commit range (e.g. "
            "origin/main..HEAD) instead of the working tree: every commit's own "
            "tree, judged against the provenance bookkeeping that same commit "
            "publishes — which is the only way a carrier added in one commit and "
            "deleted in a later one is seen at all"
        ),
    )
    args = parser.parse_args(argv)

    if args.limits:
        print(__doc__)
        return 0
    if args.negative_control:
        from check_provenance_controls import run_negative_control

        return run_negative_control()
    if args.commits:
        try:
            findings, stats = audit_history(Path(args.root), args.commits)
        except AuditError as exc:
            print(f"NOT_RUN: provenance history audit could not run: {exc}")
            print(CAVEAT)
            return 2
        report_history(findings, stats, args.root, as_json=args.json)
        return 1 if findings else 0

    try:
        findings, stats = audit(Path(args.root), include_untracked=args.include_untracked)
    except AuditError as exc:
        print(f"NOT_RUN: provenance audit could not run: {exc}")
        print(CAVEAT)
        return 2
    report(findings, stats, args.root, as_json=args.json)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
