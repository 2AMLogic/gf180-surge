#!/usr/bin/env python3
"""SXT-033 reference renderer (requires the external pinned oracle).

Renders the fixture sequences through the pinned engine for the DECLARED
Classic-family fixture configurations (from inputs/<carrier>.json): the
reference the model budget checks compare against. The isolation overrides
(mute other mixer paths, filters/FX/ws/lowcut off, fbc serial1, FM off,
scene mode Single, retrigger on) are applied by fixture_config.build_instance
with readback verification; they are test configurations, never adapted
presets, and never count toward preset coverage.

Policies inherited from the SXT-012 fixture harness (fixtures/
render_fixture.py): fresh instance per render, controller reset, 0.25 s
settle discarded, block-quantized event scheduling, tail = last event +
tail_s, mono (L+R)/2 int16 PCM, no normalization / time warping / fades,
clipped-sample counts recorded.

Outputs under --out-dir: <carrier>__<seq>-ref.wav + a sidecar JSON with
engine identity, override readback, sha256, determinism repeats.

Harness body (render_bus, sha256_file, argument parsing, blob gate, sidecar
assembly) is shared with render_sine_reference.py via
_render_reference_common.py (issue #245 dedup); only this docstring, the
family directory, and the isolation-note wording are Classic-specific.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "classic"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402
from _render_reference_common import run_reference_renderer  # noqa: E402

oc.reexec_under_pinned_python(REPO)

FAMILY_DIR = os.path.join("model", "oscillators", "classic")
ISSUE_ID = "SXT-033"
ISOLATION_NOTE = (
    "declared fixture configuration (one Classic slot "
    "audible; other mixer paths, filter units, FX, "
    "waveshaper, lowcut, FM routing off; fbc serial1; "
    "scene mode Single; retrigger on) - a test "
    "configuration, never an adapted preset, never "
    "coverage"
)


def main():
    return run_reference_renderer(oc, fc, REPO, FAMILY_DIR,
                                  ISSUE_ID, ISOLATION_NOTE,
                                  __doc__.splitlines()[0])


if __name__ == "__main__":
    sys.exit(main())
