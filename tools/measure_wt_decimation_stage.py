#!/usr/bin/env python3
"""SXT-026 (#176, re-run for #180): per-slice vs per-scene decimation.

WHAT THIS IS. A model-vs-model measurement of the two possible placements of
the 96 kHz -> 48 kHz decimator and the master stage in the SXT-026 wavetable
leaf:

  * PER SLICE -- one `voice_model.HalfbandD2` inside each `wt_model.Slice`,
    slices summed after decimation. This is what the frozen model did BEFORE
    the #180 contract revision (declared deviation 7 of #176).
  * PER SCENE -- the summed unclipped 96 kHz `sceneout`, one +/-8 clip, ONE
    `HalfbandD2` for the scene persisting across voice death, then master and
    clips. This is the pinned engine's placement
    (`SurgeSynthesizer::halfbandA/B` -> `HalfRateFilter::process_block_D2`),
    what `model/voice/run_model.py` models and `rtl/voice/tb_voice.sv`
    implements, and -- since the #180 SXT-017 contract revision
    (`decision-records/0018-wavetable-scene-decimation-placement.md`) -- what
    the frozen SXT-026 model does too.

The filter is linear, so the two topologies differ only by

  * fixed-point rounding (one rounding of a sum vs a sum of roundings),
  * where the +/-8 `sceneout` clip falls (per slice vs once on the sum),
  * where the master gain and its clips fall (per slice vs once per scene),
  * STATE LIFETIME: a slice's filter state -- and its ring-out -- is discarded
    when the voice dies, where the engine's scene filter keeps ringing.

WHICH LEG IS FROZEN CHANGED WITH #180, THE NUMBERS DID NOT. |legA - legB| is
symmetric, so re-running this tool after the revision reproduces the #176
numbers exactly; that reproduction is the check that the landed topology is the
one that was measured before the decision was taken. What moved is which leg is
gated against `run_model.py`:

  before #180: leg A (per slice) was the frozen model; leg B was the proposal.
  since  #180: leg B (per scene) is the frozen model; leg A is a LEGACY
               re-implementation of the retired placement, kept here so the
               delta stays re-measurable -- the same device
               `tools/halfband_legacy_render.py` uses for #123 attribution.

WHAT THIS IS NOT. Both legs are model arithmetic; no reference render is read
and no pinned engine is executed. Nothing here is a fidelity, preset-support,
RTL-vs-model, or musical-quality claim, and no budget is graded.

HOW THE TWO LEGS STAY COMPARABLE. Both legs are driven from ONE render: the
oscillator / AEG / scene-gain stage upstream of the decimator is identical in
both topologies, so it is evaluated once per block (`Slice.scene_block`) and
fed to both legs. Voice creation and voice death therefore happen at exactly
the same blocks in both legs, and every measured difference is attributable to
the decimation stage alone.

  leg A (per slice, LEGACY -- retired by #180):
      `LegacyPerSliceStage` per slice, then sum -> +/-8 clip -> +/-1
      clip -> int16                     [pre-#180 run_model.py:198-202]
  leg B (per scene, = the frozen model and the pinned engine's placement):
      `wt_model.SceneDecimator` on the summed unclipped 96 kHz scene
                                              [run_model.py, #180 onward]

Leg B is verified byte-identical to `run_model.py`'s own render of the same
case (fail-closed, `--verify-runner`, on by default), so the recorded numbers
cannot come from a drifted re-implementation of the frozen leg.

Requires the external pinned asset root (ORACLE_SURGE_DATA); the fixtures
hash-verify the asset themselves and ABORT on mismatch.

Usage:
  ORACLE_SURGE_DATA=<pinned>/resources/data \\
  python3 tools/measure_wt_decimation_stage.py \\
      --out reports/sxt-026/artifacts/decimation-stage-per-slice-vs-per-scene.json
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "wavetable"))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402
import wt_model as wm  # noqa: E402

INPUTS = os.path.join(REPO, "model", "oscillators", "wavetable", "inputs")
RUNNER = os.path.join(REPO, "model", "oscillators", "wavetable", "run_model.py")

FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS
N_SLOTS = 4                      # same slot budget as run_model.py
INT16_FULL_SCALE = 32767.0
RMS_DIFF_DBFS_FLOOR = -300.0     # same finite floor the comparators use

# The nine committed SXT-026 fixture cases: exactly the (inputs, sequence)
# pairs that have a committed model render under reports/sxt-026/artifacts/
# (model-<inputs>__<sequence>.wav). `kick-original` / `mf-original` carry a
# REFERENCE render only (no model render, no RTL stimulus) and are not fixture
# cases of this leaf.
CASES = [
    ("kick-wtfix", "seq-wt-base-v1"),
    ("kick-wtfix-morph25", "seq-wt-base-v1"),
    ("kick-wtfix-morph75", "seq-wt-base-v1"),
    ("kick-wtfix", "seq-wt-pitch-extremes-v1"),
    ("kick-wtfix-kt", "seq-wt-pitch-extremes-hi-v1"),
    ("kick-wtfix-uni16", "seq-wt-unison16-v1"),
    ("mf-wtfix", "seq-wt-base-v1"),
    ("mf-wtfix-morph25", "seq-wt-base-v1"),
    ("mf-wtfix-morph75", "seq-wt-base-v1"),
]


def rms_dbfs(rms):
    """20*log10(rms/32767), clamped to a finite floor (strict-JSON safe)."""
    if not rms > 0:
        return RMS_DIFF_DBFS_FLOOR
    return max(float(20 * np.log10(rms / INT16_FULL_SCALE)),
               RMS_DIFF_DBFS_FLOOR)


def to_int16(m):
    """run_model.py's single Q10.21 -> int16 conversion (round toward zero)."""
    m = vm.limit_i(m, -wm.ONE, wm.ONE)
    return (m * 32767) >> FQ if m >= 0 else -((-m * 32767) >> FQ)


def sha256_of_i16(samples, tmpdir):
    """sha256 of a leg's WAV render (recorded for both legs; the FROZEN leg's
    is additionally gated against run_model.py by verify_runner)."""
    p = os.path.join(tmpdir, "leg.wav")
    wm.write_wav16(p, samples)
    return sha256_file(p)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class LegacyPerSliceStage:
    """The PRE-#180 per-slice decimator + master stage, verbatim.

    Reproduces `wt_model.Slice.decimate_scene()` as it stood before the #180
    SXT-017 contract revision moved the stage out to `SceneDecimator`: one
    `HalfbandD2` per voice slice, the +/-8 clip applied to that slice's own
    contribution, and the master gain and its clips inside the slice. One
    instance per slice, created and discarded with the slice, so its filter
    state dies with the voice exactly as the retired placement's did.

    It is a LEGACY re-implementation, kept only so the retired placement stays
    measurable (`tools/halfband_legacy_render.py` does the same for the
    pre-#123 halfband ordering). It is not the frozen model and must never be
    presented as one.
    """

    def __init__(self, inp):
        self.master = vm.db_to_linear(vm.qint(inp.master_db))
        self.halfband = vm.HalfbandD2()

    def process_block(self, scene):
        scene = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene]
        bl = self.halfband.process(scene)
        mono = []
        for k in range(BLOCK_SIZE):
            l = vm.qmul(bl[k], self.master)
            l = vm.limit_i(l, vm.qint(-8.0), vm.qint(8.0))
            mono.append(vm.limit_i(l, -wm.ONE, wm.ONE))
        return mono


def render_both(inputs_path, seq_path, max_blocks=None):
    """Render both decimation topologies from one shared upstream pass."""
    seq = vm.load_sequence(seq_path)
    inp = wm.Inputs(inputs_path)

    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    if not notes:
        raise RuntimeError("sequence has no notes")
    last_t = max(e["t"] for e in notes)
    total_samples = last_t + int(float(seq.get("tail_s", 1.5)) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)
    if max_blocks:
        total_blocks = min(total_blocks, max_blocks)

    scene_stage = wm.SceneDecimator(inp)    # ONE per scene (leg B, frozen)
    legacy_stages = {}                      # id(slice) -> LegacyPerSliceStage

    voices = []
    events = list(seq["events"])
    ei = 0
    a_q21, b_q21 = [], []                   # Q10.21 mono, both legs
    a_i16, b_i16 = [], []
    live_per_block = []
    death_blocks = []
    last_death_block = None

    for b in range(total_blocks):
        created = []
        while ei < len(events) and -(-events[ei]["t"] // BLOCK_SIZE) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = wm.Slice(inp, e["note"], e.get("velocity", 100))
                v.slot = slot
                # the legacy per-slice stage is created WITH the slice and
                # discarded with it: that is the state-lifetime half of the
                # difference being measured
                legacy_stages[id(v)] = LegacyPerSliceStage(inp)
                voices.append(v)
                created.append(slot)
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.gate = False
                        break
            ei += 1

        live_per_block.append(len(voices))
        alive = []
        mono_a = [0] * BLOCK_SIZE
        scene_sum = [0] * BLOCK_SIZE_OS
        for v in voices:
            # ONE shared upstream pass: identical in both topologies
            scene, _osout, keep = v.scene_block(b)
            # leg A: the retired per-slice stage
            mono = legacy_stages[id(v)].process_block(scene)
            for k in range(BLOCK_SIZE):
                mono_a[k] += mono[k]
            # leg B: accumulate the UNCLIPPED per-slice scene contribution
            for k in range(BLOCK_SIZE_OS):
                scene_sum[k] += scene[k]
            if keep:
                alive.append(v)
            else:
                death_blocks.append(b)
                last_death_block = b
                legacy_stages.pop(id(v), None)   # the slice's filter dies too
        voices = alive

        # leg A tail: pre-#180 run_model.py:198-202
        # (sum -> +/-8 clip -> +/-1 -> int16)
        mono_a = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in mono_a]
        for k in range(BLOCK_SIZE):
            a_q21.append(vm.limit_i(mono_a[k], -wm.ONE, wm.ONE))
            a_i16.append(to_int16(mono_a[k]))

        # leg B tail: the frozen per-scene stage (`wt_model.SceneDecimator`,
        # the same statement order as model/voice/run_model.py:265-279). NOTE
        # it runs on EVERY block, including blocks with no live voice -- that
        # ring-out is the state-lifetime half of the difference.
        for m in scene_stage.process_block(scene_sum):
            b_q21.append(m)
            b_i16.append(to_int16(m))

    return {
        "blocks": total_blocks,
        "a_q21": a_q21, "b_q21": b_q21,
        "a_i16": a_i16, "b_i16": b_i16,
        "live_per_block": live_per_block,
        "voice_death_blocks": sorted(set(death_blocks)),
        "last_death_block": last_death_block,
    }


def metrics_for(r):
    a16 = np.asarray(r["a_i16"], dtype=np.float64)
    b16 = np.asarray(r["b_i16"], dtype=np.float64)
    a21 = np.asarray(r["a_q21"], dtype=np.int64)
    b21 = np.asarray(r["b_q21"], dtype=np.int64)
    d16 = np.abs(a16 - b16)
    d21 = np.abs(a21 - b21)
    nz = np.nonzero(d16)[0]
    live = np.asarray(r["live_per_block"], dtype=np.int64)
    ld = r["last_death_block"]
    post = None
    if ld is not None and (ld + 1) * BLOCK_SIZE < len(a16):
        tail_from = (ld + 1) * BLOCK_SIZE
        post = {
            "from_frame": int(tail_from),
            "frames": int(len(a16) - tail_from),
            "per_slice_peak_lsb": float(np.abs(a16[tail_from:]).max()),
            "per_scene_peak_lsb": float(np.abs(b16[tail_from:]).max()),
            "max_abs_diff_lsb": float(d16[tail_from:].max()),
            "rms_diff_dbfs": rms_dbfs(
                float(np.sqrt((d16[tail_from:] ** 2).mean()))),
            # the ring-out is measured in the FINER Q10.21 domain too: an
            # int16-only reading cannot distinguish "no ring-out" from "a
            # ring-out below one int16 LSB"
            "per_slice_peak_q21": int(np.abs(a21[tail_from:]).max()),
            "per_scene_peak_q21": int(np.abs(b21[tail_from:]).max()),
            "max_abs_diff_q21": int(d21[tail_from:].max()),
        }
    return {
        "frames": int(len(a16)),
        "blocks": int(r["blocks"]),
        "per_slice_peak_lsb": float(np.abs(a16).max()),
        "per_scene_peak_lsb": float(np.abs(b16).max()),
        "max_abs_diff_lsb": float(d16.max()),
        "rms_diff_lsb": float(np.sqrt((d16 ** 2).mean())),
        "rms_diff_dbfs": rms_dbfs(float(np.sqrt((d16 ** 2).mean()))),
        "frames_differing": int(len(nz)),
        "first_differing_frame": (int(nz[0]) if len(nz) else None),
        "max_abs_diff_q21": int(d21.max()),
        "rms_diff_q21": float(np.sqrt((d21.astype(np.float64) ** 2).mean())),
        "bit_identical": bool(d21.max() == 0),
        "max_live_voices": int(live.max()),
        "blocks_with_overlapping_voices": int((live > 1).sum()),
        "voice_death_blocks": r["voice_death_blocks"],
        "has_voice_death_mid_render": bool(
            r["last_death_block"] is not None
            and r["last_death_block"] < r["blocks"] - 1),
        "after_last_voice_death": post,
    }


def failure_control(cases):
    """Issue #176's failure control, as a function so it can be exercised.

    The per-scene leg MUST differ from the per-slice leg on at least one case
    that exercises overlapping or released voices. Bit-identical everywhere
    means the measurement did not exercise voice death and the case set must be
    extended -- so a synthetic all-bit-identical case list must come back FAIL
    (that is what makes this a live control rather than a formality; asserted
    by tests/test_wt_decimation_stage.py)."""
    qualifying = [c for c in cases
                  if c["max_live_voices"] > 1 or c["has_voice_death_mid_render"]]
    differing = [c for c in qualifying if not c["bit_identical"]]
    return {
        "requirement": (
            "the per-scene leg must differ from the per-slice leg on at least "
            "one case with overlapping or released voices; bit-identical "
            "everywhere would mean voice death was never exercised and the "
            "case set must be extended"),
        "qualifying_cases": len(qualifying),
        "differing_qualifying_cases": len(differing),
        "verdict": "PASS" if differing else "FAIL",
    }


def verify_runner(inputs_path, seq, b_i16, tmpdir):
    """Fail-closed: leg B must be byte-identical to run_model.py's render.

    Leg B is the frozen model since the #180 contract revision; before it the
    gate guarded leg A. The gate always guards whichever leg claims to BE the
    frozen model, so the recorded numbers can never come from a drifted
    re-implementation of it."""
    out_dir = os.path.join(tmpdir, "runner")
    cmd = [sys.executable, RUNNER, "--inputs", inputs_path,
           "--sequence", seq, "--out-dir", out_dir]
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("run_model.py refused: %s" % p.stderr[-2000:])
    mine = os.path.join(tmpdir, "leg_b.wav")
    wm.write_wav16(mine, b_i16)
    ref = os.path.join(out_dir, "model.wav")
    got, want = sha256_file(mine), sha256_file(ref)
    if got != want:
        raise RuntimeError(
            "ABORT: leg B is not the frozen model's render "
            "(%s: leg B %s != run_model.py %s)" % (seq, got, want))
    return want


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="metrics JSON path")
    ap.add_argument("--wav-dir", default=None,
                    help="also write both legs' renders here (not committed)")
    ap.add_argument("--max-blocks", type=int, default=None,
                    help="cap the render (debug only; a capped run is marked "
                         "partial and must not be committed)")
    ap.add_argument("--case", action="append", default=None,
                    help="inputs:sequence (repeatable); default: all nine")
    ap.add_argument("--no-verify-runner", action="store_true",
                    help="skip the leg-A byte-identity gate (debug only)")
    args = ap.parse_args()

    cases = CASES
    if args.case:
        cases = [tuple(c.split(":", 1)) for c in args.case]

    out_cases = []
    tmpdir = tempfile.mkdtemp(prefix="wt-decim-")
    for name, seq in cases:
        inputs_path = os.path.join(INPUTS, name + ".json")
        seq_path = os.path.join(REPO, "fixtures", "sequences", seq + ".json")
        r = render_both(inputs_path, seq_path, args.max_blocks)
        m = metrics_for(r)
        entry = {"inputs": os.path.relpath(inputs_path, REPO),
                 "sequence": seq, "case": "%s / %s" % (name, seq)}
        entry["leg_a_render_sha256"] = sha256_of_i16(r["a_i16"], tmpdir)
        if args.no_verify_runner:
            entry["frozen_leg_runner_equality"] = "NOT_RUN (--no-verify-runner)"
        else:
            entry["frozen_leg_runner_equality"] = "PASS (byte-identical)"
            entry["leg_b_render_sha256"] = verify_runner(
                inputs_path, seq, r["b_i16"], tmpdir)
        entry.update(m)
        out_cases.append(entry)
        if args.wav_dir:
            os.makedirs(args.wav_dir, exist_ok=True)
            wm.write_wav16(os.path.join(
                args.wav_dir, "per-slice-%s__%s.wav" % (name, seq)),
                r["a_i16"])
            wm.write_wav16(os.path.join(
                args.wav_dir, "per-scene-%s__%s.wav" % (name, seq)),
                r["b_i16"])
        print(json.dumps({k: entry[k] for k in (
            "case", "max_abs_diff_lsb", "rms_diff_dbfs", "max_abs_diff_q21",
            "bit_identical", "max_live_voices", "has_voice_death_mid_render")},
            indent=1), flush=True)

    control = failure_control(out_cases)
    control_ok = control["verdict"] == "PASS"

    doc = {
        # /2: the frozen leg swapped from A (per slice) to B (per scene) with
        # the #180 SXT-017 contract revision; the metrics are unchanged and
        # re-run to the same numbers, and both legs now carry a render sha256.
        "format": "sxt-026-decimation-stage-measurement/2",
        "issue": 176,
        "reissue": 180,
        "frozen_leg": ("b (per scene) -- since the #180 contract revision "
                       "(decision-records/0018-wavetable-scene-decimation-"
                       "placement.md). Before it, leg a (per slice) was the "
                       "frozen model and leg b was the proposal. |a-b| is "
                       "symmetric, so these numbers are the #176 numbers "
                       "re-run after the move: that reproduction is the check "
                       "that the landed topology is the measured one."),
        "leaf": "SXT-026 osc:Wavetable (#19)",
        "generated_by": "tools/measure_wt_decimation_stage.py",
        "engine_pin": ("surge-synthesizer/surge@"
                       "58914e59c608ed4384ba6002e44c3465c58b2e71"),
        "partial_run": bool(args.max_blocks),
        "asset_identity": (
            "each fixture's declared wt_sha256 is re-verified against the "
            "external pinned asset by wt_model.Inputs at load; a mismatch "
            "ABORTs, so these numbers cannot have been produced from a "
            "substituted wavetable. No payload is committed "
            "(decision-records/0004)."),
        "environment": {
            "python": "%d.%d" % sys.version_info[:2],
            "sample_rate_hz": vm.SR,
            "block_size_48k": BLOCK_SIZE,
            "block_size_96k": BLOCK_SIZE_OS,
            "determinism": ("pure integer model + fixed stimulus; identical "
                            "reruns produce identical numbers"),
        },
        "claim_scope": (
            "MODEL-vs-MODEL ONLY. Both legs are SXT-026 wavetable model "
            "arithmetic (leg b is the frozen model, leg a a legacy "
            "re-implementation of the retired placement); no reference render "
            "is read and no pinned engine is executed. This establishes no "
            "fidelity, preset-support, RTL-vs-model, or musical-quality "
            "claim, and grades no budget."),
        "leg_a": ("per-slice decimation: one voice_model.HalfbandD2 per voice "
                  "slice, slices summed after decimation -- the RETIRED "
                  "placement (pre-#180 wt_model.Slice.decimate_scene), kept "
                  "here as the LEGACY re-implementation "
                  "measure_wt_decimation_stage.LegacyPerSliceStage so the "
                  "delta stays re-measurable. Not the frozen model."),
        "leg_b": ("per-scene decimation: unclipped per-slice scene "
                  "contributions summed at 96 kHz, one +/-8 clip, ONE "
                  "HalfbandD2 for the whole scene (persisting across voice "
                  "death), then master and clips -- the pinned engine's "
                  "SurgeSynthesizer::halfbandA/B placement, as modelled by "
                  "model/voice/run_model.py, implemented by "
                  "rtl/voice/tb_voice.sv, and -- since #180 -- by "
                  "wt_model.SceneDecimator: THE FROZEN MODEL."),
        "shared_upstream": (
            "both legs consume ONE Slice.scene_block() pass per block, so "
            "voice creation/death blocks are identical and every difference "
            "is attributable to the decimation stage"),
        "metric_definitions": {
            "max_abs_diff_lsb": "max |legA - legB| on the 48 kHz int16 render",
            "rms_diff_lsb": "RMS of |legA - legB| in int16 LSB",
            "rms_diff_dbfs": ("20*log10(rms/32767), clamped to "
                              "%.1f (same finite floor the audio comparators "
                              "use)" % RMS_DIFF_DBFS_FLOOR),
            "max_abs_diff_q21": ("max |legA - legB| in Q10.21 LSB, before the "
                                 "int16 conversion (finer than the int16 leg: "
                                 "one int16 LSB is 64 Q10.21 LSB)"),
            "after_last_voice_death": (
                "the same metrics restricted to the frames after the last "
                "voice died -- where leg A is silent by construction and leg "
                "B is still ringing out"),
        },
        "cases": out_cases,
        "failure_control": control,
        "summary": {
            "cases": len(out_cases),
            "max_abs_diff_lsb_worst": max(c["max_abs_diff_lsb"]
                                          for c in out_cases),
            "rms_diff_dbfs_worst": max(c["rms_diff_dbfs"] for c in out_cases),
            "max_abs_diff_q21_worst": max(c["max_abs_diff_q21"]
                                          for c in out_cases),
            "bit_identical_cases": sum(1 for c in out_cases
                                       if c["bit_identical"]),
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps({"out": args.out,
                      "failure_control": doc["failure_control"]["verdict"],
                      "summary": doc["summary"]}, indent=1))
    return 0 if control_ok else 1


if __name__ == "__main__":
    sys.exit(main())
