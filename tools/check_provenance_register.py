#!/usr/bin/env python3
"""SXT-019 provenance audit — the GPL-boundary register cross-check.

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or message was changed, reordered or reflowed). This module parses
`decision-records/gpl-boundary-register.md` and reconciles that TABLE-level
inventory with the FILE-level manifest and with the decision records
themselves, in both directions.
"""

from __future__ import annotations

import re

from check_provenance_manifest import (
    _matcher,
)
from check_provenance_rules import (
    MANIFEST_REL,
)
from check_provenance_signals import (
    Finding,
)
from check_provenance_tree import (
    Tree,
)


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
