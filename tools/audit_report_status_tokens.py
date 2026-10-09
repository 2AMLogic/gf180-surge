#!/usr/bin/env python3
"""#365 -- audit committed report verdict tokens against the six-status vocabulary.

CLAUDE.md requires verification statuses to be reported as PASS, FAIL,
NOT_RUN, BLOCKED, NO_VERDICT or STALE.  This stdlib-only audit walks every
committed `reports/**/*.json`, and for the declared verdict-position keys
(`status`, `verdict`, `comparison`, `result`) requires each string value to be

  * one of the six canonical statuses (optionally followed by a free-text
    qualifier, e.g. `PASS (PENDING-FREEZE: ...)` -- counted as "qualified"), or
  * covered by the reviewed allowlist `docs/report-status-allowlist.json`,
    which maps each extra token to a canonical meaning plus a reason.

Allowlist targets: the six canonical statuses, `NON_VERDICT` (a descriptor /
control-outcome / measurement-kind label that is not itself a verdict), or
`OPEN` (what the producer meant is undecided; recorded as an open finding for
the owning leaf, NOT guessed).  Two rules protect the vocabulary: no extra
token may map to PASS, and a refusal-like token (contains REFUS) may only map
to NOT_RUN, NO_VERDICT, BLOCKED or FAIL.

WHAT THIS ESTABLISHES: vocabulary conformance of committed reports only.
It says nothing about whether any recorded result is correct, and a token
allowlisted as NON_VERDICT/OPEN is not endorsed as a verdict.  Non-string
values (ints, objects) under these keys are inventoried but not judged.
It rewrites no report and no producer tool (many are byte-frozen).

Usage: audit_report_status_tokens.py [--reports DIR] [--allowlist FILE] [--json]
Exit 0 only when the allowlist is valid and every token is canonical or
allowlisted; 1 otherwise.
"""

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = ("PASS", "FAIL", "NOT_RUN", "BLOCKED", "NO_VERDICT", "STALE")
KEYS = ("status", "verdict", "comparison", "result")
EXTRA_TARGETS = ("NON_VERDICT", "OPEN")
REFUSAL_OK_TARGETS = ("NOT_RUN", "NO_VERDICT", "BLOCKED", "FAIL")
DEFAULT_REPORTS = os.path.join(REPO, "reports")
DEFAULT_ALLOWLIST = os.path.join(REPO, "docs", "report-status-allowlist.json")
_BOUNDARY = re.compile(r"[\s(:]")


def validate_allowlist(allow):
    """Return a list of error strings (empty when the allowlist is valid)."""
    errs = []
    if not isinstance(allow, dict) or not isinstance(allow.get("keys"), dict):
        return ["allowlist must be an object with a 'keys' object"]
    for key, entries in allow["keys"].items():
        if key not in KEYS:
            errs.append(f"{key!r}: not a declared verdict-position key {KEYS}")
            continue
        if not isinstance(entries, dict):
            errs.append(f"{key}: entries must be an object")
            continue
        for tok, ent in entries.items():
            where = f"{key}.{tok!r}"
            to = ent.get("to") if isinstance(ent, dict) else None
            reason = ent.get("reason") if isinstance(ent, dict) else None
            if tok in CANONICAL:
                errs.append(f"{where}: canonical statuses are implicit; do not list")
            if to == "PASS":
                errs.append(f"{where}: an extra token may never map to PASS")
            elif to not in CANONICAL + EXTRA_TARGETS:
                errs.append(f"{where}: unknown target {to!r}")
            elif "REFUS" in tok.upper() and to not in REFUSAL_OK_TARGETS:
                errs.append(f"{where}: a refusal may only map to {REFUSAL_OK_TARGETS}")
            if not isinstance(reason, str) or not reason.strip():
                errs.append(f"{where}: missing reason")
    return errs


def _prefix_hit(value, tokens):
    """Longest token that is a prefix of value ending at a boundary."""
    best = None
    for t in tokens:
        if value.startswith(t) and (len(value) == len(t)
                                    or _BOUNDARY.match(value[len(t)])):
            if best is None or len(t) > len(best):
                best = t
    return best


def classify(key, value, allow):
    """-> (class, canonical_meaning|None, matched_token|None).

    class is one of: canonical, qualified, allowlisted, violation.
    """
    if value in CANONICAL:
        return "canonical", value, value
    entries = allow.get("keys", {}).get(key, {})
    hit = _prefix_hit(value, entries)
    chit = _prefix_hit(value, CANONICAL)
    # a longer allowlist match beats a canonical head; otherwise canonical head
    if hit is not None and (chit is None or len(hit) >= len(chit)):
        return "allowlisted", entries[hit]["to"], hit
    if chit is not None:
        return "qualified", chit, chit
    return "violation", None, None


def _walk(obj, path, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in KEYS:
                out.append((k, v, path + "." + k))
            _walk(v, path + "." + k, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk(v, f"{path}[{i}]", out)


def scan(reports_dir):
    """Yield (relpath, key, value, jsonpath) for every verdict-position key."""
    rows, unparsable = [], []
    for root, dirs, files in os.walk(reports_dir):
        dirs.sort()
        for fn in sorted(files):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, reports_dir)
            try:
                with open(p, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError) as e:
                unparsable.append((rel, str(e)))
                continue
            found = []
            _walk(doc, "", found)
            rows.extend((rel, k, v, jp) for k, v, jp in found)
    return rows, unparsable


def audit(reports_dir, allow):
    errs = validate_allowlist(allow)
    rows, unparsable = scan(reports_dir)
    inv = {}      # key -> token -> {count, class, meaning, example}
    used = set()
    nonstr = {}
    for rel, k, v, jp in rows:
        if not isinstance(v, str):
            nonstr[k] = nonstr.get(k, 0) + 1
            continue
        cls, meaning, tok = classify(k, v, allow) if not errs else \
            classify(k, v, {"keys": {}})
        if cls == "allowlisted":
            used.add((k, tok))
        # group by matched token (qualified/free-text values share a head)
        e = inv.setdefault(k, {}).setdefault(
            tok if tok is not None else v,
            {"count": 0, "class": cls, "meaning": meaning,
             "example": f"{rel}{jp}", "distinct_values": set()})
        e["count"] += 1
        e["distinct_values"].add(v)
    for d in inv.values():
        for e in d.values():
            e["distinct_values"] = len(e["distinct_values"])
    violations = [(k, t, e) for k, d in inv.items() for t, e in d.items()
                  if e["class"] == "violation"]
    unused = sorted(f"{k}.{t}" for k, ents in allow.get("keys", {}).items()
                    if isinstance(ents, dict) for t in ents
                    if (k, t) not in used)
    return {"allowlist_errors": errs, "inventory": inv, "non_string": nonstr,
            "violations": violations, "unparsable": unparsable,
            "unused_allowlist_entries": unused,
            "ok": not errs and not violations}


def render(res):
    lines = []
    for k in KEYS:
        d = res["inventory"].get(k, {})
        lines.append(f"[{k}] {len(d)} distinct token(s), "
                     f"{sum(e['count'] for e in d.values())} occurrence(s)")
        for t, e in sorted(d.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
            m = f" -> {e['meaning']}" if e["meaning"] else ""
            dv = (f" ({e['distinct_values']} distinct values)"
                  if e["distinct_values"] > 1 else "")
            lines.append(f"  {e['count']:6d}  {e['class']:<11}{m:<16} {t[:70]!r}{dv}")
    if res["non_string"]:
        lines.append(f"non-string values (not judged): {res['non_string']}")
    for p, e in res["unparsable"]:
        lines.append(f"UNPARSABLE {p}: {e}")
    for e in res["allowlist_errors"]:
        lines.append(f"ALLOWLIST ERROR: {e}")
    for k, t, e in res["violations"]:
        lines.append(f"VIOLATION {k}={t[:70]!r} (x{e['count']}, e.g. {e['example']})")
    if res["unused_allowlist_entries"]:
        lines.append("unused allowlist entries: "
                     + ", ".join(res["unused_allowlist_entries"]))
    lines.append("RESULT: " + ("PASS (vocabulary conformance only)" if res["ok"]
                               else "FAIL"))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reports", default=DEFAULT_REPORTS)
    ap.add_argument("--allowlist", default=DEFAULT_ALLOWLIST)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    with open(a.allowlist, encoding="utf-8") as fh:
        allow = json.load(fh)
    res = audit(a.reports, allow)
    if a.json:
        print(json.dumps(res, indent=2, sort_keys=True, default=list))
    else:
        print(render(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
