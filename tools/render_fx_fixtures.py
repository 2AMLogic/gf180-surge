#!/usr/bin/env python3
"""SXT-023 reference fixtures: stereo float renders of the chosen presets.

 Inherits the SXT-012 render policies by importing fixtures/render_fixture.py
 (fresh instance per bus, census-blob-verified load, controller reset, 0.25 s
 settle, block-quantized scheduling, identical tails). Differences, declared:

  * AUDIO: stereo float32 WAV (IEEE format 3), unclipped and un-normalized.
    The SXT-012 committed bus is mono 16-bit; the delay/EQ slice needs the
    stereo field (crossfeed, width, pan) and a wider word than int16 to keep
    the model-vs-reference comparison inside the effect's own error budget,
    so SXT-023 renders its own reference buses and records hashes.
  * DETERMINISM GATE: every fixture is rendered 3x per bus; all three float
    buffers must be bit-identical (sha256) for the fixture to be committed.
    This proves the wet bus's pre-effect signal equals the all-off dry bus
    (dry is a separate fresh instance) for the presets' determinism class.
  * TEMPO: unchanged - no transport-tempo setter. Tempo-synced behavior is
    exercised through patch-stored tempo (tempoOnSave applied by loadPatch),
    which is engine behavior, not a harness event.

WAVs are this project's own renders of loaded presets (not redistributed
upstream content). Original tool, Apache-2.0.
"""

import argparse
import hashlib
import json
import math
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "fixtures"))

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402
import render_fixture as rf  # noqa: E402  (SXT-012 harness: policies inherited)

SR = 48000
FX_SLOTS = 16

PRESETS = {
    "metallic": "resources/data/patches_factory/Plucks/Metallic.fxp",
    "fm_bass_1": "resources/data/patches_factory/Basses/FM Bass 1.fxp",
    "dexie": "resources/data/patches_3rdparty/John Valentine/Keys/Dexie Swirly E-Piano.fxp",
}
SEQUENCES = ["seq-notes-coverage-v1"]


class Refuse(Exception):
    pass


def sha256_buf(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def write_wav_stereo_f32(path, stereo):
    """IEEE float32 stereo WAV (format tag 3), no clipping, no normalization."""
    nch, frames = stereo.shape
    data = np.ascontiguousarray(stereo.T, dtype="<f4").tobytes()
    byte_rate = SR * nch * 4
    block_align = nch * 4
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, nch, SR, byte_rate, block_align, 32)
    hdr += b"data" + struct.pack("<I", len(data))
    with open(path, "wb") as f:
        f.write(hdr + data)


def render_bus_stereo(surgepy, preset_abs, seq, fx_off, repeats=3):
    """Render the bus `repeats` times in fresh instances; return buffers+info.

    Refuses unless all repeats are bit-identical (determinism gate).
    """
    bufs = []
    infos = []
    import surgepy.constants as C

    for _ in range(repeats):
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
            types_after = None
            if fx_off:
                for i in range(FX_SLOTS):
                    s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
            bs = int(s.getBlockSize())
            settle_blocks = int(seq.get("settle_s", 0.25) * SR) // bs
            sbuf = s.createMultiBlock(settle_blocks)
            s.processMultiBlock(sbuf)
            if fx_off:
                types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                         for i in range(FX_SLOTS)]
                if any(t != C.fxt_off for t in types):
                    raise Refuse(f"dry render: FX types did not read back Off: {types}")
                types_after = types
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
                nxt = rf.dispatch(s, events[dispatched:], b, quant) + dispatched
                if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                    raise Refuse("scheduler failed to advance")
                seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
                s.processMultiBlock(buf, b, seg - b)
                b = seg
                dispatched = nxt
            stereo = np.asarray(buf, dtype=np.float32).copy()
            bufs.append(stereo)
            infos.append({
                "blocks": total_blocks,
                "frames": total_blocks * bs,
                "peak_abs": float(np.max(np.abs(stereo))) if stereo.size else 0.0,
                "fx_types_readback": types_after,
            })
        finally:
            del s
    hashes = [sha256_buf(x) for x in bufs]
    if any(h != hashes[0] for h in hashes):
        raise Refuse(f"determinism gate failed over {repeats} repeats: {hashes}")
    return bufs[0], hashes, infos[0]


def render_fixture(surgepy, slug, rel_path, seq_id, out_dir):
    seq, seq_path, seq_sha = rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    blob, graphs = census_entry(rel_path)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise Refuse(f"census blob mismatch: {rel_path}")

    wet, wet_hashes, winfo = render_bus_stereo(surgepy, abs_path, seq, False)
    dry, dry_hashes, dinfo = render_bus_stereo(surgepy, abs_path, seq, True)

    os.makedirs(out_dir, exist_ok=True)
    wet_path = os.path.join(out_dir, f"{slug}__{seq_id}-wet.f32.wav")
    dry_path = os.path.join(out_dir, f"{slug}__{seq_id}-dry.f32.wav")
    write_wav_stereo_f32(wet_path, wet)
    write_wav_stereo_f32(dry_path, dry)

    sidecar = {
        "schema_version": 1,
        "fixture_id": f"{slug}__{seq_id}",
        "issue": "SXT-023",
        "claim_scope": "reference-vs-reference wet/dry buses of the pinned engine "
                       "under the SXT-012 policies; no fidelity/support/quality claim",
        "preset": {
            "slug": slug,
            "path": rel_path,
            "census_blob_sha1": blob,
            "graphs_sha256_prefix": graphs["sha"][:16],
        },
        "sequence": {"id": seq_id, "sha256": seq_sha},
        "render": {
            "sample_rate": SR,
            "block_size": 32,
            "frames": winfo["frames"],
            "duration_s": round(winfo["frames"] / SR, 6),
            "policies_inherited": "fixtures/render_fixture.py (reset/scheduling/tail/"
                                  "dry-bypass); see fixtures/README.md",
            "tail_s": seq.get("tail_s", 2.5),
            "settle_s": seq.get("settle_s", 0.25),
        },
        "audio_policy": "stereo float32 (IEEE fmt 3), raw engine output, no clip, "
                        "no normalization, no fades",
        "determinism_gate": {
            "repeats": 3,
            "wet_sha256_all": wet_hashes,
            "dry_sha256_all": dry_hashes,
            "bit_identical": True,
        },
        "wet": {
            "wav": os.path.relpath(wet_path, REPO),
            "sha256": rf.sha256_file(wet_path),
            "bytes": os.path.getsize(wet_path),
            "peak_abs_float": winfo["peak_abs"],
        },
        "dry": {
            "wav": os.path.relpath(dry_path, REPO),
            "sha256": rf.sha256_file(dry_path),
            "bytes": os.path.getsize(dry_path),
            "peak_abs_float": dinfo["peak_abs"],
            "bypass_method": "all 16 FX-slot type params -> fxt_off via setParamVal "
                             "before settle; read-back verified Off; fresh instance",
            "dry_fx_bypass_verified": dinfo["fx_types_readback"] == [0] * FX_SLOTS,
        },
        "engine": rf.engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "tool": rf.tool_version(),
    }
    sp = os.path.join(out_dir, f"{slug}__{seq_id}.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"rendered {slug}__{seq_id}: wet {sidecar['wet']['sha256'][:12]} "
          f"dry {sidecar['dry']['sha256'][:12]} peak {winfo['peak_abs']:.4f}")
    return sidecar


def census_entry(rel_path):
    import csv

    csv_path = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                break
        else:
            raise Refuse(f"preset not in census: {rel_path}")
    graphs_line = None
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel_path:
                graphs_line = g
                break
    if graphs_line is None or graphs_line.get("st") != "normalized":
        raise Refuse(f"preset missing/abnormal in graphs.jsonl: {rel_path}")
    return row["git_blob_sha1"], graphs_line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "sxt-023", "fixtures"))
    ap.add_argument("--presets", help="comma-separated subset")
    args = ap.parse_args()
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    slugs = args.presets.split(",") if args.presets else sorted(PRESETS)
    for slug in slugs:
        for seq_id in SEQUENCES:
            render_fixture(surgepy, slug, PRESETS[slug], seq_id, args.out_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
