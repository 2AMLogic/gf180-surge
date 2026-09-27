#!/usr/bin/env python3
"""SXT-028g: probe for the pinned oracle and record the status of every
oracle-gated leg of this leaf.

This exists so the NOT_RUN statuses in reports/SXT-028g/EVIDENCE.md are
MEASURED rather than asserted: it actually attempts to locate the pinned
engine checkout and import surgepy, and writes what it found. A leg that did
not run is recorded NOT_RUN (or BLOCKED), never PASS.

Re-run on an oracle host to flip the record; the same file is then the
input-of-record for the extraction, render and reference-comparison legs.

Original to this repository (Apache-2.0).
"""

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "reports", "SXT-028g", "artifacts",
                   "oracle-status.json")

ORACLE_LEGS = [
    ("extract", "tools/extract_phaser_inputs.py",
     "fail-closed preset extraction (census-blob verified, graphs "
     "cross-checked) -> model/effects/fx_inputs/type-phaser-<slug>.json"),
    ("render", "tools/render_phaser_fixtures.py",
     "pinned-engine wet/dry fixture buses under SXT-012/023 policies, "
     "tails included -> reports/SXT-028g/fixtures/"),
    ("model-render", "model/effects/run_phaser_model.py",
     "frozen chain model over the fixture dry bus -> model wet render"),
    ("reference-compare", "tools/compare_phaser_reference.py",
     "model-vs-pinned-engine agreement against [PROPOSED, not frozen] "
     "budgets + the issue-#100 wet tail gate"),
]


def probe():
    detail = {}
    engine_dir = os.environ.get("ORACLE_SURGE_DIR")
    manifest = os.path.join(REPO, "oracle", "manifest.json")
    if os.path.exists(manifest):
        with open(manifest) as f:
            m = json.load(f)
        detail["engine_pin"] = m["engine"]["commit"]
        detail["expected_checkout"] = \
            m["engine"]["expected_checkout"]["location_used_for_evidence"]
        if engine_dir is None:
            engine_dir = detail["expected_checkout"]
    detail["engine_dir_probed"] = engine_dir
    detail["engine_dir_present"] = bool(engine_dir and os.path.isdir(engine_dir))

    r = subprocess.run([sys.executable, "-c", "import surgepy"],
                       capture_output=True, text=True)
    detail["surgepy_importable"] = r.returncode == 0
    detail["surgepy_probe_stderr"] = r.stderr.strip().splitlines()[-1:] or []
    return detail


def main():
    detail = probe()
    available = detail["surgepy_importable"] and detail["engine_dir_present"]
    status = "AVAILABLE" if available else "UNAVAILABLE"
    doc = {
        "schema_version": 1,
        "leaf": "SXT-028g",
        "oracle_status": status,
        "probe": detail,
        "legs": {
            name: {
                "tool": tool,
                "what": what,
                "status": "NOT_RUN" if not available else "RUNNABLE",
                "reason": (None if available else
                           "no pinned-engine checkout / surgepy in this "
                           "environment; the leg was not run and must never "
                           "be reported as a pass"),
            } for name, tool, what in ORACLE_LEGS
        },
        "rule": "AGENTS.md: a test that did not run must never be reported as "
                "a pass. Claim 2 (model-vs-pinned-engine agreement) is "
                "NOT_RUN for this leaf until every leg above is RUNNABLE and "
                "has actually been run.",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({"oracle_status": status,
                      "legs": {k: v["status"] for k, v in doc["legs"].items()}},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
