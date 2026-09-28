#!/usr/bin/env python3
"""SXT-026 RTL-vs-model exactness harness (issue #19).

DECLARED SCOPE BOUNDARY (issue #176). This harness compares the model and the
RTL **up to and including the 2x-rate (96 kHz) oscillator output block**. It
does NOT read the model trace's 48 kHz `mono_block` samples, because
`rtl/oscillators/wavetable/` implements no post-oscillator stage: the model's
`wt_model.Slice` tail (o2 level, VCA x AEG gain ramp, scene out, +/-8 clip,
`HalfbandD2` decimation, master, clips) has no RTL counterpart in this leaf.
A PASS here therefore establishes `rtl_vs_model: PASS` for the oscillator and
its declared external-traffic accounting ONLY -- never for the 48 kHz output.
The emitted summary carries this boundary in its `scope` field so every
transcript states it. The 48 kHz scene path IS covered by RTL on the SXT-022
voice leaf (`rtl/voice/tb_voice.sv`), against that leaf's own model; extending
coverage to this leaf's 48 kHz output is an SXT-017 contract question (#180),
not a gap this harness may paper over. Measurement of the per-slice vs per-scene
difference: `reports/sxt-026/artifacts/decimation-stage-per-slice-vs-per-scene.json`.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * per-voice impulse-engine state at every declared checkpoint
    (oscstate, table state, last_level, mipmap),
  * morph machinery state (tableid, tableipol, last_tableipol, l_shape),
  * the hpf/output stage (osc_out, bufpos, hpf_prev),
  * every 64-sample oscillator output block,
  * external-asset traffic: core reads_words vs the model's declared
    2-words-per-impulse accounting, fill_words vs frame-fills.

Also verifies the RTL negative-control mutant (NC-B RTL: -DWAVETABLE_MUTANT_MIP)
FAILS the same comparison (--mutant).

SIMULATOR-LEVEL FAILURES ARE NOT COMPARISON DISAGREEMENTS (issues #182, #188,
#194). A run that never produced trustworthy traces must say so. Five
mechanisms are recognized and recorded in the summary's `sim_fails` list, and
every one of them sets `comparison: NOT_RUN` (the comparison and the traffic
reconciliation are skipped entirely) so a transcript can never read "the RTL
disagreed with the model" when the truth is "the stimulus never loaded":

  1. a declared input missing before the simulator is invoked at all
     (`model_trace.json` plus the five `rtl/*.hex` files of STIMULUS). This is
     asserted up front deliberately (#188 checkbox 3): it is cheaper and more
     direct than pattern-matching simulator output, and it names the exact
     file. It does not *replace* mechanism 2 -- a file can be present and
     still unreadable, and iverilog resolves the paths itself -- so both are
     kept.
  2. `$readmemh: Unable to open ...` on the simulation's STDOUT. Icarus
     reports a stimulus open failure there and still exits 0 (measured on
     Icarus 11, 12.0 and 13.0), so neither the exit status nor stderr sees it;
     vvp's stdout is parsed, and a tail of it retained, exactly the way its
     stderr already was.
  3. a non-zero `vvp` exit (the mechanism #182/#190 fixed).
  4. `iverilog` failing to compile (CalledProcessError) or `vvp` exceeding
     --timeout (TimeoutExpired) -- caught, so the harness still writes a
     verdict with a reason instead of dying by traceback with no verdict at
     all.
  5. a declared stimulus file that IS present and opens, but is TRUNCATED --
     fewer hex words than the model wrote (#194). This is a CONTENT check
     against the model side's own declaration (`rtl/stimulus_index.json`,
     written by `run_model.py --rtl` beside the files), NOT a matcher on the
     simulator's output, and the measurement that forced that choice is
     recorded in `reports/tooling-wt-harness-stimulus-load/`: a genuinely
     PASSING pinned-tree run emits `$readmemh(<file>): Not enough words in
     the file for the requested range [...]` for ALL FIVE memories, because
     the testbench declares them generously (`ctrl_mem[0:262143]`,
     `wt_mem[0:131071]`, `init_mem[0:63]`, sinc `[0:6143]`) and a real run
     never fills them. No stdout matcher on that warning can discriminate a
     truncated file from a healthy one; a content check can, and it names the
     file. When the run dir carries no `rtl/stimulus_index.json` (a run dir
     produced by tooling older than #194), this check is reported as NOT_RUN
     in the summary's `stimulus_lengths` field rather than failing closed --
     reporting a healthy run as failed is the one outcome worse than the lost
     reason (#188), and NOT_RUN is never a pass.

The verdict vocabulary is unchanged (PASS/FAIL): every one of these fails
closed as FAIL, with `comparison: NOT_RUN` carrying the distinction between
"the comparison ran and disagreed" and "the comparison never ran".

Usage:
  python3 tools/compare_wt_rtl_model.py --run-dir DIR [--tb TB] [--out JSON]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RTLDIR = os.path.join(REPO, "rtl", "oscillators", "wavetable")

# Machine-readable restatement of the module docstring's scope boundary
# (issue #176): every emitted transcript carries it, so a PASS can never be
# read as covering the 48 kHz output.
SCOPE = {
    "covers": ("model-vs-RTL integer equality up to and including the 2x-rate "
               "(96 kHz) oscillator output block, plus the declared "
               "external-asset traffic accounting"),
    "does_not_cover": ("the 48 kHz output: the model's post-oscillator stage "
                       "(o2 level, VCA x AEG gain ramp, scene out, +/-8 clip, "
                       "HalfbandD2 decimation, master, clips) has NO RTL "
                       "counterpart in rtl/oscillators/wavetable/, so the "
                       "model trace's mono_block samples are not compared"),
    "declared_in": ("model/oscillators/wavetable/README.md (declared "
                    "deviations 7-8), reports/sxt-026/EVIDENCE.md section 2"),
    "issue": 176,
}

# The hex stimulus the testbench $readmemh's, as (plusarg, path relative to the
# run dir) pairs. ONE list feeds both vvp's command line and the pre-flight
# existence check, so the check can never drift from what is actually passed.
STIMULUS = (
    ("INIT", "rtl/init.hex"),
    ("CTRL", "rtl/ctrl.hex"),
    ("WT_TABLE", "rtl/wt_table.hex"),
    ("SINC_MAIN", "rtl/sinc_main.hex"),
    ("SINC_DERIV", "rtl/sinc_deriv.hex"),
)

# Declared inputs a run cannot proceed without: the model side of the
# comparison plus the stimulus above.
REQUIRED_INPUTS = ("model_trace.json",) + tuple(rel for _, rel in STIMULUS)

# The model side's own declaration of how long each stimulus file is, written
# next to the files by `run_model.py --rtl`. Deliberately NOT in
# REQUIRED_INPUTS: its absence is reported as NOT_RUN coverage (see mechanism
# 5 in the module docstring), never as a failure.
STIMULUS_INDEX = "rtl/stimulus_index.json"


def missing_inputs(run_dir):
    """Declared inputs absent from `run_dir`, in declaration order."""
    return [rel for rel in REQUIRED_INPUTS
            if not os.path.exists(os.path.join(run_dir, rel))]


def count_hex_words(path):
    """Hex words in a `$readmemh` file, counted the way Icarus loads them.

    `run_model.write_hex` emits one 8-digit word per line, but the count is
    tokenized rather than line-counted so a hand-edited file (trailing blank
    lines, several words per line, an `@address` directive, a `//` comment)
    is counted by content and not by layout. Only tokens that would become
    memory words are counted.
    """
    n = 0
    with open(path) as f:
        for line in f:
            for tok in line.split("//")[0].split():
                if not tok.startswith("@"):
                    n += 1
    return n


def check_stimulus_lengths(run_dir):
    """Every stimulus file's word count vs the model's declared length.

    Mechanism 5 (#194): a file that opens but is SHORT. Returns
    `(report, fails)`; `report` always states coverage explicitly, so a run
    whose lengths were never checked can never read as one whose lengths
    checked out:

      status PASS    every STIMULUS file was declared and matches
      status FAIL    at least one file disagrees with its declaration
      status NOT_RUN no usable `rtl/stimulus_index.json`, or it declares only
                     some of the files -- no length claim is made for the
                     undeclared ones (`declared: null` in `words`)

    Agreement is reported separately from coverage: `words` carries the
    measured and declared count for every file either way.
    """
    report = {"status": "NOT_RUN", "declared_by": STIMULUS_INDEX,
              "reason": "", "words": {}}
    idx_path = os.path.join(run_dir, STIMULUS_INDEX)
    declared = {}
    if not os.path.exists(idx_path):
        report["reason"] = (
            "%s is absent from the run dir, so no stimulus length was "
            "declared by the model side and no truncation claim is made "
            "(a run dir produced by tooling older than issue #194); this "
            "is NOT a pass" % STIMULUS_INDEX)
    else:
        try:
            with open(idx_path) as f:
                declared = json.load(f)["files"]
            if not isinstance(declared, dict):
                raise ValueError("'files' is not an object")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            declared = {}
            report["reason"] = (
                "%s could not be read as a stimulus index (%s), so no "
                "truncation claim is made; this is NOT a pass"
                % (STIMULUS_INDEX, exc))

    fails = []
    undeclared = []
    for _, rel in STIMULUS:
        want = declared.get(rel)
        try:
            got = count_hex_words(os.path.join(run_dir, rel))
        except OSError as exc:
            got = None
            fails.append("stimulus file %s could not be read: %s"
                         % (rel, exc))
        report["words"][rel] = {"declared": want, "actual": got}
        if want is None:
            undeclared.append(rel)
            continue
        if got is None or got == want:
            continue
        how = "TRUNCATED" if got < want else "LONGER THAN DECLARED"
        fails.append(
            "%s stimulus file: %s holds %d hex words but the model declared "
            "%d in %s. The file opened, so $readmemh loaded what was there "
            "and Icarus's `Not enough words in the file for the requested "
            "range` WARNING cannot report it -- a PASSING run emits that "
            "warning for every memory, because the testbench declares them "
            "far larger than any real stimulus (#194)."
            % (how, rel, got, want, STIMULUS_INDEX))

    if fails:
        report["status"] = "FAIL"
    elif undeclared:
        if not report["reason"]:
            report["reason"] = (
                "%s declares no length for %s, so no truncation claim is "
                "made for %s; this is NOT a pass"
                % (STIMULUS_INDEX, ", ".join(undeclared),
                   "them" if len(undeclared) > 1 else "it"))
    else:
        report["status"] = "PASS"
        report["reason"] = ("all %d stimulus files match the length the "
                            "model declared" % len(STIMULUS))
    return report, fails


def scan_stdout_for_load_failures(stdout, limit=10):
    """Stimulus-load failures Icarus reports on STDOUT while exiting 0.

    Matched NARROWLY, on both the `$readmem` token and `Unable to open`, and
    deliberately NOT on a bare `ERROR:` prefix. The testbench's own runtime
    diagnostics are `DBG `, `WARNING:`, `UNDERRUN:`, `WATCHDOG:` and
    `TB done:` lines; none of them can match this pattern, so the matcher
    cannot turn a genuinely passing exactness run into a FAIL. Reporting a run
    that did not fail as failed would be a worse defect than the lost reason
    this matcher exists to recover (issue #188).
    """
    hits = []
    for line in _as_text(stdout).splitlines():
        line = line.strip()
        if "$readmem" in line and "Unable to open" in line:
            hits.append(line)
            if len(hits) >= limit:
                break
    return hits


def _as_text(stream):
    """subprocess streams: str, bytes or None (TimeoutExpired) -> str."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", "replace")
    return stream


def parse_traces(run_dir, slots=4):
    """Parse tb_trace.s<k> files: T (per-voice), S (shared), O (oscout)."""
    t, sh, o = {}, {}, {}
    for s in range(slots):
        p = os.path.join(run_dir, "tb_trace.s%d" % s)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                parts = line.split()
                if parts[0] == "T":
                    b, slot, v = int(parts[1]), int(parts[2]), int(parts[3])
                    vals = [int(x) for x in parts[4:]]
                    t[(b, slot, v)] = vals
                elif parts[0] == "S":
                    b, slot = int(parts[1]), int(parts[2])
                    vals = [int(x) for x in parts[3:]]
                    sh[(b, slot)] = vals
                elif parts[0] == "O":
                    b, slot = int(parts[1]), int(parts[2])
                    o.setdefault((b, slot), []).extend(
                        int(x) for x in parts[3:])
    return t, sh, o


def to_signed32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x >= (1 << 31) else x


def compare(model_trace, rtl, max_blocks=None):
    t, sh, o = rtl
    fails = []
    checked = {"voices": 0, "fields": 0, "oscout": 0, "shared": 0}
    for blk in model_trace["blocks"]:
        b = blk["b"]
        if max_blocks is not None and b >= max_blocks:
            break
        for rec in blk["voices"]:
            if "after" not in rec:
                continue
            slot = rec["slot"]
            a = rec["after"]
            n = len(a["oscstate"])
            for v in range(n):
                want = [a["oscstate"][v], a["osc_state"][v],
                        to_signed32(a["last_level"][v]), a["mipmap"][v]]
                got = t.get((b, slot, v))
                checked["voices"] += 1
                if got is None:
                    fails.append("block %d slot %d voice %d: missing T line"
                                 % (b, slot, v))
                    continue
                for fi, (wv, gv) in enumerate(zip(want, got)):
                    checked["fields"] += 1
                    if wv != gv:
                        fails.append(
                            "block %d slot %d voice %d field %d: "
                            "model=%d rtl=%d" % (b, slot, v, fi, wv, gv))
            want_s = [a["tableid"], to_signed32(a["tableipol"]),
                      to_signed32(a["last_tableipol"]),
                      to_signed32(a["l_shape"]),
                      to_signed32(a["osc_out"]), a["bufpos"],
                      to_signed32(a["hpf_prev"])]
            got_s = sh.get((b, slot))
            checked["shared"] += 1
            if got_s is None:
                fails.append("block %d slot %d: missing S line" % (b, slot))
            else:
                for fi, (wv, gv) in enumerate(zip(want_s, got_s)):
                    checked["fields"] += 1
                    if wv != gv:
                        fails.append("block %d slot %d sfield %d: "
                                     "model=%d rtl=%d" % (b, slot, fi,
                                                          wv, gv))
            om = rec.get("oscout_block")
            ot = o.get((b, slot))
            if om is not None:
                if ot is None or len(ot) != len(om):
                    fails.append("block %d slot %d: missing/short O line"
                                 % (b, slot))
                    continue
                for k, (wv, gv) in enumerate(zip(om, ot)):
                    checked["oscout"] += 1
                    if to_signed32(wv) != gv:
                        fails.append("block %d slot %d osout[%d]: "
                                     "model=%d rtl=%d" % (b, slot, k,
                                                          wv, gv))
            if len(fails) > 30:
                return checked, fails
    return checked, fails


def compile_and_run_sim(run_dir, model_trace, *, mutant, reverb_bg,
                        max_blocks, timeout):
    """Compile the testbench and run it; return (sim_fails, stdout_tail).

    Recognizes mechanisms 2-4 of the module docstring. Never raises on a
    simulator-level failure: every one is returned as a `sim_fails` string so
    the caller can still write a verdict that states the reason.
    """
    sim_fails = []
    stdout_tail = ""
    vvp = os.path.join(run_dir, "tb_wt.vvp")
    build = ["iverilog", "-g2012", "-o", vvp, "-s", "tb_wavetable"]
    if mutant:
        build.append("-DWAVETABLE_MUTANT_MIP")
    build += [os.path.join(RTLDIR, "tb_wavetable.sv"),
              os.path.join(RTLDIR, "wavetable_core.sv")]
    # ---- mechanism 4a: a failed/unrunnable compile is a recorded reason,
    # not a traceback that leaves no verdict JSON written at all.
    try:
        subprocess.run(build, check=True, cwd=run_dir)
    except subprocess.CalledProcessError as exc:
        # The compile's streams are inherited (so its diagnostics stay visible
        # live), which means exc.stderr is None here; say so rather than
        # printing an empty field that reads like "no reason given".
        detail = (_as_text(exc.stderr)[-500:]
                  or "(compiler diagnostics went to this harness's own "
                     "stderr; the compile step is not captured)")
        return (["iverilog compile failed rc=%s: %s"
                 % (exc.returncode, detail)], "")
    except OSError as exc:
        return (["iverilog could not be executed: %s" % exc], "")

    cmd = ["vvp", vvp, "+BLOCKS=%d" % max_blocks,
           "+N_UNISON=%d" % model_trace["unison"],
           "+WAVE_SIZE=%d" % model_trace.get("wave_size", 1024),
           "+N_TABLES=%d" % model_trace["n_tables"],
           "+NOINTERP=%d" % model_trace["nointerp"],
           "+LEGACY=%d" % model_trace["legacy"],
           "+TRACE=%s/tb_trace" % run_dir,
           "+TRAFFIC=%s/tb_traffic.txt" % run_dir,
           "+MUT=%d" % (1 if mutant else 0),
           "+REVERB_BG=%d" % (1 if reverb_bg else 0)]
    cmd += ["+%s=%s" % (plusarg, rel) for plusarg, rel in STIMULUS]
    # ---- mechanism 4b: a timeout kill is a recorded reason too ----
    try:
        run = subprocess.run(cmd, cwd=run_dir, capture_output=True,
                             text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout_tail = _as_text(exc.stdout)[-2000:]
        return (["vvp exceeded the %gs timeout and was killed (the "
                 "simulation never completed, so no trace it left can be "
                 "trusted) stdout=%s" % (timeout, stdout_tail[-500:])],
                stdout_tail)
    except OSError as exc:
        return (["vvp could not be executed: %s" % exc], "")

    # ---- mechanism 3: non-zero exit (the #182/#190 mechanism) ----
    if run.returncode != 0:
        sim_fails.append("vvp exited rc=%d stderr=%s"
                         % (run.returncode, _as_text(run.stderr)[-500:]))
    # ---- mechanism 2: $readmemh open failure on STDOUT, with rc=0 ----
    for line in scan_stdout_for_load_failures(run.stdout):
        sim_fails.append("vvp rc=%d but a stimulus file never loaded: %s"
                         % (run.returncode, line))
    if sim_fails:
        stdout_tail = _as_text(run.stdout)[-2000:]
    return sim_fails, stdout_tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="run dir with model_trace.json + rtl/ stimulus")
    ap.add_argument("--out", help="write verdict JSON here")
    ap.add_argument("--mutant", action="store_true",
                    help="build the committed mip-threshold mutant; "
                         "the comparison must FAIL")
    ap.add_argument("--reverb-bg", action="store_true",
                    help="enable the concurrent Reverb1 background bus "
                         "traffic (SXT-016 pattern, 34 words/frame); the "
                         "no-underrun gate applies to the combined load")
    ap.add_argument("--max-blocks", type=int, default=130)
    ap.add_argument("--timeout", type=float, default=3600,
                    help="seconds before the vvp run is killed; an expiry is "
                         "recorded as a simulator-level failure, not raised")
    args = ap.parse_args()

    # Simulator-level failures are collected separately and then MERGED into
    # the comparison's own fail list, so a dead simulator reports its own
    # reason in the verdict instead of being lost, raising, or masquerading as
    # a comparison disagreement.
    fails = []
    sim_fails = []
    cmp_fails = []
    checked = {"voices": 0, "fields": 0, "oscout": 0, "shared": 0}
    sim_stdout_tail = ""
    model_trace = None

    # ---- mechanism 1: declared inputs, checked BEFORE the simulator runs ----
    for rel in missing_inputs(args.run_dir):
        sim_fails.append(
            "missing declared input: %s (absent from the run dir; the "
            "testbench $readmemh's the rtl/*.hex stimulus and Icarus reports "
            "an open failure on stdout while still exiting 0, so this is "
            "asserted before the simulator is invoked)" % rel)

    # The existence check above is deliberately only that: a declared input
    # that is PRESENT but malformed (not valid JSON) or unopenable (mode 000,
    # a directory, an I/O error) used to raise straight out of main() here --
    # traceback, no verdict JSON, no recorded reason (#197). It is recorded the
    # same way every other simulator-level failure is, and the simulator is not
    # invoked on a trace that never parsed.

    # ---- mechanism 5: stimulus CONTENT (length) vs the model's own
    # declaration, also before the simulator runs. Only meaningful once the
    # files are known to exist, so it follows mechanism 1.
    stimulus_lengths = {"status": "NOT_RUN", "declared_by": STIMULUS_INDEX,
                        "reason": "not reached: a declared input was missing",
                        "words": {}}
    if not sim_fails:
        stimulus_lengths, short_fails = check_stimulus_lengths(args.run_dir)
        sim_fails += short_fails

    if not sim_fails:
        try:
            with open(os.path.join(args.run_dir, "model_trace.json")) as f:
                model_trace = json.load(f)
        # OSError covers the open (mode 000, a directory, an I/O error);
        # ValueError covers the decode, and is used rather than
        # json.JSONDecodeError alone because UnicodeDecodeError -- raised by a
        # non-UTF-8/binary file before the JSON parser ever sees it -- is a
        # sibling ValueError subclass, not a JSONDecodeError.
        except (OSError, ValueError) as exc:
            model_trace = None
            sim_fails.append(
                "declared input present but unreadable: model_trace.json "
                "(%s: %s; the existence pre-flight above cannot tell a "
                "malformed or unopenable trace from a usable one, so this is "
                "asserted before the simulator is invoked)"
                % (type(exc).__name__, exc))
        else:
            sim_fails, sim_stdout_tail = compile_and_run_sim(
                args.run_dir, model_trace, mutant=args.mutant,
                reverb_bg=args.reverb_bg, max_blocks=args.max_blocks,
                timeout=args.timeout)

    fails += sim_fails

    # A simulator-level failure makes the comparison NOT_RUN: comparing model
    # state against traces from a run that did not happen (or is absent, or
    # stale from an earlier run) is what produced the "wall of mismatches"
    # misreport this path exists to prevent (#188).
    traffic = {}
    model_traffic = None
    traffic_fails = []
    if not sim_fails:
        rtl = parse_traces(args.run_dir)
        checked, cmp_fails = compare(model_trace, rtl, args.max_blocks)
        fails += cmp_fails

        # traffic reconciliation (counts from the core, dumped by the TB)
        tp = os.path.join(args.run_dir, "tb_traffic.txt")
        if os.path.exists(tp):
            with open(tp) as f:
                for line in f:
                    k, v = line.split()
                    traffic[k] = int(v)

        tp = os.path.join(args.run_dir, "traffic.json")
        if os.path.exists(tp):
            with open(tp) as f:
                model_traffic = json.load(f)["totals"]

        # ---- traffic reconciliation (exact; any mismatch = FAIL) ----
        if model_traffic is not None:
            reads = traffic.get("core_reads_words", 0)
            fills = traffic.get("core_fill_words", 0)
            want = model_traffic["ext_read_words"]
            if reads + fills != want:
                traffic_fails.append(
                    "ext words: rtl reads+fills %d+%d != model %d"
                    % (reads, fills, want))
        # no-underrun gate: the sustained/concurrent check must hold
        underruns = traffic.get("underrun_blocks", 0)
        if underruns:
            traffic_fails.append("%d underrun block(s)" % underruns)

    verdict = "PASS" if not (fails or traffic_fails) else "FAIL"
    if sim_fails:
        comparison = "NOT_RUN"
    else:
        comparison = "FAIL" if (cmp_fails or traffic_fails) else "PASS"
    summary = {
        "verdict": verdict,
        "comparison": comparison,
        "scope": SCOPE,
        "mutant": args.mutant,
        "reverb_bg": bool(args.reverb_bg),
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
        "sim_fails": sim_fails,
        "sim_stdout_tail": sim_stdout_tail,
        "stimulus_lengths": stimulus_lengths,
        "traffic_fails": traffic_fails,
        "traffic_tb": traffic,
        "traffic_model": model_traffic,
    }
    print(json.dumps(summary, indent=1))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=1)
            f.write("\n")
    if args.mutant:
        # The mutant must fail the COMPARISON. A simulator that never ran
        # demonstrates nothing about the mutant, so a simulator-level failure
        # is NOT_RUN for this control and must exit non-zero.
        return 0 if cmp_fails and not sim_fails else 1
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
