#!/usr/bin/env python3
"""SXT-026 frozen fixed-point WAVETABLE oscillator model.

This module is the FROZEN reference for the SXT-026 RTL
(`rtl/oscillators/wavetable/`). RTL-vs-model agreement must be EXACT
(integer equality at every declared checkpoint). Model-vs-pinned-engine
agreement is governed by [PROPOSED] error budgets (fidelity policy DRAFT;
nothing is frozen; reports/sxt-026 records achieved numbers only).

Word lengths and operation order are normative: `model/oscillators/wavetable/
README.md`. Q formats and helpers are SHARED with the SXT-022 voice model
(`model/voice/voice_model.py`): Q10.21 samples/coefs, Q2.29 envelope phase,
Q13.18 pitchmult_inv, 16-bit sinc lipol fraction, round-half-up products.

Structure is cited from the pinned engine (read, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  WavetableOscillator.cpp process_block / convolute / init   impulse engine,
        mip selection (a = dt*pitchmult_inv vs 2^-k*1.8, ts >= 2^(k+1)),
        morph frame interpolation deformContinuous/deformLegacy,
        distort_level (skewV + saturate), 1-pole hpf output stage
  OscillatorBase.h / ClassicOscillator.cpp prepare_unison    unison setup
  sst-basic-blocks OscillatorDriftUnisonCharacter.h          UnisonSetup
        (detune bias/offset, pan law; pan cancels in the declared mono
        (L+R)/2 bus: (panL+panR)/2 == 1 per voice)
  Wavetable.cpp BuildWT / MipMapWT                            dt = 1/size,
        level-0 conversion (i15/i16 -> float, exact binary scaling), 63-tap
        halfband mip cascade (hrfilter[63], QUOTED constants — see
        decision-records/0004)
  SurgeStorage.h                                             FIRipol_M/N

Arithmetic discipline (FROZEN, same rules as SXT-022):
  * every value is a Python int in two's-complement Q-format;
  * products are exact then rounded back round-half-up:
        r = (a*b + (1 << (s-1))) >> s,  s = fa+fb-fq,  saturated;
  * oscstate is a 64-bit Q10.21 word (no overflow over any fixture);
  * the engine computes ipos = (unsigned)(2^24*oscstate*pitchmult_inv) in
    float32; the model truncates the exact integer product (finer) —
    declared deviation, absorbed by the model-vs-reference budget;
  * mip level-0 table words are EXACT vs the engine for int15/int16 assets
    (power-of-two scaling: Q10.21 word = s << 7 / s << 6); mip levels >= 1
    are built in double from the quoted 63-tap halfband and quantized once
    (the engine accumulates in float32 — declared deviation);
  * no floating point at run time; no dict-iteration-order dependence.
"""

import json
import math
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from model.voice import voice_model as vm  # noqa: E402

FQ = vm.FQ
ONE = vm.ONE
QMAX, QMIN = vm.QMAX, vm.QMIN
F_PHASE = vm.F_PHASE
PMI_F = vm.PMI_F
SR = vm.SR
BLOCK_SIZE = vm.BLOCK_SIZE
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS
OB_LENGTH = vm.OB_LENGTH
FIRIPOL_M = vm.FIRIPOL_M
FIRIPOL_N = vm.FIRIPOL_N
FIROFFSET = vm.FIROFFSET

MAX_UNISON = 16            # SurgeStorage.h (unison cap; profile-v1 cap too)
BLOCK_SIZE_OS_INV_FQ = 6   # oscstate/64 exact shift (1/64 is a power of two)
INTEGRATOR_HPF = vm.qint((1.0 - 40.0 / 48000.0) ** 2)   # integrator_hpf
HPF_CYCLE_LOSS = 0.99      # WavetableOscillator.cpp hpf_cycle_loss
LAG_RATE = vm.qint(0.05)   # l_*.setRate(0.05): one-pole per block
MORPH_SHAPE_SCALE_F = 0.99999   # shape *= (n-1+nointerp)*0.99999f
TAYLORSCALE = vm.qint(math.sqrt(27.0 / 4.0))

# Mip selection thresholds (float32 as the engine evaluates them) and the
# minimum FULL table size per level (WavetableOscillator::convolute).
MIP_THRESHOLDS = []
for _k in (6, 5, 4, 3, 2, 1):
    MIP_THRESHOLDS.append((_k, struct.unpack(
        "f", struct.pack("f", (2.0 ** -_k) * 1.8))[0], 1 << (_k + 1)))


def qint(x):
    return vm.qint(x)


# --------------------------------------------------- mip halfband (quoted)
# QUOTED ENGINE CONSTANTS — src/common/dsp/Wavetable.cpp hrfilter[63]
# (surge@58914e59c608ed4384ba6002e44c3465c58b2e71; GPL-3.0-or-later).
# 63-tap halfband lowpass used by Wavetable::MipMapWT to build mip levels.
# Provenance and license boundary: decision-records/0004 (successor to 0003
# per 0002's standing requirement). No construction formula exists in the
# pinned tree; re-derivation would be a different (wrong) model.
HRFILTER_63 = [
    -9.637663112e-008, -2.216513622e-006, -1.200509132e-006, 1.79627641e-005,
    1.773084477e-005,  -5.898886593e-005, -8.980041457e-005, 0.0001233910152,
    0.0002964516752,  -0.0001573183545,  -0.0007465034723, 1.204636671e-018,
    0.001525280299,    0.0006605535164,  -0.002588451374,  -0.002282966627,
    0.003618633142,    0.005384810269,   -0.003885820275,  -0.01036664937,
    0.002154163085,    0.0172905419,      0.003383208299,  -0.02569983155,
    -0.01536878385,    0.03457865119,     0.0387589559,    -0.04251147807,
    -0.0895993337,     0.04802387953,     0.3125254214,     0.4499996006,
    0.3125254214,      0.04802387953,    -0.0895993337,    -0.04251147807,
    0.0387589559,      0.03457865119,    -0.01536878385,   -0.02569983155,
    0.003383208299,    0.0172905419,      0.002154163085,  -0.01036664937,
    -0.003885820275,   0.005384810269,    0.003618633142,  -0.002282966627,
    -0.002588451374,   0.0006605535164,   0.001525280299,   1.204636671e-018,
    -0.0007465034723, -0.0001573183545,   0.0002964516752,  0.0001233910152,
    -8.980041457e-005,-5.898886593e-005,  1.773084477e-005, 1.79627641e-005,
    -1.200509132e-006,-2.216513622e-006, -9.637663112e-008,
]


def build_mip_tables(source_words, wave_size, wave_count, built_levels):
    """MipMapWT() float32->double cascade, quantized once per level.

    source_words: Q10.21 ints for level 0 (wave_count * wave_size).
    Returns a flat list per level (same order as the RTL table memory).
    """
    levels = [list(source_words)]
    for lvl in range(1, built_levels):
        prev = levels[lvl - 1]
        psize = wave_size >> (lvl - 1)
        lsize = wave_size >> lvl
        base = (lvl - 1) * 0  # frames are laid out per level, fixed stride
        prev_frames = [prev[f * psize:(f + 1) * psize] for f in range(wave_count)]
        out = []
        # double-precision cascade on REAL table values (Q-words are
        # converted first; the engine accumulates float32 — declared)
        for f in range(wave_count):
            fr = [w / float(ONE) for w in prev_frames[f]]
            for i in range(lsize):
                acc = 0.0
                for a in range(63):
                    acc += HRFILTER_63[a] * fr[((i << 1) + a - 31) & (psize - 1)]
                out.append(vm.qint(acc))
        levels.append(out)
    return levels


def wavetable_from_file(path):
    """Level-0 Q10.21 words from a .wt file (EXACT for int formats).

    int15: Q10.21 word = s << 7 (i152float_block scale 1/16384)
    int16_full: Q10.21 word = s << 6 (i162float_block scale 1/32768)
    float32: quantized once (qint of the float32 value).
    """
    import hashlib
    data = open(path, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    if data[:4] != b"vawt":
        raise RuntimeError("%s: not a vawt wavetable" % path)
    wave_size, = struct.unpack("<I", data[4:8])
    wave_count, flags = struct.unpack("<HH", data[8:12])
    words = []
    off = 12
    if flags & 0x0004:  # int16
        sh = 7 if not (flags & 0x0008) else 6
        for _ in range(wave_size * wave_count):
            s, = struct.unpack("<h", data[off:off + 2])
            off += 2
            words.append(vm.sat(s << sh))
    else:
        for _ in range(wave_size * wave_count):
            f, = struct.unpack("<f", data[off:off + 4])
            off += 4
            words.append(qint(f))
    return {"sha256": sha, "wave_size": wave_size, "wave_count": wave_count,
            "flags": flags, "words": words}


# ----------------------------------------------------------------- osc
class WavetableOsc:
    """WavetableOscillator slice (mono out; FM path NOT in this slice)."""

    def __init__(self, inp, key):
        self.inp = inp
        if inp.unison < 1 or inp.unison > MAX_UNISON:
            # Explicit rejection, never a silent clamp (issue #19 acceptance;
            # the engine itself clamps — SXT-015's 58 flagged cases — and our
            # product contract rejects beyond-cap unison at load).
            raise RuntimeError(
                "unison %d outside 1..MAX_UNISON(%d): explicitly rejected"
                % (inp.unison, MAX_UNISON))
        self.pitch = min(148, key + 12 * inp.octave)
        self.n_unison = inp.unison
        self.deform = inp.deform_mode  # "xt14_continuous" | "xt134_legacy"
        self.nointerp = 0 if inp.extend_range else 1

        wt = inp.wt
        self.wave_size = wt["wave_size"]
        self.n_tables = wt["wave_count"]
        if not (self.wave_size & (self.wave_size - 1)):
            self.size_po2 = self.wave_size.bit_length() - 1
        self.levels = inp.mip_tables
        self.dt = vm.qint(1.0 / self.wave_size)

        # prepare_unison (UnisonSetup)
        n = self.n_unison
        self.out_attenuation = qint(1.0 / math.sqrt(n))
        self.detune_bias = qint(1.0 if n == 1 else 2.0 / (n - 1))
        self.detune_offset = qint(0.0 if n == 1 else -1.0)

        # lag targets (constant params in this slice): instantize
        self.l_shape = limit_q(qint(inp.morph), 0, ONE)
        self.l_vskew = limit_q(qint(inp.skewv), qint(-1.0), qint(1.0))
        self.l_hskew = limit_q(qint(inp.skewh), qint(-1.0), qint(1.0))
        self.l_clip = vm.qmul(qint(-8.0), vm.qmul(
            vm.qmul(limit_q(qint(inp.saturate), 0, ONE),
                    limit_q(qint(inp.saturate), 0, ONE)),
            limit_q(qint(inp.saturate), 0, ONE)))
        self.t_shape = self.l_shape
        self.t_vskew = self.l_vskew
        self.t_hskew = self.l_hskew
        self.t_clip = self.l_clip
        self.formant_t = max(0, qint(inp.formant))
        self.formant_last = self.formant_t

        self.hpf = self._hpf_target()
        self.hpf_prev = self.hpf

        self.tableipol = 0
        self.tableid = 0
        self.last_tableipol = 0
        self.last_tableid = 0
        self._morph_update(first=True)

        self.osc = [0] * (OB_LENGTH + FIRIPOL_N)
        self.bufpos = 0
        self.osc_out = 0
        self.voices = []
        for v in range(n):
            self.voices.append({
                "oscstate": 0,      # retrigger on -> 0 (deterministic)
                "state": 0,
                "last_level": 0,
                "mipmap": 0,
                "mipmap_ofs": 0,
            })

    # ------------------------------------------------------------- helpers
    def _hpf_target(self):
        """update_lagvals: hpf2 = min(integrator_hpf, 0.99^(4*invt))."""
        pp = vm.ntp_tuningctr(vm.qint(float(self.pitch)))
        invt = vm.qmul(qint(8.175798915), vm.qmul(pp, qint(1.0 / 96000.0)))
        invt = min(ONE, invt)
        # 0.99^(4*invt): 4*invt_real = invt_raw >> 19 (invt_raw is Q10.21)
        hp = qint(HPF_CYCLE_LOSS ** (invt / float(1 << 19)))
        return min(INTEGRATOR_HPF, hp)

    def _morph_update(self, first=False):
        """process_block tableid/tableipol step (n_tables > 1, no sample)."""
        if not first:
            self.last_tableipol = self.tableipol
            self.last_tableid = self.tableid
            # one-pole lag step (rate 0.05) then morph position
            self.l_shape += vm.qmul(LAG_RATE, self.t_shape - self.l_shape)
            shape = limit_q(self.l_shape, 0, ONE)   # getMorph (no mod routed)
            shape = vm.qmul(shape, qint((self.n_tables - 1 + self.nointerp)
                                        * MORPH_SHAPE_SCALE_F))
            if self.deform == "xt14_continuous":
                self.tableipol = shape
                self.tableid = limit_q(shape >> FQ, 0,
                                       max(self.n_tables - 2 + self.nointerp, 0))
            else:  # xt134_legacy
                self.tableipol = shape & (ONE - 1) if shape >= 0 else shape
                whole = shape >> FQ
                self.tableid = limit_q(whole, 0,
                                       max(self.n_tables - 2 + self.nointerp, 0))
                # legacy monotonic clamp
                if self.tableid > self.last_tableid:
                    if self.last_tableipol != ONE:
                        self.tableid = self.last_tableid
                        self.tableipol = ONE
                    else:
                        self.last_tableipol = 0
                elif self.tableid < self.last_tableid:
                    if self.last_tableipol != 0:
                        self.tableid = self.last_tableid
                        self.tableipol = 0
                    else:
                        self.last_tableipol = ONE
        else:
            shape = limit_q(self.l_shape, 0, ONE)
            shape = vm.qmul(shape, qint((self.n_tables - 1 + self.nointerp)
                                        * MORPH_SHAPE_SCALE_F))
            if self.deform == "xt14_continuous":
                self.tableipol = shape
                self.tableid = limit_q(shape >> FQ, 0,
                                       max(self.n_tables - 2 + self.nointerp, 0))
            else:
                self.tableipol = shape & (ONE - 1)
                self.tableid = limit_q(shape >> FQ, 0,
                                       max(self.n_tables - 2 + self.nointerp, 0))
            self.last_tableipol = self.tableipol
            self.last_tableid = self.tableid

    def _table_word(self, mip, table, idx):
        return self.levels[mip][table * (self.wave_size >> mip) + idx]

    # ---------------------------------------------------------- convolute
    def _convolute(self, v, pmi, pitchmult):
        self.block_impulses += 1
        st = self.voices[v]
        # oscstate/64 (exact) * pitchmult_inv (Q13.18) -> Q10.21
        block_pos = vm.qmul(st["oscstate"] >> BLOCK_SIZE_OS_INV_FQ, pmi,
                            fb=PMI_F)

        detune = 0
        if self.n_unison > 1:
            detune = vm.qmul(self.inp.udet_ext_q,
                             vm.qmul(self.detune_bias, qint(float(v)))
                             + self.detune_offset)
        tempt = vm.ntpi_tuningctr(detune)

        ipos = (st["oscstate"] * pmi) >> (FQ + PMI_F - 24)
        ipos &= 0xFFFFFFFF

        if st["state"] == 0:
            self.formant_last = self.formant_t
            # dt (Q10.21) * pitchmult_inv (Q13.18) -> Q10.21
            a_sel = vm.qmul(self.dt, pmi, fb=PMI_F)
            mipmap = 0
            for k, thr, min_ts in MIP_THRESHOLDS:
                if a_sel < qint(thr) and self.wave_size >= min_ts:
                    mipmap = k
                    break
            st["mipmap"] = mipmap
            ofs = 0
            for i in range(mipmap):
                ofs += self.wave_size >> i
            st["mipmap_ofs"] = ofs

        delay = (ipos >> 24) & 0x3F
        m = ((ipos >> 16) & 0xFF) * (FIRIPOL_N << 1)
        lipol = ipos & 0xFFFF

        wt_inc = 1 << st["mipmap"]
        dt2 = vm.qmul(self.dt, qint(float(wt_inc)))

        xt = vm.qmul(qint(float(st["state"]) + 0.5), dt2)
        # hskew taylor warp (hskew = 0 -> exactly 1; implemented in full)
        xt_w = ONE + vm.qmul(self.l_hskew, vm.qmul(qint(4.0), vm.qmul(
            xt, vm.qmul(xt - ONE, vm.qmul(2 * xt - ONE, TAYLORSCALE)))))
        ft = vm.qmul(block_pos, self.formant_t) + \
            vm.qmul(ONE - block_pos, self.formant_last)
        formant = vm.ntp_tuningctr(-ft)
        d = vm.qmul(formant, xt_w)
        dt2 = vm.qmul(dt2, d)

        wtsize = self.wave_size >> st["mipmap"]
        if st["state"] >= (wtsize - 1):
            dt2 += ONE - formant
        t = vm.qmul(dt2, tempt)
        st["state"] &= wtsize - 1

        # deform frame interpolation (2-entry linear blend)
        if self.deform == "xt14_continuous":
            bp = 1 if self.nointerp else block_pos
            tblip = vm.qmul(ONE - bp, self.last_tableipol) + \
                vm.qmul(bp, self.tableipol)
            tid = tblip >> FQ
            target = min(tid + 1, self.n_tables - 1)
            proc = vm.qmul(tblip - (tid << FQ), 1 - self.nointerp)
        else:  # xt134_legacy
            tblip = vm.qmul(ONE - block_pos, self.last_tableipol) + \
                vm.qmul(block_pos, self.tableipol)
            proc = vm.qmul(1 - self.nointerp, tblip)
            tid = self.tableid
            target = self.tableid + 1 - self.nointerp
        w0 = self._table_word(st["mipmap"], tid, st["state"])
        w1 = self._table_word(st["mipmap"], target, st["state"])
        level = vm.qmul(w0, ONE - proc) + vm.qmul(w1, proc)

        # distort_level (skewV + saturate) — WavetableOscillator.cpp order
        a = self.l_vskew >> 1
        x1 = level - vm.qmul(vm.qmul(a, level), level) + a
        x3 = vm.qmul(vm.qmul(vm.qmul(self.l_clip, x1), x1), x1)
        x = vm.qmul(x1, ONE - self.l_clip) + x3
        newlevel = limit_q(x, -ONE, ONE)

        g = newlevel - st["last_level"]
        st["last_level"] = newlevel
        g = vm.qmul(g, self.out_attenuation)
        # stereo pan cancels in the declared (L+R)/2 mono bus

        base = self.bufpos + delay
        m12 = m >> 1
        for k in range(FIRIPOL_N):
            term = vm.SINC_MAIN[m12 + k] + vm.qmul(lipol, vm.SINC_DERIV[m12 + k],
                                                   fb=16)
            self.osc[base + k] = vm.sat(self.osc[base + k] + vm.qmul(term, g))

        st["rate"] = t
        st["oscstate"] = max(0, st["oscstate"] + t)
        st["state"] = (st["state"] + 1) & (wtsize - 1)

    # -------------------------------------------------------- block proc
    def process_block(self):
        """One 64-sample (over-sampled) oscillator block. Returns output."""
        pitch = self.pitch
        assert 24 <= pitch <= 148, "declared slice pitch range is [24, 148]"
        pmi_d = max(1.0, 96000.0 * (1.0 / 8.175798915) * (2.0 ** (-pitch / 12.0)))
        pmi = vm.sat(int(math.floor(pmi_d * (1 << PMI_F) + 0.5)))
        pitchmult = vm.qdiv(1 << PMI_F, pmi, fa=PMI_F, fb=PMI_F)

        # update_lagvals<false> + lag steps (targets constant in-slice)
        self.l_vskew += vm.qmul(LAG_RATE, self.t_vskew - self.l_vskew)
        self.l_hskew += vm.qmul(LAG_RATE, self.t_hskew - self.l_hskew)
        self.l_clip += vm.qmul(LAG_RATE, self.t_clip - self.l_clip)
        hpf_new = self._hpf_target()
        hpf_start = self.hpf_prev
        hpf_d = hpf_new - hpf_start
        self.hpf_prev = hpf_new

        self.ctrl = {"pmi": pmi, "pitchmult": pitchmult,
                     "hpf_start": hpf_start, "hpf_d": hpf_d}

        if self.n_tables > 1:
            self._morph_update()
        else:
            self.tableipol = 0
            self.tableid = 0
            self.last_tableipol = 0
            self.last_tableid = 0

        a_cov = vm.qmul(BLOCK_SIZE_OS << FQ, pitchmult)
        self.ctrl["a_cov"] = a_cov
        self.block_impulses = 0
        for v in range(self.n_unison):
            while self.voices[v]["oscstate"] < a_cov:
                self._convolute(v, pmi, pitchmult)
            self.voices[v]["oscstate"] -= a_cov

        out = []
        for k in range(BLOCK_SIZE_OS):
            hpf = hpf_start + vm.qround(hpf_d * (k + 1), 6)
            acc = vm.qmul(self.osc_out, hpf)
            self.osc_out = vm.sat(acc + self.osc[self.bufpos + k])
            out.append(self.osc_out)
        for k in range(BLOCK_SIZE_OS):
            self.osc[self.bufpos + k] = 0
        self.bufpos = (self.bufpos + BLOCK_SIZE_OS) & (OB_LENGTH - 1)
        if self.bufpos == 0:
            for k in range(FIRIPOL_N):
                self.osc[k] = self.osc[OB_LENGTH + k]
                self.osc[OB_LENGTH + k] = 0
        self.last_oscout = out
        return out


def limit_q(x, lo, hi):
    return vm.limit_i(x, lo, hi)


class AdsrWt:
    """ADSRModulationSource, digital mode, decay shape d_s = 1 (sqrt-domain
    linear-in-amplitude decay) and release power r_s (Kick.fxp uses r_s=2).
    Fail-closed on anything outside the declared slice. Structure cited from
    ADSRModulationSource.h process_block (pinned); sqrt evaluated in double
    at the pinned formula and quantized once (declared deviation, as in
    SXT-022 coefficient-rate sqrt)."""

    S_ATTACK, S_DECAY, S_SUSTAIN, S_RELEASE, S_UBER, S_IDLE_WAIT1, S_IDLE = \
        vm.Adsr.S_ATTACK, vm.Adsr.S_DECAY, vm.Adsr.S_SUSTAIN, \
        vm.Adsr.S_RELEASE, vm.Adsr.S_UBER, vm.Adsr.S_IDLE_WAIT1, vm.Adsr.S_IDLE
    PH_ONE = 1 << F_PHASE

    def __init__(self, prm, name):
        if int(prm["mode"]) != 0:
            raise RuntimeError(f"{name}: analog envelope mode not in slice")
        if int(prm["d_s"]) != 1:
            raise RuntimeError(f"{name}: decay shape {prm['d_s']} not in "
                               "slice (only d_s=1 declared)")
        self.name = name
        self.a = qint(prm["a"])
        self.d = qint(prm["d"])
        self.s = qint_phase(prm["s"])
        self.r = qint(prm["r"])
        self.a_s = int(prm["a_s"])
        self.d_s = int(prm["d_s"])
        self.r_s = int(prm["r_s"])
        self.A_MIN = qint(-8.0)
        self.phase = 0
        self.output = 0
        self.idlecount = 0
        self.state = self.S_ATTACK
        self.scalestage = ONE
        self.s_lvl = 0

    def attack_from(self, start):
        assert start == 0, "attackFrom(start>0) not in slice"
        self.phase = 0
        self.output = 0
        self.idlecount = 0
        self.scalestage = ONE
        self.state = self.S_ATTACK
        if (self.a - self.A_MIN) < qint(0.01):
            self.state = self.S_DECAY
            self.output = ONE
            self.phase = self.PH_ONE

    def release(self):
        self.scalestage = self.output
        self.phase = self.PH_ONE
        self.state = self.S_RELEASE

    def process_block(self):
        if self.state == self.S_ATTACK:
            self.phase += vm.envelope_rate_linear_nowrap(self.a)
            if self.phase >= self.PH_ONE:
                self.phase = self.PH_ONE
                self.state = self.S_DECAY
                self.s_lvl = self.s
            ph = self.phase >> (F_PHASE - FQ)
            if self.a_s == 1:
                self.output = ph
            else:
                raise RuntimeError(f"{self.name}: attack shape {self.a_s} "
                                   "not in slice")
        elif self.state == self.S_DECAY:
            rate = vm.envelope_rate_linear_nowrap(self.d)
            # d_s == 1: sx = sqrt(phase); l_lo/hi = phase -/+ 2*sx*rate + rate^2
            sx = int(math.floor(math.sqrt(self.phase / float(self.PH_ONE))
                                * self.PH_ONE + 0.5))
            two_sx_rate = vm.qround(2 * vm.qmul(sx, rate, fa=F_PHASE,
                                                fb=F_PHASE, fq=F_PHASE), 0)
            rr = vm.qround(vm.qmul(rate, rate, fa=F_PHASE, fb=F_PHASE,
                                   fq=F_PHASE), 0)
            l_lo = self.phase - two_sx_rate + rr
            l_hi = self.phase + two_sx_rate + rr
            if (self.s < qint(1e-3) and self.phase < qint(1e-4)) or \
                    (self.s == 0 and self.d < qint(-7.0)):
                l_lo = 0
            # engine: rate > 1.0 -- rate is a Q2.29 word here
            if rate > (1 << F_PHASE) and l_lo > self.s:
                l_lo = self.s
            self.phase = limit_q(self.s, l_lo, l_hi)
            self.output = self.phase >> (F_PHASE - FQ)
        elif self.state == self.S_RELEASE:
            self.phase -= vm.envelope_rate_linear_nowrap(self.r)
            out = self.phase >> (F_PHASE - FQ)
            for _ in range(self.r_s):
                out = vm.qmul(out, self.phase >> (F_PHASE - FQ))
            self.output = vm.qmul(out, self.scalestage)
            if self.phase < 0:
                self.state = self.S_IDLE
                self.output = 0
        elif self.state == self.S_IDLE:
            self.idlecount += 1
        self.output = limit_i_q(self.output, 0, ONE)

    def is_idle(self):
        return self.state == self.S_IDLE and self.idlecount > 0


def qint_phase(x):
    return vm.qint_phase(x)


def limit_i_q(x, lo, hi):
    return vm.limit_i(x, lo, hi)


class Inputs:
    """Frozen model inputs (wt_inputs.json)."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.preset_path = d["preset_path"]
        self.octave = int(d["octave"])
        self.unison = int(d["unison"])
        self.morph = d["morph"]
        self.skewv = d["skewv"]
        self.saturate = d["saturate"]
        self.formant = d["formant"]
        self.skewh = d["skewh"]
        self.udet = d["unison_detune"]
        self.udet_ext_q = qint(12.0 * self.udet)   # ct_oscspread: 12*f semitones
        self.deform_mode = d.get("deform_mode", "xt14_continuous")
        self.extend_range = bool(d.get("extend_range", True))
        self.retrigger = bool(d.get("retrigger", True))
        self.o2_level = d["o2_level"]
        self.scene_volume = d["scene_volume"]
        self.vca_db = d["vca_db"]
        self.vca_vs = d.get("vca_velsense", 0.0)
        self.master_db = d["master_db"]
        self.adsr = d["adsr"]
        self.wt_sha256 = d["wt_sha256"]
        self.wt_relpath = d["wt_relpath"]
        self.declared_overrides = d.get("declared_overrides", [])

        # wavetable words: either embedded (small fixtures) or from file
        if "wt_words" in d:
            self.wt = {"wave_size": d["wt_wave_size"],
                       "wave_count": d["wt_wave_count"],
                       "words": d["wt_words"]}
        else:
            root = os.environ.get("ORACLE_SURGE_DATA",
                                  "/Users/joseph/dev/surge-xt-oracle/surge/resources/data")
            wt_path = os.path.join(root, self.wt_relpath)
            self.wt = wavetable_from_file(wt_path)
            if self.wt["sha256"] != self.wt_sha256:
                raise RuntimeError(
                    "ABORT: asset identity mismatch %s: %s != %s"
                    % (wt_path, self.wt["sha256"], self.wt_sha256))
        self.mip_tables = build_mip_tables(self.wt["words"],
                                           self.wt["wave_size"],
                                           self.wt["wave_count"],
                                           self.wt["wave_size"].bit_length() - 1)


class Slice:
    """Voice slice: WT osc -> o2 level -> AEG gain -> scene out -> halfband
    -> master (mono). Sine osc muted, filter units Off, noise/ring muted by
    the declared fixture configuration (see extract_inputs.py)."""

    def __init__(self, inp, key, velocity):
        self.inp = inp
        self.key = key
        self.gate = True
        self.osc = WavetableOsc(inp, key)
        self.aeg = AdsrWt(inp.adsr, "aeg")
        self.aeg.attack_from(0)
        self.lvl = vm.amp_to_linear(qint(inp.o2_level))
        # Gain = db_to_linear(vca + vs*(1 - velocity/127)) * aeg (SurgeVoice
        # calc_ctrldata; velocity is constant over a note; the engine's
        # velocity source starts at the note velocity)
        vca_db_eff = inp.vca_db + inp.vca_vs * (1.0 - velocity / 127.0)
        self.vca = vm.db_to_linear(qint(vca_db_eff))
        self.outl = vm.amp_to_linear(qint(inp.scene_volume)) >> 1
        self.master = vm.db_to_linear(qint(inp.master_db))
        self.gain = vm.qmul(self.vca, self.aeg.output)
        self.prev_gain = self.gain
        self.halfband = vm.HalfbandD2()
        self.keep_playing = True

    def process_block(self, b):
        self.aeg.process_block()
        if self.aeg.is_idle():
            self.keep_playing = False
        osout = self.osc.process_block()
        target = vm.qmul(self.vca, self.aeg.output)
        d = target - self.prev_gain
        start = self.prev_gain
        self.prev_gain = target
        scene = [0] * BLOCK_SIZE_OS
        for k in range(BLOCK_SIZE_OS):
            x = vm.qmul(osout[k], self.lvl)
            v = vm.qmul(x, start + vm.qround(d * (k + 1), 6))
            scene[k] = v
        scene = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene]
        bl = self.halfband.process(scene)
        mono = []
        for k in range(BLOCK_SIZE):
            l = vm.qmul(bl[k], self.master)
            l = vm.limit_i(l, vm.qint(-8.0), vm.qint(8.0))
            m = vm.limit_i(l, -ONE, ONE)
            mono.append(m)          # Q10.21; int16 conversion happens once
        self.lastmono = mono        # in the runner (single conversion)
        return mono, osout, self.keep_playing


def write_wav16(path, samples):
    vm.write_wav16(path, samples, SR)
