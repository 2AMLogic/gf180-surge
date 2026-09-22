#!/usr/bin/env python3
"""SXT-032: render the LFO-slice reference fixtures through the pinned oracle.

Fixture = factory preset `Basses/Attacky.fxp` (census-blob verified, the
landed SXT-022 voice-slice preset) PLUS the two modulation routes declared in
`model/voice/attacky_lfo_inputs.json`, added at runtime through the engine's
host modulation API (`setModDepth01`, LFO1 -> Filter 1 Cutoff / Resonance).
The engine render of this configuration is the oracle reference for the leaf.

Policies (fixtures/render_fixture.py conventions):
  RESET    fresh surgepy instance per render; blob-verified loadPatch;
           controller reset (bend/CC64/CC1/CC11/pressure/allNotesOff);
           settle 0.25 s discarded before t=0.
  ROUTES   applied after loadPatch, before settle, from the committed
           extractor sidecar (normalized depths; read back and verified).
  SCHED    event times are integer samples at 48 kHz, ceil-quantized to
           32-sample block starts (identical to render_fixture.render_bus).
  TAIL     render span = last event + tail_s, whole blocks.
  AUDIO    mono (L+R)/2, int16 PCM, hard clip [-1, 1] (clipped count
           recorded). No normalization, no time warping, no fades.
  DET      three fresh-instance repeats; sha256 of the raw float mono buffer
           must be identical (determinism gate, SXT-012 class).

Run under the pinned interpreter (auto re-exec via oracle_common).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402

SR = 48000
FX_SLOTS = 16
PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
LFO_INPUTS = os.path.join(REPO, "model", "voice", "attacky_lfo_inputs.json")
SEQ_DIR = os.path.join(REPO, "fixtures", "sequences")


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def census_blob():
    import csv

    with open(os.path.join(REPO, "corpus", "census-v0.1", "results",
                           "per-preset.csv"), newline="",
              encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == PRESET_REL:
                return row["git_blob_sha1"]
    raise Refuse("preset not in census")


def load_sequence(ref):
    path = ref if os.path.sep in ref or ref.endswith(".json") \
        else os.path.join(SEQ_DIR, ref + ".json")
    with open(path, encoding="utf-8") as f:
        seq = json.load(f)
    if seq.get("schema_version") != 1:
        raise Refuse(f"{path}: unsupported schema_version")
    return seq, path


def render_bus(surgepy, preset_abs, seq, routes):
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

        import surgepy.constants as C

        applied = []
        for r in routes:
            key = r["dest_param"]
            target = s.getPatch()["scene"][0]["filterunit"][0][key]
            ms = s.getModSource(C.ms_lfo1)
            if not s.isValidModulation(target, ms):
                raise Refuse(f"modulation invalid: {key}")
            s.setModDepth01(target, ms, r["normalized_depth"], 0, 0)
            got = s.getModDepth01(target, ms, 0, 0)
            if abs(got - r["normalized_depth"]) > 1e-6:
                raise Refuse(f"route depth readback {got} for {key}")
            applied.append({**r, "depth_readback": got})

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
            i = dispatched
            while i < len(events) and quant(events[i]["t"]) <= b:
                e = events[i]
                if e["type"] == "note_on":
                    s.playNote(e["channel"], e["note"], e["velocity"], 0)
                elif e["type"] == "note_off":
                    s.releaseNote(e["channel"], e["note"], 0)
                elif e["type"] == "cc":
                    s.channelController(e["channel"], e["controller"],
                                        e["value"])
                i += 1
            nxt = i
            if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                raise Refuse("scheduler failed to advance")
            seg = total_blocks if nxt >= len(events) \
                else max(quant(events[nxt]["t"]), b + 1)
            s.processMultiBlock(buf, b, seg - b)
            b = seg
            dispatched = nxt

        stereo = np.asarray(buf)
        mono = 0.5 * (stereo[0] + stereo[1])
        info = {
            "blocks": total_blocks,
            "frames": int(total_blocks * bs),
            "peak_abs_float": float(np.max(np.abs(mono))) if len(mono) else 0.0,
            "clipped_samples": int(np.sum(np.abs(mono) > 1.0)),
            "last_event_sample": int(last_t),
            "tail_s": tail_s,
            "settle_s": float(seq.get("settle_s", 0.25)),
            "routes_applied": applied,
        }
        return mono, info
    finally:
        del s


def tool_version():
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                                capture_output=True, text=True,
                                check=True).stdout.strip()
    except Exception as e:  # pragma: no cover
        commit = f"unavailable: {e}"
    return {"repo_commit": commit,
            "script_sha256": sha256_file(os.path.abspath(__file__))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sequence", required=True,
                    help="sequence id (fixtures/sequences) or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    with open(LFO_INPUTS, encoding="utf-8") as f:
        lfo_in = json.load(f)

    preset_abs = os.path.join(oc.data_home(), PRESET_REL[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse("pinned-engine preset not found; set ORACLE_SURGE_DIR")
    expected = lfo_in["preset"]["census_blob_sha1"]
    actual = oc.git_blob_sha1(preset_abs)
    if actual != expected:
        raise Refuse(f"preset blob {actual} != extractor {expected}")

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    seq, seq_path = load_sequence(args.sequence)

    routes = lfo_in["fixture_routes"]
    renders = []
    hashes = []
    info = None
    for _ in range(args.repeats):
        mono, info = render_bus(surgepy, preset_abs, seq, routes)
        hashes.append(hashlib.sha256(
            np.ascontiguousarray(mono).tobytes()).hexdigest())
        renders.append(mono)
    identical = all(h == hashes[0] for h in hashes)
    if not identical:
        raise Refuse(f"reference renders not bit-identical: {hashes}")

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(args.out_dir,
                            f"reference-{seq['id']}-lfo-fixture.wav")
    oc.write_wav_mono16(wav_path, renders[0], SR)

    sidecar = {
        "schema_version": 1,
        "issue": "SXT-032",
        "fixture_id": f"attacky-lfo__{seq['id']}",
        "preset": {
            "path": PRESET_REL,
            "census_blob_sha1": expected,
            "actual_blob_sha1": actual,
        },
        "fixture_modification": "two modulation routes added at runtime via "
                                "setModDepth01 (host modulation API) after "
                                "loadPatch; preset file untouched; synthetic "
                                "declared fixture on the landed voice slice",
        "routes": info["routes_applied"],
        "sequence": {"id": seq["id"],
                     "sha256": sha256_file(seq_path),
                     "path": os.path.relpath(seq_path, REPO)},
        "render": {"sample_rate": SR,
                   "scheduling": "block-quantized (32 samples), ceil to next "
                                 "block start",
                   **{k: v for k, v in info.items() if k != "routes_applied"}},
        "determinism": {"repeats": args.repeats, "sha256": hashes,
                        "bit_identical": identical},
        "audio_policy": "mono (L+R)/2, int16 PCM, hard clip [-1,1], no "
                        "normalization, no time warping, no fades",
        "wav": os.path.relpath(wav_path, REPO),
        "wav_sha256": sha256_file(wav_path),
        "tool": tool_version(),
        "engine": {"commit": lfo_in["engine"]["commit"],
                   "version_string": lfo_in["engine"]["version_string"]},
    }
    with open(os.path.join(args.out_dir, f"reference-{seq['id']}.json"),
              "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({"wav": sidecar["wav"],
                      "wav_sha256": sidecar["wav_sha256"],
                      "frames": info["frames"],
                      "deterministic": identical}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
