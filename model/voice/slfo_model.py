#!/usr/bin/env python3
"""SXT-041 frozen fixed-point SCENE LFO (SLFO) model — modsource ids 23..28
(ms_slfo1..ms_slfo6) of the pinned engine.

This module is the FROZEN reference for the SXT-041 SLFO control-plane RTL
(`rtl/voice/tb_slfo.sv`). RTL-vs-model agreement must be EXACT (integer
equality at every declared block-boundary checkpoint; enforced by
tools/compare_slfo_rtl_model.py). Model-vs-pinned-engine agreement is a
SEPARATE claim governed by error budgets which are NOT frozen — SXT-041
reports achieved numbers only and establishes no fidelity claim.

What this leaf adds over SXT-032 (voice LFOs ms_lfo1..6)
--------------------------------------------------------
The *per-instance arithmetic* is the SXT-032 frozen core, reused verbatim
(`model/voice/lfo_model.py`: phase accumulator, lfoeg_* state machine,
waveform evaluation, unipolar fold, magnitude scaling). `LFOModulationSource`
is literally the same engine class — the pinned engine constructs scene LFOs
from the same class and only calls `setIsVoice(false)` on them
(`SurgeSynthesizer.cpp` ctor), and `isVoice` is read *only* by the Formula
modulator (`LFOModulationSource.cpp` `formulastate.isVoice`), which is
fail-closed in this leaf's frozen waveform set. So the arithmetic is NOT
re-frozen here; duplicating it would create a second, driftable copy.

What IS frozen here is the SCENE SCHEDULING, which differs from the voice
LFOs on four axes that are all observable:

  S1 ONE instance set per scene, shared by every voice.
     `SurgeVoice.cpp` lines 325..330 copy the *scene's* modsource POINTERS
     into the voice (`modsources[ms_slfo1+i] = oscene->modsources[...]`), so
     six instances exist per scene — not six per voice. Per-instance state is
     still never merged (AGENTS.md): the six instances keep six independent
     state sets even though the arithmetic is shared.

  S2 ATTACK is gated on `getNonReleasedVoices(scene) == 0`.
     `SurgeSynthesizer::playVoice` attacks all `n_lfos_scene` instances only
     when no GATED voice exists in the scene (`getNonReleasedVoices` counts
     `v->state.gate`), evaluated BEFORE the new voice is created. A legato
     note-on therefore does NOT restart a scene LFO, where it always
     restarts a voice LFO (every voice owns a fresh one).

  S3 RELEASE is gated on the same predicate, evaluated AFTER the released
     voice's gate is cleared (`SurgeVoice::release` sets `state.gate =
     false`; `SurgeSynthesizer::releaseNote` then tests the count).

  S4 The scene route application is ONE BLOCK BEHIND the instance.
     In `SurgeSynthesizer::processControl` the `modulation_scene` apply loop
     (`scenedata[dst].f += depth * modsources[src]->get_output(...)`) runs
     BEFORE the `n_lfos_scene` `process_block()` loop. So block N's scene
     routes consume the output computed at the end of block N-1. (The
     modwheel, by contrast, is `process_block()`-ed earlier in the same
     function, before the apply loop, so SXT-022's modwheel route is NOT
     delayed — the asymmetry is real and is covered by a negative control.)

  S5 All six instances process EVERY block while the scene plays, with no
     `modsource_doprocess` gate (the `n_lfos_scene` loop is unconditional),
     including blocks with no voices at all. Voice LFOs 2..6 process only
     when routed, and only while a voice exists.

Pinned source (read and cited, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71
  src/common/ModulationSource.h
      modsources enum (ms_slfo1 == 23 .. ms_slfo6 == 28), isScenelevel(),
      isVoiceModulator() (false exactly for ms_slfo1..6)
  src/common/SurgeSynthesizer.cpp
      ctor: scene.modsources[ms_slfo1+l] = new LFOModulationSource(), bound
            to scene.lfo[n_lfos_voice + l], setIsVoice(false)
      playVoice: getNonReleasedVoices(scene) == 0 -> attack() all six
      releaseNote: getNonReleasedVoices(scene) == 0 -> release() all six
      processControl: copy_scenedata, modwheel/controller process_block,
            modulation_scene apply loop, THEN the n_lfos_scene process loop
      setModulation/getModulationList: isScenelevel(ms_slfo*) -> the route
            lands in scene[].modulation_scene (not modulation_voice)
  src/common/dsp/SurgeVoice.cpp
      ctor lines 325..330: scene SLFO pointers copied into the voice
  src/common/dsp/modulators/LFOModulationSource.cpp/.h
      the shared instance arithmetic (frozen by SXT-032)

Arithmetic discipline: inherited unchanged from SXT-032 (every value a
Python int in two's-complement Q-format; phase/EG-phase Q2.29, waveform
Q4.27, routed output Q10.21; products exact then round-half-up and
saturated; no floating point at run time).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lfo_model as lm  # noqa: E402

# Pinned modsource ids (ModulationSource.h). Recorded so the leaf's identity
# is checkable without the engine.
MS_SLFO1 = 23
N_SCENE_LFOS = 6
# scene.lfo[] index of ms_slfo1 (n_lfos_voice == 6)
SCENE_LFO_BASE = 6

# Frozen destination classes for this leaf (same two as SXT-032, reached here
# through modulation_scene rather than modulation_voice).
DEST_CUTOFF = "cutoff"
DEST_RESO = "reso"
FROZEN_DESTS = (DEST_CUTOFF, DEST_RESO)

# ---------------------------------------------------------------------------
# Negative-control switches. NEVER set in a committed model run; each one is
# a deliberately WRONG scene-scheduling semantic that a control must show
# demonstrably failing. See tools/slfo_negative_controls.py.
# ---------------------------------------------------------------------------
# S2/S3 confusion: attack/release on EVERY note-on/note-off (voice-LFO
# semantics applied to a scene LFO).
MUTANT_PER_NOTE_RETRIGGER = False
# S4 confusion: scene routes read the CURRENT block's output instead of the
# previous block's (the one-block scene-route delay dropped).
MUTANT_ZERO_DELAY_ROUTE = False
# S1 confusion: all six instances collapsed onto ONE shared state set
# (AGENTS.md shared-instead-of-per-instance control).
MUTANT_SHARED_INSTANCE = False
# S5 confusion: instances advance only while a gated voice exists (voice-LFO
# residency applied to a scene LFO).
MUTANT_GATED_PROCESS = False


class SlfoParams(lm.LfoParams):
    """Frozen control-plane words for ONE scene-LFO instance.

    Identical quantization to `lfo_model.LfoParams` (same engine class, same
    parameter storage layout: `scene.lfo[n_lfos_voice + i]`); subclassed only
    so the scene instances carry their own type for traces and gates.
    """


class SceneLfoBank:
    """The six `ms_slfo1..6` instances of ONE scene, with their scheduling.

    State of record: `self.inst[i]` (six independent `lfo_model.Lfo`
    instances; never merged) plus `self.route_out[i]`, the ONE-BLOCK-DELAYED
    output latch the scene routes actually consume (S4).

    Usage per engine block (mirrors processControl):
        bank.note_on(gated_voices)        # for each note-on at this boundary,
        bank.note_off(gated_voices)       #   with the engine's own predicate
        sums = bank.block_pass(routes, gated_voices)
        ... voices consume sums ...       # voices run AFTER processControl
        bank.checkpoint()                 # declared block-boundary record
    """

    def __init__(self, params_list):
        if len(params_list) != N_SCENE_LFOS:
            raise RuntimeError(
                f"scene LFO bank needs exactly {N_SCENE_LFOS} instances, "
                f"got {len(params_list)}")
        self.inst = [lm.Lfo(p, i) for i, p in enumerate(params_list)]
        # the words the scene routes consume this block (output of block N-1)
        self.route_out = [0] * N_SCENE_LFOS
        # bookkeeping for the evidence record / cost accounting
        self.attacks = 0
        self.releases = 0
        self.processed_blocks = 0

    # ------------------------------------------------------------- events
    def note_on(self, gated_voices_before):
        """`SurgeSynthesizer::playVoice`: attack all six iff no gated voice.

        `gated_voices_before` is `getNonReleasedVoices(scene)` evaluated
        BEFORE the new voice is created, exactly as the engine does.
        """
        if MUTANT_PER_NOTE_RETRIGGER or gated_voices_before == 0:
            for inst in self.inst:
                inst.attack()
            self.attacks += 1
            return True
        return False

    def note_off(self, gated_voices_after):
        """`SurgeSynthesizer::releaseNote`: release all six iff no gated voice.

        `gated_voices_after` is the count AFTER the released voice's gate has
        been cleared (`SurgeVoice::release` clears it first).
        """
        if MUTANT_PER_NOTE_RETRIGGER or gated_voices_after == 0:
            for inst in self.inst:
                inst.release()
            self.releases += 1
            return True
        return False

    # ----------------------------------------------------- one scene block
    def block_pass(self, routes, gated_voices=1):
        """One engine block at scene scope, in the FROZEN order.

        FROZEN (engine) order, from `processControl`:
            1. apply the `modulation_scene` routes from the PREVIOUS block's
               instance outputs (the `route_out` latch),
            2. THEN advance the six instances.

        `MUTANT_ZERO_DELAY_ROUTE` flips those two steps, which is exactly the
        "scene route is not one block late" control: the route then consumes
        the current block's output. Returns [cutoff_sum, reso_sum] in Q10.21.
        """
        if MUTANT_ZERO_DELAY_ROUTE:
            self._advance(gated_voices)
            return self._route_sums(routes)
        sums = self._route_sums(routes)
        self._advance(gated_voices)
        return sums

    def _route_sums(self, routes):
        """Scene-route sums from the `route_out` latch (Q10.21 per class).

        routes: [(instance_index, dest, depth_q21)].
        """
        cut = 0
        reso = 0
        for idx, dest, depth in routes:
            if dest not in FROZEN_DESTS:
                raise RuntimeError(
                    f"destination {dest!r} outside the SXT-041 frozen "
                    f"destination classes {FROZEN_DESTS}")
            term = lm.qmul(depth, self.route_out[idx], lm.FQ, lm.FQ, lm.FQ)
            if dest == DEST_CUTOFF:
                cut = lm.sat(cut + term)
            else:
                reso = lm.sat(reso + term)
        return [cut, reso]

    # ------------------------------------------------------------- process
    def _advance(self, gated_voices=1):
        """Advance all six instances (S5: unconditional while the scene plays).

        Then re-latch `route_out` from the fresh outputs, so the NEXT block's
        route application consumes this block's result (S4).
        """
        if MUTANT_GATED_PROCESS and gated_voices == 0:
            # CONTROL ONLY: voice-LFO residency applied to a scene LFO
            return list(self.route_out)
        if MUTANT_SHARED_INSTANCE:
            # CONTROL ONLY: one shared state set. Instance 0 is advanced and
            # every instance reports its words (per-instance state merged).
            out = self.inst[0].process_block()
            for inst in self.inst[1:]:
                inst.phase = self.inst[0].phase
                inst.env_state = self.inst[0].env_state
                inst.env_phase = self.inst[0].env_phase
                inst.env_val = self.inst[0].env_val
                inst.output = out
        else:
            for inst in self.inst:
                inst.process_block()
        self.processed_blocks += 1
        self.route_out = [i.output for i in self.inst]
        return list(self.route_out)

    # ---------------------------------------------------------------- trace
    def checkpoint(self):
        """Declared per-block checkpoint record (one entry per instance)."""
        return [{
            "index": inst.index,
            "phase": inst.phase,
            "env_state": inst.env_state,
            "env_phase": inst.env_phase,
            "env_val": inst.env_val,
            "output": inst.output,
        } for inst in self.inst]

    def state_bits(self):
        """Per-instance state word widths (SXT-015 accounting input)."""
        return state_bits()


def state_bits():
    """Per-instance scene-LFO state word widths (SXT-015 accounting input).

    Mirrors the SXT-032 accounting exactly (the state IS the same engine
    class), plus this leaf's own `route_out` latch, which is what makes the
    scene route one block late. Reported, never claimed as a technology
    result.
    """
    return {
        "phase": 29,
        "env_phase": 29,
        "env_val": 30,
        "env_releasestart": 30,
        "env_state": 3,
        "output": 22,
        "flags_phase_init_ever_attacked": 2,
        "route_out_latch": 22,
    }


def reset_mutants():
    """Clear every negative-control switch (used by the test suite)."""
    global MUTANT_PER_NOTE_RETRIGGER, MUTANT_ZERO_DELAY_ROUTE
    global MUTANT_SHARED_INSTANCE, MUTANT_GATED_PROCESS
    MUTANT_PER_NOTE_RETRIGGER = False
    MUTANT_ZERO_DELAY_ROUTE = False
    MUTANT_SHARED_INSTANCE = False
    MUTANT_GATED_PROCESS = False
