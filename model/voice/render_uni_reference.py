#!/usr/bin/env python3
"""SXT-034: render unison-stack reference audio through the pinned engine.

Mirrors the SXT-012 render policies (RESET / SCHEDULING / TAIL / AUDIO,
`fixtures/render_fixture.py`) with the SXT-034 declared override applied
after loadPatch: scene A osc1 unison-voices set via the official host
parameter path (setParamVal), read back and verified; optionally retrigger
forced off for the mechanism fixture (quantified-variation class -- no
fidelity claim possible, see fixtures/README.md).

The committed SXT-034 reference WAVs are this project's own renders of the
loaded preset under a declared test configuration on a real corpus carrier;
they are NOT committed library fixtures and support no coverage claim.

Output: WAV + sidecar JSON under --out-dir; --repeats N additionally renders
N fresh instances and records per-render sha256 (determinism class).
"""

import argparse
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402

SR = 48000
PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")


class Refuse(Exception):
    pass


def census_blob(rel):
    import csv
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_sequence(ref):
    if os.path.sep not in ref:
        path = os.path.join(REPO, "fixtures", "sequences", ref + ".json")
    else:
        path = ref if os.path.isabs(ref) else os.path.join(os.getcwd(), ref)
    with open(path, encoding="utf-8") as f:
        seq = json.load(f)
    if seq.get("schema_version") != 1:
        raise Refuse(f"{path}: unsupported schema_version")
    if seq.get("sample_rate") != SR:
        raise Refuse(f"{path}: sample_rate must be {SR}")
    return seq, path, sha256_file(path)


def render_bus(surgepy, preset_abs, seq, unison, nodraw):
    """One full render in a fresh instance (SXT-012 policies + override)."""
    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse(f"loadPatch failed: {preset_abs}")
        s.pitchBend(0, 0)
        s.channelController(0, 64, 0)
        s.channelController(0, 1, 0)
        s.channelController(0, 11, 0)
        s.channelAftertouch(0, 0)
        s.allNotesOff()

        osc1 = s.getPatch()["scene"][0]["osc"][0]
        s.setParamVal(osc1["p"][6], float(unison))
        if int(round(s.getParamVal(osc1["p"][6]))) != unison:
            raise Refuse("unison override readback mismatch")
        if nodraw:
            s.setParamVal(osc1["retrigger"], 0.0)

        bs = int(s.getBlockSize())
        settle_blocks = int(seq.get("settle_s", 0.25) * SR) // bs
        sbuf = s.createMultiBlock(settle_blocks)
        s.processMultiBlock(sbuf)

        events = seq["events"]
        notes = [e for e in events if e["type"] in ("note_on", "note_off")]
        last_t = max(e["t"] for e in notes) if notes else 0
        tail_s = float(seq.get("tail_s", 2.5))
        total_samples = last_t + int(tail_s * SR)
        total_blocks = -(-total_samples // bs)
        buf = s.createMultiBlock(total_blocks)

        quant = lambda t: -(-t // bs)  # noqa: E731
        dispatched = 0
        b = 0
        while b < total_blocks:
            i = 0
            while i < len(events[dispatched:]) and quant(events[dispatched + i]["t"]) <= b:
                e = events[dispatched + i]
                if e["type"] == "note_on":
                    s.playNote(e["channel"], e["note"], e["velocity"], 0)
                elif e["type"] == "note_off":
                    s.releaseNote(e["channel"], e["note"], e.get("velocity", 0))
                elif e["type"] == "cc":
                    s.channelController(e["channel"], e["controller"], e["value"])
                i += 1
            nxt = dispatched + i
            if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                raise Refuse("scheduler failed to advance")
            seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
            s.processMultiBlock(buf, b, seg - b)
            b = seg
            dispatched = nxt

        stereo = np.asarray(buf)
        mono = 0.5 * (stereo[0] + stereo[1])
        return mono, {
            "blocks": total_blocks,
            "frames": total_blocks * bs,
            "peak_abs_float": float(np.max(np.abs(mono))) if total_blocks else 0.0,
            "clipped_samples": int(np.sum(np.abs(mono) > 1.0)),
        }
    finally:
        del s


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--unison", type=int, required=True)
    ap.add_argument("--nodraw", action="store_true",
                    help="retrigger off (mechanism fixture; variation class)")
    ap.add_argument("--repeats", type=int, default=1,
                    help="fresh-instance renders for the determinism record")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    if not (1 <= args.unison <= 16):
        raise Refuse(f"unison {args.unison} outside 1..16")

    expected = census_blob(PRESET_REL)
    preset_abs = os.path.join(oc.data_home(), PRESET_REL[len("resources/data/"):])
    actual = oc.git_blob_sha1(preset_abs)
    if actual != expected:
        raise Refuse(f"preset blob {actual} != census {expected}")

    seq, seq_path, seq_sha = load_sequence(args.sequence)

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    renders, hashes = [], []
    for _ in range(args.repeats):
        mono, info = render_bus(surgepy, preset_abs, seq, args.unison, args.nodraw)
        hashes.append(hashlib.sha256(np.ascontiguousarray(mono).tobytes()).hexdigest())
        renders.append(mono)

    os.makedirs(args.out_dir, exist_ok=True)
    name = f"reference-{seq['id']}-uni{args.unison}{'-nodraw' if args.nodraw else ''}"
    wav_path = os.path.join(args.out_dir, name + ".wav")
    oc.write_wav_mono16(wav_path, renders[0], SR)

    sidecar = {
        "schema_version": 1,
        "issue": "SXT-034",
        "fixture": name,
        "preset": {
            "path": PRESET_REL,
            "census_blob_sha1": expected,
            "actual_blob_sha1": actual,
        },
        "sequence": {"id": seq["id"], "sha256": seq_sha,
                     "path": os.path.relpath(seq_path, REPO)},
        "declared_override": {
            "kind": "test configuration on a real corpus carrier "
                    "(SXT-012 declared-override pattern)",
            "unison_voices": args.unison,
            "retrigger_forced_off": bool(args.nodraw),
            "determinism_class": "bit-identical expected (retrigger on)"
                                 if not args.nodraw else
                                 "quantified variation (free-running init "
                                 "phase; no reference-fidelity claim)",
        },
        "render": {
            "sample_rate": SR,
            "scheduling": "block-quantized (32 samples), ceil to next block start",
            **{k: v for k, v in info.items()},
        },
        "repeats": args.repeats,
        "render_sha256": hashes,
        "bit_identical_across_repeats": all(h == hashes[0] for h in hashes),
        "wav": os.path.relpath(wav_path, REPO),
        "wav_sha256": sha256_file(wav_path),
        "audio_policy": "mono (L+R)/2, int16 PCM, hard clip to [-1,1], no "
                        "normalization, no time warping, no fades",
        "engine": {
            "commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
            "version_string": surgepy.getVersion(),
            "sample_rate": SR,
        },
    }
    with open(os.path.join(args.out_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({k: sidecar[k] for k in
                      ("fixture", "render_sha256", "bit_identical_across_repeats",
                       "wav_sha256")} | {"frames": info["frames"],
                                        "peak": info["peak_abs_float"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
