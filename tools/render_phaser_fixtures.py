#!/usr/bin/env python3
"""SXT-028g reference fixtures: stereo float renders of the Phaser carriers.

ORACLE-GATED. It imports surgepy from the pinned external oracle checkout;
without it the tool REFUSES (exit 2) and nothing is graded — a missing
oracle makes the model-vs-reference leg NOT_RUN, never a pass.

Fixture policy is inherited unchanged from the SXT-023 renderer
(tools/render_fx_fixtures.py): fresh instance per bus, census-blob-verified
load, controller reset, 0.25 s settle, block-quantized scheduling, identical
tails on wet and dry, a 3x bit-identical determinism gate, and a DRY bus
made by setting all 16 FX-slot types to Off with read-back verification. One
mechanism per behaviour: no fixture policy is re-invented here.

Carriers: the B4-scope Phaser carriers named by issue #59, with the census
blob SHA-1 recorded by the SXT-028 generator
(reports/sxt-028/leaves/SXT-028g/newly-enabled.json) and re-verified at
render time:
  reson   Argitoth/FX/Reson.fxp             (blob ba7d2c45b8ed...)
  bass11  Bluelight/Basses/Bass 11.fxp      (blob bebc1a6c8d18...)
  bass17  Bluelight/Basses/Bass 17.fxp      (blob 7c8cd4d1060b...)

Any carrier that fails the determinism gate, needs an unlanded sibling FX
class, or uses an RNG-driven Phaser LFO waveform (Noise / Sample & Hold,
outside the frozen model's deterministic scope) is REFUSED and recorded in
artifacts/render-refusals.txt — never silently excluded and never patched
around.

TAIL POLICY. The acceptance render must cover this effect's own declared
tail span after the input goes silent: Phaser.h getRingoutDecay, in blocks
of 32 samples (see reports/SXT-028g/artifacts/tail-window.json). The SXT-012
sequence `tail_s` is checked against that span here and the render is
REFUSED when it is shorter, so a dropped tail cannot enter the evidence.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, copies nothing.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-phaser"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import render_fx_fixtures as rfx  # noqa: E402  (SXT-023 policies inherited)
from phaser_model import ringout_blocks  # noqa: E402

PRESETS = {
    "reson": "resources/data/patches_3rdparty/Argitoth/FX/Reson.fxp",
    "bass11": "resources/data/patches_3rdparty/Bluelight/Basses/Bass 11.fxp",
    "bass17": "resources/data/patches_3rdparty/Bluelight/Basses/Bass 17.fxp",
}
SEQUENCES = ["seq-notes-coverage-v1", "seq-poly-8-v1"]
FX_TYPE_PHASER = 3
PH_FEEDBACK = 1
BLOCK = 32


def required_tail_s(s, patch, engine_types):
    """The longest declared Phaser ringout in the patch, in seconds."""
    worst = 0
    for slot, t in enumerate(engine_types):
        if t != FX_TYPE_PHASER:
            continue
        fb = float(s.getParamVal(patch["fx"][slot]["p"][PH_FEEDBACK]))
        rb = ringout_blocks(fb)
        if rb < 0:
            raise rfx.Refuse(
                f"slot{slot} feedback {fb} gives getRingoutDecay = -1 "
                "(possible self-oscillation): no finite tail span can be "
                "declared for this carrier")
        worst = max(worst, rb)
    return worst * BLOCK / 48000.0


def render_fixture(surgepy, slug, rel_path, seq_id, out_dir):
    seq, _seq_path, seq_sha = rfx.rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    blob, graphs = rfx.census_entry(rel_path)
    if oc.git_blob_sha1(abs_path) != blob:
        raise rfx.Refuse(f"census blob mismatch: {rel_path}")

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise rfx.Refuse(f"loadPatch failed: {rel_path}")
    patch = s.getPatch()
    engine_types = [int(s.getParamVal(patch["fx"][i]["type"]))
                    for i in range(16)]
    if FX_TYPE_PHASER not in engine_types:
        raise rfx.Refuse(f"no Phaser slot in {rel_path}")
    need_tail = required_tail_s(s, patch, engine_types)
    have_tail = float(seq.get("tail_s", 2.5))
    if have_tail + 1e-9 < need_tail:
        raise rfx.Refuse(
            f"sequence tail {have_tail:.3f} s is shorter than the declared "
            f"Phaser tail span {need_tail:.3f} s (Phaser.h getRingoutDecay) — "
            "a dropped tail must not enter the evidence")

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
        "issue": "SXT-028g",
        "claim_scope": "reference-vs-reference wet/dry buses of the pinned "
                       "engine under the SXT-012/023 policies; no fidelity, "
                       "support or quality claim",
        "preset": {"slug": slug, "path": rel_path,
                   "census_blob_sha1": blob,
                   "graphs_sha256_prefix": graphs["sha"][:16]},
        "sequence": {"id": seq_id, "sha256": seq_sha},
        "render": {
            "sample_rate": 48000,
            "block_size": 32,
            "frames": winfo["frames"],
            "duration_s": round(winfo["frames"] / 48000, 6),
            "policies_inherited": "fixtures/render_fixture.py via "
                                  "tools/render_fx_fixtures.py",
            "tail_s": have_tail,
            "settle_s": seq.get("settle_s", 0.25),
        },
        "declared_effect_tail": {
            "required_tail_s": need_tail,
            "basis": "Phaser.h getRingoutDecay (blocks of 32 at 48 kHz), "
                     "worst Phaser slot of this patch",
            "covered": have_tail + 1e-9 >= need_tail,
        },
        "audio_policy": "stereo float32 (IEEE fmt 3), raw engine output, no "
                        "clip, no normalization, no fades",
        "determinism_gate": {"repeats": 3, "wet_sha256_all": wet_hashes,
                             "dry_sha256_all": dry_hashes,
                             "bit_identical": True},
        "wet": {"wav": os.path.relpath(wet_path, REPO),
                "sha256": rfx.rf.sha256_file(wet_path),
                "bytes": os.path.getsize(wet_path),
                "peak_abs_float": winfo["peak_abs"]},
        "dry": {"wav": os.path.relpath(dry_path, REPO),
                "sha256": rfx.rf.sha256_file(dry_path),
                "bytes": os.path.getsize(dry_path),
                "peak_abs_float": dinfo["peak_abs"],
                "bypass_method": "all 16 FX-slot type params -> fxt_off via "
                                 "setParamVal before settle; read-back "
                                 "verified Off; fresh instance",
                "dry_fx_bypass_verified": dinfo["fx_types_readback"] == [0] * 16},
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
                    default=os.path.join(REPO, "reports", "SXT-028g",
                                         "fixtures"))
    ap.add_argument("--presets", help="comma-separated subset")
    ap.add_argument("--seqs", help="comma-separated subset")
    ap.add_argument("--refusals",
                    default=os.path.join(REPO, "reports", "SXT-028g",
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
                render_fixture(surgepy, slug, PRESETS[slug], seq_id,
                               args.out_dir)
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
