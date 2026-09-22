#!/usr/bin/env python3
"""SXT-033 frozen fixed-point CLASSIC oscillator family model.

This module is the FROZEN reference for the SXT-033 RTL
(`rtl/oscillators/classic/`). RTL-vs-model agreement must be EXACT
(integer equality at every declared checkpoint). Model-vs-pinned-engine
agreement is governed by [PROPOSED] error budgets (fidelity policy DRAFT;
nothing is frozen; `reports/SXT-033` records achieved numbers only).

Scope (issue #67 / SXT-033): the Classic oscillator family BEYOND the landed
SXT-022 Attacky configuration (shape 0, sub mix 1, sync 0, unison 1). This
leaf extends PARAMETER coverage only — no new algorithm: the impulse engine
is the same 4-state machine frozen in SXT-022, now driven over the declared
parameter classes observed in the recovery-basis presets' normalized graphs:

  * shape        p[0]  ct_percent_bipolar [-1, 1]
  * width 1/2    p[1]/p[2]  ct_percent, lag-limited to [0.001, 0.999]
  * sub mix      p[3]  ct_percent [0, 1]  (0 = main path only, 1 = sub only)
  * sync         p[4]  ct_syncpitch [0, 60] — sync > 0 engages the engine's
                 per-voice syncstate restart machine (declared class)
  * unison       p[6]  ct_osccount [1, 16], detune p[5] ct_oscspread
                 (get_extended = 12*f semitones when extended) — unison > 1
                 replicates the impulse machine per voice with UnisonSetup
                 attenuation/detune (declared class)

Everything else stays at the SXT-022 declared boundaries and REFUSES
fail-closed (drift != 0, absolute detune mode, FM routing into the modeled
slot, analog envelopes, character Bright, unison > 16, pitch outside
[24, 148]).

Word lengths and operation order are normative:
`model/oscillators/classic/README.md`. Q formats and helpers are SHARED with
the frozen SXT-022 voice model (`model/voice/voice_model.py`, imported, not
duplicated): Q10.21 samples/coefs, Q2.29 envelope phase, Q13.18
pitchmult_inv, 16-bit sinc lipol fraction, round-half-up products.

Structure is cited from the pinned engine (read, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  ClassicOscillator.cpp init / process_block / convolute /
        update_lagvals          impulse engine incl. the syncstate restart
                                branch and per-voice detune
  OscillatorBase.h prepare_unison
  sst-basic-blocks OscillatorDriftUnisonCharacter.h  UnisonSetup
        (attenuation 1/sqrt(n), detune bias 2/(n-1) offset -1, pan law;
        the pan law is INERT here: the modeled voice runs mono —
        StereoVoice calls process_block with stereo = (fbc == fc_wide) and
        the declared fixture configuration pins fbc to fc_serial1 — and
        would cancel in the (L+R)/2 bus anyway)
  sst-basic-blocks mechanics/simd-ops.h rcp     t_inv = rcp_ss(t): the raw
        SSE reciprocal approximation is microarchitecture-specific and is
        NOT reproduced bit-exactly; the model divides exactly in Q10.21 —
        DECLARED DEVIATION, absorbed by the model-vs-reference budget
  sst-basic-blocks OscillatorDriftUnisonCharacter.h CharacterFilter (Warm /
        Neutral; Bright refuses)

Arithmetic discipline (FROZEN, same rules as SXT-022/SXT-026):
  * every value is a Python int in two's-complement Q-format;
  * products are exact then rounded back round-half-up:
        r = (a*b + (1 << (s-1))) >> s,  s = fa+fb-fq,  saturated;
  * oscstate/syncstate are 64-bit Q10.21 words per unison voice;
  * the engine computes ipos = (unsigned)(2^24*oscstate*pitchmult_inv) in
    float32; the model truncates the exact integer product (finer) —
    declared deviation (SXT-022 rule 3 / SXT-026 deviation 3);
  * unison constants (attenuation, bias, offset, per-voice detune) are
    computed at QUANTIZATION TIME in float32 emulation of the engine's
    exact operation order (`_f32` round-trips), then quantized once to
    Q10.21 — no floating point at run time;
  * frequency-domain lookups evaluate the pinned construction formulas in
    double and quantize once (SXT-022 rule 5);
  * no floating point at run time; no dict-iteration-order dependence.
"""

import json
import math
import struct

from model.voice import voice_model as vm

FQ = vm.FQ
ONE = vm.ONE
SR = vm.SR
BLOCK_SIZE = vm.BLOCK_SIZE
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS
OB_LENGTH = vm.OB_LENGTH
FIRIPOL_N = vm.FIRIPOL_N
FIROFFSET = vm.FIROFFSET
F_PHASE = vm.F_PHASE
PMI_F = vm.PMI_F
MAX_UNISON = 16            # SurgeStorage.h MAX_UNISON
HPF_CYCLE_LOSS = 0.995     # ClassicOscillator.cpp hpf_cycle_loss
INTEGRATOR_HPF = vm.qint((1.0 - 40.0 / 48000.0) ** 2)
LAG_RATE = vm.qint(0.05)
SYNC_CEILING = 156         # (12 + 72 + 72) - pitch clamp in convolute


def _f32(x):
    """Round a double to the nearest float32 value (quantization time only)."""
    return struct.unpack("f", struct.pack("f", x))[0]


def limit_q(x, lo, hi):
    return vm.limit_i(x, lo, hi)


def qint_phase(x):
    return vm.qint_phase(x)


class AdsrClassic(vm.Adsr):
    """SXT-022 digital-mode ADSR, decay shapes d_s in {0 (linear), 1 (sqrt)}
    both declared (the landed linear path is byte-identical to vm.Adsr; the
    sqrt path follows the SXT-026 AdsrWt form). Analog mode refuses."""

    def __init__(self, prm, name):
        # vm.Adsr refuses d_s != 0; this slice declares d_s in {0, 1}, so
        # gate here and hand the super a d_s it accepts
        if int(prm["d_s"]) not in (0, 1):
            raise RuntimeError(
                f"{name}: decay shape {prm['d_s']} not in slice (0 or 1)")
        super().__init__({**prm, "d_s": 0}, name)
        self.d_s = int(prm["d_s"])
        self.s_lvl = 0

    def process_block(self):
        if self.state == self.S_DECAY and self.d_s == 1:
            rate = vm.envelope_rate_linear_nowrap(self.d)
            # d_s == 1: sx = sqrt(phase); l_lo/hi = phase -/+ 2*sx*rate + rate^2
            sx = int(math.floor(math.sqrt(self.phase / float(1 << F_PHASE))
                                * (1 << F_PHASE) + 0.5))
            two_sx_rate = vm.qround(2 * vm.qmul(sx, rate, fa=F_PHASE,
                                                fb=F_PHASE, fq=F_PHASE), 0)
            rr = vm.qround(vm.qmul(rate, rate, fa=F_PHASE, fb=F_PHASE,
                                   fq=F_PHASE), 0)
            l_lo = self.phase - two_sx_rate + rr
            l_hi = self.phase + two_sx_rate + rr
            if (self.s < vm.qint(1e-3) and self.phase < vm.qint(1e-4)) or \
                    (self.s == 0 and self.d < vm.qint(-7.0)):
                l_lo = 0
            if rate > (1 << F_PHASE) and l_lo > self.s:
                l_lo = self.s
            self.phase = limit_q(self.s, l_lo, l_hi)
            self.output = self.phase >> (F_PHASE - FQ)
        else:
            super().process_block()
        self.output = vm.limit_i(self.output, 0, ONE)


class ClassicOsc:
    """ClassicOscillator slice: mono output, drift 0 (asserted), FM off,
    per-unison-voice impulse machines over the shared oscbuffer/dcbuffer."""

    def __init__(self, inp, key):
        self.inp = inp
        n = inp.unison
        if not 1 <= n <= MAX_UNISON:
            # Explicit rejection, never a silent clamp (engine clamps; the
            # product contract rejects beyond-cap unison at load, as frozen
            # for SXT-026).
            raise RuntimeError(
                "unison %d outside 1..MAX_UNISON(%d): explicitly rejected"
                % (n, MAX_UNISON))
        self.n_unison = n
        if inp.absolute_detune:
            raise RuntimeError("absolute detune mode not in SXT-033 slice")
        if inp.drift != 0.0:
            raise RuntimeError("scene drift not 0 (determinism gate)")

        # SurgeVoice noteShiftFromPitchParam: kt=1 -> the note, kt=0 ->
        # keytrack root 60; plus 12*(scene octave + osc octave) and the osc
        # pitch param (ct_pitch_semi7bp extended: 12*val semitones)
        base = float(key) if inp.keytrack else 60.0
        self.pitch = int(min(148.0, base + 12.0 * (inp.scene_octave + inp.octave)
                             + 12.0 * inp.pitch_param))
        if not 24 <= self.pitch <= 148:
            raise RuntimeError("declared slice osc pitch range is [24, 148]")

        # prepare_unison (UnisonSetup, float32 op order at quantization time)
        att_inv = _f32(math.sqrt(1.0 * n))
        self.out_attenuation = vm.qint(_f32(1.0 / att_inv))
        udet_f = _f32(12.0 * inp.udet) if inp.extend_detune else _f32(inp.udet)
        self.voice_detune = []          # float32 semitones, per voice
        self.t_u = []                   # Q10.21 impulse rate, per voice
        self.t_sync_u = []              # Q10.21 sync restart period, per voice
        self.t_inv_u = []               # Q10.21 1/t (exact; engine rcp —
                                        # declared deviation), per voice
        # convolute clamps the sync semitones: sync = min(l_sync, 156-pitch)
        sync_raw = min(max(0.0, inp.sync), float(SYNC_CEILING - self.pitch))
        for v in range(n):
            if n == 1:
                detune_f = 0.0
            else:
                bias = 2.0 / (n - 1)
                inner = _f32(_f32(bias * float(v)) + -1.0)
                detune_f = _f32(udet_f * inner)
            self.voice_detune.append(detune_f)
            t = vm.ntpi_tuningctr(vm.qint(_f32(detune_f + sync_raw)))
            self.t_u.append(t)
            self.t_sync_u.append(vm.qmul(vm.ntpi_tuningctr(vm.qint(detune_f)),
                                         vm.qint(2.0)))
            self.t_inv_u.append(vm.qdiv(ONE, t))

        # lag targets (constant params in this slice): instantize
        self.t_shape = limit_q(vm.qint(inp.shape), vm.qint(-1.0), ONE)
        self.t_pw = limit_q(vm.qint(inp.pw), vm.qint(0.001), vm.qint(0.999))
        self.t_pw2 = limit_q(vm.qint(inp.pw2), vm.qint(0.001), vm.qint(0.999))
        self.t_sub = limit_q(vm.qint(inp.submix), 0, ONE)
        self.t_sync = vm.qint(max(0.0, inp.sync))
        self.l_shape, self.l_pw, self.l_pw2 = self.t_shape, self.t_pw, self.t_pw2
        self.l_sub, self.l_sync = self.t_sub, self.t_sync

        # per-voice state (retrigger forced on by the declared fixture
        # configuration: oscstate/syncstate start at 0 — deterministic)
        self.voices = [{
            "oscstate": 0, "syncstate": 0, "state": 0, "last_level": 0,
            "pwidth": limit_q(self.l_pw, vm.qint(0.001), vm.qint(0.999)),
            "pwidth2": 0, "dc_uni": 0,
        } for _ in range(n)]

        # integrator hpf (keytracked): update_lagvals<true> instantized
        self.hpf_prev = self._hpf_target()
        self.hpf_target = self.hpf_prev

        # character filter (patch character; Warm/Neutral declared, Bright
        # refuses) — inside the osc instance, as in ClassicOscillator::init
        filt = (1.0 - 2.0 * 5000.0 / 48000.0) ** 2
        if inp.character == 0:
            self.char_b0, self.char_b1, self.char_a1 = \
                vm.qint(1.0 - filt), 0, vm.qint(filt)
        elif inp.character == 1:
            self.char_b0, self.char_b1, self.char_a1 = ONE, 0, 0
        else:
            raise RuntimeError("character Bright not in SXT-033 slice")

        # shared mono buffers
        self.ob = [0] * (OB_LENGTH + FIRIPOL_N)
        self.dcb = [0] * (OB_LENGTH + FIRIPOL_N)
        self.bufpos = 0
        self.dc = 0
        self.osc_out = 0
        self.osc_out2 = 0

    # ------------------------------------------------------------- helpers
    def _hpf_target(self):
        """update_lagvals: pp = ntp_tuningctr(pitch + l_sync);
        invt = 4*min(1, 8.175798915*pp*sr_inv); hpf2 = min(integ, 0.995^invt)."""
        pp = vm.ntp_tuningctr(vm.qint(float(self.pitch)) + self.l_sync)
        invt = vm.qmul(vm.qint(4.0), min(ONE, vm.qmul(
            vm.qint(8.175798915), vm.qmul(pp, vm.qint(1.0 / 96000.0)))))
        return min(INTEGRATOR_HPF, vm.qint(HPF_CYCLE_LOSS ** (invt / float(ONE))))

    def _convolute(self, u, pmi):
        v = self.voices[u]
        sync_on = self.l_sync > 0
        if sync_on and v["syncstate"] < v["oscstate"]:
            # hard-sync restart branch: rewind the cycle to syncstate
            # (ipos from syncstate; the branch-local t advances syncstate
            # only — the impulse RATE stays the outer t in both branches)
            ipos = (v["syncstate"] * pmi) >> (FQ + PMI_F - 24)
            ipos &= 0xFFFFFFFF
            v["state"] = 0
            v["last_level"] = vm.sat(v["last_level"]
                                     + vm.qmul(v["dc_uni"],
                                               v["oscstate"] - v["syncstate"]))
            v["oscstate"] = v["syncstate"]
            v["syncstate"] = max(0, v["syncstate"] + self.t_sync_u[u])
        else:
            ipos = (v["oscstate"] * pmi) >> (FQ + PMI_F - 24)
            ipos &= 0xFFFFFFFF
        t = self.t_u[u]
        delay = (ipos >> 24) & 0x3F
        m = ((ipos >> 16) & 0xFF) * (FIRIPOL_N << 1)
        lipol = ipos & 0xFFFF

        wf = self.l_shape
        sub = self.l_sub
        om1 = ONE - sub
        if v["state"] == 0:
            v["pwidth"] = limit_q(self.l_pw, vm.qint(0.001), vm.qint(0.999))
            v["pwidth2"] = vm.qmul(vm.qint(2.0), self.l_pw2)
        pw = v["pwidth"]
        pw2 = v["pwidth2"]
        st = v["state"]
        if st == 0:
            # tg = ((1+wf)*0.5 + (1-pw)*(-wf))*(1-sub) + 0.5*sub*(2-pw2)
            tg = vm.qmul(vm.qround(ONE + wf, 1) + vm.qmul(ONE - pw, -wf), om1)
            tg += vm.qmul(vm.qround(sub, 1), vm.qint(2.0) - pw2)
            g = tg - v["last_level"]
            v["last_level"] = tg
            v["last_level"] -= vm.qmul(vm.qmul(pw, pw2),
                                       vm.qmul(ONE + wf, om1))
        elif st == 1:
            g = vm.qmul(wf, om1) - sub
            v["last_level"] += g
            v["last_level"] -= vm.qmul(vm.qmul(ONE - pw, vm.qint(2.0) - pw2),
                                       vm.qmul(ONE + wf, om1))
        elif st == 2:
            g = om1
            v["last_level"] += g
            v["last_level"] -= vm.qmul(vm.qmul(pw, vm.qint(2.0) - pw2),
                                       vm.qmul(ONE + wf, om1))
        else:
            g = vm.qmul(wf, om1) + sub
            v["last_level"] += g
            v["last_level"] -= vm.qmul(vm.qmul(ONE - pw, pw2),
                                       vm.qmul(ONE + wf, om1))
        g = vm.qmul(g, self.out_attenuation)

        base = self.bufpos + delay
        m12 = m >> 1
        for k in range(FIRIPOL_N):
            term = vm.SINC_MAIN[m12 + k] + vm.qmul(lipol, vm.SINC_DERIV[m12 + k],
                                                   fb=16)
            self.ob[base + k] = vm.sat(self.ob[base + k] + vm.qmul(term, g))

        olddc = v["dc_uni"]
        v["dc_uni"] = vm.qmul(vm.qmul(self.t_inv_u[u], ONE + wf), om1)
        self.dcb[base + FIROFFSET] = vm.sat(
            self.dcb[base + FIROFFSET] + (v["dc_uni"] - olddc))

        if st & 1:
            rate = vm.qmul(t, ONE - pw)
        else:
            rate = vm.qmul(t, pw)
        if (st + 1) & 2:
            rate = vm.qmul(rate, vm.qint(2.0) - pw2)
        else:
            rate = vm.qmul(rate, pw2)
        v["oscstate"] = max(0, v["oscstate"] + rate)
        v["state"] = (st + 1) & 3

    # -------------------------------------------------------------- block
    def process_block(self, pitchmult):
        """One 64-OS-sample block at the given Q10.21 pitchmult."""
        pmi = self.ctrl_pmi
        a_cov = vm.qmul(BLOCK_SIZE_OS << FQ, pitchmult)
        # lag steps (update_lagvals<false> + process, one step per block)
        self.l_shape += vm.qmul(LAG_RATE, self.t_shape - self.l_shape)
        self.l_pw += vm.qmul(LAG_RATE, self.t_pw - self.l_pw)
        self.l_pw2 += vm.qmul(LAG_RATE, self.t_pw2 - self.l_pw2)
        self.l_sub += vm.qmul(LAG_RATE, self.t_sub - self.l_sub)
        self.l_sync += vm.qmul(LAG_RATE, self.t_sync - self.l_sync)
        hpf_new = self._hpf_target()
        hpf_start = self.hpf_prev
        hpf_d = hpf_new - hpf_start
        self.hpf_prev = hpf_new
        self.hpf_start = hpf_start
        self.hpf_d = hpf_d
        sync_on = self.l_sync > 0

        for u in range(self.n_unison):
            v = self.voices[u]
            while (sync_on and v["syncstate"] < a_cov) or v["oscstate"] < a_cov:
                self._convolute(u, pmi)
            v["oscstate"] -= a_cov
            if sync_on:
                v["syncstate"] -= a_cov

        oa = vm.qmul(self.out_attenuation, pitchmult)
        mdc = self.dc
        bp = self.bufpos
        out = []
        for k in range(BLOCK_SIZE_OS):
            hpf = hpf_start + vm.qround(hpf_d * (k + 1), 6)
            acc = vm.qmul(self.osc_out, hpf)
            mdc += self.dcb[bp + k]
            obv = self.ob[bp + k] - vm.qmul(mdc, oa)
            last_osc_out = self.osc_out
            self.osc_out = vm.sat(acc + obv)
            self.osc_out2 = (vm.qmul(self.osc_out2, self.char_a1)
                             + vm.qmul(self.osc_out, self.char_b0)
                             + vm.qmul(last_osc_out, self.char_b1))
            out.append(self.osc_out2)
        self.dc = mdc
        for k in range(BLOCK_SIZE_OS):
            self.ob[bp + k] = 0
            self.dcb[bp + k] = 0
        self.bufpos = (bp + BLOCK_SIZE_OS) & (OB_LENGTH - 1)
        if self.bufpos == 0:
            for k in range(FIRIPOL_N):
                self.ob[k] = self.ob[OB_LENGTH + k]
                self.ob[OB_LENGTH + k] = 0
                self.dcb[k] = self.dcb[OB_LENGTH + k]
                self.dcb[OB_LENGTH + k] = 0
        return out


class Slice:
    """Voice slice: Classic osc -> o-level -> pfg -> AEG gain ramp -> scene
    out (accumulated into the shared scene bus). The scene decimator
    (halfband), master gain and output clips live in the runner (one shared
    chain per scene, as in the engine). All other mixer paths (other oscs,
    noise, ring modulators) and both filter units are muted/off by the
    declared fixture configuration (see fixture_config.py) — test
    configurations, never adapted presets, never coverage."""

    def __init__(self, inp, key, velocity):
        self.inp = inp
        self.key = key
        self.gate = True
        self.osc = ClassicOsc(inp, key)
        pmi_d = 96000.0 * (1.0 / 8.175798915) * (2.0 ** (-self.osc.pitch / 12.0))
        pmi_d = max(1.0, pmi_d)
        self.osc.ctrl_pmi = vm.sat(int(math.floor(pmi_d * (1 << PMI_F) + 0.5)))
        self.pitchmult = vm.qdiv(1 << PMI_F, self.osc.ctrl_pmi,
                                 fa=PMI_F, fb=PMI_F)
        self.aeg = AdsrClassic(inp.adsr, "aeg")
        self.aeg.attack_from(0)
        self.lvl = vm.amp_to_linear(vm.qint(inp.o_level))
        self.pfg = vm.db_to_linear(vm.qint(inp.level_pfg))
        vca_db_eff = inp.vca_db + inp.vca_vs * (1.0 - velocity / 127.0)
        self.vca = vm.db_to_linear(vm.qint(vca_db_eff))
        self.outl = vm.amp_to_linear(vm.qint(inp.scene_volume)) >> 1
        self.gain = vm.qmul(self.vca, self.aeg.output)
        self.prev_gain = self.gain
        self.keep_playing = True

    def process_block(self, b, scene):
        """One 32-sample block: envelope step, osc block, gain-ramped
        accumulation into `scene` (64 OS samples). Returns (osc_out, keep)."""
        self.aeg.process_block()
        if self.aeg.is_idle():
            self.keep_playing = False
        osout = self.osc.process_block(self.pitchmult)
        target = vm.qmul(self.vca, self.aeg.output)
        d_gain = target - self.prev_gain
        gain_start = self.prev_gain
        self.prev_gain = target
        for k in range(BLOCK_SIZE_OS):
            x = vm.qmul(vm.qmul(osout[k], self.lvl), self.pfg)
            scene[k] += vm.qmul(vm.qmul(x, gain_start + vm.qround(d_gain * (k + 1), 6)),
                                self.outl)
        # control-plane words for the RTL record (post-block state)
        self.ctrl_a_cov = vm.qmul(BLOCK_SIZE_OS << FQ, self.pitchmult)
        self.ctrl_hpf_start = self.osc.hpf_start
        self.ctrl_hpf_d = self.osc.hpf_d
        self.ctrl_gain_start = gain_start
        self.ctrl_d_gain = d_gain
        return osout, self.keep_playing


class Inputs:
    """Frozen model inputs (inputs/<name>.json, extracted by
    extract_inputs.py from the pinned engine — never guessed)."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.preset_path = d["preset_path"]
        self.preset_census_blob_sha1 = d["preset_census_blob_sha1"]
        self.slot = int(d["slot"])
        self.octave = int(d["octave"])
        self.scene_octave = int(d.get("scene_octave", 0))
        self.keytrack = bool(d.get("keytrack", True))
        self.pitch_param = d.get("pitch_param", 0.0)
        self.shape = d["shape"]
        self.pw = d["pw"]
        self.pw2 = d["pw2"]
        self.submix = d["submix"]
        self.sync = d["sync"]
        self.udet = d["unison_detune"]
        self.extend_detune = bool(d.get("extend_detune", False))
        self.absolute_detune = bool(d.get("absolute_detune", False))
        self.unison = int(d["unison"])
        self.retrigger = bool(d["retrigger"])
        self.character = int(d["character"])
        self.drift = d.get("drift", 0.0)
        self.o_level = d["o_level"]
        self.level_pfg = d.get("level_pfg", 0.0)
        self.scene_volume = d["scene_volume"]
        self.vca_db = d["vca_db"]
        self.vca_vs = d.get("vca_velsense", 0.0)
        self.master_db = d["master_db"]
        self.adsr = d["adsr"]
        self.declared_overrides = d.get("declared_overrides", [])
