"""SXT-016 runner: regenerate every probe output deterministically.

    python3 probes/run_all.py

Writes (byte-identical on re-run; no timestamps):
  reports/sxt-016/probes/*.json      validated probe records
  reports/sxt-016/probes/SUMMARY.md  summary tables
  reports/sxt-016/negative-control/nc-underspecified-record.json
  reports/sxt-016/worked-bundles.json

Every emitted record passes probes/validate.py or the run aborts.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probes import (negative_control, probe_filter, probe_fx_delay,
                    probe_fx_eq, probe_fx_reverb1, probe_osc, probe_scheduler,
                    worked_bundle)
from probes.common import CLOCK_CANDIDATES_HZ

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBES_OUT = os.path.join(ROOT, "reports", "sxt-016", "probes")


def summary_tables():
    lines = []
    lines.append("# SXT-016 probe summary (machine-generated; deterministic)")
    lines.append("")
    lines.append("All values are ESTIMATES under named assumptions (each "
                 "record embeds them). No gf180mcu synthesis/PnR/signoff "
                 "has been run. clocks: "
                 + ", ".join("%d MHz" % (c // 1_000_000)
                             for c in CLOCK_CANDIDATES_HZ)
                 + " x Fs = 48 kHz; gross cycles/frame = "
                 + ", ".join(str(c // FS)
                             for c, FS in [(c, 48000)
                                           for c in CLOCK_CANDIDATES_HZ])
                 + ".")
    lines.append("")

    # ---- per-record table -------------------------------------------------
    lines.append("## Records")
    lines.append("")
    lines.append("| record | kernel | xMult | phase | cyc/sample | cyc/frame "
                 "| state RAM bits | ext B/frame | replaces (SXT-015) |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---|")
    recs = []
    for fn in sorted(os.listdir(PROBES_OUT)):
        if fn.endswith(".json"):
            recs.append((fn, json.load(open(os.path.join(PROBES_OUT, fn)))))
    for fn, r in recs:
        wl = r["word_lengths"]
        lines.append(
            "| `%s` | %s | %s | %s | %s | %d | %d | %d | %s |" % (
                fn.replace(".json", ""), r["kernel"], wl.get("multiplier"),
                wl.get("phase_bits", "-"),
                r.get("cycles_per_sample", "-") if
                r.get("cycles_per_sample") is not None else "-",
                r["cycles_per_frame"], r["state_ram_bits"],
                r["ext_bytes_per_frame"],
                str(r["sxt015_replacement"].get("replaces"))))
    lines.append("")

    # ---- worked bundles ---------------------------------------------------
    doc = worked_bundle.run()
    lines.append("## Worked bundles (Pareto-style; alternatives uncombined "
                 "- no single score)")
    lines.append("")
    lines.append(worked_bundle.markdown_table(doc))
    lines.append("")
    lines.append("Closure columns combine the plan-section-5 formula "
                 "(gross F/Fs, minus 20% reserve, minus transfer 8 and "
                 "contention 990 cyc/frame) with the bundle's total "
                 "cycles/frame. Percentage is utilization of gross. Rows "
                 "flagged with placeholder components carry SXT-015 "
                 "placeholder-v0 values for uncovered classes (see "
                 "`worked-bundles.json` `flags`); `covered_worst_synth` "
                 "has none.")
    lines.append("")
    lines.append("External-bandwidth fit per bundle (bytes/frame x 48k vs "
                 "E-model sustained): see `closure_at_clocks` in "
                 "`worked-bundles.json`.")
    lines.append("")
    lines.append("## Headline findings (estimates, not measurements)")
    lines.append("")
    lines.append("1. Under scalar single-lane arithmetic (A-SCHED-1) NO "
                 "worked bundle closes at any candidate clock: the "
                 "worst-pitch-corner BLIT oscillator cost dominates "
                 "(classic 175.8-352.7 cyc/sample/instance, wavetable "
                 "139.9-262.3). Closure therefore requires parallel lanes, "
                 "reduced unison (an adaptation), cheaper oscillator "
                 "candidates (adaptations), or higher clocks - SXT-017 "
                 "tradeoffs, quantified in the bundles.")
    lines.append("2. Phase-word width moves state RAM, not cycles "
                 "(24-bit audio muls dominate via the MAC decomposition): "
                 "16 vs 32-bit phase costs the same cycles/instance and "
                 "differs by 32 state bits/instance (Classic).")
    lines.append("3. Delay physical external traffic is model-dependent: "
                 "24 words/frame naive vs ~4 words/frame with the named "
                 "sliding-window cache (A-EXT-BUF); SXT-015's 6r+2w was a "
                 "logical count. Reverb1's 34 scattered words/frame are "
                 "latency-bound, not bandwidth-bound (990 cyc/frame "
                 "contention at E1).")
    lines.append("4. Reverb1 fixed-point guard band: at max decay the "
                 "zero-latency loop spectral radius approaches 1 "
                 "(rho=0.99995), i.e. ~15 guard bits for quantization "
                 "noise; internal reverb words need 24+15 bits or a "
                 "shorter max-decay cap (SXT-024 decision input).")
    lines.append("5. Scheduler: 91 cyc/event (worst 8 coincident events "
                 "re-derived from fixtures, matching SXT-015), 90 "
                 "cyc/frame fixed control - small vs voice cost.")
    lines.append("")
    lines.append("## Negative control")
    lines.append("")
    lines.append("`negative-control/nc-underspecified-record.json`: a "
                 "record with unstated clock/memory/word-length "
                 "assumptions is REFUSED by validate/write - the "
                 "mechanical exclusion SXT-017 relies on.")
    return "\n".join(lines) + "\n"


def main():
    for m in (probe_osc, probe_filter, probe_fx_delay, probe_fx_eq,
              probe_fx_reverb1, probe_scheduler):
        m.run(PROBES_OUT)
    negative_control.run()
    text = summary_tables()
    with open(os.path.join(PROBES_OUT, "SUMMARY.md"), "w") as f:
        f.write(text)
    print("wrote", len(os.listdir(PROBES_OUT)), "files in", PROBES_OUT)


if __name__ == "__main__":
    main()
