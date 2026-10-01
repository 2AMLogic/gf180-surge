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
     there.
  3. **Provenance manifest integrity** — `decision-records/provenance.json`
     rows are exact and current: the path exists, the class is known, the
     cited decision record exists and is indexed, and the file itself
     corroborates the row (it cites the record, or the pinned upstream
     commit the row names). Stale rows, blanket patterns, and exemptions
     that match nothing all fail.
  4. **Undeclared-carrier tripwires** — content signals that a file carries
     third-party material. A tripwire hit must be answered by a provenance
     row (or, for the one exemptible rule, by an explicit exemption with a
     reason — optionally scoped to named *occurrences* of the quotation
     vocabulary in one file, so a later foreign quotation elsewhere in the
     same file still fails). The tripwires are deliberately high-precision:
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
                                         it wraps
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
    `discovery/in-repo-symlink-to-a-regular-file-passes`).
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
    (increment 9), which is the only signal a marker-free member has. Two
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
      - an inflation that hits the 256 MiB budget or the 4-deep wrapper limit is
        reported as a TRUNCATED payload scan on every run and in `--json`, which
        is a disclosed partial read, not a pass. A wrapper the audit cannot open
        at all (a corrupt stream) likewise yields no member names, and the
        coverage line reports how many names were read so "none offended" and
        "none examined" do not look alike.
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
    harvest applies in bytes.
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
    previous increment's own declared residual.
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
a committed gitlink, a nested repository in a non-git tree, and an escaping
symlink must each produce a finding, a declared one must not, and a plain
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
only name, an asset member two wrappers deep, and a `.wt` member that is itself
a gzip (whose outer name must not be masked by the inner one) must each produce
a finding; a row declaring `covers` must clear it and the same row WITHOUT
`covers` must not; and this repository's own gzipped trace carrying an FNAME,
plus an `.npz` of `.npy` members, must stay clean.

Usage:
    python3 tools/check_provenance.py                # audit this repository
    python3 tools/check_provenance.py --root DIR     # audit another tree
    python3 tools/check_provenance.py --json         # machine-readable report
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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_REL = "decision-records/provenance.json"
INDEX_REL = "decision-records/README.md"
RECORD_DIR_REL = "decision-records"

SCHEMA_VERSION = 1

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
    "external-reference": "a by-reference link to content outside this tree",
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
    "exemption-bad-pattern": "exemption pattern too broad or malformed",
    "scope-exclusion-stale": "declared scope exclusion matching no file",
    "scan-underflow": "fewer files scanned than the manifest's declared floor",
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

# Bounds, so a decompression bomb cannot hang or OOM the audit. Both are
# generous against this tree (its largest inflation is ~15 MiB at depth 1) and
# neither is silent: a payload that hits either is reported as truncated on
# every run and in `--json`, because a scan that could not finish must never
# look like one that passed.
MAX_UNWRAPPED_BYTES = 256 * 1024 * 1024
MAX_UNWRAP_DEPTH = 4

# A run of printable ASCII long enough to hold a word, and the word test
# itself. Three consecutive letters is the cheapest filter that keeps every
# license/copyright vocabulary word ("GNU", "Copyright", "GPL-3.0-or-later",
# a holder name) while discarding PCM and float noise: dropping a WORDLESS run
# can only bring two surviving runs CLOSER together, so it cannot break a
# phrase the rules would otherwise have matched.
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


def _unwrap_stream(raw: bytes, kind: str, limit: int):
    """(payload, truncated) for a single-stream wrapper, or (None, False).

    The `*File` wrappers are used rather than the one-shot `decompress()`
    helpers because they handle CONCATENATED streams (a multi-member gzip) and
    because `read(limit + 1)` bounds the inflation without materialising it.
    """
    openers = {
        "gzip": lambda buf: gzip.GzipFile(fileobj=buf, mode="rb"),
        "bzip2": lambda buf: bz2.BZ2File(buf, "rb"),
        "xz": lambda buf: lzma.LZMAFile(buf, "rb"),
    }
    try:
        with openers[kind](io.BytesIO(raw)) as handle:
            out = handle.read(limit + 1)
    except Exception:
        # Corrupt or not actually this wrapper. Not a finding: the payload falls
        # through to the string harvest, and whatever it is stays disclosed.
        return None, False
    if len(out) > limit:
        return out[:limit], True
    return out, False


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


# Joins a wrapper's name to the name of what it wraps. Every component of a
# joined label is tripwired separately, so an outer name is never masked by the
# inner one (`Bank Sine.wt!meta.json` must still read as a `.wt`).
MEMBER_JOIN = "!"


def _join_member(outer, inner):
    if outer and inner:
        return f"{outer}{MEMBER_JOIN}{inner}"
    return outer or inner or ""


def _unwrap_archive(raw: bytes, limit: int):
    """([(member name, payload)], truncated) for a zip/tar, or (None, False)."""
    buf = io.BytesIO(raw)
    members = None
    try:
        if zipfile.is_zipfile(buf):
            members = []
            remaining = limit
            with zipfile.ZipFile(buf) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    with archive.open(info) as handle:
                        data = handle.read(remaining + 1)
                    if len(data) > remaining:
                        return members + [(info.filename, data[:remaining])], True
                    remaining -= len(data)
                    members.append((info.filename, data))
            return members, False
    except Exception:
        return None, False
    buf.seek(0)
    try:
        if not tarfile.is_tarfile(buf):
            return None, False
        buf.seek(0)
        members = []
        remaining = limit
        with tarfile.open(fileobj=buf, mode="r") as archive:
            for info in archive:
                if not info.isfile():
                    continue
                handle = archive.extractfile(info)
                if handle is None:  # pragma: no cover - sparse/odd member
                    continue
                data = handle.read(remaining + 1)
                if len(data) > remaining:
                    return members + [(info.name, data[:remaining])], True
                remaining -= len(data)
                members.append((info.name, data))
        return members, False
    except Exception:
        return None, False


def unwrap_payload(raw: bytes, limit=None, depth=0):
    """([(member name, payload)] carried inside `raw`, truncated), or (None, …).

    `None` means `raw` is not a wrapper — not that it is safe. Recurses so that
    a `.tar.gz` (and a `.tar.gz` inside a zip) is unwrapped to its real members;
    `truncated` is True when the inflation budget or the depth limit stopped the
    walk, so the caller can disclose an incomplete scan instead of reporting a
    pass.

    The member NAME travels with its payload (increment 9). Unwrapping read
    member CONTENT only, so a wrapper whose members carry no marker — a zip of
    upstream `.wt` wavetables, a tar of marker-free `.cpp` sources — was
    answered by nothing: the archive extensions judge the OUTER name, which a
    `.dat` rename evades. A member that is itself a wrapper keeps its own name
    in the label (`dsp/Reverb1.h.gz!…`) rather than being replaced by what it
    wraps.
    """
    if limit is None:
        limit = MAX_UNWRAPPED_BYTES
    if depth >= MAX_UNWRAP_DEPTH:
        return None, _looks_like_wrapper(raw)
    for magic, kind in STREAM_WRAPPERS:
        if not raw.startswith(magic):
            continue
        inner, truncated = _unwrap_stream(raw, kind, limit)
        if inner is None:
            return None, False
        label = _gzip_header_name(raw) if kind == "gzip" else None
        deeper, deeper_truncated = unwrap_payload(inner, limit, depth + 1)
        truncated = truncated or deeper_truncated
        if deeper is not None:
            return [
                (_join_member(label, name), payload) for name, payload in deeper
            ], truncated
        return [(_join_member(label, ""), inner)], truncated
    members, truncated = _unwrap_archive(raw, limit)
    if members is None:
        return None, truncated
    entries = []
    for name, member in members:
        deeper, deeper_truncated = unwrap_payload(member, limit, depth + 1)
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
                seen.setdefault(rel, (kind, blob if kind == "gitlink" else ""))
            return sorted((rel, kind, blob) for rel, (kind, blob) in seen.items())
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(_walk_entries(root))


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


def list_files(root: Path):
    """Repo-relative POSIX paths of candidate entries, deterministically sorted."""
    return [rel for rel, _, _ in list_entries(root)]


SUBMODULE_PATH_RE = re.compile(r"^\s*path\s*=\s*(.+?)\s*$")
SUBMODULE_URL_RE = re.compile(r"^\s*url\s*=\s*(.+?)\s*$")


def parse_gitmodules(root: Path):
    """{submodule path: url} from `.gitmodules`, best effort (evidence only)."""
    try:
        text = (root / ".gitmodules").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
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

    def __init__(self, root: Path, exclusions):
        self.root = root
        self.exclusions = exclusions
        entries = list_entries(root)
        self.all_files = [rel for rel, _, _ in entries]
        self.kinds = {rel: kind for rel, kind, _ in entries}
        self.gitlink_commits = {
            rel: blob for rel, kind, blob in entries if kind == "gitlink" and blob
        }
        self.submodule_urls = parse_gitmodules(root)
        self.excluded = {}
        self.files = []
        for rel in self.all_files:
            hit = self.excluded_by(rel)
            if hit is None:
                self.files.append(rel)
            else:
                self.excluded.setdefault(hit, []).append(rel)
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

    def text(self, rel):
        """Text for the content rules, or None when the entry yields none.

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
        if rel in self._text_cache:
            return self._text_cache[rel]
        value, mode, truncated, names, wide = self._read(rel)
        self._scan_modes[rel] = mode
        self._carried_names[rel] = tuple(names)
        self._wide_runs[rel] = wide
        if truncated:
            self._truncated.add(rel)
        self._text_cache[rel] = value
        return value

    def _read(self, rel):
        """(text|None, scan mode, truncated, member names, wide runs) for an entry."""
        try:
            with (self.root / rel).open("rb") as handle:
                head = handle.read(BINARY_SNIFF_BYTES)
                encoding = sniff_encoding(head)
                raw = head + handle.read()
        except OSError:
            # A by-reference entry (a gitlink, a symlink to a directory) and an
            # unreadable file both land here; the discovery layer judges those.
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

    def scan_mode(self, rel):
        """"decoded" | "unwrapped" | "strings" | "none" | "unreadable"."""
        if rel not in self._scan_modes:
            self.text(rel)
        return self._scan_modes.get(rel, "unreadable")

    def carried_names(self, rel):
        """Member names the wrapper at `rel` carries inside it (may be empty).

        Forces the read, like `scan_mode`: the unwrap that recovers these names
        happens there. Empty for every entry that is not a wrapper the audit
        could open — a corrupt stream and anything past the depth/inflation
        budget carry no names here, and that partial read is disclosed as a
        TRUNCATED payload scan rather than counted as a pass.
        """
        if rel not in self._carried_names:
            self.text(rel)
        return self._carried_names.get(rel, ())

    def wide_runs(self, rel):
        """How many wide-encoded runs this entry's payload yielded (increment 10).

        Forces the read, like `scan_mode`. Zero for a decoded file — a file the
        sniff admits is read whole, in its own encoding, by every content rule.
        """
        if rel not in self._wide_runs:
            self.text(rel)
        return self._wide_runs.get(rel, 0)

    def truncated_scans(self):
        """Paths whose payload scan hit the inflation/depth budget."""
        return sorted(self._truncated)

    def lower(self, rel):
        """Lowercased text — the cheap prefilter for every signal.

        Cached for ordinary decoded files. A payload-derived text (an inflated
        trace, a harvested render) is NOT cached: keeping a second copy of every
        unwrapped payload roughly doubled the audit's peak memory, and
        `str.lower()` on the few large ones costs milliseconds.
        """
        if rel in self._lower_cache:
            return self._lower_cache[rel]
        text = self.text(rel)
        value = None if text is None else text.lower()
        if value is None or self._scan_modes.get(rel) == "decoded":
            self._lower_cache[rel] = value
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
    findings = []
    for rel in tree.files:
        if rel == MANIFEST_REL:
            continue
        low = tree.lower(rel)
        # Cheap prefilter (superset of RECORD_CITATION_RE): skip files that
        # cannot cite a record at all.
        if low is None or not any(
            token in low for token in ("decision-records/", "dr-0", "dr0")
        ):
            continue
        text = tree.text(rel)
        for number in sorted(set(RECORD_CITATION_RE.findall(text))):
            if number not in records:
                findings.append(
                    Finding(
                        "dangling-record-citation",
                        rel,
                        f"cites decision record {number}, which does not exist",
                    )
                )
            elif number not in rows:
                findings.append(
                    Finding(
                        "unindexed-record-citation",
                        rel,
                        f"cites decision record {number}, which is missing from "
                        f"the {INDEX_REL} index",
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


def load_manifest(root: Path):
    path = root / MANIFEST_REL
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("manifest-missing", MANIFEST_REL, f"cannot read: {exc}")]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [Finding("manifest-missing", MANIFEST_REL, f"invalid JSON: {exc}")]
    if not isinstance(data, dict):
        return None, [Finding("manifest-schema", MANIFEST_REL, "top level must be an object")]
    findings = []
    if data.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "manifest-schema",
                MANIFEST_REL,
                f"schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}",
            )
        )
    for key in ("entries", "exemptions", "scope_exclusions"):
        value = data.get(key, [])
        if not isinstance(value, list):
            findings.append(Finding("manifest-schema", MANIFEST_REL, f"{key!r} must be a list"))
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


def check_manifest(tree: Tree, manifest, records, rows):
    """Validate rows/exemptions and return (findings, coverage)."""
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
            findings.append(Finding("manifest-schema", MANIFEST_REL, f"{label} must be an object"))
            continue
        if bool(entry.get("path")) == bool(entry.get("pattern")):
            findings.append(
                Finding(
                    "manifest-field-missing",
                    MANIFEST_REL,
                    f"{label}: exactly one of 'path' or 'pattern' is required",
                )
            )
            continue
        missing = [f for f in REQUIRED_ENTRY_FIELDS if not entry.get(f)]
        if missing:
            findings.append(
                Finding(
                    "manifest-field-missing",
                    MANIFEST_REL,
                    f"{label} ({entry.get('path') or entry.get('pattern')}): "
                    f"missing required field(s) {missing}",
                )
            )
        if entry.get("class") and entry["class"] not in KNOWN_CLASSES:
            findings.append(
                Finding(
                    "manifest-unknown-class",
                    MANIFEST_REL,
                    f"{label}: class {entry['class']!r} not in "
                    f"{sorted(KNOWN_CLASSES)}",
                )
            )
        kind, target, matches = _matcher(entry)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("manifest-bad-pattern", MANIFEST_REL, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "manifest-stale-path",
                    MANIFEST_REL,
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
                        MANIFEST_REL,
                        f"{label}: decision_record {number!r} does not exist",
                    )
                )
            elif number not in rows:
                findings.append(
                    Finding(
                        "manifest-unindexed-record",
                        MANIFEST_REL,
                        f"{label}: decision_record {number!r} is not in the index",
                    )
                )
        covers_raw = entry.get("covers")
        covers_declared = set()
        if covers_raw is not None:
            if not isinstance(covers_raw, list):
                findings.append(
                    Finding("manifest-schema", MANIFEST_REL, f"{label}: 'covers' must be a list")
                )
            else:
                bad = [r for r in covers_raw if r not in TRIPWIRE_RULES]
                if bad:
                    findings.append(
                        Finding(
                            "manifest-schema",
                            MANIFEST_REL,
                            f"{label}: 'covers' rule(s) {bad} not in {sorted(TRIPWIRE_RULES)}",
                        )
                    )
                covers_declared = {r for r in covers_raw if r in TRIPWIRE_RULES}
        for rel in hits:
            coverage.setdefault(rel, set()).update(
                _structural_tripwire_rules(tree, rel) | covers_declared
            )
            findings.extend(_corroborate(tree, rel, entry, number, label))

    for index, item in enumerate(manifest.get("exemptions", []) or []):
        label = f"exemptions[{index}]"
        if not isinstance(item, dict):
            findings.append(Finding("manifest-schema", MANIFEST_REL, f"{label} must be an object"))
            continue
        if bool(item.get("path")) == bool(item.get("pattern")):
            findings.append(
                Finding(
                    "exemption-field-missing",
                    MANIFEST_REL,
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
                    MANIFEST_REL,
                    f"{label}: non-empty 'rules' list and 'reason' are required",
                )
            )
            rules = rules if isinstance(rules, list) else []
        bad = [r for r in rules if r not in EXEMPTIBLE_RULES]
        if bad:
            findings.append(
                Finding(
                    "exemption-non-exemptible-rule",
                    MANIFEST_REL,
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
                        MANIFEST_REL,
                        f"{label}: 'occurrences' must be a non-empty list of "
                        "non-empty strings",
                    )
                )
                continue
            if not item.get("path"):
                findings.append(
                    Finding(
                        "exemption-bad-pattern",
                        MANIFEST_REL,
                        f"{label}: 'occurrences' requires an exact 'path', not a pattern",
                    )
                )
                continue
        kind, target, matches = _matcher(item)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("exemption-bad-pattern", MANIFEST_REL, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "exemption-stale",
                    MANIFEST_REL,
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
                    live = [
                        (start, end)
                        for start, end in located
                        if any(start <= mk.start() and mk.end() <= end for _, mk in markers)
                    ]
                    if not live:
                        findings.append(
                            Finding(
                                "exemption-stale",
                                MANIFEST_REL,
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
                        exemptions[rel][rule] = {"reason": reason, "spans": spans}
                    else:
                        current["spans"].extend(spans)

    for index, item in enumerate(manifest.get("scope_exclusions", []) or []):
        label = f"scope_exclusions[{index}]"
        if not isinstance(item, dict) or not item.get("prefix") or not item.get("reason"):
            findings.append(
                Finding(
                    "manifest-schema",
                    MANIFEST_REL,
                    f"{label}: 'prefix' and 'reason' are required",
                )
            )
            continue
        if not tree.excluded.get(str(item["prefix"])):
            findings.append(
                Finding(
                    "scope-exclusion-stale",
                    MANIFEST_REL,
                    f"{label}: prefix {item['prefix']!r} excludes nothing "
                    "(stale — remove it)",
                )
            )

    floor = manifest.get("scan_floor")
    if isinstance(floor, int) and len(tree.files) < floor:
        findings.append(
            Finding(
                "scan-underflow",
                MANIFEST_REL,
                f"scanned {len(tree.files)} in-scope files, below the declared "
                f"scan_floor of {floor} — the audit may have walked the wrong "
                "tree; a partial scan is not a pass",
            )
        )
    return findings, coverage, exemptions


def _corroborate(tree: Tree, rel, entry, number, label):
    """The file must show the provenance its row claims (row != reality guard)."""
    commit = str(entry.get("pinned_commit") or "").strip()
    kind = tree.kind(rel)
    if kind == "gitlink":
        # A gitlink carries its own pin, so corroboration is exact here: the
        # commit in the index is what a build checks out, whatever the row says.
        actual = tree.gitlink_commits.get(rel)
        if actual and commit and actual.lower() != commit.lower():
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
    text = tree.text(rel)
    if kind == "symlink":
        if text is None:
            # The target is not readable here (an external tree, absent at
            # audit time). There is no file body in which to state provenance,
            # so the row and its record are the only description — as for a
            # binary payload. The structural tripwire is what makes the row
            # mandatory in the first place.
            return []
        # The link target is what a reviewer reads first; search it alongside
        # the content the link resolves to.
        try:
            text = text + "\n" + os.readlink(tree.root / rel)
        except OSError:  # pragma: no cover - raced away
            pass
    if text is None:
        return []  # binary payload: nothing to read; the row is the record
    tokens = []
    if number:
        tokens.append(f"decision-records/{number}")
        tokens.append(f"DR-{number}")
        tokens.append(f"DR{number}")
    if len(commit) >= 8:
        tokens.append(commit[:8])
    if not tokens:
        return []
    if any(token.lower() in text.lower() for token in tokens):
        return []
    return [
        Finding(
            "manifest-uncorroborated",
            rel,
            f"{label}: the file cites neither decision record {number or '????'} "
            f"nor the pinned commit {commit[:12] or '(none given)'} — state the "
            "provenance in the file, or fix the row",
        )
    ]


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
    return detail + " — its files are in the build tree but not in this audit"


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


def _structural_tripwire_rules(tree: Tree, rel):
    """Tripwire rules implied by the ENTRY itself, not by any text it holds.

    Extension rules plus the by-reference kinds. Like an extension rule, the
    kind is a property of the whole entry — a gitlink *is* a reference to
    another tree, a symlink *is* its target — so a row naming this exact path
    describes it in full and covers the rule without a 'covers' declaration.
    The content-signal rules still require 'covers', because text can appear
    anywhere in a file regardless of what the row's 'content' field says.
    """
    rules = _extension_tripwire_rules(rel)
    kind = tree.kind(rel)
    if kind == "gitlink":
        rules.add("submodule-reference")
    elif kind == "symlink":
        rules.add("external-symlink-target")
    return rules


def tripwire_hits(tree: Tree, rel):
    """[(rule, evidence)] for content signals of third-party carriage.

    Each signal is gated behind a cheap lowercase substring prefilter; the
    regexes below only run on files that could match. The prefilter tokens
    must stay a SUPERSET of what each regex can match, or the rule silently
    stops firing — `--negative-control` is what catches that mistake.
    """
    hits = []
    # The discovery layer first: an entry that carries its content by reference
    # has no bytes of its own for any signal below to read.
    kind = tree.kind(rel)
    if kind == "gitlink":
        # Nothing further applies: a gitlink has no extension and no text.
        return [("submodule-reference", submodule_evidence(tree, rel))]
    if kind == "symlink":
        escape = symlink_escape(tree, rel)
        if escape is not None:
            hits.append(("external-symlink-target", escape))
        # Deliberately NOT a return: `text()` follows the link, so a target
        # that does resolve is still read by every content rule below.
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
        for label in tree.carried_names(rel)
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
    text = tree.text(rel)
    if text is None:
        return hits
    low = tree.lower(rel)
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


def check_tripwires(tree: Tree, coverage, exemptions):
    findings = []
    counts = {rule: 0 for rule in TRIPWIRE_RULES}
    for rel in tree.files:
        for rule, evidence in tripwire_hits(tree, rel):
            counts[rule] += 1
            if rule in coverage.get(rel, ()):
                continue
            exemption = exemptions.get(rel, {}).get(rule)
            if exemption and exemption["spans"] is None:
                continue
            if exemption:
                # Occurrence-scoped: exempt only markers inside a named span.
                outside = [
                    (name, match)
                    for name, match in quotation_marker_matches(tree.text(rel) or "")
                    if not any(
                        start <= match.start() and match.end() <= end
                        for start, end in exemption["spans"]
                    )
                ]
                if not outside:
                    continue
                name, match = outside[0]
                evidence = (
                    f"{name}: {_snippet(tree.text(rel), match)} (outside the "
                    "occurrence(s) its exemption names)"
                )
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
    return findings, counts


# --- audit driver -------------------------------------------------------------


def audit(root: Path):
    root = Path(root)
    manifest, findings = load_manifest(root)
    if manifest is None:
        manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
    tree = Tree(root, scope_exclusion_prefixes(manifest))
    records, record_findings = parse_records(tree)
    rows, index_findings = parse_index(tree)
    findings = list(findings) + record_findings + index_findings
    findings += check_index(records, rows)
    findings += check_citations(tree, records, rows)
    manifest_findings, coverage, exemptions = check_manifest(tree, manifest, records, rows)
    findings += manifest_findings
    tripwire_findings, tripwire_counts = check_tripwires(tree, coverage, exemptions)
    findings += tripwire_findings
    stats = {
        "files_scanned": len(tree.files),
        "files_excluded": sum(len(v) for v in tree.excluded.values()),
        "exclusions": {k: len(v) for k, v in sorted(tree.excluded.items())},
        "records": len(records),
        "index_rows": len(rows),
        "provenance_rows": len(manifest.get("entries", []) or []),
        "files_covered_by_rows": len(coverage),
        "exemptions": len(manifest.get("exemptions", []) or []),
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
        "entries_by_reference": {
            kind: sum(1 for rel in tree.files if tree.kind(rel) == kind)
            for kind in ("symlink", "gitlink")
        },
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


# --- negative control (self-test) --------------------------------------------


SKELETON_RECORD = """# 0001: Example quoted constants (synthetic)

- **Status**: ratified
- **Date**: 2026-01-01

## Decision

Synthetic record used only by the provenance audit's negative control.
"""

SKELETON_INDEX = """# Decision records

## Index

| Number | Title | Status | Date |
|---|---|---|---|
| [0001](0001-example.md) | Example quoted constants (synthetic) | ratified | 2026-01-01 |
"""

SKELETON_CARRIER = '''"""Synthetic carrier.

Constants below are QUOTED as data from
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71;
licensing decision: decision-records/0001-example.md.
"""

TABLE = [1, 2, 3]
'''


def _write(root: Path, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def build_skeleton(root: Path):
    """A minimal tree that must audit clean."""
    _write(root, f"{RECORD_DIR_REL}/0001-example.md", SKELETON_RECORD)
    _write(root, INDEX_REL, SKELETON_INDEX)
    _write(root, "model/carrier.py", SKELETON_CARRIER)
    _write(root, "docs/plain.md", "A document with no third-party content.\n")
    _write(
        root,
        MANIFEST_REL,
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "scan_floor": 1,
                "scope_exclusions": [],
                "entries": [
                    {
                        "path": "model/carrier.py",
                        "class": "quoted-constants",
                        "content": "synthetic TABLE",
                        "upstream": "synthetic upstream",
                        "pinned_commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
                        "upstream_license": "GPL-3.0-or-later",
                        "decision_record": "0001",
                        "covers": ["self-declared-quotation"],
                    }
                ],
                "exemptions": [],
            },
            indent=2,
        )
        + "\n",
    )


# NOTE — the fixture strings below are deliberately assembled from fragments.
# If this file contained a contiguous foreign license body, copyright line or
# decision-record citation, the audit would (correctly) flag its own source as
# unattributed carriage — and the only ways out would be to exempt a
# non-exemptible rule or to special-case the audit's own path, both of which
# would punch a hole in the rule set. Assembling at runtime keeps the rules
# intact and the synthetic violations byte-identical to the real thing. Do not
# "tidy" these into single literals.
FIXTURE_GPL_BODY = (
    '"""Helper.\n\n'
    + "GNU GENERAL "
    + "PUBLIC LICENSE Version 3\n"
    + "Copy"
    + "right (C) 20"
    + "16 Somebody Else\n"
    + "This program is "
    + 'free software.\n"""\n'
)
FIXTURE_RECORD_CITATION = "Licensing: see " + "decision-records/" + "0099.\n"
FIXTURE_TRANSCRIBED = (
    '"""Table '
    + "transcribed from "
    + "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71.\n"
    + '"""\n\nT = [4, 5, 6]\n'
)


# An in-repo document that cites the pinned upstream AND says it carries a
# verbatim copy of this project's OWN model (the model/oscillators/classic
# README shape that landed with #181). Plus a genuinely foreign quotation, in
# the SAME marker wording, that an occurrence-scoped exemption must not hide.
FIXTURE_OWN_COPY_DOC = (
    "Pinned structure (read and cited, never copied): "
    + "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71.\n\n"
    + "`run_model.py` instantiates the shared `voice_model.HalfbandD2`, and\n"
    + "`tb_own.sv` carries a\nverbatim copy of it.\n"
)
FIXTURE_OWN_COPY_OCCURRENCE = "`tb_own.sv` carries a verbatim copy of it"
FIXTURE_FOREIGN_COPY_LINE = (
    "\nThe table below is copied verbatim from the pinned upstream wavetable.\n"
)


# --- masking fixtures ---------------------------------------------------------
#
# Our OWN attribution above a pasted upstream one. This is how the
# non-exemptible `foreign-license-text` rule was disarmed before: the signal
# read only the FIRST copyright line / SPDX tag in a file, and judged that
# line's holder from a ±120-char window that any nearby mention of this
# project satisfied. Both shapes below audited clean until the fix; both must
# fail now, and our own attribution alone must still audit clean (a rule that
# fires on our own header would just be turned off again).
# Assembled from fragments, like the fixtures above — see the fixture note.
FIXTURE_OWN_COPYRIGHT = "# Copy" + "right 20" + "26 2AM" + "Logic\n"
FIXTURE_OWN_SPDX_TAG = "# SPDX-License" + "-Identifier" + ": Apache-2.0\n"
FIXTURE_OWN_PROJECT_LINE = "# This module belongs to the gf180-surge model.\n"
FIXTURE_FOREIGN_COPYRIGHT_LINE = "# Copy" + "right (C) 20" + "19 Some Upstream Author\n"
FIXTURE_FOREIGN_SPDX_TAG = "# SPDX-License" + "-Identifier" + ": GPL-3.0-or-later\n"

# Increment 3 — the same masking one level in. Each of these audited clean on
# the non-exemptible rule while every rule still "fired" in the self-test:
#
#   * our project named in the foreign notice's own HOLDER line (a
#     parenthetical, or after a spaced hyphen) — the line-scoped holder test
#     from increment 2 read the whole line, so the mention suppressed it;
#   * an SPDX *expression* whose leading operand is our own licence — only the
#     first whitespace-delimited word was compared, so every other operand was
#     invisible (and `Apache-2.0 OR <foreign>` is the standard dual-licence
#     spelling, not an exotic one);
#   * a license body wrapped mid-phrase across a comment leader — the plain
#     `\s+` between words does not span `"\n# "`, and the multi-word prefilter
#     did not survive the wrap either.
FIXTURE_FOREIGN_COPYRIGHT_PARENTHETICAL = (
    "# Copy" + "right (C) 20" + "19 Some Upstream Author (adapted for gf180-surge)\n"
)
FIXTURE_FOREIGN_COPYRIGHT_AFTER_DASH = (
    "# Copy" + "right 20" + "19 Chris Johnson - reworked for gf180-surge\n"
)
FIXTURE_COMPOUND_SPDX_OWN_FIRST = (
    "# SPDX-License" + "-Identifier" + ": Apache-2.0 OR GPL-3.0-or-later\n"
)
FIXTURE_WRAPPED_FSF_BODY = (
    "#  This program is " + "free\n#  software; you can redistribute it.\n"
)
FIXTURE_WRAPPED_GPL_TITLE = "/*\n * GNU " + "GENERAL\n * PUBLIC " + "LICENSE Version 3\n */\n"
# Positive controls: own-attribution layouts that ALSO put a name-like aside or
# a spaced hyphen on the notice line, plus an SPDX tag quoted inside prose.
# A fix that flagged these would be reverted, and the rule with it.
FIXTURE_OWN_COPYRIGHT_WITH_ASIDE = (
    "# Copy" + "right 20" + "26 2AM" + "Logic (gf180-surge model sources)\n"
)
FIXTURE_OWN_COPYRIGHT_AUTHORS = "# Copy" + "right (c) 20" + "26 The gf180-surge Authors\n"
FIXTURE_OWN_COPYRIGHT_AFTER_DASH = "# Copy" + "right 20" + "26 - 2AM " + "Logic\n"
FIXTURE_OWN_SPDX_IN_PROSE = (
    "# The SPDX-License" + "-Identifier" + ": Apache-2.0 tags below are ours.\n"
)
# The deliberate scope boundary (declared, not an oversight): a LEADERLESS
# prose wrap of a license NAME is not a comment-block paste, and is not
# treated as carriage — otherwise ordinary text that names a license would
# become a finding that no exemption could answer (the rule is non-exemptible).
FIXTURE_PROSE_WRAP_LICENSE_NAME = (
    "The record cites the GNU " + "General Public\n" + "License as the upstream terms.\n"
)

# Increment 4 — four more families that audited clean while --negative-control
# still reported every rule firing. All four are the SAME failure shape as
# increments 2 and 3: a signal that stops reading as soon as it has seen enough
# to recognise OUR OWN attribution.
#
#   * the holder field opens with a delimiter, so it held no name and the holder
#     test fell back to searching the WHOLE LINE — the very thing increment 3
#     removed, reinstated for every bracket/semicolon/dash layout;
#   * an SPDX expression whose foreign operand sits past the end of the
#     parseable expression (a comma list, a parenthetical);
#   * a notice with a holder but NO year, which carried no signal at all;
#   * a holder list WRAPPED onto a continuation line that carries no keyword.
FIXTURE_FOREIGN_HOLDER_BEHIND_BRACKETS = (
    "# Copy" + "right (C) 20" + "19 [gf180-surge] Some Upstream Author\n"
)
FIXTURE_FOREIGN_HOLDER_BEHIND_PARENS = (
    "# Copy" + "right (C) 20" + "19 (gf180-surge port) Some Upstream Author\n"
)
FIXTURE_FOREIGN_HOLDER_AFTER_SEMICOLON = (
    "# Copy" + "right 20" + "19; gf180-surge adaptation of Chris Johnson's filter\n"
)
FIXTURE_FOREIGN_HOLDER_AFTER_EM_DASH = (
    "# Copy" + "right 20" + "19 — gf180-surge vendoring of Chris Johnson\n"
)
FIXTURE_SPDX_FOREIGN_AFTER_COMMA = (
    "# SPDX-License" + "-Identifier" + ": Apache-2.0, GPL-3.0-or-later\n"
)
FIXTURE_SPDX_FOREIGN_IN_PARENTHETICAL = (
    "# SPDX-License" + "-Identifier" + ": Apache-2.0 (upstream GPL-3.0-or-later)\n"
)
FIXTURE_YEARLESS_FOREIGN_COPYRIGHT = (
    "# Copy" + "right (C) " + "Chris Johnson / Airwindows\n"
)
FIXTURE_WRAPPED_HOLDER_LIST = (
    FIXTURE_OWN_COPYRIGHT + "#     and " + "Chris Johnson / Airwindows\n"
)
# Positive controls for increment 4: own-attribution and ordinary prose layouts
# that the four fixes above could plausibly have started flagging. Each one is a
# shape that really occurs in this repository (lettered list markers are used
# throughout the decision records and evidence reports), and a false positive
# here would be UNANSWERABLE — `foreign-license-text` cannot be exempted — so
# the rule would be switched off rather than answered.
FIXTURE_OWN_COPYRIGHT_RIGHTS_RESERVED = (
    "# Copy" + "right (c) 20" + "26 2AM " + "Logic, All Rights Reserved.\n"
)
FIXTURE_OWN_COPYRIGHT_CROSS_REFERENCE = (
    "# Copy" + "right 20" + "26 2AM " + "Logic. See LICENSE for terms.\n"
)
FIXTURE_OWN_COPYRIGHT_QUOTED_IN_PROSE = (
    "The header reads \"Copy" + "right (c) 20" + "26 The gf180-surge Authors\". "
    "Anything else names someone else.\n"
)
FIXTURE_OWN_DASH_HOLDER_WITH_ASIDE = (
    "# Copy" + "right 20" + "26 - 2AM " + "Logic (SXT-019 governance)\n"
)
FIXTURE_OWN_COPYRIGHT_THEN_PROSE = (
    FIXTURE_OWN_COPYRIGHT + "# Implements the halfband decimator.\n"
)
FIXTURE_LETTERED_LIST_MARKERS = (
    "## (c) Unknown status string\n\n"
    "| leg | control |\n| --- | --- |\n| (c) | status `DONE` rejected |\n"
)
# Increment 5 — the holder list continues past the NEXT delimiter on the SAME
# line. The segment walk from increment 4 judged the first segment holding a
# name and returned, so a second holder standing after that segment's closing
# delimiter was never read: the same "stop as soon as our own name is
# recognised" shape, one segment to the right. All four audited clean while
# --negative-control reported every rule firing, and all four are how a
# part-vendored file actually gets attributed.
FIXTURE_SECOND_HOLDER_AFTER_SEMICOLON = (
    "# Copy" + "right 20" + "26 2AM " + "Logic; Some Upstream Author\n"
)
FIXTURE_SECOND_HOLDER_IN_PARENTHETICAL = (
    "# Copy" + "right (c) 20" + "26 2AM " + "Logic (from Chris Johnson)\n"
)
FIXTURE_SECOND_HOLDER_AFTER_EM_DASH = (
    "# Copy" + "right 20" + "26 2AM " + "Logic — Chris Johnson\n"
)
FIXTURE_SECOND_HOLDER_AFTER_DASH = (
    "# Copy" + "right 20" + "26 2AM " + "Logic - Some Upstream Author\n"
)
# Positive controls for increment 5, and the two residual limits it declares
# rather than closes (see DECLARED LIMITS at the top of this file): a later
# segment is read as a holder only on a TWO-WORD name shape, and only before the
# segment's first sentence break. Both bounds exist because an own notice that
# became a finding on this non-exemptible rule would be unanswerable.
FIXTURE_OWN_SINGLE_NAME_ASIDE = (
    "# Copy" + "right 20" + "26 2AM " + "Logic (generated from Verilog)\n"
)
FIXTURE_OWN_NOTICE_THEN_SENTENCE = (
    "# Copy" + "right 20" + "26 2AM " + "Logic; see NOTICE. "
    "Chris Johnson's filter is discussed in the record, not carried here.\n"
)
FIXTURE_COPYRIGHT_PROSE_NOT_A_NOTICE = (
    "2. Grant of Copy" + "right License. Subject to the terms and conditions of\n"
    "this record, the Copy" + "right Notice is retained verbatim.\n"
)
# Long enough that the foreign notice is well outside the old ±120-char
# proximity window, so this control isolates the first-match-only bug.
FIXTURE_FILLER = "\n" + "".join(f"ROW_{n} = [{n}, {n}, {n}]\n" for n in range(12)) + "\n"

# Increment 6 — masking one level BELOW the signal layer. Increments 1-5 all
# assumed the file had become text; these never do. A head carrying a NUL was
# classified "binary", and `tripwire_hits` returns before every content rule
# for such a file — so an ordinary source file saved in UTF-16, or an ASCII one
# carrying a single stray NUL, took a complete GPL body, a GPL SPDX tag and a
# foreign copyright notice straight past the non-exemptible rule. Neither needs
# an exotic tool: "Unicode" is a standard editor save, and `.py`/`.sv` are not
# in FOREIGN_SOURCE_EXTS, so no extension tripwire covered them either.
FIXTURE_WIDE_NOTICE_TEXT = (
    "# Copy" + "right (C) 20" + "19 Some Upstream Author\n"
    "# This program is free " + "software; you can redistribute it\n"
    "# under the terms of the GNU " + "General Public License as published\n"
    "# by the Free " + "Software Foundation.\n"
)
# The locator each wide-encoding control requires in its finding's evidence,
# assembled from fragments for the same reason as the fixtures above.
WIDE_NOTICE_LOCATOR = "GNU " + "General Public License"
FIXTURE_UTF16_BOM_NOTICE = FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16")
FIXTURE_UTF16LE_BOMLESS_NOTICE = FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-le")
FIXTURE_UTF16BE_BOMLESS_NOTICE = FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-be")
FIXTURE_STRAY_NUL_NOTICE = (
    b"# \x00 vim: set fileencoding=utf-8 :\n" + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8")
)
# Increment 8 — the PAYLOAD layer, below the decode layer of increment 6. A
# payload the sniff refuses is not evidence-free: it is either a WRAPPER (one
# `read()` from text) or binary data with ASCII runs in it. Until this
# increment all of the fixtures below audited **clean** while
# `--negative-control` reported all 29 rules and all 41 masking controls
# behaving — demonstrated on the real tree in `reports/sxt-019/EVIDENCE.md` §14.
# Assembled from fragments like every other fixture here (see the fixture note).
FIXTURE_PAYLOAD_COPYRIGHT = "Copy" + "right (C) 20" + "19 Some Upstream Author"
PAYLOAD_COPYRIGHT_LOCATOR = "Some Upstream Author"


def _lcg_samples(count, seed=12345):
    """Deterministic pseudo-random 16-bit samples — stand-in render data.

    Noise is the worst case for the string harvest (it maximises the chance of
    an accidental printable run), which is what a positive control wants.
    """
    value = seed
    out = []
    for _ in range(count):
        value = (1103515245 * value + 12345) & 0x7FFFFFFF
        out.append((value >> 8) % 65536 - 32768)
    return out


def _riff_chunk(chunk_id: bytes, payload: bytes):
    if len(payload) % 2:
        payload += b"\x00"
    return chunk_id + struct.pack("<I", len(payload)) + payload


def _wav_payload(info_fields=(), spliced=b"", quiet=False):
    """A real 16-bit PCM WAV, optionally carrying LIST/INFO metadata.

    `ICOP` is the RIFF copyright field — exactly where an upstream sample pack
    or an exported preset render states its holder. None of this repository's
    own renders carries one.

    `spliced` is inserted into the middle of the data chunk, which is how a
    notice rides along inside a real render. `quiet` scales the samples into the
    low-amplitude range this repository's own renders mostly occupy, where the
    high byte of every sample is NUL — the shape a UTF-16-LE string also has
    (increment 10's false-positive hazard).
    """
    fmt = _riff_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16))
    samples = _lcg_samples(2400)
    if quiet:
        samples = [sample // 256 for sample in samples]
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    if spliced:
        middle = len(pcm) // 2
        pcm = pcm[:middle] + spliced + pcm[middle:]
    data = _riff_chunk(b"data", pcm)
    body = b"WAVE" + fmt
    if info_fields:
        info = b"".join(
            _riff_chunk(field, text.encode("ascii") + b"\x00")
            for field, text in info_fields
        )
        body += _riff_chunk(b"LIST", b"INFO" + info)
    body += data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _float_dump(notice=None, spliced=b"", seed=777):
    """A raw float32 dump (the `.f32` shape), optionally with a notice spliced in.

    `notice` is spliced as ASCII (increment 8); `spliced` takes raw bytes, which
    is how a re-encoded notice arrives (increment 10).
    """
    values = [sample / 32768.0 for sample in _lcg_samples(1200, seed=seed)]
    payload = struct.pack(f"<{len(values)}f", *values)
    if notice is not None:
        spliced = notice.encode("ascii")
    if not spliced:
        return payload
    middle = len(payload) // 2
    return payload[:middle] + spliced + payload[middle:]


def _tensor_payload():
    """An `.npy`-shaped payload: a short ASCII header over float data."""
    header = b"\x93NUMPY\x01\x00v\x00{'descr': '<f4', 'fortran_order': False, }"
    return header + b" " * (64 - len(header) % 64) + _float_dump()


def _zip_payload(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return buf.getvalue()


def _tar_gz_payload(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        for name, content in members:
            raw = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return gzip.compress(buf.getvalue())


FIXTURE_WAV_WITH_COPYRIGHT_CHUNK = _wav_payload(
    (
        (b"ICOP", FIXTURE_PAYLOAD_COPYRIGHT),
        (b"IART", "Some Upstream Author"),
    )
)
FIXTURE_PLAIN_PCM_WAV = _wav_payload()
FIXTURE_FLOAT_DUMP_WITH_NOTICE = _float_dump(FIXTURE_WIDE_NOTICE_TEXT)
FIXTURE_PLAIN_FLOAT_DUMP = _float_dump()
FIXTURE_TENSOR_PAYLOAD = _tensor_payload()
FIXTURE_GZIPPED_NOTICE = gzip.compress(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
FIXTURE_XZ_NOTICE = lzma.compress(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
FIXTURE_BZIP2_NOTICE = bz2.compress(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
FIXTURE_ZIP_WITH_NOTICE = _zip_payload(
    (("dsp/Reverb1.h", "/*\n" + FIXTURE_WIDE_NOTICE_TEXT + "*/\n"),)
)
FIXTURE_NPZ_WITH_NOTICE = _zip_payload(
    (("taps.npy", "x"), ("header.txt", FIXTURE_WIDE_NOTICE_TEXT))
)
FIXTURE_TAR_GZ_WITH_NOTICE = _tar_gz_payload(
    (("vendor/filter.cpp", "// " + FIXTURE_WIDE_NOTICE_TEXT),)
)
# Wrapper inside wrapper, one for each recursion site. Neither is reachable by
# the string harvest: the inner layer is itself compressed, so the notice is not
# ASCII anywhere in the outer payload's bytes. (A `.tar.gz` is NOT such a case —
# a tar stores its members uncompressed, so the harvest alone would find it.)
FIXTURE_GZIPPED_ZIP_WITH_NOTICE = gzip.compress(FIXTURE_ZIP_WITH_NOTICE)
FIXTURE_ZIP_WITH_GZIPPED_MEMBER = _zip_payload(
    (("dsp/Reverb1.h.gz", FIXTURE_GZIPPED_NOTICE),)
)
# This repository's own evidence-trace shape: a gzipped JSON trace. 18 are
# tracked, all now inflated and content-scanned, and none may become a finding.
FIXTURE_OWN_GZIPPED_TRACE = gzip.compress(
    json.dumps(
        {
            "fixture": "seq-notes-coverage-v1",
            "tool": "tools/run_fx_model.py",
            "taps": [sample / 32768.0 for sample in _lcg_samples(64, seed=31)],
        },
        indent=1,
    ).encode("utf-8")
)
# The exact payload increment 6 declared out of reach ("a notice sealed inside
# an opaque payload"), kept byte-for-byte so this increment's control is a
# direct inversion of that one: it was `masking/notice-sealed-in-an-opaque-
# payload-stays-out-of-scope`, a POSITIVE control, and is now
# `payload/notice-embedded-in-an-opaque-payload`, which must FIRE.
FIXTURE_NOTICE_IN_AN_OPAQUE_PAYLOAD = (
    bytes(range(256)) * 4
    + (FIXTURE_PAYLOAD_COPYRIGHT + "\n").encode("ascii")
    + bytes(range(256)) * 4
)
# A notice written with the sign spelling (U+00A9) rather than the word, inside
# a payload. The UTF-8 sign is not printable ASCII, so without normalisation it
# ENDS the run and takes the keyword with it: the surviving run reads
# " 2019 Some Upstream Author", which matches no prefilter at all. The sign is
# written as an ESCAPE here, like every other fixture fragment, so this file does
# not itself carry a notice (see the fixture note above).
FIXTURE_COPYRIGHT_SIGN_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=41))
    + ("\u00a9 20" + "19 Some Upstream Author\n").encode("utf-8")
    + struct.pack("<600h", *_lcg_samples(600, seed=42))
)
# Increment 10 — the WIDE-ENCODED run inside a payload. Increment 8 declared
# this out of reach ("the harvest reads ASCII"); the fixture below is kept
# BYTE-FOR-BYTE from that declaration so this increment's control is a direct
# inversion of it, exactly as increment 8 inverted increment 6's
# `masking/notice-sealed-in-an-opaque-payload-stays-out-of-scope`. It was
# `payload/wide-encoded-notice-in-a-payload-stays-out-of-scope`, a POSITIVE
# control, and is now `payload/wide-encoded-notice-in-a-payload`, which must FIRE.
FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=99))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=100))
)
# The same mask in the other byte order, in UTF-32 (both orders), and with a BOM
# in front of it — the four shapes `BOMLESS_WIDE_ENCODINGS` and `BOM_ENCODINGS`
# already name at the decode layer, which a payload-embedded notice reached none
# of. A `.wav`/`.f32` carriage is used rather than a source name so no extension
# tripwire can answer them instead.
FIXTURE_UTF16BE_NOTICE_IN_A_PAYLOAD = _float_dump(
    spliced=FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-be"), seed=101
)
# The same notice spliced at an ODD byte offset. A notice lands on an odd offset
# as often as an even one, and at an odd offset the data byte of each code unit
# sits on the OTHER side of its padding — the reading that was missed first, and
# the reason both windows are read.
FIXTURE_WIDE_NOTICE_AT_AN_ODD_OFFSET = (
    b"\x81" + struct.pack("<600h", *_lcg_samples(600, seed=110))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=111))
)
# The odd-offset case where the FIRST character of the run is load-bearing: a
# bare holder line, with no "(c)" marker and no license body behind it, so
# "opyright 2019 …" — the reading one unit late — matches no prefilter at all and
# the audit comes back clean. This is what makes reading both windows a coverage
# fix rather than a tidiness one.
FIXTURE_WIDE_HOLDER_LINE_AT_AN_ODD_OFFSET = (
    b"\x81" + struct.pack("<600h", *_lcg_samples(600, seed=112))
    + ("Copy" + "right 20" + "19 Some Upstream Author\n").encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=113))
)
FIXTURE_UTF32LE_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=102))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-32-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=103))
)
FIXTURE_UTF32BE_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=104))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-32-be")
    + struct.pack("<600h", *_lcg_samples(600, seed=105))
)
# A real PCM render whose data chunk carries the notice in UTF-16-LE: the
# carriage an exported render actually has, and the shape whose own quiet samples
# are the false-positive hazard this layer had to be measured against.
FIXTURE_WAV_WITH_WIDE_NOTICE = _wav_payload(
    spliced=FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16")
)
# One wrapper deep: a gzip whose member is an opaque payload with a UTF-16-LE
# notice in it. The unwrap resolves the member, the member is still refused by
# the sniff, and only the wide harvest reads it — so this case fails if the
# member path does not harvest wide runs, even when the top-level path does.
FIXTURE_GZIPPED_WIDE_NOTICE_PAYLOAD = gzip.compress(
    FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD
)
# A notice whose holder is written with the sign spelling (U+00A9), wide-encoded
# inside a payload: 0xA9 arrives NUL-padded inside an otherwise printable
# NUL-padded run, so it is admitted and normalised, where the bare Latin-1 byte
# in the NARROW harvest deliberately is not. The sign is built from the byte
# constant rather than written as a character, like every other fixture fragment
# here, so this file carries no notice of its own.
FIXTURE_WIDE_COPYRIGHT_SIGN_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=106))
    + (COPYRIGHT_SIGN_CHAR + " 20" + "19 Some Upstream Author\n").encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=107))
)
# This repository's own renders are mostly QUIET, and a quiet 16-bit PCM sample
# is a low byte beside a NUL high byte — byte-for-byte the shape a UTF-16-LE
# string has. That makes a quiet render, not a full-scale one, the real
# false-positive hazard for this layer, and `foreign-license-text` cannot be
# exempted: a finding on one of this repository's 264 renders would be
# unanswerable. Kept as a positive control with real PCM data.
FIXTURE_QUIET_PCM_WAV = _wav_payload(quiet=True)
# The residual this increment declares rather than closes: a notice carried in a
# TRANSFORMED encoding (base64 here) is not text in any stride, so no run-shaped
# harvest reaches it. Non-vacuous in both directions — it is clean today and
# fails the moment a decoding layer is added.
FIXTURE_BASE64_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=108))
    + base64.b64encode(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
    + struct.pack("<600h", *_lcg_samples(600, seed=109))
)

# Increment 9 — the NAMES a wrapper carries. Increment 8 unwrapped wrappers and
# content-scanned their members, then DECLARED the remainder: "a wrapper whose
# members carry no marker at all is covered only by the extension tripwires …
# unwrapping reads member CONTENT, and member NAMES are not themselves
# tripwired". Every must-fail fixture below audited **clean** under increment 8
# — no license text anywhere in it to find, and the outer `.dat`/`.bin` name
# evades both extension sets — which is precisely the shape upstream assets
# arrive in: a wavetable payload states no copyright, and a stripped source file
# states nothing either.
#
# Marker-free ON PURPOSE. A fixture carrying a notice would be caught by
# `foreign-license-text` and prove nothing about this rule, so each payload
# below is deterministic noise or plain code: the member NAME is the only signal
# in the file.
# NUL-interleaved high bytes: the encoding sniff refuses it (no BOM, NUL-dense,
# no wide decode that is mostly ASCII) and no six consecutive printable bytes
# exist, so the harvest is empty and `text()` is None. The member NAME is then
# the only thing in the file any rule can read — which is both the point of this
# control and the real shape of a wavetable payload. (Ordinary int16 noise fires
# the rule just as well, but an accidental printable run in it makes
# `manifest-uncorroborated` demand a citation a binary cannot carry — a
# confound, not the rule under test.)
FIXTURE_MARKER_FREE_ASSET_PAYLOAD = bytes(
    value for i in range(512) for value in (0x00, 0x80 | (i * 37) % 0x80)
)
FIXTURE_MARKER_FREE_SOURCE = (
    "float run(float x, float k) { return x - k * x * x * x; }\n"
)


def _gzip_with_name(name, payload: bytes):
    """A gzip stream whose header carries `name` in its FNAME field.

    `mtime=0` keeps the bytes deterministic. This is the shape `gzip <file>`
    produces by default, and the shape 15 of this repository's own evidence
    traces are in — so the positive control below is this repository's real
    data, not a hypothetical.
    """
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", filename=name, mtime=0) as handle:
        handle.write(payload)
    return buf.getvalue()


FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME = _zip_payload(
    (("wavetables/Bank Sine.wt", FIXTURE_MARKER_FREE_ASSET_PAYLOAD),)
)
FIXTURE_TAR_GZ_WITH_SOURCE_MEMBER_NAME = _tar_gz_payload(
    (("vendor/Reverb1.cpp", FIXTURE_MARKER_FREE_SOURCE),)
)
FIXTURE_GZIP_WITH_ASSET_FNAME = _gzip_with_name(
    "Bank Sine.wt", FIXTURE_MARKER_FREE_ASSET_PAYLOAD
)
FIXTURE_GZIPPED_ZIP_WITH_ASSET_MEMBER = gzip.compress(
    FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME
)
# The masking shape `member_name_signals` splits for: the offending name is the
# OUTER member, and what it wraps is innocuous. Judging only the last component
# of the joined label would read this as a `.json`.
FIXTURE_ZIP_WITH_WRAPPED_ASSET_MEMBER = _zip_payload(
    (("Bank Sine.wt", _gzip_with_name("meta.json", b'{"frames": 16}')),)
)
# Positive controls — this repository's own wrapper shapes, which must stay
# clean. `wrapper-member-name` cannot be exempted, so a false positive here
# would be answered by switching the rule off. Both are measured shapes: of the
# 18 tracked `*.json.gz`/`*.hex.gz` traces, 15 carry an FNAME (9 `.json`,
# 6 `.hex`; the other 3 carry none), and the `.npz` tap fixture is a zip of 11
# `.npy` members — 26 real member names, 0 hits, re-derived by
# `test_real_tree_member_names_are_read_and_none_offend` on every run.
FIXTURE_OWN_GZIPPED_TRACE_WITH_FNAME = _gzip_with_name(
    "trace_seq-notes-coverage-v1.json",
    json.dumps({"fixture": "seq-notes-coverage-v1", "taps": [0.0, 0.25]}).encode("utf-8"),
)
FIXTURE_OWN_NPZ_MEMBERS = _zip_payload(
    (("gal_in.npy", "x"), ("gal_out.npy", "y"), ("__trimmed__.npy", "z"))
)


def _scoped_exemption(root: Path, occurrences, path="docs/own_copy.md"):
    item = {
        "rules": ["self-declared-quotation"],
        "occurrences": occurrences,
        "reason": "synthetic: the named occurrence copies this project's own model",
    }
    item["path" if "*" not in path else "pattern"] = path
    # Naming the occurrence puts the marker wording into the manifest itself,
    # so the skeleton exempts the manifest exactly as the real repository does.
    manifest_exemption = {
        "path": MANIFEST_REL,
        "rules": ["self-declared-quotation"],
        "reason": "synthetic: the manifest quotes the occurrence it exempts",
    }
    _patch_manifest(root, lambda d: d["exemptions"].extend([manifest_exemption, item]))


def _patch_manifest(root: Path, mutate):
    path = root / MANIFEST_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# --- discovery-layer fixtures -------------------------------------------------
#
# A by-reference entry cannot be written as a string, so these controls build
# real symlinks and a real mode-160000 index entry. The gitlink ones turn the
# control tree into a git checkout on purpose: that is the path `list_entries`
# takes on this repository, so the control exercises the actual `ls-files -s`
# mode parsing rather than a stand-in for it.
FIXTURE_SUBMODULE_REL = "libs/surge"
FIXTURE_SUBMODULE_COMMIT = "58914e59c608ed4384ba6002e44c3465c58b2e71"
FIXTURE_SUBMODULE_URL = "https://github.com/surge-synthesizer/surge.git"
FIXTURE_NESTED_REPO_REL = "libs/vendored-engine"
FIXTURE_ESCAPING_LINK_REL = "model/oracle_tables.py"
FIXTURE_ESCAPING_LINK_TARGET = "../../surge-oracle/include/sst/effects/Reverb1.h"


def _git(root: Path, *args):
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True
    )
    if proc.returncode != 0:
        raise AuditError(
            "git " + " ".join(args) + " failed: "
            + proc.stderr.decode("utf-8", "replace").strip()
        )


def _symlink(root: Path, rel, target):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def _git_submodule_entry(root: Path, rel=FIXTURE_SUBMODULE_REL,
                         commit=FIXTURE_SUBMODULE_COMMIT, url=FIXTURE_SUBMODULE_URL):
    """Record a submodule GITLINK in a synthetic tree — no clone, no network.

    `git update-index --cacheinfo 160000,…` writes exactly the index entry
    `git submodule add` would, so the audit sees a real mode-160000 row.
    """
    _git(root, "init", "-q")
    # -f: a host-level core.excludesFile must not silently drop skeleton files
    # (an untracked file is invisible to `ls-files`, which would change what
    # the control is actually testing).
    _git(root, "add", "-A", "-f")
    if url:
        _write(root, ".gitmodules", f'[submodule "{rel}"]\n\tpath = {rel}\n\turl = {url}\n')
        _git(root, "add", "-f", ".gitmodules")
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{commit},{rel}")


def _nested_repo(root: Path, rel=FIXTURE_NESTED_REPO_REL):
    """A nested repository checkout in a NON-git tree (the tarball shape)."""
    _write(root, f"{rel}/.git/config", "[core]\n\tbare = false\n")
    _write(root, f"{rel}/dsp/Reverb1.h", "float run(float x) { return x; }\n")


def _submodule_row(commit=FIXTURE_SUBMODULE_COMMIT, rel=FIXTURE_SUBMODULE_REL):
    return {
        "path": rel,
        "class": "external-reference",
        "content": "synthetic: the pinned upstream engine, referenced as a submodule",
        "upstream": FIXTURE_SUBMODULE_URL,
        "pinned_commit": commit,
        "upstream_license": "GPL-3.0-or-later",
        "decision_record": "0001",
    }


def _controls():
    """{rule: (description, mutator)} — one deliberate violation per rule."""

    def add_second_record(root, indexed):
        _write(
            root,
            f"{RECORD_DIR_REL}/0002-second.md",
            "# 0002: Second (synthetic)\n\n- **Status**: proposed\n"
            "- **Date**: 2026-01-02\n",
        )
        if indexed:
            path = root / INDEX_REL
            path.write_text(
                path.read_text(encoding="utf-8")
                + "| [0002](0002-second.md) | Second (synthetic) | proposed | 2026-01-02 |\n",
                encoding="utf-8",
            )

    controls = {
        "foreign-license-text": (
            "an unattributed file carrying a foreign license body",
            lambda root: _write(root, "model/pasted_helper.py", FIXTURE_GPL_BODY),
        ),
        "upstream-asset-extension": (
            "an undeclared upstream asset payload",
            lambda root: _write(root, "assets/Bank Sine.wt", b"\x00\x01wt payload"),
        ),
        "foreign-source-language": (
            "an undeclared foreign-language source file",
            lambda root: _write(
                root, "src/copied_filter.cpp", "float run(float x) { return x; }\n"
            ),
        ),
        "wrapper-member-name": (
            "an archive renamed '.dat' carrying an upstream asset member name",
            lambda root: _write(
                root, PAYLOAD_BUNDLE_REL, FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME
            ),
        ),
        "self-declared-quotation": (
            "a file admitting quotation with no provenance row",
            lambda root: _write(root, "model/undeclared_table.py", FIXTURE_TRANSCRIBED),
        ),
        "submodule-reference": (
            "a committed submodule gitlink pinning the upstream engine",
            _git_submodule_entry,
        ),
        "external-symlink-target": (
            "a tracked symlink whose target leaves the audited tree",
            lambda root: _symlink(
                root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET
            ),
        ),
        "dangling-record-citation": (
            "a citation of a decision record that does not exist",
            lambda root: _write(root, "docs/claim.md", FIXTURE_RECORD_CITATION),
        ),
        "unindexed-record-citation": (
            "a citation of a record missing from the index",
            lambda root: (
                add_second_record(root, indexed=False),
                _write(root, "docs/claim2.md", "See DR-0002 for the decision.\n"),
            ),
        ),
        "index-missing-row": (
            "a decision record on disk with no index row",
            lambda root: add_second_record(root, indexed=False),
        ),
        "index-unknown-record": (
            "an index row with no record file",
            lambda root: _write(
                root,
                INDEX_REL,
                SKELETON_INDEX
                + "| [0002](0002-ghost.md) | Ghost | proposed | 2026-01-02 |\n",
            ),
        ),
        "index-duplicate-row": (
            "the same record listed twice in the index",
            lambda root: _write(
                root,
                INDEX_REL,
                SKELETON_INDEX
                + "| [0001](0001-example.md) | Example | ratified | 2026-01-01 |\n",
            ),
        ),
        "index-status-mismatch": (
            "an index status keyword that no longer matches the record",
            lambda root: _write(
                root, INDEX_REL, SKELETON_INDEX.replace("| ratified |", "| PROPOSED |")
            ),
        ),
        "index-date-mismatch": (
            "an index date that no longer matches the record",
            lambda root: _write(
                root, INDEX_REL, SKELETON_INDEX.replace("2026-01-01 |", "2026-02-02 |")
            ),
        ),
        "index-number-gap": (
            "a gap in the decision-record numbering (a deleted record)",
            lambda root: (
                _write(
                    root,
                    f"{RECORD_DIR_REL}/0003-third.md",
                    "# 0003: Third (synthetic)\n\n- **Status**: proposed\n"
                    "- **Date**: 2026-01-03\n",
                ),
                _write(
                    root,
                    INDEX_REL,
                    SKELETON_INDEX
                    + "| [0003](0003-third.md) | Third | proposed | 2026-01-03 |\n",
                ),
            ),
        ),
        "record-status-unrecognized": (
            "a record whose status keyword is outside the vocabulary",
            lambda root: _write(
                root,
                f"{RECORD_DIR_REL}/0001-example.md",
                SKELETON_RECORD.replace("ratified", "maybe-someday"),
            ),
        ),
        "record-header-missing": (
            "a record with no parseable Status/Date header",
            lambda root: _write(
                root, f"{RECORD_DIR_REL}/0001-example.md", "# 0001: no header\n"
            ),
        ),
        "manifest-missing": (
            "a missing provenance manifest",
            lambda root: (root / MANIFEST_REL).unlink(),
        ),
        "manifest-schema": (
            "a manifest with an unknown schema_version",
            lambda root: _patch_manifest(root, lambda d: d.update(schema_version=99)),
        ),
        "manifest-field-missing": (
            "a provenance row missing required provenance fields",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].pop("upstream_license")
            ),
        ),
        "manifest-unknown-class": (
            "a provenance row with an unknown class",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"class": "vibes"})
            ),
        ),
        "manifest-stale-path": (
            "a provenance row whose file is gone",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"path": "model/deleted.py"})
            ),
        ),
        "manifest-bad-pattern": (
            "a blanket provenance pattern",
            lambda root: _patch_manifest(
                root,
                lambda d: d["entries"].append(
                    {
                        "pattern": "model/**",
                        "class": "quoted-constants",
                        "content": "everything",
                        "upstream": "x",
                        "upstream_license": "GPL-3.0-or-later",
                        "decision_record": "0001",
                    }
                ),
            ),
        ),
        "manifest-missing-record": (
            "a provenance row citing a nonexistent decision record",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"decision_record": "0099"})
            ),
        ),
        "manifest-unindexed-record": (
            "a provenance row citing an unindexed decision record",
            lambda root: (
                add_second_record(root, indexed=False),
                _patch_manifest(
                    root, lambda d: d["entries"][0].update({"decision_record": "0002"})
                ),
            ),
        ),
        "manifest-uncorroborated": (
            "a provenance row the file itself does not corroborate",
            lambda root: _write(
                root, "model/carrier.py", "TABLE = [1, 2, 3]  # no provenance stated\n"
            ),
        ),
        "exemption-field-missing": (
            "an exemption with no reason",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {"path": "docs/plain.md", "rules": ["self-declared-quotation"]}
                ),
            ),
        ),
        "exemption-non-exemptible-rule": (
            "an exemption of a non-exemptible rule",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "path": "docs/plain.md",
                        "rules": ["foreign-license-text"],
                        "reason": "trying to wave away a GPL header",
                    }
                ),
            ),
        ),
        "exemption-stale": (
            "an exemption matching no file",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "path": "docs/gone.md",
                        "rules": ["self-declared-quotation"],
                        "reason": "stale",
                    }
                ),
            ),
        ),
        "exemption-bad-pattern": (
            "a blanket exemption pattern",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "pattern": "docs/**",
                        "rules": ["self-declared-quotation"],
                        "reason": "blanket",
                    }
                ),
            ),
        ),
        "scope-exclusion-stale": (
            "a scope exclusion that excludes nothing",
            lambda root: _patch_manifest(
                root,
                lambda d: d["scope_exclusions"].append(
                    {"prefix": "vendor-nothing/", "reason": "stale"}
                ),
            ),
        ),
        "scan-underflow": (
            "a scan that saw fewer files than the declared floor",
            lambda root: _patch_manifest(root, lambda d: d.update(scan_floor=10_000)),
        ),
    }
    return controls


def _scoped_exemption_controls():
    """[(label, expected rule or None, description, mutator)].

    The occurrence-scoped exemption is a weakening of the one exemptible rule,
    so it gets its own controls: the case it exists for must pass (a positive
    control — otherwise it is dead), and each way it could launder real
    carriage must still fail.
    """
    own = FIXTURE_OWN_COPY_DOC
    occ = [FIXTURE_OWN_COPY_OCCURRENCE]
    return [
        (
            "scoped-exemption/own-copy-passes",
            None,
            "a file whose only quotation marker is the named own-model occurrence",
            lambda root: (_write(root, "docs/own_copy.md", own), _scoped_exemption(root, occ)),
        ),
        (
            "scoped-exemption/foreign-copy-still-fails",
            "self-declared-quotation",
            "the same exempted file plus a foreign 'copied verbatim' line",
            lambda root: (
                _write(root, "docs/own_copy.md", own + FIXTURE_FOREIGN_COPY_LINE),
                _scoped_exemption(root, occ),
            ),
        ),
        (
            "scoped-exemption/other-marker-still-fails",
            "self-declared-quotation",
            "the same exempted file plus a foreign 'transcribed from' table",
            lambda root: (
                _write(root, "docs/own_copy.md", own + FIXTURE_TRANSCRIBED),
                _scoped_exemption(root, occ),
            ),
        ),
        (
            "scoped-exemption/occurrence-gone",
            "exemption-stale",
            "a named occurrence that no longer appears in the file",
            lambda root: (
                _write(root, "docs/own_copy.md", own),
                _scoped_exemption(root, occ + ["a sentence that is not there"]),
            ),
        ),
        (
            "scoped-exemption/occurrence-without-marker",
            "exemption-stale",
            "a named occurrence that contains no quotation marker",
            lambda root: (
                _write(root, "docs/own_copy.md", own),
                _scoped_exemption(root, occ + ["instantiates the shared"]),
            ),
        ),
        (
            "scoped-exemption/on-a-pattern",
            "exemption-bad-pattern",
            "occurrences attached to a glob instead of one exact path",
            lambda root: (
                _write(root, "docs/own_copy.md", own),
                _scoped_exemption(root, occ, path="docs/*.md"),
            ),
        ),
    ]


MASKED_REL = "model/pasted_below_our_header.py"
OWN_ONLY_REL = "model/own_header_only.py"


def _masking_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    `foreign-license-text` cannot be exempted, so the only way to disarm it is
    to make it stop firing. These controls pin the two ways that happened —
    reading only a file's FIRST notice, and judging a notice's holder from a
    proximity window rather than from the notice itself — plus the positive
    cases that keep the fix from degenerating into "flag our own headers too".
    """
    below = FIXTURE_OWN_COPYRIGHT + FIXTURE_FILLER + FIXTURE_FOREIGN_COPYRIGHT_LINE
    adjacent = FIXTURE_OWN_PROJECT_LINE + FIXTURE_FOREIGN_COPYRIGHT_LINE
    spdx_below = FIXTURE_OWN_SPDX_TAG + FIXTURE_FILLER + FIXTURE_FOREIGN_SPDX_TAG
    return [
        (
            "masking/foreign-copyright-under-our-own",
            "foreign-license-text",
            MASKED_REL,
            "a pasted foreign copyright line below our own copyright header",
            lambda root: _write(root, MASKED_REL, below),
        ),
        (
            "masking/foreign-copyright-beside-a-project-mention",
            "foreign-license-text",
            MASKED_REL,
            "a foreign copyright line one line under a 'gf180-surge' mention",
            lambda root: _write(root, MASKED_REL, adjacent),
        ),
        (
            "masking/foreign-spdx-under-our-own",
            "foreign-license-text",
            MASKED_REL,
            "a pasted foreign SPDX tag below our own Apache tag",
            lambda root: _write(root, MASKED_REL, spdx_below),
        ),
        (
            "masking/our-own-copyright-alone-passes",
            None,
            None,
            "a file carrying only our own copyright header",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-spdx-alone-passes",
            None,
            None,
            "a file carrying only our own Apache SPDX tag",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_SPDX_TAG + FIXTURE_FILLER
            ),
        ),
        # --- increment 3: the same masking inside the notice itself ---------
        (
            "masking/foreign-holder-with-our-name-in-a-parenthetical",
            "foreign-license-text",
            MASKED_REL,
            "a foreign copyright line that names this project in a parenthetical",
            lambda root: _write(
                root, MASKED_REL, FIXTURE_FOREIGN_COPYRIGHT_PARENTHETICAL
            ),
        ),
        (
            "masking/foreign-holder-with-our-name-after-a-dash",
            "foreign-license-text",
            MASKED_REL,
            "a foreign copyright line that names this project after a spaced hyphen",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_COPYRIGHT_AFTER_DASH),
        ),
        (
            "masking/compound-spdx-behind-our-own-operand",
            "foreign-license-text",
            MASKED_REL,
            "an SPDX expression whose leading operand is our own licence",
            lambda root: _write(root, MASKED_REL, FIXTURE_COMPOUND_SPDX_OWN_FIRST),
        ),
        (
            "masking/license-body-wrapped-across-a-comment-leader",
            "foreign-license-text",
            MASKED_REL,
            "an FSF license body wrapped mid-phrase across a '#' comment leader",
            lambda root: _write(root, MASKED_REL, FIXTURE_WRAPPED_FSF_BODY),
        ),
        (
            "masking/license-title-wrapped-across-a-comment-leader",
            "foreign-license-text",
            MASKED_REL,
            "a GPL license title wrapped mid-phrase across a '*' comment leader",
            lambda root: _write(root, MASKED_REL, FIXTURE_WRAPPED_GPL_TITLE),
        ),
        (
            "masking/our-own-copyright-with-an-aside-passes",
            None,
            None,
            "our own copyright line trailed by a parenthetical aside",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_WITH_ASIDE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-authors-line-passes",
            None,
            None,
            "our own copyright line spelled 'The gf180-surge Authors'",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_AUTHORS + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-copyright-after-a-dash-passes",
            None,
            None,
            "our own copyright line whose holder follows a spaced hyphen",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_AFTER_DASH + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-spdx-quoted-in-prose-passes",
            None,
            None,
            "our own SPDX tag quoted mid-sentence, with prose after the operand",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_SPDX_IN_PROSE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/leaderless-prose-wrap-stays-out-of-scope",
            None,
            None,
            "a declared boundary: a license NAME wrapped in leaderless prose",
            lambda root: _write(
                root, "docs/mentions.md", FIXTURE_PROSE_WRAP_LICENSE_NAME
            ),
        ),
        # --- increment 4: delimiter-led holder fields, SPDX operands past the
        # --- expression, yearless notices, wrapped holder lists -------------
        (
            "masking/foreign-holder-behind-a-bracketed-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder behind a bracketed mention of this project",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_BEHIND_BRACKETS),
        ),
        (
            "masking/foreign-holder-behind-a-parenthesised-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder behind a parenthesised mention of this project",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_BEHIND_PARENS),
        ),
        (
            "masking/foreign-holder-after-a-semicolon-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder in a notice whose year is followed by '; gf180-surge …'",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_AFTER_SEMICOLON),
        ),
        (
            "masking/foreign-holder-after-an-em-dash-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder in a notice whose year is followed by '— gf180-surge …'",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_AFTER_EM_DASH),
        ),
        (
            "masking/spdx-foreign-operand-after-a-comma",
            "foreign-license-text",
            MASKED_REL,
            "an SPDX tag listing a foreign licence after a comma",
            lambda root: _write(root, MASKED_REL, FIXTURE_SPDX_FOREIGN_AFTER_COMMA),
        ),
        (
            "masking/spdx-foreign-operand-in-a-parenthetical",
            "foreign-license-text",
            MASKED_REL,
            "an SPDX tag naming a foreign licence inside a parenthetical",
            lambda root: _write(root, MASKED_REL, FIXTURE_SPDX_FOREIGN_IN_PARENTHETICAL),
        ),
        (
            "masking/yearless-foreign-copyright-notice",
            "foreign-license-text",
            MASKED_REL,
            "a pasted foreign notice that carries a holder but no year",
            lambda root: _write(root, MASKED_REL, FIXTURE_YEARLESS_FOREIGN_COPYRIGHT),
        ),
        (
            # The notice is written BELOW a filler pad on purpose. `Finding`
            # carries no line number, so the finding's `detail` snippet is its
            # only locator -- and a wrapped-holder match computed at
            # line-relative offsets quotes the right bytes only while the notice
            # sits at the top of the file. The pad makes the offsets diverge, and
            # the expected-detail substring below is what fails on a regression.
            "masking/foreign-holder-on-a-wrapped-continuation-line",
            "foreign-license-text",
            MASKED_REL,
            "a holder list wrapped onto a continuation line with no keyword",
            lambda root: _write(
                root, MASKED_REL, FIXTURE_FILLER + FIXTURE_WRAPPED_HOLDER_LIST
            ),
            "Chris Johnson / Airwindows",
        ),
        (
            "masking/our-own-notice-with-rights-reserved-passes",
            None,
            None,
            "our own notice trailed by 'All Rights Reserved.'",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_RIGHTS_RESERVED + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-notice-with-a-cross-reference-passes",
            None,
            None,
            "our own notice trailed by a sentence pointing at LICENSE",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_CROSS_REFERENCE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-notice-quoted-inside-prose-passes",
            None,
            None,
            "our own notice quoted mid-sentence, with prose after the closing quote",
            lambda root: _write(
                root, "docs/mentions.md", FIXTURE_OWN_COPYRIGHT_QUOTED_IN_PROSE
            ),
        ),
        (
            # Pins the segment walk itself: with the old fallback to the WHOLE
            # LINE, the aside's own capitalised token reads as a second holder
            # and our own notice becomes an unanswerable finding.
            "masking/our-own-dash-holder-with-an-aside-passes",
            None,
            None,
            "our own notice after a spaced hyphen, trailed by a capitalised aside",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_DASH_HOLDER_WITH_ASIDE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/ordinary-comment-under-an-own-notice-passes",
            None,
            None,
            "a capitalised comment sentence directly under our own notice",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_THEN_PROSE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/lettered-list-markers-stay-out-of-scope",
            None,
            None,
            "a declared boundary: '(c)' list markers are not yearless notices",
            lambda root: _write(root, "docs/legs.md", FIXTURE_LETTERED_LIST_MARKERS),
        ),
        # --- increment 5: the holder list continues past the next delimiter on
        # --- the SAME line --------------------------------------------------
        (
            "masking/second-holder-after-a-semicolon",
            "foreign-license-text",
            MASKED_REL,
            "a second holder after a semicolon on a notice line that names us first",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_AFTER_SEMICOLON),
            "Some Upstream Author",
        ),
        (
            "masking/second-holder-in-a-parenthetical",
            "foreign-license-text",
            MASKED_REL,
            "an upstream holder credited in a parenthetical after our own holder",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_IN_PARENTHETICAL),
            "Chris Johnson",
        ),
        (
            "masking/second-holder-after-an-em-dash",
            "foreign-license-text",
            MASKED_REL,
            "a second holder after an em dash, our own holder standing first",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_AFTER_EM_DASH),
            "Chris Johnson",
        ),
        (
            "masking/second-holder-after-a-spaced-hyphen",
            "foreign-license-text",
            MASKED_REL,
            "a second holder after a spaced hyphen, our own holder standing first",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_AFTER_DASH),
            "Some Upstream Author",
        ),
        (
            "masking/single-name-aside-stays-out-of-scope",
            None,
            None,
            "a declared boundary: ONE capitalised token in an aside is not a holder",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_SINGLE_NAME_ASIDE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/prose-after-a-sentence-break-stays-out-of-scope",
            None,
            None,
            "a declared boundary: a name after a full stop is prose, not a holder list",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_NOTICE_THEN_SENTENCE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/copyright-prose-is-not-a-notice-passes",
            None,
            None,
            "prose ABOUT copyright, whose holder position holds 'License'/'Notice'",
            lambda root: _write(
                root, "docs/mentions.md", FIXTURE_COPYRIGHT_PROSE_NOT_A_NOTICE
            ),
        ),
        # --- increment 6: masking the DECODE layer, below every signal ------
        (
            "masking/utf16-bom-encoded-license-body",
            "foreign-license-text",
            MASKED_REL,
            "a GPL body in a UTF-16 (BOM) source file the sniff called binary",
            lambda root: _write(root, MASKED_REL, FIXTURE_UTF16_BOM_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "masking/utf16-le-bomless-encoded-license-body",
            "foreign-license-text",
            MASKED_REL,
            "the same body in BOM-less UTF-16-LE (a plain 'Unicode' editor save)",
            lambda root: _write(root, MASKED_REL, FIXTURE_UTF16LE_BOMLESS_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "masking/utf16-be-bomless-encoded-license-body",
            "foreign-license-text",
            MASKED_REL,
            "the same body in BOM-less UTF-16-BE",
            lambda root: _write(root, MASKED_REL, FIXTURE_UTF16BE_BOMLESS_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "masking/stray-nul-byte-above-a-license-body",
            "foreign-license-text",
            MASKED_REL,
            "one stray NUL byte in the head of an otherwise ASCII GPL-headed file",
            lambda root: _write(root, MASKED_REL, FIXTURE_STRAY_NUL_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
    ]


PAYLOAD_WRAPPED_REL = "model/pasted_helper.py.gz"
PAYLOAD_RENDER_REL = "fixtures/audio/render.wav"
PAYLOAD_DUMP_REL = "reports/artifacts/ref-hot.f32"
PAYLOAD_BUNDLE_REL = "compiler/golden/bundle.dat"


def _payload_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    Increment 8 — the PAYLOAD layer. Increment 6 made the decode layer honest
    about ENCODINGS; a payload it still refused reached no content rule, and
    `files_not_content_scanned` counted 335 such files on this tree. Every
    must-fail case below audited **clean** before this increment while
    `--negative-control` reported all 29 rules and all 41 masking controls
    behaving — a gzipped source file, a zip/tar renamed `.dat`, a WAV copyright
    chunk, a notice spliced into a float dump.

    Increment 10 then inverted this increment's own declared residual, on the
    same fixture bytes: a notice re-saved in a WIDE encoding and spliced into the
    same payloads went past the non-exemptible rule just as the ASCII one had,
    and a "Unicode" save is an ordinary editor default rather than an exotic
    carriage.

    The positive controls carry at least as much weight. `foreign-license-text`
    cannot be exempted, so a false positive on this repository's own 264
    renders, 22 float dumps, 8 tensors or 18 gzipped traces would be
    unanswerable — the rule would be switched off rather than answered. Hence a
    real PCM render, a float dump, an `.npy`-shaped tensor and an own gzipped
    JSON trace must all stay clean; so must a QUIET render, which is the shape
    increment 10 had to be measured against (a quiet 16-bit sample is a low byte
    beside a NUL high byte — byte-for-byte what a UTF-16-LE string looks like);
    and a base64-carried notice pins the residual limit increment 10 declares
    rather than closes.
    """
    return [
        (
            "payload/gzipped-source-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_WRAPPED_REL,
            "a gzipped source file whose stripped extension matches no tripwire",
            lambda root: _write(root, PAYLOAD_WRAPPED_REL, FIXTURE_GZIPPED_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/xz-compressed-source-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_WRAPPED_REL,
            "the same body in an xz stream (the wrapper is found by magic, not name)",
            lambda root: _write(root, PAYLOAD_WRAPPED_REL, FIXTURE_XZ_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/bzip2-compressed-source-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_WRAPPED_REL,
            "the same body in a bzip2 stream",
            lambda root: _write(root, PAYLOAD_WRAPPED_REL, FIXTURE_BZIP2_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/zip-member-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a zip renamed '.dat' — the archive extension tripwire evaded outright",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_ZIP_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/tar-gz-member-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a tar inside a gzip inside a '.dat' name — two wrappers deep",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_TAR_GZ_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/zip-inside-a-gzip-stream",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a zip inside a gzip — the inner layer is compressed, not ASCII",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_GZIPPED_ZIP_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/gzipped-member-inside-a-zip",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a gzipped member inside a zip — the other recursion site",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_ZIP_WITH_GZIPPED_MEMBER),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/npz-member-with-a-license-body",
            "foreign-license-text",
            "reports/fixtures/taps.npz",
            "a notice riding along in an '.npz' tensor archive (a zip)",
            lambda root: _write(
                root, "reports/fixtures/taps.npz", FIXTURE_NPZ_WITH_NOTICE
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wav-copyright-chunk",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a render whose RIFF LIST/INFO 'ICOP' chunk states an upstream holder",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WAV_WITH_COPYRIGHT_CHUNK
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/notice-spliced-into-a-float-dump",
            "foreign-license-text",
            PAYLOAD_DUMP_REL,
            "a GPL body spliced into the middle of a raw float32 dump",
            lambda root: _write(root, PAYLOAD_DUMP_REL, FIXTURE_FLOAT_DUMP_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/notice-embedded-in-an-opaque-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "increment 6's declared limit, now closed: an ASCII notice in binary data",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_NOTICE_IN_AN_OPAQUE_PAYLOAD
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/copyright-sign-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a notice written with the © sign, which ends the printable run",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_COPYRIGHT_SIGN_IN_A_PAYLOAD
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/pcm-render-stays-clean",
            None,
            None,
            "a real 16-bit PCM render with no metadata chunk",
            lambda root: _write(root, PAYLOAD_RENDER_REL, FIXTURE_PLAIN_PCM_WAV),
        ),
        (
            "payload/float-dump-stays-clean",
            None,
            None,
            "a raw float32 dump of this repository's own shape",
            lambda root: _write(root, PAYLOAD_DUMP_REL, FIXTURE_PLAIN_FLOAT_DUMP),
        ),
        (
            "payload/tensor-payload-stays-clean",
            None,
            None,
            "an '.npy'-shaped tensor payload (ASCII header over float data)",
            lambda root: _write(root, "reports/traces/click-dry.npy", FIXTURE_TENSOR_PAYLOAD),
        ),
        (
            "payload/our-own-gzipped-trace-stays-clean",
            None,
            None,
            "this repository's own evidence shape: a gzipped JSON trace, now inflated",
            lambda root: _write(
                root, "reports/artifacts/trace.json.gz", FIXTURE_OWN_GZIPPED_TRACE
            ),
        ),
        # Increment 10 — the inversion of increment 8's own declared residual,
        # on the same fixture bytes, plus the other byte orders, strides and
        # carriages that declaration also covered.
        (
            "payload/wide-encoded-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "increment 8's declared limit, now closed: a UTF-16-LE notice in a payload",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-encoded-notice-in-the-other-byte-order",
            "foreign-license-text",
            PAYLOAD_DUMP_REL,
            "the same notice in UTF-16-BE, spliced into a float dump",
            lambda root: _write(
                root, PAYLOAD_DUMP_REL, FIXTURE_UTF16BE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-notice-spliced-at-an-odd-offset",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "the same notice at an ODD offset: its data bytes sit on the other "
            "side of their padding",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_NOTICE_AT_AN_ODD_OFFSET
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-holder-line-at-an-odd-offset",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "the same, where the run's FIRST character is the whole prefilter: a "
            "bare holder line read one unit late matches nothing",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_HOLDER_LINE_AT_AN_ODD_OFFSET
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/utf32-le-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a 32-bit code unit: three padding bytes per character, not one",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_UTF32LE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/utf32-be-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "the same, big-endian — the other half of the second halving step",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_UTF32BE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/bom-led-wide-notice-inside-a-real-render",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a BOM-led UTF-16 notice inside a real PCM render's data chunk",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WAV_WITH_WIDE_NOTICE
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-notice-inside-a-wrapper-member",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a gzip whose member is an opaque payload with a UTF-16 notice in it",
            lambda root: _write(
                root, PAYLOAD_BUNDLE_REL, FIXTURE_GZIPPED_WIDE_NOTICE_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-encoded-copyright-sign-notice",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a wide-encoded notice whose holder is written with the sign spelling",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_COPYRIGHT_SIGN_IN_A_PAYLOAD
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/quiet-pcm-render-stays-clean",
            None,
            None,
            (
                "the real false-positive hazard: a QUIET 16-bit PCM render, whose "
                "every sample is a low byte beside a NUL — a UTF-16-LE string's "
                "own byte shape"
            ),
            lambda root: _write(root, PAYLOAD_RENDER_REL, FIXTURE_QUIET_PCM_WAV),
        ),
        (
            "payload/base64-encoded-notice-stays-out-of-scope",
            None,
            None,
            (
                "a declared limit: a notice carried in a TRANSFORMED encoding "
                "(base64) is not text at any stride, so no run harvest reaches it"
            ),
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_BASE64_NOTICE_IN_A_PAYLOAD
            ),
        ),
    ]


PAYLOAD_ASSET_BUNDLE_REL = "compiler/golden/wavetables.dat"


def _asset_bundle_row(covers=None):
    """A provenance row for the synthetic wavetable bundle, plus the manifest's
    own `self-declared-quotation` exemption.

    The row's class is `vendored-copy`, so the manifest itself then carries the
    quotation vocabulary beside an upstream citation — exactly as the real
    `decision-records/provenance.json` does, and exempted the same way (that
    file's own exemption, not a special case in the tool). Without it the
    control would fail on a confound rather than on the rule under test.
    """
    row = {
        "path": PAYLOAD_ASSET_BUNDLE_REL,
        "class": "vendored-copy",
        "content": "synthetic: an archive of upstream wavetable assets",
        "upstream": "surge-synthesizer/surge",
        "pinned_commit": FIXTURE_SUBMODULE_COMMIT,
        "upstream_license": "GPL-3.0-or-later",
        "decision_record": "0001",
    }
    if covers is not None:
        row["covers"] = list(covers)
    exemption = {
        "path": MANIFEST_REL,
        "rules": ["self-declared-quotation"],
        "reason": "synthetic: the manifest's own rows use the quotation vocabulary",
    }

    def mutate(root):
        _write(root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME)
        _patch_manifest(
            root,
            lambda d: (d["entries"].append(row), d["exemptions"].append(exemption)),
        )

    return mutate


def _wrapper_name_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    Increment 9 — the NAMES inside a wrapper, which increment 8 declared rather
    than closed. Every must-fail case below audited **clean** on increment 8's
    tool while `--negative-control` reported all 31 rules, all 40 masking
    controls, all 11 discovery controls and all 17 payload controls behaving:
    the files carry no license text to find, and their outer name is in neither
    extension set.

    The positive controls carry at least as much weight as on every earlier
    increment. `wrapper-member-name` is non-exemptible, so a false positive on
    this repository's own 19 wrappers — 15 gzipped traces that really do carry
    an FNAME, and the `.npz` tap fixture whose 11 members are all `.npy` — could
    only be answered by switching the rule off. Both were measured over the
    real tree before this was written: 0 hits across its 26 member names
    (9 `.json`, 6 `.hex`, 11 `.npy`; 3 gzip streams carry no FNAME at all).
    """
    return [
        (
            "wrapper/zip-member-named-as-an-upstream-asset",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a zip renamed '.dat' whose member is a '.wt' wavetable with no marker",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/tar-member-named-as-foreign-source",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a tar.gz renamed '.dat' carrying a stripped '.cpp' — no notice in it",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_TAR_GZ_WITH_SOURCE_MEMBER_NAME
            ),
            "Reverb1.cpp",
        ),
        (
            "wrapper/gzip-fname-header-names-an-asset",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a gzip whose FNAME header is the only name it has ('Bank Sine.wt')",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_GZIP_WITH_ASSET_FNAME
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/asset-member-inside-a-gzipped-zip",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "the recursion site: a zip inside a gzip, '.wt' member two deep",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_GZIPPED_ZIP_WITH_ASSET_MEMBER
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/outer-member-name-not-masked-by-the-inner-one",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a '.wt' member that is itself a gzip of 'meta.json' — the outer "
            "name must still be judged",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_ZIP_WITH_WRAPPED_ASSET_MEMBER
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/own-gzipped-trace-with-an-fname-stays-clean",
            None,
            None,
            "this repository's real shape: a gzipped JSON trace whose gzip "
            "header carries its original '.json' filename",
            lambda root: _write(
                root,
                "reports/artifacts/trace.json.gz",
                FIXTURE_OWN_GZIPPED_TRACE_WITH_FNAME,
            ),
        ),
        (
            "wrapper/own-npz-members-stay-clean",
            None,
            None,
            "an '.npz' tap fixture: a zip of this project's own '.npy' members",
            lambda root: _write(
                root, "reports/fixtures/taps.npz", FIXTURE_OWN_NPZ_MEMBERS
            ),
        ),
        (
            "wrapper/asset-member-answered-by-a-row-passes",
            None,
            None,
            "the rule is ANSWERABLE: a row citing its record and declaring "
            "'covers' clears the same bundle",
            _asset_bundle_row(covers=["wrapper-member-name"]),
        ),
        (
            "wrapper/a-row-without-covers-does-not-clear-it",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "and coverage is not implicit: the SAME row without 'covers' still "
            "fails, so a row filed for another reason cannot absorb a member "
            "name added later",
            _asset_bundle_row(),
            "Bank Sine.wt",
        ),
    ]


def _discovery_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    Increment 7 — the DISCOVERY layer, below the decode layer increment 6
    closed. Both negative cases below audited **clean** while
    `--negative-control` reported all 29 earlier rules firing: a by-reference
    entry has no bytes of its own, so `open()` failed and the file was counted
    as an undecodable payload among the renders.

    The positive controls matter as much: a repository that symlinks
    `CLAUDE.md -> AGENTS.md` (this one does) must not acquire a finding on a
    non-exemptible rule, or the rule would be switched off rather than answered.
    """
    return [
        (
            "discovery/committed-submodule-gitlink",
            "submodule-reference",
            FIXTURE_SUBMODULE_REL,
            "a committed mode-160000 gitlink pinning the upstream GPL engine",
            _git_submodule_entry,
            "surge-synthesizer/surge",
        ),
        (
            "discovery/submodule-gitlink-answered-by-a-row",
            None,
            None,
            "the same gitlink, declared by a provenance row at its exact commit",
            lambda root: (
                _git_submodule_entry(root),
                _patch_manifest(root, lambda d: d["entries"].append(_submodule_row())),
            ),
        ),
        (
            "discovery/submodule-row-naming-the-wrong-commit",
            "manifest-uncorroborated",
            FIXTURE_SUBMODULE_REL,
            "a submodule row whose pinned_commit is not the committed gitlink",
            lambda root: (
                _git_submodule_entry(root),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(
                        _submodule_row(commit="0" * 40)
                    ),
                ),
            ),
        ),
        (
            "discovery/nested-repository-in-a-non-git-tree",
            "submodule-reference",
            FIXTURE_NESTED_REPO_REL,
            "a nested repository checkout in a tree that is not itself a checkout",
            _nested_repo,
        ),
        (
            "discovery/symlink-to-an-absent-external-target",
            "external-symlink-target",
            FIXTURE_ESCAPING_LINK_REL,
            "a symlink into an external oracle tree that is not checked out here",
            lambda root: _symlink(
                root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET
            ),
            "escapes the audited tree",
        ),
        (
            "discovery/symlink-with-an-absolute-target",
            "external-symlink-target",
            FIXTURE_ESCAPING_LINK_REL,
            "a symlink whose target is an absolute path on the author's machine",
            lambda root: _symlink(
                root, FIXTURE_ESCAPING_LINK_REL, "/opt/surge/include/Reverb1.h"
            ),
            "absolute target",
        ),
        (
            # The structural rule is not the only one that must fire here: a
            # link that DOES resolve is read by every content rule, and a fix
            # that short-circuited on the symlink kind would silently drop them.
            "discovery/resolvable-escaping-symlink-is-still-content-scanned",
            "foreign-license-text",
            FIXTURE_ESCAPING_LINK_REL,
            "an escaping symlink that resolves, whose target carries a GPL body",
            lambda root: (
                _write(root.parent / f"{root.name}-oracle", "Reverb1.h", FIXTURE_GPL_BODY),
                _symlink(
                    root,
                    FIXTURE_ESCAPING_LINK_REL,
                    f"../../{root.name}-oracle/Reverb1.h",
                ),
            ),
        ),
        (
            "discovery/symlink-into-a-declared-scope-exclusion",
            "external-symlink-target",
            FIXTURE_ESCAPING_LINK_REL,
            "a symlink from product space into a declared, unaudited hole",
            lambda root: (
                _write(root, ".loom/vendored_table.py", "TABLE = [7, 8, 9]\n"),
                _patch_manifest(
                    root,
                    lambda d: d["scope_exclusions"].append(
                        {"prefix": ".loom/", "reason": "synthetic declared hole"}
                    ),
                ),
                _symlink(root, FIXTURE_ESCAPING_LINK_REL, "../.loom/vendored_table.py"),
            ),
            "scope exclusion",
        ),
        (
            "discovery/in-repo-symlink-to-a-regular-file-passes",
            None,
            None,
            "this repository's own shape: a symlink to an audited in-tree file",
            lambda root: _symlink(root, "CLAUDE.md", "docs/plain.md"),
        ),
        (
            "discovery/in-repo-symlink-to-a-directory-passes",
            None,
            None,
            "a symlink to an in-tree directory, whose files are audited at their own paths",
            lambda root: _symlink(root, "docs/model", "../model"),
        ),
        (
            "discovery/escaping-symlink-answered-by-a-row-passes",
            None,
            None,
            "an escaping symlink declared by a provenance row citing its record",
            lambda root: (
                _symlink(
                    root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET
                ),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(
                        {
                            "path": FIXTURE_ESCAPING_LINK_REL,
                            "class": "external-reference",
                            "content": "synthetic: a link into the external oracle tree",
                            "upstream": "surge-synthesizer/surge",
                            "pinned_commit": FIXTURE_SUBMODULE_COMMIT,
                            "upstream_license": "GPL-3.0-or-later",
                            "decision_record": "0001",
                        }
                    ),
                ),
            ),
        ),
    ]


def _run_case_controls(tmp_root: Path, prefix, cases):
    """Run (label, expected, path, description, mutate[, in_detail]) cases.

    Returns [(label, ok, detail)]. The optional sixth element `in_detail` is a
    substring the firing finding's own `detail` must contain. It exists because
    `Finding` carries no line number: the `detail` snippet is the only locator a
    human has for answering a finding, and `foreign-license-text` cannot be
    exempted -- so a control that checks only `rule`/`path` would pass on a
    finding whose evidence points at the wrong bytes.
    """
    results = []
    for index, case in enumerate(cases):
        label, expected, where, description, mutate = case[:5]
        in_detail = case[5] if len(case) > 5 else None
        case_root = Path(tmp_root) / f"{prefix}-{index}"
        case_root.mkdir()
        build_skeleton(case_root)
        try:
            mutate(case_root)
        except Exception as exc:  # a control that cannot be SET UP is a FAIL
            results.append(
                (label, False, f"{description} -> control setup failed: {exc}")
            )
            continue
        findings, _ = audit(case_root)
        found = ", ".join(sorted({f"{f.rule}@{f.path}" for f in findings})) or "nothing"
        if expected is None:
            passed = not findings
            detail = f"{description} -> " + ("audits clean" if passed else f"found {found}")
        else:
            matched = [
                f
                for f in findings
                if f.rule == expected and (where is None or f.path == where)
            ]
            passed = bool(matched)
            detail = f"{description} -> " + (
                f"{expected} fired on {where}"
                if passed
                else f"{expected} did NOT fire on {where} (found {found})"
            )
            if passed and in_detail is not None:
                quoting = [f for f in matched if in_detail in f.detail]
                passed = bool(quoting)
                if not passed:
                    detail = (
                        f"{description} -> {expected} fired on {where} but no "
                        f"finding quoted {in_detail!r} (details: "
                        + "; ".join(repr(f.detail) for f in matched)
                        + ")"
                    )
                else:
                    detail += f", quoting {in_detail!r}"
        results.append((label, passed, detail))
    return results


def run_negative_control(verbose=True):
    """Every rule must fire on a deliberate violation. Returns exit code."""
    controls = _controls()
    missing = sorted(set(RULES) - set(controls))
    results = []
    ok = True

    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean"
        clean.mkdir()
        build_skeleton(clean)
        findings, _ = audit(clean)
        clean_ok = not findings
        ok = ok and clean_ok
        results.append(
            (
                "(clean skeleton)",
                "PASS" if clean_ok else "FAIL",
                "audits clean"
                if clean_ok
                else "false alarm on a clean tree: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings),
            )
        )

        for rule in sorted(controls):
            description, mutate = controls[rule]
            case = Path(tmp) / f"case-{rule}"
            case.mkdir()
            build_skeleton(case)
            try:
                mutate(case)
            except Exception as exc:  # a control that cannot be SET UP is a FAIL
                ok = False
                results.append(
                    (rule, "FAIL", f"{description} -> control setup failed: {exc}")
                )
                continue
            findings, _ = audit(case)
            fired = [f for f in findings if f.rule == rule]
            if fired:
                results.append((rule, "PASS", f"{description} -> {fired[0].path}"))
            else:
                ok = False
                results.append(
                    (
                        rule,
                        "FAIL",
                        f"{description} -> rule did NOT fire (found: "
                        + (", ".join(sorted({f.rule for f in findings})) or "nothing")
                        + ")",
                    )
                )

        # A scoped-exemption tripwire must fire on the exempted file itself,
        # not on the manifest; a manifest rule fires on the manifest.
        scoped = [
            (
                label,
                expected,
                None
                if expected is None
                else ("docs/own_copy.md" if expected in TRIPWIRE_RULES else MANIFEST_REL),
                description,
                mutate,
            )
            for label, expected, description, mutate in _scoped_exemption_controls()
        ]
        for prefix, cases in (
            ("scoped", scoped),
            ("masking", _masking_controls()),
            ("discovery", _discovery_controls()),
            ("payload", _payload_controls()),
            ("wrapper", _wrapper_name_controls()),
        ):
            for label, passed, detail in _run_case_controls(Path(tmp), prefix, cases):
                ok = ok and passed
                results.append((label, "PASS" if passed else "FAIL", detail))

    if verbose:
        print("negative control: one deliberate violation per rule\n")
        for name, verdict, detail in results:
            print(f"  {verdict:4}  {name}")
            print(f"        {detail}")
        if missing:
            print(
                "\nFAIL: rules with no negative control (add one before merging): "
                + ", ".join(missing)
            )
        print()
        if ok and not missing:
            print(
                f"PASS: all {len(controls)} rules fired on their deliberate "
                "violation, the clean control tree produced no findings, "
                f"all {len(_scoped_exemption_controls())} occurrence-scoped "
                f"exemption controls behaved, all {len(_masking_controls())} "
                "own-attribution masking controls behaved, all "
                f"{len(_discovery_controls())} discovery-layer controls behaved, "
                f"all {len(_payload_controls())} payload-layer controls behaved, "
                f"and all {len(_wrapper_name_controls())} wrapper-member-name "
                "controls behaved."
            )
        else:
            print("FAIL: the audit's own failure detection is not intact.")
        print(CAVEAT)
    return 0 if (ok and not missing) else 2


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
    args = parser.parse_args(argv)

    if args.limits:
        print(__doc__)
        return 0
    if args.negative_control:
        return run_negative_control()

    try:
        findings, stats = audit(Path(args.root))
    except AuditError as exc:
        print(f"NOT_RUN: provenance audit could not run: {exc}")
        print(CAVEAT)
        return 2
    report(findings, stats, args.root, as_json=args.json)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
