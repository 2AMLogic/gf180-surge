#!/usr/bin/env python3
"""SXT-043 frozen model: playmode submode pm_mono_st_fp.

"Mono (Single Trigger & Fingered Portamento)" -- `play_mode` id 4 in the
pinned engine (`src/common/SurgeStorage.h`, enum `play_mode`
pm_poly..pm_latch).  This module freezes, in exact integer arithmetic:

  1. the submode's **voice-allocation / articulation state machine** --
     which note-on legatos an existing gated voice instead of creating one
     (single trigger), which note-off legatos the mono voice down to a
     still-held key instead of releasing it, and which note-on reclaims a
     releasing voice (`monoVoiceEnvelopeMode`);
  2. the submode's **fingered-portamento anchoring** -- the pinned
     `SurgeVoice::resetPortamentoFrom` special case that makes
     pm_mono_st_fp (and only pm_mono_st_fp) anchor a *new or reclaimed*
     voice's glide at its own pitch, so portamento is reachable only
     through a legato (fingered) transition;
  3. the **portamento ramp arithmetic** -- `portaphase` accumulation, the
     three glide curves, constant-rate mode, glissando quantization and
     the mid-glide re-anchoring performed by `SurgeVoice::legato`.

Pinned sources read and cited, never copied (GPL-3.0-or-later, external):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  * `src/common/SurgeStorage.h`          -- enum play_mode, MonoVoicePriorityMode,
                                            MonoVoiceEnvelopeMode, porta_curve
  * `src/common/SurgeStorage.cpp`        -- table_glide_log / table_glide_exp
                                            construction, glide_log / glide_exp,
                                            envelope_rate_linear
  * `src/common/SurgeSynthesizer.cpp`    -- playNote / playVoice (pm_mono_st,
                                            pm_mono_st_fp branch), releaseNote,
                                            releaseNotePostHoldCheck,
                                            reclaimVoiceFor
  * `src/common/dsp/SurgeVoice.cpp/.h`   -- legato, update_portamento,
                                            resetPortamentoFrom,
                                            retriggerPortaIfKeyChanged,
                                            retriggerOSCWithIndependentAttacks,
                                            release / uber_release,
                                            getAEGFEGLevel / restartAEGFEGAttack,
                                            resetVelocity, getPitch,
                                            noteShiftFromPitchParam, Gain line
  * `src/common/dsp/modulators/ADSRModulationSource.h`
                                         -- attackFrom, release, uber_release,
                                            s_uberrelease rate (-6.5)
  * `src/common/ModulationSource.h`      -- ControllerModulationSource
                                            processSmoothing (SLOW_EXP)

CLAIM SCOPE.  This module advances exactly two claims and no others: the RTL
(`rtl/voice/tb_pm_mono_st_fp.sv`) matches this model EXACTLY at the declared
checkpoints, and this model reproduces the pinned engine's render of the
DECLARED fixture configuration within [PROPOSED] budgets.  It makes no
preset-support claim, no musical-quality claim, and no synthesis / timing /
hardware claim.

WORD LENGTHS (FROZEN for this leaf; see README.md for the rationale):

| quantity                                   | format  |
|--------------------------------------------|---------|
| key / pitch / pkey / portasrc_key / priorpkey, glide phase | Q10.21 |
| portaphase, envelope phase, sustain        | Q2.29   |
| oscillator omega / phase                   | Q3.28   |
| samples, gains, coefficients               | Q10.21  |

Arithmetic rules are the frozen SXT-022 rules (`model/voice/README.md`):
integer two's-complement words, exact 64-bit products rounded round-half-up
to the target format and saturated to signed 32 bits, divisions only at
block rate.
"""

import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "sine"))
sys.path.insert(0, REPO)

import voice_model as vm                                       # noqa: E402
import sine_model as sm                                        # noqa: E402
from refusal import Refuse                                     # noqa: E402

FQ = vm.FQ                       # 21
ONE = vm.ONE                     # 1.0 in Q10.21
F_PHASE = vm.F_PHASE             # 29
PHASE_ONE = 1 << F_PHASE         # 1.0 in Q2.29
BLOCK_SIZE = vm.BLOCK_SIZE       # 32
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS  # 64
SR = vm.SR                       # 48000

PLAY_MODE_ID = 4                 # pm_mono_st_fp (SurgeStorage.h enum play_mode)
PLAY_MODE_NAME = "Mono (Single Trigger & Fingered Portamento)"

# MonoVoicePriorityMode (SurgeStorage.h)
NOTE_ON_LATEST_RETRIGGER_HIGHEST = 0
ALWAYS_LATEST = 1
ALWAYS_HIGHEST = 2
ALWAYS_LOWEST = 3

# MonoVoiceEnvelopeMode (SurgeStorage.h)
RESTART_FROM_ZERO = 0
RESTART_FROM_LATEST = 1

# porta_curve (SurgeStorage.h)
PORTA_LOG = -1
PORTA_LIN = 0
PORTA_EXP = 1

# SurgeVoice::update_portamento
PORTA_CLAMP = 4.0
# ADSRModulationSource.h s_uberrelease: envelope_rate_linear_nowrap(-6.5)
UBER_RELEASE_RATE_PARAM = -6.5
# ControllerModulationSource processSmoothing, SLOW_EXP sigma (process_block)
SLOW_EXP_SIGMA = 0.0025


# --------------------------------------------------------------- glide tables
def _tbl_glide_log(i):
    """SurgeStorage.cpp: table_glide_log[i] = log2(1 + i/512*10) / log2(11)."""
    return math.log2(1.0 + (i * (1.0 / 512.0)) * 10.0) / math.log2(1.0 + 10.0)


def _tbl_glide_exp(i):
    """SurgeStorage.cpp: table_glide_exp[511 - i] = 1 - table_glide_log[i]."""
    return 1.0 - _tbl_glide_log(511 - i)


def _glide_lerp(tbl, x):
    """storage::glide_log / glide_exp body (x in [0, 1]).

    Pinned: `x *= 511; e = (int)x; a = x - e;` then lerp over
    `tbl[e & 0x1ff]` and `tbl[(e + 1) & 0x1ff]`.  Declared deviation (the
    frozen SXT-022 table rule): the engine lerps a float32 table, the model
    evaluates the pinned construction FORMULA in double and quantizes once.
    """
    x = x * 511.0
    e = int(x)
    a = x - float(e)
    lo = tbl(e & 0x1ff)
    hi = tbl((e + 1) & 0x1ff)
    return (1 - a) * lo + a * hi


def glide_rom(curve):
    """512-word Q10.21 ROM for one curve, streamed to the RTL.

    Word i is the curve's table entry; the RTL performs the SAME index/lerp
    arithmetic as `glide_phase` over these words, so the ROM is the only
    transcendental content that crosses the model/RTL boundary.
    """
    if curve == PORTA_LOG:
        return [vm.qint(_tbl_glide_log(i)) for i in range(512)]
    if curve == PORTA_EXP:
        return [vm.qint(_tbl_glide_exp(i)) for i in range(512)]
    if curve == PORTA_LIN:
        return [0] * 512               # unused: the linear curve reads no table
    raise Refuse(f"porta_curve {curve!r} outside the pinned enum {{-1, 0, 1}}")


def glide_phase(curve, portaphase_q29):
    """The pinned curve mapping, Q2.29 portaphase -> Q10.21 phase factor."""
    if curve == PORTA_LIN:
        # `phase = state.portaphase` -- a pure format change, no table
        return vm.qround(portaphase_q29, F_PHASE - FQ)
    x = portaphase_q29 / float(PHASE_ONE)
    if curve == PORTA_LOG:
        return vm.qint(_glide_lerp(_tbl_glide_log, x))
    if curve == PORTA_EXP:
        return vm.qint(_glide_lerp(_tbl_glide_exp, x))
    raise Refuse(f"porta_curve {curve!r} outside the pinned enum {{-1, 0, 1}}")


def floor_half(x_q):
    """floor(x + 0.5) in Q10.21 (C `floor`, i.e. toward -inf)."""
    return ((x_q + (ONE >> 1)) // ONE) * ONE


def porta_rate_q29(porta_val, temposync_ratio_q=ONE):
    """envelope_rate_linear(min(porta, 4)) * temposyncratio, Q2.29/block.

    Declared equivalence (asserted): over the engine-declared portamento
    range [-8, 2] the wrapping `envelope_rate_linear` and the clamping
    `envelope_rate_linear_nowrap` index the same table cells
    (x*16 + 256 in [128, 288] is inside [0, 510]), so the frozen SXT-022
    `_nowrap` helper is used verbatim.
    """
    v = min(porta_val, PORTA_CLAMP)
    if not -8.0 <= v <= 2.0:
        raise Refuse(f"portamento {porta_val!r} outside engine-declared [-8, 2]")
    r = vm.envelope_rate_linear_nowrap(vm.qint(v))
    if temposync_ratio_q != ONE:
        r = vm.qmul(r, temposync_ratio_q, fa=F_PHASE, fb=FQ, fq=F_PHASE)
    return r


# ----------------------------------------------------------------- envelope
class AegMono(vm.Adsr):
    """Frozen SXT-022 digital ADSR + the three entries this submode needs.

    Added (pinned ADSRModulationSource.h), each absent from the frozen
    SXT-022 slice because poly playmode never reaches it:
      * `attack_from(start)` for start > 0 -- the `RESTART_FROM_LATEST`
        reclaim path (`restartAEGFEGAttack(getAEGFEGLevel())`), including
        the pinned per-attack-shape phase seeding;
      * `uber_release()` and the `s_uberrelease` branch, whose phase
        decrement is the FIXED `envelope_rate_linear_nowrap(-6.5)` rather
        than the release-rate parameter.
    Everything else is the landed frozen arithmetic, unmodified.
    """

    def __init__(self, prm, name):
        super().__init__(prm, name)
        self.uber_rate = vm.envelope_rate_linear_nowrap(vm.qint(
            UBER_RELEASE_RATE_PARAM))

    def attack_from(self, start):
        """attackFrom(start) -- pinned form, any start in [0, 1]."""
        self.phase = 0
        self.output = 0
        self.idlecount = 0
        self.scalestage = ONE
        if start > 0:
            self.output = start
            if self.a_s == 0:
                self.phase = vm.qround(vm.qmul(start, start), FQ - F_PHASE)
            elif self.a_s == 1:
                self.phase = vm.qround(start, FQ - F_PHASE)
            elif self.a_s == 2:
                self.phase = vm.qint_phase(math.sqrt(start / float(ONE)))
            else:
                raise Refuse(f"{self.name}: attack shape {self.a_s} not in slice")
        self.state = self.S_ATTACK
        if (self.a - self.A_MIN) < vm.qint(0.01):
            # instant attack: the pinned ctor/attackFrom tail, which makes
            # `start` INERT (output and phase are forced to 1 either way)
            self.state = self.S_DECAY
            self.output = ONE
            self.phase = PHASE_ONE

    def uber_release(self):
        self.scalestage = self.output
        self.phase = PHASE_ONE
        self.state = self.S_UBER

    def process_block(self):
        if self.state != self.S_UBER:
            super().process_block()
            return
        self.phase -= self.uber_rate
        out = self.phase >> (F_PHASE - FQ)
        for _ in range(self.r_s):
            out = vm.qmul(out, self.phase >> (F_PHASE - FQ))
        self.output = vm.qmul(out, self.scalestage)
        if self.phase < 0:
            self.state = self.S_IDLE
            self.output = 0
        self.output = vm.limit_i(self.output, 0, ONE)


class VelocitySmoother:
    """ControllerModulationSource, SLOW_EXP -- the ms_velocity word.

    Pinned `processSmoothing(SLOW_EXP, 0.0025)`:
      b = |target - value|; if b < sigma: value = target
      else a = clamp(0.9 * 44100 / samplerate * b, 0, 1);
           value = (1 - a) * value + a * target

    This is per-instance state that the mono reclaim path WRITES
    (`resetVelocity`), so it is one of the submode's live state elements:
    a reclaimed voice's VCA gain glides from the prior note's velocity.
    """

    SIGMA = vm.qint(SLOW_EXP_SIGMA)

    def __init__(self, fvel_q):
        self.value = fvel_q          # init(0, fvel): immediate, no ramp
        self.target = fvel_q
        self.coeff = vm.qint(0.9 * 44100.0 / float(SR))

    def set_target(self, fvel_q):
        self.target = fvel_q

    def process_block(self):
        b = abs(self.target - self.value)
        if b < self.SIGMA:
            self.value = self.target
            return
        a = vm.limit_i(vm.qmul(self.coeff, b), 0, ONE)
        self.value = vm.sat(vm.qmul(ONE - a, self.value)
                            + vm.qmul(a, self.target))


# ---------------------------------------------------------------- portamento
class Portamento:
    """Per-voice portamento state and the pinned ramp arithmetic.

    Per-instance by construction: every voice owns its own
    (portasrc_key, pkey, priorpkey, portaphase, porta_doretrigger).  The
    arithmetic is shared across the mono submodes; the STATE never is.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.portasrc_key = 0
        self.pkey = 0
        self.priorpkey = 0
        self.portaphase = 0
        self.porta_doretrigger = False

    # ---- SurgeVoice::resetPortamentoFrom -------------------------------
    def reset_from(self, last_key_q, own_pitch_q):
        """resetPortamentoFrom(key, channel), pm_mono_st_fp branch.

        THE submode-defining line (`SurgeVoice.cpp`):

            if ((scene->polymode.val.i == pm_mono_st_fp) ||
                (scene->portamento.val.f == scene->portamento.val_min.f))
                state.portasrc_key = state.getPitch(storage);
            else
                ... glide from the prior key ...

        pm_mono_st_fp therefore anchors EVERY new/reclaimed voice at its own
        pitch: a fresh note-on never glides, however recently another key
        sounded.  `last_key_q` is accepted and deliberately ignored -- it is
        kept in the signature (and recorded in the trace) so the forced-mode
        negative controls can exercise the branch that DOES read it.
        """
        if self.cfg.fingered:
            self.portasrc_key = own_pitch_q
        elif self.cfg.porta_val == self.cfg.porta_val_min:
            self.portasrc_key = own_pitch_q
        else:
            self.portasrc_key = last_key_q
        self.priorpkey = self.portasrc_key
        self.portaphase = 0

    # ---- SurgeVoice::retriggerPortaIfKeyChanged (standard tuning) ------
    def _retrigger_if_key_changed(self):
        f = floor_half(self.pkey)
        if f != self.priorpkey:
            self.priorpkey = f
            self.porta_doretrigger = True

    def _const_rate_factor(self, own_pitch_q):
        """1 / ((1/quantStep) * |getPitch() - portasrc_key| + 0.00001).

        Block-rate division (one per voice per control pass), consistent
        with cost assumption A-ALU-2 (no audio-rate division).  quantStep is
        12 at the pin (standard tuning; microtuning is refused upstream).
        """
        d = abs(own_pitch_q - self.portasrc_key)
        t = vm.sat(vm.qmul(vm.qint(1.0 / 12.0), d) + vm.qint(0.00001))
        return vm.qdiv(ONE, t)

    # ---- SurgeVoice::update_portamento ---------------------------------
    def update(self, own_pitch_q):
        cfg = self.cfg
        crf = self._const_rate_factor(own_pitch_q) if cfg.constrate else ONE
        inc = cfg.rate_q29 if crf == ONE else vm.qmul(
            cfg.rate_q29, crf, fa=F_PHASE, fb=FQ, fq=F_PHASE)
        self.portaphase = vm.sat(self.portaphase + inc)
        if self.portaphase < PHASE_ONE and cfg.porta_val > cfg.porta_val_min:
            phase = glide_phase(cfg.curve, self.portaphase)
            self.pkey = vm.sat(vm.qmul(ONE - phase, self.portasrc_key)
                               + vm.qmul(phase, own_pitch_q))
            if cfg.gliss:
                self.pkey = floor_half(self.pkey)
            self.porta_doretrigger = False
            if cfg.porta_retrigger:
                self._retrigger_if_key_changed()
        else:
            self.pkey = own_pitch_q
        # state.pkey += noteExpressions[PITCH]; PITCH expression is 0 at the
        # pin for MIDI fixtures (declared, gated by the extractor)
        return self.pkey

    # ---- SurgeVoice::legato --------------------------------------------
    def legato(self, own_pitch_q):
        """legato(key, velocity, detune) portamento half, run BEFORE the key
        changes (the pinned order: the re-anchor reads the OLD pitch)."""
        cfg = self.cfg
        if self.portaphase > PHASE_ONE:
            self.portasrc_key = own_pitch_q
        else:
            phase = glide_phase(cfg.curve, self.portaphase)
            self.portasrc_key = vm.sat(
                vm.qmul(ONE - phase, self.portasrc_key)
                + vm.qmul(phase, own_pitch_q))
            if cfg.gliss:
                # pinned: legato quantizes pkey (not portasrc_key) here
                self.pkey = floor_half(self.pkey)
            self.porta_doretrigger = False
            if cfg.porta_retrigger:
                self._retrigger_if_key_changed()
        self.portaphase = 0

    def state_words(self):
        return [self.portaphase, self.portasrc_key, self.pkey,
                self.priorpkey, 1 if self.porta_doretrigger else 0]


class PortamentoConfig:
    """Fixture-constant portamento parameterization (engine-read)."""

    def __init__(self, porta_val, curve, gliss, constrate, porta_retrigger,
                 fingered, porta_val_min=-8.0, temposync_ratio_q=ONE):
        self.porta_val = porta_val
        self.porta_val_min = porta_val_min
        self.curve = int(curve)
        self.gliss = bool(gliss)
        self.constrate = bool(constrate)
        self.porta_retrigger = bool(porta_retrigger)
        self.fingered = bool(fingered)
        self.rate_q29 = porta_rate_q29(porta_val, temposync_ratio_q)
        self.glide_rom = glide_rom(self.curve)


# --------------------------------------------------------------------- voice
class MonoVoice:
    """One scene voice under the declared SXT-043 fixture configuration.

    Audio path (DECLARED fixture configuration -- see fixture_config.py):
    one Sine oscillator slot (shape 0, legacy FM path, unison 1, retrigger
    on, lowcut/highcut off) -> o-level -> pfg -> VCA gain ramp -> scene bus.
    Both filter units Off, waveshaper Off, scene lowcut off, all FX Off,
    other mixer paths muted, fbc pinned to fc_serial1, scene mode Single.
    The oscillator and envelope arithmetic is the LANDED frozen SXT-033 /
    SXT-040 code imported unchanged; this leaf adds only the articulation
    layer above it.
    """

    KEYTRACK_ROOT_Q = vm.qint(60.0)
    RECIP_12_Q = vm.qint(1.0 / 12.0)

    def __init__(self, inp, key, velocity, porta_cfg, last_key_q, slot=0):
        self.inp = inp
        self.porta_cfg = porta_cfg
        self.key = int(key)
        self.velocity = int(velocity)
        self.slot = int(slot)
        self.gate = True
        self.uberrelease = False
        self.keep_playing = True
        self.voice_order = 0
        self.legato_count = 0
        self.reclaim_count = 0
        # SXT-042 finding F-042-1: the engine initialises ms_keytrack to ZERO
        # in the voice constructor and only installs (state.pitch - root)/12
        # at the END of a control pass -- the declared 1-control-pass lag.
        # Under portamento state.pitch MOVES, so unlike every landed leaf
        # this word is genuinely time-varying here.
        self.kt_word = 0
        self.vca_routes = list(getattr(inp, "vca_gain_routes", ()))

        self.vel = VelocitySmoother(vm.qint(velocity / 127.0))
        self.aeg = AegMono(inp.adsr, "aeg")
        self.aeg.attack_from(0)

        self.porta = Portamento(porta_cfg)
        self.porta.reset_from(last_key_q, self.own_pitch_q())
        self.porta.pkey = self.own_pitch_q()

        # SineOsc owns the oscillator's per-instance state.  It is created
        # ONCE per voice and is NOT reset by a legato or a reclaim: the
        # pinned `retriggerOSCWithIndependentAttacks` re-inits only
        # ot_string / ot_twist, so a Sine slot keeps its quadrature state
        # across a mono articulation.  (Negative control: an
        # osc-reset-on-reclaim mutant must fail the reference budget.)
        self.osc = sm.SineOsc(inp, key)
        self._apply_cut_deactivation(self.osc)
        self.lvl = vm.amp_to_linear(vm.qint(inp.o_level))
        self.pfg = vm.db_to_linear(vm.qint(inp.level_pfg))
        pan_f = max(-1.0, min(1.0, inp.pan))
        mono_law = vm.qint(1.0 - 0.25 * pan_f * pan_f)
        self.outl = vm.qmul(vm.amp_to_linear(vm.qint(inp.scene_volume)) >> 1,
                            mono_law)
        self._apply_vca_routes()
        self.prev_gain = self._gain_target()

    IDENTITY_BIQUAD = (ONE, 0, 0, 0, 0)

    def _apply_cut_deactivation(self, osc):
        """Bypass the applyFilter biquads the pinned engine does not run.

        `SineOscillator::applyFilter` is guarded by each cut parameter's
        DEACTIVATED flag.  On these carriers the modeled slot was not a Sine
        oscillator before the declared type override, and the inherited
        deactivation flags leave BOTH cuts off -- measured, not assumed, by
        the extractor's A/B probe (`osc_cut_activation_probe` in the inputs
        sidecar: changing the parameter does not change one output sample).
        The landed SXT-040 `SineOsc` builds both biquads unconditionally
        because its carriers' cuts were live, so the frozen model bypasses
        them HERE rather than by editing that landed file.

        Fail-closed: if the probe says a cut IS live, the landed biquad is
        kept (not silently bypassed).
        """
        probe = getattr(self.inp, "cut_activation", None)
        if probe is None:
            raise Refuse(
                "inputs sidecar carries no osc_cut_activation_probe; the "
                "model will not guess whether the engine runs applyFilter")
        if probe.get("lowcut_deactivated"):
            osc.hp = vm.TDFBiquad(self.IDENTITY_BIQUAD)
        if probe.get("highcut_deactivated"):
            osc.lp = vm.TDFBiquad(self.IDENTITY_BIQUAD)

    # ---- pitch -------------------------------------------------------
    def own_pitch_q(self):
        """state.getPitch(storage) = key + mpeBend + detune, Q10.21.

        MPE off and detune 0 at the pin for these fixtures (gated by the
        extractor), so this is the integer key exactly.
        """
        return vm.qint(float(self.key))

    def osc_pitch(self, pkey_q):
        """noteShiftFromPitchParam(state.pitch + 12*osc_octave, 0).

        state.pitch = pkey + scenepbpitch, scenepbpitch = pitchbend(0) +
        scene pitch param(0) + 12*scene_octave.
        """
        inp = self.inp
        base = pkey_q / float(ONE) if inp.keytrack else 60.0
        pitch_off = inp.pitch_param * (12.0 if inp.pitch_extend else 1.0)
        p = min(148.0, base + 12.0 * (inp.scene_octave + inp.octave) + pitch_off)
        if not 24 <= p <= 148:
            raise Refuse(f"osc pitch {p} outside declared [24, 148]")
        return p

    # ---- modulation --------------------------------------------------
    def _apply_vca_routes(self):
        """applyModulationToLocalcopy for the declared live route vocabulary.

        Only {ms_velocity, ms_keytrack} -> `A VCA Gain` is in the vocabulary
        (SXT-035 / SXT-042 destination class); every other route is
        structurally inert or `modpin_zero`-ed by the fixture configuration,
        and `PmInputs` refuses anything else rather than dropping it.
        The source words are read in the pinned order: the SMOOTHED velocity
        of this pass and the keytrack word installed at the END of the
        previous pass.
        """
        acc = vm.qint(self.inp.vca_db)
        for src, depth in self.vca_routes:
            val = self.vel.value if src == "Velocity" else self.kt_word
            acc = vm.sat(acc + vm.qmul(vm.qint(depth), val))
        self.mod_vca_db = acc

    def _refresh_keytrack(self, pitch_q):
        """ms_keytrack->set_output((state.pitch - keytrack_root) / 12).

        Declared integer form: multiply by the quantized reciprocal of 12
        (streamed to the RTL as `one_twelfth_q21`) instead of dividing in
        double.  Declared deviation from the engine's float32 divide, bounded
        by one Q10.21 LSB on the quotient; it is the model/RTL-shared form,
        so the exactness claim is unaffected and only the model-vs-reference
        budget sees it.
        """
        self.kt_word = vm.qmul(pitch_q - self.KEYTRACK_ROOT_Q, self.RECIP_12_Q)

    # ---- gain --------------------------------------------------------
    def _gain_target(self):
        """db_to_linear(vca + vcavel*(1 - velocitySource)) * ampeg."""
        inp = self.inp
        base = getattr(self, "mod_vca_db", vm.qint(inp.vca_db))
        vca_db = vm.sat(base
                        + vm.qmul(vm.qint(inp.vca_vs), ONE - self.vel.value))
        return vm.qmul(vm.db_to_linear(vca_db), self.aeg.output)

    # ---- articulation entries ----------------------------------------
    def legato(self, key, velocity):
        """SurgeVoice::legato(key, velocity, detune) -- SINGLE TRIGGER.

        No envelope entry is touched: that is what "Single Trigger" means.
        The commented-out velocity update in the pinned source is honored
        (the voice keeps the velocity it was created/reclaimed with).
        """
        self.porta.legato(self.own_pitch_q())
        self.key = int(key)
        self.legato_count += 1

    def reclaim(self, key, velocity, envelope_mode):
        """SurgeSynthesizer::reclaimVoiceFor (mono branch).

        Order is the pinned order: capture the AEG level, re-gate, set the
        key, reset the velocity (SLOW_EXP target, not an immediate jump),
        restart the attack from the captured level, then re-anchor
        portamento from the PRIOR key -- which pm_mono_st_fp overrides to
        the voice's own (new) pitch.
        """
        aeg_start = 0 if envelope_mode == RESTART_FROM_ZERO else self.aeg.output
        prior_key_q = self.own_pitch_q()
        self.gate = True
        self.uberrelease = False
        self.keep_playing = True
        self.key = int(key)
        self.velocity = int(velocity)
        self.vel.set_target(vm.qint(velocity / 127.0))
        self.aeg.attack_from(aeg_start)
        self.porta.reset_from(prior_key_q, self.own_pitch_q())
        self.reclaim_count += 1
        return aeg_start

    def release(self):
        self.aeg.release()
        self.gate = False

    def uber_release(self):
        self.aeg.uber_release()
        self.gate = False
        self.uberrelease = True

    # ---- one control pass + one audio block --------------------------
    def process_block(self, scene):
        """Pinned per-block order inside SurgeVoice::process_block:
        velocitySource.process_block() -> AEG.process_block() ->
        update_portamento() -> state.pitch -> oscillator -> gain ramp."""
        self.vel.process_block()
        self.aeg.process_block()
        if self.aeg.is_idle():
            self.keep_playing = False
        self._apply_vca_routes()
        pkey = self.porta.update(self.own_pitch_q())
        p = self.osc_pitch(pkey)
        # state.pitch = pkey + scenepbpitch; the keytrack modsource refresh
        # happens HERE (after state.pitch, before the next control pass)
        self._refresh_keytrack(
            vm.sat(pkey + vm.qint(12.0 * self.inp.scene_octave)))
        # the legacy quadrature path re-reads omega (set_rate) every block,
        # so a per-block pitch needs no change to the frozen oscillator
        self.osc.pitch = p
        self.osc.omega_u = [sm.pitch_to_omega_q28(p, d)
                            for d in self.osc.voice_detune]
        osout = self.osc.process_block()
        target = self._gain_target()
        gain_start = self.prev_gain
        d_gain = target - gain_start
        self.prev_gain = target
        for k in range(BLOCK_SIZE_OS):
            x = vm.qmul(vm.qmul(osout[k], self.lvl), self.pfg)
            scene[k] += vm.qmul(
                vm.qmul(x, gain_start + vm.qround(d_gain * (k + 1), 6)),
                self.outl)
        self.ctrl_gain_start = gain_start
        self.ctrl_d_gain = d_gain
        self.ctrl_omega = self.osc.omega_u[0]
        return osout, self.keep_playing

    def state_words(self):
        """Declared RTL checkpoint vector for this voice."""
        return [
            1 if self.gate else 0,
            1 if self.uberrelease else 0,
            self.key,
            self.aeg.state, self.aeg.phase, self.aeg.output,
            self.aeg.scalestage,
            self.vel.value, self.vel.target, self.kt_word,
        ] + self.porta.state_words()


STATE_WORD_ORDER = [
    "gate", "uberrelease", "key",
    "aeg_state", "aeg_phase_q29", "aeg_output_q21", "aeg_scalestage_q21",
    "vel_value_q21", "vel_target_q21", "kt_word_q21",
    "portaphase_q29", "portasrc_key_q21", "pkey_q21", "priorpkey_q21",
    "porta_doretrigger",
]
N_STATE_WORDS = len(STATE_WORD_ORDER)


# ---------------------------------------------------------------- allocator
class MonoStFpScene:
    """The pm_mono_st_fp allocation / articulation state machine.

    Declared bounds (fail-closed; `mode` may be forced to another playmode
    ONLY by the negative controls):
      * one MIDI channel, non-MPE, `mapChannelToOctave` off, scene mode
        Single, no keyboard split;
      * no sustain / sostenuto pedal events (`monoPedalMode` unreachable);
      * voice pool 8 (the SXT-021 declared pool), fail-closed on overflow.
    """

    POOL = 8

    def __init__(self, inp, porta_cfg, priority_mode, envelope_mode,
                 mode=PLAY_MODE_ID):
        self.inp = inp
        self.porta_cfg = porta_cfg
        self.priority_mode = int(priority_mode)
        self.envelope_mode = int(envelope_mode)
        self.mode = int(mode)
        self.voices = []                  # engine `voices[scene]` push order
        self.keystate = [0] * 128         # keyState[k].keystate (velocity)
        self.key_is_down = [False] * 128
        self.key_order = [0] * 128        # keyState[k].voiceOrder
        self.voice_counter = 1
        self.last_key_q = vm.qint(0.0)    # storage->last_key[scene]
        self.events = []                  # articulation event log
        # NEGATIVE-CONTROL hooks: never set on a real run.  `shared_portamento`
        # replaces every voice's per-instance portamento state with ONE shared
        # object (the "shared instead of per-instance state" control CLAUDE.md
        # requires); `nc_reset_osc_on_reclaim` re-inits the oscillator on a
        # mono reclaim, which the pinned engine does NOT do for a Sine slot.
        self.shared_portamento = None
        self.nc_reset_osc_on_reclaim = False

    # ---- helpers -----------------------------------------------------
    def _log(self, b, kind, **kw):
        rec = {"b": b, "event": kind}
        rec.update(kw)
        self.events.append(rec)

    def _pick_key(self, exclude=None):
        """The pinned highest / lowest / latest scan over keystate."""
        highest, lowest, latest, lt = -1, 128, -1, 0
        for k in range(127, -1, -1):
            if exclude is not None and k == exclude:
                continue
            if not self.keystate[k]:
                continue
            if k >= highest:
                highest = k
            if k <= lowest:
                lowest = k
            if self.key_order[k] >= lt:
                latest = k
                lt = self.key_order[k]
        pm = self.priority_mode
        if pm in (ALWAYS_HIGHEST, NOTE_ON_LATEST_RETRIGGER_HIGHEST):
            return highest if highest >= 0 else -1
        if pm == ALWAYS_LATEST:
            return latest if latest >= 0 else -1
        if pm == ALWAYS_LOWEST:
            return lowest if lowest <= 127 else -1
        raise Refuse(f"monoVoicePriorityMode {pm} outside the pinned enum")

    def _create(self, b, key, velocity):
        used = {v.slot for v in self.voices}
        free = [i for i in range(self.POOL) if i not in used]
        if not free:
            raise Refuse(
                f"voice pool {self.POOL} exhausted at block {b} -- the "
                "declared SXT-021 pool is fail-closed, never silently stolen")
        v = MonoVoice(self.inp, key, velocity, self.porta_cfg,
                      self.last_key_q, slot=free[0])
        if self.shared_portamento is not None:
            v.porta = self.shared_portamento        # NEGATIVE CONTROL
            v.porta.reset_from(self.last_key_q, v.own_pitch_q())
            v.porta.pkey = v.own_pitch_q()
        v.voice_order = self.voice_counter
        self.voice_counter += 1
        self.key_order[key] = v.voice_order
        self.voices.append(v)
        # SurgeVoice ctor tail: storage->last_key[scene] = key
        self.last_key_q = vm.qint(float(key))
        self._log(b, "create", key=key, velocity=velocity,
                  portasrc=v.porta.portasrc_key)
        return v

    # ---- note on -----------------------------------------------------
    def note_on(self, b, key, velocity):
        """SurgeSynthesizer::playVoice, pm_mono_st / pm_mono_st_fp branch.

        `createVoice` suppression (ALWAYS_HIGHEST / ALWAYS_LOWEST) reads the
        keystate BEFORE this note is recorded, exactly as the pinned order
        does (playNote writes keystate only after playVoice returns).
        """
        create_voice = True
        if self.priority_mode in (ALWAYS_HIGHEST, ALWAYS_LOWEST):
            for k in range(0, 127):
                if self.keystate[k]:
                    if self.priority_mode == ALWAYS_HIGHEST and k > key:
                        create_voice = False
                    if self.priority_mode == ALWAYS_LOWEST and k < key:
                        create_voice = False
        if not create_voice:
            self.key_order[key] = self.voice_counter
            self.voice_counter += 1
            self._log(b, "suppressed", key=key, velocity=velocity)
        else:
            found_one = False
            recycle = None
            for v in self.voices:
                if v.gate:
                    v.legato(key, velocity)
                    # legato tail: storage->last_key[scene] = key
                    self.last_key_q = vm.qint(float(key))
                    found_one = True
                    self._log(b, "legato", key=key, velocity=velocity,
                              portasrc=v.porta.portasrc_key)
                    break
                if not v.uberrelease:
                    if self.envelope_mode != RESTART_FROM_ZERO:
                        recycle = v
                    else:
                        v.uber_release()
                        self._log(b, "uber_release", key=v.key)
            if recycle is not None:
                aeg_start = recycle.reclaim(key, velocity, self.envelope_mode)
                if self.nc_reset_osc_on_reclaim:
                    # NEGATIVE CONTROL: the pinned
                    # retriggerOSCWithIndependentAttacks re-inits only
                    # ot_string / ot_twist, so a Sine slot KEEPS its
                    # quadrature state across a reclaim.  Resetting it here
                    # must FAIL the reference budget.
                    recycle.osc = sm.SineOsc(self.inp, recycle.key)
                    recycle._apply_cut_deactivation(recycle.osc)
                # reclaimVoiceFor bumps the key's voiceOrder but, unlike the
                # SurgeVoice ctor and legato(), does NOT write
                # storage->last_key -- so last_key keeps the previously
                # CREATED key.  (pm_mono_st_fp ignores it anyway; the
                # forced-mode controls do not.)
                self.key_order[key] = self.voice_counter
                self.voice_counter += 1
                self._log(b, "reclaim", key=key, velocity=velocity,
                          aeg_start=aeg_start,
                          portasrc=recycle.porta.portasrc_key)
            elif not found_one:
                self._create(b, key, velocity)
            else:
                # legato slide: no new voice, but this key becomes 'newer'
                self.key_order[key] = self.voice_counter
                self.voice_counter += 1
        # playNote tail (AFTER playVoice): record the key as held
        self.keystate[key] = velocity
        self.key_is_down[key] = True

    # ---- note off ----------------------------------------------------
    def note_off(self, b, key, velocity):
        """releaseNote -> releaseNotePostHoldCheck, pm_mono_st* branch.

        No pedal is held (declared), so the hold buffer is unreachable and
        every note-off reaches the post-hold check directly.
        """
        self.key_is_down[key] = False
        self.keystate[key] = 0           # set BEFORE the voice scan (pinned)
        for v in list(self.voices):
            if v.key != key:
                continue
            k = self._pick_key(exclude=key)
            if k >= 0:
                v.legato(k, velocity)
                self.last_key_q = vm.qint(float(k))
                self._log(b, "legato_down", key=k,
                          portasrc=v.porta.portasrc_key)
            else:
                v.release()
                self._log(b, "release", key=key)

    # ---- one control pass + audio block ------------------------------
    def process_block(self, b, scene):
        alive, per_voice = [], []
        for v in self.voices:
            osout, keep = v.process_block(scene)
            per_voice.append((v, osout))
            if keep:
                alive.append(v)
        self.voices = alive
        return per_voice
