#!/usr/bin/env python3
"""SXT-019 provenance audit — rule ids, classes and shared constants.

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule,
message, class or constant was changed, renamed, reordered or reflowed). This
is the base layer: it defines nothing but names, so it imports no sibling and
every other module of the audit may import it.
"""

from __future__ import annotations

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
