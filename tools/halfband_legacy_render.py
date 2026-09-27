#!/usr/bin/env python3
"""#145 attribution harness: run any committed leaf runner with the shared
`HalfbandD2` decimator reverted IN-PROCESS to the pre-#123 A-even
reconstruction, so a committed (pre-#123) model render can be re-derived from
the committed tree and a republished render's movement attributed to #123
alone.

Why this exists
---------------
#145 republishes every leaf artifact that passes through the scene decimator.
A republication is only a like-for-like delta if the OLD artifact is itself
reproducible from source: if the legacy ordering re-renders a committed WAV
byte-identically, the only difference between it and the HEAD render is the
#123 branch-order fix. If it does NOT, the committed artifact carried some
other drift (reported as its own finding, never absorbed into the #123
delta). Method follows reports/halfband-branch-order/ section 3.

  a_even (legacy, pre-#123) : out[n] = (A[2n] + B[2n+1]) * 0.5
  b_even (pinned, shipped)  : out[n] = (B[2n] + A[2n+1]) * 0.5

Nothing in the repository is modified: the override lives only in this
process. Classic/Sine/Wavetable import the same source file under a second
module name (`from model.voice import voice_model`), so BOTH class objects
are patched; patching only one silently measures nothing.

`--zero-unison-spread` additionally forces the loaded voice inputs' unison
detune spread to 0 after loading (the SXT-034 NC-2 "detune-zeroed" model
mutant, whose original input file was not committed; #145 re-derives it this
way and validates the reconstruction against the committed NC-2 metrics
under the legacy ordering before using it at HEAD). `--head-order` keeps the
shipped (pinned, B-even) decimator, so the spread override can be applied at
HEAD without the legacy ordering.

This is a diagnostic. It makes no fidelity, listening, or hardware claim.

Usage:
  python3 tools/halfband_legacy_render.py [--zero-unison-spread] \
      [--head-order] <runner.py> [runner args...]
  # e.g.
  python3 tools/halfband_legacy_render.py model/voice/run_model.py \
      --sequence seq-modwheel-v1 --out-dir /tmp/legacy/mw
"""

import os
import runpy
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as _vm_a  # noqa: E402
from model.voice import voice_model as _vm_b  # noqa: E402


def legacy_a_even_process(self, inp):
    """HalfbandD2.process with the pre-#123 (A-even/B-odd) reconstruction.
    Identical to the shipped class in every other respect."""
    vm = _vm_a
    chain_b, chain_a = [], []
    for x_in in inp:
        xb, xa = x_in, x_in
        for j in range(6):
            y = self.bx[j][1] + vm.qmul(vm.HALFBAND_B_Q[j], xb - self.by[j][1])
            self.bx[j] = [xb, self.bx[j][0], self.bx[j][1]]
            self.by[j] = [y, self.by[j][0], self.by[j][1]]
            xb = y
            y = self.ax[j][1] + vm.qmul(vm.HALFBAND_A_Q[j], xa - self.ay[j][1])
            self.ax[j] = [xa, self.ax[j][0], self.ax[j][1]]
            self.ay[j] = [y, self.ay[j][0], self.ay[j][1]]
            xa = y
        chain_b.append(xb)
        chain_a.append(xa)
    return [vm.qround(chain_a[2 * n] + chain_b[2 * n + 1], 1)
            for n in range(len(inp) // 2)]


def _zero_spread(cls):
    orig = cls.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.spread = 0.0
    cls.__init__ = init


def main(argv):
    zero_spread = False
    head_order = False
    while argv and argv[0] in ("--zero-unison-spread", "--head-order"):
        if argv[0] == "--zero-unison-spread":
            zero_spread = True
        else:
            head_order = True
        argv = argv[1:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    for vm in (_vm_a, _vm_b):
        if not head_order:
            vm.HalfbandD2.process = legacy_a_even_process
        if zero_spread:
            _zero_spread(vm.Inputs)
            _zero_spread(vm.InputsV2)
    runner = os.path.abspath(argv[0])
    sys.argv = [runner] + argv[1:]
    runpy.run_path(runner, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
