#!/usr/bin/env python3
"""#122 negative controls. Each must DEMONSTRABLY FAIL the check it targets;
a control that passes is a BROKEN control and this tool exits non-zero.

NC-R1  CONVENIENT DETERMINISTIC SUBSTITUTE (the control issue #122 names).
       A model that replaces the RNG-driven Noise / Sample & Hold shapes
       with a convenient deterministic stand-in must be labelled ADAPTED and
       refused from original-preset coverage. Fires on five legs:
         1. the FROZEN model refuses mod_wave 5/6 (the substitute cannot be
            reached through the frozen scope at all);
         2. the substitute nevertheless RENDERS -- so the control is real,
            not vacuous;
         3. its render differs from the nearest in-scope shape by more than
            the declared agreement threshold -- it is not a silent no-op;
         4. two substitutes differing ONLY in their arbitrary seed differ by
            more than the same threshold -- the substituted stream is a FREE
            CHOICE, not a property of the reference, so no seed choice can
            carry an original-preset claim;
         5. the substitute is labelled ADAPTED with
            counts_toward_original_preset_coverage == False, and a coverage
            gate refuses it.

NC-R2  THE FAIL-CLOSED REFUSAL IS LIVE AND NOT ALWAYS-FIRING. The frozen
       model and the extractor must both refuse waves 5/6 AND both accept
       every deterministic wave; a refusal that fires on everything would
       prove nothing.

NC-R3  SILENT EXCLUSION IS DETECTED. Dropping the affected presets from the
       corpus instead of publishing them as a reduction must be REFUSED by
       tools/fx_rng_coverage_impact.py (denominator guard), with no artifact
       written. Control leg: the untampered corpus is accepted, so the guard
       is not always-firing.

NC-R4  THE CHARACTERISATION'S OWN DETECTOR CONTROLS ARE LIVE. The
       "not reproducible" verdict is only admissible if the probe's
       fixed-seed comparators reported IDENTICAL; otherwise the verdict is
       NO_VERDICT, never FAIL.

ANCHOR AND CLAIM SCOPE. There is no pinned-engine checkout in this
environment, so NC-R1 is anchored on the FROZEN SXT-028g model and on its
declared agreement threshold, never on the engine. It records a
`reference_anchored_leg` with status NOT_RUN: nothing here is a fidelity,
agreement or support claim.

Writes reports/SXT-028-rng/negative-controls/negative-controls.{json,txt}.
Oracle-independent. Original to this repository (Apache-2.0).
"""

import argparse
import ast
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "model" / "effects"))
sys.path.insert(0, str(REPO / "model" / "effects" / "type-phaser"))

import phaser_model as pm  # noqa: E402
from phaser_model import (  # noqa: E402
    BLOCK, C_FMT, FXModLfo, PhaserModel, PhaserParams, Refuse, to_q,
)
from corners import CORNERS  # noqa: E402

OUTDIR = REPO / "reports" / "SXT-028-rng" / "negative-controls"
CHARACTERIZATION = REPO / "reports/SXT-028-rng/artifacts/rng-characterization.json"

# The same declared agreement threshold the SXT-028g controls are scored
# against (tools/phaser_negative_controls.py SENSITIVITY_LSB): a substitute
# must exceed the very budget a reference comparison would grade it on.
SENSITIVITY_LSB = 8192
CONTROL_CORNER = "synth-a"
BURST_BLOCKS = 96


# --------------------------------------------------------------------------
# the substitute: a "convenient deterministic shape" for the RNG waveforms
# --------------------------------------------------------------------------

class SubstituteRNGLfo(FXModLfo):
    """FXModLfo widened to accept mod_wave 5/6 by driving the sample-and-hold
    targets from a FIXED-SEED pseudo-random sequence.

    This is exactly the adaptation AGENTS.md forbids under a support claim:
    the pinned engine's stream is not reproduced, it is REPLACED by a
    convenient one. It exists here only as a live control.
    """

    coverage_class = "ADAPTED"
    counts_toward_original_preset_coverage = False

    def __init__(self, seed):
        super().__init__()
        self.seed = seed
        self._rs = random.Random(seed)
        self._snh = [0.0] * 4

    def process_start_of_block(self, mwave, rate, depth, phase_offset, width):
        if mwave not in (pm.MOD_NOISE, pm.MOD_SNH):
            return super().process_start_of_block(
                mwave, rate, depth, phase_offset, width)
        import math
        thisrate = max(0.0, rate)
        thiswidth = min(1.0, max(0.0, width))
        if thisrate > 0:
            self.lfophase = math.fmod(self.lfophase + thisrate, 1.0)
            p0 = self.lfophase + phase_offset
        else:
            p0 = phase_offset
        phases = [math.fmod(p0 + i * thiswidth * 0.25, 1.0) for i in range(4)]
        self.last_phases = list(phases)
        # the substitution: a convenient stand-in stream
        if thisrate <= 0 or phases[0] - thisrate <= 0:
            self._snh = [self._rs.uniform(-1.0, 1.0) for _ in range(4)]
        w = thiswidth ** 3
        wih = (1.0 - w) * 0.5
        vals = list(self._snh)
        for i in (0, 2):
            diff = wih * (self._snh[i + 1] - self._snh[i])
            vals[i] = self._snh[i] + diff
            vals[i + 1] = self._snh[i + 1] - diff
        for i in range(4):
            self.vals[i].new_value(to_q(vals[i], C_FMT))
        self.depth.new_value(to_q(depth, C_FMT))


def make_substitute(wave, seed, corner=CONTROL_CORNER):
    """A PhaserModel whose LFO has been widened to the RNG waveforms."""
    # build through a deterministic wave (the frozen gate refuses 5/6), then
    # substitute -- which is precisely what makes this an ADAPTED model.
    m = PhaserModel(PhaserParams(dict(CORNERS[corner],
                                      mod_wave_i=pm.MOD_SQUARE)))
    m.initialize()
    m.st.lfo = SubstituteRNGLfo(seed)
    m.p.mod_wave_i = wave
    return m


def make_frozen(wave, corner=CONTROL_CORNER):
    m = PhaserModel(PhaserParams(dict(CORNERS[corner], mod_wave_i=wave)))
    m.initialize()
    return m


def prs(n_blocks, seed, amp=1):
    rs = random.Random(seed)
    return [([rs.randint(-(amp << 21), amp << 21) for _ in range(BLOCK)],
             [rs.randint(-(amp << 21), amp << 21) for _ in range(BLOCK)])
            for _ in range(n_blocks)]


def render(model, blocks):
    v = []
    for il, ir in blocks:
        ol, orr = model.process_block(il, ir)
        v += ol
        v += orr
    return v


def max_abs_diff(a, b):
    n = min(len(a), len(b))
    return max((abs(a[i] - b[i]) for i in range(n)), default=0)


# --------------------------------------------------------------------------
# a coverage gate the substitute must not pass
# --------------------------------------------------------------------------

def coverage_gate_accepts(model_like) -> bool:
    """The rule a coverage publication applies to a candidate model: only an
    ORIGINAL model (not an adaptation) may contribute to original-preset
    coverage. Mirrors tools/publish_coverage.py's `adapted` discipline.
    """
    lfo = getattr(model_like, "st", model_like)
    lfo = getattr(lfo, "lfo", lfo)
    if getattr(lfo, "coverage_class", "ORIGINAL") != "ORIGINAL":
        return False
    return getattr(lfo, "counts_toward_original_preset_coverage", True)


# --------------------------------------------------------------------------
# NC-R1
# --------------------------------------------------------------------------

def nc_r1_substitute():
    blocks = prs(BURST_BLOCKS, 11)
    legs = {}

    # leg 1: the frozen model refuses the RNG waveforms outright
    refused = []
    for wave in (pm.MOD_NOISE, pm.MOD_SNH):
        try:
            make_frozen(wave)
            refused.append(False)
        except Refuse:
            refused.append(True)
    legs["frozen_model_refuses_5_and_6"] = all(refused)

    # leg 2: the substitute renders (the control is not vacuous)
    sub_a = render(make_substitute(pm.MOD_SNH, seed=1), blocks)
    legs["substitute_renders"] = len(sub_a) == BURST_BLOCKS * BLOCK * 2 \
        and any(v != 0 for v in sub_a)

    # leg 3: it differs from the nearest in-scope shape by > threshold
    inscope = render(make_frozen(pm.MOD_SQUARE), blocks)
    d_shape = max_abs_diff(inscope, sub_a)
    legs["differs_from_nearest_in_scope_shape"] = d_shape > SENSITIVITY_LSB

    # leg 4: the substituted stream is an arbitrary free choice
    sub_b = render(make_substitute(pm.MOD_SNH, seed=2), blocks)
    d_seed = max_abs_diff(sub_a, sub_b)
    legs["seed_choice_is_arbitrary"] = d_seed > SENSITIVITY_LSB
    # ... and the SAME seed reproduces itself, so leg 4's comparator works
    sub_a2 = render(make_substitute(pm.MOD_SNH, seed=1), blocks)
    legs["same_seed_reproduces_itself_detector_control"] = \
        max_abs_diff(sub_a, sub_a2) == 0

    # leg 5: labelled ADAPTED and refused by the coverage gate
    sub_model = make_substitute(pm.MOD_SNH, seed=1)
    legs["labelled_ADAPTED"] = \
        SubstituteRNGLfo.coverage_class == "ADAPTED" and \
        SubstituteRNGLfo.counts_toward_original_preset_coverage is False
    legs["coverage_gate_refuses_substitute"] = not coverage_gate_accepts(
        sub_model)
    # ... and accepts the frozen model, so the gate is not always-refusing
    legs["coverage_gate_accepts_frozen_detector_control"] = \
        coverage_gate_accepts(make_frozen(pm.MOD_SQUARE))

    ok = all(legs.values())
    return {
        "control": "NC-R1 convenient deterministic substitute for the RNG "
                   "waveforms",
        "targets": "a model that replaces the unpinnable RNG shape with a "
                   "convenient deterministic one must be ADAPTED and refused "
                   "from original-preset coverage",
        "legs": legs,
        "metrics": {
            "max_abs_diff_vs_nearest_in_scope_shape_lsb": d_shape,
            "max_abs_diff_between_two_substitute_seeds_lsb": d_seed,
            "declared_threshold_lsb": SENSITIVITY_LSB,
        },
        "coverage_class": "ADAPTED",
        "counts_toward_original_preset_coverage": False,
        "reference_anchored_leg": {
            "status": "NOT_RUN",
            "reason": "no pinned-engine fixture in this environment; the "
                      "substitute must also be scored against the wet "
                      "reference before any agreement statement. It cannot "
                      "be: that is the finding.",
        },
        "verdict": ("CONTROL-OK (the substitute renders, is materially "
                    "different, depends on an arbitrary seed, is labelled "
                    "ADAPTED and is refused from original-preset coverage)"
                    if ok else
                    "CONTROL-BROKEN (a leg did not fire)"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-R2
# --------------------------------------------------------------------------

def nc_r2_refusal_live():
    legs = {}
    refused, accepted = [], []
    for wave in (pm.MOD_NOISE, pm.MOD_SNH):
        try:
            make_frozen(wave)
            refused.append(wave)
        except Refuse:
            pass
    legs["model_refuses_rng_waves"] = not refused
    for wave in pm.DETERMINISTIC_WAVES:
        try:
            make_frozen(wave)
            accepted.append(wave)
        except Refuse:
            pass
    legs["model_accepts_every_deterministic_wave"] = \
        sorted(accepted) == sorted(pm.DETERMINISTIC_WAVES)

    src = (REPO / "tools" / "extract_phaser_inputs.py").read_text(
        encoding="utf-8")
    waves = None
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], "id", None)
                == "DETERMINISTIC_WAVES"):
            waves = ast.literal_eval(node.value)
    legs["extractor_gate_agrees_with_model"] = \
        waves is not None and tuple(waves) == tuple(pm.DETERMINISTIC_WAVES)
    legs["rng_waves_outside_both_gates"] = \
        waves is not None and not ({5, 6} & set(waves))

    ok = all(legs.values())
    return {
        "control": "NC-R2 the fail-closed refusal is live and not "
                   "always-firing",
        "targets": "one rule, two enforcement points (frozen model + "
                   "extractor); a refusal that fired on everything would "
                   "prove nothing",
        "legs": legs,
        "deterministic_waves": list(pm.DETERMINISTIC_WAVES),
        "verdict": ("CONTROL-OK (5/6 refused at both points, 0-4 accepted at "
                    "both)" if ok else "CONTROL-BROKEN"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-R3
# --------------------------------------------------------------------------

NC3_COPY = [
    "corpus/normalized/graphs.jsonl",
    "reports/SXT-028-rng/artifacts/rng-characterization.json",
    "reports/sxt-013/candidates/slate-256-balanced.json",
    "reports/sxt-013/candidates/slate-256-contributor-lean.json",
    "reports/sxt-013/candidates/slate-256-factory-lean.json",
]


def nc_r3_silent_exclusion():
    tool = REPO / "tools" / "fx_rng_coverage_impact.py"
    impact = json.loads(
        (REPO / "reports/SXT-028-rng/artifacts/coverage-impact.json")
        .read_text(encoding="utf-8"))
    affected = {r["path"] for r in impact["affected_presets"]}

    with tempfile.TemporaryDirectory(prefix="sxt028-rng-nc3-") as td:
        root = Path(td) / "repo"
        for rel in NC3_COPY:
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)

        # control leg: the untampered copy is ACCEPTED (guard not always-on)
        clean = subprocess.run(
            [sys.executable, str(tool), "--repo-root", str(root),
             "--out", "out/clean.json"],
            capture_output=True, text=True)

        # the tamper: silently drop the affected presets from the corpus
        graphs = root / "corpus/normalized/graphs.jsonl"
        kept = [line for line in graphs.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line)["p"] not in affected]
        graphs.write_text("\n".join(kept) + "\n", encoding="utf-8")
        tampered = subprocess.run(
            [sys.executable, str(tool), "--repo-root", str(root),
             "--out", "out/tampered.json"],
            capture_output=True, text=True)
        wrote = (root / "out/tampered.json").exists()

    legs = {
        "clean_corpus_accepted_detector_control": clean.returncode == 0,
        "silent_drop_refused": tampered.returncode == 2,
        "refusal_names_the_denominator": "corpus entries" in tampered.stderr,
        "no_artifact_written_on_refusal": not wrote,
    }
    ok = all(legs.values())
    return {
        "control": "NC-R3 silent exclusion (dropping affected presets from "
                   "the denominator instead of publishing a reduction)",
        "targets": "the coverage-impact tool must fail closed when the "
                   "corpus it is counting against has been shrunk",
        "legs": legs,
        "dropped_presets": len(affected),
        "refusal_stderr": tampered.stderr.strip()[:200],
        "verdict": ("CONTROL-OK (the silent drop is REFUSED and writes "
                    "nothing; the untampered corpus is accepted)" if ok
                    else "CONTROL-BROKEN"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-R4
# --------------------------------------------------------------------------

def nc_r4_probe_detectors():
    if not CHARACTERIZATION.is_file():
        return {
            "control": "NC-R4 the characterisation's detector controls",
            "status": "NOT_RUN",
            "reason": "no characterization artifact; run "
                      "tools/fx_rng_characterize.py first",
            "ok": False,
        }
    ch = json.loads(CHARACTERIZATION.read_text(encoding="utf-8"))
    leg_b = ch["legs"]["seed_reproducibility"]
    if leg_b["status"] == "NOT_RUN":
        return {
            "control": "NC-R4 the characterisation's detector controls",
            "status": "NOT_RUN",
            "reason": leg_b.get("reason", "probe not run"),
            "ok": False,
        }
    controls = [c for c in leg_b["checks"] if "DETECTOR CONTROL" in c["check"]]
    legs = {
        "at_least_two_detector_controls": len(controls) >= 2,
        "all_detector_controls_ok": all(c["status"] == "CONTROL-OK"
                                        for c in controls),
        "verdict_is_not_a_pass": leg_b["status"] in ("FAIL", "NO_VERDICT"),
    }
    ok = all(legs.values())
    return {
        "control": "NC-R4 the characterisation's detector controls are live",
        "targets": "a 'not reproducible' verdict must not come from an "
                   "always-firing comparator",
        "legs": legs,
        "detector_controls": [
            {"check": c["check"], "status": c["status"]} for c in controls],
        "leg_b_status": leg_b["status"],
        "verdict": ("CONTROL-OK (the fixed-seed comparators report IDENTICAL, "
                    "so the FAIL legs are measurements)" if ok
                    else "CONTROL-BROKEN"),
        "ok": ok,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", default=str(OUTDIR))
    args = ap.parse_args()

    controls = [nc_r1_substitute(), nc_r2_refusal_live(),
                nc_r3_silent_exclusion(), nc_r4_probe_detectors()]
    ok = all(c.get("ok") for c in controls)

    doc = {
        "schema_version": "sxt-028-rng-negative-controls/1.0.0",
        "issue": "#122",
        "decision_record":
            "decision-records/0013-fx-modulation-rng-stream.md",
        "anchor": "the FROZEN SXT-028g Phaser model and its declared "
                  "agreement threshold; NOT the pinned engine (no oracle in "
                  "this environment)",
        "model_revision": pm.model_revision(),
        "declared_threshold_lsb": SENSITIVITY_LSB,
        "controls": controls,
        "result": "PASS" if ok else "FAIL",
        "claim_scope": "controls only; no fidelity, agreement, support or "
                       "listening claim is made or implied.",
    }

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "negative-controls.json").write_text(
        json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    lines = ["#122 negative controls — FX modulation RNG waveforms",
             f"runner: tools/fx_rng_negative_controls.py; anchor: "
             f"{doc['anchor']}",
             f"frozen model revision: {doc['model_revision']}",
             ""]
    for c in controls:
        lines.append(f"{c['control']}")
        for k, v in c.get("legs", {}).items():
            lines.append(f"    {k}: {v}")
        for k, v in c.get("metrics", {}).items():
            lines.append(f"    {k}: {v}")
        lines.append(f"    {c.get('verdict', c.get('reason', ''))}")
        lines.append("")
    lines.append(f"RESULT: {doc['result']}" + (
        " — all controls healthy (each demonstrably fails the check it "
        "targets)" if ok else " — unhealthy controls present"))
    (outdir / "negative-controls.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
