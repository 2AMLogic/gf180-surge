#!/usr/bin/env python3
"""SXT-028l: probe for the pinned oracle and record the status of every
oracle-gated leg of this leaf.

This exists so the NOT_RUN statuses in reports/SXT-028l/EVIDENCE.md are
MEASURED rather than asserted: it actually attempts to locate the pinned
engine checkout and import surgepy, and writes what it found. A leg that did
not run is recorded NOT_RUN (or BLOCKED), never PASS.

Re-run on an oracle host to flip the record; the same file is then the
input-of-record for the fixture-render and reference-comparison legs.

NOTE (specific to this leaf): an available oracle is NECESSARY BUT NOT
SUFFICIENT for this routing form's fixture freeze. Send buses 3/4 hit the
documented SXT-011 exposure gap -- no .fxp stores their per-scene send levels
and surgepy does not expose them -- so the loader-default semantics need an
engine-behavior probe AND an SXT-017 data-gap policy decision (#12) before
fixtures can be frozen. That leg is therefore recorded as BLOCKED on #12
rather than merely NOT_RUN on the missing oracle.

Also writes the render-refusal transcript
(reports/SXT-028l/artifacts/render-refusals.txt), so the absence of pinned-
engine fixture renders is recorded rather than silently missing. The issue's
Fixtures plan calls for NEW reference fixtures (no SXT-014 ablation carrier
exists for this routing form); none can be rendered without the oracle.

Original to this repository (Apache-2.0).
"""

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(REPO, "reports", "SXT-028l", "artifacts")
OUT = os.path.join(ARTIFACTS, "oracle-status.json")
RENDER_REFUSALS = os.path.join(ARTIFACTS, "render-refusals.txt")

ORACLE_LEGS = [
    ("extract-slot-params", "tools/extract_rf_send34_inputs.py",
     "the LIVE surgepy leg of the carrier extraction: per-slot algorithm "
     "parameter values + the engine-side per-scene drift determinism gate "
     "(the census/graphs routing metadata itself needs no oracle and IS "
     "verified)"),
    ("render", "tools/render_fx_fixtures.py pattern",
     "NEW pinned-engine reference fixtures for this routing form under "
     "SXT-012 policies (original + per-slot bypass + all-off dry, tails "
     "included), for the carriers named in the issue's Fixtures plan"),
    ("model-render", "model/effects/rf-rf-send34/ over a fixture scene/main bus",
     "the frozen routing model driven by real fixture buses with concrete "
     "occupant algorithms in send3/send4"),
    ("reference-compare", "tools/compare_fx_reference.py pattern",
     "model-vs-pinned-engine agreement against the [PROPOSED, not frozen] "
     "max/rms/corr budgets on the fixture presets"),
]

# Legs that an available oracle alone does NOT unblock.
POLICY_BLOCKED_LEGS = [
    ("send-level-default-probe", "SXT-017 data-gap decision (#12)",
     "the per-scene send levels for buses 3/4 are not stored in any .fxp and "
     "are not exposed by surgepy (corpus/normalized/README.md 'Send levels "
     "3/4'); the loader-default semantics need an engine-behavior probe AND "
     "an SXT-017 policy decision before any fixture for this routing form "
     "can be frozen. BLOCKED on #12, not merely NOT_RUN on the oracle.",
     "BLOCKED"),
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


RENDER_REFUSAL_TEMPLATE = """\
SXT-028l pinned-engine fixture renders (tools/render_fx_fixtures.py pattern)
status: {status}

The issue's Fixtures plan calls for NEW reference fixtures: no SXT-014
ablation carrier exists for this routing form, so original + per-slot bypass
+ all-off dry buses (tails included) would have to be rendered from the
pinned engine under SXT-012 policies.

TWO independent gates apply to this leaf, and both are open:
  1. the pinned oracle build (surgepy) -- see below;
  2. the SXT-011 send-level exposure gap for buses 3/4, which needs an
     SXT-017 data-gap policy decision (#12) before ANY fixture for this
     routing form can be frozen, oracle or no oracle
     (reports/SXT-028l/artifacts/send-level-gap.json).

{body}

Re-run on an oracle host:
  python3 tools/rf_send34_oracle_status.py       # flips the oracle half
  python3 tools/extract_rf_send34_inputs.py      # live per-slot params
  # then, ONLY after #12 decides the send-level data-gap policy, render the
  # fixtures and run the reference comparison
"""

UNAVAILABLE_BODY = """\
No pinned-engine checkout and no importable surgepy exist in the environment
this leaf was built in (measured: reports/SXT-028l/artifacts/oracle-status.json).
No wet/dry fixture bus was rendered, so there are no per-carrier refusal rows
yet. NOT_RUN is not a pass.

Consequence: every model-vs-pinned-engine leg of this leaf is NOT_RUN. The
RTL-vs-frozen-model exactness claim is unaffected and was run in full
(reports/SXT-028l/rtl-exactness.json), as were all the negative controls
(reports/SXT-028l/negative-controls/negative-controls.json)."""

AVAILABLE_BODY = """\
A pinned-engine checkout and an importable surgepy were found (measured:
reports/SXT-028l/artifacts/oracle-status.json). The fixture renders
themselves are still not produced by this tool -- and gate 2 above (the
SXT-017 send-level data-gap decision, #12) still applies regardless. Once
both are cleared, run the render and reference-comparison legs and replace
this transcript with their per-carrier rows."""


def main():
    detail = probe()
    available = detail["surgepy_importable"] and detail["engine_dir_present"]
    status = "AVAILABLE" if available else "UNAVAILABLE"
    legs = {
        name: {
            "tool": tool,
            "what": what,
            "status": "NOT_RUN" if not available else "RUNNABLE",
            "reason": (None if available else
                       "no pinned-engine checkout / surgepy in this "
                       "environment; the leg was not run and must never "
                       "be reported as a pass"),
        } for name, tool, what in ORACLE_LEGS
    }
    for name, gate, what, st in POLICY_BLOCKED_LEGS:
        legs[name] = {"tool": gate, "what": what, "status": st,
                      "reason": "blocked on the SXT-017 data-gap policy "
                                "decision (#12); an available oracle does "
                                "not unblock it"}
    doc = {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "oracle_status": status,
        "probe": detail,
        "legs": legs,
        "fixture_freeze_gates": {
            "oracle_build": status,
            "sxt017_send_level_data_gap": "BLOCKED (#12)",
            "note": "BOTH gates must clear before reference fixtures for this "
                    "routing form can be frozen; the RTL-vs-frozen-model "
                    "exactness claim depends on neither.",
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
    with open(RENDER_REFUSALS, "w") as f:
        f.write(RENDER_REFUSAL_TEMPLATE.format(
            status="NOT_RUN" if not available else "RUNNABLE (not run here)",
            body=UNAVAILABLE_BODY if not available else AVAILABLE_BODY))
    print(json.dumps({"oracle_status": status,
                      "legs": {k: v["status"] for k, v in doc["legs"].items()}},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
