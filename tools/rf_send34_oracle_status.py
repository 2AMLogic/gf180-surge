#!/usr/bin/env python3
"""SXT-028l: probe for the pinned oracle and record the status of every
oracle-gated leg of this leaf.

This exists so the NOT_RUN statuses in reports/SXT-028l/EVIDENCE.md are
MEASURED rather than asserted: it actually attempts to locate the pinned
engine checkout and import surgepy, and writes what it found. A leg that did
not run is recorded NOT_RUN (or BLOCKED), never PASS.

Re-run on an oracle host to flip the record; the same file is then the
input-of-record for the fixture-render and reference-comparison legs. Run it
UNDER the oracle's own interpreter (`$ORACLE_PYTHON` from
`oracle/fetch-and-build.sh --prebuilt`), because the surgepy binding is built
for one CPython ABI -- a probe run under the ambient `python3` truthfully
reports UNAVAILABLE even on a host that has the oracle installed.

"AVAILABLE" requires all three of: the engine directory present, `import
surgepy` succeeding through `oracle_common`, and the version string the binding
itself reports carrying the pinned commit. An import that lands on an unpinned
engine is NOT available.

Whether an oracle-gated leg was actually RUN is read from the live record
(`artifacts/live-oracle-extraction.json`), never inferred from the oracle being
present: "RUNNABLE" is not "ran", and "ran" is not "passed".

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
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))

ARTIFACTS = os.path.join(REPO, "reports", "SXT-028l", "artifacts")
OUT = os.path.join(ARTIFACTS, "oracle-status.json")
RENDER_REFUSALS = os.path.join(ARTIFACTS, "render-refusals.txt")
LIVE_LEG = os.path.join(ARTIFACTS, "live-oracle-extraction.json")

# Legs whose only gate is the oracle build: an available oracle makes them
# runnable, and whether they were actually RUN is read from the live record,
# never assumed.
ORACLE_LEGS = [
    ("extract-slot-params", "tools/extract_rf_send34_inputs.py",
     "the LIVE surgepy leg of the carrier extraction: per-slot algorithm "
     "parameter values for send3/send4, read from the engine's normalized "
     "state and cross-checked against the committed corpus graph (the "
     "census/graphs routing metadata itself needs no oracle and IS verified)"),
    ("drift-determinism-gate", "tools/extract_rf_send34_inputs.py",
     "the engine-side per-scene drift determinism gate: a carrier whose "
     "scene `drift` is nonzero cannot carry a repeatable reference render at "
     "all, so it is not render-eligible even once #12 clears"),
]

# Legs that an available oracle alone does NOT unblock, because this routing
# form's fixtures cannot be frozen until #12 decides the send-level policy.
# These are BLOCKED, not merely NOT_RUN -- running them would require guessing
# a per-scene send level for buses 3/4, which is exactly #12's decision.
FIXTURE_LEGS = [
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
    """Actually look for the oracle and import the binding. Everything here is
    MEASURED in the environment this runs in: the engine pin, the checkout (or
    prebuilt install) directory, an `import surgepy` through the same
    `oracle_common` path every harness tool uses, and -- when the import
    succeeds -- the engine version string the binding itself reports, checked
    against the pinned commit. An import that lands on an UNPINNED engine is
    recorded as not-available rather than counted."""
    detail = {}
    pin = None
    manifest = os.path.join(REPO, "oracle", "manifest.json")
    engine_dir = os.environ.get("ORACLE_SURGE_DIR")
    if os.path.exists(manifest):
        with open(manifest) as f:
            m = json.load(f)
        pin = m["engine"]["commit"]
        detail["engine_pin"] = pin
        detail["expected_checkout"] = \
            m["engine"]["expected_checkout"]["location_used_for_evidence"]
        if engine_dir is None:
            engine_dir = detail["expected_checkout"]
    detail["engine_dir_probed"] = engine_dir
    detail["engine_dir_present"] = bool(engine_dir and os.path.isdir(engine_dir))

    detail["surgepy_version"] = None
    detail["surgepy_module"] = None
    detail["surgepy_version_carries_pin"] = False
    try:
        import oracle_common as oc  # noqa: PLC0415
        surgepy = oc.import_surgepy()
    except Exception as e:  # environment-dependent
        detail["surgepy_importable"] = False
        detail["surgepy_probe_stderr"] = [f"{type(e).__name__}: {e}"]
        return detail
    detail["surgepy_importable"] = True
    detail["surgepy_probe_stderr"] = []
    detail["surgepy_version"] = surgepy.getVersion()
    detail["surgepy_module"] = surgepy.__file__
    detail["surgepy_version_carries_pin"] = bool(
        pin and pin[:9] in detail["surgepy_version"])
    return detail


def live_leg_record():
    """The live leg's own committed record, or None. Read rather than assumed:
    an available oracle says a leg COULD run, never that it DID."""
    if not os.path.exists(LIVE_LEG):
        return None
    with open(LIVE_LEG) as f:
        return json.load(f)


RENDER_REFUSAL_TEMPLATE = """\
SXT-028l pinned-engine fixture renders (tools/render_fx_fixtures.py pattern)
status: {status}

The issue's Fixtures plan calls for NEW reference fixtures: no SXT-014
ablation carrier exists for this routing form, so original + per-slot bypass
+ all-off dry buses (tails included) would have to be rendered from the
pinned engine under SXT-012 policies.

TWO independent gates apply to this leaf:
  1. the pinned oracle build (surgepy) -- {gate1};
  2. the SXT-011 send-level exposure gap for buses 3/4, which needs an
     SXT-017 data-gap policy decision (#12) before ANY fixture for this
     routing form can be frozen, oracle or no oracle
     (reports/SXT-028l/artifacts/send-level-gap.json) -- OPEN.

{body}

Re-run on an oracle host:
  ORACLE_PREBUILT=1 oracle/fetch-and-build.sh    # installs/locates the oracle
  "$ORACLE_PYTHON" tools/extract_rf_send34_inputs.py   # live per-slot params
  "$ORACLE_PYTHON" tools/rf_send34_oracle_status.py    # records what ran
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
Gate 1 is CLEARED: a pinned-engine install and an importable surgepy whose
reported version carries the pinned commit were found, and the LIVE
extraction leg has been run against them (measured:
reports/SXT-028l/artifacts/oracle-status.json,
reports/SXT-028l/artifacts/live-oracle-extraction.json).

Gate 2 is still OPEN, so NO fixture was rendered and there are no per-carrier
rows yet: the SXT-017 send-level data-gap decision (#12) owns the per-scene
send level for buses 3/4, and rendering a fixture without it would mean
guessing that value. The render / model-render / reference-compare legs are
therefore recorded BLOCKED (#12), not NOT_RUN-on-the-oracle and not a pass.

Additionally, the engine-side per-scene drift determinism gate FAILS for at
least one carrier in some environments (see
`legs["drift-determinism-gate"]` in oracle-status.json): a carrier whose
scene `drift` is nonzero cannot carry a repeatable reference render even once
#12 clears, so it is not render-eligible and a different carrier must be
chosen for that shape."""


NOT_RUN_REASON = ("no pinned-engine checkout / surgepy in this environment; "
                  "the leg was not run and must never be reported as a pass")
BLOCKED_12_REASON = ("blocked on the SXT-017 data-gap policy decision (#12); "
                     "an available oracle does not unblock it, because no "
                     "fixture for this routing form can be frozen without a "
                     "per-scene send level for buses 3/4")


def oracle_leg_status(name, live):
    """Measured status of an oracle-gated leg. `live` is the live record (or
    None). Returns (status, reason, extra-fields)."""
    if live is None:
        return "NOT_RUN", ("the oracle is available but the leg has not been "
                           "run here: run tools/extract_rf_send34_inputs.py "
                           "and commit artifacts/live-oracle-extraction.json"), {}
    if name == "extract-slot-params":
        sub = live["parameter_extraction"]
        extra = {"ran": True,
                 "evidence": "reports/SXT-028l/artifacts/"
                             "live-oracle-extraction.json",
                 "carriers_extracted": sub["carriers_extracted"],
                 "carriers_total": sub["carriers_total"]}
        reason = (None if sub["status"] == "PASS" else
                  f"the live leg ran but reported {sub['status']}")
        return sub["status"], reason, extra
    sub = live["determinism_gate"]
    extra = {"ran": True,
             "evidence": "reports/SXT-028l/artifacts/"
                         "live-oracle-extraction.json",
             "carriers_passing": sub["carriers_passing"],
             "carriers_failing": sub["carriers_failing"],
             "bounds": sub["bounds"],
             "routed_to": sub.get("routed_to")}
    reason = (None if sub["status"] == "PASS" else
              f"the gate ran and FAILED for {sub['carriers_failing']}: a "
              f"carrier with nonzero per-scene drift cannot carry a "
              f"repeatable reference render")
    return sub["status"], reason, extra


def main():
    detail = probe()
    available = (detail["surgepy_importable"] and detail["engine_dir_present"]
                 and detail["surgepy_version_carries_pin"])
    status = "AVAILABLE" if available else "UNAVAILABLE"
    live = live_leg_record() if available else None

    legs = {}
    for name, tool, what in ORACLE_LEGS:
        if not available:
            legs[name] = {"tool": tool, "what": what, "status": "NOT_RUN",
                          "reason": NOT_RUN_REASON, "ran": False}
            continue
        st, reason, extra = oracle_leg_status(name, live)
        legs[name] = {"tool": tool, "what": what, "status": st,
                      "reason": reason, "ran": bool(extra.get("ran", False))}
        legs[name].update({k: v for k, v in extra.items() if k != "ran"})
    for name, tool, what in FIXTURE_LEGS:
        # These stay unrun whether or not the oracle is there. While the oracle
        # is missing BOTH gates are open, so NOT_RUN is the honest measurement;
        # with the oracle present the remaining gate is #12 alone, so BLOCKED
        # names the real reason instead of implying the leg could just be run.
        legs[name] = {
            "tool": tool, "what": what, "ran": False,
            "status": "BLOCKED" if available else "NOT_RUN",
            "reason": BLOCKED_12_REASON if available else NOT_RUN_REASON,
            "blocking_issue": "#12 (SXT-017 send-level data-gap decision)",
        }
    for name, gate, what, st in POLICY_BLOCKED_LEGS:
        legs[name] = {"tool": gate, "what": what, "status": st, "ran": False,
                      "blocking_issue": "#12 (SXT-017 send-level data-gap "
                                        "decision)",
                      "reason": BLOCKED_12_REASON}
    doc = {
        "schema_version": 2,
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
            status=("NOT_RUN (both gates open)" if not available else
                    "BLOCKED (#12) -- the oracle gate is cleared, the "
                    "send-level policy gate is not"),
            gate1="OPEN" if not available else "CLEARED",
            body=UNAVAILABLE_BODY if not available else AVAILABLE_BODY))
    print(json.dumps({"oracle_status": status,
                      "legs": {k: v["status"] for k, v in doc["legs"].items()}},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
