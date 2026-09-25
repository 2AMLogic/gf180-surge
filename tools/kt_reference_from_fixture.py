#!/usr/bin/env python3
"""SXT-042: derive the mono int16 DRY reference render for the keytrack
carrier from the COMMITTED, sha-pinned SXT-025 pinned-engine fixture.

This does **not** render anything and does **not** substitute an engine: it
reproduces, byte-for-byte, the two documented steps the oracle-side renderer
(`tools/render_leaf48_reference.py`) applies to the engine's stereo output
after `processMultiBlock`:

    mono   = 0.5 * (stereo[0] + stereo[1])            # float32 domain
    int16  = int(clamp(x, -1, 1) * 32767.0)           # oracle_common.write_wav_mono16

The input is `reports/sxt-025/fixtures/hells_bells__sxt025-accept-v1-dry.f32.wav`
— the pinned engine's dry bus (all 16 FX slots set to `fxt_off` and
read-back verified, fresh instance, 0.25 s settle, block-quantized
scheduling), committed under SXT-025 with a 3x bit-identical determinism
gate and a sha256 recorded in its manifest.

Fail-closed (`Refuse` -> exit 2): manifest sha mismatch, unexpected WAV
format/rate/channel count, frame-count or peak disagreement with the
manifest.

Scope discipline: this yields a pinned-engine REFERENCE for a preset whose
content carries a live keytrack route. It does not make any new engine
measurement, and it cannot stand in for a render of a configuration the
pinned engine has not actually produced (a runtime-added route, a different
sequence, a different preset). Those remain NOT_RUN without an oracle host.

Usage:
  python3 tools/kt_reference_from_fixture.py --out reports/SXT-042/artifacts/\
reference-sxt025-accept-v1-bells-dry.wav [--json OUT.json]
"""

import argparse
import hashlib
import io
import json
import os
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import oracle_common as oc  # noqa: E402

MANIFEST = os.path.join(REPO, "reports", "sxt-025", "fixtures",
                        "hells_bells__sxt025-accept-v1.json")
SR = 48000


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_f32_wav(path):
    """Minimal IEEE-float WAV reader (the `wave` module refuses fmt 3)."""
    raw = open(path, "rb").read()
    f = io.BytesIO(raw)
    if f.read(4) != b"RIFF" or (f.read(4) and f.read(4) != b"WAVE"):
        raise Refuse(f"{path}: not a RIFF/WAVE file")
    fmt = None
    data = None
    while True:
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        cid, sz = struct.unpack("<4sI", hdr)
        body = f.read(sz + (sz % 2))
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            data = body[:sz]
    if fmt is None or data is None:
        raise Refuse(f"{path}: missing fmt/data chunk")
    audio_fmt, channels, rate, _, _, bits = fmt
    if audio_fmt != 3 or bits != 32:
        raise Refuse(f"{path}: expected IEEE float32 (fmt 3/32), got "
                     f"fmt {audio_fmt}/{bits}")
    if channels != 2:
        raise Refuse(f"{path}: expected stereo, got {channels} channels")
    if rate != SR:
        raise Refuse(f"{path}: expected {SR} Hz, got {rate}")
    return np.frombuffer(data, dtype="<f4").reshape(-1, 2).T


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--bus", default="dry", choices=("dry", "wet"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--json", help="write the provenance record here")
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as f:
        man = json.load(f)
    rec_bus = man[args.bus]
    src = os.path.join(REPO, rec_bus["wav"])
    if not os.path.exists(src):
        raise Refuse(f"committed fixture missing: {src}")
    got_sha = sha256_file(src)
    if got_sha != rec_bus["sha256"]:
        raise Refuse(f"fixture sha256 {got_sha} != manifest "
                     f"{rec_bus['sha256']}")
    if not man["determinism_gate"]["bit_identical"]:
        raise Refuse("fixture determinism gate is not bit_identical")
    if man["engine"]["sample_rate"] != SR:
        raise Refuse("fixture engine sample rate != 48000")

    stereo = read_f32_wav(src)
    frames = stereo.shape[1]
    if frames != man["render"]["frames"]:
        raise Refuse(f"frames {frames} != manifest {man['render']['frames']}")
    peak = float(np.abs(stereo).max())
    if abs(peak - rec_bus["peak_abs_float"]) > 0:
        raise Refuse(f"peak {peak} != manifest {rec_bus['peak_abs_float']}")

    mono = 0.5 * (stereo[0] + stereo[1])        # render_leaf48_reference.py
    if mono.dtype != np.float32:
        raise Refuse(f"mono law left float32 domain: {mono.dtype}")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    oc.write_wav_mono16(args.out, mono, SR)

    rec = {
        "issue": "SXT-042",
        "claim": ("mono int16 projection of a COMMITTED pinned-engine render; "
                  "no new engine measurement was made by this tool"),
        "source_fixture": rec_bus["wav"],
        "source_sha256": got_sha,
        "source_manifest": os.path.relpath(args.manifest, REPO),
        "bus": args.bus,
        "engine": man["engine"],
        "preset": man["preset"],
        "sequence": man["sequence"],
        "frames": frames,
        "mono_law": "0.5*(L+R) in float32, then int(clamp(x,-1,1)*32767)",
        "out": os.path.relpath(os.path.abspath(args.out), REPO),
        "out_sha256": sha256_file(args.out),
        "peak_abs_float": peak,
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
    print(json.dumps(rec, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
