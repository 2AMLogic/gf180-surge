#!/usr/bin/env python3
"""SXT-028k: regenerate the leaf's derived evidence artifacts.

Writes, all from the frozen model and the committed extraction records so
that every one of them is reproducible from the tree (the failure mode
recorded as #125 was an evidence record that could no longer be regenerated
from its own inputs):

  reports/SXT-028k/artifacts/state-cost.json    state residency + traffic
                                                (SXT-015 accounting; the fit
                                                verdict stays PENDING-SXT-016)
  reports/SXT-028k/artifacts/tail-window.json   the declared gain-recovery
                                                tail span per carrier slot
  reports/SXT-028k/artifacts/oracle-status.json a live probe for the pinned
                                                oracle; every leg it cannot
                                                run is NOT_RUN or BLOCKED,
                                                never a pass

Claim scope: accounting and status only. Nothing written here is a
model-vs-pinned-engine agreement claim, a cost/fit claim, a preset-support
claim, or a musical-quality claim.

Usage: python3 tools/aw4_evidence_artifacts.py [--check]
  --check  regenerate in memory and diff against the committed files
           (exit 1 on drift); used by CI/reviewers, writes nothing.

Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-4"))

import logical4_model as M  # noqa: E402

ARTDIR = os.path.join(REPO, "reports", "SXT-028k", "artifacts")
INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")
MANIFEST = os.path.join(REPO, "oracle", "manifest.json")

TAIL_DECADES = 5.0
TAIL_DEFINITION = (
    "Logical emits silence into silence, so it has no amplitude ringout. "
    "The declared tail is the GAIN RECOVERY span: `decades / "
    "min(remainder[0..sel])` samples, i.e. 5 natural time constants of the "
    "slowest ACTIVE control bank. An amplitude-only ringout gate would read "
    "'no tail' here and would pass a dropped-tail render -- see NC-D.")


def carrier_records():
    out = []
    for name in sorted(os.listdir(INPUTS)):
        if name.startswith("aw-4-") and name.endswith(".json"):
            with open(os.path.join(INPUTS, name)) as f:
                out.append(json.load(f))
    return out


def state_cost():
    rep = M.buffer_report()
    rep["model_revision"] = M.model_revision()
    return rep


def tail_window():
    windows = {}
    for rec in carrier_records():
        for slot in rec["logical_slots"]:
            ctrl = M.build_control(slot["params"])
            sel = ctrl["ratioselector"]
            key = "%s:slot%d" % (rec["slug"], slot["slot_index"])
            windows[key] = {
                "ratioselector": sel,
                "remainders_active": ctrl["d"]["remainder"][:sel + 1],
                "tail_window_samples": M.tail_window_samples(ctrl,
                                                             TAIL_DECADES),
                "tail_window_blocks": M.tail_window_blocks(ctrl,
                                                           TAIL_DECADES),
            }
    return {
        "leaf": "SXT-028k",
        "model_revision": M.model_revision(),
        "decades": TAIL_DECADES,
        "definition": TAIL_DEFINITION,
        "windows": windows,
    }


def probe_oracle():
    """Is a built pinned oracle reachable? Fail-closed: unknown == no."""
    d = os.environ.get("ORACLE_SURGE_DIR")
    if not d or not os.path.isdir(d):
        return None
    for root, _dirs, files in os.walk(d):
        for f in files:
            if f.startswith("surgepy") and f.endswith((".so", ".pyd",
                                                       ".dylib")):
                return os.path.join(root, f)
    return None


def oracle_status():
    with open(MANIFEST) as f:
        man = json.load(f)
    found = probe_oracle()
    available = found is not None
    if available:
        probe = "surgepy found at %s" % found
        legs = {
            "oracle_parameter_readback": {
                "status": "NOT_RUN",
                "why": "an oracle is reachable but this run did not execute "
                       "the leg: run tools/extract_aw4_inputs.py "
                       "--mode oracle and re-record",
            },
            "fixture_renders_sxt012": {
                "status": "NOT_RUN",
                "why": "not executed by this tool",
            },
            "reference_repeatability_3x_gate": {
                "status": "NOT_RUN",
                "why": "not executed by this tool",
            },
            "model_vs_pinned_engine_agreement": {
                "status": "NOT_RUN",
                "why": "no reference render exists, so no max/rms/corr "
                       "number exists",
            },
        }
    else:
        probe = ("ORACLE_SURGE_DIR unset and no built surgepy reachable in "
                 "the implementation environment")
        legs = {
            "oracle_parameter_readback": {
                "status": "BLOCKED",
                "why": "tools/extract_aw4_inputs.py --mode oracle refuses; "
                       "transcript in artifacts/extract-refusals-oracle.txt",
            },
            "fixture_renders_sxt012": {
                "status": "NOT_RUN",
                "why": "needs the oracle host",
            },
            "reference_repeatability_3x_gate": {
                "status": "NOT_RUN",
                "why": "no renders to repeat",
            },
            "model_vs_pinned_engine_agreement": {
                "status": "NOT_RUN",
                "why": "no reference render exists, so no max/rms/corr "
                       "number exists",
            },
        }
    return {
        "leaf": "SXT-028k",
        "oracle_status": "AVAILABLE" if available else "UNAVAILABLE",
        "probe": probe,
        "expected_checkout": man["engine"]["expected_checkout"],
        "legs": legs,
        "rule": "a leg that did not run is never reported as a pass "
                "(AGENTS.md)",
    }


ARTIFACTS = (
    ("state-cost.json", state_cost),
    ("tail-window.json", tail_window),
    ("oracle-status.json", oracle_status),
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="diff against the committed files; write nothing")
    args = ap.parse_args()

    drift = []
    for name, fn in ARTIFACTS:
        path = os.path.join(ARTDIR, name)
        text = json.dumps(fn(), indent=2, sort_keys=True) + "\n"
        if args.check:
            have = open(path).read() if os.path.exists(path) else ""
            if have != text:
                drift.append(name)
            continue
        os.makedirs(ARTDIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        print("wrote", os.path.relpath(path, REPO))

    if args.check:
        if drift:
            print("STALE: " + ", ".join(drift))
            return 1
        print("artifacts are current against the frozen model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
