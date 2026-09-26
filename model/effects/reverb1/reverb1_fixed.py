#!/usr/bin/env python3
"""SXT-024 Reverb1 frozen integer fixed-point model.

This file IS the frozen model referenced by the RTL-vs-model exactness claim
(issue #17 acceptance: "RTL vs model exact"). It implements Surge Reverb 1's
composite structure in pure integer arithmetic with the word lengths and
rounding rules below. STRUCTURE (not code) is cited from the pinned
GPL-3.0-or-later sources; see README.md for the citation map and licensing.

FROZEN FORMATS (see README.md "Frozen word lengths"):
  s24     audio I/O                       Q1.23 (signed 24-bit)
  s32i    internal signal/storage words   Q4.28 in 32-bit containers
          (sign + 3 integer headroom bits + 28 fraction bits; range +/-8).
          HEADROOM IS LOAD-BEARING: the composite loop value fbw = ca*sum +
          predelay reaches +/-3 and tap writes reach +/-4*max(delay_fb) at
          coherent summation; the pinned engine carries these in float without
          clipping. A format without integer headroom (e.g. Q1.31) saturates
          the loop and is a DEFECT (measured: -7 dB error). I/O conversion:
          in: s24 << 5 (exact); out: rnd5 then saturate to s24.
  c31     unit-range coefficients         Q1.31 (delay_fb, damp, 1-damp, pan)
  c30     +/-2-range coefficients         Q2.30 (mix, 1-mix, width_s)
  c29     +/-4-range coefficients         Q3.29 (biquad a1,a2,b0,b1,b2)
  reg80   biquad TDF2 state               Q-.57 in 80-bit signed

FROZEN ROUNDING RULE:
  rnd_f(x)  = (x + (1 << (f-1))) >>> f   (round-half-up, floor-biased;
                                          arithmetic shift, matches SV >>>)
  sat32(x)  = clamp(x, -2^31, 2^31-1);  output stage saturates to s24.
  f = a_frac + b_frac - dst_frac for every multiply that feeds a stored word:
  c31 x Q4.28 -> Q4.28 shifts 31; c30 x Q4.28 -> Q4.28 shifts 30; the biquad
  c29 x Q4.28 -> 2^-57 accumulator shifts 29. Intermediates are exact integers
  (Python int, unbounded); the model asserts every RTL-representable value
  stays in its frozen word width (assert_width=True, default on).

FROZEN OP ORDER per sample k (cites Reverb1.h processBlock):
  1. for t = 0..15:  dp = (delay_pos - (delay_time[t] >>> 8)) & 32767
       new = delay[(dp << 4) + t]                          # s32i external read
       out_tap[t] = sat32(rnd31(damp*out_tap[t] + (1-damp)*new))
  2. fbsum = sum(out_tap)                                  # exact, 36-bit
     fbw = -(fbsum >>> 3) + predelay[(delay_pos - pdtime) & 32767]
                                                           # ca = -2/16 exact
  3. delay_pos = (delay_pos + 1) & 32767
     predelay[delay_pos] = ((inL + inR) >>> 1) << 5        # 0.5*(L+R) exact
  4. wetL = sat32(sum_t rnd31(pan_L[t]*out_tap[t]));  wetR likewise
     for t = 0..15: delay[(delay_pos << 4) + t] =
                       sat32(rnd31(delay_fb[t] * (fbw + out_tap[t])))
  Per 32-sample block, after step 4 (block order cited from processBlock):
  5. locut HP (if active) -> band1 peak -> hicut LP2B (if active)
     TDF2 per channel: op = x*b0 + reg0; reg0' = x*b1 - a1*op + reg1;
     reg1' = x*b2 - a2*op; y = sat32(rnd29(op))            # products at 2^-57
  6. width: M = (L+R)>>>1; S = (L-R)>>>1; S = sat32(rnd30(S*width_s));
     L' = sat32(M+S); R' = sat32(M-S)
  7. mix: out = sat32(rnd30((1-mix)*dry + mix*wet)); device output stage
     converts s32i -> s24 via rnd5 + saturation (to_s24)

External-memory traffic (exact, per output frame): 16 tap reads + 16 tap
writes + 1 predelay read + 1 predelay write = 34 words/frame = 136 B/frame
(reconciles with reports/sxt-016 probe_fx_reverb1 rows; see README).

Original to this repository (Apache-2.0). No Surge source, tables, or assets
are copied; algorithm structure is cited from the pinned external tree.
"""

REV_TAPS = 16
REV_TAP_BITS = 4
REV_BITS = 15
MAX_REV_DLY = 1 << REV_BITS            # 32768
BLOCK = 32
TAP_WORDS = REV_TAPS * MAX_REV_DLY     # 524288 composite-tap words

# word width of the external storage words (FROZEN; see README stability).
# Internal value format Q4.28: 28 fraction bits + 3 integer headroom bits and
# sign, carried in 32-bit containers (range +/-8, LSB 2^-28). HEADROOM IS
# LOAD-BEARING: the composite loop value fbw = ca*sum + predelay reaches +/-3
# and tap writes reach +/-4*max(delay_fb) at coherent summation; the pinned
# engine carries these in float without clipping. The 28 fraction bits keep
# the quiet tail quantization 32x below the 24-bit audio LSB (the float
# reference has relative precision; a pure 24-bit fixed grid measures ~48 dB
# worse on long tails -- measured, see README).
STORAGE_BITS = 32
DST_FRAC = 28
IO_SHIFT = 5  # s24 -> s32i: value * 2**28 = in24 << 5
S32_MIN = -(1 << 31)
S32_MAX = (1 << 31) - 1
S24_MIN = -(1 << 23)
S24_MAX = (1 << 23) - 1
REG_MAX = (1 << 79) - 1
REG_MIN = -(1 << 79)


def rnd(x, f):
    return (x + (1 << (f - 1))) >> f


def sat(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def sat32(x):
    return sat(x, S32_MIN, S32_MAX)


def q31(v):
    """float -> c31 (round-half-up at quantize time, host side)."""
    return sat32(int(v * (1 << 31) + 0.5) if v >= 0 else -int(-v * (1 << 31) + 0.5))


def q30(v):
    return sat32(int(v * (1 << 30) + 0.5) if v >= 0 else -int(-v * (1 << 30) + 0.5))


def q29(v):
    return sat32(int(v * (1 << 29) + 0.5) if v >= 0 else -int(-v * (1 << 29) + 0.5))


class Reverb1Fixed:
    """One Reverb1 instance. State is per-instance by construction (AGENTS.md:
    per-instance effect state is never shared)."""

    def __init__(self, cp, assert_width=True):
        self.cp = cp
        self.assert_width = assert_width
        self.trace = None  # optional dict of debug capture lists (off by default)
        # coefficient plane quantization (frozen formats)
        self.delay_time = list(cp["delay_time"])          # int, 256ths of sample
        self.delay_fb = [q31(v) for v in cp["delay_fb"]]  # c31
        self.pdtime = int(cp["pdtime"])
        self.pan_l = [q31(v) for v in cp["pan_l"]]        # c31
        self.pan_r = [q31(v) for v in cp["pan_r"]]
        self.damp = q31(cp["damp"])
        self.damp_m1 = q31(cp["damp_m1"])
        (b0, b1, b2, a1, a2) = cp["band1"]
        self.band1 = [q29(v) for v in (b0, b1, b2, a1, a2)]
        (b0, b1, b2, a1, a2) = cp["locut"]
        self.locut = [q29(v) for v in (b0, b1, b2, a1, a2)]
        (b0, b1, b2, a1, a2) = cp["hicut"]
        self.hicut = [q29(v) for v in (b0, b1, b2, a1, a2)]
        self.lowcut_active = bool(cp["lowcut_active"])
        self.hicut_active = bool(cp["hicut_active"])
        self.mix = q30(cp["mix"])
        self.mix_m1 = (1 << 30) - self.mix
        self.width_s = q30(cp["width_s"])
        self.reset()

    def reset(self):
        """initialize()/clear_buffers(): zero long-buffer state, biquad state,
        position counters. Coefficients are re-derivable from the plane."""
        self.delay = [0] * (REV_TAPS * MAX_REV_DLY)   # external in RTL
        self.predelay = [0] * MAX_REV_DLY             # external in RTL
        self.out_tap = [0] * REV_TAPS                 # on-chip
        self.delay_pos = 0
        self.regs = [[0, 0], [0, 0], [0, 0]]          # [filter][ch] reg0
        self.regs2 = [[0, 0], [0, 0], [0, 0]]         # [filter][ch] reg1
        self.ext_reads = 0
        self.ext_writes = 0

    # -- external memory transaction view -----------------------------------
    # The model can be driven with an explicit external-memory hook so the RTL
    # traffic can be reconciled transaction-for-transaction. When ext_hook is
    # set, reads/writes go through it; otherwise the local lists are used.
    def attach_ext_memory(self, read_fn, write_fn):
        self._read_fn = read_fn
        self._write_fn = write_fn

    def _rd(self, addr):
        self.ext_reads += 1
        if getattr(self, "_read_fn", None):
            return self._read_fn(addr)
        return self._ext(addr)

    def _wr(self, addr, val):
        self.ext_writes += 1
        if getattr(self, "_write_fn", None):
            self._write_fn(addr, val)
        else:
            self._ext(addr, val)

    def _ext(self, addr, val=None):
        if addr >= TAP_WORDS:
            if val is None:
                return self.predelay[addr - TAP_WORDS]
            self.predelay[addr - TAP_WORDS] = val
            return None
        if val is None:
            return self.delay[addr]
        self.delay[addr] = val
        return None

    # -- audio ---------------------------------------------------------------
    def _biquad(self, coeffs, fi, x, ch):
        """TDF2 with c29 (Q3.29) coefficients and 2^-57-scale accumulators
        (x Q4.28 * c29 = 2^57):
          op    = x*b0 + reg0
          reg0' = x*b1 + reg1 - rn29(a1*op)
          reg1' = x*b2 - rn29(a2*op)
          y     = sat32(rn29(op))
        (products land at 2^(28+29)=2^57; coefficient products are re-rounded
        to the 2^57 accumulator scale exactly once, f=29.)"""
        b0, b1, b2, a1, a2 = coeffs
        reg0 = self.regs[fi][ch]
        reg1 = self.regs2[fi][ch]
        op = x * b0 + reg0
        new_r0 = x * b1 + reg1 - rnd(a1 * op, 29)
        new_r1 = x * b2 - rnd(a2 * op, 29)
        if self.assert_width:
            for v in (op, new_r0, new_r1):
                assert REG_MIN < v < REG_MAX, f"biquad reg overflow fi={fi}: {v}"
        self.regs[fi][ch] = new_r0
        self.regs2[fi][ch] = new_r1
        return sat32(rnd(op, 29))

    def process_block(self, block_l, block_r):
        """block_l/block_r: 32 s24 ints (the FX block input). Returns
        (out_l, out_r) s24 ints after the full pinned chain."""
        assert len(block_l) == BLOCK and len(block_r) == BLOCK
        n = REV_TAPS
        dt = self.delay_time
        damp = self.damp
        damp_m1 = self.damp_m1
        wet_l = [0] * BLOCK
        wet_r = [0] * BLOCK
        for k in range(BLOCK):
            # 0. s24 inputs -> s32i (exact << IO_SHIFT)
            in_l = block_l[k] << IO_SHIFT
            in_r = block_r[k] << IO_SHIFT
            # 1. damped tap outputs (16 external reads)
            #    (c31 x Q4.28 -> Q4.28: shift = 31 + 28 - 28 = 31)
            out_tap = self.out_tap
            for t in range(n):
                dp = (self.delay_pos - (dt[t] >> 8)) & (MAX_REV_DLY - 1)
                new_t = self._rd((dp << REV_TAP_BITS) + t)
                out_tap[t] = sat32(rnd(damp * out_tap[t] + damp_m1 * new_t, 31))
            # 2. feedback: ca*out_sum + predelay read (ca = -2/16 exact)
            fbsum = 0
            for t in range(n):
                fbsum += out_tap[t]
            pd_read = self._rd(REV_TAPS * MAX_REV_DLY + ((self.delay_pos - self.pdtime) & (MAX_REV_DLY - 1)))
            fbw = -(fbsum >> 3) + pd_read
            # 3. advance + predelay write (s24 -> s32i: << IO_SHIFT, exact;
            #    0.5*(L+R) via the exact >>1 floor)
            self.delay_pos = (self.delay_pos + 1) & (MAX_REV_DLY - 1)
            self._wr(REV_TAPS * MAX_REV_DLY + self.delay_pos,
                     sat32(((in_l + in_r) >> 1)))
            # 4. tap writes + pan sums (16 external writes)
            fl = fr = 0
            pan_l = self.pan_l
            pan_r = self.pan_r
            dfb = self.delay_fb
            for t in range(n):
                ot = out_tap[t]
                fl += sat32(rnd(pan_l[t] * ot, 31))
                fr += sat32(rnd(pan_r[t] * ot, 31))
                self._wr((self.delay_pos << REV_TAP_BITS) + t, sat32(rnd(dfb[t] * (fbw + ot), 31)))
            wet_l[k] = sat32(fl)
            wet_r[k] = sat32(fr)

        # 5. biquads in pinned order
        if self.lowcut_active:
            wet_l = [self._biquad(self.locut, 0, v, 0) for v in wet_l]
            wet_r = [self._biquad(self.locut, 0, v, 1) for v in wet_r]
        wet_l = [self._biquad(self.band1, 1, v, 0) for v in wet_l]
        wet_r = [self._biquad(self.band1, 1, v, 1) for v in wet_r]
        if self.hicut_active:
            wet_l = [self._biquad(self.hicut, 2, v, 0) for v in wet_l]
            wet_r = [self._biquad(self.hicut, 2, v, 1) for v in wet_r]
        # 6. width (SurgeFXConfig: widthIsLinear absent -> dB mode, side only)
        #    encodeMS: M = 0.5*(l+r), S = 0.5*(l-r); S *= width_s; decode.
        ws = self.width_s
        if getattr(self, "trace", None) is not None:
            self.trace.setdefault("width_l_in", []).extend(wet_l)
            self.trace.setdefault("width_r_in", []).extend(wet_r)
        for k in range(BLOCK):
            l, r = wet_l[k], wet_r[k]
            mid = (l + r) >> 1
            s = sat32(rnd(((l - r) >> 1) * ws, 30))
            wet_l[k] = sat32(mid + s)
            wet_r[k] = sat32(mid - s)
        if getattr(self, "trace", None) is not None:
            self.trace.setdefault("post_width_l", []).extend(wet_l)
        # 7. mix fade (constant coefficient at converged lag); the dry term
        # is widened to s32i first (c30 x Q4.28 -> Q4.28: shift 30)
        mix = self.mix
        mix_m1 = self.mix_m1
        out_l, out_r = [], []
        for k in range(BLOCK):
            dry_l = block_l[k] << IO_SHIFT
            dry_r = block_r[k] << IO_SHIFT
            out_l.append(sat32(rnd(mix_m1 * dry_l + mix * wet_l[k], 30)))
            out_r.append(sat32(rnd(mix_m1 * dry_r + mix * wet_r[k], 30)))
        # NOTE: outputs are s32i (Q4.28) internal words. The pinned engine's
        # FX output feeds the send-return sum in float WITHOUT clipping at
        # +/-1.0; the s24 device clamp belongs to the final output stage
        # (see to_s24), never to the FX block boundary.
        return out_l, out_r

    def to_s24(self, x):
        """s32i (Q4.28) -> s24 device word: round at f=5 then saturate."""
        return sat(rnd(x, IO_SHIFT), S24_MIN, S24_MAX)

    # -- checkpoints (RTL exactness contract) --------------------------------
    def checkpoint(self):
        """Small-state checkpoint after each block. The long buffers are NOT
        checkpointed sample-for-sample; RTL-vs-model equality on them is
        established by (a) the transaction log (addr+data of every external
        access) and (b) the audio checkpoints, which make divergent buffer
        content observable in the outputs. For short test inputs the compare
        tool additionally hashes the full buffer contents both sides."""
        return {
            "delay_pos": self.delay_pos,
            "out_tap": list(self.out_tap),
            "regs": [list(r) for r in self.regs] + [list(r) for r in self.regs2],
        }
    def buffer_digest(self):
        import hashlib

        h = hashlib.sha256()
        for v in self.delay:
            h.update(v.to_bytes(4, "little", signed=True))
        for v in self.predelay:
            h.update(v.to_bytes(4, "little", signed=True))
        return h.hexdigest()

    def buffer_json(self):
        return {"taps_words": len(self.delay), "predelay_words": len(self.predelay),
                "tap_bits": STORAGE_BITS, "predelay_bits": STORAGE_BITS}


class SchroederGeneric:
    """NEGATIVE CONTROL ONLY (issue #17 acceptance: a generic reverb under a
    support claim must fail the reference-budget check). Plain Schroeder
    4-comb + 2-allpass network tuned to a similar t60. NOT a product path,
    NOT an adaptation for any preset, and never counted as Reverb 1."""

    def __init__(self, comb_ms=(29.7, 37.7, 41.1, 43.7), ap_ms=(5.0, 1.7), t60_s=3.0):
        self.comb = [int(round(FS_B * ms / 1000.0)) for ms in comb_ms]
        self.ap = [int(round(FS_B * ms / 1000.0)) for ms in ap_ms]
        self.g = [10 ** (-3 * ms / 1000.0 / t60_s) for ms in comb_ms]
        self.ap_g = 0.7
        self.bufs = [[0] * c for c in self.comb]
        self.abufs = [[0] * a for a in self.ap]
        self.idx = [0] * len(self.comb)
        self.aidx = [0] * len(self.ap)

    def process(self, x):
        acc = 0.0
        for i, c in enumerate(self.comb):
            y = self.bufs[i][self.idx[i]]
            self.bufs[i][self.idx[i]] = x + self.g[i] * y
            acc += y
        v = acc / len(self.comb)
        for i, a in enumerate(self.ap):
            d = self.abufs[i][self.aidx[i]]
            v_out = -self.ap_g * v + d
            self.abufs[i][self.aidx[i]] = v + self.ap_g * v_out
            v = v_out
            self.aidx[i] = (self.aidx[i] + 1) % a
        return v


FS_B = 48000.0


def coerce_ints(obj):
    """JSON-safe dump helper for coefficient planes (documentation artifacts)."""
    if isinstance(obj, dict):
        return {k: coerce_ints(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [coerce_ints(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj
    return str(obj)
