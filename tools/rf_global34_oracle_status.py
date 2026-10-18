#!/usr/bin/env python3
"""SXT-028j: probe for the pinned oracle and record the status of every
oracle-gated leg of this leaf.

This exists so the NOT_RUN statuses in reports/SXT-028j/EVIDENCE.md are
MEASURED rather than asserted: it actually attempts to locate the pinned
engine checkout and import surgepy, and writes what it found. A leg that did
not run is recorded NOT_RUN (or BLOCKED), never PASS.

Re-run on an oracle host to flip the record; the same file is then the
input-of-record for the fixture-render and reference-comparison legs.

Also writes the render-refusal transcript
(reports/SXT-028j/artifacts/render-refusals.txt), so the absence of pinned-
engine fixture renders is recorded rather than silently missing. The issue's
Fixtures plan calls for NEW reference fixtures (no SXT-014 ablation carrier
exists for this routing form); none can be rendered without the oracle.

Original to this repository (Apache-2.0).
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
ARTIFACTS = os.path.join(REPO, "reports", "SXT-028j", "artifacts")
OUT = os.path.join(ARTIFACTS, "oracle-status.json")
RECORD = os.path.join(REPO, "reports", "SXT-028j", "model-vs-reference.json")
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")
RENDER_REFUSALS = os.path.join(ARTIFACTS, "render-refusals.txt")

ORACLE_LEGS = [
    ("extract-slot-params", "tools/extract_rf_global34_inputs.py",
     "the LIVE surgepy leg of the carrier extraction: per-slot algorithm "
     "parameter values + the engine-side per-scene drift determinism gate "
     "(the census/graphs routing metadata itself needs no oracle and IS "
     "verified)"),
    ("render", "tools/render_fx_fixtures.py pattern",
     "NEW pinned-engine reference fixtures for this routing form under "
     "SXT-012 policies (original + per-slot bypass + all-off dry, tails "
     "included), for the carriers named in the issue's Fixtures plan"),
    ("model-render", "model/effects/rf-rf-global34/ over a fixture dry bus",
     "the frozen routing model driven by a real fixture bus with concrete "
     "occupant algorithms in global3/global4"),
    ("reference-compare", "tools/compare_fx_reference.py pattern",
     "model-vs-pinned-engine agreement against the [PROPOSED, not frozen] "
     "max/rms/corr budgets on the fixture presets"),
]


def probe():
    """Measure, never assert: locate the pinned engine tree and load surgepy
    through the harness's sanctioned loader (oracle_common.import_surgepy:
    explicit native-extension load from the selected build, no sys.path
    search). Run under the oracle's interpreter, e.g. the exports printed by
    `oracle/fetch-and-build.sh --prebuilt`."""
    detail = {}
    manifest = os.path.join(REPO, "oracle", "manifest.json")
    if os.path.exists(manifest):
        with open(manifest) as f:
            m = json.load(f)
        detail["engine_pin"] = m["engine"]["commit"]
        detail["expected_checkout"] = \
            m["engine"]["expected_checkout"]["location_used_for_evidence"]
    try:
        import oracle_common as oc  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - environment-dependent
        detail.update(engine_dir_probed=None, engine_dir_present=False,
                      surgepy_importable=False,
                      surgepy_probe_stderr=[f"oracle_common: {e}"])
        return detail
    engine_dir = oc.engine_dir()
    detail["engine_dir_probed"] = engine_dir
    detail["engine_dir_present"] = bool(engine_dir and os.path.isdir(engine_dir))
    try:
        mod = oc.import_surgepy()
        detail["surgepy_importable"] = True
        detail["surgepy_probe_stderr"] = []
        detail["surgepy_version"] = mod.getVersion()
    except Exception as e:
        detail["surgepy_importable"] = False
        detail["surgepy_probe_stderr"] = [f"{type(e).__name__}: {e}"][-1:]
    return detail


def leg_ran_evidence():
    """For an AVAILABLE oracle: which legs have a committed record proving
    they actually ran (never inferred from availability alone). Returns
    {leg: (ran, scope_note)}."""
    carriers = []
    if os.path.isdir(FX_INPUTS):
        for fn in sorted(os.listdir(FX_INPUTS)):
            if fn.startswith("rf-rf-global34-") and fn.endswith(".json"):
                with open(os.path.join(FX_INPUTS, fn)) as f:
                    carriers.append(json.load(f))
    extract_ran = bool(carriers) and all(
        c.get("oracle_extraction", {}).get("ok") and
        (c["oracle_extraction"].get("live") or {}).get("ran")
        for c in carriers)
    rec = None
    if os.path.exists(RECORD):
        with open(RECORD) as f:
            rec = json.load(f)
    ran = rec is not None
    gated = len((rec or {}).get("carrier_determinism_gate", []))
    refused = sum(1 for g in (rec or {}).get("carrier_determinism_gate", [])
                  if g["gate"] == "REFUSED")
    diag = sum(1 for p in (rec or {}).get("pairs", []) if p.get("diagnostic"))
    orig = sum(1 for p in (rec or {}).get("pairs", [])
               if not p.get("diagnostic"))
    scope = (f"carrier x sequence pairs gated: {gated}, REFUSED as "
             f"source-nonrepeatable (policy #310): {refused}; original-"
             f"carrier pairs rendered: {orig}; diagnostic (non-carrier) "
             f"pairs rendered: {diag}")
    return {
        "extract-slot-params": (extract_ran, "live leg ran for every carrier "
                                "record (model/effects/fx_inputs)"),
        "render": (ran, scope),
        "model-render": (ran, scope),
        "reference-compare": (ran, scope),
    }


RENDER_REFUSAL_TEMPLATE = """\
SXT-028j pinned-engine fixture renders (tools/render_fx_fixtures.py pattern)
status: {status}

The issue's Fixtures plan calls for NEW reference fixtures: no SXT-014
ablation carrier exists for this routing form, so original + per-slot bypass
+ all-off dry buses (tails included) would have to be rendered from the
pinned engine under SXT-012 policies.

{body}

Re-run on an oracle host:
  python3 tools/rf_global34_oracle_status.py       # flips this record
  python3 tools/extract_rf_global34_inputs.py      # live per-slot params
  # then render the fixtures and run the reference comparison
"""

UNAVAILABLE_BODY = """\
No pinned-engine checkout and no importable surgepy exist in the environment
this leaf was built in (measured: reports/SXT-028j/artifacts/oracle-status.json).
No wet/dry fixture bus was rendered, so there are no per-carrier refusal rows
yet. NOT_RUN is not a pass.

Consequence: every model-vs-pinned-engine leg of this leaf is NOT_RUN. The
RTL-vs-frozen-model exactness claim is unaffected and was run in full
(reports/SXT-028j/rtl-exactness.json), as were all five negative controls
(reports/SXT-028j/negative-controls/negative-controls.json)."""

def main():
    detail = probe()
    available = detail["surgepy_importable"] and detail["engine_dir_present"]
    status = "AVAILABLE" if available else "UNAVAILABLE"
    evidence = leg_ran_evidence() if available else {}
    doc = {
        "schema_version": 1,
        "leaf": "SXT-028j",
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
                **({"ran": evidence[name][0], "ran_scope": evidence[name][1]}
                   if available else {}),
            } for name, tool, what in ORACLE_LEGS
        },
        "rule": "AGENTS.md: a test that did not run must never be reported as "
                "a pass. Claim 2 (model-vs-pinned-engine agreement) is "
                "NOT_RUN for this leaf until every leg above is RUNNABLE and "
                "has actually been run.",
    }
    os.makedirs(ARTIFACTS, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    if not available:
        with open(RENDER_REFUSALS, "w") as f:
            f.write(RENDER_REFUSAL_TEMPLATE.format(
                status="NOT_RUN", body=UNAVAILABLE_BODY))
    # AVAILABLE: render-refusals.txt belongs to
    # tools/render_rf_global34_reference.py (per-carrier gate rows); this
    # probe never overwrites a transcript written by the leg itself.
    print(json.dumps({"oracle_status": status,
                      "legs": {k: v["status"] for k, v in doc["legs"].items()}},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
