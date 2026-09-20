"""SXT-016 negative control: an under-specified probe record must FAIL.

Issue #11 acceptance: "a probe with an unstated clock/memory assumption
fails review and is excluded from SXT-017 inputs."

This control:
  1. builds a deliberately under-specified record (invented clock outside
     the candidate set, no word lengths, no memory model, no assumptions);
  2. shows validate_record rejects it with specific errors;
  3. shows write_record REFUSES to emit it (the emitter aborts rather
     than writing a number whose assumptions are unstated);
  4. writes a machine-readable transcript to
     reports/sxt-016/negative-control/ so the demonstrated exclusion is
     inspectable.

A record that fails this validation can never enter reports/sxt-016/
probes/, which is the mechanical exclusion SXT-017 relies on.
"""
import json
import os

from .emit import write_record
from .validate import make_invalid_record, validate_record

OUTDIR = os.path.join("reports", "sxt-016", "negative-control")


def run(outdir=OUTDIR):
    bad = make_invalid_record()
    ok, errors = validate_record(bad)

    refused = False
    refusal_error = None
    try:
        write_record(bad, os.path.join(outdir, "must-not-exist"))
    except ValueError as e:
        refused = True
        refusal_error = str(e)

    control = {
        "control": "nc-underspecified-record",
        "targets_failure_mode": "a probe result with unstated clock/memory/"
                                "word-length assumptions silently entering "
                                "the SXT-016 evidence set",
        "input_record": bad,
        "validate_record_result": {"ok": ok, "errors": errors},
        "write_record_refused": refused,
        "write_record_error": refusal_error,
        "expected": {
            "ok": False,
            "refused": True,
            "error_classes": [
                "missing required field: word_lengths",
                "missing required field: memory_model",
                "clock 70000000 is not a declared candidate",
                "clock_hz_candidates must name the full candidate set",
                "word_lengths must be a dict",
                "memory_model must be a dict",
                "assumptions must be a non-empty list",
                "structure_citations must be a non-empty list",
                "closure_at_clocks missing 70000000",
                "sxt015_replacement.replaces must be stated",
            ],
        },
        "pass": (not ok) and refused,
        "exclusion_rule": "records failing validate_record never reach "
                          "reports/sxt-016/probes/; SXT-017 must consume "
                          "only validated records",
        "status": "PASS" if ((not ok) and refused) else "FAIL",
    }
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "nc-underspecified-record.json"),
              "w") as f:
        json.dump(control, f, sort_keys=True, indent=1)
        f.write("\n")
    return control
