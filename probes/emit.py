"""Record construction and validated emission for SXT-016 probes.

Records are written only after validate_record passes; an under-specified
record raises and the run aborts (negative control: probes/validate.py).
"""
import json
import os

from .common import CLOCK_CANDIDATES_HZ, FS_HZ, TECH
from .validate import validate_record

PROBES_DIR = os.path.join("reports", "sxt-016", "probes")


def build_record(*, probe, kernel, word_lengths, has_phase_accumulator,
                 memory_model, assumptions, citations, ops, cycles_per_frame,
                 state_ram_bits, ext_bytes_per_frame, closure_at_clocks,
                 sxt015_replacement, per_sample=None, extra=None,
                 status="ESTIMATE"):
    rec = {
        "probe": probe,
        "kernel": kernel,
        "clock_hz_candidates": list(CLOCK_CANDIDATES_HZ),
        "sample_rate_hz": FS_HZ,
        "word_lengths": dict(word_lengths),
        "has_phase_accumulator": bool(has_phase_accumulator),
        "memory_model": dict(memory_model),
        "assumptions": list(assumptions),
        "structure_citations": list(citations),
        "ops": ops,
        "cycles_per_frame": cycles_per_frame,
        "state_ram_bits": state_ram_bits,
        "state_ram_note": "state RAM bits are per declared instance scope "
                          "(see record); logic op counts are separate from "
                          "state RAM (issue #11 acceptance)",
        "ext_bytes_per_frame": ext_bytes_per_frame,
        "closure_at_clocks": closure_at_clocks,
        "sxt015_replacement": dict(sxt015_replacement),
        "technology_note": TECH["technology_note"],
        "status": status,
    }
    if per_sample is not None:
        rec["cycles_per_sample"] = per_sample
    if extra:
        rec.update(extra)
    return rec


def record_filename(rec):
    wl = rec["word_lengths"]
    parts = [rec["probe"], rec["kernel"]]
    if "phase_bits" in wl:
        parts.append("ph%d" % wl["phase_bits"])
    parts.append("a%d" % wl.get("audio_bits", 0))
    parts.append(wl.get("multiplier", "nomult").lower())
    mm = rec.get("memory_model", {})
    ext = mm.get("external")
    if isinstance(ext, dict) and ext.get("name") and ext["name"] != "none":
        parts.append(ext["name"].lower())
    elif isinstance(ext, dict):
        parts.append("onchip")
    return "__".join(parts) + ".json"


def write_record(rec, outdir=PROBES_DIR):
    ok, errors = validate_record(rec)
    if not ok:
        raise ValueError(
            "REFUSED under-specified probe record (%s/%s): %s"
            % (rec.get("probe"), rec.get("kernel"), "; ".join(errors)))
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, record_filename(rec))
    with open(path, "w") as f:
        json.dump(rec, f, sort_keys=True, indent=1)
        f.write("\n")
    return path


def write_records(records, outdir=PROBES_DIR):
    return [write_record(r, outdir) for r in records]
