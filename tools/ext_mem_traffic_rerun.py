#!/usr/bin/env python3
"""SXT-023 ext-mem traffic re-derivation for the revised tree (issue #16).

Reads the committed revised model trace (reports/sxt-023/artifacts/
model_trace_<slug>.json.gz, written by model/effects/run_fx_model.py) and
records the Delay instance's ext-mem counters at the last checkpoint, on ONE
stated basis: per sample (24 reads + 2 writes) and per 32-sample block (768
reads + 64 writes), checked against the counter-implied block count.

Writes reports/sxt-023/artifacts/
ext_mem_traffic-rerun-issue16.json. The PR #44 ext_mem_traffic.json (cited
by the sha256-pinned EVIDENCE.md row A6, wording owned by #367) is kept
unedited. Model-side counters only; no RTL or hardware measurement.
"""
import gzip
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from model.effects.delay.delay_model import BLOCK, DelayModel  # noqa: E402

SLUG = "dexie"
ART = os.path.join(REPO, "reports", "sxt-023", "artifacts")
OUT = os.path.join(ART, "ext_mem_traffic-rerun-issue16.json")


def main():
    with gzip.open(os.path.join(ART, f"model_trace_{SLUG}.json.gz"), "rt") as f:
        t = json.load(f)
    last = t["blocks"][-1]
    delays = [i for i in last["instances"] if i["kind"] == "delay"]
    n_blocks = t["n_blocks_total"]
    if last["b"] != n_blocks - 1:
        raise ValueError("last trace block is not the final block")
    reads_per_sample = DelayModel.TAP_READS * 2
    writes_per_sample = 2
    exp_r = reads_per_sample * BLOCK * n_blocks
    exp_w = writes_per_sample * BLOCK * n_blocks
    insts = []
    ok = True
    for d in delays:
        good = d["ext_reads"] == exp_r and d["ext_writes"] == exp_w
        ok &= good
        insts.append({"name": d["name"], "ext_reads": d["ext_reads"],
                      "ext_writes": d["ext_writes"], "matches_basis": good})
    rec = {
        "schema_version": 1,
        "interface": "rtl/effects/delay/ext_mem_if.md",
        "preset": SLUG,
        "source_trace": f"reports/sxt-023/artifacts/model_trace_{SLUG}.json.gz (revised tree, issue #16)",
        "blocks_counted": n_blocks,
        "blocks_note": f"settle {t['settle_blocks']} + render {n_blocks - t['settle_blocks']} "
                       f"blocks of {BLOCK} samples (render_frames {t['render_frames']} padded)",
        "basis": {
            "per_sample_per_instance": {"line_reads": reads_per_sample,
                                        "line_writes": writes_per_sample},
            "per_block_per_instance": {"line_reads": reads_per_sample * BLOCK,
                                       "line_writes": writes_per_sample * BLOCK},
        },
        "expected_counters": {"ext_reads": exp_r, "ext_writes": exp_w},
        "measured_model_counters_at_last_checkpoint": insts,
        "supersedes_for_revised_tree": "ext_mem_traffic.json (PR #44, 8,790-block window; kept unedited, wording tracked by #367)",
        "scope": "model-side counters only; no RTL, latency, or hardware measurement",
        "verdict": "PASS" if ok and insts else "FAIL",
    }
    with open(OUT, "w") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    print(json.dumps(rec))
    return 0 if rec["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
