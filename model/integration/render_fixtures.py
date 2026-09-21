#!/usr/bin/env python3
"""SXT-025 reference fixtures: stereo float wet/dry buses of the chosen preset.

Renders `Hell's Bells.fxp` through the pinned native oracle for the
integration sequences, inheriting the SXT-012 render policies by importing
fixtures/render_fixture.py via tools/render_fx_fixtures.py (fresh instance
per bus, census-blob-verified load, controller reset, 0.25 s settle,
block-quantized ceil scheduling, identical tails; DRY = all 16 FX-slot types
set to fxt_off via setParamVal before settle, read-back verified).

DETERMINISM GATE (SXT-012 method, per the issue task): every bus is rendered
3x in fresh instances and all three float buffers must be bit-identical
(sha256); the gate refuses otherwise.

Outputs under reports/sxt025/fixtures/:
  <slug>__<seq>-wet.f32.wav / -dry.f32.wav + sidecar JSON (hashes, engine
  identity, tool version).

WAVs are this project's own renders of the loaded preset (not redistributed
upstream content). Original tool, Apache-2.0.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "fixtures"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import render_fixture as rf  # noqa: E402  (SXT-012 harness)
import render_fx_fixtures as rfx  # noqa: E402  (SXT-023 stereo-f32 harness)

SEQ_DIR = os.path.join(REPO, "model", "integration", "sequences")
OUT_DIR = os.path.join(REPO, "reports", "sxt025", "fixtures")
REL_PATH = "resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp"
SLUG = "hells_bells"
SEQUENCES = ["sxt025-smoke-v1", "sxt025-accept-v1"]


def main():
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    abs_path = os.path.join(oc.engine_dir(), REL_PATH)
    blob = rfx.census_entry(REL_PATH)[0]
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise rfx.Refuse(f"census blob mismatch: {actual} != {blob}")
    os.makedirs(OUT_DIR, exist_ok=True)
    for seq_name in SEQUENCES:
        seq_path = os.path.join(SEQ_DIR, seq_name + ".json")
        seq, seq_sha = rf.load_sequence(seq_path)[0], rf.sha256_file(seq_path)
        wet, wet_hashes, winfo = rfx.render_bus_stereo(surgepy, abs_path, seq, False)
        dry, dry_hashes, dinfo = rfx.render_bus_stereo(surgepy, abs_path, seq, True)
        wet_path = os.path.join(OUT_DIR, f"{SLUG}__{seq_name}-wet.f32.wav")
        dry_path = os.path.join(OUT_DIR, f"{SLUG}__{seq_name}-dry.f32.wav")
        rfx.write_wav_stereo_f32(wet_path, wet)
        rfx.write_wav_stereo_f32(dry_path, dry)
        sidecar = {
            "schema_version": 1,
            "fixture_id": f"{SLUG}__{seq_name}",
            "issue": "SXT-025",
            "claim_scope": "reference-vs-reference wet/dry buses of the pinned "
                           "engine under the SXT-012 policies; no fidelity/"
                           "support/quality claim",
            "preset": {
                "slug": SLUG,
                "path": REL_PATH,
                "census_blob_sha1": blob,
                "graphs_sha256_prefix": None,
                "note": "contributor bank preset; graph sha in "
                        "model/integration/selection-scan.json",
            },
            "sequence": {"id": seq_name, "sha256": seq_sha,
                         "path": os.path.relpath(seq_path, REPO)},
            "render": {
                "sample_rate": 48000, "block_size": 32,
                "frames": winfo["frames"],
                "duration_s": round(winfo["frames"] / 48000, 6),
                "tail_s": seq.get("tail_s", 2.5),
                "settle_s": seq.get("settle_s", 0.25),
                "policies_inherited": "fixtures/render_fixture.py (reset/"
                                      "scheduling/tail/dry-bypass)",
            },
            "audio_policy": "stereo float32 (IEEE fmt 3), raw engine output, "
                            "no clip, no normalization, no fades",
            "determinism_gate": {
                "repeats": 3,
                "wet_sha256_all": wet_hashes,
                "dry_sha256_all": dry_hashes,
                "bit_identical": True,
            },
            "wet": {"wav": os.path.relpath(wet_path, REPO),
                    "sha256": rf.sha256_file(wet_path),
                    "bytes": os.path.getsize(wet_path),
                    "peak_abs_float": winfo["peak_abs"]},
            "dry": {"wav": os.path.relpath(dry_path, REPO),
                    "sha256": rf.sha256_file(dry_path),
                    "bytes": os.path.getsize(dry_path),
                    "peak_abs_float": dinfo["peak_abs"],
                    "bypass_method": "all 16 FX-slot type params -> fxt_off "
                                     "via setParamVal before settle; read-back "
                                     "verified Off; fresh instance",
                    "dry_fx_bypass_verified":
                        dinfo["fx_types_readback"] == [0] * 16},
            "engine": rf.engine_identity(surgepy, surgepy.createSurge(48000.0)),
            "tool": rf.tool_version(),
        }
        sp = os.path.join(OUT_DIR, f"{SLUG}__{seq_name}.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"rendered {SLUG}__{seq_name}: wet {sidecar['wet']['sha256'][:12]} "
              f"dry {sidecar['dry']['sha256'][:12]} "
              f"peak {winfo['peak_abs']:.4f} frames {winfo['frames']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rfx.Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
