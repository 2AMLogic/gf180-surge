#!/usr/bin/env python3
"""SXT-033 reference renderer (requires the external pinned oracle).

Renders the fixture sequences through the pinned engine for the DECLARED
Classic-family fixture configurations (from inputs/<carrier>.json): the
reference the model budget checks compare against. The isolation overrides
(mute other mixer paths, filters/FX/ws/lowcut off, fbc serial1, FM off,
scene mode Single, retrigger on) are applied by fixture_config.build_instance
with readback verification; they are test configurations, never adapted
presets, and never count toward preset coverage.

Policies inherited from the SXT-012 fixture harness (fixtures/
render_fixture.py): fresh instance per render, controller reset, 0.25 s
settle discarded, block-quantized event scheduling, tail = last event +
tail_s, mono (L+R)/2 int16 PCM, no normalization / time warping / fades,
clipped-sample counts recorded.

Outputs under --out-dir: <carrier>__<seq>-ref.wav + a sidecar JSON with
engine identity, override readback, sha256, determinism repeats.
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
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "classic"))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

SR = 48000


def sha256_file(path):
    return oc.sha256_file(path)


def render_bus(surgepy, oc, seq, carrier, repeats=1):
    """Render `repeats` fresh-instance buses; returns (list_of_mono, info)."""
    monos = []
    total_blocks = 0
    total_samples = 0
    for _r in range(repeats):
        s = fc.build_instance(surgepy, oc, carrier)
        try:
            s.pitchBend(0, 0)
            s.channelController(0, 64, 0)
            s.channelController(0, 1, 0)
            s.channelController(0, 11, 0)
            s.channelAftertouch(0, 0)
            s.allNotesOff()
            bs = int(s.getBlockSize())
            settle_blocks = int(float(seq.get("settle_s", 0.25)) * SR) // bs
            sbuf = s.createMultiBlock(settle_blocks)
            s.processMultiBlock(sbuf)

            events = seq["events"]
            notes = [e for e in events if e["type"] in ("note_on", "note_off")]
            last_t = max(e["t"] for e in notes) if notes else 0
            total_samples = last_t + int(float(seq.get("tail_s", 1.5)) * SR)
            total_blocks = -(-total_samples // bs)
            buf = s.createMultiBlock(total_blocks)
            quant = lambda t: -(-t // bs)  # noqa: E731
            i = 0
            b = 0
            while b < total_blocks:
                while i < len(events) and quant(events[i]["t"]) <= b:
                    e = events[i]
                    if e["type"] == "note_on":
                        s.playNote(e["channel"], e["note"],
                                   e.get("velocity", 100), 0)
                    elif e["type"] == "note_off":
                        s.releaseNote(e["channel"], e["note"],
                                      e.get("velocity", 0))
                    i += 1
                nxt = i
                seg = total_blocks if nxt >= len(events) \
                    else max(quant(events[nxt]["t"]), b + 1)
                s.processMultiBlock(buf, b, seg - b)
                b = seg
            stereo = np.asarray(buf)
            mono = 0.5 * (stereo[0] + stereo[1])
            monos.append(mono)
        finally:
            del s
    clipped = int(np.sum(np.abs(monos[0]) > 1.0))
    hashes = [hashlib.sha256(np.ascontiguousarray(m).tobytes()).hexdigest()
              for m in monos]
    info = {
        "blocks": total_blocks,
        "frames": total_samples,
        "peak_abs_float": float(np.max(np.abs(monos[0]))) if total_samples else 0.0,
        "clipped_samples": clipped,
        "repeats": repeats,
        "repeat_hashes": hashes,
        "bit_identical_repeats": len(set(hashes)) == 1,
    }
    return monos, info


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carrier", required=True, choices=sorted(fc.CARRIERS))
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences",
                                seq_path + ".json")
    with open(seq_path, encoding="utf-8") as f:
        seq = json.load(f)
    inputs_rel = os.path.join(REPO, "model", "oscillators", "classic",
                              "inputs", args.carrier + ".json")
    with open(inputs_rel, encoding="utf-8") as f:
        inputs = json.load(f)

    monos, info = render_bus(surgepy, oc, seq, args.carrier, args.repeats)

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(args.out_dir,
                            "%s__%s-ref.wav" % (args.carrier, seq["id"]))
    oc.write_wav_mono16(wav_path, monos[0], SR)

    # census/blob gate for the source preset
    preset_abs = os.path.join(oc.engine_dir(), inputs["preset_path"])
    blob = oc.git_blob_sha1(preset_abs)
    if blob != inputs["preset_census_blob_sha1"]:
        print("REFUSING: preset blob drift", file=sys.stderr)
        return 2

    sidecar = {
        "schema_version": 1,
        "issue": "SXT-033",
        "carrier": args.carrier,
        "inputs": os.path.relpath(inputs_rel, REPO),
        "sequence": {"id": seq["id"], "path": os.path.relpath(seq_path, REPO)},
        "declared_overrides_applied": [list(o) for o in
                                       inputs["declared_overrides"]],
        "preset_blob_sha1": blob,
        "isolation_note": "declared fixture configuration (one Classic slot "
                          "audible; other mixer paths, filter units, FX, "
                          "waveshaper, lowcut, FM routing off; fbc serial1; "
                          "scene mode Single; retrigger on) - a test "
                          "configuration, never an adapted preset, never "
                          "coverage",
        "render": {"sample_rate": SR, **info},
        "wav": {"path": os.path.relpath(wav_path, REPO),
                "sha256": sha256_file(wav_path)},
        "engine": {"commit": inputs["engine"]["commit"],
                   "surgepy": surgepy.getVersion()},
        "audio_policy": "mono (L+R)/2, int16 PCM, hard clip to [-1,1] "
                        "recorded; no normalization, no time warping, "
                        "no fades",
    }
    side = wav_path + ".json"
    with open(side, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps({"wav": wav_path,
                      "sha256": sidecar["wav"]["sha256"],
                      "bit_identical_repeats": info["bit_identical_repeats"],
                      "clipped": info["clipped_samples"],
                      "peak": round(info["peak_abs_float"], 4)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
