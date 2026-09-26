"""SXT-028l frozen fixed-point model -- routing form: Send buses 3-4
(send3 / send4, the EXTENDED RACK HALF of the four send buses).

THIS IS A PARALLEL-BUS ROUTING FORM, NOT A SERIES ONE. Every routing-form
leaf landed before it (`rf-rf-global2`, `rf-rf-bins12`, `rf-rf-ains34`,
`rf-rf-global34`) models a SERIES insert pair: one bus threaded in place
through two slots. A send bus is different in kind:

    scene A out ──┬─ x send_gain[A][3] ─┐
                  │                     ├─▶ [send bus 3] ─▶ send3 FX ─┐
    scene B out ──┼─ x send_gain[B][3] ─┘                             │
                  │                                                   ├─ x return_gain[3] ─┐
                  ├─ x send_gain[A][4] ─┐                             │                    │
                  └─ x send_gain[B][4] ─┤                             │                    ├─▶ main bus
                                        ├─▶ [send bus 4] ─▶ send4 FX ─┘ x return_gain[4] ──┘      (out)
    main bus in ────────────────────────┴──────────────────────────────────────────────────┘

The two buses are INDEPENDENT signal paths that are mixed back into the main
bus; they are not chained. What this leaf therefore adds over its series
siblings is exactly the send-form wiring: the per-scene send-level
accumulation that FORMS each bus, the per-slot `return_level` scaling that
mixes each bus BACK, the per-bus `sendused` ring flag, and the fact that an
unoccupied or disabled send slot contributes NOTHING to the main bus
(a bypassed INSERT slot passes its audio through; a bypassed SEND slot's bus
is discarded).

Structure authority (CITED, nothing copied; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71):

  src/common/SurgeSynthesizer.cpp  process() -- the send-FX block:
    `fxsendout[s][0..1]` accumulated from each scene's post-insert output
    scaled by that scene's `send_level[s]`, processed in place by the send
    slot's effect through `process_ringout(L, R, sendused[s]) -> bool`, and
    mixed into the main output scaled by the slot's `return_level`, under
    the patch-level `fx_bypass` gate and the per-slot `fx_disable` bitmask
    gate. Instance lifecycle: `loadFx()` (per-slot reload -> a FRESH
    instance), `enqueueFXOff()` (slot off -> instance released),
    `reorderFx()` (slot-content permutation -- the axis this leaf's
    wrong-order negative control attacks).
  src/common/SurgeStorage.h -- `fxslot_positions` (ains1/2 = 0/1,
    bins1/2 = 2/3, send1/2 = 4/5, global1/2 = 6/7, ains3/4 = 8/9,
    bins3/4 = 10/11, **send3 = 12, send4 = 13**, global3/4 = 14/15),
    `n_send_slots` = 4, `fxb_*` bypass enum (fxb_all_fx = 0,
    fxb_no_sends = 1, fxb_scene_fx_only = 2, fxb_no_fx = 3), `n_fx_slots`
    = 16 (`fx_disable` bit width).
  src/common/dsp/effects/SurgeSSTFXAdapter.h + SurgeEffect.h -- instance
    construction/suspend per slot (`fx[v] == nullptr` <=> slot unoccupied;
    modeled here as `SendSlotInstance.occupied`).

  In-repo re-derivation of the slot-index constants (does NOT depend on a
  live oracle): `tools/export_normalized_graphs.py` `FX_ROLES` and EVERY
  record of `corpus/normalized/graphs.jsonl` carry the pinned engine's slot
  order by patch `fx[]` index -- role `send3` at index 12 and `send4` at
  index 13, which is exactly FXSLOT_SEND3/FXSLOT_SEND4 below. Asserted over
  the whole committed corpus by
  `tests/test_sxt028l.py::test_slot_indices_agree_with_the_committed_corpus_role_table`.

  In-repo re-derivation of the SEND-STAGE ROUTING (also oracle-free): the
  committed SXT-011 artifact `corpus/normalized/README.md` ("Mapping notes",
  "FX slot roles and processing order") states the pinned engine's order as
  "A1->A4 and B1->B4 insert chains, scene sum, send buses S1..S4 (each sums
  `scene[0].send_level[k]` and `scene[1].send_level[k]`, applied when
  `fx_bypass==fxb_all_fx`, scaled by the slot's `return_level`), then G1->G4
  on the main output", with per-slot disable `fx_disable & (1<<slot)`. That
  in-repo text (written against the pin, and the authority for
  `corpus/normalized/schema.json`'s own `r` field) is what this leaf's
  routing contract is taken from; it is NOT a fresh read of the pinned
  `process()` source, which no oracle checkout in this environment could
  supply. Recorded as such in reports/SXT-028l/EVIDENCE.md section 0b.

EXTENDED RACK HALF -- what "buses 3-4" means here, and where this leaf's
boundary is. The engine has FOUR send buses: the base half (send1, send2 --
patch fx[] indices 4/5, and the only two whose per-scene levels the .fxp
format stores) and the extended half (send3, send4 -- indices 12/13, added
with the engine's extended FX rack). This leaf models the EXTENDED half
only. Because the two halves are PARALLEL, not chained, the base half is not
"upstream" of this one in the audio sense: the only coupling is that both
halves mix into the SAME main bus. The main bus handed to this leaf
(`main_l`, `main_r`) is therefore whatever the scene sum plus any already-
mixed send1/send2 returns left, and that composition is a declared scope
omission (a sibling `rf-send12`-class leaf's scope; no such leaf exists in
this repository yet -- see "Declared scope omissions").

>>> SXT-011 DATA GAP (this leaf's fixture-freeze blocker, routed to #12).
    The engine has four send buses but a `.fxp` stores only TWO per-scene
    send levels, and the surgepy binding exposes only `send_level[0..1]`
    (`corpus/normalized/README.md` "Send levels 3/4";
    `corpus/normalized/schema.json` `scene.send`). Buses 3/4 therefore run
    at LOADER DEFAULTS for every one of the 3,561 committed corpus presets,
    and NO in-repo artifact carries a per-scene send level for this leaf's
    two buses. Consequence, stated exactly:
      * `send_gain_a` / `send_gain_b` are CONTROL-PLANE STIMULUS in this
        model. They are never derived from a corpus record, and
        `tools/extract_rf_send34_inputs.py` REFUSES to emit a value for
        them (fail-closed: `send_level_stored: null` plus an explicit gap
        record), rather than inventing the loader default.
      * `return_level` IS stored per slot and IS exported by SXT-011
        (`graphs.jsonl` `fx[].rl`), so it is extracted per carrier -- and
        unlike the global/insert forms, this leaf's path really does
        consume it.
      * Freezing reference fixtures for this routing form needs an engine-
        behavior probe of the loader-default send level and an SXT-017
        data-gap policy decision (#12). This leaf does not pre-empt that
        decision; every reference-agreement leg is NOT_RUN here anyway (no
        oracle in this environment).

FORM SCOPE ONLY (issue #64 / SXT-028l). This leaf models the send-bus
formation and return wiring, the per-bus schedule, `fx_bypass` /
`fx_disable` gating (bits 12/13), the per-slot instance lifecycle
(patch-change reload, slot-off, panic/reset), and the per-instance-state
isolation of hosting TWO concurrently-active send-FX instances. It makes
**no** claim about any specific Surge FX algorithm's fidelity -- "algorithm
behavior stays with the per-algorithm leaves" (issue #64 scope note;
AGENTS.md). The per-slot "occupant" exercised here is a **synthetic TDF2
biquad primitive** (structure: the same Direct-Form-II-Transposed recurrence
every landed leaf's biquad stage uses -- Delay/Chorus's per-sample-lag
`Biquad` (model/effects/delay/delay_model.py), Reverb1's
instant-coefficient `biq_stage` (model/effects/reverb1/reverb1_fixed.py),
and the sibling routing leaves' `BiquadInstance` -- with coefficients
supplied as arbitrary control-plane stimulus, NOT derived from any concrete
Surge FX class's parameters). It exists only to give the routing/scheduling
claim a real, per-instance-stateful, tail-bearing arithmetic path to verify
gain placement, state isolation, lifecycle behavior and tail continuation
against. No preset-support or algorithm-fidelity claim follows from it, and
it must never be reported as a substitute for a concrete occupant algorithm
under a support claim (issue #64 negative control: "Generic substitute").

Frozen word formats (this leaf; format-family-consistent with the SXT-023
table in model/effects/README.md and IDENTICAL in family to the four landed
routing leaves so that the five routing forms can be composed and compared
directly):

  bus audio words          Q10.21 signed 32-bit   ("A_FMT"; matches the
                                                   Delay/EQ/Chorus bus scale
                                                   and all four landed
                                                   routing leaves)
  biquad coefficients      Q3.29  signed 32-bit   ("C_FMT"; block-constant,
                                                   NO per-sample lag -- a
                                                   declared scope omission;
                                                   coefficient smoothing is
                                                   algorithm-leaf scope)
  send/return gains        Q1.30  signed 32-bit   ("G_FMT"; NEW in this
                                                   leaf -- the series forms
                                                   have no gain plane. One
                                                   control word per (scene,
                                                   bus) send gain and one
                                                   per bus return gain,
                                                   block-constant; per-block
                                                   level smoothing is a
                                                   declared omission)
  biquad TDF2 accumulator  80-bit signed          (Reverb1 REG_LIM
                                                   precedent: headroom for
                                                   arbitrary/adversarial
                                                   negative-control
                                                   coefficients without a
                                                   stability argument)

Arithmetic rules (FROZEN, self-contained -- mirrors model/effects/qmath.py's
round-half-up / saturating conventions without mutating its shared format
registry; reverb1_fixed.py and the four landed routing leaves' precedent for
a leaf-local kernel): exact products, round-half-up `(p + 2**(s-1)) >> s`,
saturating; no floating point at audio run time.

  * Bus formation (per bus, per channel, per sample):
        wide = sa*send_gain_a + (sb*send_gain_b if scene B is live else 0)
        x    = sat32(rnd_shift(wide, G_FRAC))
    ONE rounding and ONE saturation for the whole scene sum, so the
    scene-accumulation order is IRRELEVANT BY CONSTRUCTION (verified, not
    merely asserted: tests/test_sxt028l.py::
    test_scene_accumulation_is_order_independent_by_construction).
  * Return mix (per channel, per sample):
        wide     = (main_in << G_FRAC) + sum over RUNNING buses of wet*rg
        main_out = sat32(rnd_shift(wide, G_FRAC))
    Again ONE rounding and ONE saturation for the whole mix, so the order in
    which the two returns are summed is IRRELEVANT BY CONSTRUCTION. This is
    a deliberate, declared design choice and it BOUNDS this leaf's
    wrong-order control: for a parallel form the observable permutation axis
    is slot-content-vs-bus-gain (swapping which occupant sits on which bus),
    NOT the summation order. Stated here so the control's strength is never
    overstated; see reports/SXT-028l/EVIDENCE.md section 3.
    With both buses off this reduces to main_out == main_in EXACTLY (an
    exact-multiple round-trip through the shift), asserted by
    tests/test_sxt028l.py::test_main_bus_passes_through_bit_exactly.

Gain mapping (CONTROL RATE ONLY -- never at audio rate). The engine maps a
stored normalized level to a linear gain through `amp_to_linear` cubed:
`gain = level**3` (float32), the semantic already pinned in-repo by the
landed SXT-024 Reverb1 send path (`tools/compare_reverb_model.py`
"send_gain = amp_to_linear(send_level)^3 = send^3", `run_reverb_rtl.py`,
`render_reverb_reference.py`, reports/sxt-024/EVIDENCE.md).
`gain_from_level()` below performs that mapping ONCE, at the control plane,
and quantizes to Q1.30; the audio path consumes only the integer gain word.
The mapping itself is therefore OUTSIDE the RTL-vs-model exactness claim
(both consume the same integer word) and is recorded as a declared contract
in reports/SXT-028l/EVIDENCE.md section 0b.

This file is deliberately SELF-CONTAINED and does not import a sibling
leaf's kernel: `model_revision()` (sha256 of this file) is the
frozen-revision pin consumed by the RTL comparator and the stale-harness
negative control, so a sibling leaf's future edit must never be able to
change this leaf's frozen behavior without changing this leaf's own pin.

Per-instance state: one `SendSlotInstance` holds ONE `BiquadInstance`
(4 accumulator words: reg0/reg1 x {L,R}) plus its own `occupied` flag. The
two configured send slots (`ExtendedSendRack.slot3` = send3, `.slot4` =
send4) are two disjoint `SendSlotInstance` objects -- no accumulator state
is ever shared between them, even though both instances run through the SAME
arithmetic kernel class (`BiquadInstance.process_sample`); this is exactly
the "shared arithmetic, independent per-instance state" contract (AGENTS.md;
issue #64 "State" section). This holds even when the two buses host the SAME
FX class, which the corpus really does exercise (`Exquis MPE/Strings/
Strynth.fxp` carries Nimbus in BOTH send3 and send4).

The per-bus SEND and RETURN GAINS are bus state, not occupant state: a
`loadFx()` on a slot replaces that slot's instance and clears its history,
but does NOT disturb the bus's send/return levels (they are patch routing
parameters, re-applied every control pass). Asserted by
tests/test_sxt028l.py::test_reload_does_not_disturb_the_bus_gain_plane.

Declared control-plane boundary (one control word set per block, applied by
`apply_control()` BEFORE the audio block and independent of `fx_bypass` --
the engine's load/unload path is control-rate and runs whether or not the
audio stage is bypassed): `fx_bypass` (2-bit mode), `fx_disable` (16-bit
mask, engine bit layout; only bits 12/13 are consumed here),
`scene_b_active` (scene B instantiated at all -- false in Single scene mode,
where the engine never voices scene B), and per bus: `occupied`, `reload`
(a patch-change pulse -- `loadFx()`), 5 biquad coefficients (Q3.29) and the
3 gain words (scene-A send, scene-B send, return; Q1.30). The per-bus
`sendused` flags (`send_in3`, `send_in4`) and the scene/main buses are
per-block audio-plane stimulus: computing them is OUT of this leaf's scope
(scene activity is the voice-stage leaves' scope; the scene insert chains
are the `rf-ains*` / `rf-bins*` leaves' scope; the scene sum and the
send1/send2 returns are other leaves' scope).

Instance lifecycle rule (FROZEN; identical in the model and the RTL):
  * `occupied` false                      -> instance released: registers
                                             cleared, that bus contributes
                                             NOTHING to the main bus.
  * `occupied` rising (unoccupied -> occupied), or `reload` pulse while
    occupied                              -> FRESH instance (`loadFx()`):
                                             THAT slot's registers are
                                             cleared and the new
                                             coefficients adopted; the
                                             sibling slot's history, the bus
                                             gain plane and the other bus's
                                             ring memory are untouched.
  * `occupied` steady and no `reload`     -> the coefficients are adopted
                                             WITHOUT clearing state (an
                                             abrupt parameter change; the
                                             engine's own per-parameter
                                             smoothing is algorithm-leaf
                                             scope -- declared omission).
  * `panic_reset()`                       -> both instances cleared and both
                                             buses' ring memory dropped (the
                                             engine's all-notes-off /
                                             suspend path). Occupancy (the
                                             loaded patch) and the gain
                                             plane are NOT changed.

Declared scope omissions (fail-closed):
  * The send1/send2 BASE half of the send rack (a sibling `rf-send12`-class
    leaf's scope; NOT landed in this repository at the time this model was
    frozen -- its returns are simply part of the `main_l`/`main_r` stimulus
    handed in here), the scene insert chains (`rf-rf-ains34` and
    `rf-rf-bins12` landed), and the global chain (`rf-rf-global2` /
    `rf-rf-global34` landed). This leaf models exactly the pinned-source
    `roles: [send3, send4]` scope.
  * The scene sum itself and everything downstream of the send returns.
  * Per-scene `send_level` SMOOTHING and per-slot `return_level` smoothing:
    the engine ramps these per block; this leaf consumes block-constant gain
    words (a declared omission of the same family as the block-constant
    biquad coefficients).
  * Per-sample coefficient smoothing/ramping into the occupant
    (algorithm-leaf scope).
  * Any concrete Surge FX algorithm's own ring-out DECISION: this occupant
    reports ringing exactly while `sendused` is true (see
    `SendSlotInstance.process_ringout`) -- the SAME simplification all four
    landed routing leaves declared. Its arithmetic tail (nonzero output
    after the input goes silent) is real and IS exercised, but a
    tail-bearing occupant's own `process_ringout` return policy is
    algorithm-leaf scope.
  * The exact queue-drain timing of `enqueueFXOff()` inside the engine: this
    leaf's lifecycle applies slot-off at the control-rate pass preceding a
    block, which is a DECLARED contract of the model (and of the RTL, which
    matches it exactly), not a verified read of the engine's queue.
"""

import hashlib
import os

BLOCK = 32

A_FRAC, A_BITS = 21, 32     # Q10.21 bus audio words
C_FRAC, C_BITS = 29, 32     # Q3.29 biquad coefficients (instant)
G_FRAC, G_BITS = 30, 32     # Q1.30 send / return gains (block-constant)
R_BITS = 80                 # TDF2 accumulator width (Reverb1 REG_LIM class)
REG_LIM = 1 << (R_BITS - 1)

FXB_ALL_FX, FXB_NO_SENDS, FXB_SCENE_FX_ONLY, FXB_NO_FX = 0, 1, 2, 3

# SurgeStorage.h fxslot_positions (re-derivable in-repo from
# tools/export_normalized_graphs.py FX_ROLES / corpus/normalized/graphs.jsonl)
FXSLOT_SEND1, FXSLOT_SEND2 = 4, 5
FXSLOT_SEND3, FXSLOT_SEND4 = 12, 13
N_SEND_SLOTS = 4

# The bypass modes in which the SEND stage runs: `fxb_all_fx` ONLY.
# `fxb_no_sends` removes exactly this stage (that is what the enum name
# means), and `fxb_scene_fx_only` / `fxb_no_fx` remove more. This is the
# STRICTEST of the three routing-stage partitions in the engine and the one
# fact that most sharply distinguishes the send form from its siblings:
#   INSERT stage (rf-ains*/rf-bins*): {all_fx, no_sends, scene_fx_only}
#   GLOBAL stage (rf-global*)       : {all_fx, no_sends}
#   SEND   stage (this leaf)        : {all_fx}
# Source: corpus/normalized/README.md (SXT-011, written against the pin) --
# see the module docstring's "In-repo re-derivation of the SEND-STAGE
# ROUTING" note and reports/SXT-028l/EVIDENCE.md section 0b.
SEND_ACTIVE_MODES = (FXB_ALL_FX,)

SEND_RACK_ORDER = ("send1", "send2", "send3", "send4")
BASE_HALF_ROLES = ("send1", "send2")
THIS_LEAF_ROLES = ("send3", "send4")

MODEL_REVISION = None


def model_revision():
    """sha256 of this file (frozen-revision pin for traces/harnesses)."""
    global MODEL_REVISION
    if MODEL_REVISION is None:
        with open(os.path.abspath(__file__), "rb") as f:
            MODEL_REVISION = hashlib.sha256(f.read()).hexdigest()
    return MODEL_REVISION


def sat_s(v, bits):
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def rnd_shift(v, s):
    """Round-half-up arithmetic right shift by s (s >= 0)."""
    if s <= 0:
        return v << (-s)
    return (v + (1 << (s - 1))) >> s


def to_q(x, frac, bits):
    v = int(round(x * (1 << frac)))
    return sat_s(v, bits)


def to_g(x):
    """Quantize a linear gain to the frozen Q1.30 gain word."""
    return to_q(x, G_FRAC, G_BITS)


def gain_from_level(level):
    """CONTROL-RATE mapping from a stored normalized level (send_level or
    return_level) to this leaf's Q1.30 gain word: `gain = level**3`, the
    `amp_to_linear`-cubed semantic already pinned in-repo by the landed
    SXT-024 Reverb1 send path (tools/compare_reverb_model.py,
    tools/run_reverb_rtl.py, reports/sxt-024/EVIDENCE.md).

    NOT part of the audio path and NOT part of the RTL-vs-model exactness
    claim: the RTL consumes the resulting integer word, never a level. A
    DECLARED contract, recorded in reports/SXT-028l/EVIDENCE.md section 0b.
    """
    return to_g(float(level) ** 3)


class BiquadInstance:
    """Per-slot occupant TDF2 biquad: y[n] = b0*x[n] + reg0;
    reg0' = b1*x[n] - a1*y[n] + reg1; reg1' = b2*x[n] - a2*y[n]
    (Direct Form II Transposed -- the structure every landed leaf's biquad
    stage shares). Block-constant (instant) coefficients; NO per-sample lag
    is modeled (declared scope omission -- see module docstring)."""

    def __init__(self):
        self.reg0 = [0, 0]   # L, R accumulator (scale A_FRAC + C_FRAC)
        self.reg1 = [0, 0]
        self.coeffs = (0, 0, 0, 0, 0)   # b0, b1, b2, a1, a2 (Q3.29)

    def set_coeffs(self, b0, b1, b2, a1, a2):
        self.coeffs = (b0, b1, b2, a1, a2)

    def reset(self):
        self.reg0 = [0, 0]
        self.reg1 = [0, 0]

    def process_sample(self, x, ch):
        """x: Q10.21 signed sample; ch: 0=L, 1=R. Returns Q10.21 signed."""
        b0, b1, b2, a1, a2 = self.coeffs
        op = x * b0 + self.reg0[ch]
        nr0 = x * b1 + self.reg1[ch] - rnd_shift(a1 * op, C_FRAC)
        nr1 = x * b2 - rnd_shift(a2 * op, C_FRAC)
        if nr0 >= REG_LIM or nr0 < -REG_LIM or nr1 >= REG_LIM or nr1 < -REG_LIM:
            raise OverflowError("biquad accumulator overflow (REG_LIM)")
        self.reg0[ch] = nr0
        self.reg1[ch] = nr1
        return sat_s(rnd_shift(op, C_FRAC), A_BITS)


class SendSlotInstance:
    """Per-instance state for ONE send-bus FX slot occupant. `occupied`
    mirrors `fx[v] != nullptr`; disabling is a separate, routing-level
    control (`ExtendedSendRack.fx_disable`), matching the engine's two
    independent gates (slot loaded vs. slot disabled)."""

    def __init__(self, name, slot_bit):
        self.name = name
        self.slot_bit = slot_bit
        self.occupied = False
        self.biquad = BiquadInstance()
        self.ext_reads = 0     # declared 0: this occupant is register-only
        self.ext_writes = 0    # (on-chip); a real occupant owns its own
        #                        external-memory accounting (SXT-015/016)

    def load(self, b0, b1, b2, a1, a2):
        """`loadFx()`: a FRESH instance -- state cleared, coefficients
        adopted, `occupied` set. Used both for an initially-empty slot and
        for a patch change on an already-occupied slot (mid-tail reload).
        The BUS's send/return gain plane is untouched (it is routing state,
        not occupant state)."""
        self.occupied = True
        self.biquad.reset()
        self.biquad.set_coeffs(b0, b1, b2, a1, a2)

    def unload(self):
        """`enqueueFXOff()`: instance released -- state gone, slot empty."""
        self.occupied = False
        self.biquad.reset()

    def process_ringout(self, in_l, in_r, indata):
        """Mirrors `Effect::process_ringout(L, R, indata) -> bool`: while
        `indata` (this bus's `sendused[k]` flag) is true, process every
        sample of the block IN PLACE on the send bus and report
        still-ringing; otherwise pass the bus through untouched and report
        not-ringing. This occupant declares no ring-out policy of its own,
        so its own ring decision reduces to `indata` exactly -- the SAME
        simplification all four landed routing leaves declared (a
        tail-bearing occupant's own policy is algorithm-leaf scope). Its
        ARITHMETIC tail -- nonzero output after the input goes silent,
        straight out of the TDF2 registers -- is real and is what the tail
        acceptance case and the dropped-tail negative controls exercise."""
        if not indata:
            return list(in_l), list(in_r), False
        out_l = [0] * len(in_l)
        out_r = [0] * len(in_r)
        for k in range(len(in_l)):
            out_l[k] = self.biquad.process_sample(in_l[k], 0)
            out_r[k] = self.biquad.process_sample(in_r[k], 1)
        return out_l, out_r, True


class SendBusLevels:
    """The routing gain plane of ONE send bus (Q1.30 words). Bus state, not
    occupant state: a `loadFx()` on the slot does not disturb it."""

    def __init__(self, send_gain_a=0, send_gain_b=0, return_gain=0):
        self.send_gain_a = send_gain_a
        self.send_gain_b = send_gain_b
        self.return_gain = return_gain

    def as_tuple(self):
        return (self.send_gain_a, self.send_gain_b, self.return_gain)

    def set(self, send_gain_a, send_gain_b, return_gain):
        self.send_gain_a = send_gain_a
        self.send_gain_b = send_gain_b
        self.return_gain = return_gain


class ExtendedSendRack:
    """The EXTENDED half of the engine's send rack: TWO concurrently-active
    send-bus instances (send3, send4) wired in PARALLEL -- each formed from
    the two scene buses through its own per-scene send gains, processed by
    its own occupant instance, and mixed back into the main bus through its
    own return gain -- reproducing SurgeSynthesizer::process()'s send-FX
    block for slots 12/13. Per-instance state: `slot3.biquad` and
    `slot4.biquad` are two independent `BiquadInstance` objects; state is
    never pooled (AGENTS.md; issue #64 acceptance "Per-instance state")."""

    def __init__(self):
        self.slot3 = SendSlotInstance("send3", FXSLOT_SEND3)
        self.slot4 = SendSlotInstance("send4", FXSLOT_SEND4)
        self.levels3 = SendBusLevels()
        self.levels4 = SendBusLevels()
        self.fx_bypass = FXB_ALL_FX
        self.fx_disable = 0        # 16-bit mask, engine bit layout
        self.scene_b_active = True  # false in Single scene mode
        self.send_ring = [False, False]   # this rack's per-bus ring memory

    # ---------------------------------------------------------- control
    def apply_control(self, fx_bypass, fx_disable, scene_b_active,
                      occupied3, reload3, coeffs3, levels3,
                      occupied4, reload4, coeffs4, levels4):
        """Control-rate pass, applied BEFORE the audio block and independent
        of `fx_bypass` (the engine's load/unload path is control-rate).
        Implements the frozen instance-lifecycle rule -- see the module
        docstring. `levels3`/`levels4` are (send_gain_a, send_gain_b,
        return_gain) Q1.30 triples and are applied to the BUS, never to the
        occupant instance."""
        self.fx_bypass = fx_bypass
        self.fx_disable = fx_disable
        self.scene_b_active = bool(scene_b_active)
        self.levels3.set(*levels3)
        self.levels4.set(*levels4)
        for slot, occ, rld, co in ((self.slot3, occupied3, reload3, coeffs3),
                                   (self.slot4, occupied4, reload4, coeffs4)):
            if not occ:
                slot.unload()
            elif rld or not slot.occupied:
                slot.load(*co)          # fresh instance: THIS slot only
            else:
                slot.biquad.set_coeffs(*co)   # unchanged occupancy: no clear

    def panic_reset(self):
        """All-notes-off / suspend: both instances cleared, both buses' ring
        memory dropped. Occupancy (the loaded patch) and the gain plane are
        NOT changed."""
        self.slot3.biquad.reset()
        self.slot4.biquad.reset()
        self.send_ring = [False, False]

    def slot_disabled(self, bit):
        return bool((self.fx_disable >> bit) & 1)

    def stage_active(self):
        return self.fx_bypass in SEND_ACTIVE_MODES

    def bus_runs(self, slot):
        """A send bus runs iff the send stage is active for this bypass mode
        AND the slot is loaded AND the slot is not disabled. A bus that does
        not run contributes NOTHING to the main bus (unlike an insert slot,
        which passes its audio through)."""
        return (self.stage_active() and slot.occupied
                and not self.slot_disabled(slot.slot_bit))

    # ------------------------------------------------------------ audio
    def form_bus(self, sa, sb, levels):
        """Accumulate ONE channel of one send bus from the two scene buses.
        ONE rounding, ONE saturation for the whole scene sum -- so the
        scene-accumulation order is irrelevant by construction."""
        out = [0] * len(sa)
        ga, gb = levels.send_gain_a, levels.send_gain_b
        for k in range(len(sa)):
            wide = sa[k] * ga
            if self.scene_b_active:
                wide += sb[k] * gb
            out[k] = sat_s(rnd_shift(wide, G_FRAC), A_BITS)
        return out

    def process_block(self, sa_l, sa_r, sb_l, sb_r, main_l, main_r,
                      send_in3, send_in4):
        """Returns (main_out_l, main_out_r, wet3_l, wet3_r, wet4_l, wet4_r,
        ring3, ring4).

        Mirrors process()'s send-FX block for slots 12/13:
            if fx_bypass == fxb_all_fx:
                for (slot, bit, levels, sendused) in
                        (send3, 12, levels3, send_in3),
                        (send4, 13, levels4, send_in4):
                    if slot.occupied and not fx_disable_bit(bit):
                        bus = scene_a*send_gain_a (+ scene_b*send_gain_b)
                        (bus, ring) = slot.process_ringout(bus, sendused)
                        main += bus * return_gain
            else:
                main unchanged; no bus is formed, no instance state
                advances, and neither bus reports ringing (the engine never
                enters the block).

        `sa_*` / `sb_*` are the two scenes' post-insert buses, `main_*` is
        the main bus as the scene sum (plus any already-mixed send1/send2
        returns) left it. Computing any of them is out of this leaf's scope.
        `wet3_*` / `wet4_*` are the per-bus signals AFTER the occupant and
        BEFORE the return gain; they are internal observability taps for the
        RTL-vs-model comparison (the engine keeps them in `fxsendout`
        scratch), not engine-observable outputs.
        """
        n = len(main_l)
        zero = [0] * n
        if not self.stage_active():
            self.send_ring = [False, False]
            return (list(main_l), list(main_r),
                    list(zero), list(zero), list(zero), list(zero),
                    False, False)

        wets = {}
        rings = {}
        for slot, levels, sendused in ((self.slot3, self.levels3, send_in3),
                                       (self.slot4, self.levels4, send_in4)):
            if not self.bus_runs(slot):
                wets[slot.name] = (list(zero), list(zero))
                rings[slot.name] = False
                continue
            bus_l = self.form_bus(sa_l, sb_l, levels)
            bus_r = self.form_bus(sa_r, sb_r, levels)
            wl, wr, ring = slot.process_ringout(bus_l, bus_r, sendused)
            wets[slot.name] = (wl, wr)
            rings[slot.name] = ring

        out_l = [0] * n
        out_r = [0] * n
        for k in range(n):
            wide_l = main_l[k] << G_FRAC
            wide_r = main_r[k] << G_FRAC
            for slot, levels in ((self.slot3, self.levels3),
                                 (self.slot4, self.levels4)):
                if not self.bus_runs(slot):
                    continue
                wl, wr = wets[slot.name]
                wide_l += wl[k] * levels.return_gain
                wide_r += wr[k] * levels.return_gain
            out_l[k] = sat_s(rnd_shift(wide_l, G_FRAC), A_BITS)
            out_r[k] = sat_s(rnd_shift(wide_r, G_FRAC), A_BITS)

        self.send_ring = [rings["send3"], rings["send4"]]
        w3l, w3r = wets["send3"]
        w4l, w4r = wets["send4"]
        return (out_l, out_r, w3l, w3r, w4l, w4r,
                rings["send3"], rings["send4"])

    def checkpoint(self):
        """Exact-equality checkpoint tuple (RTL-vs-model comparator)."""
        return (
            tuple(self.slot3.biquad.reg0), tuple(self.slot3.biquad.reg1),
            tuple(self.slot4.biquad.reg0), tuple(self.slot4.biquad.reg1),
        )
