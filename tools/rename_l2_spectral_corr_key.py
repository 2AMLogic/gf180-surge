#!/usr/bin/env python3
"""Issue #165: rename the L2 filter family's spectral metric key in the
COMMITTED artifacts, from `spectral_corr` to `l2_spectral_corr`.

Why a key rename and not a re-grade
-----------------------------------
Issue #110 made one shared `spectral_corr` definition (full-scale referenced,
-100 dBFS/bin floor, Hann 4096) for every comparator that grades the 0.98
effect-slice budget. The SXT-037 / SXT-038 / SXT-039 filter legs grade a
DIFFERENT metric (native-unit `log1p(|X|)` on Q10.21 LSB) against a DIFFERENT
budget family (`l2_spectral_corr_min` = 0.999), and #165 renamed that metric
in the producing code rather than migrating it -- the reason is recorded in
`reports/spectral-corr-per-leaf-migration/EVIDENCE.md` and in the
`l2_spectral_corr` docstrings.

A rename changes NO measurement. So the committed artifacts are brought to
the new name by a name-only transformation, not by a re-render: every value
is carried across byte-for-byte, which is also why the leaf `EVIDENCE.md`
tables that quote these numbers stay correct. That every single difference
this makes to a committed L2 artifact is a rename or an added definition stamp
-- never a moved value -- is checked mechanically against the base revision by
`tools/spectral_corr_per_leaf_checks.py` leg 4 (27 artifacts, including the
gzipped SXT-037 traces).

That the new name is also what the renamed PRODUCERS emit was verified by
re-running them on the committed inputs they can still be run from (leg 5,
coverage reported separately from agreement):

  SXT-039   11/11 cases       worst 1.15e-12 relative (host float ordering)
  SXT-038    4/11 bundles     worst 4.1e-07 relative -- the committed value is
                              rounded to 6 dp by compare_lp24_model.py; the
                              other 7 bundles hold `meta.json` only and need
                              the external pinned-filter harness: NOT_RUN
  sxt-037    3/3 traces       5 of 6 instance values bit-identical, worst
                              2.4e-13 relative

Those 7 NOT_RUN bundles are recorded as NOT_RUN, never as a pass. Full
transcripts: `reports/spectral-corr-per-leaf-migration/artifacts/`.

This tool is IDEMPOTENT: a second run reports 0 changes. `--check` makes no
change and exits 1 if any declared target still carries a bare
`spectral_corr` / `spectral_corr_min` key, which is what
`tests/test_spectral_corr_single_definition.py` asserts.

Usage:
  python3 tools/rename_l2_spectral_corr_key.py [--check] [--log OUT.txt]
"""

import argparse
import glob
import gzip
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lp12"))

OLD, NEW = "spectral_corr", "l2_spectral_corr"
OLD_BUDGET, NEW_BUDGET = "spectral_corr_min", "l2_spectral_corr_min"
DEFINITION_KEY = "l2_spectral_corr_definition"

# The one definition string, taken from the producing code so the stamp can
# never drift from the function it describes.
from run_filter_leg import L2_SPECTRAL_CORR_DEFINITION  # noqa: E402


def targets():
    """Every committed artifact of the L2 filter family that carries the key.

    Enumerated explicitly (no repo-wide sweep): renaming a key outside this
    family would be a silent metric change somewhere else.
    """
    out = []
    out += sorted(glob.glob(os.path.join(
        REPO, "reports", "SXT-039", "artifacts", "budget-*.json")))
    out += sorted(glob.glob(os.path.join(
        REPO, "reports", "SXT-038", "artifacts", "compare-*.json")))
    out.append(os.path.join(REPO, "reports", "SXT-038", "artifacts",
                            "budget-summary.json"))
    out += sorted(glob.glob(os.path.join(
        REPO, "reports", "sxt-037", "artifacts", "model-trace-*.json.gz")))
    out.append(os.path.join(REPO, "reports", "sxt-037", "artifacts",
                            "f038-102", "budget-before-after.json"))
    return [p for p in out if os.path.exists(p)]


def rename_in_dict(d, log, where, stamp=True):
    """Rename OLD -> NEW in `d`, in place and IN POSITION, value untouched.

    Returns True when something changed. The key keeps its position so the
    file stays in the order its producer writes, and the definition stamp is
    inserted directly after it (where the producers now emit it).
    """
    if OLD not in d:
        return False
    items = []
    for k, v in d.items():
        if k == OLD:
            items.append((NEW, v))
            log.append("%s: %s -> %s  (value carried unchanged: %r)"
                       % (where, OLD, NEW, v))
            if stamp:
                items.append((DEFINITION_KEY, L2_SPECTRAL_CORR_DEFINITION))
                log.append("%s: + %s" % (where, DEFINITION_KEY))
        elif k in (NEW, DEFINITION_KEY):
            items.append((k, v))
        else:
            items.append((k, v))
    d.clear()
    d.update(items)
    return True


def rename_budget_key(d, log, where):
    if OLD_BUDGET not in d:
        return False
    items = [((NEW_BUDGET if k == OLD_BUDGET else k), v) for k, v in d.items()]
    log.append("%s: %s -> %s  (budget value carried unchanged: %r)"
               % (where, OLD_BUDGET, NEW_BUDGET, d[OLD_BUDGET]))
    d.clear()
    d.update(items)
    return True


def rename_recursive(o, log, where):
    """Rename every nested OLD leaf (the historical #102 record's shape)."""
    changed = False
    if isinstance(o, dict):
        if OLD in o and not isinstance(o[OLD], (dict, list)):
            changed = rename_in_dict(o, log, where, stamp=False) or changed
        for k, v in list(o.items()):
            changed = rename_recursive(v, log, "%s/%s" % (where, k)) or changed
    elif isinstance(o, list):
        for i, v in enumerate(o):
            changed = rename_recursive(v, log, "%s[%d]" % (where, i)) or changed
    return changed


def transform(path, doc, log):
    """Apply the leaf-specific transformation; return True when changed."""
    rel = os.path.relpath(path, REPO)
    changed = False
    if "/SXT-039/" in path:
        changed = rename_in_dict(doc["L2_audio_q1021"], log,
                                 rel + " /L2_audio_q1021") or changed
        if changed and doc.get("schema_version") == 1:
            doc["schema_version"] = 2
            log.append("%s: schema_version 1 -> 2 (the renamed key)" % rel)
    elif "/SXT-038/" in path:
        if isinstance(doc.get("budgets"), dict):
            changed = rename_budget_key(doc["budgets"], log,
                                        rel + " /budgets") or changed
        if isinstance(doc.get(OLD), dict):
            # the per-case record's reported-not-gating spectral block
            inner = doc[OLD]
            if OLD_BUDGET in inner:
                rename_budget_key(inner, log, rel + " /%s" % OLD)
            items = []
            for k, v in doc.items():
                if k == OLD:
                    if "definition" not in v:
                        v["definition"] = L2_SPECTRAL_CORR_DEFINITION
                        log.append("%s: + /%s/definition" % (rel, NEW))
                    items.append((NEW, v))
                    log.append("%s: %s -> %s  (achieved %r, budget %r, pass "
                               "%r carried unchanged)"
                               % (rel, OLD, NEW, v.get("achieved"),
                                  v.get("budget"), v.get("pass")))
                else:
                    items.append((k, v))
            doc.clear()
            doc.update(items)
            changed = True
    elif "/sxt-037/" in path and "model-trace-" in path:
        for i, inst in enumerate(doc.get("instances", [])):
            changed = rename_in_dict(
                inst, log, "%s /instances[%d]" % (rel, i)) or changed
    elif "/sxt-037/" in path:
        changed = rename_recursive(doc, log, rel) or changed
        if changed and doc.get("schema_version") == 1:
            doc["schema_version"] = 2
            log.append("%s: schema_version 1 -> 2 (the renamed key)" % rel)
    else:
        raise SystemExit("no transformation declared for %s" % rel)
    return changed


def load(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return json.loads(f.read().decode())
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(path, doc):
    """Write back in the producer's own formatting (see EVIDENCE.md)."""
    if path.endswith(".gz"):
        buf = io.BytesIO()
        # mtime=0 / level 9: the bytes the committed traces already carry
        with gzip.GzipFile(filename="", mode="wb", compresslevel=9,
                           fileobj=buf, mtime=0) as g:
            g.write(json.dumps(doc, indent=1).encode())
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return
    if "f038-102" in path:
        # the #102 record: sorted keys, indent 1, no trailing newline
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")


def still_has_old_key(doc):
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in (OLD, OLD_BUDGET):
                    yield k
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    return sorted(set(walk(doc)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="change nothing; exit 1 if any target still carries "
                         "a bare spectral_corr / spectral_corr_min key")
    ap.add_argument("--log", default=None, help="write the change log here")
    args = ap.parse_args()

    log, offenders, changed_files = [], [], []
    for path in targets():
        rel = os.path.relpath(path, REPO)
        doc = load(path)
        if args.check:
            bad = still_has_old_key(doc)
            if bad:
                offenders.append((rel, bad))
            continue
        if transform(path, doc, log):
            dump(path, doc)
            changed_files.append(rel)
        bad = still_has_old_key(doc)
        if bad:
            offenders.append((rel, bad))

    if args.check:
        for rel, bad in offenders:
            print("STILL CARRIES %s: %s" % (",".join(bad), rel))
        print("checked %d declared L2-family artifacts; %d offenders"
              % (len(targets()), len(offenders)))
        return 1 if offenders else 0

    out = ["Issue #165 L2 key rename: spectral_corr -> l2_spectral_corr",
           "values are carried unchanged; this is a NAME-only transformation",
           ""] + log + [
           "", "changed files (%d):" % len(changed_files)] + \
        ["  " + r for r in changed_files] + \
        ["", "remaining offenders: %d" % len(offenders)] + \
        ["  %s: %s" % (r, ",".join(b)) for r, b in offenders]
    text = "\n".join(out) + "\n"
    print(text)
    if args.log:
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
        with open(args.log, "w", encoding="utf-8") as f:
            f.write(text)
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
