#!/usr/bin/env python3
"""SXT-012: comparator / integrity verifier for committed render fixtures.

Recomputes hashes and re-reads WAV headers for every fixture listed in
fixtures/manifest.json and refuses (exit 2) on any mismatch:

  - WAV file missing or sha256 differs from the manifest / per-fixture sidecar;
  - per-fixture sidecar missing, or disagreeing with the manifest;
  - sequence library file missing, or its sha256 differing from the recorded
    library hash (the fixture no longer corresponds to its versioned sequence);
  - WAV header (sample rate, frames, channels, bit width) disagreeing with the
    recorded metadata;
  - manifest totals inconsistent with the fixture table.

This is an integrity/comparator check only. Passing it establishes that the
committed audio is exactly the recorded render of the recorded sequence under
the recorded environment; it establishes no fidelity or support claim.
"""

import argparse
import hashlib
import json
import os
import sys
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(REPO, "fixtures", "manifest.json")
SEQ_DIR = os.path.join(REPO, "fixtures", "sequences")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wav_info(path):
    with wave.open(path, "rb") as w:
        return {
            "channels": w.getnchannels(),
            "sampwidth_bytes": w.getsampwidth(),
            "framerate": w.getframerate(),
            "frames": w.getnframes(),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=MANIFEST_PATH)
    ap.add_argument("--fixture", help="verify a single fixture_id")
    args = ap.parse_args()

    failures = []
    if not os.path.exists(args.manifest):
        print(f"REFUSING: manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    with open(args.manifest, encoding="utf-8") as f:
        man = json.load(f)

    fixtures = man.get("fixtures", [])
    if args.fixture:
        fixtures = [fx for fx in fixtures if fx["fixture_id"] == args.fixture]
        if not fixtures:
            print(f"REFUSING: fixture_id not in manifest: {args.fixture}", file=sys.stderr)
            return 2

    for fx in fixtures:
        fid = fx["fixture_id"]
        checks = []

        def check(name, ok, detail=""):
            checks.append((name, ok, detail))
            if not ok:
                failures.append(f"{fid}: {name}: {detail}")

        # sidecar presence + agreement
        sidecar_rel = fx.get("sidecar")
        sidecar = None
        if sidecar_rel and os.path.exists(os.path.join(REPO, sidecar_rel)):
            with open(os.path.join(REPO, sidecar_rel), encoding="utf-8") as f:
                sidecar = json.load(f)
        else:
            check("sidecar_present", False, str(sidecar_rel))
        if sidecar:
            check("sidecar_agrees_wet_hash", sidecar.get("wet", {}).get("sha256") == fx["wet"]["sha256"],
                  f"sidecar={sidecar.get('wet', {}).get('sha256')} manifest={fx['wet']['sha256']}")
            check("sidecar_agrees_dry_hash", sidecar.get("dry", {}).get("sha256") == fx["dry"]["sha256"],
                  f"sidecar={sidecar.get('dry', {}).get('sha256')} manifest={fx['dry']['sha256']}")

        # sequence library hash
        seq_rel = os.path.join("fixtures", "sequences", fx["sequence"] + ".json")
        seq_path = os.path.join(REPO, seq_rel)
        if os.path.exists(seq_path):
            recorded = man["sequence_library"].get(fx["sequence"])
            check("sequence_hash_recorded", recorded is not None, fx["sequence"])
            actual = sha256_file(seq_path)
            check("sequence_hash_matches", recorded == actual,
                  f"recorded={recorded} actual={actual}")
            if sidecar:
                check("sidecar_sequence_hash_matches", sidecar.get("sequence", {}).get("sha256") == actual,
                      f"sidecar={sidecar.get('sequence', {}).get('sha256')} actual={actual}")
        else:
            check("sequence_file_present", False, seq_rel)

        # audio files
        for bus in ("wet", "dry"):
            rel = fx[bus]["wav"]
            path = os.path.join(REPO, rel)
            if not os.path.exists(path):
                check(f"{bus}_wav_present", False, rel)
                continue
            actual = sha256_file(path)
            check(f"{bus}_sha256_matches", actual == fx[bus]["sha256"],
                  f"recorded={fx[bus]['sha256']} actual={actual}")
            info = wav_info(path)
            check(f"{bus}_wav_header", info["framerate"] == 48000 and info["channels"] == 1
                  and info["sampwidth_bytes"] == 2, str(info))
            if sidecar:
                check(f"{bus}_frames_match", info["frames"] == sidecar[bus]["frames"],
                      f"header={info['frames']} sidecar={sidecar[bus]['frames']}")

        status = "PASS" if all(ok for _n, ok, _d in checks) else "FAIL"
        print(f"{fid}: {status} ({sum(ok for _n, ok, _d in checks)}/{len(checks)} checks)")

    totals = man.get("totals", {})
    recomputed_bytes = 0
    for fx in man.get("fixtures", []):
        for bus in ("wet", "dry"):
            p = os.path.join(REPO, fx[bus]["wav"])
            if os.path.exists(p):
                recomputed_bytes += os.path.getsize(p)
    if totals.get("audio_bytes") not in (None, recomputed_bytes):
        failures.append(f"manifest: totals.audio_bytes {totals.get('audio_bytes')} != "
                        f"recomputed {recomputed_bytes}")
    print(f"totals: fixtures={totals.get('fixture_count')} wavs={totals.get('wav_count')} "
          f"audio_bytes={recomputed_bytes}")

    if failures:
        print("\nREFUSED — integrity failures:")
        for f_ in failures:
            print("  -", f_)
        return 2
    print("ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
