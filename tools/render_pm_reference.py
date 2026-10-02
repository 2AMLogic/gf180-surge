#!/usr/bin/env python3
"""SXT-043 reference renderer (requires the external pinned oracle).

Renders the fixture sequences through the pinned engine for the DECLARED
pm_mono_st_fp fixture configuration (`model/voice/playmode/fixture_config.py`
+ `inputs/<carrier>.json`): the reference the model budget checks compare
against, and the renderer the leaf's negative controls run through.

Policies inherited from the SXT-012 fixture harness
(`fixtures/render_fixture.py`) and matched by the model runner: fresh
instance per render, controller reset, 0.25 s settle discarded,
block-quantized event scheduling (an event at `t` applies at the start of
block `ceil(t/32)`), tail = last event + `tail_s`, mono (L+R)/2 int16 PCM,
no normalization / time warping / fades, clipped-sample counts recorded.

`tools/_render_reference_common.py` is NOT reused here: this leaf's
`build_instance` additionally classifies and pins modulation routes (it
returns a third value), and the leaf needs the declared forcing flags below,
which the shared two-value harness has no place for.

Declared forcing flags -- each exists for a named control or probe and is
recorded verbatim in the sidecar:

  --force-polymode N      REQUIRED NEGATIVE CONTROL (issue #77): render the
                          mono fixture as another playmode.  `--force-polymode 0`
                          is the forced-Poly control; the budget check against
                          the pm_mono_st_fp reference must FAIL.
  --porta-curve / --porta-gliss / --porta-constrate / --porta-retrigger /
  --porta-value           declared PARAMETER-CORNER probes over the
                          engine-declared portamento option space.
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice", "playmode"))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

SR = 48000
ISSUE_ID = "SXT-043"
ISOLATION_NOTE = (
    "declared fixture configuration (one Sine slot audible -- type/shape/"
    "FM-behavior/unison/lowcut/highcut/octave/pitch pinned; other mixer "
    "paths, both filter units, all FX, waveshaper, scene lowcut and FM "
    "routing off; fbc serial1; scene mode Single; retrigger on; drift 0; "
    "modulation depth zeroed for routes into pinned parameters) with the "
    "carrier's PLAYMODE and PORTAMENTO parameterization left intact -- a "
    "test configuration, never an adapted preset, never coverage"
)


def render_bus(surgepy, seq, carrier, repeats, forcing):
    monos = []
    total_blocks = total_samples = 0
    readback = routes = None
    for _r in range(repeats):
        s, readback, routes = fc.build_instance(
            surgepy, oc, carrier,
            force_polymode=forcing.get("force_polymode"),
            porta_options=forcing.get("porta_options"),
            porta_value=forcing.get("porta_value"))
        try:
            s.pitchBend(0, 0)
            s.channelController(0, 64, 0)
            s.channelController(0, 1, 0)
            s.channelController(0, 11, 0)
            s.channelAftertouch(0, 0)
            s.allNotesOff()
            bs = int(s.getBlockSize())
            settle_blocks = int(float(seq.get("settle_s", 0.25)) * SR) // bs
            s.processMultiBlock(s.createMultiBlock(settle_blocks))

            events = seq["events"]
            notes = [e for e in events if e["type"] in ("note_on", "note_off")]
            last_t = max(e["t"] for e in notes) if notes else 0
            total_samples = last_t + int(float(seq.get("tail_s", 2.5)) * SR)
            total_blocks = -(-total_samples // bs)
            buf = s.createMultiBlock(total_blocks)

            def quant(t):
                return -(-t // bs)

            i = b = 0
            while b < total_blocks:
                while i < len(events) and quant(events[i]["t"]) <= b:
                    e = events[i]
                    if e["type"] == "note_on":
                        s.playNote(e["channel"], e["note"],
                                   e.get("velocity", 100), 0)
                    elif e["type"] == "note_off":
                        s.releaseNote(e["channel"], e["note"],
                                      e.get("velocity", 0))
                    else:
                        raise fc.Refuse(
                            "sequence %r carries a %r event; the SXT-043 "
                            "fixture configuration declares every non-note "
                            "modulation source inert, so a non-note event "
                            "would make that declaration false"
                            % (seq.get("id"), e["type"]))
                    i += 1
                nxt = i
                seg = total_blocks if nxt >= len(events) \
                    else max(quant(events[nxt]["t"]), b + 1)
                s.processMultiBlock(buf, b, seg - b)
                b = seg
            stereo = np.asarray(buf)
            monos.append(0.5 * (stereo[0] + stereo[1]))
        finally:
            del s
    hashes = [hashlib.sha256(np.ascontiguousarray(m).tobytes()).hexdigest()
              for m in monos]
    info = {
        "blocks": total_blocks,
        "frames": total_samples,
        "peak_abs_float": float(np.max(np.abs(monos[0]))) if total_samples
        else 0.0,
        "clipped_samples": int(np.sum(np.abs(monos[0]) > 1.0)),
        "repeats": repeats,
        "repeat_hashes": hashes,
        "bit_identical_repeats": len(set(hashes)) == 1,
    }
    return monos, info, readback, routes


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carrier", required=True, choices=sorted(fc.CARRIERS))
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--tag", default="ref",
                    help="output basename suffix (controls use their own)")
    ap.add_argument("--force-polymode", type=int, default=None,
                    help="NEGATIVE CONTROL: force scene-A playmode to this "
                         "pinned play_mode id (0 = Poly)")
    ap.add_argument("--porta-curve", type=int, default=None,
                    choices=(-1, 0, 1))
    ap.add_argument("--porta-gliss", action="store_true")
    ap.add_argument("--porta-constrate", action="store_true")
    ap.add_argument("--porta-retrigger", action="store_true")
    ap.add_argument("--porta-value", type=float, default=None)
    args = ap.parse_args()

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences",
                                seq_path + ".json")
    with open(seq_path, encoding="utf-8") as f:
        seq = json.load(f)
    inputs_rel = os.path.join(REPO, "model", "voice", "playmode", "inputs",
                              args.carrier + ".json")
    with open(inputs_rel, encoding="utf-8") as f:
        inputs = json.load(f)

    porta_options = None
    if any((args.porta_curve is not None, args.porta_gliss,
            args.porta_constrate, args.porta_retrigger)):
        base = inputs["portamento"]["options"]
        porta_options = {
            "curve": base["curve"] if args.porta_curve is None
            else args.porta_curve,
            "glissando": bool(args.porta_gliss),
            "constantRate": bool(args.porta_constrate),
            "retrigger": bool(args.porta_retrigger),
        }
    forcing = {"force_polymode": args.force_polymode,
               "porta_options": porta_options,
               "porta_value": args.porta_value}

    monos, info, readback, routes = render_bus(
        surgepy, seq, args.carrier, args.repeats, forcing)

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(
        args.out_dir, "%s__%s-%s.wav" % (args.carrier, seq["id"], args.tag))
    oc.write_wav_mono16(wav_path, monos[0], SR)

    preset_abs = os.path.join(oc.engine_dir(), inputs["preset_path"])
    blob = oc.git_blob_sha1(preset_abs)
    if blob != inputs["preset_census_blob_sha1"]:
        print("REFUSING: preset blob drift", file=sys.stderr)
        return 2

    sidecar = {
        "schema_version": 1,
        "issue": ISSUE_ID,
        "carrier": args.carrier,
        "inputs": os.path.relpath(inputs_rel, REPO),
        "sequence": {"id": seq["id"], "path": os.path.relpath(seq_path, REPO)},
        "declared_overrides_applied": inputs["declared_overrides"],
        "declared_forcing": {k: v for k, v in forcing.items()
                             if v is not None},
        "play_mode_rendered": readback["polymode"],
        "portamento_rendered": {
            "value": readback["portamento"],
            "options": readback["portamento_options"],
        },
        "modulation_routes": routes,
        "preset_blob_sha1": blob,
        "isolation_note": ISOLATION_NOTE,
        "render": {"sample_rate": SR, **info},
        "wav": {"path": os.path.relpath(wav_path, REPO),
                "sha256": oc.sha256_file(wav_path)},
        "engine": {"commit": inputs["engine_pin"].split("@")[-1],
                   "surgepy": surgepy.getVersion()},
        "audio_policy": "mono (L+R)/2, int16 PCM, hard clip to [-1,1] "
                        "recorded; no normalization, no time warping, "
                        "no fades",
    }
    with open(wav_path + ".json", "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps({"wav": wav_path,
                      "sha256": sidecar["wav"]["sha256"],
                      "play_mode_rendered": readback["polymode"],
                      "bit_identical_repeats": info["bit_identical_repeats"],
                      "clipped": info["clipped_samples"],
                      "peak": round(info["peak_abs_float"], 4)}, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except fc.Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)
