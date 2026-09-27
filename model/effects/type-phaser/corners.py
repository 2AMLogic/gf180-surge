#!/usr/bin/env python3
"""SXT-028g parameter-corner inputs for the frozen Phaser model.

WHAT THESE ARE — AND ARE NOT
----------------------------
These are SYNTHETIC parameter corners, not preset extractions. They exist so
the oracle-INDEPENDENT claim of this leaf (RTL-vs-frozen-model integer
equality, plus the model-side negative controls) can be exercised across the
Phaser's declared parameter space in an environment with no pinned-engine
checkout. Every file written from here carries
`"source": "synthetic-corner"` and `"census_blob_sha1": null`.

They are NOT a substitute for the fail-closed preset extraction
(tools/extract_phaser_inputs.py -> type-phaser-<slug>.json, census-blob
verified and graphs cross-checked) and they carry NO support, coverage or
fidelity claim of any kind. Nothing model-vs-reference may be graded from
them.

Corners covered:
  synth-a        4 stages (Phaser.h default), sine LFO, tone active
  synth-b        8 stages, triangle LFO, negative centre/feedback/tone
  synth-c        4 stages, square LFO, tone DEACTIVATED (lp/hp bypassed)
  synth-maxst    16 stages (Phaser.h max_stages), sine LFO, full spread
  synth-legacy-a 1 stage  (Phaser.h n_stages < 2 legacy branch), saw LFO
  synth-legacy-b 1 stage, ramp LFO, mod rate DEACTIVATED (static LFO phase)
  synth-clamp-a  4 stages, feedback  0.95 (near self-oscillation)
  synth-clamp-b  2 stages, feedback -0.95 (near self-oscillation)

Reproduce: python3 model/effects/type-phaser/corners.py --write
Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

# Phaser.h parameter ranges (from paramAt / the Surge ct_ types):
#   center, feedback, sharpness, tone  : percent bipolar  [-1, 1]
#   mod_depth, stereo, mix, spread     : percent          [ 0, 1]
#   width                              : decibel narrow   [-24, 24]
#   mod_rate                           : lfo rate         [-7, 9]
#   stages                             : int              [ 1, 16]
#   mod_wave                           : int              [ 0, 6]  (0..4 only
#                                        here: 5/6 are RNG-driven and refused)
CORNERS = {
    "synth-a": {
        "center_f": 0.05, "feedback_f": 0.55, "sharpness_f": 0.3,
        "mod_rate_f": -2.0, "mod_depth_f": 0.6, "stereo_f": 0.4,
        "mix_f": 0.8, "width_f": 2.0, "stages_i": 4, "spread_f": 0.35,
        "mod_wave_i": 0, "tone_f": 0.3, "tone_deactivated": False,
        "mod_rate_deactivated": False,
    },
    "synth-b": {
        "center_f": -0.4, "feedback_f": -0.75, "sharpness_f": -0.6,
        "mod_rate_f": -4.5, "mod_depth_f": 0.9, "stereo_f": 1.0,
        "mix_f": 0.45, "width_f": -3.0, "stages_i": 8, "spread_f": 0.8,
        "mod_wave_i": 1, "tone_f": -0.5, "tone_deactivated": False,
        "mod_rate_deactivated": False,
    },
    "synth-c": {
        "center_f": 0.7, "feedback_f": 0.2, "sharpness_f": 0.9,
        "mod_rate_f": -1.0, "mod_depth_f": 0.25, "stereo_f": 0.2,
        "mix_f": 1.0, "width_f": 0.0, "stages_i": 4, "spread_f": 0.1,
        "mod_wave_i": 4, "tone_f": 0.0, "tone_deactivated": True,
        "mod_rate_deactivated": False,
    },
    "synth-maxst": {
        "center_f": 0.25, "feedback_f": 0.4, "sharpness_f": 0.55,
        "mod_rate_f": -2.5, "mod_depth_f": 1.0, "stereo_f": 0.75,
        "mix_f": 0.9, "width_f": 6.0, "stages_i": 16, "spread_f": 1.0,
        "mod_wave_i": 0, "tone_f": 0.6, "tone_deactivated": False,
        "mod_rate_deactivated": False,
    },
    "synth-legacy-a": {
        "center_f": 0.0, "feedback_f": 0.35, "sharpness_f": 0.0,
        "mod_rate_f": -3.0, "mod_depth_f": 1.0, "stereo_f": 0.5,
        "mix_f": 0.6, "width_f": 0.0, "stages_i": 1, "spread_f": 0.0,
        "mod_wave_i": 2, "tone_f": 0.0, "tone_deactivated": True,
        "mod_rate_deactivated": False,
    },
    "synth-legacy-b": {
        "center_f": 0.3, "feedback_f": -0.95, "sharpness_f": 0.5,
        "mod_rate_f": 2.0, "mod_depth_f": 0.8, "stereo_f": 0.0,
        "mix_f": 1.0, "width_f": 1.5, "stages_i": 1, "spread_f": 0.4,
        "mod_wave_i": 3, "tone_f": 0.0, "tone_deactivated": True,
        "mod_rate_deactivated": True,
    },
    "synth-clamp-a": {
        "center_f": 0.0, "feedback_f": 0.95, "sharpness_f": 0.8,
        "mod_rate_f": -3.0, "mod_depth_f": 0.7, "stereo_f": 0.5,
        "mix_f": 1.0, "width_f": 0.0, "stages_i": 4, "spread_f": 0.3,
        "mod_wave_i": 0, "tone_f": 0.0, "tone_deactivated": True,
        "mod_rate_deactivated": False,
    },
    "synth-clamp-b": {
        "center_f": -0.2, "feedback_f": -0.95, "sharpness_f": 0.6,
        "mod_rate_f": -2.0, "mod_depth_f": 1.0, "stereo_f": 0.8,
        "mix_f": 1.0, "width_f": 0.0, "stages_i": 2, "spread_f": 0.6,
        "mod_wave_i": 1, "tone_f": 0.0, "tone_deactivated": True,
        "mod_rate_deactivated": False,
    },
}

NOT_A_PRESET = (
    "SYNTHETIC parameter corner for the SXT-028g oracle-independent "
    "RTL-vs-model exactness harness. NOT a preset extraction, NOT census-"
    "verified, and carrying NO support, coverage or fidelity claim. "
    "Preset-derived inputs come only from tools/extract_phaser_inputs.py "
    "(fail-closed, census-blob verified, graphs cross-checked)."
)


def record(slug):
    p = CORNERS[slug]
    return {
        "schema_version": 1,
        "leaf": "SXT-028g",
        "source": "synthetic-corner",
        "slug": slug,
        "path": None,
        "census_blob_sha1": None,
        "graphs_sha256_prefix": None,
        "warning": NOT_A_PRESET,
        "volume_f": 0.0,
        "phaser_slots": [0],
        "chain": {"ains": [{"slot": 0, "role": "ains1", "type": "phaser",
                            "params": dict(p)}],
                  "sends": []},
        "applicability": {
            "complete_wet_render_possible": False,
            "unlanded_classes": [],
            "note": "synthetic corner: there is no preset and no pinned-"
                    "engine reference render, so no complete-wet claim is "
                    "possible from this record (fail-closed).",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    args = ap.parse_args()
    if not args.write:
        print(json.dumps(sorted(CORNERS), indent=2))
        return 0
    os.makedirs(args.out_dir, exist_ok=True)
    for slug in sorted(CORNERS):
        path = os.path.join(args.out_dir, f"type-phaser-{slug}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record(slug), f, indent=2, sort_keys=True)
            f.write("\n")
        print("wrote", os.path.relpath(path, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
