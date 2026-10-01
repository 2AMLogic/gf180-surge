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
       * `self-declared-quotation`     — the repo's own quotation vocabulary
                                         ("quoted as data", "QUOTED",
                                         "transcribed from", "vendored", …)
                                         co-occurring with an upstream
                                         citation                (exemptible)

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
  * Every masking path closed here was found by inspection, one increment at a
    time. That two specific paths, then five, then eight more, were closed is
    not evidence that no further path exists — only that these are pinned by
    controls that fail when, and only when, their own fix is reverted.
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
ordinary prose.

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
import json
import re
import subprocess
import sys
import tempfile
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
    "self-declared-quotation": "self-declared quotation without a provenance row",
}

TRIPWIRE_RULES = (
    "foreign-license-text",
    "upstream-asset-extension",
    "foreign-source-language",
    "self-declared-quotation",
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


# --- file discovery -----------------------------------------------------------


def list_files(root: Path):
    """Repo-relative POSIX paths of candidate files, deterministically sorted.

    Uses `git ls-files` when the tree is a git checkout (so untracked scratch
    files are not audited), and falls back to a filesystem walk otherwise
    (synthetic trees in tests and in --negative-control).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
        if names:
            return sorted(names)
    except (OSError, subprocess.CalledProcessError):
        pass

    out = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/__pycache__/" in f"/{rel}":
            continue
        out.append(rel)
    return sorted(out)


class Tree:
    """In-scope file set plus cached text reads."""

    def __init__(self, root: Path, exclusions):
        self.root = root
        self.exclusions = exclusions
        self.all_files = list_files(root)
        self.excluded = {}
        self.files = []
        for rel in self.all_files:
            hit = self._excluded_by(rel)
            if hit is None:
                self.files.append(rel)
            else:
                self.excluded.setdefault(hit, []).append(rel)
        self._text_cache = {}
        self._lower_cache = {}

    def _excluded_by(self, rel):
        for prefix in self.exclusions:
            if rel == prefix:
                return prefix
            # Path-boundary match only: an unslashed prefix like "corpus"
            # must not also match "corpus-eval/…" (PR #114 review, nit 3).
            boundary = prefix if prefix.endswith("/") else prefix + "/"
            if rel.startswith(boundary):
                return prefix
        return None

    def text(self, rel):
        """Decoded text, or None for binary/unreadable files.

        Sniffs the first block for NUL bytes before reading the rest, so a
        multi-megabyte render or trace payload is never fully decoded.
        """
        if rel in self._text_cache:
            return self._text_cache[rel]
        value = None
        try:
            with (self.root / rel).open("rb") as handle:
                head = handle.read(BINARY_SNIFF_BYTES)
                if b"\0" not in head:
                    value = (head + handle.read()).decode("utf-8", "replace")
        except OSError:
            value = None
        self._text_cache[rel] = value
        return value

    def lower(self, rel):
        """Lowercased text (cached) — the cheap prefilter for every signal."""
        if rel not in self._lower_cache:
            text = self.text(rel)
            self._lower_cache[rel] = None if text is None else text.lower()
        return self._lower_cache[rel]


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
                _extension_tripwire_rules(rel) | covers_declared
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
    text = tree.text(rel)
    if text is None:
        return []  # binary payload: nothing to read; the row is the record
    commit = str(entry.get("pinned_commit") or "").strip()
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


def tripwire_hits(tree: Tree, rel):
    """[(rule, evidence)] for content signals of third-party carriage.

    Each signal is gated behind a cheap lowercase substring prefilter; the
    regexes below only run on files that could match. The prefilter tokens
    must stay a SUPERSET of what each regex can match, or the rule silently
    stops firing — `--negative-control` is what catches that mistake.
    """
    hits = []
    suffix = _extension_suffix(rel)
    if suffix in UPSTREAM_ASSET_EXTS:
        hits.append(("upstream-asset-extension", f"extension {suffix}"))
    if suffix in FOREIGN_SOURCE_EXTS:
        hits.append(("foreign-source-language", f"extension {suffix}"))
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
        "self-declared-quotation": (
            "a file admitting quotation with no provenance row",
            lambda root: _write(root, "model/undeclared_table.py", FIXTURE_TRANSCRIBED),
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
        mutate(case_root)
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
            mutate(case)
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
        for prefix, cases in (("scoped", scoped), ("masking", _masking_controls())):
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
                "exemption controls behaved, and all "
                f"{len(_masking_controls())} own-attribution masking controls "
                "behaved."
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
