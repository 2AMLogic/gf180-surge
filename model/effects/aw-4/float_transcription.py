#!/usr/bin/env python3
"""SXT-028k: double-precision transcription of the pinned Airwindows
"Logical" (id 4) sample loop.

==========================================================================
THIS IS NOT THE ORACLE. IT IS NOT A REFERENCE. AGREEMENT WITH IT
ESTABLISHES NOTHING ABOUT MODEL-VS-PINNED-ENGINE FIDELITY.
==========================================================================

The only sound reference for this project is the pinned Surge engine
(`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`), run as
an external oracle under SXT-010/SXT-012 policy. That leg is NOT_RUN in this
environment (reports/SXT-028k/EVIDENCE.md).

What this module IS: a second, independent, double-precision transcription
of the same pinned structure, written straight from the cited source so that
it shares as little as possible with the fixed-point model's arithmetic. It
exists for exactly two jobs:

1. **Structural cross-check (diagnostic).** If the frozen fixed-point model
   contains a transcription error — a swapped bank, a missed clamp, a wrong
   stage gate — the two implementations diverge far beyond the declared
   quantization band. A test asserts the band; a violation is a FAIL of the
   diagnostic, never a PASS of the reference claim.
2. **Substrate for negative controls.** The "generic substitute" control
   (NC-C) needs a convenient generic dynamics processor to swap in; it is
   built here and is labelled ADAPTED wherever it appears.

Both jobs are internal. Nothing in this file may be cited as evidence of
agreement with the pinned engine, and `tests/test_sxt028k.py` asserts that
the evidence records never do.

It shares the *reading* of the pinned source with the fixed-point model, so
it is not an independent reading: a misreading common to both would not be
caught here. That limitation is declared in EVIDENCE.md.

Original to this repository (Apache-2.0); structure cited, never copied.
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import logical4_model as M  # noqa: E402


class LogicalFloat:
    """Double-precision transcription of `Logical4::processReplacing`."""

    def __init__(self, ctrl):
        d = ctrl["d"]
        self.sel = ctrl["ratioselector"]
        self.inputgain = d["inputgain"]
        self.compoutgain = d["compoutgain"]
        self.remainder = list(d["remainder"])
        self.divisor = list(d["divisor"])
        self.ratio = d["ratio"]
        self.inv_ratio = d["inv_ratio"]
        self.outputgain = d["outputgain"]
        self.wet = d["wet"]
        self.dry = d["dry"]
        self.offset = ctrl["sag_offset"]
        self.reset()

    def reset(self):
        self.gcount = 0
        self.fp_flip = True
        self.c_apos = [[1.0, 1.0] for _ in range(3)]
        self.c_aneg = [[1.0, 1.0] for _ in range(3)]
        self.c_bpos = [[1.0, 1.0] for _ in range(3)]
        self.c_bneg = [[1.0, 1.0] for _ in range(3)]
        self.t_pos = [[1.0, 1.0] for _ in range(3)]
        self.t_neg = [[1.0, 1.0] for _ in range(3)]
        self.avg = [[0.0, 0.0] for _ in range(3)]
        self.nvg = [[0.0, 0.0] for _ in range(3)]
        self.line = [[[0.0] * M.LINE_WORDS for _ in range(2)]
                     for _ in range(3)]
        self.sag_ctrl = [[0.0, 0.0] for _ in range(3)]

    # ------------------------------------------------------------------ sag
    def _sag(self, stage, ch, x):
        g = self.gcount
        s = (self.c_apos[stage][ch] + self.c_bpos[stage][ch]
             + self.c_aneg[stage][ch] + self.c_bneg[stage][ch])
        d = abs(x) * (M.INTENSITY - s * M.POWER_SAG)
        line = self.line[stage][ch]
        line[g] = d
        line[g + M.LINE_MIRROR] = d
        c = self.sag_ctrl[stage][ch]
        c += line[g] / self.offset
        c -= line[g + self.offset] / self.offset
        c -= M.SAG_LEAK
        clamp = 1.0
        if c < 0:
            c = 0.0
        if c > 1:
            clamp -= (c - 1.0)
            c = 1.0
        if clamp < M.CLAMP_FLOOR:
            clamp = M.CLAMP_FLOOR
        self.sag_ctrl[stage][ch] = c
        thickness = ((1.0 - c) * 2.0) - 1.0
        out = abs(thickness)
        br = abs(x)
        if br > M.BR_MAX:
            br = M.BR_MAX
        br = math.sin(br) if thickness > 0 else 1.0 - math.cos(br)
        if x > 0:
            x = (x * (1.0 - out)) + (br * out)
        else:
            x = (x * (1.0 - out)) - (br * out)
        if clamp != 1.0:
            x *= clamp
        return x

    # ----------------------------------------------------------------- comp
    def _comp(self, stage, ch, x):
        rem = self.remainder[stage]
        div = self.divisor[stage]
        if stage == 0 and self.inputgain != 1.0:
            x *= self.inputgain

        ipos = (x * M.FP_OLD) + (self.avg[stage][ch] * M.FP_NEW) + 1.0
        self.avg[stage][ch] = x
        if ipos < M.POS_FLOOR:
            ipos = M.POS_FLOOR
        opos = ipos / 2.0
        if opos > 1.0:
            opos = 1.0
        ipos *= ipos
        dr = rem * (ipos + 1.0)
        if dr > 1.0:
            dr = 1.0
        dd = 1.0 - dr
        tgt = 0 if (stage == 2 and ch == 1) else ch     # quirk Q2
        self.t_pos[stage][tgt] *= dd
        self.t_pos[stage][tgt] += (ipos * dr)
        calc_pos = math.pow(1.0 / self.t_pos[stage][ch], 2)

        ineg = (-x * M.FP_OLD) + (self.nvg[stage][ch] * M.FP_NEW) + 1.0
        self.nvg[stage][ch] = -x
        if ineg < M.POS_FLOOR:
            ineg = M.POS_FLOOR
        oneg = ineg / 2.0
        if oneg > 1.0:
            oneg = 1.0
        ineg *= ineg
        dr = rem * (ineg + 1.0)
        if dr > 1.0:
            dr = 1.0
        dd = 1.0 - dr
        self.t_neg[stage][ch] *= dd
        self.t_neg[stage][ch] += (ineg * dr)
        calc_neg = math.pow(1.0 / self.t_neg[stage][ch], 2)

        other = 1 - ch
        if x > 0:
            bank = self.c_apos if self.fp_flip else self.c_bpos
            calc = calc_pos
        else:
            bank = self.c_aneg if self.fp_flip else self.c_bneg
            calc = calc_neg
        bank[stage][ch] *= div
        bank[stage][ch] += (calc * rem)
        if bank[stage][other] > bank[stage][ch]:
            bank[stage][other] = (bank[stage][other] + bank[stage][ch]) * 0.5

        if self.fp_flip:
            tot = (self.c_apos[stage][ch] * opos
                   + self.c_aneg[stage][ch] * oneg)
        else:
            tot = (self.c_bpos[stage][ch] * opos
                   + self.c_bneg[stage][ch] * oneg)
        if tot != 1.0:
            x *= tot
        if x > M.HARD_CLIP:
            x = M.HARD_CLIP
        if x < -M.HARD_CLIP:
            x = -M.HARD_CLIP
        return x, x / self.compoutgain

    # --------------------------------------------------------------- sample
    def sample(self, in_l, in_r):
        dry = (in_l, in_r)
        x = [in_l, in_r]
        self.gcount -= 1
        if self.gcount < 0 or self.gcount > M.GCOUNT_MAX:
            self.gcount = M.GCOUNT_MAX
        a = [0.0, 0.0]
        b = [0.0, 0.0]
        c = [0.0, 0.0]
        x[0] = self._sag(0, 0, x[0])
        x[1] = self._sag(0, 1, x[1])
        x[0], a[0] = self._comp(0, 0, x[0])
        x[1], a[1] = self._comp(0, 1, x[1])
        if self.sel > 0:
            x[0] = self._sag(1, 0, x[0])
            x[1] = self._sag(1, 1, x[1])
            x[0], b[0] = self._comp(1, 0, x[0])
            x[1], b[1] = self._comp(1, 1, x[1])
            if self.sel > 1:
                x[0] = self._sag(2, 0, x[0])
                x[1] = self._sag(2, 1, x[1])
                x[0], c[0] = self._comp(2, 0, x[0])
                x[1], c[1] = self._comp(2, 1, x[1])
        res = [0.0, 0.0]
        for ch in (0, 1):
            if self.sel == 0:
                lo, hi = dry[ch], a[ch]
            elif self.sel == 1:
                lo, hi = a[ch], b[ch]
            else:
                lo, hi = b[ch], c[ch]
            v = (lo * self.inv_ratio) + (hi * self.ratio)
            if self.outputgain != 1.0:
                v *= self.outputgain
            if self.wet != 1.0:
                v = (v * self.wet) + (dry[ch] * self.dry)
            res[ch] = v
        self.fp_flip = not self.fp_flip
        return res[0], res[1]

    def process_block(self, in_l, in_r):
        ol, orr = [], []
        for k in range(len(in_l)):
            u, v = self.sample(in_l[k], in_r[k])
            ol.append(u)
            orr.append(v)
        return ol, orr


class GenericCompressorADAPTED:
    """ADAPTED, NOT Logical.

    A convenient generic peak compressor with the same five knobs. It exists
    only as the "generic substitute" negative control (NC-C): any coverage
    accounting that accepts this in place of the pinned algorithm is broken
    accounting, and the control asserts that it is refused. Never counts
    toward original-preset coverage (AGENTS.md).
    """

    is_adapted = True
    adapted_reason = ("generic peak compressor substituted for the pinned "
                      "Airwindows Logical algorithm")

    def __init__(self, ctrl):
        d = ctrl["d"]
        self.thr = d["inputgain"]
        self.att = d["remainder"][0]
        self.makeup = d["outputgain"]
        self.wet = d["wet"]
        self.dry = d["dry"]
        self.env = [0.0, 0.0]

    def sample(self, in_l, in_r):
        out = []
        for ch, v in enumerate((in_l, in_r)):
            self.env[ch] += (abs(v) - self.env[ch]) * self.att
            g = 1.0 / (1.0 + self.env[ch] * self.thr)
            y = v * g * self.makeup
            out.append(y * self.wet + v * self.dry)
        return out[0], out[1]

    def process_block(self, in_l, in_r):
        ol, orr = [], []
        for k in range(len(in_l)):
            u, v = self.sample(in_l[k], in_r[k])
            ol.append(u)
            orr.append(v)
        return ol, orr
