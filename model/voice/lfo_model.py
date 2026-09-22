#!/usr/bin/env python3
"""SXT-032 frozen fixed-point LFO model for scene voice LFOs 1..6
(modsource ids 17..22 of the pinned engine).

This module is the FROZEN reference for the SXT-032 LFO control-plane RTL
(`rtl/voice/tb_lfo.sv`). RTL-vs-model agreement must be EXACT (integer
equality at every declared block-boundary checkpoint; enforced by
tools/compare_lfo_rtl_model.py). Model-vs-pinned-engine agreement is a
separate claim governed by error budgets, which are NOT frozen — SXT-032
reports achieved numbers only, no freeze claims.

Word lengths and operation order are normative: `model/voice/README.md`
(SXT-032 section). The LFO is a CONTROL-RATE modulator: one output value
per 32-sample engine block (the engine evaluates it inside
SurgeVoice::calc_ctrldata, once per block, before the envelopes step).

Structure is cited from the pinned engine (read, not copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  src/common/dsp/modulators/LFOModulationSource.cpp/.h
      phase accumulator + wrap, lfoeg_* envelope state machine, per-shape
      waveform evaluation, unipolar fold, magnitude scaling, attack/release
  src/common/dsp/modulators/LFOModulationSource.h
      startPhaseClamped (basic shapes clamp to [0, 1 - 1/360])
  src/common/dsp/SurgeVoice.cpp calc_ctrldata / applyModulationToLocalcopy
      processing order (LFO1 always; LFOs 2..6 when routed), route
      application localcopy[dst] += depth * get_output(0)
  src/common/SurgeSynthesizer.cpp prepareModsourceDoProcess
      modsource_doprocess recomputed per block from the live routings
      (empirically verified on the pinned oracle: a routed LFO2 processes
      with its own definition)
  libs/sst/sst-waveshapers WaveshaperTables.h
      wst_sine table = sin((i - 512) * pi / 512), 1024 entries, float32
  src/common/SurgeStorage.cpp lookup_waveshape_warp
      x *= 256; x += 512; e = (int)x; a = x - e;
      (1-a)*T[e & 0x3ff] + a*T[(e+1) & 0x3ff]
  src/common/SurgeStorage.cpp envelope_rate_linear_nowrap
      per-block rate increments (same table family as the SXT-022 envelopes)

Frozen waveform set (deterministic members of lt_*):
  lt_sine(0) deform == 0, lt_tri(1) deform == 0, lt_square(2) any deform,
  lt_ramp(3) deform == 0.  Everything else is REFUSED by the fail-closed
  extractor: lt_noise/lt_snh (engine RNG: nondeterministic), lt_stepseq
  (grid state outside normalized-schema rev 1.0.0), lt_mseg/lt_formula
  (contents not exposed by surgepy), lt_envelope, and deform != 0 on the
  type_3 shapes (needs runtime sin(); recorded boundary, never guessed).

Arithmetic discipline (FROZEN, mirrors model/voice/voice_model.py):
  * every value is a Python int in two's-complement Q-format;
  * phase and envelope-phase words are Q2.29; waveform values Q4.27;
    routed modulation outputs Q10.21;
  * products are exact then rounded back round-half-up and saturated;
  * no floating point at run time; the only double-precision evaluations
    happen once at quantization time (rate table, table construction).
"""

import math

FQ = 21                     # routed output word Q10.21
F_PHASE = 29                # phase / envelope-phase Q2.29
F_WAVE = 27                 # waveform value Q4.27
PH_ONE = 1 << F_PHASE       # 1.0 in Q2.29
W_ONE = 1 << F_WAVE         # 1.0 in Q4.27
QMAX = (1 << 31) - 1
QMIN = -(1 << 31)

# lfoeg states (LFOModulationSource.h LFOEG_state)
EG_OFF, EG_DELAY, EG_ATTACK, EG_HOLD, EG_DECAY, EG_RELEASE, EG_MSEGREL, EG_STUCK \
    = range(8)

# lt_* shape ids (SurgeStorage.h)
LT_SINE, LT_TRI, LT_SQUARE, LT_RAMP, LT_NOISE, LT_SNH, LT_ENVELOPE, \
    LT_STEPSEQ, LT_MSEG, LT_FORMULA = range(10)

# lm_* trigger modes (SurgeStorage.h)
LM_FREERUN, LM_KEYTRIGGER, LM_RANDOM = range(3)

# Engine parameter bounds used by the pinned structure (ct_envtime family is
# [-8, 8]; magnitude ct_lfoamplitude [0, 2]; deform ct_lfodeform [-1, 1]).
ENVTIME_MIN = -8.0
ENVTIME_MAX = 8.0

PHASE_CLAMP_MAX = 1.0 - 1.0 / 360.0      # startPhaseClamped, basic shapes

# Negative-control switch (tools/lfo_negative_controls.py): when True,
# attack() derives the phase from global elapsed time (start_phase + t*rate)
# instead of restarting per voice — the free-running/keytrigger confusion.
# In poly mode every voice owns a fresh LFO instance, so the observable
# keytrigger behavior is the per-voice phase restart; the mutant replaces it
# with a t=0-anchored free-running phase. Never set in committed model runs.
MUTANT_FREE_RUNNING = False
BLOCK_CLOCK = 0                 # runner sets this to the block index per block


def sat(x):
    return QMIN if x < QMIN else (QMAX if x > QMAX else x)


def qmul(a, b, fa, fb, fq):
    """Exact product, round-half-up back to fq, saturated."""
    s = fa + fb - fq
    if s > 0:
        return sat((a * b + (1 << (s - 1))) >> s)
    return sat(a * b << (-s))


def qint_phase(x):
    """Quantize a double level/rate to Q2.29 (quantization time only)."""
    return sat(int(math.floor(x * PH_ONE + 0.5)))


def qint_wave(x):
    return sat(int(math.floor(x * W_ONE + 0.5)))


def qint_21(x):
    return sat(int(math.floor(x * (1 << FQ) + 0.5)))


def _f32(x):
    import struct
    return struct.unpack("f", struct.pack("f", x))[0]


def build_ws_sine_table():
    """wst_sine table from the pinned construction formula (WaveshaperTables.h).

    t[i] = sin((i - 512) * pi / 512), i in [0, 1024), stored as float32 by
    the engine; quantized once to Q10.21 here. Provenance: construction
    formula cited; no table bytes are copied from any repository.
    """
    return [sat(int(math.floor(_f32(math.sin((i - 512) * math.pi / 512.0))
                               * (1 << FQ) + 0.5))) for i in range(1024)]


WS_SINE = build_ws_sine_table()


def envelope_rate_linear_nowrap_q(x_q21):
    """storage::envelope_rate_linear_nowrap evaluated in double at the pinned
    formula, quantized once to Q2.29 (per-block increment).

    Body (pinned): x *= 16; x += 256; e = int(x) in [0, 510]; lerp of
    1 / (96000 * 2^((e - 256) / 16) / 64).
    """
    from voice_model import envelope_rate_linear_nowrap
    return envelope_rate_linear_nowrap(x_q21)


def warp_sine_lookup(x_q27):
    """lookup_waveshape_warp(wst_sine, x) with x in Q4.27; returns Q10.21.

    t = x*256 + 512; e = int(t) (trunc toward zero; t > 0 here);
    a = t - e in Q10.21 fraction; lerp with two round-half-up multiplies.
    Q-format: x in [(-2, 2] -> x*256 has word x_q27 << 2 in Q10.21
    (x_q27 << 8 >> 6 == x_q27 << 2, exact); 512 enters as 512 << FQ.
    """
    t_q21 = sat((x_q27 << 8) >> 6) + (512 << FQ)
    e = t_q21 >> FQ                       # t in (0, 1024] -> e in [0, 1024]
    a = t_q21 - (e << FQ)                 # Q10.21 fraction
    i0 = e & 0x3FF
    i1 = (e + 1) & 0x3FF
    t0 = WS_SINE[i0]
    t1 = WS_SINE[i1]
    return sat(qmul((1 << FQ) - a, t0, FQ, FQ, FQ)
               + qmul(a, t1, FQ, FQ, FQ))


class LfoParams:
    """Frozen control-plane words for one LFO instance (block-constant).

    All fields are quantized once here (quantization time, double precision
    against the pinned formulas); the runtime model and the RTL consume only
    these integer words. Rate TEMPOSYNC and rate DEACTIVATED flags are not
    observable through the surgepy binding; the frozen model implements the
    non-temposync / non-deactivated paths (at the pinned 120 BPM the two
    rate formulas agree up to the declared table-lerp deviation; the gap is
    recorded in the SXT-032 evidence record, like the SXT-011 send-level gap).
    """

    def __init__(self, d):
        shape = int(d["shape"])
        if shape not in (LT_SINE, LT_TRI, LT_SQUARE, LT_RAMP):
            raise RuntimeError(f"LFO shape {shape} not in the SXT-032 frozen "
                               "waveform set (noise/snh/envelope/stepseq/"
                               "mseg/formula are fail-closed)")
        trig = int(d["trigmode"])
        if trig == LM_RANDOM:
            raise RuntimeError("LFO trigmode lm_random uses engine RNG: "
                               "fail-closed")
        deform = float(d["deform"])
        if shape in (LT_SINE, LT_TRI, LT_RAMP) and deform != 0.0:
            raise RuntimeError(
                f"LFO shape {shape} with deform {deform} not in the frozen "
                "slice (type_3 bend needs runtime sin; recorded boundary)")
        self.shape = shape
        self.trigmode = trig
        self.unipolar = bool(int(d["unipolar"]))
        self.rate_q21 = qint_21(float(d["rate"]))
        self.start_phase_q29 = qint_phase(
            min(max(float(d["start_phase"]), 0.0), PHASE_CLAMP_MAX))
        self.magnitude_q27 = qint_wave(min(max(float(d["magnitude"]), -3.0), 3.0))
        self.deform_q27 = qint_wave(deform)
        self.env = {
            "delay": qint_21(float(d["delay"])),
            "attack": qint_21(float(d["attack"])),
            "hold": qint_21(float(d["hold"])),
            "decay": qint_21(float(d["decay"])),
            "sustain": qint_phase(float(d["sustain"])),
            "release": qint_21(float(d["release"])),
        }
        for k in ("delay", "attack", "hold", "decay", "release"):
            v = float(d[k])
            if not (ENVTIME_MIN <= v <= ENVTIME_MAX):
                raise RuntimeError(f"LFO EG {k} {v} outside pinned [-8, 8]")
        # per-stage rates (control-plane words, block-constant here)
        from voice_model import envelope_rate_linear_nowrap
        self.rate_word = envelope_rate_linear_nowrap(self.rate_q21)
        self.eg_rate = {k: envelope_rate_linear_nowrap(self.env[k])
                        for k in ("delay", "attack", "hold", "decay", "release")}

    def release_active(self):
        """LFOModulationSource::release gate: release.val.f < val_max.f (8)."""
        return self.env["release"] < qint_21(ENVTIME_MAX)


class Lfo:
    """One LFOModulationSource-equivalent instance (fixed point).

    Per-instance state is preserved even when the arithmetic is shared:
    every voice carries six of these (scene voice LFOs 1..6), never merged.
    """

    def __init__(self, prm, index):
        self.p = prm
        self.index = index                  # 0..5 -> ms_lfo1 + index
        self.phase = 0                      # Q2.29 fraction in [0, 2^29)
        self.unwrapped = 0                  # integer cycles (asserted unused)
        self.phase_initialized = False
        self.env_state = EG_STUCK           # assign(): un-attacked -> stuck
        self.env_val = 0                    # Q2.29
        self.env_phase = 0                  # Q2.29
        self.env_releasestart = 0
        self.ever_attacked = False
        self.output = 0                     # Q10.21 routed output (get_output(0))

    # ------------------------------------------------------------- attack
    def _init_phase_from_start(self):
        self.phase = self.p.start_phase_q29
        self.phase_initialized = True
        if self.p.shape == LT_TRI and not self.p.unipolar:
            # initPhaseFromStartPhase: lt_tri && rate.deactivated && !unipolar
            # adds 0.25 here; the deactivated flag is not observable via
            # surgepy and the frozen model implements the active-rate path.
            pass
        self.phase %= PH_ONE
        self.unwrapped = 0

    def attack(self):
        """LFOModulationSource::attackFrom(0)."""
        if not self.phase_initialized:
            self._init_phase_from_start()
        self.env_state = EG_DELAY
        self.env_val = 0
        self.env_phase = 0
        first = not self.ever_attacked
        self.ever_attacked = True
        if self.p.env["delay"] == qint_21(ENVTIME_MIN):
            self.env_state = EG_ATTACK
            if self.p.env["attack"] == qint_21(ENVTIME_MIN):
                self.env_state = EG_HOLD
                self.env_val = PH_ONE
                if self.p.env["hold"] == qint_21(ENVTIME_MIN):
                    self.env_state = EG_DECAY
        if self.p.trigmode == LM_KEYTRIGGER:
            if MUTANT_FREE_RUNNING:
                # CONTROL ONLY: free-running confusion — phase anchored at
                # t=0 instead of the per-voice restart
                self.phase = (self.p.start_phase_q29
                              + BLOCK_CLOCK * self.p.rate_word) % PH_ONE
                self.unwrapped = 0
            else:
                self.phase = self.p.start_phase_q29 % PH_ONE
                self.unwrapped = 0
        elif self.p.trigmode == LM_FREERUN:
            # storage->songpos == 0 in the offline oracle renders (no
            # transport): totalPhase = startPhase + 0. Fail-closed on any
            # future harness that advances songpos.
            self.phase = self.p.start_phase_q29 % PH_ONE
            self.unwrapped = 0
        else:
            raise RuntimeError("lm_random refused at extraction")
        if not MUTANT_FREE_RUNNING:
            # the shape switch in attackFrom runs for ALL trigger modes
            if self.p.shape == LT_TRI and not self.p.unipolar:
                self.phase = (self.phase + (PH_ONE >> 2)) % PH_ONE
            elif self.p.shape == LT_SINE and self.p.unipolar:
                self.phase = (self.phase + 3 * (PH_ONE >> 2)) % PH_ONE
        return first

    def release(self):
        if self.p.release_active():
            self.env_releasestart = self.env_val
            self.env_phase = 0
            self.env_state = EG_RELEASE

    # ------------------------------------------------------- process_block
    def process_block(self):
        p = self.p
        if not self.phase_initialized:
            self._init_phase_from_start()

        # phase += frate * ratemult (ratemult == 1 outside stepseq)
        self.phase += p.rate_word
        if p.rate_word == 0 and self.phase == 0 and p.shape == LT_STEPSEQ:
            self.phase = qint_phase(0.001)      # not in the frozen shapes
        if self.phase >= PH_ONE:
            if self.phase >= (PH_ONE << 1):
                # engine modf branch; unreachable with frate < 1 (declared)
                self.unwrapped += self.phase >> F_PHASE
                self.phase &= PH_ONE - 1
            else:
                self.phase -= PH_ONE
                self.unwrapped += 1
            self._on_phase_wrap()

        # LFO EG state machine
        if self.env_state not in (EG_STUCK, EG_MSEGREL):
            rate = 0
            if self.env_state == EG_DELAY:
                rate = p.eg_rate["delay"]
            elif self.env_state == EG_ATTACK:
                rate = p.eg_rate["attack"]
            elif self.env_state == EG_HOLD:
                rate = p.eg_rate["hold"]
            elif self.env_state == EG_DECAY:
                rate = p.eg_rate["decay"]
            elif self.env_state == EG_RELEASE:
                rate = p.eg_rate["release"]
            self.env_phase += rate
            if self.env_phase > PH_ONE:
                if self.env_state == EG_DELAY:
                    self.env_state = EG_ATTACK
                    self.env_phase = 0
                elif self.env_state == EG_ATTACK:
                    self.env_state = EG_HOLD
                    self.env_phase = 0
                elif self.env_state == EG_HOLD:
                    self.env_state = EG_DECAY
                    self.env_phase = 0
                elif self.env_state == EG_DECAY:
                    self.env_state = EG_STUCK
                    self.env_phase = 0
                    self.env_val = p.env["sustain"]
                elif self.env_state == EG_RELEASE:
                    self.env_state = EG_STUCK
                    self.env_phase = 0
                    self.env_val = 0
            if self.env_state == EG_DELAY:
                self.env_val = 0
            elif self.env_state == EG_ATTACK:
                self.env_val = self.env_phase
            elif self.env_state == EG_HOLD:
                self.env_val = PH_ONE
            elif self.env_state == EG_DECAY:
                t = qmul(self.env_phase, p.env["sustain"], F_PHASE, F_PHASE,
                         F_PHASE)
                self.env_val = (PH_ONE - self.env_phase) + t
            elif self.env_state == EG_RELEASE:
                self.env_val = qmul(PH_ONE - self.env_phase,
                                    self.env_releasestart,
                                    F_PHASE, F_PHASE, F_PHASE)

        # waveform evaluation (control rate), Q4.27
        io2 = self._waveform()

        # unipolar fold (non-stepseq)
        if p.unipolar:
            io2 = (W_ONE + io2) >> 1

        # output_multi[0] = (useenvval + useenv0) * magnf * io2
        # envelopeStart == 0 (attackFrom(0), FROM_ZERO): useenv0 == 0
        out27 = qmul(io2, self.env_val, F_WAVE, F_PHASE, F_WAVE)
        out27 = qmul(out27, p.magnitude_q27, F_WAVE, F_WAVE, F_WAVE)
        # Q4.27 -> Q10.21, round-half-up
        self.output = sat((out27 + (1 << (F_WAVE - FQ - 1)))
                          >> (F_WAVE - FQ))
        return self.output

    def _on_phase_wrap(self):
        # lt_snh / lt_stepseq / lt_noise wrap updates are outside the frozen
        # waveform set; nothing to do for sine/tri/square/ramp.
        pass

    def _waveform(self):
        p = self.p
        ph = self.phase
        s = p.shape
        if s == LT_SINE:
            # deform type_3, deform == 0: bend3 identity, divisor 1, offset 0
            # x = 2 - 4*phase; in Q4.27 words: 2^28 - phase (exact)
            x_q27 = (W_ONE << 1) - ph
            # warp table lives in Q10.21; io2 domain is Q4.27 (exact shift)
            return warp_sine_lookup(x_q27) << (F_WAVE - FQ)
        if s == LT_TRI:
            # -1 + 4*min(phase, 1-phase); deform type_3, deform == 0
            y = PH_ONE - ph if ph > (PH_ONE >> 1) else ph
            return -W_ONE + (y >> 2)
        if s == LT_SQUARE:
            thresh = (W_ONE >> 1) + (p.deform_q27 >> 1)
            return -W_ONE if (ph >> (F_PHASE - F_WAVE)) > thresh else W_ONE
        if s == LT_RAMP:
            y = W_ONE - (ph >> (F_PHASE - F_WAVE - 1))          # 1 - 2*phase
            return y
        raise RuntimeError(f"shape {s} refused (frozen set is sine/tri/"
                           "square/ramp)")
