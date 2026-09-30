#!/usr/bin/env python3
"""SXT-036 (#70) PARAMETER CORNERS -- ORACLE-INDEPENDENT.

Issue #70 lists three declared input sets under "Fixtures and oracle": carrier
presets, sequences, and

    "Parameter corners: the leaf freezes the observed normalized parameter
     ranges of its carriers plus the engine-declared ranges at the pin."

`model/voice/audit_vel_carriers.py` accounted for the carriers and
`tools/vel_declared_coverage.py` for the sequences. This driver accounts for
the third set, from committed artifacts only -- no pinned oracle, no Surge
checkout:

 1. DERIVED RANGES. `corpus/normalized/graphs.jsonl` (sha256 pinned by #70)
    stores each modulation route twice: the destination-unit depth (`depth_raw`)
    and the normalized depth (`depth_normalized`). Their ratio is the
    destination parameter's full extent, so the extent of every destination in
    the frozen SXT-036 class is DERIVED by agreement across hundreds of
    independent corpus rows, and the observed normalized depth range of
    `ms_velocity` / `ms_releasevelocity` is read off the same file. Fail-closed
    (exit 2) on a sha256 mismatch, a missing destination, or rows that disagree
    about an extent by more than --extent-tol.

 2. EXHAUSTIVE SOURCE-WORD DOMAIN. The velocity quantizer is a 128-entry table;
    the corner sweep would only touch six entries, so the whole domain is
    checked instead: the `vel_rom` function is lifted verbatim out of
    `rtl/voice/tb_vel.sv` into a generated enumerating testbench, and all 128
    RTL words are compared for INTEGER EQUALITY against the frozen model's
    `vel_q()`. The `rom-floor` mutation (same anchor
    `tools/vel_negative_controls.py` uses) must make that exhaustive check FAIL.

 3. CORNER SWEEP. Each corner is a declared route table over every (source,
    destination) pair of the frozen class, rendered on the corner stimulus
    `model/voice/sequences/sxt036-vel-corners-v1.json` (whose note-on and
    note-off velocities are the MIDI corners of both sources, on overlapping
    voices). Every corner is checked RTL-vs-model with integer equality
    (`tools/compare_vel_rtl_model.py`, plus `tools/compare_rtl_model.py` on the
    unchanged datapath), and the per-destination route-sum magnitudes are
    recorded against the 32-bit checkpoint word.

 4. CONTROLS (each must demonstrably fail the check it targets).
    * `rounding-tie-half`: a depth of exactly 0.5 makes `depth * source` land
      exactly on the .5 boundary for every ODD source word, in both signs. The
      driver asserts the ties really occur, then re-runs the `round-trunc` RTL
      mutant on that corner: it must FAIL. A corner set that cannot distinguish
      round-half-up from truncation would not be freezing the rounding rule.
    * `over-range-accumulator` (deliberately OUTSIDE the derived ranges): the
      per-destination checkpoint word is 32-bit in the RTL and unbounded in the
      Python model, so a depth far above the derived extent must FAIL. This
      documents where the frozen checkpoint definition stops holding, and the
      headroom the declared corners keep from it.

WHAT THIS IS NOT (do not upgrade these claims): it establishes claim (1) only
-- RTL == frozen model, exactly, in iverilog simulation, at the declared
corners. The derived extents and the observed depth ranges come from the corpus
pipeline, NOT from a live engine readback, so they are FALSIFIABLE PREDICTIONS
for the oracle-host backfill (#232), never reference values. Acceptance items 2
(model-vs-pinned-engine budgets) and 5 (reference-budget negative controls) of
#70 remain NOT_RUN -- pinned oracle unavailable on dispatch host (#96). No
fidelity, sound-quality, synthesis or hardware claim. Supported-preset delta 0.

Exit codes: 0 = every declared corner exact and every control fired as
required; 1 = a corner that must be exact was not, or a control did not fire;
2 = refusal (fail-closed input check).

Usage:
  python3 tools/vel_param_corners.py --artifacts reports/SXT-036/artifacts
  python3 tools/vel_param_corners.py --artifacts DIR --skip-datapath
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, REPO)
import voice_model as vm                      # noqa: E402
import vel_negative_controls as vnc           # noqa: E402  (mutation anchors)
from refusal import Refuse  # noqa: E402

RUNNER = os.path.join(REPO, "model", "voice", "run_vel_model.py")
CMP_VEL = os.path.join(REPO, "tools", "compare_vel_rtl_model.py")
CMP_VOICE = os.path.join(REPO, "tools", "compare_rtl_model.py")
TB_VEL = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")

# sha256 pinned in the body of issue #70 ("Inputs / outputs / state")
GRAPHS_SHA256 = ("c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df"
                 "39204715")
PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
SEQ = "sxt036-vel-corners-v1"

FQ = vm.FQ                                   # 21
ONE = vm.ONE                                 # 2^21
QMAX = (1 << 31) - 1
QMIN = -(1 << 31)

SOURCES = {1: "ms_velocity", 30: "ms_releasevelocity"}
FROZEN_CLASS = {308: "A Filter 1 Cutoff", 309: "A Filter 1 Resonance",
                310: "A Filter 1 FEG Mod Amount", 298: "A VCA Gain"}
DEST_ORDER = [308, 309, 310, 298]            # issue/README order
SUM_ORDER = ["cutoff", "reso", "fegmod", "vca"]
SUM_INDEX = {308: 0, 309: 1, 310: 2, 298: 3}

ROM_TB_TEMPLATE = """// GENERATED by tools/vel_param_corners.py -- not a frozen
// source file. The vel_rom function below is lifted VERBATIM out of
// rtl/voice/tb_vel.sv (or a mutant of it) so that this exhaustive enumeration
// tests that file's own integer expression rather than a second copy of it.
`timescale 1ns/1ps
module tb_vel_rom;
  localparam int FQ = 21;
  int unsigned qmul_count = 0;   // unused here; keeps the lifted text compiling
  integer m, fd;
{rom}
  initial begin
    fd = $fopen("tb_vel_rom_trace.txt", "w");
    for (m = 0; m < 128; m++) $fwrite(fd, "R %0d %0d\\n", m, vel_rom(m));
    $fclose(fd);
    $display("DONE vel-rom-entries=128");
    $finish;
  end
endmodule
"""


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def vel_q(midi):
    """The frozen model quantizer (model/voice/run_vel_model.py)."""
    return (int(midi) * (1 << (FQ + 1)) + 127) // 254


# --------------------------------------------------------------- 1. ranges ---
def derive_ranges(tol):
    """Destination extents and observed source depth ranges, from graphs.jsonl.

    md row layout (corpus/normalized/schema.json):
      [modsource_id, scene, index, dest_id, dest_name, depth_raw, depth_norm]
    """
    got = sha256(GRAPHS)
    if got != GRAPHS_SHA256:
        raise Refuse(f"graphs.jsonl sha256 {got} != pinned {GRAPHS_SHA256}")

    ratios = {d: [] for d in FROZEN_CLASS}
    obs = {(s, d): {"min_norm": None, "max_norm": None,
                    "min_raw": None, "max_raw": None, "rows": 0}
           for s in SOURCES for d in FROZEN_CLASS}
    src_norm = {s: {"min": None, "max": None, "rows": 0} for s in SOURCES}
    presets = 0
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            presets += 1
            md = row["g"].get("md", {})
            rows = list(md.get("g", []))
            for scene in md.get("s", []):
                rows += list(scene.get("s", [])) + list(scene.get("v", []))
            for r in rows:
                src, dest, raw, norm = r[0], r[3], r[5], r[6]
                if dest in FROZEN_CLASS and norm not in (0, None):
                    ratios[dest].append(abs(raw / norm))
                if src in SOURCES:
                    e = src_norm[src]
                    e["rows"] += 1
                    e["min"] = norm if e["min"] is None else min(e["min"], norm)
                    e["max"] = norm if e["max"] is None else max(e["max"], norm)
                    if dest in FROZEN_CLASS:
                        o = obs[(src, dest)]
                        o["rows"] += 1
                        for k, v in (("min_norm", norm), ("max_norm", norm),
                                     ("min_raw", raw), ("max_raw", raw)):
                            cur = o[k]
                            if cur is None:
                                o[k] = v
                            else:
                                o[k] = min(cur, v) if k.startswith("min") \
                                    else max(cur, v)
    extents = {}
    for dest, vals in ratios.items():
        if not vals:
            raise Refuse(f"no corpus row derives the extent of destination "
                         f"{dest} ({FROZEN_CLASS[dest]})")
        lo, hi = min(vals), max(vals)
        mid = 0.5 * (lo + hi)
        spread = (hi - lo) / mid
        if spread > tol:
            raise Refuse(f"destination {dest} ({FROZEN_CLASS[dest]}): corpus "
                         f"rows disagree about the extent by {spread:.3%} "
                         f"(> --extent-tol {tol:.3%}); min {lo}, max {hi}")
        extents[dest] = {"extent": round(mid, 6), "rows": len(vals),
                         "row_min": lo, "row_max": hi,
                         "relative_spread": spread}
    return {"graphs_sha256": got, "presets_scanned": presets,
            "extents": extents,
            "observed_source_normalized_range":
                {SOURCES[s]: src_norm[s] for s in SOURCES},
            "observed_in_class":
                {f"{SOURCES[s]}->{d}": obs[(s, d)]
                 for s in SOURCES for d in FROZEN_CLASS}}


def rounded_extent(x):
    """Snap a derived extent to its nearest 0.5 grid point when the corpus rows
    bracket it; keeps the declared corner depth a clean, exactly representable
    number and is recorded next to the raw derived value."""
    snapped = round(x * 2) / 2
    return snapped if abs(snapped - x) / max(abs(x), 1e-9) < 0.01 else x


# ----------------------------------------------------- 2. exhaustive ROM ----
def lift_rom(tb_text):
    start = tb_text.index("  // velocity ROM contents")
    end = tb_text.index("endfunction", start) + len("endfunction")
    return tb_text[start:end]


def rom_exhaustive(work, tb_text, tag):
    """All 128 RTL ROM words vs the frozen model quantizer."""
    d = os.path.join(work, "rom-" + tag)
    os.makedirs(d, exist_ok=True)
    sv = os.path.join(d, "tb_vel_rom.sv")
    with open(sv, "w", encoding="utf-8") as f:
        f.write(ROM_TB_TEMPLATE.replace("{rom}", lift_rom(tb_text)))
    vvp = os.path.join(d, "tb_vel_rom.vvp")
    rc, out, err = sh(["iverilog", "-g2012", "-o", vvp, sv], cwd=d)
    if rc != 0:
        return {"verdict": "ERROR", "mismatches": None,
                "stderr_tail": err[-300:]}, sv
    rc, out, err = sh(["vvp", vvp], cwd=d)
    words, fails = {}, []
    with open(os.path.join(d, "tb_vel_rom_trace.txt"), encoding="utf-8") as f:
        for line in f:
            p = line.split()
            if p and p[0] == "R":
                words[int(p[1])] = int(p[2])
    for m in range(128):
        want = vel_q(m)
        got = words.get(m)
        if got != want:
            fails.append(f"midi {m}: model={want} rtl={got}")
    return {"verdict": "PASS" if not fails else "FAIL",
            "entries_checked": len(words), "mismatches": len(fails),
            "first_failures": fails[:6],
            "rtl_done_line": out.strip().splitlines()[-1] if out.strip() else "",
            }, sv


# ------------------------------------------------------- 3. corner sweep ----
def sidecar(path, routes, note):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "engine_pin": "surge-synthesizer/surge@"
                          "58914e59c608ed4384ba6002e44c3465c58b2e71",
            "issue": "SXT-036",
            "provenance": "GENERATED parameter-corner route table "
                          "(tools/vel_param_corners.py). Depths are DECLARED "
                          "corners derived from committed corpus artifacts, "
                          "NOT engine readbacks (#96/#232).",
            "corner": note,
            "preset": {"path": PRESET_REL,
                       "census_blob_sha1":
                           "4675e423a7489b02f501f7763b4760f64ab035f9",
                       "blob_verified": False},
            "frozen_scope": "voice-list routes {ms_velocity(1), "
                            "ms_releasevelocity(30)} -> {308, 309, 310, 298}",
            "fixture_routes": routes,
        }, f, indent=2)
        f.write("\n")


def route(src, dest, depth):
    return {"modsource": SOURCES[src], "modsource_id": src, "dest_id": dest,
            "dest_name": FROZEN_CLASS[dest], "depth_raw": depth,
            "source": "declared-corner"}


def trace_stats(trace_path):
    """Per-destination checkpoint-sum magnitudes, term magnitudes and ties."""
    with open(trace_path, encoding="utf-8") as f:
        t = json.load(f)
    max_sum = [0, 0, 0, 0]
    max_term = 0
    saturated_terms = 0
    ties = 0
    src_words = set()
    concurrent = 0          # blocks with >=2 live voices carrying DISTINCT
    #                         source words: the precondition the per-instance-
    #                         state controls need in order to fire at all
    depth_q = [(r["source_id"], vm.qint(r["depth_raw"]), r["dest_id"])
               for r in t["vel_routes"]]
    for blk in t["blocks"]:
        if (len(blk["voices"]) > 1
                and len({tuple(r["vel_words"]) for r in blk["voices"]}) > 1):
            concurrent += 1
        for rec in blk["voices"]:
            vw, rw = rec["vel_words"]
            src_words.add((vw, rw))
            for i, s in enumerate(rec["vel_route_sums"]):
                max_sum[i] = max(max_sum[i], abs(s))
            for sid, dq, _dest in depth_q:
                srcv = vw if sid == 1 else rw
                p = dq * srcv
                unsat = (p + (1 << (FQ - 1))) >> FQ      # pre-saturation qmul
                term = vm.qmul(dq, srcv)                 # frozen, saturating
                max_term = max(max_term, abs(term))
                if unsat > QMAX or unsat < QMIN:
                    saturated_terms += 1
                if p % (1 << FQ) == (1 << (FQ - 1)):
                    ties += 1
    worst = max(max_sum)
    return {
        "blocks": len(t["blocks"]),
        "max_abs_route_sum": dict(zip(SUM_ORDER, max_sum)),
        "worst_abs_route_sum": worst,
        "checkpoint_word_headroom_x": (QMAX / worst) if worst else None,
        "fits_32bit_checkpoint_word": worst <= QMAX,
        "max_abs_single_term": max_term,
        "saturated_qmul_terms": saturated_terms,
        "exact_rounding_ties": ties,
        "distinct_source_word_pairs": len(src_words),
        "concurrent_distinct_source_word_blocks": concurrent,
        "routes": t.get("vel_routes", []),
    }


def exactness(cmp_tool, run_dir, tb=None):
    cmd = [sys.executable, cmp_tool, "--run-dir", run_dir]
    if tb:
        cmd += ["--tb", tb]
    rc, out, err = sh(cmd)
    try:
        return json.loads(out)
    except Exception:
        return {"verdict": "ERROR", "mismatches": None,
                "stderr_tail": err[-300:]}


def corner_table(kind, extents, obs, fallbacks=None):
    """Declared route table for a corner kind (all 8 source/destination pairs
    of the frozen class unless the corner says otherwise)."""
    rows = []
    for dest in DEST_ORDER:
        ext = rounded_extent(extents[dest]["extent"])
        for src in (1, 30):
            if kind == "full-scale-positive":
                d = +ext
            elif kind == "full-scale-negative":
                d = -ext
            elif kind == "mixed-sign-full-scale":
                d = +ext if src == 1 else -ext
            elif kind == "one-lsb":
                d = (1 if src == 1 else -1) / float(ONE)
            elif kind == "rounding-tie-half":
                d = 0.5 if src == 1 else -0.5
            elif kind == "observed-corpus-extreme":
                o = obs[f"{SOURCES[src]}->{dest}"]
                if o["rows"]:
                    d = (o["max_raw"] if abs(o["max_raw"] or 0)
                         >= abs(o["min_raw"] or 0) else o["min_raw"])
                else:
                    # no corpus row for this pair: fall back to full scale and
                    # record the fallback (never silently)
                    d = +ext
                    if fallbacks is not None:
                        fallbacks.append(
                            f"{SOURCES[src]}->{dest} {FROZEN_CLASS[dest]!r}: "
                            "no route with this source exists anywhere in the "
                            "corpus, so the corner falls back to full scale "
                            f"(+{ext})")
            elif kind == "over-range-accumulator":
                d = 3.0 * ext
            else:
                raise Refuse(f"unknown corner kind {kind}")
            rows.append(route(src, dest, float(d)))
    return rows


CORNERS = [
    ("full-scale-positive", "every route at normalized depth +1 "
     "(depth_raw = +derived extent)", True),
    ("full-scale-negative", "every route at normalized depth -1", True),
    ("mixed-sign-full-scale", "velocity +1, release velocity -1 "
     "(per-destination cancellation at full-scale terms)", True),
    ("one-lsb", "smallest nonzero model depth word (depth_q = +-1): the "
     "rounding floor of the qmul", True),
    ("rounding-tie-half", "depth exactly +-0.5: an exact round-half-up tie "
     "for every odd source word, both signs", True),
    ("observed-corpus-extreme", "largest |depth_raw| this source/destination "
     "pair actually shows anywhere in the corpus", True),
    ("over-range-accumulator", "CONTROL, outside the derived ranges: depth "
     "3x the derived extent overflows the 32-bit checkpoint word", False),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--sequence", default=SEQ)
    ap.add_argument("--skip-datapath", action="store_true",
                    help="control-plane exactness only (skip tb_voice.sv)")
    ap.add_argument("--extent-tol", type=float, default=0.005,
                    help="allowed relative spread between corpus rows that "
                         "derive the same destination extent (default 0.5%%)")
    args = ap.parse_args()
    art = os.path.abspath(args.artifacts)
    os.makedirs(art, exist_ok=True)
    work = tempfile.mkdtemp(prefix="sxt036-corners-")
    lines, ok = [], True

    def log(s=""):
        lines.append(s)
        print(s, flush=True)

    log("SXT-036 (#70) parameter corners - oracle-independent "
        "(graphs.jsonl + iverilog only)")
    log("Claim established: RTL == frozen model, exactly, at the declared "
        "corners (claim 1). Model-vs-pinned-engine agreement: NOT_RUN (#96). "
        "No fidelity, sound-quality, synthesis or hardware claim.")
    log(f"stimulus: {args.sequence}")
    log("")

    # ---- 1. derived ranges ------------------------------------------------
    ranges = derive_ranges(args.extent_tol)
    log(f"Derived destination extents from {ranges['presets_scanned']} "
        f"normalized corpus graphs (graphs.jsonl sha256 "
        f"{ranges['graphs_sha256'][:16]}.. == value pinned in #70):")
    for dest in DEST_ORDER:
        e = ranges["extents"][dest]
        log(f"  {dest} {FROZEN_CLASS[dest]!r}: extent {e['extent']} "
            f"(declared corner uses {rounded_extent(e['extent'])}) from "
            f"{e['rows']} rows, spread {e['relative_spread']:.4%}")
    log("  These extents are depth_raw/depth_normalized ratios recorded by the "
        "corpus pipeline - a FALSIFIABLE PREDICTION for the oracle host "
        "(#232), not an engine readback.")
    log("")
    log("Observed normalized depth range of this leaf's sources, whole corpus:")
    for s in SOURCES.values():
        o = ranges["observed_source_normalized_range"][s]
        log(f"  {s}: {o['rows']} route rows, normalized depth "
            f"[{o['min']}, {o['max']}]")
    log("  In-class rows (source -> frozen destination):")
    for key, o in ranges["observed_in_class"].items():
        log(f"    {key}: {o['rows']} rows"
            + (f", raw [{o['min_raw']}, {o['max_raw']}], norm "
               f"[{o['min_norm']}, {o['max_norm']}]" if o["rows"] else ""))
    log("")

    # ---- 2. exhaustive source-word domain --------------------------------
    tb_text = open(TB_VEL, encoding="utf-8").read()
    rom, rom_sv = rom_exhaustive(work, tb_text, "frozen")
    log(f"[exhaustive ROM] all 128 ms_velocity / ms_releasevelocity source "
        f"words, RTL (vel_rom lifted from rtl/voice/tb_vel.sv) vs frozen model "
        f"vel_q(): {rom['verdict']} entries={rom.get('entries_checked')} "
        f"mismatches={rom['mismatches']}")
    if rom["verdict"] != "PASS":
        ok = False
    mutant_text = tb_text
    for needle, rep in vnc.MUTANTS["rom-floor"]:
        if mutant_text.count(needle) < 1:
            log(f"[exhaustive ROM control] mutation anchor missing: {needle!r}")
            ok = False
        mutant_text = mutant_text.replace(needle, rep)
    rom_mut, _ = rom_exhaustive(work, mutant_text, "floor-mutant")
    fired = rom_mut["verdict"] == "FAIL" and (rom_mut["mismatches"] or 0) > 0
    log(f"[exhaustive ROM control] rom-floor mutant (no +127 rounding): "
        f"{rom_mut['verdict']} mismatches={rom_mut['mismatches']} -> "
        f"{'FAILS as required' if fired else 'DID NOT FAIL (control broken)'}")
    if not fired:
        ok = False
    shutil.copy(rom_sv, os.path.join(art, "tb_vel_rom_generated.sv"))
    log("")

    # ---- 3. corner sweep -------------------------------------------------
    results = {}
    for kind, note, must_be_exact in CORNERS:
        fallbacks = []
        rows = corner_table(kind, ranges["extents"],
                            ranges["observed_in_class"], fallbacks)
        d = os.path.join(work, kind)
        sc = os.path.join(work, kind + "-inputs.json")
        sidecar(sc, rows, note)
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", args.sequence,
                           "--vel-inputs", sc, "--out-dir", d])
        if rc != 0:
            log(f"[{kind}] model runner exit {rc}: {err[-300:]}")
            results[kind] = {"model_runner_exit": rc}
            ok = False
            continue
        st = trace_stats(os.path.join(d, "model_trace.json"))
        jv = exactness(CMP_VEL, d)
        expect = "PASS" if must_be_exact else "FAIL"
        good = (jv["verdict"] == expect) and (must_be_exact or
                                             (jv["mismatches"] or 0) > 0)
        log(f"[{kind}] {note}")
        log(f"    depths: " + ", ".join(
            f"{SOURCES[r['modsource_id']].replace('ms_', '')}->"
            f"{SUM_ORDER[SUM_INDEX[r['dest_id']]]} {r['depth_raw']:g}"
            for r in rows))
        log(f"    tb_vel.sv control plane: {jv['verdict']} "
            f"mismatches={jv['mismatches']} checked={jv.get('checked')} "
            f"(expected {expect}) -> "
            f"{'as required' if good else 'UNEXPECTED'}")
        if not good:
            ok = False
        for fb in fallbacks:
            log(f"    fallback: {fb}")
        entry = {"note": note, "expected_verdict": expect,
                 "control_plane": jv, "stats": st, "as_required": good,
                 "declared_depth_fallbacks": fallbacks}
        if must_be_exact and not args.skip_datapath:
            jd = exactness(CMP_VOICE, d)
            log(f"    tb_voice.sv datapath:    {jd['verdict']} "
                f"mismatches={jd['mismatches']} checked={jd.get('checked')}")
            if jd["verdict"] != "PASS":
                ok = False
            entry["datapath"] = jd
        elif must_be_exact:
            entry["datapath"] = {"verdict": "NOT_RUN",
                                 "reason": "--skip-datapath"}
        log(f"    worst |route sum| {st['worst_abs_route_sum']} of "
            f"{QMAX} (32-bit checkpoint word), headroom "
            + (f"{st['checkpoint_word_headroom_x']:.2f}x"
               if st["checkpoint_word_headroom_x"] else "n/a")
            + f"; fits={st['fits_32bit_checkpoint_word']}; max |term| "
            f"{st['max_abs_single_term']}; saturated qmul terms "
            f"{st['saturated_qmul_terms']}; exact rounding ties "
            f"{st['exact_rounding_ties']}; blocks with >=2 concurrently-live "
            f"voices carrying distinct source words "
            f"{st['concurrent_distinct_source_word_blocks']}")

        # per-corner controls
        if kind == "rounding-tie-half":
            ties = st["exact_rounding_ties"]
            log(f"    [tie precondition] exact .5 products observed: {ties} -> "
                + ("ties really occur" if ties > 0 else
                   "NO TIE OCCURRED (corner does not test the rounding rule)"))
            if ties == 0:
                ok = False
            mt = tb_text
            for needle, rep in vnc.MUTANTS["round-trunc"]:
                mt = mt.replace(needle, rep)
            mp = os.path.join(art, "tb_vel_round_trunc_mutant.sv")
            with open(mp, "w", encoding="utf-8") as f:
                f.write(mt)
            jm = exactness(CMP_VEL, d, tb=mp)
            fired = jm["verdict"] == "FAIL" and (jm["mismatches"] or 0) > 0
            log(f"    [tie control] round-trunc RTL mutant on this corner: "
                f"{jm['verdict']} mismatches={jm['mismatches']} -> "
                + ("FAILS as required" if fired
                   else "DID NOT FAIL (control broken)"))
            entry["round_trunc_control"] = {"exactness": jm,
                                            "fails_as_required": fired}
            if not fired:
                ok = False
            jb = exactness(CMP_VEL, d)      # restore the unmutated trace file
            entry["control_plane_rerun"] = jb["verdict"]
        if kind == "over-range-accumulator":
            entry["boundary"] = (
                "The per-destination checkpoint sum is a 32-bit signed word in "
                "rtl/voice/tb_vel.sv and an unbounded Python integer in the "
                "model, so the frozen checkpoint definition holds only while "
                "|sum| <= 2^31-1. This corner is deliberately outside the "
                "derived ranges and shows the divergence is reachable there.")
            log(f"    boundary recorded: {entry['boundary']}")
        results[kind] = entry
        shutil.rmtree(d, ignore_errors=True)
        log("")

    # ---- headroom roll-up over the DECLARED corners -----------------------
    declared = {k: v for k, v in results.items()
                if v.get("expected_verdict") == "PASS" and "stats" in v}
    worst_k = min(declared, key=lambda k: declared[k]["stats"]
                  ["checkpoint_word_headroom_x"] or float("inf")) \
        if declared else None
    log("Checkpoint-word accounting over the declared corners (not an "
        "agreement claim):")
    if worst_k:
        w = declared[worst_k]["stats"]
        log(f"  worst declared corner: {worst_k}, |sum| "
            f"{w['worst_abs_route_sum']} -> "
            f"{w['checkpoint_word_headroom_x']:.2f}x headroom in the 32-bit "
            f"checkpoint word")
        log(f"  every declared corner fits the 32-bit checkpoint word: "
            f"{all(v['stats']['fits_32bit_checkpoint_word'] for v in declared.values())}")
    log("  the over-range CONTROL above does not fit, and demonstrably fails "
        "exactness there - the boundary is recorded, not designed around.")
    log("")
    log("Not established here: model-vs-pinned-engine dry-render budgets "
        "(item 2) and the reference-budget negative controls (item 5) remain "
        "NOT_RUN - pinned oracle unavailable on dispatch host (#96). The "
        "derived extents and observed depth ranges above are predictions for "
        "the oracle-host backfill (#232), not reference values. "
        "Supported-preset delta from this leaf stays 0.")
    log(f"VERDICT (declared corners exact AND every control fired): "
        f"{'PASS' if ok else 'FAIL'}")

    with open(os.path.join(art, "param-corners.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(art, "param-corners.json"), "w",
              encoding="utf-8") as f:
        json.dump({"verdict": "PASS" if ok else "FAIL",
                   "claim": "RTL == frozen model (integer equality) at the "
                            "declared parameter corners of issue #70",
                   "sequence": args.sequence,
                   "reference_budget_items": "NOT_RUN (#96)",
                   "derived_ranges": ranges,
                   "exhaustive_source_word_rom": rom,
                   "exhaustive_source_word_rom_control": rom_mut,
                   "corners": results}, f, indent=2)
        f.write("\n")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)
