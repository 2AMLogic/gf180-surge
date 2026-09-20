#!/usr/bin/env python3
"""SXT-010: capture one note through the real pinned engine.

Loads a simple factory preset (Basses/Sub 4.fxp: Sine oscillator, Single
scene, no effects, no embedded wavetable — chosen from the SXT-000 census,
which also supplies its verified blob identity), renders exactly 2.000 s of
one note at 48 kHz, and writes a small mono 16-bit WAV plus full timing and
identity metadata. The render is repeated in a fresh engine instance to
measure render-to-render repeatability rather than assume determinism.

The WAV is this project's own render, not redistributed upstream content.
"""

import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oracle_common as oc  # noqa: E402

PRESET_REL = "resources/data/patches_factory/Basses/Sub 4.fxp"
PRESET_CENSUS_SHA = "47d1db8a36d4ff57fa260b927a31f7fb199f755f"
SAMPLE_RATE = 48000
NOTE = 60
VELOCITY = 100
CHANNEL = 0
DETUNE = 0
DURATION_S = 2.0


def render_once(surgepy, preset_abs, block_size):
    # createSurge() sets samplerate, tempo=120 and ppqPos=0 internally
    # (src/surge-python/surgepy.cpp createSurge).
    s = surgepy.createSurge(float(SAMPLE_RATE))
    ok = s.loadPatch(preset_abs)
    blocks = int(DURATION_S * SAMPLE_RATE / block_size)
    sample_count = blocks * block_size
    s.playNote(CHANNEL, NOTE, VELOCITY, DETUNE)
    t0 = time.time()
    buf = s.createMultiBlock(blocks)
    s.processMultiBlock(buf)
    wall = time.time() - t0
    s.allNotesOff()
    # mono downmix (L+R)/2, first sample_count samples across channels
    stereo = np.asarray(buf)
    left = stereo[0, :sample_count]
    right = stereo[1, :sample_count]
    mono = 0.5 * (left + right)
    return ok, sample_count, blocks, mono, wall, buf.shape


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    oc.reexec_under_pinned_python(repo)
    out_dir = os.path.join(repo, "reports", "sxt-010", "first-capture")
    os.makedirs(out_dir, exist_ok=True)

    preset_abs = os.path.join(oc.data_home(), os.path.relpath(PRESET_REL, "resources/data"))
    actual_sha = oc.git_blob_sha1(preset_abs)
    if actual_sha != PRESET_CENSUS_SHA:
        print(f"REFUSING: preset blob {actual_sha} != census {PRESET_CENSUS_SHA}", file=sys.stderr)
        return 2

    oc.apply_engine_env()
    surgepy = oc.import_surgepy()

    probe = surgepy.createSurge(float(SAMPLE_RATE))
    block_size = probe.getBlockSize()
    del probe

    ok1, n1, blocks1, mono1, wall1, shape1 = render_once(surgepy, preset_abs, block_size)
    ok2, n2, blocks2, mono2, wall2, _ = render_once(surgepy, preset_abs, block_size)

    if not ok1:
        print("REFUSING: preset did not load", file=sys.stderr)
        return 3

    wav_path = os.path.join(out_dir, "first-note.wav")
    oc.write_wav_mono16(wav_path, mono1, SAMPLE_RATE)

    diff = float(np.max(np.abs(mono1 - mono2))) if n1 == n2 else None
    identical = bool(n1 == n2 and np.array_equal(mono1, mono2))
    peak = float(np.max(np.abs(mono1)))

    meta = {
        "issue": "SXT-010",
        "what": "first note captured through the pinned native engine (own render, mono 16-bit, ~2 s; not upstream content)",
        "engine_commit": json.load(open(os.path.join(repo, "oracle", "manifest.json")))["engine"]["commit"],
        "preset": {
            "path": PRESET_REL,
            "census_blob_sha1": PRESET_CENSUS_SHA,
            "actual_blob_sha1": actual_sha,
            "selection_reason": "factory bass; Sine oscillator, Single scene, 0 non-Off FX slots, 0 modroutings, no embedded wavetable (census columns)",
            "load_ok": ok1,
        },
        "render": {
            "sample_rate": SAMPLE_RATE,
            "block_size_samples": block_size,
            "blocks": blocks1,
            "sample_count": n1,
            "duration_s": DURATION_S,
            "note_number": NOTE,
            "velocity": VELOCITY,
            "channel": CHANNEL,
            "detune_value": DETUNE,
            "tempo_bpm": 120,
            "note_off_sent": False,
            "tail_note": "single held note; release/tail behavior is a later fixture concern (SXT-012)",
            "multiblock_shape": list(shape1),
            "render_wall_seconds": [round(wall1, 4), round(wall2, 4)],
            "processing": "stereo float out, downmixed (L+R)/2, clipped to [-1,1], scaled by 32767 to int16 PCM; no normalization",
        },
        "files": {
            "wav": "reports/sxt-010/first-capture/first-note.wav",
            "wav_sha256": oc.sha256_file(wav_path),
            "wav_bytes": os.path.getsize(wav_path),
        },
        "repeatability": {
            "second_render_fresh_instance": True,
            "bit_identical": identical,
            "max_abs_diff_float": diff,
            "note": "measured, not assumed; engine RNG is not overridden by the harness",
        },
        "environment": json.load(open(os.path.join(repo, "oracle", "manifest.json")))["environment"],
        "peak_abs_float": peak,
    }
    with open(os.path.join(out_dir, "first-note.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps({k: meta[k] for k in ("files", "render", "repeatability")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
