#!/usr/bin/env python3
"""SXT-019 provenance audit — content signals (licence, SPDX, copyright).

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or message was changed, reordered or reflowed). This module decides what a
piece of TEXT says: whether it carries a foreign licence body, a foreign SPDX
identifier, or a copyright notice naming somebody other than us. It also holds
the two exception/record types the rest of the audit raises and returns.
"""

from __future__ import annotations

import re

from check_provenance_rules import (
    RULES,
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
