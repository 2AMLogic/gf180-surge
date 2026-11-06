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
import base64
import bz2
import codecs
import gzip
import io
import json
import lzma
import os
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_REL = "decision-records/provenance.json"
INDEX_REL = "decision-records/README.md"
RECORD_DIR_REL = "decision-records"

SCHEMA_VERSION = 1

# The class a row MUST carry to answer either by-reference rule
# (`submodule-reference`, `external-symlink-target`). Named rather than spelled
# inline because the tie is now enforced: before increment 13 any row at the
# exact path covered those two rules whatever its class said, so a row declaring
# it "restates an upstream attribution, carries no upstream content" silently
# answered a committed GPL engine checkout — while this file's own vocabulary
# and `decision-records/provenance.json`'s notes both described
# `external-reference` as required. One of the two had to move; the wording was
# right, so the code moved (control
# `discovery/gitlink-answered-by-a-row-of-the-wrong-class`).
BY_REFERENCE_CLASS = "external-reference"

# Every provenance row must cite a decision record: "Nothing is adopted
# without a recorded decision in #25" (docs/REUSE-AUDIT.md, standing rules).
KNOWN_CLASSES = {
    # engine/third-party data constants quoted into this repository
    "quoted-constants": "third-party data constants quoted as data",
    # identity (path/hash/dims) of an external asset whose payload stays out
    "external-asset-identity": "external asset identity only, payload external",
    # original source here that compiles against pinned third-party headers
    "api-client-harness": "original source built against pinned upstream headers",
    # in-repo tooling that drives an externally built/patched upstream binary
    "external-build-client": "drives an externally built upstream binary",
    # a file copied from a third party (pinned, attributed, license recorded)
    "vendored-copy": "file copied from a third-party source",
    # our own prose that restates an upstream copyright/license attribution
    # (e.g. the libs/airwindows MIT notice, restated by DR-0015) while
    # carrying no third-party code, table or asset. Covers nothing implicitly:
    # the row must list the tripwire in 'covers' and cite its record.
    "attribution-statement": "restates an upstream attribution, carries no upstream content",
    # a tree entry that carries its content BY REFERENCE rather than in its own
    # bytes: a committed submodule gitlink, or a symlink whose target leaves
    # the audited tree. The referenced content is in the build tree but not in
    # this audit, so the row (and its record) is the only description of it.
    # REQUIRED (not merely advertised) for `submodule-reference` and
    # `external-symlink-target`, and the only class for which `pinned_commit`
    # is mandatory: with no bytes to read, the pin is the whole description.
    BY_REFERENCE_CLASS: "a by-reference link to content outside this tree",
}

# --- rule ids -----------------------------------------------------------------

RULES = {
    # group 1: decision-record index integrity
    "index-missing-row": "decision record on disk with no index row",
    "index-unknown-record": "index row whose record file does not exist",
    "index-duplicate-row": "decision record listed more than once in the index",
    "index-status-mismatch": "index status keyword differs from the record",
    "index-date-mismatch": "index date differs from the record",
    "index-number-gap": "gap in the decision-record numbering",
    "record-status-unrecognized": "record status keyword outside the vocabulary",
    "record-header-missing": "record without a parseable Status/Date header",
    # group 2: citation integrity
    "dangling-record-citation": "citation of a decision record that does not exist",
    "unindexed-record-citation": "citation of a record missing from the index",
    # group 3: provenance manifest integrity
    "manifest-missing": "provenance manifest absent or unreadable",
    "manifest-schema": "provenance manifest schema problem",
    "manifest-field-missing": "provenance row missing a required field",
    "manifest-unknown-class": "provenance row with an unknown class",
    "manifest-stale-path": "provenance row whose path matches no file",
    "manifest-bad-pattern": "provenance row pattern too broad or malformed",
    "manifest-missing-record": "provenance row citing a nonexistent record",
    "manifest-unindexed-record": "provenance row citing an unindexed record",
    "manifest-uncorroborated": "file does not corroborate its provenance row",
    "exemption-field-missing": "exemption missing a required field",
    "exemption-non-exemptible-rule": "exemption of a non-exemptible rule",
    "exemption-stale": "exemption matching no file",
    "exemption-ambiguous": "exemption occurrence matching more than one place",
    "exemption-bad-pattern": "exemption pattern too broad or malformed",
    "scope-exclusion-stale": "declared scope exclusion matching no file",
    "scan-underflow": "fewer files scanned than the manifest's declared floor",
    # group 3b: GPL-boundary register cross-check (issue #370)
    "register-missing": "GPL-boundary register absent, unreadable or without its tables",
    "register-malformed-row": "register row with a missing/invalid field or wrong shape",
    "register-missing-row": (
        "quoted-constants provenance row with no GPL-boundary register row"
    ),
    "register-unmapped-row": (
        "register row whose citation maps to no provenance row or exception"
    ),
    "register-licence-mismatch": (
        "register licence disagrees with its table or its provenance row"
    ),
    "register-exception-stale": "register exception that is unused, unjustified or stale",
    "register-record-unaccounted": (
        "decision record declaring quoted data that the register neither lists nor excludes"
    ),
    # group 4: undeclared-carrier tripwires
    "foreign-license-text": "foreign license/copyright text without a provenance row",
    "upstream-asset-extension": "upstream asset / opaque bundle without a provenance row",
    "foreign-source-language": "foreign-language source file without a provenance row",
    "wrapper-member-name": (
        "wrapper carrying an upstream-asset / foreign-source member NAME "
        "without a provenance row"
    ),
    "self-declared-quotation": "self-declared quotation without a provenance row",
    "submodule-reference": "committed submodule / nested repository without a provenance row",
    "external-symlink-target": "symlink whose target leaves the audited tree without a provenance row",
}

TRIPWIRE_RULES = (
    "foreign-license-text",
    "upstream-asset-extension",
    "foreign-source-language",
    "wrapper-member-name",
    "self-declared-quotation",
    "submodule-reference",
    "external-symlink-target",
)

# Only the prose-marker tripwire may be exempted: a document may *discuss*
# quotation without carrying anything. A foreign license body, an upstream
# asset payload, or foreign-language source must be answered by a real
# provenance row — never by an exemption.
EXEMPTIBLE_RULES = frozenset({"self-declared-quotation"})

STATUS_VOCABULARY = (
    "ratified",
    "accepted",
    "proposed",
    "escalated",
    # "RECORDED" / "RECORDED CONTRACT REVISION": a decision in force at its
    # enforcement point with owner ratification still pending (DR-0013,
    # DR-0016). Distinct from "ratified"; never read as a ratification.
    "recorded",
    "superseded",
    "withdrawn",
    "rejected",
)

# --- content signals ----------------------------------------------------------

# Third-party trees this repository cites but must not carry. The pinned Surge
# commit is the one in AGENTS.md; the substrate names come from the reuse
# survey (docs/REUSE-AUDIT.md). Matched as lowercase substrings.
UPSTREAM_CITATION_PREFILTERS = (
    "58914e59c608ed4384ba6002e44c3465c58b2e71",
    "surge-synthesizer/surge",
    "sst-basic-blocks",
    "sst-effects",
    "sst-filters",
    "airwindows",
    "airwin",
    "torchsynth",
    "parasynth",
    "klayout-tools",
)

# The repository's own vocabulary for "this is upstream data, not our work".
# (name, lowercase prefilter, confirming regex) — the prefilter must be a
# superset of what the regex can match.
QUOTATION_MARKER_RES = (
    ("quoted-as-data", "quoted as ", re.compile(r"quoted as (?:cited )?data", re.IGNORECASE)),
    ("QUOTED", "quoted", re.compile(r"\bQUOTED\b")),
    ("transcribed-from", "transcribed", re.compile(r"transcribed from", re.IGNORECASE)),
    (
        "copied-verbatim",
        "verbatim",
        re.compile(r"copied verbatim|verbatim cop(?:y|ied)", re.IGNORECASE),
    ),
    ("vendored", "vendor", re.compile(r"\bvendored?\b", re.IGNORECASE)),
)


def quotation_marker_matches(text):
    """Every quotation-marker occurrence in `text` as [(name, match)], in order.

    `tripwire_hits` stops at the first marker (one hit per file is enough to
    raise the rule); an occurrence-scoped exemption needs all of them, so that
    a file whose one named occurrence is exempt still fails on any other.
    """
    low = text.lower()
    found = []
    for name, prefilter, regex in QUOTATION_MARKER_RES:
        if prefilter in low:
            found.extend((name, match) for match in regex.finditer(text))
    return sorted(found, key=lambda item: item[1].start())


def occurrence_regex(literal):
    """Whitespace-insensitive matcher for an exemption's named occurrence."""
    return re.compile(r"\s+".join(re.escape(part) for part in literal.split()))

# A pasted license header is a COMMENT block, so any gap between two words of
# its body may carry the block's comment leader:
#
#     #  This program is free
#     #  software; you can redistribute it
#      *  GNU GENERAL
#      *  PUBLIC LICENSE Version 3
#
# A plain `\s+` between the words does not span `"\n#  "`, so every phrase that
# a vendored file happens to wrap mid-phrase slipped past this signal — on the
# rule that cannot be exempted. `_GAP` therefore accepts either same-line
# whitespace or a line break whose continuation begins with a comment leader.
#
# It deliberately does NOT accept a bare prose wrap ("the GNU General Public\n
# License"): a leaderless newline stays unmatched so that ordinary in-repo
# prose naming a license does not become a finding that no exemption could
# answer. What is closed here is the *commented-header* shape, which is how
# license bodies actually arrive in a copied file.
_LEADER = r"[*#;%!>|]+|//+|--+|<!--"
_GAP = r"(?:[ \t]+|[ \t]*\r?\n[ \t]*(?:" + _LEADER + r")[ \t]*)"


def _license_phrase(*parts):
    """Compile a license-body phrase whose word gaps tolerate comment leaders."""
    return re.compile(_GAP.join(parts), re.IGNORECASE)


# The license-body patterns are split across string fragments on purpose: a
# contiguous license phrase in this file would make the audit flag its own
# source (the rule is not exemptible, by design). See the fixture note further
# down. Do not "tidy" these into single literals.
#
# Each prefilter is a SINGLE word the regex cannot match without — a superset
# by construction, and unlike a multi-word prefilter it stays a superset once
# the phrase may be interrupted by a comment leader (a "general public license"
# prefilter silently un-armed the leader-interrupted match).
FOREIGN_LICENSE_BODY_RES = (
    (
        "gpl-body",
        "gnu",
        _license_phrase(
            "GNU", r"(?:LESSER" + _GAP + r"|AFFERO" + _GAP + r")?GENERAL", "PUBLIC", "LICENSE"
        ),
    ),
    (
        "fsf-body",
        "free",
        _license_phrase("This", "program", "is", "free", "software"),
    ),
    (
        "mit-body",
        "hereby",
        _license_phrase(
            "Permission", "is", "hereby", r"granted,", "free", "of", "charge"
        ),
    ),
    (
        "bsd-body",
        "redistribution",
        _license_phrase(
            "Redistribution", "and", "use", "in", "source", "and", "binary", "forms"
        ),
    ),
    (
        # Prefilter deliberately just "mozilla": a case-insensitive regex
        # matches its own lowercase prefilter if the prefilter spells out the
        # whole phrase.
        "mpl-body",
        "mozilla",
        _license_phrase("MOZILLA", "PUBLIC", "LICENSE"),
    ),
)

# Assembled from fragments so this file does not itself contain a contiguous
# SPDX tag (see the fixture note below). IGNORECASE: the prefilter above is a
# lowercase substring check, so an all-lowercase spelling of the tag name must
# not silently pass this regex — see PR #114 review, finding 2. (That prefilter
# is spelled without its colon here on purpose: with the capture widened to the
# rest of the line, a colon in this comment would make the audit read the words
# after it as an SPDX expression and flag its own source.)
#
# The capture is the REST OF THE LINE, not the first whitespace-delimited word:
# an SPDX tag carries a license *expression*, and a tag whose leading operand
# happens to be our own licence hid every other operand behind it
# ("Apache-2.0 OR GPL-3.0-or-later" audited clean — the standard dual-licence
# shape). `spdx_foreign_ids` parses the expression instead.
SPDX_RE = re.compile(
    "SPDX-License" "-Identifier" + r":[ \t]*([^\r\n]*)", re.IGNORECASE
)
OWN_SPDX = "apache-2.0"
SPDX_OPERATORS = frozenset({"and", "or", "with"})
# An SPDX id token; also strips the comment syntax a tag may trail in
# ("... Apache-2.0 */", "... MIT -->").
SPDX_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")

# License-id families this repository does not license under, recognised by
# SHAPE. The expression walk below stops at the first token that is not part of
# a parseable `id (OPERATOR id)*` expression — deliberately, so that our own tag
# quoted inside a sentence does not read the following prose as operands. That
# stop is also a mask: a foreign operand smuggled past the end of the parseable
# expression was invisible, and these tag VALUES all audited clean (the tag name
# itself is omitted here so this comment is not read as a tag — see the fixture
# note further down) —
#
#     Apache-2.0, GPL-3.0-or-later
#     Apache-2.0 / GPL-3.0-or-later
#     Apache-2.0 (upstream GPL-3.0-or-later)
#
# — a comma list, a slash list, and a parenthetical, none of them exotic. The
# remainder of the tag is therefore scanned for a license id by shape, which
# prose cannot satisfy ("Apache-2.0 tags are used below" stays clean).
FOREIGN_LICENSE_ID_RE = re.compile(
    r"\b(?:(?:A|L)?GPL|MPL|EPL|CDDL|CPL|OSL|AFL|EUPL|BSL|ISC|NCSA|WTFPL"
    r"|Artistic|Zlib|Unlicense|Sleepycat|CC-BY[A-Za-z0-9.-]*"
    r"|BSD-[0-9]+-Clause[A-Za-z0-9.-]*|MIT)"
    r"(?:-[0-9]+(?:\.[0-9]+)*)?(?:-or-later|-only|\+)?\b",
    re.IGNORECASE,
)


def spdx_foreign_ids(expression):
    """License ids in an SPDX expression that are not this repository's own.

    Walks the expression as `id (OPERATOR id)*` and stops at the first token
    that is neither an operator nor an id in operator position — so a tag
    quoted mid-sentence (one whose operand is followed by prose such as "tags
    are used below") contributes only its real operand, while every operand of
    a compound expression is examined:

        Apache-2.0                        -> []                (ours)
        Apache-2.0 OR GPL-3.0-or-later    -> ['GPL-3.0-or-later']
        (MIT AND Apache-2.0)              -> ['MIT']
        Apache-2.0 WITH LLVM-exception    -> ['LLVM-exception'] (over-flagged
                                             on purpose: an exception clause is
                                             foreign licence text too)

    Whatever follows the parseable expression is then scanned for a license id
    BY SHAPE (`FOREIGN_LICENSE_ID_RE`), so that a foreign operand hidden behind
    a comma, a slash or a parenthetical is not lost with the rest of the line:

        Apache-2.0, GPL-3.0-or-later      -> ['GPL-3.0-or-later']
        Apache-2.0 (upstream MIT)         -> ['MIT']
        Apache-2.0 tags are used below    -> []                  (prose)
    """
    normalized = expression.replace("(", " ").replace(")", " ")
    foreign = []
    expect_id = True
    consumed = 0
    for match in SPDX_TOKEN_RE.finditer(normalized):
        token = match.group(0)
        lowered = token.lower()
        if expect_id:
            if lowered in SPDX_OPERATORS:
                break  # malformed; stop rather than guess
            if lowered != OWN_SPDX:
                foreign.append(token)
            expect_id = False
        else:
            if lowered not in SPDX_OPERATORS:
                break  # end of the expression (trailing prose or comment)
            expect_id = True
        consumed = match.end()
    for match in FOREIGN_LICENSE_ID_RE.finditer(normalized[consumed:]):
        if match.group(0).lower() != OWN_SPDX:
            foreign.append(match.group(0))
    return foreign


COPYRIGHT_PREFILTERS = ("copyright", "(c)", "©")

COPYRIGHT_RE = re.compile(
    r"(?:Copyright|\(c\)|©)\s*(?:\(c\)\s*|©\s*)?(?:19|20)\d\d",
    re.IGNORECASE,
)
OWN_HOLDER_RE = re.compile(r"2AM\s*Logic|2AMLogic|gf180-surge", re.IGNORECASE)

# A notice that names a holder but NO year — the keyword, or the © sign, run
# straight into a holder name with no year between them. `COPYRIGHT_RE` requires
# a year, so a yearless pasted notice carried no signal at all. (Spelled out in
# the `masking/*` fixtures rather than here: a contiguous example in this comment
# would make the audit flag its own source — see the fixture note further down.)
#
# Deliberately NOT matched from a bare "(c)": this repository marks enumerated
# list items "(a) … (b) … (c)", and "(c) Tables" / "(c) Unknown status string"
# are everywhere in the decision records and evidence reports. Matching those
# would make ordinary lettered lists findings on a rule that CANNOT be exempted
# — an unanswerable failure, which is how a rule gets switched off. The
# remaining gap (a yearless notice written with a bare "(c)") is a declared
# limit, not an oversight.
#
# Case-sensitive on purpose: the lookahead requires a capitalised holder name,
# which IGNORECASE would silently widen to any letter.
YEARLESS_COPYRIGHT_RE = re.compile(
    r"(?:[Cc]opyright|COPYRIGHT|©)[ \t]*(?:\([cC]\)|©)?[ \t]*(?=[A-Z])"
)
# Capitalised words that follow the keyword in PROSE about copyright rather than
# in a notice ("Grant of Copyright License", "the Copyright Notice is retained").
# A notice whose holder position holds one of these is not read as a notice.
NOT_A_HOLDER_WORDS = frozenset(
    {
        "license", "licence", "licenses", "licences", "licensing", "notice",
        "notices", "act", "office", "holder", "holders", "owner", "owners",
        "law", "statement", "statements", "year", "years", "header", "headers",
        "line", "lines", "text", "texts", "assignment", "registration",
        "information", "and", "or", "in", "is", "are", "the",
    }
)

# A holder list may WRAP: the notice names us, and the next comment line names
# someone else with no keyword of its own — our own notice, then a second line
# reading `#     and Chris Johnson / Airwindows` (the notice line itself is in
# the `masking/*` fixtures, not here — see the fixture note further down).
#
# That layout audited clean because the second line carries no notice keyword. Kept
# deliberately narrow (a conjunction, then a capitalised name) so that ordinary
# comment prose under an own notice is not a finding on the non-exemptible rule.
HOLDER_CONTINUATION_RE = re.compile(
    r"^[ \t]*(?:" + _LEADER + r")?[ \t]*(?:and|&|,)[ \t]+(?=[A-Z])"
)


def copyright_line(text, match):
    """The single line carrying `match` — the only place its holder may be read.

    A copyright notice names its holder on its own line. Testing a ±120-char
    *window* around the match instead (what this did before) means any nearby
    mention of this project — an own header line above a pasted upstream
    header, or a prose "gf180-surge" a few words away — reads as "this holder
    is us" and silently disarms the non-exemptible `foreign-license-text`
    rule. Scoped to the line, an own notice still suppresses itself and a
    foreign notice beside it still fires (controls `masking/*`).
    """
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    return text[start : len(text) if end == -1 else end]


# Text that ends a copyright line's HOLDER field: a holder name does not
# contain a parenthetical, a bracketed note, an em/en dash aside, a spaced
# hyphen, a semicolon, a quotation mark, an inline URL, or a closing comment
# delimiter. (The quotation marks matter because a notice QUOTED inside prose —
# as several of this file's own comments do — would otherwise read the prose
# after the closing quote as part of its holder field.)
HOLDER_FIELD_END_RE = re.compile(r"[(\[{<;—–\"“”]| - |\*/|-->|https?://")
# Filler that may legitimately precede the holder's own name inside the holder
# field ("Copyright (c) 2026 The gf180-surge Authors"). Anything else standing
# where the holder belongs means the notice names SOMEONE ELSE first.
HOLDER_LEADING_FILLER = frozenset({"the", "by", "c", "and", "of", "for"})
HOLDER_WORD_RE = re.compile(r"[A-Za-z][A-Za-z.'’]*")
# A capitalised token is how a SECOND holder shows up next to our own name
# ("[gf180-surge] Some Upstream Author"). These are the capitalised words that
# are NOT a second holder: collective suffixes and corporate forms our own
# notice legitimately carries. Everything else capitalised, standing in the
# same holder field as our name, means the notice names someone else too.
HOLDER_NAME_RE = re.compile(r"[A-Z][A-Za-z.'’]*")
HOLDER_NEUTRAL_WORDS = HOLDER_LEADING_FILLER | frozenset(
    {
        "author", "authors", "contributor", "contributors", "developer",
        "developers", "maintainer", "maintainers", "project", "team",
        "inc", "llc", "ltd", "gmbh", "sa", "bv", "co",
        "all", "rights", "reserved", "see", "or",
        # legal boilerplate an own notice trails, never a holder name
        "license", "licence", "licenses", "licences", "licensed", "notice",
        "notices", "terms", "spdx", "apache",
    }
)


def _holder_word_key(word):
    """A holder word reduced to its vocabulary key.

    The word regexes admit a trailing abbreviation dot so that "Inc." reads as
    one token, which means the raw token ("Reserved.", "License.") does not
    compare equal to its vocabulary entry. Without this, "2AM Logic, All Rights
    Reserved." became a finding on the non-exemptible rule — a false positive on
    our OWN notice, which is how this rule gets switched off.
    """
    return word.lower().strip(".'’")


# A holder list may also continue past a delimiter on the SAME line, after a
# segment that names us: `… 2AM Logic; Some Upstream Author`, `… 2AM Logic
# (derived from Chris Johnson / Airwindows)`. `own_copyright_holder` judged the
# FIRST segment holding a name and returned, so everything past that delimiter
# was never read — the same stop-as-soon-as-our-own-name-is-recognised shape as
# the earlier increments, one segment to the right. (The notice lines themselves
# are in the `masking/*` fixtures, not here — see the fixture note further down.)
#
# A later segment is read as naming a second holder only on a TWO-WORD name
# shape (two consecutive capitalised, non-neutral tokens), and only before the
# segment's first sentence break. Both bounds exist because this rule cannot be
# exempted, so a false positive on our own notice is unanswerable:
#
#   * an own aside carries at most one capitalised token in practice
#     (`(SXT-019 governance)`, `(All Rights Reserved)`, `(see NOTICE)`), whereas a
#     holder name is two or more (`Chris Johnson`, `Some Upstream Author`);
#   * text after a full stop is prose, not a continuing holder list — our own
#     notice quoted inside a sentence is followed by exactly that
#     (`… The gf180-surge Authors". Anything else names someone else.`).
#
# The residual limits are declared, pinned by positive controls, and NOT closed:
# a single-token second holder in a later segment (`(portions Airwindows)`), and
# a second holder written after a sentence break.
SENTENCE_BREAK_RE = re.compile(r"[.!?](?=[ \t]|$)")


def _second_holder_name(field):
    """True when a later segment of an own notice line names a SECOND holder.

    Called only for segments standing after the one that named us, so our own
    name is excised first ("2AM Logic (2AM Logic internal)" stays ours).
    """
    scrubbed = OWN_HOLDER_RE.sub(" ", field)
    sentence_break = SENTENCE_BREAK_RE.search(scrubbed)
    if sentence_break:
        scrubbed = scrubbed[: sentence_break.start()]
    run = 0
    for match in HOLDER_WORD_RE.finditer(scrubbed):
        word = match.group(0)
        if HOLDER_NAME_RE.match(word) and _holder_word_key(word) not in HOLDER_NEUTRAL_WORDS:
            run += 1
            if run > 1:
                return True
        else:
            run = 0
    return False


def _holder_segments(tail):
    """The holder field, then each later segment of the line, in order.

    A holder name does not span one of `HOLDER_FIELD_END_RE`'s delimiters, so
    the holder field is the first segment — but a layout that opens with a
    delimiter ("Copyright 2026 - 2AM Logic", "Copyright 2026 (2AM Logic)")
    leaves that first segment empty of names, and the holder is in the next
    one. Walking segment by segment is what replaced falling back to the WHOLE
    LINE: that fallback reintroduced, for exactly these layouts, the
    whole-line masking this function exists to prevent (a foreign notice whose
    year is followed by `[gf180-surge] Some Upstream Author` audited clean).
    """
    return HOLDER_FIELD_END_RE.split(tail)


def own_copyright_holder(line, holder_start):
    """True when the notice at `holder_start` in `line` names THIS project.

    The holder is the name standing immediately after the year, so that is the
    only text consulted. Searching the whole LINE for our name instead (what
    this did before) means a pasted upstream notice that merely *mentions* this
    project suppresses itself — the same masking bug as the old ±120-char
    window, one level in. Two shapes audited clean on the non-exemptible rule:
    a notice whose year is followed by

        Some Upstream Author (adapted for gf180-surge)
        Chris Johnson - vendored for gf180-surge

    — this project named in a parenthetical, and after a spaced hyphen. Read as
    a holder field the holders are Some Upstream Author and Chris Johnson, and
    both fire.

    Our name standing in the holder position is not sufficient on its own: the
    holder field must name NOBODY ELSE. Five notices audited clean until that
    second condition landed, because our name came first in each of them — the
    text after the year was

        [gf180-surge] Some Upstream Author
        (gf180-surge port) Some Upstream Author
        <gf180-surge> Chris Johnson
        ; gf180-surge adaptation of Chris Johnson's filter
        — gf180-surge vendoring of Chris Johnson

    and each one opens with a delimiter, so the holder field itself held no name
    and the old code fell back to searching the WHOLE line. (Only the holder
    field is shown, not the whole notice: a contiguous notice in this file would
    make the audit flag its own source — see the fixture note further down.)

    Our own header (our name, or "The gf180-surge Authors", standing in the
    holder position) still suppresses itself: a rule that flagged our own
    attribution would simply be switched off again — and because this rule
    cannot be exempted, a false positive here is an unanswerable finding. That
    is why the test is scoped to ONE segment of the line: an own notice trailed
    by an aside or a cross-reference ("… 2AM Logic — see NOTICE") keeps naming
    only us. The byte-identical notices live in the `masking/*` fixtures,
    assembled at run time.

    Scoped to one segment, the test still stopped at the first segment naming
    us, so a holder list continuing past the NEXT delimiter on the same line was
    never read ("… 2AM Logic; Some Upstream Author"). The segments after it are
    therefore checked for a second holder too — see `_second_holder_name` for
    the two bounds that keep an own aside from becoming an unanswerable finding.
    """
    segments = _holder_segments(line[holder_start:])
    for index, field in enumerate(segments):
        if not HOLDER_WORD_RE.search(field):
            continue  # delimiter-led segment with no name in it; keep walking
        own = OWN_HOLDER_RE.search(field)
        if not own:
            return False
        # Our name must be the FIRST name in the holder field — not one
        # trailing somebody else's.
        preceding = HOLDER_WORD_RE.findall(field[: own.start()])
        if not all(_holder_word_key(word) in HOLDER_LEADING_FILLER for word in preceding):
            return False
        # …and it must be the ONLY holder named in that field. Every other
        # occurrence of our own name is excised first, so "2AM Logic /
        # gf180-surge" stays ours.
        rest = OWN_HOLDER_RE.sub(" ", field[: own.start()] + " " + field[own.end() :])
        if not all(
            _holder_word_key(word) in HOLDER_NEUTRAL_WORDS
            for word in HOLDER_NAME_RE.findall(rest)
        ):
            return False
        # …and the holder list must not CONTINUE past the delimiter that ended
        # this segment.
        return not any(_second_holder_name(later) for later in segments[index + 1 :])
    return False  # no name anywhere on the holder side: not an own notice


def _first_holder_word(line, holder_start):
    """The first name standing in the holder position, lowercased (or None)."""
    for field in _holder_segments(line[holder_start:]):
        word = HOLDER_WORD_RE.search(field)
        if word:
            return _holder_word_key(word.group(0))
    return None


def _wrapped_holder_match(text, notice_match):
    """A foreign name on a holder-list CONTINUATION line, or None.

    Called only for a notice already judged ours: a wrapped holder list puts the
    second holder on the next line, where no notice keyword stands to raise the
    signal on its own.

    The returned match is searched against `text` with ABSOLUTE offsets, bounded
    to the continuation line. `Finding` carries no line number, so the caller's
    `_snippet(text, match)` is the finding's only locator: a match computed
    against the line slice would be indexed into `text` at line-relative offsets
    and quote unrelated bytes from the top of the file.
    """
    cursor = text.find("\n", notice_match.end())
    while cursor != -1:
        start = cursor + 1
        end = text.find("\n", start)
        line_end = len(text) if end == -1 else end
        line = text[start:line_end]
        continuation = HOLDER_CONTINUATION_RE.match(line)
        if not continuation:
            return None
        if COPYRIGHT_RE.search(line) or YEARLESS_COPYRIGHT_RE.search(line):
            return None  # a notice of its own; the normal scan judges it
        if not own_copyright_holder(line, continuation.end()):
            return HOLDER_WORD_RE.search(text, start + continuation.end(), line_end)
        cursor = end
    return None


def foreign_copyright_match(text):
    """The first copyright notice in `text` that does NOT name this project.

    Three shapes are read as a notice: one carrying a year, one carrying only a
    holder (no year), and a holder-list continuation line under an own notice.
    All three are judged by `own_copyright_holder`, so our own attribution never
    becomes a finding on this non-exemptible rule.
    """
    notices = [(match.start(), match, False) for match in COPYRIGHT_RE.finditer(text)]
    covered = [(match.start(), match.end()) for _, match, _ in notices]
    for match in YEARLESS_COPYRIGHT_RE.finditer(text):
        if not any(start <= match.start() < end for start, end in covered):
            notices.append((match.start(), match, True))
    for _, match, yearless in sorted(notices, key=lambda item: item[0]):
        line = copyright_line(text, match)
        holder_start = match.end() - (text.rfind("\n", 0, match.start()) + 1)
        if yearless and _first_holder_word(line, holder_start) in NOT_A_HOLDER_WORDS:
            continue  # prose about copyright, not a notice
        if not own_copyright_holder(line, holder_start):
            return match
        wrapped = _wrapped_holder_match(text, match)
        if wrapped is not None:
            return wrapped
    return None


# The repository's own Apache-2.0 license text (its appendix contains a
# copyright placeholder). Hardcoded rather than exemptible: the LICENSE file
# is required to be there, and no provenance row can describe it.
OWN_LICENSE_PATHS = frozenset({"LICENSE"})

# Surge/third-party asset payload types plus opaque bundles that no review can
# read. `.gz` is deliberately absent: this repository gzips its own evidence
# traces. `.wav`/`.bin`/`.hex`/`.npy`/`.npz` are this project's own render and
# RTL artifacts (fixtures/README.md § Licensing / provenance).
UPSTREAM_ASSET_EXTS = frozenset(
    {
        ".wt", ".wtscan", ".fxp", ".fxb", ".srg",
        ".zip", ".tar", ".tgz", ".rar", ".7z", ".jar", ".whl", ".egg",
        ".so", ".dylib", ".dll", ".a", ".lib", ".o", ".obj",
        ".pt", ".pth", ".safetensors", ".h5", ".onnx",
    }
)

# Languages this repository authors: Python, SystemVerilog/Verilog, shell,
# markdown/JSON/CSV data. Anything else is either vendored or an explicitly
# recorded API-client harness (e.g. oracle/sxt038/lp24_ref_harness.cpp, DR-0010).
FOREIGN_SOURCE_EXTS = frozenset(
    {
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl",
        ".rs", ".go", ".java", ".kt", ".swift", ".m", ".mm",
        ".ts", ".tsx", ".js", ".jsx", ".rb", ".pl", ".lua", ".cs", ".scala",
        ".vhd", ".vhdl",
    }
)

RECORD_CITATION_RE = re.compile(r"(?:decision-records/|\bDR-?)(\d{4})", re.IGNORECASE)
RECORD_FILE_RE = re.compile(r"^(\d{4})-[A-Za-z0-9._-]+\.md$")
INDEX_ROW_RE = re.compile(
    r"^\|\s*\[(\d{4})\]\(([^)]+)\)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$"
)

CAVEAT = (
    "NOTE: bookkeeping + carriage-signal audit only. A PASS is not proof that "
    "no third-party content was copied (see --limits), and says nothing about "
    "whether any decision record has been ratified."
)

BINARY_SNIFF_BYTES = 8192


class AuditError(Exception):
    """The audit could not be performed (exit 2, never a silent pass)."""


class Finding:
    def __init__(self, rule, path, detail):
        if rule not in RULES:
            raise AuditError(f"internal: unknown rule id {rule!r}")
        self.rule = rule
        self.path = path
        self.detail = detail

    def as_dict(self):
        return {"rule": self.rule, "path": self.path, "detail": self.detail}

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Finding({self.rule!r}, {self.path!r}, {self.detail!r})"


# --- encoding sniffing --------------------------------------------------------
#
# Only files this layer turns into text are reachable by the content rules
# (`foreign-license-text`, `self-declared-quotation`). Everything below exists
# to keep an ordinary text file — whatever its encoding, however it has been
# scuffed — from being discarded as "binary" before any rule can read it, while
# still not pretending a render or a wavetable payload is prose.

# Longest BOM first: UTF-32-LE's BOM starts with UTF-16-LE's.
BOM_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
    (codecs.BOM_UTF8, "utf-8-sig"),
)

# Tried in order when a head carries NULs but no BOM (the shape a Windows
# editor's "Unicode" save leaves behind).
BOMLESS_WIDE_ENCODINGS = ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")

# A license notice is ASCII English prose, so "mostly ASCII" is the right
# admission test: a .wav or .npy payload reinterpreted as UTF-16 decodes to
# mostly non-ASCII code points and is correctly refused. The cost is a
# DECLARED boundary, not a silent one — see DECLARED LIMITS.
ASCII_TEXT_RATIO = 0.90

# Above this share of NULs the payload is structural (PCM silence, a tensor),
# not text someone scuffed to hide a notice.
MAX_STRAY_NUL_RATIO = 0.01


def _ascii_text_ratio(text):
    """Share of `text` that is printable ASCII or ordinary whitespace."""
    if not text:
        return 0.0
    good = sum(1 for ch in text if ch in "\t\n\r\f\v" or "\x20" <= ch <= "\x7e")
    return good / len(text)


def sniff_encoding(head: bytes):
    """An encoding name to decode this payload with, or None if it is binary.

    `head` is the first `BINARY_SNIFF_BYTES` only; a trailing split code unit
    is harmless because the result is used solely to choose the codec.
    """
    for bom, encoding in BOM_ENCODINGS:
        if head.startswith(bom):
            return encoding
    if not head:
        return "utf-8"
    if b"\0" not in head:
        return "utf-8"
    for encoding in BOMLESS_WIDE_ENCODINGS:
        width = 4 if encoding.startswith("utf-32") else 2
        # Decode whole code units only, so a split tail cannot skew the ratio.
        usable = head[: len(head) - (len(head) % width)]
        if not usable:
            continue
        if _ascii_text_ratio(usable.decode(encoding, "replace")) >= ASCII_TEXT_RATIO:
            return encoding
    # Narrow text someone has scuffed with a few NULs: sparse enough to be an
    # evasion rather than a payload, and ASCII once they are removed.
    if head.count(0) / len(head) <= MAX_STRAY_NUL_RATIO:
        stripped = head.replace(b"\0", b"").decode("utf-8", "replace")
        if _ascii_text_ratio(stripped) >= ASCII_TEXT_RATIO:
            return "utf-8"
    return None


# --- payloads the sniff refuses: wrappers and embedded strings ----------------
#
# Increment 8. The layer above decides HOW to decode a file; this one decides
# what to do with the payload it refused. Until now the answer was "nothing":
# `Tree.text()` returned None, `tripwire_hits()` returned before every content
# rule, and the only trace was a count. Two shapes went straight past the
# non-exemptible `foreign-license-text` rule on the real tree (both demonstrated
# in `reports/sxt-019/EVIDENCE.md` §14):
#
#   * a WRAPPER. A gzip/bzip2/xz stream, a zip or a tar is not opaque content —
#     it is text one `read()` away. `.gz` is deliberately absent from
#     UPSTREAM_ASSET_EXTS (this repository gzips its own evidence traces) and
#     `_extension_suffix` strips it, so `pasted_helper.py.gz` matched no
#     extension tripwire either; a zip or tar renamed `.dat` evades the
#     extension rule outright.
#   * an EMBEDDED notice. A notice pasted into a render, a tensor or a raw
#     float dump is ordinary ASCII sitting in a payload — a WAV `LIST/INFO`
#     `ICOP` chunk is where an upstream sample pack states its copyright, and
#     nothing in this repository's own renders carries one.
#
# Both are answered WITHOUT loosening the sniff, which is the failure the
# previous increment's positive control guards (decoding a render as prose would
# turn 264 renders into garbage findings on a rule nobody can exempt):
#
#   1. unwrap wrappers by MAGIC, not by extension, recursively (a `.tar.gz`
#      is two layers), bounded by an inflation budget, and run the ordinary
#      decode + content rules on each member;
#   2. for a payload that is still not text, harvest the printable-ASCII RUNS
#      that carry a word, and run the content rules on those. A license notice
#      is ASCII English prose; 16-bit PCM and float32 data produce runs with no
#      word in them.
#
# Measured on this repository before committing: 339 MiB of payloads over 335
# files (264 `.wav`, 22 `.bin`, 22 `.f32`, 18 `.gz`, 8 `.npy`, 1 `.npz`) yield
# ZERO hits on all four content signals. That matters because
# `foreign-license-text` cannot be exempted: a false positive on our own render
# would be unanswerable, so the rule would be switched off rather than answered.

GZIP_MAGIC = b"\x1f\x8b"
BZIP2_MAGIC = b"BZh"
XZ_MAGIC = b"\xfd7zXZ\x00"
ZIP_MAGIC = b"PK\x03\x04"
STREAM_WRAPPERS = ((GZIP_MAGIC, "gzip"), (BZIP2_MAGIC, "bzip2"), (XZ_MAGIC, "xz"))

# Bounds on what ONE tree entry may inflate to, so a decompression bomb cannot
# hang or OOM the audit. `MAX_UNWRAPPED_BYTES` is a budget over the WHOLE unwrap
# of an entry, summed across every stream, archive member and recursion level
# (`_InflationBudget`), not a per-level ceiling; `MAX_UNWRAP_DEPTH` bounds the
# recursion. Both are generous against this tree (its largest inflation is
# ~15 MiB at depth 1) and neither is silent: a payload that hits either is
# reported as truncated on every run and in `--json`, because a scan that could
# not finish must never look like one that passed.
MAX_UNWRAPPED_BYTES = 256 * 1024 * 1024
MAX_UNWRAP_DEPTH = 4

# A run of printable ASCII long enough to hold a word, and the word test
# itself. Three consecutive letters is the cheapest filter that keeps every
# license/copyright vocabulary word ("GNU", "Copyright", "GPL-3.0-or-later",
# a holder name) while discarding PCM and float noise: dropping a WORDLESS run
# can only bring two surviving runs CLOSER together, so it cannot break a
# phrase the rules would otherwise have matched.
#
# It is NOT merely a precision/cost knob (#283 corrected the increment-8
# record, which said so). Harvested text reaches every rule, including the
# BOOKKEEPING ones, and those are cheap enough for noise to satisfy: with this
# filter removed, `reports/sxt-024/traces/reset-midpatch-wet.npy` fails the
# real-tree audit with `dangling-record-citation`, because its noise happens to
# carry a `dR` + `90459` run. (Written as fragments here for the same reason as
# every fixture below: spelled out, this comment would itself be a citation of
# a record that does not exist — the rule reads THIS file too.) Pinned by
# `payload/citation-shaped-noise-run-stays-clean`.
PRINTABLE_RUN_RE = re.compile(rb"[\x20-\x7e\t\r\n]{6,}")
RUN_WORD_RE = re.compile(rb"[A-Za-z]{3,}")

# A UTF-8 © would end a printable-ASCII run mid-notice and take the copyright
# keyword with it. Normalised to its ASCII spelling before harvesting, which the
# `(c)` prefilter already recognises. Only this one spelling in the NARROW
# harvest: the Latin-1 single byte 0xA9 occurs constantly inside PCM and float
# data, and rewriting it there would manufacture `(c)` tokens in noise on a rule
# that cannot be exempted. (Inside a WIDE run the same byte is admitted, because
# it has to arrive NUL-padded inside an otherwise printable NUL-padded run —
# see `_wide_runs`.)
UTF8_COPYRIGHT_SIGN = b"\xc2\xa9"

# --- increment 10: the same payload, read in a WIDE encoding -------------------
#
# Increment 8 harvested the printable-ASCII runs a refused payload carries and
# then DECLARED the rest: "the harvest reads ASCII, so a notice written in a WIDE
# encoding *inside* a binary payload stays out of reach". That declaration was
# wrong in exactly the way increments 6, 8 and 9 were wrong about their own: a
# UTF-16 save is what an ordinary Windows editor produces, so "wide" is not an
# exotic carriage — and a notice re-encoded that way and spliced into a render,
# a float dump or an opaque archive member went past the non-exemptible
# `foreign-license-text` rule with the audit reporting PASS, exit 0 and
# UNCHANGED tripwire counts (demonstrated on the real tree in
# `reports/sxt-019/EVIDENCE.md` §16).
#
# The sniff already decodes a file that is wide-encoded THROUGHOUT; what it
# cannot do is admit a payload that is mostly binary with a wide-encoded notice
# in it, and loosening it is the other failure direction (increment 6's positive
# control guards that: decoding a render as prose would turn 264 renders into
# garbage findings on a rule nobody can exempt).
#
# So the runs are found the same way the ASCII ones are — by their SHAPE, not by
# a name or a declaration. An ASCII code point in UTF-16/UTF-32 is one data byte
# plus NUL padding, so a wide run is a run of NULs in one of the two half-stride
# streams whose matching data bytes are all printable:
#
#   utf-16-le  'H\0e\0'   -> NULs at odd offsets,  data at even
#   utf-16-be  '\0H\0e'   -> NULs at even offsets, data at odd
#   utf-32-le  'H\0\0\0'  -> NULs at odd offsets,  and the data stream is itself
#   utf-32-be  '\0\0\0H'     NUL-padded, so one more halving step resolves it
#
# Looking for the PADDING rather than for alternating pairs is what makes this
# affordable: `\x00{6,}` has a literal prefix, so the regex engine scans for
# candidates at memchr speed instead of restarting a character class at every
# byte. Measured over this repository's 339 MiB of payloads: 4.0 s for this
# shape against 18.8 s for the alternating-pair pattern, i.e. the same cost as
# the ASCII harvest that was already being paid (§16).
MIN_WIDE_RUN_UNITS = 6

WIDE_PAD_RUN_RE = re.compile(rb"\x00{%d,}" % MIN_WIDE_RUN_UNITS)

# The admission test for a wide run's data bytes, applied with `bytes.translate`
# (C speed) rather than a per-character ratio: EVERY data byte must be printable
# ASCII or ordinary whitespace. Not a ratio, because the padding constraint is
# already doing the discriminating work and a single stray byte simply splits one
# run into two. 0xA9 is admitted here and normalised below: a notice that writes
# its holder with the sign spelling (U+00A9) rather than the word is the first
# evasion anyone would reach for, and in a wide run that byte has to arrive
# NUL-padded inside an otherwise printable NUL-padded run — which is nothing like
# the bare 0xA9 that occurs constantly in PCM, and is why the NARROW harvest
# still refuses it.
WIDE_DATA_BYTES = bytes(range(0x20, 0x7F)) + b"\t\r\n"
LATIN1_COPYRIGHT_SIGN = b"\xa9"
WIDE_DATA_ALLOWED = WIDE_DATA_BYTES + LATIN1_COPYRIGHT_SIGN
# Derived from the byte above rather than written as a character, so this file
# carries no notice of its own — the same reason every fixture here is assembled
# from fragments (see the fixture note below).
COPYRIGHT_SIGN_CHAR = LATIN1_COPYRIGHT_SIGN.decode("latin-1")


def _decode_wide_run(data: bytes):
    """A candidate run's text, or None when its bytes are not printable.

    `data` is the run's DATA bytes with the padding already removed, so this is
    the admission test plus the U+00A9 normalisation, nothing more.
    """
    if len(data) < MIN_WIDE_RUN_UNITS:
        return None
    if data.translate(None, WIDE_DATA_ALLOWED):
        return None
    if not RUN_WORD_RE.search(data):
        return None
    # latin-1 rather than ascii: every admitted byte but 0xA9 is ASCII, and that
    # one is normalised to the spelling the `(c)` prefilter already recognises.
    return data.decode("latin-1").replace(COPYRIGHT_SIGN_CHAR, "(c)")


def _wide_runs(raw: bytes):
    """Text of each wide-encoded (UTF-16/UTF-32, either byte order) ASCII run.

    A BOM is neither required nor consumed: the run is found by its padding, so
    `\\xff\\xfe`-led text, BOM-less text and text spliced into the middle of a
    payload are all the same case here.
    """
    runs = []
    for pad_phase in (0, 1):
        pad = raw[pad_phase::2]
        data_stream = raw[1 - pad_phase :: 2]
        # Whether a code unit's data byte PRECEDES its padding or FOLLOWS it
        # depends on the byte order AND on the offset the text happens to start
        # at, which is odd as often as it is even for a notice spliced into a
        # payload. Both windows are therefore read; a misaligned one picks up a
        # padding NUL (not in `WIDE_DATA_ALLOWED`) and fails the admission test,
        # so reading both cannot invent a run — it can only read the same text
        # twice, which the coverage count says it does.
        shifts = (0, -1) if pad_phase == 0 else (0, 1)
        for match in WIDE_PAD_RUN_RE.finditer(pad):
            start, end = match.span()
            for shift in shifts:
                low = start + shift
                if low < 0:
                    continue
                # pad[k] is one byte of a code unit; data_stream[k + shift] is
                # its data byte, so these are the data bytes of the units this
                # NUL run pads.
                data = data_stream[low : end + shift]
                text = _decode_wide_run(data)
                if text is not None:
                    runs.append(text)
                    continue
                # A 32-bit code unit pads its data stream in turn, so the same
                # step once more resolves UTF-32 in either byte order. The OTHER
                # half must be all NUL for that reading to be real padding rather
                # than an arbitrary decimation of binary data — without that
                # check, quiet 16-bit PCM (whose every high byte is NUL)
                # decimates into printable noise and manufactures runs on a rule
                # that cannot be exempted.
                for inner_phase in (0, 1):
                    if data[1 - inner_phase :: 2].translate(None, b"\x00"):
                        continue
                    text = _decode_wide_run(data[inner_phase::2])
                    if text is not None:
                        runs.append(text)
                        break
    return runs


def harvest_strings(raw: bytes):
    """Text harvested from a payload the sniff refused (see `harvest_payload`)."""
    return harvest_payload(raw)[0]


def harvest_payload(raw: bytes):
    """(text, number of wide-encoded runs) for a payload the sniff refused.

    The text is the payload's printable-ASCII runs that carry a word, plus the
    same for its wide-encoded (UTF-16/UTF-32) runs. The joint is a newline, which
    every content regex treats as an ordinary word gap (`_GAP`), so a notice
    split across runs by a binary field is still matched.

    The wide-run count is returned rather than inferred: it is reported as
    coverage, so "no wide run offended" and "no wide run was examined" cannot be
    confused with each other.
    """
    if UTF8_COPYRIGHT_SIGN in raw:
        raw = raw.replace(UTF8_COPYRIGHT_SIGN, b"(c)")
    kept = [
        match.group().decode("ascii", "replace")
        for match in PRINTABLE_RUN_RE.finditer(raw)
        if RUN_WORD_RE.search(match.group())
    ]
    wide = _wide_runs(raw)
    return "\n".join(kept + wide), len(wide)


def _looks_like_wrapper(raw: bytes):
    """Cheap magic test: could `raw` be a compressed/archive wrapper?"""
    if any(raw.startswith(magic) for magic, _ in STREAM_WRAPPERS):
        return True
    if raw.startswith(ZIP_MAGIC):
        return True
    # tar's magic sits at offset 257, so there is no prefix to test.
    try:
        return tarfile.is_tarfile(io.BytesIO(raw))
    except Exception:  # pragma: no cover - defensive
        return False


class _InflationBudget:
    """One mutable remaining-byte budget, SHARED by every level of one unwrap.

    A per-level limit is not a bound on the total. Until #283 the recursion was
    handed `limit` unchanged, so a zip of many small gzip members could stay
    under the limit at every individual level while the sum vastly exceeded it:
    measured at a 1 MiB test budget, an 8.7 KB zip of 64 gzip members (each
    inflating to just under 1 MiB) yielded 64 MiB of payload with
    `truncated=False` — 16 GiB resident at the real 256 MiB budget. Passing this
    object by REFERENCE instead makes the budget a bound on the TOTAL bytes one
    tree entry may be inflated to.

    `exhausted` is the disclosure half: it becomes the caller's `truncated`, so
    a walk the budget cut short is reported as a partial read rather than
    counted as a pass.
    """

    __slots__ = ("remaining", "exhausted")

    def __init__(self, limit: int):
        self.remaining = max(0, limit)
        self.exhausted = False

    def read(self, handle):
        """`(data, over)` — read at most what is left, charging the budget.

        One byte PAST the remaining budget is requested on purpose: it is how a
        payload that exactly fills the budget is told apart from one that
        overruns it. `over` is True only in the latter case, and the budget is
        then exhausted for every later member and deeper level too.
        """
        data = handle.read(self.remaining + 1)
        if len(data) > self.remaining:
            data = data[: self.remaining]
            self.remaining = 0
            self.exhausted = True
            return data, True
        self.remaining -= len(data)
        return data, False


def _unwrap_stream(raw: bytes, kind: str, budget: "_InflationBudget"):
    """(payload, truncated) for a single-stream wrapper, or (None, False).

    The `*File` wrappers are used rather than the one-shot `decompress()`
    helpers because they handle CONCATENATED streams (a multi-member bzip2 or
    xz) and because the bounded `read()` caps the inflation without
    materialising it.

    gzip does NOT come through here: it is walked member by member by
    `_gzip_members` instead, because each of its members carries a NAME of its
    own and this function would fold them all into one unnamed payload
    (increment 12).
    """
    openers = {
        "bzip2": lambda buf: bz2.BZ2File(buf, "rb"),
        "xz": lambda buf: lzma.LZMAFile(buf, "rb"),
    }
    try:
        with openers[kind](io.BytesIO(raw)) as handle:
            out, over = budget.read(handle)
    except Exception:
        # Corrupt or not actually this wrapper. Not a finding: the payload falls
        # through to the string harvest, and whatever it is stays disclosed.
        return None, False
    return out, over


def _gzip_header_name(raw: bytes):
    """The original filename a gzip header carries (FNAME), or None.

    RFC 1952 §2.3.1: `FLG` bit 3 means a NUL-terminated original file name
    follows the fixed 10-byte header (after `FEXTRA`, if bit 2 is set too).
    `gzip.GzipFile` reads this field and throws it away, and there is no public
    API for it — so it is parsed here. It is the ONLY name a single-stream
    wrapper carries: `evidence.dat` whose gzip header says `Bank Sine.wt` has
    no other name to judge, and before increment 9 nothing read it.
    """
    if not raw.startswith(GZIP_MAGIC) or len(raw) < 11:
        return None
    flags = raw[3]
    if not flags & 0x08:  # FNAME not present
        return None
    offset = 10
    if flags & 0x04:  # FEXTRA: a 2-byte length then that many bytes
        if len(raw) < offset + 2:
            return None
        extra = raw[offset] | (raw[offset + 1] << 8)
        offset += 2 + extra
    end = raw.find(b"\0", offset)
    if end < 0 or end <= offset:
        return None
    # Latin-1 per RFC 1952; replace rather than raise on anything else.
    return raw[offset:end].decode("latin-1", "replace")


# `zlib` with the gzip header/trailer handled for us (RFC 1952), one MEMBER at
# a time: `decompressobj` stops at the member's own trailer and hands the
# remainder back as `unused_data`, which is the only boundary a concatenated
# stream has. `gzip.GzipFile` inflates straight through those boundaries, which
# is why it cannot be asked where the second member's header starts.
GZIP_WBITS = 16 + zlib.MAX_WBITS


def _gzip_members(raw: bytes, budget: "_InflationBudget"):
    """([(FNAME|None, payload)] per MEMBER, truncated), or (None, False).

    A gzip stream may be CONCATENATED — `cat a.gz b.gz > c.gz` is a valid gzip
    file whose content is `a`'s followed by `b`'s — and **every member carries
    its own FNAME header**. Increment 9 read that header once per stream, from
    the first member only, so a `.wt` named by the SECOND member's header was
    not judged at all while the first member's innocuous `.json` name was: the
    same two members in the other order fired. That order-dependence is the
    whole defect this closes (increment 12).

    The inflation budget is SHARED with every other level of the same unwrap
    (`_InflationBudget`), exactly as `_unwrap_archive` already shares it across
    a zip's or a tar's members: each member's read is charged against the one
    `remaining` counter, and the first member that overruns it truncates there
    and reports `truncated` for the whole stream — a bound on the TOTAL this
    entry inflates to, not a fresh allowance per member.

    `None` means the stream is not cleanly parseable as gzip (a corrupt member,
    or trailing bytes that are not another member's header) — the same answer,
    and the same fall-through to the string harvest, that `gzip.GzipFile`
    raising `BadGzipFile` produced before.
    """
    members = []
    rest = raw
    while rest.startswith(GZIP_MAGIC):
        name = _gzip_header_name(rest)
        try:
            obj = zlib.decompressobj(wbits=GZIP_WBITS)
            data = obj.decompress(rest, budget.remaining + 1)
        except Exception:
            return None, False
        if len(data) > budget.remaining:
            # The budget stopped the walk mid-member: keep what fits, disclose
            # the partial read, and do not pretend to have seen later members'
            # names.
            data = data[: budget.remaining]
            budget.remaining = 0
            budget.exhausted = True
            return members + [(name, data)], True
        if not obj.eof:
            # All input consumed without reaching this member's trailer: the
            # stream is truncated or corrupt, not a wrapper this audit opened.
            return None, False
        members.append((name, data))
        budget.remaining -= len(data)
        rest = obj.unused_data
    if rest or not members:
        return None, False
    return members, False


# Joins a wrapper's name to the name of what it wraps. Every component of a
# joined label is tripwired separately, so an outer name is never masked by the
# inner one (`Bank Sine.wt!meta.json` must still read as a `.wt`).
MEMBER_JOIN = "!"


def _join_member(outer, inner):
    if outer and inner:
        return f"{outer}{MEMBER_JOIN}{inner}"
    return outer or inner or ""


def _unwrap_archive(raw: bytes, budget: "_InflationBudget"):
    """([(member name, payload)], truncated) for a zip/tar, or (None, False).

    The budget is shared with every other level of the same unwrap, so the sum
    of this archive's members is charged against whatever its own wrappers
    already spent — and against whatever its members go on to inflate to.
    """
    buf = io.BytesIO(raw)
    members = None
    try:
        if zipfile.is_zipfile(buf):
            members = []
            with zipfile.ZipFile(buf) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    with archive.open(info) as handle:
                        data, over = budget.read(handle)
                    members.append((info.filename, data))
                    if over:
                        return members, True
            return members, False
    except Exception:
        return None, False
    buf.seek(0)
    try:
        if not tarfile.is_tarfile(buf):
            return None, False
        buf.seek(0)
        members = []
        with tarfile.open(fileobj=buf, mode="r") as archive:
            for info in archive:
                if not info.isfile():
                    continue
                handle = archive.extractfile(info)
                if handle is None:  # pragma: no cover - sparse/odd member
                    continue
                data, over = budget.read(handle)
                members.append((info.name, data))
                if over:
                    return members, True
        return members, False
    except Exception:
        return None, False


def unwrap_payload(raw: bytes, budget=None, depth=0):
    """([(member name, payload)] carried inside `raw`, truncated), or (None, …).

    `None` means `raw` is not a wrapper — not that it is safe. Recurses so that
    a `.tar.gz` (and a `.tar.gz` inside a zip) is unwrapped to its real members;
    `truncated` is True when the inflation budget or the depth limit stopped the
    walk, so the caller can disclose an incomplete scan instead of reporting a
    pass.

    `budget` is an `_InflationBudget` shared by the whole recursion (default: a
    fresh `MAX_UNWRAPPED_BYTES` one per entry), so `MAX_UNWRAPPED_BYTES` bounds
    the TOTAL this entry inflates to rather than each level separately (#283).

    The member NAME travels with its payload (increment 9). Unwrapping read
    member CONTENT only, so a wrapper whose members carry no marker — a zip of
    upstream `.wt` wavetables, a tar of marker-free `.cpp` sources — was
    answered by nothing: the archive extensions judge the OUTER name, which a
    `.dat` rename evades. A member that is itself a wrapper keeps its own name
    in the label (`dsp/Reverb1.h.gz!…`) rather than being replaced by what it
    wraps.

    A gzip stream is walked member by member (increment 12), so EVERY member of
    a concatenated stream contributes its own name. Reading the FNAME once per
    stream made the rule order-dependent: `cat notes.json.gz 'Bank Sine.wt.gz'`
    audited clean while the same two members in the other order fired.
    """
    if budget is None:
        budget = _InflationBudget(MAX_UNWRAPPED_BYTES)
    if depth >= MAX_UNWRAP_DEPTH:
        return None, _looks_like_wrapper(raw)
    for magic, kind in STREAM_WRAPPERS:
        if not raw.startswith(magic):
            continue
        if kind == "gzip":
            # EVERY member of a concatenated stream, each with its own FNAME
            # (increment 12). Before this, one name was read for the whole
            # stream and members 2..n were content-scanned but never named.
            members, truncated = _gzip_members(raw, budget)
        else:
            inner, truncated = _unwrap_stream(raw, kind, budget)
            members = None if inner is None else [(None, inner)]
        if members is None:
            return None, False
        entries = []
        for label, inner in members:
            deeper, deeper_truncated = unwrap_payload(inner, budget, depth + 1)
            truncated = truncated or deeper_truncated
            if deeper is None:
                entries.append((_join_member(label, ""), inner))
            else:
                entries.extend(
                    (_join_member(label, name), payload) for name, payload in deeper
                )
        return entries, truncated
    members, truncated = _unwrap_archive(raw, budget)
    if members is None:
        return None, truncated
    entries = []
    for name, member in members:
        deeper, deeper_truncated = unwrap_payload(member, budget, depth + 1)
        truncated = truncated or deeper_truncated
        if deeper is None:
            entries.append((name, member))
        else:
            entries.extend(
                (_join_member(name, inner), payload) for inner, payload in deeper
            )
    return entries, truncated


# --- file discovery -----------------------------------------------------------
#
# This layer decides what EXISTS as far as the audit is concerned, and — new in
# increment 7 — what KIND of entry each path is. Everything above it reads
# bytes; a tree entry that carries its content by REFERENCE has no bytes of its
# own to read, so the signal layers never saw it:
#
#   * a committed submodule (mode 160000) is one index entry whose files are
#     not listed in the parent at all. `open()` on it raises IsADirectoryError,
#     so it decoded to None and reached no content rule — a gitlink pinning the
#     GPL Surge engine audited clean, which is the single highest-volume way
#     upstream content can enter this tree (and `AGENTS.md`/#25 forbid creating
#     one "by silent default").
#   * a tracked symlink (mode 120000) whose target leaves the tree carries
#     upstream content at a product path. `open()` follows it, so a target that
#     resolves is read — but a target that is absent at audit time (the CI
#     shape: the pinned oracle is an EXTERNAL working directory by design) read
#     as "undecodable payload" and was counted with the renders.
#
# Both are therefore judged here, from the entry itself, before any byte is
# read. `.gitmodules` is used only to name the upstream in the finding.

# `git ls-files -s` modes for entries that are not regular files.
GIT_MODE_KINDS = {"120000": "symlink", "160000": "gitlink"}

# How many un-indexed working-tree paths the text report names individually.
# The COUNT is always printed; this only bounds the listing (`--json` carries
# the full list either way).
UNINDEXED_PATHS_LISTED = 10


def list_entries(root: Path):
    """[(rel, kind, gitlink_commit)] for candidate entries, sorted by path.

    `kind` is "file", "symlink" or "gitlink". Uses `git ls-files -s` when the
    tree is a git checkout (so untracked scratch files are not audited, and the
    recorded MODE is read rather than guessed), and falls back to a filesystem
    walk otherwise (synthetic trees in tests and in --negative-control).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-s", "-z"],
            capture_output=True,
            check=True,
        )
        records = [r for r in proc.stdout.decode("utf-8", "replace").split("\0") if r]
        if records:
            seen = {}
            for record in records:
                meta, _, rel = record.partition("\t")
                if not rel:
                    continue
                fields = meta.split()
                mode = fields[0] if fields else ""
                blob = fields[1] if len(fields) > 1 else ""
                kind = GIT_MODE_KINDS.get(mode, "file")
                # Conflict stages repeat a path; the first stage is enough.
                # The object id is kept for EVERY kind, not just gitlinks: for a
                # blob it is how the STAGED bytes are read (increment 14), and
                # for a gitlink it is the commit the entry pins (increment 7).
                seen.setdefault(rel, (kind, blob))
            return sorted((rel, kind, blob) for rel, (kind, blob) in seen.items())
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(_walk_entries(root))


# --- the index boundary (increment 11) ---------------------------------------
#
# `list_entries` reads the git INDEX, so what it audits is "what this repository
# has committed or staged", not "what is in this working tree". That boundary is
# right for CI — a PR's files are all tracked — but it was SILENT, and silence
# is the one thing every other residual in this tool is not:
#
#   * a file dropped into the working tree and not yet `git add`ed is scanned by
#     no rule at all. Dropping an unattributed file carrying a GPL body, a
#     foreign SPDX tag and a foreign copyright line into `model/` audited
#     **PASS**, and the coverage line printed the SAME file count as the clean
#     tree — so "no unattributed file is here" and "one is here, unlooked at"
#     were indistinguishable in the output;
#   * that is exactly the local, pre-commit run acceptance item 4's own wording
#     describes ("demonstrate it once on a deliberately unattributed file"), and
#     the demonstration only worked after staging the file.
#
# The boundary is kept — auditing a developer's scratch files by default would
# put unanswerable findings on a non-exemptible rule — but it is now DISCLOSED
# per run (a count, printed even when zero, so "none present" and "never looked"
# do not look alike), DECLARED in `--limits`, and crossable on demand with
# `--include-untracked`.
#
# Ignored files are deliberately not counted: `.gitignore` is this repository's
# own statement that a path is not part of it, and build output would otherwise
# drown the signal. That sub-boundary is declared and control-pinned too.


def list_untracked(root: Path):
    """Repo-relative paths present in the working tree but not in the index.

    Ignored files are excluded (`--exclude-standard`). Returns `[]` for a tree
    that is not a git checkout, where "untracked" has no meaning: the
    filesystem walk in `_walk_entries` already sees every file there.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    if not _is_git_checkout(root):
        return []
    return sorted(r for r in proc.stdout.decode("utf-8", "replace").split("\0") if r)


def _is_git_checkout(root: Path):
    """True when `list_entries` read `root`'s own git index rather than walking.

    Guards against the one way the two discovery paths can disagree: a
    NON-git synthetic tree created inside a git checkout would make
    `git -C <tree> ls-files --others` succeed against the ENCLOSING repository
    and report every file in the tree as untracked, while `list_entries` had
    already walked and audited them all.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    top = proc.stdout.decode("utf-8", "replace").strip()
    if not top:
        return False
    try:
        return Path(top).resolve() == Path(root).resolve()
    except OSError:
        return False


# --- the staged-content boundary (increment 14) -------------------------------
#
# The layer below enumeration is not WHICH entries are read but WHICH BYTES an
# enumerated entry is read as. Increment 7 moved the discovery rules onto the
# INDEX (an entry's mode, a gitlink's pinned commit are read from `ls-files -s`),
# and increment 11 disclosed that the audited SET is the index. The CONTENT rules
# never followed: `Tree._read` opened `root / rel` — the WORKING TREE — so the
# bytes judged were not the bytes the index holds, and `git commit` commits the
# index. Two shapes audited **PASS** on a tree whose staged blob carried a
# complete GPL body, a foreign SPDX tag and a foreign copyright line:
#
#   * `git add carrier.py` and then overwrite the working-tree copy with
#     innocuous text (no re-add). Every content rule read the innocuous copy;
#     the commit published the body. Coverage printed nothing at all — the file
#     count, `files_not_content_scanned` and the un-indexed list were identical
#     to the clean tree's.
#   * `git add carrier.py` and then delete the working-tree copy. `ls-files`
#     still names it, `open()` raised `OSError`, the entry was recorded
#     "unreadable" and counted among the renders in `files_not_content_scanned`
#     — the same place increment 7's gitlink hid.
#
# So the audit now reads BOTH views of an entry whose staged blob and
# working-tree bytes differ: the working-tree view (unchanged — an unstaged
# paste into a tracked file must keep firing, which is what the audit is for
# before a `git add`) and the STAGED view, read from the index blob with
# `git cat-file`. Findings from the staged view say so in their evidence, and
# the divergence is reported as coverage on every run, printed even when zero.
#
# The divergence set is git's own index-vs-working-tree comparison
# (`diff-files`), so a legitimate difference introduced by a CRLF/clean filter
# is not called divergence — and when it is, the only cost is an extra scan of
# the committable bytes. Added to it are the entries git was TOLD not to
# compare: `assume-unchanged` (lowercase `ls-files -v` tag) and `skip-worktree`
# (`S`) both make `diff-files` report an entry clean no matter what its working
# copy holds, which is a "stop looking" switch sitting exactly under this rule.
# Those are audited from the index unconditionally rather than trusted.

# How many divergent paths the text report names individually (the COUNT is
# always printed; `--json` carries the full list either way).
STAGED_PATHS_LISTED = 10

# The two byte sources a single entry can be read as.
WORKTREE_VIEW = "working tree"
STAGED_VIEW = "staged"

# A third, DERIVED selector (increment 15), used as a `Tree`'s default view
# rather than as a byte source of its own: "the bytes a commit would publish"
# resolves per entry to its STAGED blob when the two views diverge, and to its
# working-tree copy when git itself says the two are equal — in which case the
# working-tree copy IS the committable content, and reading it is both cheaper
# and the same bytes. It exists because increment 14 moved the carriage rules
# onto both views while the ANSWERS to them (the provenance rows, exemptions,
# scope exclusions, the record index and the records' own headers) stayed on the
# working-tree copy, so an answer could be published by no commit at all.
COMMITTED_VIEW = "committed"

# The files that ANSWER a carriage finding rather than raise one. When any of
# them is staged-divergent, the audited tree has two different answer sets and
# the committable one has to be judged on its own (increment 15).
def _is_bookkeeping(rel):
    if rel in (MANIFEST_REL, INDEX_REL):
        return True
    parent, _, name = rel.rpartition("/")
    return parent == RECORD_DIR_REL and bool(RECORD_FILE_RE.match(name))

# `git ls-files -v` tags for entries git has been told not to compare against
# the working tree. A lowercase tag means assume-unchanged for any state.
SKIP_WORKTREE_TAG = "S"


def _view_label(rel, view):
    """`rel`, naming the byte source when it is not the working-tree copy.

    Used wherever coverage or a finding quotes a path: "which bytes offended" is
    not answerable from the path alone once an entry has two views.
    """
    return rel if view == WORKTREE_VIEW else f"{rel} [{view} blob]"


def entry_views(tree, rel):
    """Every byte view of `rel` this run reads, in the order it reads them.

    The view set increment 14 introduced for the carriage rules: the
    working-tree copy of every in-scope entry, plus the STAGED blob of every
    entry whose index bytes are not known to equal it. It lived inline in
    `check_tripwires` until increment 16 needed it in two MORE places — the two
    checks outside group 4 that read an entry's own content as EVIDENCE for a
    bookkeeping judgement (`check_citations`, `_corroborate`), each of which
    read exactly one view until then and so could be satisfied, or silenced, by
    bytes no commit publishes. It is a function rather than three copies of the
    same two lines precisely so a later increment cannot move one and leave the
    others behind, which is the shape of every mask this series has closed.

    A history tree (increment 17) has exactly one view of each entry — the blob
    its commit names — and that view is its PRIMARY one, so the structural
    signals belong to it rather than to a working-tree copy that describes some
    other tree entirely.
    """
    if tree.primary_view != WORKTREE_VIEW:
        return [tree.primary_view]
    views = [WORKTREE_VIEW]
    if rel in tree.staged_views:
        views.append(STAGED_VIEW)
    return views


def view_evidence_prefix(view):
    """How a finding names the bytes it read, or "" for the working-tree copy.

    One definition, used by both places that say it (increment 17 added the
    third view and would otherwise have inherited the staged wording for bytes
    that have nothing to do with an index).
    """
    if view == WORKTREE_VIEW:
        return ""
    if view == HISTORY_VIEW:
        return "in the content this COMMIT publishes (commit blob) — "
    return f"in the STAGED content ({view} blob), not in the working-tree copy — "


def _staged_evidence(view, detail):
    """`detail`, saying so when the bytes it describes are not the working copy.

    The path alone does not answer "which bytes" once an entry has two views,
    and the answer changes what the author must do — the same reason
    `_view_tripwire_findings` prefixes its evidence.
    """
    return view_evidence_prefix(view) + detail


def list_staged_divergent(root: Path):
    """Index entries whose STAGED bytes may differ from the working tree's.

    `git diff-files` answers the question directly and with git's own filter /
    CRLF semantics. Union-ed with the entries git was told not to compare
    (`assume-unchanged`, `skip-worktree`), whose staged bytes are therefore
    unknown here and are read rather than assumed clean.

    Returns `[]` for a tree that is not a git checkout, where there is no index
    to diverge from: `_walk_entries` has already read every file in it.
    """
    if not _is_git_checkout(root):
        return []
    divergent = set()
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff-files", "--name-only", "-z"],
            capture_output=True,
            check=True,
        )
        divergent.update(r for r in proc.stdout.decode("utf-8", "replace").split("\0") if r)
    except (OSError, subprocess.CalledProcessError):
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-v", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return sorted(divergent)
    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if len(record) < 3 or record[1] != " ":
            continue
        tag, rel = record[0], record[2:]
        if tag.islower() or tag == SKIP_WORKTREE_TAG:
            divergent.add(rel)
    return sorted(divergent)


def read_index_blob(root: Path, oid: str):
    """The staged bytes of blob `oid`, or None when they cannot be read.

    None is "this view yielded nothing", never "this view is clean": the caller
    records it as an unreadable scan, and a view that was never read is reported
    separately from one that was read and carried no signal.
    """
    if not oid or not re.fullmatch(r"[0-9a-f]{40,64}", oid):
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", oid],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return proc.stdout


# --- the history boundary (increment 17) --------------------------------------
#
# Increments 11, 14 and 15 walked down one axis: WHICH entries are audited (the
# working tree, then the index), WHICH BYTES an audited entry is read as (the
# working-tree copy, then the staged blob), and WHICH ANSWER SET judges them
# (the copy on disk, then the committable one). Every one of those reads the
# repository as it stands NOW. The set nobody enumerated is the one a clone
# actually carries: **every tree every commit publishes**.
#
# That is not an abstract residual here. This repository merges with MERGE
# COMMITS (squash and rebase merges are disabled on the forge), so every
# intermediate commit of every merged branch is permanently reachable from
# `main` — `git clone` fetches its blobs, and `git show` prints them. A carrier
# added in one commit and deleted in a later one is therefore published content
# that no tree audit, in any of the four views above, ever reads: the final tree
# does not contain it.
#
# `--commits <rev-range>` audits each commit in a range as its own tree: the
# entries are that commit's (`git ls-tree -r`), the bytes are that commit's
# blobs, and the ANSWERS come from that commit's own `decision-records/`
# bookkeeping — the same asymmetry increment 15 established, one step further
# out. An answer is a claim a commit publishes, so a commit answers for the
# bytes it publishes; a later commit's apology is not retroactive.
#
# What this does NOT do, and says so on every run: it judges the commits in the
# range it was given, not all of history. Commits that predate the provenance
# manifest entirely have no answer set to be judged against, and are reported as
# NOT judged (a count and a list, never folded into a PASS) rather than buried
# under a finding per carrier per commit. Deleting the manifest does not buy
# that silence: once a commit in the range has published one, every later commit
# in the range is judged, and a commit that drops it is judged with no answers
# at all.

# The byte source of an entry read from a commit's tree. A view name, like
# WORKTREE_VIEW / STAGED_VIEW: `_read` resolves it through the same
# `git cat-file blob <oid>` path the staged view uses, because an index blob and
# a commit's blob are the same kind of object read the same way.
HISTORY_VIEW = "commit"

# How many commits the text report names individually per disclosure list (the
# COUNT is always printed; `--json` carries the full list either way).
HISTORY_COMMITS_LISTED = 10


def list_entries_at_commit(root: Path, sha: str):
    """[(rel, kind, oid)] for every entry commit `sha` publishes, sorted.

    The commit-tree counterpart of `list_entries`: `git ls-tree -r` is to a
    commit what `git ls-files -s` is to the index — the recorded MODE is read
    rather than guessed (so a symlink and a gitlink are seen as such), and the
    object id is how the bytes are read.
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", sha],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AuditError(
            f"cannot list the tree of {sha}: "
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    seen = {}
    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if not record:
            continue
        meta, _, rel = record.partition("\t")
        if not rel:
            continue
        fields = meta.split()
        if len(fields) < 3:
            continue
        mode, _type, oid = fields[0], fields[1], fields[2]
        seen.setdefault(rel, (GIT_MODE_KINDS.get(mode, "file"), oid))
    return sorted((rel, kind, oid) for rel, (kind, oid) in seen.items())


# Field separator for the one `git log` call that reads the range: a unit
# separator cannot occur in a commit subject.
_LOG_SEP = "\x1f"


def commit_log(root: Path, revrange):
    """[(sha, date, parents, subject)] for `revrange`, PARENTS BEFORE CHILDREN.

    `--topo-order --reverse` is not cosmetic: whether a commit that publishes no
    provenance manifest is "older than the manifest" or "deleted the manifest" is
    decided from its PARENTS, and in a merge-commit history (which this
    repository's is) a branch forked before the manifest landed carries trees
    that legitimately have none, interleaved by date with commits that do.
    Walking parents first is what lets each commit be judged against its own
    ancestry rather than against the calendar.

    A range that resolves to no commits is an AuditError, never an empty PASS:
    "nothing to audit" and "nothing offended" must not look alike.
    """
    args = [a for a in str(revrange).split() if a]
    if not args:
        raise AuditError("--commits needs a revision range (e.g. origin/main..HEAD)")
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "log",
            "--reverse",
            "--topo-order",
            "--date=short",
            f"--format=%H{_LOG_SEP}%ad{_LOG_SEP}%P{_LOG_SEP}%s",
            *args,
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AuditError(
            f"cannot resolve the commit range {revrange!r}: "
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    commits = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(_LOG_SEP)
        if len(parts) == 4:
            commits.append((parts[0], parts[1], parts[2].split(), parts[3]))
    if not commits:
        raise AuditError(
            f"the commit range {revrange!r} resolves to no commits — a range "
            "that audits nothing is not a pass"
        )
    return commits


def commit_publishes_manifest(root: Path, sha, memo):
    """Does commit `sha` publish a provenance manifest at all? (memoised)

    Asked of PARENTS, including parents outside the audited range, which is why
    it goes to git rather than reading the range's own bookkeeping: the question
    "did this commit delete the answer set" is about the commit before it,
    wherever that commit lives.
    """
    if sha in memo:
        return memo[sha]
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{sha}:{MANIFEST_REL}"],
        capture_output=True,
    )
    memo[sha] = proc.returncode == 0
    return memo[sha]


def commit_label(rel, sha):
    """`rel`, naming the commit whose bytes were judged.

    The history counterpart of `_view_label`: once the audited set spans
    commits, a path alone does not say which published bytes offended.
    """
    return f"{rel} [commit {sha[:12]}]"


def _walk_entries(root: Path):
    """Filesystem fallback for a tree that is not a git checkout.

    A directory that holds a `.git` entry is reported as a "gitlink": a nested
    repository checkout is the same by-reference carriage shape as a committed
    gitlink, and in a non-git tree (an unpacked tarball, a synthetic control
    tree) it is the only way to see one. It is not descended into — its files
    belong to that other repository, not this one.
    """
    out = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for path in children:
            if path.name in (".git", "__pycache__"):
                continue
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                out.append((rel, "symlink", ""))
            elif path.is_dir():
                if (path / ".git").exists():
                    out.append((rel, "gitlink", ""))
                    continue
                stack.append(path)
            elif path.is_file():
                out.append((rel, "file", ""))
    return out


SUBMODULE_PATH_RE = re.compile(r"^\s*path\s*=\s*(.+?)\s*$")
SUBMODULE_URL_RE = re.compile(r"^\s*url\s*=\s*(.+?)\s*$")


def parse_gitmodules(root: Path):
    """{submodule path: url} from `.gitmodules`, best effort (evidence only)."""
    try:
        text = (root / ".gitmodules").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return parse_gitmodules_text(text)


def parse_gitmodules_text(text):
    """The same parse, from text already in hand.

    Split out for the history pass (increment 17): a commit's `.gitmodules` is a
    blob in that commit, not a file on disk, and reading the working-tree copy
    there would describe the wrong tree.
    """
    urls = {}
    path = None
    for line in text.splitlines():
        if line.lstrip().startswith("["):
            path = None
            continue
        match = SUBMODULE_PATH_RE.match(line)
        if match:
            path = match.group(1)
            continue
        match = SUBMODULE_URL_RE.match(line)
        if match and path:
            urls[path] = match.group(1)
    return urls


class Tree:
    """In-scope entry set (with kinds) plus cached text reads."""

    def __init__(self, root: Path, exclusions, include_untracked=False,
                 default_view=WORKTREE_VIEW, share_reads_from=None,
                 entries=None, primary_view=WORKTREE_VIEW, signal_cache=None):
        self.root = root
        self.exclusions = exclusions
        # The view that carries this tree's STRUCTURAL signals — an entry's
        # kind, its extension (increment 17). For every tree built over the
        # working checkout that is the working-tree view; for a commit tree it is
        # the commit's own blobs, which are the only bytes that tree has. It is
        # NOT the same question as `default_view`: the committable pass
        # (increment 15) reads committable BYTES while its entries are still the
        # working checkout's, and its primary view stays the working tree.
        self.primary_view = primary_view
        self.history = primary_view == HISTORY_VIEW
        # Carriage signals already derived for a (path, blob) pair, shared across
        # the commits of a history run (increment 17). Signals are a function of
        # a regular file's path and bytes alone, so a blob that survives 200
        # commits is scanned once; the ANSWERS are still re-derived per commit,
        # because they are what differs between commits. `None` disables it.
        self.signal_cache = signal_cache
        # Which bytes this tree reads when a caller names no view (increment
        # 15). `WORKTREE_VIEW` is the historical behaviour and stays the
        # default, so every existing call site is unchanged; `COMMITTED_VIEW`
        # makes the same code read what a commit would publish.
        self.default_view = default_view
        # `entries` is supplied only by the history pass, which enumerates a
        # COMMIT's tree rather than this checkout's index (increment 17).
        entries = list_entries(root) if entries is None else sorted(entries)
        # Present in the working tree, absent from the index (increment 11).
        # Always computed, because the COUNT is coverage that is reported
        # whether or not the entries are audited; `include_untracked` decides
        # only whether they also become ordinary entries. A commit's tree has no
        # working copy to be untracked relative to.
        self.untracked = [] if self.history else list_untracked(root)
        self.include_untracked = include_untracked
        if include_untracked:
            known = {rel for rel, _, _ in entries}
            entries = sorted(
                list(entries)
                + [
                    (rel, "symlink" if (root / rel).is_symlink() else "file", "")
                    for rel in self.untracked
                    if rel not in known
                ]
            )
        self.all_files = [rel for rel, _, _ in entries]
        self.kinds = {rel: kind for rel, kind, _ in entries}
        self.gitlink_commits = {
            rel: blob for rel, kind, blob in entries if kind == "gitlink" and blob
        }
        # Blob ids of the STAGED content of every entry that HAS content of its
        # own (increment 14). A gitlink's object is a commit in another
        # repository, not a blob here, so it is deliberately absent: its
        # by-reference carriage is judged from the index at the discovery layer
        # and its bytes are outside this audit in both views.
        self.index_blobs = {
            rel: blob for rel, kind, blob in entries if blob and kind != "gitlink"
        }
        # A commit's `.gitmodules` is a blob in that commit; read below, once the
        # caches exist, rather than from the working-tree copy of another tree.
        self.submodule_urls = {} if self.history else parse_gitmodules(root)
        self.excluded = {}
        # Gitlinks under a declared exclusion prefix (increment 13). A declared
        # exclusion is a hole in CONTENT scanning — "this prefix's bytes are
        # not product content, their provenance is the install as a whole" —
        # and a gitlink has no bytes of its own for that statement to be about.
        # Letting the prefix swallow it hid the single highest-volume entry a
        # tree can carry (a whole other repository) behind a line of manifest
        # text, while `symlink_escape()` was meanwhile treating a link INTO the
        # same prefix as a reportable escape: a hole you can point at but not
        # mount. So the existence of a by-reference entry is judged; only its
        # (nonexistent) content is excluded. Kept separately from
        # `self.excluded` so the exclusion is not double-counted as both
        # scanned and excluded, and so `scope-exclusion-stale` still sees a
        # prefix whose only member is a gitlink as live rather than stale.
        self.excluded_by_reference = {}
        self.files = []
        for rel in self.all_files:
            hit = self.excluded_by(rel)
            if hit is None:
                self.files.append(rel)
            elif self.kinds.get(rel) == "gitlink":
                self.excluded_by_reference.setdefault(hit, []).append(rel)
                self.files.append(rel)
            else:
                self.excluded.setdefault(hit, []).append(rel)
        # In-scope entries whose staged bytes are not known to equal the working
        # tree's, and which therefore get a SECOND content view (increment 14).
        # A path inside a declared scope exclusion is left out for the same
        # reason increment 11 leaves one out of its count: it is already
        # disclosed as a hole, and counting it here would read as coverage the
        # audit does not have.
        # A commit's tree has one view of each entry: the blob it names. There is
        # no index-vs-working-tree divergence to read there.
        self.staged_divergent = [] if self.history else list_staged_divergent(root)
        self.staged_views = [
            rel
            for rel in self.staged_divergent
            if rel in self.index_blobs and self.excluded_by(rel) is None
        ]
        self._staged_view_set = set(self.staged_views)
        # Read caches are keyed by (rel, VIEW), and a view's bytes do not depend
        # on which scope exclusions a manifest declares — so a second tree built
        # over the same root for the committable answer set shares them by
        # reference rather than re-inflating every payload (increment 15).
        self._text_cache = {}
        self._lower_cache = {}
        # How each file's text was obtained, and which scans were cut short.
        # Coverage is reported from these, so they are bookkeeping, not debug
        # state: a file scanned only as extracted strings has NOT had its whole
        # payload read as prose, and a truncated unwrap has not been read at all
        # past its budget.
        self._scan_modes = {}
        self._truncated = set()
        # Names a wrapper carries INSIDE it (increment 9). Bookkeeping, not
        # debug state: these are the only description a marker-free member has,
        # and the coverage line reports how many were read.
        self._carried_names = {}
        # Wide-encoded runs harvested from a payload (increment 10). Reported as
        # coverage for the same reason: a payload whose wide runs were never
        # examined must not look like one that carried none.
        self._wide_runs = {}
        # (rel, view) pairs a BOOKKEEPING check actually read as evidence
        # (increment 16). Reported as coverage, and NOT shared with a second
        # tree: the point of the count is which views THIS pass consulted, and
        # a tree whose staged views were read only by group 4 must not look
        # like one whose citations and provenance rows were checked against
        # them. Deliberately recorded at the point of a successful read, not
        # derived from `staged_views`, so a view the prefilter skipped or the
        # encoding sniff refused is not counted as examined.
        self._bookkeeping_reads = set()
        if share_reads_from is not None:
            self._text_cache = share_reads_from._text_cache
            self._lower_cache = share_reads_from._lower_cache
            self._scan_modes = share_reads_from._scan_modes
            self._truncated = share_reads_from._truncated
            self._carried_names = share_reads_from._carried_names
            self._wide_runs = share_reads_from._wide_runs
        if self.history and ".gitmodules" in self.index_blobs:
            self.submodule_urls = parse_gitmodules_text(self.text(".gitmodules") or "")

    def _key(self, rel, view):
        """Cache key for one read.

        The blob id joins the key for a commit view (increment 17): the same path
        holds different bytes in different commits, and a cache keyed on the path
        alone would answer a later commit's read with an earlier commit's text.
        """
        if view == HISTORY_VIEW:
            return (rel, view, self.index_blobs.get(rel, ""))
        return (rel, view)

    def view_for(self, rel):
        """The byte source this tree reads `rel` as when no view is named.

        The only non-trivial case is `COMMITTED_VIEW` (increment 15): the
        committable bytes of a DIVERGENT entry are its index blob, and of every
        other entry its working-tree copy — which git has just told us is the
        same content, so this is a cheaper spelling of the same read and not a
        weaker one. An entry with no blob in the index (a gitlink) is never in
        `staged_views`, so it keeps its by-reference treatment in both.
        """
        if self.default_view != COMMITTED_VIEW:
            return self.default_view
        if rel in self.index_blobs and rel not in self._staged_view_set:
            return WORKTREE_VIEW
        # No blob in the index (an entry `git rm --cached` left on disk, an
        # untracked path, a gitlink) or a divergent one: either way the answer
        # comes from the index, and for the first group that is deliberately
        # NOTHING — the working-tree copy must not stand in for content no
        # commit would publish.
        return STAGED_VIEW

    def divergent_bookkeeping(self):
        """Files that ANSWER findings rather than raise them, and that differ.

        Non-empty means this tree has two different answer sets — one on disk,
        one in the index — and the committable one has to be judged on its own.
        Reported as coverage on every run, empty included, for the same reason
        increment 14 prints its divergence list even when zero.

        Two ways an answer set can differ, not one. The obvious one is a
        staged-divergent file (increment 14's set). The other is a bookkeeping
        file in the working tree and NOT in the index — a record written and
        never staged, or a manifest `git rm --cached` left on disk. Its
        committable content is nothing at all, which is the largest possible
        difference, and leaving it out would have made the absent-manifest case
        the one shape the committable pass never looked at.
        """
        return sorted(
            {rel for rel in self.staged_views if _is_bookkeeping(rel)}
            | {rel for rel in self.untracked if _is_bookkeeping(rel)}
        )

    def note_bookkeeping_read(self, rel, view):
        """Record that a bookkeeping check read this view's bytes as evidence."""
        self._bookkeeping_reads.add((rel, view))

    def staged_views_read_as_evidence(self):
        """Staged views a bookkeeping check read (increment 16).

        Reported on every run, zero included: before increment 16 the staged
        views existed, were disclosed, and were read by the carriage rules
        alone — so "the bookkeeping groups agreed with the staged bytes" and
        "the bookkeeping groups never looked at them" were indistinguishable.
        """
        return sorted(rel for rel, view in self._bookkeeping_reads if view != WORKTREE_VIEW)

    def untracked_not_audited(self):
        """In-scope working-tree entries this run did NOT audit (increment 11).

        Empty when `--include-untracked` is on (they were audited) and when a
        path falls in a declared scope exclusion (already disclosed as a hole).
        """
        if self.include_untracked:
            return []
        return [rel for rel in self.untracked if self.excluded_by(rel) is None]

    def by_reference_inside_exclusions(self):
        """Gitlinks a declared exclusion covers but does not hide (increment 13).

        Reported as coverage on every run, zero included: an exclusion that
        happens to contain no submodule must not look like one whose submodule
        was never examined.
        """
        return sorted(
            rel for rels in self.excluded_by_reference.values() for rel in rels
        )

    def excluded_by(self, rel):
        for prefix in self.exclusions:
            if rel == prefix:
                return prefix
            # Path-boundary match only: an unslashed prefix like "corpus"
            # must not also match "corpus-eval/…" (PR #114 review, nit 3).
            boundary = prefix if prefix.endswith("/") else prefix + "/"
            if rel.startswith(boundary):
                return prefix
        return None

    def kind(self, rel):
        """"file" | "symlink" | "gitlink" — what sort of entry `rel` is."""
        return self.kinds.get(rel, "file")

    def staged_only(self):
        """Divergent entries with NO working-tree copy at all (increment 14).

        Reported separately because this is the shape whose working-tree view
        reaches no content rule: `open()` fails, the entry is recorded
        "unreadable" and counted among the opaque payloads, while its staged
        blob is the content a commit would publish.
        """
        return [rel for rel in self.staged_views if not os.path.lexists(self.root / rel)]

    def text(self, rel, view=None):
        """Text for the content rules, or None when the entry yields none.

        `view` selects the BYTE SOURCE (increment 14): the working-tree file, or
        the entry's staged blob. Both are read for an entry whose staged bytes
        and working-tree bytes differ — the working-tree view because an
        unstaged paste must still fire before a `git add`, the staged view
        because the index is what `git commit` publishes. `None` means "this
        tree's own default view" (increment 15), which is how the BOOKKEEPING
        groups — which name no view, because an answer set is one tree-wide
        thing rather than a per-entry choice — get moved onto the committable
        bytes without touching their call sites.

        A file this returns None for is scanned by NOTHING except the
        extension tripwires — so every step below is a detection surface, not a
        performance detail. Two increments of masking lived here:

          * treating "a NUL byte appears in the head" as "binary" let a
            UTF-16-encoded source file, or an ASCII one carrying a single stray
            NUL, carry a complete foreign license body, SPDX tag and copyright
            notice past every content rule (controls `masking/*-encoded-*`,
            `masking/stray-nul-*`);
          * treating an undecodable payload as opaque let a WRAPPER (a gzipped
            source file, a zip or tar renamed `.dat`) and an EMBEDDED notice (a
            WAV `LIST/INFO` copyright chunk, a notice spliced into a float dump)
            do the same (controls `payload/*`);
          * harvesting only the ASCII runs of such a payload let the same notice
            through once it was re-saved in a WIDE encoding — a "Unicode" save
            spliced into a render, a float dump or an opaque archive member
            (controls `payload/wide-*`, `payload/utf32-*`).

        So the order is: resolve an encoding; failing that, unwrap wrappers by
        magic and read their members; failing that, harvest the payload's
        word-bearing ASCII runs and its wide-encoded ones. What each file got is recorded in
        `_scan_modes` and reported as coverage — a strings-only scan is weaker
        than a decode, and says so, rather than being counted as a full read.
        """
        view = self.view_for(rel) if view is None else view
        key = self._key(rel, view)
        if key in self._text_cache:
            return self._text_cache[key]
        value, mode, truncated, names, wide = self._read(rel, view)
        self._scan_modes[key] = mode
        self._carried_names[key] = tuple(names)
        self._wide_runs[key] = wide
        if truncated:
            self._truncated.add(_view_label(rel, view))
        self._text_cache[key] = value
        return value

    def _read(self, rel, view=WORKTREE_VIEW):
        """(text|None, scan mode, truncated, member names, wide runs) for a view."""
        if view in (STAGED_VIEW, HISTORY_VIEW):
            raw = read_index_blob(self.root, self.index_blobs.get(rel, ""))
            if raw is None:
                # The index holds no blob for this entry (a gitlink), or git
                # could not produce it. Recorded as unread, never as clean.
                return None, "unreadable", False, (), 0
            encoding = sniff_encoding(raw[:BINARY_SNIFF_BYTES])
        else:
            try:
                with (self.root / rel).open("rb") as handle:
                    head = handle.read(BINARY_SNIFF_BYTES)
                    encoding = sniff_encoding(head)
                    raw = head + handle.read()
            except OSError:
                # A by-reference entry (a gitlink, a symlink to a directory), a
                # staged entry whose working copy was deleted, and an unreadable
                # file all land here. The discovery layer judges the first; the
                # second is answered by its staged view (increment 14).
                return None, "unreadable", False, (), 0
        if encoding is not None:
            value = raw.decode(encoding, "replace")
            # A stray NUL survives the narrow decode as U+0000 and would split a
            # regex's word gap; it is masking noise, not content. Drop it so the
            # signal layer sees the real text.
            if "\0" in value:
                value = value.replace("\0", "")
            return value, "decoded", False, (), 0
        entries, truncated = unwrap_payload(raw)
        if entries is not None:
            parts = []
            wide = 0
            for _, payload in entries:
                member_encoding = sniff_encoding(payload[:BINARY_SNIFF_BYTES])
                if member_encoding is None:
                    # A member the sniff refuses gets the same payload read as a
                    # committed one, wide runs included: a wrapper is not a place
                    # a re-encoded notice may hide (increment 10).
                    part, member_wide = harvest_payload(payload)
                    parts.append(part)
                    wide += member_wide
                else:
                    parts.append(
                        payload.decode(member_encoding, "replace").replace("\0", "")
                    )
            value = "\n".join(part for part in parts if part)
            names = tuple(name for name, _ in entries if name)
            # Scan mode describes the CONTENT read, as before: a wrapper whose
            # members are all opaque still read no text, and saying otherwise
            # because a NAME was recovered would overstate the content coverage.
            return (
                (value or None),
                ("unwrapped" if value else "none"),
                truncated,
                names,
                wide,
            )
        value, wide = harvest_payload(raw)
        return (value or None), ("strings" if value else "none"), truncated, (), wide

    def scan_mode(self, rel, view=None):
        """"decoded" | "unwrapped" | "strings" | "none" | "unreadable"."""
        view = self.view_for(rel) if view is None else view
        if self._key(rel, view) not in self._scan_modes:
            self.text(rel, view)
        return self._scan_modes.get(self._key(rel, view), "unreadable")

    def carried_names(self, rel, view=None):
        """Member names the wrapper at `rel` carries inside it (may be empty).

        Forces the read, like `scan_mode`: the unwrap that recovers these names
        happens there. Empty for every entry that is not a wrapper the audit
        could open — a corrupt stream and anything past the depth/inflation
        budget carry no names here, and that partial read is disclosed as a
        TRUNCATED payload scan rather than counted as a pass.
        """
        view = self.view_for(rel) if view is None else view
        if self._key(rel, view) not in self._carried_names:
            self.text(rel, view)
        return self._carried_names.get(self._key(rel, view), ())

    def wide_runs(self, rel, view=None):
        """How many wide-encoded runs this entry's payload yielded (increment 10).

        Forces the read, like `scan_mode`. Zero for a decoded file — a file the
        sniff admits is read whole, in its own encoding, by every content rule.
        """
        view = self.view_for(rel) if view is None else view
        if self._key(rel, view) not in self._wide_runs:
            self.text(rel, view)
        return self._wide_runs.get(self._key(rel, view), 0)

    def truncated_scans(self):
        """Paths whose payload scan hit the inflation/depth budget.

        A staged view carries its view in the label, so a truncated read of the
        committable bytes is not reported as if the working-tree copy had been
        the one cut short.
        """
        return sorted(self._truncated)

    def lower(self, rel, view=None):
        """Lowercased text — the cheap prefilter for every signal.

        Cached for ordinary decoded files. A payload-derived text (an inflated
        trace, a harvested render) is NOT cached: keeping a second copy of every
        unwrapped payload roughly doubled the audit's peak memory, and
        `str.lower()` on the few large ones costs milliseconds.
        """
        view = self.view_for(rel) if view is None else view
        key = self._key(rel, view)
        if key in self._lower_cache:
            return self._lower_cache[key]
        text = self.text(rel, view)
        value = None if text is None else text.lower()
        if value is None or self._scan_modes.get(key) == "decoded":
            self._lower_cache[key] = value
        return value


# --- pattern handling ---------------------------------------------------------


def glob_to_regex(pattern: str):
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def pattern_problem(pattern: str):
    """Reject blanket patterns: the last segment must name a file or *.ext.

    A bare `reports/**` would silently cover any future file of any type —
    exactly the hole this audit exists to close.
    """
    if not pattern or pattern.startswith("/") or ".." in pattern.split("/"):
        return "pattern must be a relative repo path"
    if "**" in pattern.replace("**/", ""):
        return "'**' is only allowed as a '**/' directory wildcard"
    last = pattern.rsplit("/", 1)[-1]
    if "*" in last and not re.fullmatch(r"\*\.[A-Za-z0-9]+", last):
        return (
            "the last segment must be a literal file name or '*.ext' "
            f"(got {last!r}) — blanket patterns are not accepted"
        )
    return None


# --- decision records ---------------------------------------------------------


def status_keyword(text):
    if not text:
        return None
    first = re.split(r"[^A-Za-z-]+", text.strip(), maxsplit=1)[0].lower()
    return first or None


def parse_records(tree: Tree):
    """{number: {'path', 'status', 'status_keyword', 'date'}} for records on disk."""
    records = {}
    findings = []
    for rel in tree.files:
        parent, _, name = rel.rpartition("/")
        if parent != RECORD_DIR_REL:
            continue
        match = RECORD_FILE_RE.match(name)
        if not match:
            continue
        number = match.group(1)
        text = tree.text(rel) or ""
        status = _header_field(text, "Status")
        date = _header_field(text, "Date")
        if status is None or date is None:
            findings.append(
                Finding(
                    "record-header-missing",
                    rel,
                    "expected '- **Status**: …' and '- **Date**: …' header lines",
                )
            )
        keyword = status_keyword(status)
        if status is not None and keyword not in STATUS_VOCABULARY:
            findings.append(
                Finding(
                    "record-status-unrecognized",
                    rel,
                    f"status keyword {keyword!r} not in {list(STATUS_VOCABULARY)}",
                )
            )
        records[number] = {
            "path": rel,
            "status": status,
            "status_keyword": keyword,
            "date": date,
        }
    return records, findings


def _header_field(text, field):
    pattern = re.compile(
        r"^[-*]\s*\*\*" + field + r"\*\*:?\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    pattern = re.compile(
        r"^[-*]\s*\*\*" + field + r":\*\*\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def parse_index(tree: Tree):
    """{number: {'link', 'title', 'status', 'date', 'line'}} from the index table."""
    text = tree.text(INDEX_REL)
    if text is None:
        raise AuditError(f"{INDEX_REL} is missing or unreadable")
    rows = {}
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = INDEX_ROW_RE.match(line)
        if not match:
            continue
        number, link, title, status, date = match.groups()
        if number in rows:
            findings.append(
                Finding(
                    "index-duplicate-row",
                    INDEX_REL,
                    f"record {number} listed twice (line {lineno} and "
                    f"line {rows[number]['line']})",
                )
            )
            continue
        rows[number] = {
            "link": link.strip(),
            "title": title.strip(),
            "status": status.strip(),
            "date": date.strip(),
            "line": lineno,
        }
    return rows, findings


def check_index(records, rows):
    findings = []
    for number in sorted(records):
        record = records[number]
        row = rows.get(number)
        if row is None:
            findings.append(
                Finding(
                    "index-missing-row",
                    record["path"],
                    f"record {number} is on disk but has no row in {INDEX_REL} "
                    "(add one; the index is the visible list of decisions)",
                )
            )
            continue
        expected_link = record["path"].split("/")[-1]
        if row["link"] != expected_link:
            findings.append(
                Finding(
                    "index-unknown-record",
                    INDEX_REL,
                    f"row {number} links to {row['link']!r}, expected "
                    f"{expected_link!r}",
                )
            )
        row_keyword = status_keyword(row["status"])
        if record["status_keyword"] and row_keyword != record["status_keyword"]:
            findings.append(
                Finding(
                    "index-status-mismatch",
                    INDEX_REL,
                    f"row {number} says {row['status']!r} "
                    f"({row_keyword!r}) but the record says "
                    f"{record['status']!r} ({record['status_keyword']!r})",
                )
            )
        if record["date"] and row["date"] != record["date"]:
            findings.append(
                Finding(
                    "index-date-mismatch",
                    INDEX_REL,
                    f"row {number} says date {row['date']!r} but the record "
                    f"says {record['date']!r}",
                )
            )
    for number in sorted(rows):
        if number not in records:
            findings.append(
                Finding(
                    "index-unknown-record",
                    INDEX_REL,
                    f"row {number} has no matching decision-records/{number}-*.md",
                )
            )
    numbers = sorted(int(n) for n in records)
    for expected, actual in enumerate(numbers, start=1):
        if expected != actual:
            findings.append(
                Finding(
                    "index-number-gap",
                    RECORD_DIR_REL,
                    f"decision-record numbering is not contiguous: expected "
                    f"{expected:04d}, found {actual:04d} (a superseded record "
                    "stays on disk and is marked in its Status line)",
                )
            )
            break
    return findings


def check_citations(tree: Tree, records, rows):
    """A record citation must resolve in EVERY byte view that makes it.

    Group 2 reads an ENTRY's content, and until increment 16 it read exactly one
    view of it — the tree's default — so a citation present only in the bytes
    `git commit` publishes resolved against nothing and audited PASS, with the
    carrier disclosed as divergent and read by group 4 alone.

    A citation is a QUESTION the entry's bytes raise ("does this record exist,
    and is it indexed?"), so it is asked of both views for the same reason
    increment 14 asks a carriage question of both: an unstaged paste must fire
    before a `git add`, and a staged one must fire whatever the working copy
    says. The ANSWER (which records exist, which are indexed) still comes from
    the view that raised it — `records`/`rows` are parsed per pass, which is
    what increment 15's committable pass supplies here.
    """
    findings = []
    for rel in tree.files:
        if rel == MANIFEST_REL:
            continue
        for view in entry_views(tree, rel):
            low = tree.lower(rel, view)
            # Cheap prefilter (superset of RECORD_CITATION_RE): skip files that
            # cannot cite a record at all.
            if low is None or not any(
                token in low for token in ("decision-records/", "dr-0", "dr0")
            ):
                continue
            text = tree.text(rel, view)
            tree.note_bookkeeping_read(rel, view)
            for number in sorted(set(RECORD_CITATION_RE.findall(text))):
                if number not in records:
                    findings.append(
                        Finding(
                            "dangling-record-citation",
                            rel,
                            _staged_evidence(
                                view,
                                f"cites decision record {number}, which does "
                                "not exist",
                            ),
                        )
                    )
                elif number not in rows:
                    findings.append(
                        Finding(
                            "unindexed-record-citation",
                            rel,
                            _staged_evidence(
                                view,
                                f"cites decision record {number}, which is "
                                f"missing from the {INDEX_REL} index",
                            ),
                        )
                    )
    return findings


# --- manifest -----------------------------------------------------------------


REQUIRED_ENTRY_FIELDS = (
    "class",
    "content",
    "upstream",
    "upstream_license",
    "decision_record",
)


FROM_DISK = object()
"""Sentinel: `load_manifest` should open the working-tree copy itself.

Deliberately NOT `None`. A view can legitimately yield `None` — a manifest
`git rm --cached` left on disk, or a staged blob the encoding sniff refuses —
and if that were spelled the same as "no text supplied", the committable pass
would fall back to the copy on disk and answer from the very bytes this
increment exists to stop answering from.
"""


def load_manifest(root: Path, raw=FROM_DISK, label=MANIFEST_REL):
    """Parse the provenance manifest from `root`, or from `raw` text if given.

    `raw` is how the COMMITTABLE manifest is parsed (increment 15): the index
    blob's text, read through the tree's own cache. `label` is the path every
    finding quotes, so a finding about the staged manifest names the staged
    manifest rather than looking like one about the file on disk.
    """
    if raw is FROM_DISK:
        path = root / MANIFEST_REL
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, [Finding("manifest-missing", label, f"cannot read: {exc}")]
    if raw is None:
        return None, [
            Finding(
                "manifest-missing",
                label,
                "this view holds no readable manifest — a commit would publish "
                "none, so it answers nothing",
            )
        ]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [Finding("manifest-missing", label, f"invalid JSON: {exc}")]
    if not isinstance(data, dict):
        return None, [Finding("manifest-schema", label, "top level must be an object")]
    findings = []
    if data.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "manifest-schema",
                label,
                f"schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}",
            )
        )
    for key in ("entries", "exemptions", "scope_exclusions"):
        value = data.get(key, [])
        if not isinstance(value, list):
            findings.append(Finding("manifest-schema", label, f"{key!r} must be a list"))
            data[key] = []
    return data, findings


def scope_exclusion_prefixes(manifest):
    prefixes = []
    for item in (manifest or {}).get("scope_exclusions", []) or []:
        if isinstance(item, dict) and item.get("prefix"):
            prefixes.append(str(item["prefix"]))
    return prefixes


def _matcher(entry):
    """(kind, matcher) for an entry/exemption: exact path or extension glob."""
    if entry.get("path"):
        target = str(entry["path"])
        return "path", target, lambda rel: rel == target
    pattern = str(entry.get("pattern", ""))
    regex = glob_to_regex(pattern)
    return "pattern", pattern, lambda rel: bool(regex.match(rel))


def check_manifest(tree: Tree, manifest, records, rows, manifest_rel=MANIFEST_REL):
    """Validate rows/exemptions and return (findings, coverage).

    `manifest_rel` is the manifest path every finding here quotes. The committable
    pass (increment 15) passes the staged manifest's label, so a row that is
    wrong only in the bytes a commit would publish does not read as a finding
    about the file on disk — which is clean, and is what the author is
    looking at.
    """
    findings = []
    # rel -> set of tripwire rule ids this file's row(s) cover. Scoped per
    # rule, not blanket per-file: a row naming a file only suppresses the
    # rule(s) implied by that file's own extension plus whatever the row's
    # 'covers' field explicitly declares — never every rule the file happens
    # to trip (see PR #114 review, finding 1: an unrelated row was silently
    # laundering an appended, unmodified GPL license block past the
    # non-exemptible foreign-license-text tripwire).
    coverage = {}
    exemptions = {}  # rel -> {rule -> reason}

    for index, entry in enumerate(manifest.get("entries", []) or []):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            findings.append(Finding("manifest-schema", manifest_rel, f"{label} must be an object"))
            continue
        if bool(entry.get("path")) == bool(entry.get("pattern")):
            findings.append(
                Finding(
                    "manifest-field-missing",
                    manifest_rel,
                    f"{label}: exactly one of 'path' or 'pattern' is required",
                )
            )
            continue
        missing = [f for f in REQUIRED_ENTRY_FIELDS if not entry.get(f)]
        if missing:
            findings.append(
                Finding(
                    "manifest-field-missing",
                    manifest_rel,
                    f"{label} ({entry.get('path') or entry.get('pattern')}): "
                    f"missing required field(s) {missing}",
                )
            )
        if entry.get("class") and entry["class"] not in KNOWN_CLASSES:
            findings.append(
                Finding(
                    "manifest-unknown-class",
                    manifest_rel,
                    f"{label}: class {entry['class']!r} not in "
                    f"{sorted(KNOWN_CLASSES)}",
                )
            )
        kind, target, matches = _matcher(entry)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("manifest-bad-pattern", manifest_rel, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "manifest-stale-path",
                    manifest_rel,
                    f"{label}: {target!r} matches no in-scope file (stale row — "
                    "remove it or fix the path)",
                )
            )
        number = str(entry.get("decision_record") or "").strip()
        if number:
            if number not in records:
                findings.append(
                    Finding(
                        "manifest-missing-record",
                        manifest_rel,
                        f"{label}: decision_record {number!r} does not exist",
                    )
                )
            elif number not in rows:
                findings.append(
                    Finding(
                        "manifest-unindexed-record",
                        manifest_rel,
                        f"{label}: decision_record {number!r} is not in the index",
                    )
                )
        covers_raw = entry.get("covers")
        covers_declared = set()
        if covers_raw is not None:
            if not isinstance(covers_raw, list):
                findings.append(
                    Finding("manifest-schema", manifest_rel, f"{label}: 'covers' must be a list")
                )
            else:
                bad = [r for r in covers_raw if r not in TRIPWIRE_RULES]
                if bad:
                    findings.append(
                        Finding(
                            "manifest-schema",
                            manifest_rel,
                            f"{label}: 'covers' rule(s) {bad} not in {sorted(TRIPWIRE_RULES)}",
                        )
                    )
                covers_declared = {r for r in covers_raw if r in TRIPWIRE_RULES}
        for rel in hits:
            coverage.setdefault(rel, set()).update(
                _structural_tripwire_rules(tree, rel, entry) | covers_declared
            )
            findings.extend(_corroborate(tree, rel, entry, number, label))

    for index, item in enumerate(manifest.get("exemptions", []) or []):
        label = f"exemptions[{index}]"
        if not isinstance(item, dict):
            findings.append(Finding("manifest-schema", manifest_rel, f"{label} must be an object"))
            continue
        if bool(item.get("path")) == bool(item.get("pattern")):
            findings.append(
                Finding(
                    "exemption-field-missing",
                    manifest_rel,
                    f"{label}: exactly one of 'path' or 'pattern' is required",
                )
            )
            continue
        rules = item.get("rules")
        reason = str(item.get("reason") or "").strip()
        if not isinstance(rules, list) or not rules or not reason:
            findings.append(
                Finding(
                    "exemption-field-missing",
                    manifest_rel,
                    f"{label}: non-empty 'rules' list and 'reason' are required",
                )
            )
            rules = rules if isinstance(rules, list) else []
        bad = [r for r in rules if r not in EXEMPTIBLE_RULES]
        if bad:
            findings.append(
                Finding(
                    "exemption-non-exemptible-rule",
                    manifest_rel,
                    f"{label}: rule(s) {bad} cannot be exempted (only "
                    f"{sorted(EXEMPTIBLE_RULES)} may be); answer them with a "
                    "provenance row instead",
                )
            )
        # Optional 'occurrences': the exemption then covers only the named
        # quotation-marker occurrences in ONE exact file, never the whole
        # file — any other marker in that file (a real foreign quotation added
        # later, even with the same wording) still fails. Required to be an
        # exact path: an occurrence list on a glob would be a blanket.
        occurrences = item.get("occurrences")
        if occurrences is not None:
            if (
                not isinstance(occurrences, list)
                or not occurrences
                or not all(isinstance(o, str) and o.strip() for o in occurrences)
            ):
                findings.append(
                    Finding(
                        "exemption-field-missing",
                        manifest_rel,
                        f"{label}: 'occurrences' must be a non-empty list of "
                        "non-empty strings",
                    )
                )
                continue
            if not item.get("path"):
                findings.append(
                    Finding(
                        "exemption-bad-pattern",
                        manifest_rel,
                        f"{label}: 'occurrences' requires an exact 'path', not a pattern",
                    )
                )
                continue
        kind, target, matches = _matcher(item)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("exemption-bad-pattern", manifest_rel, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "exemption-stale",
                    manifest_rel,
                    f"{label}: {target!r} matches no in-scope file (stale "
                    "exemption — remove it)",
                )
            )
        for rel in hits:
            spans = None
            if occurrences is not None:
                spans = []
                text = tree.text(rel) or ""
                markers = quotation_marker_matches(text)
                for occurrence in occurrences:
                    located = [
                        (m.start(), m.end())
                        for m in occurrence_regex(occurrence).finditer(text)
                    ]
                    # A named occurrence must identify ONE place in the file.
                    # Matching the literal wording everywhere it appears would
                    # exempt a genuinely foreign quotation that happens to be
                    # worded as the exact same sentence with a different
                    # referent ("The Surge oscillator: `tb.sv` carries a
                    # verbatim copy of it."), which is indistinguishable from
                    # the legitimate self-copy by wording alone. Ambiguity is
                    # therefore a finding, not a silent widening: name the
                    # occurrence with enough surrounding text to be unique.
                    if len(located) > 1:
                        findings.append(
                            Finding(
                                "exemption-ambiguous",
                                MANIFEST_REL,
                                f"{label}: occurrence {occurrence!r} appears "
                                f"{len(located)} times in {rel}; an exemption "
                                "must name exactly one place (extend the quoted "
                                "text until it is unique)",
                            )
                        )
                        continue
                    live = [
                        (start, end)
                        for start, end in located
                        if any(start <= mk.start() and mk.end() <= end for _, mk in markers)
                    ]
                    if not live:
                        findings.append(
                            Finding(
                                "exemption-stale",
                                manifest_rel,
                                f"{label}: occurrence {occurrence!r} "
                                + (
                                    "contains no quotation marker"
                                    if located
                                    else "no longer appears"
                                )
                                + f" in {rel} (stale exemption — fix or remove it)",
                            )
                        )
                    spans.extend(live)
            for rule in rules:
                if rule in EXEMPTIBLE_RULES:
                    current = exemptions.setdefault(rel, {}).get(rule)
                    if current is not None and current["spans"] is None:
                        continue  # an unscoped exemption already covers the file
                    if spans is None or current is None:
                        # The occurrence LITERALS travel with the resolved spans:
                        # a second byte view of the same file needs its own
                        # offsets, and only the literals can produce them
                        # (increment 14).
                        exemptions[rel][rule] = {
                            "reason": reason,
                            "spans": spans,
                            "occurrences": None if occurrences is None else list(occurrences),
                        }
                    else:
                        current["spans"].extend(spans)
                        current["occurrences"] = (current.get("occurrences") or []) + list(
                            occurrences or []
                        )

    for index, item in enumerate(manifest.get("scope_exclusions", []) or []):
        label = f"scope_exclusions[{index}]"
        if not isinstance(item, dict) or not item.get("prefix") or not item.get("reason"):
            findings.append(
                Finding(
                    "manifest-schema",
                    manifest_rel,
                    f"{label}: 'prefix' and 'reason' are required",
                )
            )
            continue
        prefix = str(item["prefix"])
        # A prefix whose only member is a gitlink is NOT stale: it still
        # declares the hole, even though the gitlink itself is judged at the
        # discovery layer rather than excluded (increment 13).
        if not tree.excluded.get(prefix) and not tree.excluded_by_reference.get(prefix):
            findings.append(
                Finding(
                    "scope-exclusion-stale",
                    manifest_rel,
                    f"{label}: prefix {item['prefix']!r} excludes nothing "
                    "(stale — remove it)",
                )
            )

    floor = manifest.get("scan_floor")
    if isinstance(floor, int) and len(tree.files) < floor:
        findings.append(
            Finding(
                "scan-underflow",
                manifest_rel,
                f"scanned {len(tree.files)} in-scope files, below the declared "
                f"scan_floor of {floor} — the audit may have walked the wrong "
                "tree; a partial scan is not a pass",
            )
        )
    return findings, coverage, exemptions


def _pinned_commit_required(tree: Tree, rel, entry):
    """Why this row MUST carry a `pinned_commit`, or None (increment 13).

    The field is optional in general, and rightly so: a row describing quoted
    constants is corroborated by the file's own bytes, which the audit reads.
    It is not optional for a row describing content the audit never reads. A
    gitlink's entire content is "whatever that commit is", and
    `class: external-reference` says the same of a link into an external tree —
    the pin IS the description, so a row without one describes nothing
    checkable.

    Before this increment the field's absence also SHORT-CIRCUITED the gitlink
    arm's own comparison below (`actual and commit and …`), so the control that
    catches a row naming the WRONG commit was defeated by deleting the field
    rather than changing its value: a gitlink pinning the GPL engine, answered
    by a row with no pin at all, audited clean with no pin recorded anywhere
    (control `discovery/submodule-row-with-no-pinned-commit`).
    """
    if tree.kind(rel) == "gitlink":
        return f"{rel} is a committed gitlink, whose content is its commit"
    if str(entry.get("class") or "") == BY_REFERENCE_CLASS:
        return f"the row's class is {BY_REFERENCE_CLASS!r}"
    return None


def _corroborate(tree: Tree, rel, entry, number, label):
    """The file must show the provenance its row claims (row != reality guard).

    Checked against EVERY byte view the entry has (increment 16). The row is a
    claim this repository PUBLISHES, so the bytes a commit publishes have to
    carry the provenance it claims; and the working-tree copy has to as well,
    because an unstaged edit that strips the citation while the row stands is a
    real defect the author must see before `git add`. Until increment 16 only
    one view was read, so `git add`-ing a carrier with its citation removed and
    leaving the citing copy on disk audited PASS — and so did staging that
    carrier and deleting the working copy outright, where the only bytes a
    commit publishes were read by no bookkeeping check at all.
    """
    commit = str(entry.get("pinned_commit") or "").strip()
    kind = tree.kind(rel)
    if not commit:
        why = _pinned_commit_required(tree, rel, entry)
        if why is not None:
            return [
                Finding(
                    "manifest-field-missing",
                    MANIFEST_REL,
                    f"{label} ({rel}): missing required field "
                    f"['pinned_commit'] — {why}, so the row records nothing "
                    "this audit (or a reviewer) can check it against",
                )
            ]
    if kind == "gitlink":
        # A gitlink carries its own pin, so corroboration is exact here: the
        # commit in the index is what a build checks out, whatever the row says.
        # `commit` is non-empty by the guard above; `actual` can still be empty
        # for a nested repository in a non-git tree, which records no mode.
        actual = tree.gitlink_commits.get(rel)
        if actual and actual.lower() != commit.lower():
            return [
                Finding(
                    "manifest-uncorroborated",
                    rel,
                    f"{label}: the committed submodule points at {actual[:12]}, "
                    f"not the row's pinned_commit {commit[:12]} — the row "
                    "describes a tree this repository does not reference",
                )
            ]
        return []
    if kind == "symlink":
        escape = symlink_escape(tree, rel)
        if escape is not None:
            # The target is outside what this audit reads — an external tree, an
            # absolute path, a declared hole — WHETHER OR NOT it happens to be
            # checked out on the machine running the audit. There is no file
            # body in this tree in which to state provenance, so the row and its
            # record are the only description, as for a binary payload; the
            # structural tripwire is what makes the row mandatory in the first
            # place.
            #
            # Keyed on the escape, not on readability, because the previous
            # reading of the same reasoning ("the target is not readable here")
            # made the verdict depend on the auditing machine: one identical
            # committed tree audited PASS in CI, where the pinned oracle is not
            # checked out, and FAIL on a developer box that had it, where the
            # resolved UPSTREAM bytes were then required to cite one of this
            # repository's decision records. Requiring that is not a tooling
            # change — it would mean editing upstream bytes, which is #25's
            # question, not this tool's. DECLARED LIMIT, not a closed hole: for
            # an escaping link the row is corroborated by nothing but itself
            # (control
            # `discovery/declared-escaping-symlink-passes-whether-its-target-resolves-or-not`).
            return []
        # An in-tree target: the link resolves to content this audit scans at
        # its own path, so the row is still checked against what a reviewer
        # reads. The link target is what they read first; search it alongside.
        suffix = ""
        try:
            suffix = "\n" + os.readlink(tree.root / rel)
        except OSError:  # pragma: no cover - raced away
            pass
    else:
        suffix = ""
    tokens = []
    if number:
        tokens.append(f"decision-records/{number}")
        tokens.append(f"DR-{number}")
        tokens.append(f"DR{number}")
    if len(commit) >= 8:
        tokens.append(commit[:8])
    if not tokens:
        return []
    findings = []
    for view in entry_views(tree, rel):
        text = tree.text(rel, view)
        if text is None:
            # Binary payload (or, for the working-tree view of an entry staged
            # and then deleted, no file at all): nothing to read in THIS view,
            # so the row is the record here exactly as it always was. Declared
            # per view rather than per entry — which is what let the staged-only
            # shape past: its working-tree view yields None, and that answered
            # for the staged bytes too.
            continue
        tree.note_bookkeeping_read(rel, view)
        if any(token.lower() in (text + suffix).lower() for token in tokens):
            continue
        findings.append(
            Finding(
                "manifest-uncorroborated",
                rel,
                _staged_evidence(
                    view,
                    f"{label}: the file cites neither decision record "
                    f"{number or '????'} nor the pinned commit "
                    f"{commit[:12] or '(none given)'} — state the provenance in "
                    "the file, or fix the row",
                ),
            )
        )
    return findings


# --- tripwires ----------------------------------------------------------------


def _extension_suffix(rel):
    """The extension used for tripwire matching, `.gz` compression stripped.

    Without this, renaming any upstream asset or foreign-source file with a
    trailing `.gz` (`Bank Sine.wt.gz`, `copied_filter.cpp.gz`) drops it from
    both extension tripwires with no actual compression required — see PR
    #114 review, finding 3. The repository's own gzipped evidence traces
    (`*.json.gz`, `*.hex.gz`) fall through to an extension that is in neither
    set, so this does not newly flag them.
    """
    name = rel.rsplit("/", 1)[-1]
    if name.lower().endswith(".gz"):
        name = name[: -len(".gz")]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def member_name_signals(label):
    """[(component, suffix, what it is)] for one wrapper member's name label.

    EVERY `!`-joined component is judged, not just the last: a zip member named
    `Bank Sine.wt` that is itself a gzip would otherwise be labelled
    `Bank Sine.wt!inner.json` and read as a `.json`, which is the same
    "stop at the first answer" masking shape increments 2-5 closed on the
    license rule. The two extension sets are the ones that judge a file's own
    name, so a member name is held to exactly the standard its own path would
    be held to if it were committed unwrapped.
    """
    out = []
    for component in label.split(MEMBER_JOIN):
        suffix = _extension_suffix(component)
        if suffix in UPSTREAM_ASSET_EXTS:
            out.append((component, suffix, "upstream asset / opaque bundle"))
        elif suffix in FOREIGN_SOURCE_EXTS:
            out.append((component, suffix, "foreign-language source"))
    return out


def symlink_escape(tree: Tree, rel):
    """Why this symlink's target is not plain in-tree content, or None.

    A symlink that stays inside the tree and lands on in-scope content is not a
    carriage signal: whatever it points at is audited at its own path. What IS a
    signal is a link whose target the audit cannot see — absolute, escaping via
    `..`, unresolvable here, or inside a declared scope exclusion. In every one
    of those cases the bytes that reach a build are not the bytes this audit
    read, so only a provenance row can describe them.
    """
    link = tree.root / rel
    if tree.history:
        # A commit's symlink IS a blob whose content is the target path; the
        # working-tree copy at this path belongs to whatever is checked out now,
        # which is a different tree (increment 17).
        raw = read_index_blob(tree.root, tree.index_blobs.get(rel, ""))
        if raw is None:
            return "symlink target unreadable: the commit's blob could not be read"
        target = raw.decode("utf-8", "replace").strip()
        if not target:
            return "symlink with an empty target"
    else:
        try:
            target = os.readlink(link)
        except OSError:
            # The index says mode 120000 but the filesystem has no symlink here: a
            # `core.symlinks=false` checkout materialises the entry as a regular
            # file whose CONTENT is the target path. Read it that way rather than
            # inventing a finding on a rule that cannot be exempted.
            try:
                target = link.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:  # pragma: no cover - raced away
                return f"symlink target unreadable: {exc}"
            if not target:
                return "symlink with an empty target"
    if os.path.isabs(target):
        return f"absolute target outside the audited tree: {target!r}"
    logical = os.path.normpath(os.path.join(os.path.dirname(rel), target))
    if logical == ".." or logical.startswith(".." + os.sep) or logical.startswith("../"):
        return f"target escapes the audited tree: {target!r} -> {logical!r}"
    if tree.history:
        # Resolution against the COMMIT's own entry set, not the filesystem: the
        # question is whether the tree that commit publishes contains the target,
        # and a `resolve()` here would answer it from whatever is checked out now.
        inside = logical.replace(os.sep, "/")
        if inside not in tree.all_files and not any(
            other.startswith(inside + "/") for other in tree.all_files
        ):
            return f"target does not resolve in this commit's tree: {target!r}"
        excluded = tree.excluded_by(inside)
        if excluded is not None:
            return (
                f"target {inside!r} is under the declared scope exclusion "
                f"{excluded!r}, which this audit does not scan"
            )
        return None
    try:
        resolved = link.resolve(strict=True)
        root = tree.root.resolve()
    except (OSError, RuntimeError, ValueError):
        # Absent at audit time. This is the CI shape for a link into the
        # pinned oracle: the external working directory is not checked out, so
        # the content is invisible here but present wherever the link resolves.
        return f"target does not resolve in this tree: {target!r}"
    try:
        inside = resolved.relative_to(root).as_posix()
    except ValueError:
        return f"target resolves outside the audited tree: {str(resolved)!r}"
    excluded = tree.excluded_by(inside)
    if excluded is not None:
        return (
            f"target {inside!r} is under the declared scope exclusion "
            f"{excluded!r}, which this audit does not scan"
        )
    return None


def submodule_evidence(tree: Tree, rel):
    """Finding evidence for a committed gitlink / nested repository."""
    commit = tree.gitlink_commits.get(rel)
    url = tree.submodule_urls.get(rel)
    detail = "committed submodule / nested repository"
    if commit:
        detail += f" pinned at {commit[:12]}"
    if url:
        detail += f", url {url}"
    detail += " — its files are in the build tree but not in this audit"
    excluded = tree.excluded_by(rel)
    if excluded is not None:
        # The locator a reviewer needs: the entry is inside a declared hole, so
        # it looks exempted and is not. An exclusion withholds content from the
        # content rules; it cannot withhold the existence of another repository.
        detail += (
            f"; it sits under the declared scope exclusion {excluded!r}, which "
            "withholds content from the content rules but does not hide a "
            "by-reference entry"
        )
    return detail


def _extension_tripwire_rules(rel):
    """Tripwire rule ids implied purely by `rel`'s own (de-gzipped) extension.

    These are structural properties of the whole file — every byte of a `.wt`
    file is upstream-asset content by virtue of being a `.wt` file — so a
    provenance row naming this exact file safely covers them in full. This is
    unlike the content-signal tripwires (`foreign-license-text`,
    `self-declared-quotation`), which can appear anywhere in a file's text
    independent of what the row's 'content' field describes, and therefore
    require an explicit 'covers' declaration instead of blanket coverage
    (see PR #114 review, finding 1).
    """
    suffix = _extension_suffix(rel)
    rules = set()
    if suffix in UPSTREAM_ASSET_EXTS:
        rules.add("upstream-asset-extension")
    if suffix in FOREIGN_SOURCE_EXTS:
        rules.add("foreign-source-language")
    return rules


def _structural_tripwire_rules(tree: Tree, rel, entry):
    """Tripwire rules implied by the ENTRY itself, not by any text it holds.

    Extension rules plus the by-reference kinds. Like an extension rule, the
    kind is a property of the whole entry — a gitlink *is* a reference to
    another tree, a symlink *is* its target — so a row naming this exact path
    describes it in full and covers the rule without a 'covers' declaration.
    The content-signal rules still require 'covers', because text can appear
    anywhere in a file regardless of what the row's 'content' field says.

    The two by-reference rules additionally require the row to be of the class
    that describes a by-reference entry (increment 13). Before that, ANY row at
    the exact path covered them: a row whose class said
    "restates an upstream attribution, carries no upstream content" answered a
    committed GPL engine checkout, with the row and its record — the only
    description a by-reference entry has — describing something else entirely.
    A row of the wrong class is not a laundering trick to catch, it is a row
    that does not say what the rule needs said; `external-reference` was
    already named as the required class both in `KNOWN_CLASSES` and in the
    manifest's own notes, so what moved was the enforcement, not the contract
    (control `discovery/gitlink-answered-by-a-row-of-the-wrong-class`).
    """
    rules = _extension_tripwire_rules(rel)
    kind = tree.kind(rel)
    by_reference = {
        "gitlink": "submodule-reference",
        "symlink": "external-symlink-target",
    }
    row_class = str((entry or {}).get("class") or "")
    if kind in by_reference and row_class == BY_REFERENCE_CLASS:
        rules.add(by_reference[kind])
    return rules


def tripwire_hits(tree: Tree, rel, view=WORKTREE_VIEW):
    """`_tripwire_hits`, memoised per (path, blob) when a cache is in use.

    The history pass (increment 17) audits one tree per commit, and a blob that
    survives two hundred commits would otherwise be scanned two hundred times.
    Signals are a function of a REGULAR file's path and bytes, so (path, blob) is
    a sound key for those; a by-reference entry is deliberately not cached, since
    its evidence is read from the tree around it (`.gitmodules`, the declared
    exclusions, where the link resolves) and not from bytes of its own. The
    ANSWERS are never cached — they are precisely what differs between commits.
    """
    cache = tree.signal_cache
    if cache is None or tree.kind(rel) != "file":
        return _tripwire_hits(tree, rel, view)
    key = (rel, tree.index_blobs.get(rel, ""), view)
    if key not in cache:
        cache[key] = _tripwire_hits(tree, rel, view)
    return cache[key]


def _tripwire_hits(tree: Tree, rel, view=WORKTREE_VIEW):
    """[(rule, evidence)] for content signals of third-party carriage.

    Each signal is gated behind a cheap lowercase substring prefilter; the
    regexes below only run on files that could match. The prefilter tokens
    must stay a SUPERSET of what each regex can match, or the rule silently
    stops firing — `--negative-control` is what catches that mistake.

    `view` selects which bytes of `rel` are judged (increment 14). The
    structural signals — the by-reference kinds and the extension sets — are
    properties of the ENTRY and of its path, identical in both views, so they
    are evaluated once, on the tree's PRIMARY view; a secondary (staged) view
    runs the content signals and the wrapper-member-name signal, which are the
    ones that read bytes.

    "Primary" rather than "the working tree" because of increment 17: a commit
    tree's only view is the commit's own blobs, and gating the structural signals
    on `view == WORKTREE_VIEW` would have made every extension rule and both
    by-reference rules silently unreachable there — a whole rule group answering
    "nothing offended" for a view it never examined.
    """
    hits = []
    # The discovery layer first: an entry that carries its content by reference
    # has no bytes of its own for any signal below to read.
    kind = tree.kind(rel)
    primary = view == tree.primary_view
    if not primary:
        if kind == "gitlink":
            # A gitlink's object is a commit in another repository, not a blob
            # here: there is no staged payload to read. Its carriage is judged
            # at the discovery layer on the working-tree pass.
            return hits
    elif kind == "gitlink":
        # Nothing further applies: a gitlink has no extension and no text.
        return [("submodule-reference", submodule_evidence(tree, rel))]
    elif kind == "symlink":
        escape = symlink_escape(tree, rel)
        if escape is not None:
            hits.append(("external-symlink-target", escape))
        # Deliberately NOT a return: `text()` follows the link, so a target
        # that does resolve is still read by every content rule below.
    if primary:
        suffix = _extension_suffix(rel)
        if suffix in UPSTREAM_ASSET_EXTS:
            hits.append(("upstream-asset-extension", f"extension {suffix}"))
        if suffix in FOREIGN_SOURCE_EXTS:
            hits.append(("foreign-source-language", f"extension {suffix}"))
    # The names a wrapper carries INSIDE it, before the content rules: a member
    # that carries no marker at all (a `.wt` payload, a stripped `.cpp`) reaches
    # none of them, and `text()` is None for a wrapper whose members are all
    # opaque — so judging names after the `text is None` return would have left
    # the whole class unanswered. `carried_names` forces that read itself.
    offenders = [
        (label, signal)
        for label in tree.carried_names(rel, view)
        for signal in member_name_signals(label)
    ]
    if offenders:
        label, (component, member_suffix, what) = offenders[0]
        evidence = (
            f"wrapper member {component!r} ({what}, extension {member_suffix})"
        )
        if label != component:
            evidence += f", carried at {label!r}"
        if len(offenders) > 1:
            evidence += f", and {len(offenders) - 1} more member name(s)"
        hits.append(("wrapper-member-name", evidence))
    text = tree.text(rel, view)
    if text is None:
        return hits
    low = tree.lower(rel, view)
    if rel not in OWN_LICENSE_PATHS:
        for name, prefilter, regex in FOREIGN_LICENSE_BODY_RES:
            if prefilter not in low:
                continue
            match = regex.search(text)
            if match:
                hits.append(("foreign-license-text", f"{name}: {_snippet(text, match)}"))
                break
        # EVERY tag/line is inspected, not just the first: an own Apache tag or
        # own copyright header sitting ABOVE a pasted upstream header must not
        # mask it. `.search()` here made both signals silently stop firing in
        # exactly that layout — the false-negative shape this audit exists to
        # prevent, on a rule that cannot be exempted (issue #25, acceptance
        # item 4; controls `masking/*` in --negative-control).
        if "spdx-license-identifier" in low:
            for spdx in SPDX_RE.finditer(text):
                # EVERY operand of the expression, not just the leading one:
                # "Apache-2.0 OR GPL-3.0-or-later" is a foreign tag.
                foreign = spdx_foreign_ids(spdx.group(1))
                if foreign:
                    # Label assembled from fragments (see the fixture note below).
                    hits.append(
                        (
                            "foreign-license-text",
                            "SPDX-License" + "-Identifier tag: " + ", ".join(foreign),
                        )
                    )
                    break
        if any(token in low for token in COPYRIGHT_PREFILTERS):
            # EVERY notice is inspected (an own header above a pasted one must
            # not mask it), each judged from its own holder field, and a notice
            # may carry no year or wrap its holder list onto the next line.
            copyright_match = foreign_copyright_match(text)
            if copyright_match is not None:
                hits.append(
                    (
                        "foreign-license-text",
                        f"copyright line: {_snippet(text, copyright_match)}",
                    )
                )
    if any(token in low for token in UPSTREAM_CITATION_PREFILTERS):
        for name, prefilter, regex in QUOTATION_MARKER_RES:
            if prefilter not in low:
                continue
            match = regex.search(text)
            if match:
                hits.append(
                    ("self-declared-quotation", f"{name}: {_snippet(text, match)}")
                )
                break
    return hits


def _snippet(text, match, width=70):
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def live_quotation_spans(text, occurrences):
    """Spans of `occurrences` in `text` that actually contain a quotation marker.

    The same resolution `check_manifest` performs against the working-tree text,
    re-run here for a staged view (increment 14): an exemption names occurrences
    of the quotation vocabulary, and a span computed from one view's offsets
    means nothing in the other's. An occurrence that is absent from the view
    being judged contributes no span, so its markers are NOT exempt there —
    which is the conservative direction on a scoped exemption.
    """
    markers = quotation_marker_matches(text)
    spans = []
    for occurrence in occurrences or ():
        for match in occurrence_regex(occurrence).finditer(text):
            if any(
                match.start() <= mk.start() and mk.end() <= match.end()
                for _, mk in markers
            ):
                spans.append((match.start(), match.end()))
    return spans


def _view_tripwire_findings(tree: Tree, rel, view, coverage, exemptions, counts):
    """Findings for one BYTE VIEW of one entry, and the hits it contributes."""
    findings = []
    # True for any view whose offsets are not the ones `check_manifest` resolved
    # a scoped exemption's occurrences against: the staged blob (increment 14)
    # and a commit's blob (increment 17). Re-resolving is the conservative
    # direction — an occurrence absent from THESE bytes exempts nothing in them.
    reresolve = view != tree.view_for(rel)
    staged = view != WORKTREE_VIEW
    for rule, evidence in tripwire_hits(tree, rel, view):
        counts[rule] += 1
        if rule in coverage.get(rel, ()):
            continue
        exemption = exemptions.get(rel, {}).get(rule)
        if exemption and exemption["spans"] is None:
            continue
        if exemption:
            # Occurrence-scoped: exempt only markers inside a named span. The
            # spans resolved for the working-tree text do not address any other
            # view's offsets, so a staged view re-resolves them against its own
            # bytes rather than reusing them.
            spans = (
                live_quotation_spans(
                    tree.text(rel, view) or "", exemption.get("occurrences")
                )
                if reresolve
                else exemption["spans"]
            )
            outside = [
                (name, match)
                for name, match in quotation_marker_matches(tree.text(rel, view) or "")
                if not any(
                    start <= match.start() and match.end() <= end
                    for start, end in spans
                )
            ]
            if not outside:
                continue
            name, match = outside[0]
            evidence = (
                f"{name}: {_snippet(tree.text(rel, view), match)} (outside the "
                "occurrence(s) its exemption names)"
            )
        if staged:
            # The path alone does not say which bytes offended, and the answer
            # changes what the author must do: the working-tree copy is clean,
            # the STAGED one is not, and a commit would publish the staged one.
            evidence = view_evidence_prefix(view) + evidence
        findings.append(
            Finding(
                rule,
                rel,
                f"{RULES[rule]}: {evidence} — add a row to {MANIFEST_REL} "
                "(with its decision record)"
                + (
                    f", or an explicit '{rule}' exemption with a reason"
                    if rule in EXEMPTIBLE_RULES
                    else ""
                ),
            )
        )
    return findings


def check_tripwires(tree: Tree, coverage, exemptions):
    """Tripwire findings over every byte view of every in-scope entry.

    Two passes, not one (increment 14): the working-tree bytes of each in-scope
    entry, then the STAGED bytes of each entry whose index blob is not known to
    match them. A provenance row or exemption attached to the path answers both
    views — it is the file's third-party content that is being declared — but the
    occurrence spans of a scoped exemption are re-resolved per view.
    """
    findings = []
    counts = {rule: 0 for rule in TRIPWIRE_RULES}
    # `entry_views` is the single definition of that view set (increment 16),
    # which read it out of this loop so the two bookkeeping checks that now
    # share it cannot drift from the enumeration group 4 uses. Every entry in
    # `staged_views` is in `files` by construction (it is filtered on
    # `index_blobs` and on not being excluded), so iterating per entry covers
    # exactly what the two sequential loops here covered before.
    for rel in tree.files:
        for view in entry_views(tree, rel):
            findings += _view_tripwire_findings(
                tree, rel, view, coverage, exemptions, counts
            )
    return findings, counts


# --- audit driver -------------------------------------------------------------


COMMITTED_PREFIX = (
    "in the ANSWER SET a commit would publish (the staged "
    "decision-records bookkeeping differs from the copy on disk)"
)


def _committed_pass(root: Path, tree: Tree, already):
    """Re-judge the tree against the ANSWER SET a commit would publish.

    Increment 15. Increment 14 moved the carriage rules (group 4) onto both byte
    views an entry can have; the four groups' ANSWERS — a provenance row, an
    exemption, a scope exclusion, the record index, a record's own header —
    stayed on the working-tree copy of `decision-records/`. So an answer could
    be published by no commit at all: `git add` the carrier, then add its row to
    `provenance.json` on disk WITHOUT staging it, and the audit passed with
    coverage identical to a legitimately declared tree's, while the commit
    published the carrier and a manifest that does not mention it.

    The fix is not a new rule. It is to run the SAME four groups a second time
    with every read resolved to the committable bytes (`COMMITTED_VIEW`), and
    only when the bookkeeping actually diverges — so a tree whose
    `decision-records/` is staged, or has no unstaged edits at all, takes this
    path not at all and behaves exactly as before.

    `already` is the (rule, path) set pass one produced: a finding both answer
    sets agree on is reported once, by the pass that reads what the author is
    looking at. What survives here is the finding that exists ONLY in the
    committable tree, which is the whole mask.

    Note the deliberate asymmetry with group 4's two views: a carriage question
    is asked of BOTH views (an unstaged paste must fire before a `git add`),
    while an answer is accepted only from the view that raised the question. An
    answer is a claim this repository publishes; a question is a fact about bytes
    on hand.
    """
    divergent = tree.divergent_bookkeeping()
    if not divergent:
        return [], []
    # The staged manifest's own bytes, read through the shared cache. Read from
    # the FIRST tree, because the committable tree's scope exclusions come out
    # of this manifest and cannot be known before it is parsed.
    # When the manifest itself does not diverge, `FROM_DISK` makes this read
    # byte-for-byte the one pass one performed, rather than a second read
    # through the content-scan machinery that could differ on an odd encoding.
    raw = (
        tree.text(MANIFEST_REL, STAGED_VIEW) if MANIFEST_REL in divergent else FROM_DISK
    )
    label = _view_label(MANIFEST_REL, STAGED_VIEW)
    manifest, findings = load_manifest(root, raw=raw, label=label)
    if manifest is None:
        manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
    # include_untracked is deliberately NOT carried over: the committable tree
    # is the index. A file that is not in the index is published by no commit,
    # so judging it here would report a finding against a tree that does not
    # exist — pass one already audits it when the flag is on, and increment 11's
    # coverage line discloses it when the flag is off.
    committed = Tree(
        root,
        scope_exclusion_prefixes(manifest),
        include_untracked=False,
        default_view=COMMITTED_VIEW,
        share_reads_from=tree,
    )
    records, record_findings = parse_records(committed)
    try:
        rows, index_findings = parse_index(committed)
    except AuditError as exc:
        # The working-tree README parsed (pass one got this far), so this is a
        # statement about the committable bytes alone: reported as a finding
        # against the staged index, never as an audit that could not run.
        return findings + [
            Finding(
                "index-row-malformed",
                _view_label(INDEX_REL, STAGED_VIEW),
                f"{exc} — {COMMITTED_PREFIX}",
            )
        ], divergent
    findings += record_findings + index_findings
    findings += check_index(records, rows)
    findings += check_citations(committed, records, rows)
    manifest_findings, coverage, exemptions = check_manifest(
        committed, manifest, records, rows, manifest_rel=label
    )
    findings += manifest_findings
    tripwire_findings, _ = check_tripwires(committed, coverage, exemptions)
    findings += tripwire_findings
    tagged = []
    for finding in findings:
        if (finding.rule, finding.path) in already:
            continue
        tagged.append(Finding(finding.rule, finding.path, f"{COMMITTED_PREFIX} — {finding.detail}"))
    return tagged, divergent


# --- GPL-boundary register cross-check (issue #370, governance issue #25) -----
#
# `decision-records/gpl-boundary-register.md` is the TABLE-level inventory of
# quoted third-party constants; `provenance.json` stays the FILE-level source.
# Neither is assumed complete, so this check reconciles them in both directions
# and against the decision records themselves:
#
#   * every `quoted-constants` manifest row has at least one register row;
#   * every register row cites a manifest row (same path, same record, same
#     pinned commit) or a declared, still-live exception, and carries every
#     required field;
#   * the register licence matches the table it sits in and the manifest row's
#     licence, unless the row is explicitly `licence reconciled` (an MIT
#     Airwindows constant must not be relabelled GPL because the Surge adapter
#     around it is, nor the reverse);
#   * every decision record that declares quoted data is listed or excluded
#     there (the case no manifest row can reveal: a record that classifies
#     material as quoted while the manifest names no such file).
#
# It does NOT read model source for literals: completeness against code is
# bounded by the records' inventories (declared in the register itself).

REGISTER_REL = "decision-records/gpl-boundary-register.md"

REGISTER_GPL_SECTION = "GPL-derived register"
REGISTER_MIT_SECTION = "MIT-sourced quoted constants"
REGISTER_EXCEPTION_SECTION = "Provenance exceptions"
REGISTER_EXCLUSION_SECTION = "Reviewed exclusions"

REGISTER_ROW_COLUMNS = (
    "ID",
    "In-repo file",
    "Symbol / table",
    "Upstream file",
    "Pinned revision",
    "Upstream licence",
    "Decision record",
    "Provenance citation",
    "Status",
    "Notes",
)
REGISTER_EXCEPTION_COLUMNS = (
    "ID",
    "In-repo files",
    "Decision record",
    "Reason",
    "Closing action",
)
REGISTER_EXCLUSION_COLUMNS = (
    "ID",
    "Decision record",
    "In-repo file",
    "Symbol / table",
    "Classification",
    "Reason",
)
REGISTER_TABLES = {
    REGISTER_GPL_SECTION: REGISTER_ROW_COLUMNS,
    REGISTER_MIT_SECTION: REGISTER_ROW_COLUMNS,
    REGISTER_EXCEPTION_SECTION: REGISTER_EXCEPTION_COLUMNS,
    REGISTER_EXCLUSION_SECTION: REGISTER_EXCLUSION_COLUMNS,
}
REGISTER_SECTION_LICENCE = {
    REGISTER_GPL_SECTION: "GPL-3.0-or-later",
    REGISTER_MIT_SECTION: "MIT",
}
REGISTER_STATUSES = ("registered", "provenance incomplete", "licence reconciled")
REGISTER_EXCLUSION_CLASSES = (
    "re-derived",
    "structural",
    "external-identity",
    "no-opaque-constants-claimed",
)
REGISTER_INCOMPLETE_REVISION = "incomplete"
REGISTER_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
REGISTER_ID_RE = re.compile(r"^[A-Z]-[0-9]+$")
# A decision record that declares data quoted into this repository must be
# accounted for in the register (listed, or excluded with a reason).
QUOTED_RECORD_RE = re.compile(
    r"quoted[ -](?:as[ -])?(?:data|constants?)", re.IGNORECASE
)


def _licence_class(text):
    lowered = str(text or "").strip().lower()
    if lowered.startswith("gpl"):
        return "GPL-3.0-or-later"
    if lowered.startswith("mit"):
        return "MIT"
    return None


def parse_register(text):
    """({section: [(lineno, [cells])]}, findings) from the register markdown."""
    findings = []
    sections = {}
    current = None
    state = None  # None | 'header' | 'rows'
    for lineno, line in enumerate(text.splitlines(), start=1):
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            state = None
            if current in REGISTER_TABLES:
                sections[current] = []
            continue
        if current not in REGISTER_TABLES or not line.lstrip().startswith("|"):
            if current in REGISTER_TABLES and state == "rows" and line.strip():
                state = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if state is None:
            expected = list(REGISTER_TABLES[current])
            if cells != expected:
                findings.append(
                    Finding(
                        "register-malformed-row",
                        REGISTER_REL,
                        f"section {current!r}: header row (line {lineno}) is "
                        f"{cells!r}, expected {expected!r}",
                    )
                )
            state = "separator"
            continue
        if state == "separator":
            state = "rows"
            continue
        sections[current].append((lineno, cells))
    return sections, findings


def _register_manifest_entries(manifest):
    out = []
    for entry in (manifest or {}).get("entries", []) or []:
        if isinstance(entry, dict) and entry.get("class") == "quoted-constants":
            out.append(entry)
    return out


def _entry_key(entry):
    return str(entry.get("path") or entry.get("pattern") or "")


def check_register(tree: Tree, manifest, records, index_rows, register_rel=REGISTER_REL):
    """Reconcile the GPL-boundary register with the manifest and the records.

    Returns (findings, stats). Every finding names `register_rel` (or the
    manifest row it concerns) so a reviewer can open the file that must change.
    """
    findings = []
    stats = {
        "register_rows": 0,
        "register_mit_rows": 0,
        "register_exceptions": 0,
        "register_exclusions": 0,
        "register_provenance_incomplete": [],
    }
    text = tree.text(register_rel)
    if text is None:
        findings.append(
            Finding(
                "register-missing",
                register_rel,
                "the GPL-boundary register is absent or unreadable; the "
                "quoted-constants inventory it holds cannot be cross-checked",
            )
        )
        return findings, stats
    sections, parse_findings = parse_register(text)
    findings += parse_findings
    for name in REGISTER_TABLES:
        if name not in sections:
            findings.append(
                Finding(
                    "register-missing",
                    register_rel,
                    f"required section '## {name}' is absent",
                )
            )
    if any(f.rule == "register-missing" for f in findings):
        return findings, stats

    files = set(tree.files)
    entries = _register_manifest_entries(manifest)
    entry_by_key = {_entry_key(e): e for e in entries}
    seen_ids = {}

    def malformed(rid, detail):
        findings.append(
            Finding("register-malformed-row", register_rel, f"{rid}: {detail}")
        )

    def check_shape(section, lineno, cells):
        columns = REGISTER_TABLES[section]
        rid = cells[0] if cells else f"line {lineno}"
        if len(cells) != len(columns):
            malformed(
                rid,
                f"line {lineno} has {len(cells)} cells, expected {len(columns)}",
            )
            return None
        for column, cell in zip(columns, cells):
            if not cell:
                malformed(rid, f"line {lineno}: field {column!r} is empty")
                return None
        if not REGISTER_ID_RE.match(cells[0]):
            malformed(rid, f"line {lineno}: ID {cells[0]!r} is not LETTER-NUMBER")
            return None
        if cells[0] in seen_ids:
            malformed(rid, f"line {lineno}: ID repeated (first on line {seen_ids[cells[0]]})")
            return None
        seen_ids[cells[0]] = lineno
        return rid

    def check_record(rid, number, allow_none=False):
        if allow_none and number == "none":
            return True
        if number not in records:
            malformed(rid, f"decision record {number!r} does not exist")
            return False
        if number not in index_rows:
            malformed(rid, f"decision record {number!r} is not indexed")
            return False
        return True

    # ---- exceptions ---------------------------------------------------------
    exceptions = {}
    for lineno, cells in sections[REGISTER_EXCEPTION_SECTION]:
        rid = check_shape(REGISTER_EXCEPTION_SECTION, lineno, cells)
        if rid is None:
            continue
        stats["register_exceptions"] += 1
        _id, paths, number, _reason, _closing = cells
        if not check_record(rid, number):
            continue
        listed = [p.strip() for p in paths.split(";") if p.strip()]
        ok = True
        for path in listed:
            if path not in files:
                findings.append(
                    Finding(
                        "register-exception-stale",
                        register_rel,
                        f"{rid}: listed file {path!r} does not exist",
                    )
                )
                ok = False
            for entry in entries:
                _kind, _label, matches = _matcher(entry)
                if matches(path):
                    findings.append(
                        Finding(
                            "register-exception-stale",
                            register_rel,
                            f"{rid}: {path!r} is now covered by the "
                            f"quoted-constants row {_entry_key(entry)!r}; remove "
                            "the exception and cite the row",
                        )
                    )
                    ok = False
        if ok:
            exceptions[rid] = {"files": set(listed), "record": number, "used": False}

    # ---- register rows --------------------------------------------------------
    cited_keys = set()
    accounted_records = set()
    for section in (REGISTER_GPL_SECTION, REGISTER_MIT_SECTION):
        for lineno, cells in sections[section]:
            rid = check_shape(section, lineno, cells)
            if rid is None:
                continue
            (_id, path, _symbol, _upstream, revision, licence, number, citation,
             status, notes) = cells
            stats["register_rows" if section == REGISTER_GPL_SECTION else "register_mit_rows"] += 1
            if status not in REGISTER_STATUSES:
                malformed(rid, f"status {status!r} not in {list(REGISTER_STATUSES)}")
                continue
            if status == "provenance incomplete":
                stats["register_provenance_incomplete"].append(rid)
            if revision == REGISTER_INCOMPLETE_REVISION:
                if status != "provenance incomplete":
                    malformed(
                        rid,
                        "pinned revision 'incomplete' requires status "
                        "'provenance incomplete'",
                    )
                    continue
            elif not REGISTER_REVISION_RE.match(revision):
                malformed(rid, f"pinned revision {revision!r} is not a 40-hex commit")
                continue
            if licence not in ("GPL-3.0-or-later", "MIT"):
                malformed(rid, f"upstream licence {licence!r} is not GPL-3.0-or-later or MIT")
                continue
            if licence != REGISTER_SECTION_LICENCE[section]:
                findings.append(
                    Finding(
                        "register-licence-mismatch",
                        register_rel,
                        f"{rid}: licence {licence!r} sits in the "
                        f"'{section}' table ({REGISTER_SECTION_LICENCE[section]})",
                    )
                )
                continue
            if path not in files:
                malformed(rid, f"in-repo file {path!r} does not exist")
                continue
            if not check_record(rid, number):
                continue
            accounted_records.add(number)
            kind, _, target = citation.partition(":")
            if kind == "manifest":
                entry = entry_by_key.get(target)
                if entry is None or target != path:
                    findings.append(
                        Finding(
                            "register-unmapped-row",
                            register_rel,
                            f"{rid}: cites manifest row {target!r} but "
                            + (
                                "no quoted-constants row has that path"
                                if entry is None
                                else f"the row is for a different file than {path!r}"
                            ),
                        )
                    )
                    continue
                cited_keys.add(target)
                if str(entry.get("decision_record")) != number:
                    findings.append(
                        Finding(
                            "register-unmapped-row",
                            register_rel,
                            f"{rid}: record {number} but the manifest row for "
                            f"{target!r} cites record {entry.get('decision_record')}",
                        )
                    )
                    continue
                pinned = entry.get("pinned_commit")
                if revision != REGISTER_INCOMPLETE_REVISION and pinned and pinned != revision:
                    findings.append(
                        Finding(
                            "register-unmapped-row",
                            register_rel,
                            f"{rid}: pinned revision {revision} differs from the "
                            f"manifest row's {pinned}",
                        )
                    )
                    continue
                manifest_class = _licence_class(entry.get("upstream_license"))
                differs = manifest_class is not None and manifest_class != licence
                cited = {m for m in re.findall(r"\b(\d{4})\b", notes) if m in records}
                if differs and status == "registered":
                    findings.append(
                        Finding(
                            "register-licence-mismatch",
                            register_rel,
                            f"{rid}: register licence {licence} but the manifest "
                            f"row says {entry.get('upstream_license')!r}; mark the "
                            "row 'licence reconciled' and cite the reconciling record",
                        )
                    )
                    continue
                if differs or status == "licence reconciled":
                    if not differs:
                        findings.append(
                            Finding(
                                "register-licence-mismatch",
                                register_rel,
                                f"{rid}: 'licence reconciled' but the manifest row "
                                "already agrees; nothing is reconciled",
                            )
                        )
                    elif not cited:
                        findings.append(
                            Finding(
                                "register-licence-mismatch",
                                register_rel,
                                f"{rid}: a licence that differs from the manifest "
                                "row must cite the reconciling decision record in Notes",
                            )
                        )
            elif kind == "exception":
                exc = exceptions.get(target)
                if exc is None:
                    findings.append(
                        Finding(
                            "register-unmapped-row",
                            register_rel,
                            f"{rid}: cites exception {target!r}, which is not a "
                            "live, valid row of 'Provenance exceptions'",
                        )
                    )
                    continue
                exc["used"] = True
                if path not in exc["files"] or exc["record"] != number:
                    findings.append(
                        Finding(
                            "register-unmapped-row",
                            register_rel,
                            f"{rid}: exception {target} does not list {path!r} "
                            f"under record {number}",
                        )
                    )
                    continue
                if status == "licence reconciled":
                    malformed(rid, "'licence reconciled' needs a manifest citation")
            else:
                findings.append(
                    Finding(
                        "register-unmapped-row",
                        register_rel,
                        f"{rid}: citation {citation!r} is neither "
                        "'manifest:<path>' nor 'exception:<ID>'",
                    )
                )

    for rid, exc in sorted(exceptions.items()):
        if not exc["used"]:
            findings.append(
                Finding(
                    "register-exception-stale",
                    register_rel,
                    f"{rid}: no register row cites this exception",
                )
            )

    # ---- exclusions -----------------------------------------------------------
    excluded_records = set()
    for lineno, cells in sections[REGISTER_EXCLUSION_SECTION]:
        rid = check_shape(REGISTER_EXCLUSION_SECTION, lineno, cells)
        if rid is None:
            continue
        stats["register_exclusions"] += 1
        _id, number, path, _symbol, classification, _reason = cells
        if classification not in REGISTER_EXCLUSION_CLASSES:
            malformed(
                rid,
                f"classification {classification!r} not in "
                f"{list(REGISTER_EXCLUSION_CLASSES)}",
            )
            continue
        if path not in files:
            malformed(rid, f"in-repo file {path!r} does not exist")
            continue
        # Only a "no opaque constants" classification accounts for a record
        # that mentions quoted data: a re-derived or structural exclusion sits
        # BESIDE quoted rows and must not stand in for them (dropping a record's
        # quoted rows would otherwise be hidden by its own exclusions).
        if check_record(rid, number, allow_none=True) and number != "none":
            if classification == "no-opaque-constants-claimed":
                excluded_records.add(number)

    # ---- manifest -> register (the omission direction) ----------------------
    for entry in entries:
        key = _entry_key(entry)
        if key not in cited_keys:
            findings.append(
                Finding(
                    "register-missing-row",
                    MANIFEST_REL,
                    f"quoted-constants row {key!r} (record "
                    f"{entry.get('decision_record')}) has no row in {register_rel}",
                )
            )

    # ---- records -> register (what no manifest row can reveal) ---------------
    for number, record in sorted(records.items()):
        body = tree.text(record["path"]) or ""
        if QUOTED_RECORD_RE.search(body) and number not in (
            accounted_records | excluded_records
        ):
            findings.append(
                Finding(
                    "register-record-unaccounted",
                    record["path"],
                    f"record {number} declares quoted data but {register_rel} "
                    "neither lists it nor records a reviewed exclusion for it",
                )
            )
    return findings, stats



def audit(root: Path, include_untracked=False):
    root = Path(root)
    manifest, findings = load_manifest(root)
    if manifest is None:
        manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
    tree = Tree(root, scope_exclusion_prefixes(manifest), include_untracked)
    records, record_findings = parse_records(tree)
    rows, index_findings = parse_index(tree)
    findings = list(findings) + record_findings + index_findings
    findings += check_index(records, rows)
    findings += check_citations(tree, records, rows)
    manifest_findings, coverage, exemptions = check_manifest(tree, manifest, records, rows)
    findings += manifest_findings
    register_findings, register_stats = check_register(tree, manifest, records, rows)
    findings += register_findings
    tripwire_findings, tripwire_counts = check_tripwires(tree, coverage, exemptions)
    findings += tripwire_findings
    committed_findings, divergent_bookkeeping = _committed_pass(
        root, tree, {(f.rule, f.path) for f in findings}
    )
    findings += committed_findings
    stats = {
        "files_scanned": len(tree.files),
        "files_excluded": sum(len(v) for v in tree.excluded.values()),
        "exclusions": {k: len(v) for k, v in sorted(tree.excluded.items())},
        "records": len(records),
        "index_rows": len(rows),
        "provenance_rows": len(manifest.get("entries", []) or []),
        "files_covered_by_rows": len(coverage),
        "exemptions": len(manifest.get("exemptions", []) or []),
        # GPL-boundary register (issue #370): rows reconciled, and the rows
        # listed but flagged `provenance incomplete` (disclosed, not failed).
        "gpl_boundary_register": register_stats,
        # Disclosed, not silent: these files reached no content rule at all,
        # so a PASS says nothing about what is inside them (DECLARED LIMITS).
        # Counted over REGULAR files only: a by-reference entry has no bytes of
        # its own, and reporting it here read as "an undecodable payload" —
        # which is how a gitlink hid among the renders (increment 7).
        "files_not_content_scanned": sum(
            1
            for rel in tree.files
            if tree.kind(rel) == "file" and tree.scan_mode(rel) in ("none", "unreadable")
        ),
        # The two weaker scan modes, reported SEPARATELY from a full decode:
        # a wrapper's members were read as their own payloads, and a binary
        # payload was read only as the ASCII runs it carries (increment 8).
        "files_unwrapped_from_wrappers": sum(
            1 for rel in tree.files if tree.scan_mode(rel) == "unwrapped"
        ),
        "files_scanned_as_extracted_strings": sum(
            1 for rel in tree.files if tree.scan_mode(rel) == "strings"
        ),
        # Names recovered from inside wrappers and judged by the extension sets
        # (increment 9). Reported because a wrapper the audit could not open
        # contributes none, so "0 names" and "no wrappers" must not look alike.
        "wrapper_member_names_read": sum(
            len(tree.carried_names(rel)) for rel in tree.files
        ),
        # Wide-encoded (UTF-16/UTF-32) runs read out of those payloads
        # (increment 10). Reported for the same reason as the member names: a
        # payload whose wide runs were never examined must not be reported the
        # same way as one that carried none.
        "wide_encoded_runs_harvested": sum(tree.wide_runs(rel) for rel in tree.files),
        # A scan that could not finish must never look like one that passed.
        "payload_scans_truncated": tree.truncated_scans(),
        # The INDEX boundary (increment 11): entries present in the working
        # tree that this run did not audit because they are not in the git
        # index. Reported as a count AND as the paths themselves, and printed
        # even when zero — "none present" and "never looked" must not look
        # alike. `--include-untracked` audits them, which empties this list.
        "entries_present_but_not_in_the_index": tree.untracked_not_audited(),
        "untracked_entries_audited": (
            len(tree.untracked) if tree.include_untracked else 0
        ),
        # The STAGED-CONTENT boundary (increment 14): entries whose index blob is
        # not known to equal their working-tree bytes, and whose committable
        # bytes were therefore read as a SECOND view. Reported as the paths and
        # printed even when zero, for the same reason as the index boundary
        # above: "nothing diverges here" and "the committable bytes were never
        # read" must not look alike.
        "entries_whose_staged_content_differs_from_the_working_tree": list(
            tree.staged_views
        ),
        "staged_payloads_content_scanned": sum(
            1
            for rel in tree.staged_views
            if tree.scan_mode(rel, STAGED_VIEW) not in ("none", "unreadable")
        ),
        # The subset with no working-tree copy at all: their working-tree view
        # reaches no content rule, so the staged view is the only read there is.
        "staged_entries_absent_from_the_working_tree": tree.staged_only(),
        # The EVIDENCE boundary (increment 16): staged views that a BOOKKEEPING
        # check — a record citation, a provenance row's corroboration — read as
        # evidence, as opposed to the carriage rules reading them for signals.
        # Printed even when empty: until increment 16 this was always empty
        # while the divergence list above was not, and nothing said so.
        "staged_views_read_as_bookkeeping_evidence": (
            tree.staged_views_read_as_evidence()
        ),
        # The ANSWER-SET boundary (increment 15): bookkeeping files whose staged
        # bytes are not known to equal the working tree's, which means this tree
        # has two different answer sets and the committable one was judged on
        # its own. Printed even when empty, for the reason the two boundaries
        # above are: "the answers agree in both views" and "only the copy on
        # disk was ever consulted" must not look alike.
        "divergent_bookkeeping_files": divergent_bookkeeping,
        "committed_answer_set_findings": len(committed_findings),
        "entries_by_reference": {
            kind: sum(1 for rel in tree.files if tree.kind(rel) == kind)
            for kind in ("symlink", "gitlink")
        },
        # Gitlinks a declared exclusion covers but does not hide (increment 13).
        # Reported as the paths themselves, printed even when empty: a prefix
        # that happens to contain no submodule must not look like one whose
        # submodule was never examined.
        "by_reference_entries_inside_declared_exclusions": (
            tree.by_reference_inside_exclusions()
        ),
        "tripwire_hits": tripwire_counts,
    }
    findings.sort(key=lambda f: (f.rule, f.path))
    return findings, stats


def report(findings, stats, root, as_json=False):
    if as_json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "verdict": "PASS" if not findings else "FAIL",
                    "coverage": stats,
                    "findings": [f.as_dict() for f in findings],
                    "caveat": CAVEAT,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(f"provenance audit of {root}")
    print(
        "coverage: "
        f"{stats['files_scanned']} files scanned, "
        f"{stats['files_excluded']} excluded by declared scope exclusions, "
        f"{stats['records']} decision records, "
        f"{stats['provenance_rows']} provenance rows covering "
        f"{stats['files_covered_by_rows']} files, "
        f"{stats['exemptions']} exemptions"
    )
    for prefix, count in stats["exclusions"].items():
        print(f"  excluded: {prefix} ({count} files)")
    reg = stats["gpl_boundary_register"]
    print(
        f"  gpl-boundary register: {reg['register_rows']} GPL-derived rows, "
        f"{reg['register_mit_rows']} MIT-sourced rows, "
        f"{reg['register_exceptions']} provenance exception(s), "
        f"{reg['register_exclusions']} reviewed exclusion(s); "
        f"provenance incomplete: {', '.join(reg['register_provenance_incomplete']) or 'none'}"
    )
    print(
        f"  not content-scanned (no text in the payload at all): "
        f"{stats['files_not_content_scanned']} files — extension tripwires only"
    )
    print(
        f"  unwrapped by magic (compressed stream / archive): "
        f"{stats['files_unwrapped_from_wrappers']} files — members content-scanned, "
        f"{stats['wrapper_member_names_read']} member name(s) read and judged"
    )
    print(
        f"  scanned as extracted strings only: "
        f"{stats['files_scanned_as_extracted_strings']} files — printable-ASCII "
        "runs, plus the wide-encoded ones; a notice in some other encoding "
        "inside one would still be missed"
    )
    print(
        f"  wide-encoded (UTF-16/UTF-32) runs harvested from payloads and "
        f"judged: {stats['wide_encoded_runs_harvested']} — counted over every "
        "payload read as strings, members of wrappers included"
    )
    unindexed = stats["entries_present_but_not_in_the_index"]
    if stats["untracked_entries_audited"]:
        print(
            f"  present in the working tree but not in the git index: "
            f"{stats['untracked_entries_audited']} entries — AUDITED "
            "(--include-untracked)"
        )
    else:
        print(
            f"  present in the working tree but NOT in the git index: "
            f"{len(unindexed)} entries — not audited by any rule; "
            "re-run with --include-untracked to audit them"
        )
        for rel in unindexed[:UNINDEXED_PATHS_LISTED]:
            print(f"      not audited (not in the index): {rel}")
        if len(unindexed) > UNINDEXED_PATHS_LISTED:
            print(
                f"      … and {len(unindexed) - UNINDEXED_PATHS_LISTED} more "
                "(full list in --json)"
            )
    divergent = stats["entries_whose_staged_content_differs_from_the_working_tree"]
    absent = stats["staged_entries_absent_from_the_working_tree"]
    print(
        f"  staged content not known to match the working tree: "
        f"{len(divergent)} entries — their index blobs (what a commit would "
        f"publish) were read as a second view, "
        f"{stats['staged_payloads_content_scanned']} of them content-scanned; "
        f"{len(absent)} have no working-tree copy at all"
    )
    for rel in divergent[:STAGED_PATHS_LISTED]:
        print(
            f"      also audited (staged blob): {rel}"
            + (" — not present in the working tree" if rel in absent else "")
        )
    if len(divergent) > STAGED_PATHS_LISTED:
        print(
            f"      … and {len(divergent) - STAGED_PATHS_LISTED} more "
            "(full list in --json)"
        )
    evidence = stats["staged_views_read_as_bookkeeping_evidence"]
    print(
        f"  staged views read as BOOKKEEPING evidence (a record citation, a "
        f"provenance row's corroboration): {len(evidence)} of {len(divergent)}"
        + (f" — {', '.join(evidence[:STAGED_PATHS_LISTED])}" if evidence else "")
    )
    bookkeeping = stats["divergent_bookkeeping_files"]
    print(
        f"  bookkeeping whose staged bytes are not known to match the working "
        f"tree: {len(bookkeeping)} file(s) — "
        + (
            "the ANSWER SET a commit would publish was judged on its own, "
            f"finding {stats['committed_answer_set_findings']} issue(s) present "
            "only there"
            if bookkeeping
            else "one answer set, published and on disk alike"
        )
    )
    for rel in bookkeeping:
        print(f"      answers re-read from the staged blob: {rel}")
    for rel in stats["payload_scans_truncated"]:
        print(
            f"  TRUNCATED payload scan (unwrap budget/depth reached, NOT fully "
            f"read): {rel}"
        )
    by_reference = stats["entries_by_reference"]
    print(
        f"  by reference (content is not in the entry's own bytes): "
        f"{by_reference['symlink']} symlink(s), "
        f"{by_reference['gitlink']} submodule/nested repo(s) — judged at the "
        "discovery layer"
    )
    inside = stats["by_reference_entries_inside_declared_exclusions"]
    print(
        f"      of those, inside a declared scope exclusion: {len(inside)} — "
        "an exclusion withholds content, not the existence of another repository"
    )
    for rel in inside:
        print(f"      by-reference entry inside a declared exclusion: {rel}")
    hits = ", ".join(f"{k}={v}" for k, v in sorted(stats["tripwire_hits"].items()))
    print(f"tripwire hits (declared + undeclared): {hits}")
    if findings:
        print(f"\nFAIL: {len(findings)} provenance finding(s):")
        for finding in findings:
            print(f"  [{finding.rule}] {finding.path}")
            print(f"      {finding.detail}")
    else:
        print("\nPASS: every carriage signal is answered by a provenance row or "
              "a declared exemption, and the decision-record bookkeeping is "
              "self-consistent.")
    print(CAVEAT)


# --- the history pass (increment 17) -----------------------------------------


HISTORY_CAVEAT = (
    "\nNOTE: this judges the commits in the range it was given, and only the "
    "carriage question (group 4) — a commit's own bookkeeping self-consistency "
    "is the current tree's obligation, not a historical commit's. Commits "
    "outside the range are NOT_RUN, not clean, and every limit in --limits "
    "still applies to each tree judged here. The rules applied are TODAY's: a "
    "commit that passed the audit as it existed then can be flagged here, so a "
    "finding is 'what the current rule set says about bytes this history "
    "published', never 'a violation of the rule in force at the time'."
)

# How a finding relates to the ANSWER SET at the range's final commit. The
# distinction is the whole reason this mode is not a duplicate of the tree
# audit: only the middle one is a shape no audit of the current tree can see,
# and only the last one is also live today.
TIP_ANSWERED = "answered at the range tip (declared in a later commit)"
TIP_ABSENT = "the path does not exist at the range tip (published, then removed)"
TIP_SIGNAL_GONE = "the offending bytes are gone at the range tip (the path remains)"
TIP_UNANSWERED = "still unanswered at the range tip (the tree audit fails too)"


def audit_history(root: Path, revrange):
    """Audit every commit in `revrange` as the tree it publishes.

    Returns (findings, stats). Each commit is judged on the carriage question
    alone — does every signal in the bytes this commit publishes have an answer
    in the bookkeeping THIS COMMIT publishes — because that is the question a
    tree audit of HEAD cannot answer for a blob that no longer exists at HEAD,
    and because judging a 2026-03 commit's README table against today's index
    conventions would bury the signal under bookkeeping churn.

    Findings are deduplicated per (rule, path, blob) and attributed to the
    EARLIEST commit in the range that published them, with the number of commits
    in range that carried the same bytes — a carrier that survived forty commits
    is one finding about one blob, not forty.
    """
    root = Path(root)
    commits = commit_log(root, revrange)
    signals = {}
    pairs = set()
    found = {}
    judged = 0
    unjudged = []
    dropped = []
    unreadable_index = []
    by_reference_signals = 0
    by_reference_entries = 0
    published = {}
    tip = None
    for sha, date, parents, subject in commits:
        entries = list_entries_at_commit(root, sha)
        blobs = {rel: oid for rel, kind, oid in entries if kind != "gitlink"}
        published[sha] = MANIFEST_REL in blobs
        raw = None
        if MANIFEST_REL in blobs:
            payload = read_index_blob(root, blobs[MANIFEST_REL])
            raw = None if payload is None else payload.decode("utf-8", "replace")
        if raw is None:
            # No manifest here. Whether that is "this tree predates the
            # bookkeeping" or "this commit removed the bookkeeping" is decided
            # from the PARENTS, not from a range-wide latch: in a merge-commit
            # history a branch forked before the manifest landed carries trees
            # that legitimately have none, and a date-ordered latch would judge
            # all of them against an empty answer set.
            inherited = any(
                commit_publishes_manifest(root, parent, published)
                for parent in parents
            )
            if not inherited:
                # Nothing to judge this commit's carriage against. Disclosed as a
                # commit this run did NOT judge — never folded into a PASS, and
                # never turned into a finding per carrier per commit, which would
                # bury the signal this mode exists to surface.
                unjudged.append(
                    {"commit": sha, "date": date, "subject": subject}
                )
                continue
            # A parent published an answer set and this commit does not: judged
            # with NO answers, so deleting the manifest buys a commit nothing.
            # This is the one way the "not judged" disclosure above could have
            # become an escape hatch.
            dropped.append({"commit": sha, "date": date, "subject": subject})
        manifest, _ = load_manifest(root, raw=raw)
        if manifest is None:
            manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
            if raw is not None:
                # Present but unparseable: a manifest that answers nothing,
                # judged as such and disclosed with the deletions.
                dropped.append({"commit": sha, "date": date, "subject": subject})
        tree = Tree(
            root,
            scope_exclusion_prefixes(manifest),
            entries=entries,
            default_view=HISTORY_VIEW,
            primary_view=HISTORY_VIEW,
            signal_cache=signals,
        )
        records, _ = parse_records(tree)
        try:
            rows, _ = parse_index(tree)
        except AuditError:
            # The record index is this commit's bookkeeping, not its carriage. A
            # commit whose README cannot be parsed is still judged on content;
            # the unknown row set is disclosed rather than treated as an answer.
            rows = {}
            unreadable_index.append({"commit": sha, "date": date})
        _, coverage, exemptions = check_manifest(tree, manifest, records, rows)
        tripwire_findings, counts = check_tripwires(tree, coverage, exemptions)
        judged += 1
        # Kept for the LAST judged commit only: how each finding relates to the
        # answer set at the tip is what separates "declared one commit later"
        # from "published and then removed" — and the second is the shape no
        # audit of the current tree can see at all.
        tip = {
            "commit": sha,
            "coverage": coverage,
            "exemptions": exemptions,
            "files": set(tree.files),
            "blobs": blobs,
        }
        for rel in tree.files:
            pairs.add((rel, blobs.get(rel, "")))
            if tree.kind(rel) != "file":
                by_reference_entries += 1
        by_reference_signals += counts["submodule-reference"] + counts["external-symlink-target"]
        for finding in tripwire_findings:
            key = (finding.rule, finding.path, blobs.get(finding.path, ""))
            record = found.get(key)
            if record is None:
                found[key] = {
                    "commit": sha,
                    "date": date,
                    "subject": subject,
                    "detail": finding.detail,
                    # A SET of commits, not a count of findings: one blob can
                    # carry several signals of the same rule (a GPL body, a
                    # foreign SPDX tag and a foreign copyright line are three
                    # `foreign-license-text` hits), and counting findings here
                    # would report a one-commit carrier as "present in 3
                    # commits".
                    "commits": {sha},
                }
            else:
                record["commits"].add(sha)
    findings = []
    standing = {TIP_ANSWERED: 0, TIP_ABSENT: 0, TIP_SIGNAL_GONE: 0, TIP_UNANSWERED: 0}
    for (rule, rel, _oid), record in sorted(found.items()):
        if tip is None:  # pragma: no cover - no commit was judged at all
            where = TIP_UNANSWERED
        elif rel not in tip["files"]:
            where = TIP_ABSENT
        elif rule in tip["coverage"].get(rel, ()) or (
            tip["exemptions"].get(rel, {}).get(rule) is not None
        ):
            where = TIP_ANSWERED
        elif rule not in {
            hit
            for hit, _evidence in signals.get(
                (rel, tip["blobs"].get(rel, ""), HISTORY_VIEW), ()
            )
        }:
            # The path is still there, has no answer, and needs none: the bytes
            # that signalled are not the bytes the tip publishes. Distinct from
            # the case below, which the ordinary tree audit would fail on too —
            # and distinct from TIP_ABSENT, where the whole path went away.
            where = TIP_SIGNAL_GONE
        else:
            where = TIP_UNANSWERED
        standing[where] += 1
        findings.append(
            Finding(
                rule,
                commit_label(rel, record["commit"]),
                f"first published by {record['commit'][:12]} ({record['date']}) "
                f"{record['subject']!r}, present in {len(record['commits'])} "
                f"commit(s) in range; {where} — {record['detail']}",
            )
        )
    by_rule = {rule: 0 for rule in TRIPWIRE_RULES}
    for hits in signals.values():
        for rule, _evidence in hits:
            by_rule[rule] += 1
    stats = {
        "range": str(revrange),
        "commits_in_range": len(commits),
        "commits_judged": judged,
        # NOT_RUN, printed even when empty: "no commit predates the manifest" and
        # "half the range was never looked at" must not look alike.
        "commits_not_judged_no_answer_set_yet": unjudged,
        "commits_that_published_no_manifest_after_one_existed": dropped,
        "commits_whose_record_index_could_not_be_parsed": unreadable_index,
        "distinct_path_blob_pairs_published": len(pairs),
        # Regular-file signal derivations, memoised per (path, blob): the number
        # of distinct blobs this run actually read, as opposed to the number of
        # (commit, path) slots they occupy.
        "distinct_pairs_examined_for_signals": len(signals),
        "distinct_carriage_signals": sum(len(v) for v in signals.values()),
        "distinct_carriage_signals_by_rule": by_rule,
        "unanswered_signals": len(found),
        "range_tip_commit": None if tip is None else tip["commit"],
        "findings_by_standing_at_the_range_tip": standing,
        # By-reference entries are re-judged per commit (their evidence comes
        # from the tree around them, not from bytes of their own), so these are
        # per-commit totals rather than distinct counts, and say so.
        "by_reference_entry_slots_judged": by_reference_entries,
        "by_reference_signals_per_commit_total": by_reference_signals,
    }
    return findings, stats


def report_history(findings, stats, root, as_json=False):
    if as_json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "mode": "history",
                    "verdict": "PASS" if not findings else "FAIL",
                    "coverage": stats,
                    "findings": [f.as_dict() for f in findings],
                    "caveat": CAVEAT + HISTORY_CAVEAT,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    unjudged = stats["commits_not_judged_no_answer_set_yet"]
    dropped = stats["commits_that_published_no_manifest_after_one_existed"]
    unreadable = stats["commits_whose_record_index_could_not_be_parsed"]
    print(f"provenance history audit of {root}")
    print(f"  range: {stats['range']}")
    print(
        f"coverage: {stats['commits_in_range']} commits in range, "
        f"{stats['commits_judged']} judged, {len(unjudged)} NOT judged"
    )
    print(
        f"  not judged (no provenance manifest had been published yet in this "
        f"range — NOT_RUN, not a pass): {len(unjudged)} commit(s)"
    )
    for item in unjudged[:HISTORY_COMMITS_LISTED]:
        print(f"      not judged: {item['commit'][:12]} ({item['date']}) {item['subject']}")
    if len(unjudged) > HISTORY_COMMITS_LISTED:
        print(
            f"      … and {len(unjudged) - HISTORY_COMMITS_LISTED} more "
            "(full list in --json)"
        )
    print(
        f"  published no manifest after one had existed (judged with NO "
        f"answers): {len(dropped)} commit(s)"
    )
    for item in dropped[:HISTORY_COMMITS_LISTED]:
        print(f"      judged with no answer set: {item['commit'][:12]} ({item['date']})")
    print(
        f"  decision-record index unparseable (row set unknown, carriage still "
        f"judged): {len(unreadable)} commit(s)"
    )
    print(
        f"  distinct (path, blob) pairs published by the judged commits: "
        f"{stats['distinct_path_blob_pairs_published']}, of which "
        f"{stats['distinct_pairs_examined_for_signals']} were read for content "
        "signals (each blob once, however many commits carry it)"
    )
    hits = ", ".join(
        f"{k}={v}" for k, v in sorted(stats["distinct_carriage_signals_by_rule"].items())
    )
    print(
        f"  distinct carriage signals in those pairs: "
        f"{stats['distinct_carriage_signals']} — {hits}"
    )
    print(
        f"  by-reference entries judged (per-commit slots): "
        f"{stats['by_reference_entry_slots_judged']}, signalling "
        f"{stats['by_reference_signals_per_commit_total']} time(s)"
    )
    standing = stats["findings_by_standing_at_the_range_tip"]
    print(
        "  findings by standing at the range tip "
        f"({(stats['range_tip_commit'] or 'none')[:12]}): "
        + ", ".join(f"{k} = {v}" for k, v in sorted(standing.items()))
    )
    if findings:
        print(f"\nFAIL: {len(findings)} provenance finding(s) in published history:")
        for finding in findings:
            print(f"  [{finding.rule}] {finding.path}")
            print(f"      {finding.detail}")
    else:
        print(
            f"\nPASS: every carriage signal in the {stats['commits_judged']} "
            "judged commit(s) is answered by the provenance bookkeeping that "
            "same commit publishes."
        )
    print(CAVEAT + HISTORY_CAVEAT)




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
