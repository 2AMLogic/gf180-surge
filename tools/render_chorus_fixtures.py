#!/usr/bin/env python3
"""SXT-028c reference fixtures: stereo float renders of the Chorus carriers.

Inherits the SXT-023 fixture policy by importing tools/render_fx_fixtures.py
(fresh instance per bus, census-blob-verified load, controller reset, 0.25 s
settle, block-quantized scheduling, identical tails, 3x bit-identical
determinism gate, dry = all 16 FX-slot types set Off with read-back).

Carriers (deterministic full-chain-feasible chorus presets; see
reports/SXT-028c/EVIDENCE.md section 1):
  fmcombo   factory Basses/FM Combo.fxp    (eq ains1 + chorus ains2)
  fmtwang2  Luna/MPE/FM Twang 2.fxp        (chorus-only ains1)
  alienappears  Giana Brotherz/FX/Alien Appears.fxp
            (reverb1 global1 -> chorus global2; delay-free chain)

Refusal rows (attempted, REFUSED by the 3x render determinism gate, no
fixture committed; refusals recorded to artifacts/render-refusals.txt):
  melon     factory Polysynths/Melon.fxp   (eq ains1 + chorus send1)
  dronebee  Dan Maurer/Pads/Drone Bee.fxp  (chorus global1 -> rev1 global2)

Both melon and dronebee passed the graphs-based determinism screen but
FAILED the 3x render gate empirically (engine-level nondeterminism the
normalized graph does not expose; dronebee already in its all-off DRY
bus) - engine-level evidence that the static screen cannot replace the
render gate.

The issue-named presets (Novuo, Ancient FM, Piercing) are REFUSED at
extraction (unlanded sibling classes / drift != 0) and are never
attempted here. Original tool, Apache-2.0.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import render_fx_fixtures as rfx  # noqa: E402  (SXT-023 policies inherited)

PRESETS = {
    "fmcombo": "resources/data/patches_factory/Basses/FM Combo.fxp",
    "fmtwang2": "resources/data/patches_3rdparty/Luna/MPE/FM Twang 2.fxp",
    "alienappears": "resources/data/patches_3rdparty/Giana Brotherz/FX/Alien Appears.fxp",
    # refusal rows: attempted by a full run, refused by the determinism gate
    "melon": "resources/data/patches_factory/Polysynths/Melon.fxp",
    "dronebee": "resources/data/patches_3rdparty/Dan Maurer/Pads/Drone Bee.fxp",
}
SEQUENCES = ["seq-notes-coverage-v1", "seq-poly-8-v1"]


def render_fixture(surgepy, slug, rel_path, seq_id, out_dir):
    seq, seq_path, seq_sha = rfx.rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    blob, graphs = rfx.census_entry(rel_path)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise rfx.Refuse(f"census blob mismatch: {rel_path}")

    wet, wet_hashes, winfo = rfx.render_bus_stereo(surgepy, abs_path, seq, False)
    dry, dry_hashes, dinfo = rfx.render_bus_stereo(surgepy, abs_path, seq, True)

    os.makedirs(out_dir, exist_ok=True)
    wet_path = os.path.join(out_dir, f"{slug}__{seq_id}-wet.f32.wav")
    dry_path = os.path.join(out_dir, f"{slug}__{seq_id}-dry.f32.wav")
    rfx.write_wav_stereo_f32(wet_path, wet)
    rfx.write_wav_stereo_f32(dry_path, dry)

    sidecar = {
        "schema_version": 1,
        "fixture_id": f"{slug}__{seq_id}",
        "issue": "SXT-028c",
        "claim_scope": "reference-vs-reference wet/dry buses of the pinned engine "
                       "under the SXT-012/023 policies; no fidelity/support/"
                       "quality claim",
        "preset": {
            "slug": slug,
            "path": rel_path,
            "census_blob_sha1": blob,
            "graphs_sha256_prefix": graphs["sha"][:16],
        },
        "sequence": {"id": seq_id, "sha256": seq_sha},
        "render": {
            "sample_rate": 48000,
            "block_size": 32,
            "frames": winfo["frames"],
            "duration_s": round(winfo["frames"] / 48000, 6),
            "policies_inherited": "fixtures/render_fixture.py via "
                                  "tools/render_fx_fixtures.py (reset/scheduling/"
                                  "tail/dry-bypass); see fixtures/README.md",
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
            "sha256": rfx.rf.sha256_file(wet_path),
            "bytes": os.path.getsize(wet_path),
            "peak_abs_float": winfo["peak_abs"],
        },
        "dry": {
            "wav": os.path.relpath(dry_path, REPO),
            "sha256": rfx.rf.sha256_file(dry_path),
            "bytes": os.path.getsize(dry_path),
            "peak_abs_float": dinfo["peak_abs"],
            "bypass_method": "all 16 FX-slot type params -> fxt_off via setParamVal "
                             "before settle; read-back verified Off; fresh instance",
            "dry_fx_bypass_verified": dinfo["fx_types_readback"] == [0] * 16,
        },
        "engine": rfx.rf.engine_identity(surgepy, surgepy.createSurge(48000.0)),
        "tool": rfx.rf.tool_version(),
    }
    sp = os.path.join(out_dir, f"{slug}__{seq_id}.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"rendered {slug}__{seq_id}: wet {sidecar['wet']['sha256'][:12]} "
          f"dry {sidecar['dry']['sha256'][:12]} peak {winfo['peak_abs']:.4f}")
    return sidecar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "SXT-028c", "fixtures"))
    ap.add_argument("--presets", help="comma-separated subset")
    ap.add_argument("--seqs", help="comma-separated subset")
    ap.add_argument("--refusals",
                    default=os.path.join(REPO, "reports", "SXT-028c",
                                         "artifacts", "render-refusals.txt"))
    args = ap.parse_args()
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    slugs = args.presets.split(",") if args.presets else sorted(PRESETS)
    seqs = args.seqs.split(",") if args.seqs else SEQUENCES
    refusals = []
    for slug in slugs:
        for seq_id in seqs:
            try:
                render_fixture(surgepy, slug, PRESETS[slug], seq_id, args.out_dir)
            except rfx.Refuse as e:
                msg = f"{slug}__{seq_id}: REFUSED: {e}"
                refusals.append(msg)
                print(msg, file=sys.stderr)
    if refusals and args.presets is None and args.seqs is None:
        os.makedirs(os.path.dirname(args.refusals), exist_ok=True)
        with open(args.refusals, "w", encoding="utf-8") as f:
            f.write("\n".join(refusals) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rfx.Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
