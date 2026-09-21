#!/usr/bin/env python3
"""SXT-026 reference renderer (requires the external pinned oracle).

Renders the fixture sequences through the pinned engine for:

  * the UNMODIFIED preset (`--original`): the complete wet reference. The
    preset has all 16 FX slots Off, so its wet sound is FX-free by the
    patch's own state — no effect is substituted or bypassed (documented
    choice per issue #19; nothing here is an adapted preset).
  * the DECLARED WT-validation fixture configurations (from an inputs JSON):
    the wet reference the model budget checks compare against.

Policies inherited from the SXT-012 fixture harness (fixtures/
render_fixture.py): fresh instance per render, controller reset, 0.25 s
settle discarded, block-quantized event scheduling, tail = last event +
tail_s, mono (L+R)/2 int16 PCM, no normalization / time warping / fades,
clipped-sample counts recorded.

Outputs under --out-dir: <inputs-name>__<seq>-ref.wav + a sidecar JSON with
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
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "wavetable"))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

SR = 48000


def sha256_file(path):
    return oc.sha256_file(path)


def render_bus(surgepy, oc, seq, overrides, repeats=1, preset_rel=fc.PRESET_REL):
    """Render `repeats` fresh-instance buses; returns (list_of_mono, info)."""
    monos = []
    for r in range(repeats):
        s = fc.build_instance(surgepy, oc, overrides, preset_rel)
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
                        s.playNote(e["channel"], e["note"], e.get("velocity", 100), 0)
                    elif e["type"] == "note_off":
                        s.releaseNote(e["channel"], e["note"], e.get("velocity", 0))
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
    info = {
        "blocks": total_blocks,
        "frames": total_samples,
        "peak_abs_float": float(np.max(np.abs(monos[0]))) if total_samples else 0.0,
        "clipped_samples": clipped,
        "repeats": repeats,
        "repeat_hashes": [hashlib.sha256(np.ascontiguousarray(m).tobytes()).hexdigest()
                          for m in monos],
        "bit_identical_repeats": len({h for h in
                                      [hashlib.sha256(np.ascontiguousarray(m).tobytes()).hexdigest()
                                       for m in monos]}) == 1,
    }
    return monos, info


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", required=True,
                    help="inputs/<name>.json (declared fixture config)")
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--original", action="store_true",
                    help="render the UNMODIFIED preset (wet, FX-free by "
                         "patch state) instead of the fixture config")
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
    with open(args.inputs, encoding="utf-8") as f:
        inputs = json.load(f)

    overrides = [] if args.original else \
        [tuple(o) for o in inputs.get("declared_overrides", [])]
    monos, info = render_bus(surgepy, oc, seq, overrides, args.repeats,
                             inputs["preset_path"])

    os.makedirs(args.out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(args.inputs))[0]
    wav_path = os.path.join(args.out_dir,
                            "%s__%s-ref.wav" % (name, seq["id"]))
    oc.write_wav_mono16(wav_path, monos[0], SR)

    # census/blob gate for the source preset
    preset = fc.preset_abs(oc, inputs["preset_path"])
    blob = oc.git_blob_sha1(preset)
    if blob != inputs["preset_census_blob_sha1"]:
        print("REFUSING: preset blob drift", file=sys.stderr)
        return 2

    sidecar = {
        "schema_version": 1,
        "issue": "SXT-026",
        "inputs": os.path.relpath(args.inputs, REPO),
        "sequence": {"id": seq["id"], "path": os.path.relpath(seq_path, REPO)},
        "original_preset_render": bool(args.original),
        "declared_overrides_applied": [list(o) for o in overrides],
        "preset_blob_sha1": blob,
        "wt_sha256": inputs["wt_sha256"],
        "fx_note": "preset has all 16 FX slots Off (normalized graph): the "
                   "wet render is FX-free by patch state; no substitution, "
                   "no bypass",
        "render": {"sample_rate": SR, **info},
        "wav": {"path": os.path.relpath(wav_path, REPO),
                "sha256": sha256_file(wav_path)},
        "engine": {"commit": inputs.get("engine_version"),
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
