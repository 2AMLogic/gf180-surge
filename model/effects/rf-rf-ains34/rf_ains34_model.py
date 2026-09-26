"""SXT-028i frozen fixed-point model -- routing form: Scene-A insert FX bus,
slots 3-4 (ains3 -> ains4, the EXTENDED rack half of scene A's insert chain).

Structure authority (CITED, nothing copied; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71):

  src/common/SurgeSynthesizer.cpp  process() -- the per-scene INSERT-effect
    block: each scene's own stereo bus (`sceneout[0][0]`, `sceneout[0][1]`
    for scene A) is processed IN PLACE through that scene's insert slots in
    slot order, with the scene's own ring/live flag threaded forward through
    each slot's `process_ringout(L, R, indata) -> bool` return value
    (`sc_state[0]` for scene A). The per-slot gates are (a) the slot is
    loaded (`fx[fxslot_ains3] != nullptr`) and (b) the slot is not disabled
    (`!(storage.getPatch().fx_disable.val.i & (1 << fxslot_ains3))`).
    Instance lifecycle: `loadFx()` (per-slot reload -> a FRESH instance,
    i.e. that slot's history starts from zero and the sibling slot's history
    is untouched), `enqueueFXOff()` (slot off -> instance released),
    `reorderFx()` (slot-content permutation -- the order axis this leaf's
    wrong-order negative control attacks).
  src/common/SurgeStorage.h -- `fxslot_positions` (fxslot_ains1 = 0,
    fxslot_ains2 = 1, bins1/2 = 2/3, send1/2 = 4/5, global1/2 = 6/7,
    **fxslot_ains3 = 8, fxslot_ains4 = 9**, bins3/4 = 10/11, send3/4 =
    12/13, global3/4 = 14/15), `fxb_*` bypass enum (fxb_all_fx = 0,
    fxb_no_sends = 1, fxb_scene_fx_only = 2, fxb_no_fx = 3), `n_fx_slots`
    = 16 (`fx_disable` bit width), `n_send_slots` = 4 (send-form leaves'
    scope, not this leaf's).
  src/common/dsp/effects/SurgeSSTFXAdapter.h + SurgeEffect.h -- instance
    construction/suspend per slot (`fx[v] == nullptr` <=> slot unoccupied;
    modeled here as `InsertSlotInstance.occupied`).

  In-repo re-derivation of the slot-index constants (does NOT depend on a
  live oracle): `tools/export_normalized_graphs.py` `FX_ROLES` and every
  record of `corpus/normalized/graphs.jsonl` carry the pinned engine's slot
  order by patch `fx[]` index -- role `ains3` at index 8 and `ains4` at
  index 9, which is exactly FXSLOT_AINS3/FXSLOT_AINS4 below. The landed
  sibling routing-form leaves pin the same table's global1/global2 = 6/7
  (`model/effects/rf-rf-global2/`) and bins1/bins2 = 2/3
  (`model/effects/rf-rf-bins12/`).

EXTENDED RACK HALF -- what "slots 3-4" means here, and where this leaf's
boundary is. Scene A's insert chain is FOUR slots long: the base half
(ains1, ains2 -- patch fx[] indices 0/1) followed by the extended half
(ains3, ains4 -- indices 8/9, added with the engine's extended FX rack).
This leaf models the EXTENDED half only: the ains3 -> ains4 series pair, in
place on scene A's own bus. The audio and the scene ring/live flag arriving
at ains3 are therefore whatever the UPSTREAM base half (ains1/ains2) left --
that upstream half is a declared scope omission (a sibling `rf-ains12`-class
leaf's scope) and is supplied here as per-block stimulus (`in_l`, `in_r`,
`sc_in`). Two facts about that composition are kept apart on purpose:

  * VERIFIED in-repo (see above): ains3 = slot 8, ains4 = slot 9, and the
    `fx_disable` bit for each is its own slot index.
  * DECLARED CONTRACT, not a verified read here: that the chain order is
    ains1 -> ains2 -> ains3 -> ains4 (i.e. the extended half runs AFTER the
    base half, and within it ains3 runs before ains4). The environment that
    froze this model had no oracle checkout, so the pinned `process()` text
    could not be re-read. The intra-pair order (ains3 before ains4) is the
    axis this leaf's own wrong-order control attacks; the base-vs-extended
    composition order is out of this leaf's scope to verify and is recorded
    as a named re-verification item in reports/SXT-028i/EVIDENCE.md section 0.

BYPASS-MODE PARTITION (declared contract of this leaf). The insert
(scene) stage runs in every `fx_bypass` mode EXCEPT `fxb_no_fx`, i.e. in
{fxb_all_fx, fxb_no_sends, fxb_scene_fx_only} -- `fxb_no_sends` removes the
send stage only, `fxb_scene_fx_only` keeps exactly this (scene/insert)
stage and removes sends + globals, `fxb_no_fx` removes everything. This is
the complement of the GLOBAL set ({fxb_all_fx, fxb_no_sends}) pinned by the
landed sibling leaf `model/effects/rf-rf-global2/` under the same enum, and
it is the SAME insert-stage partition the landed sibling insert leaf
`model/effects/rf-rf-bins12/` declared (its scene-B half of the same
`process()` block). As there, it is the one structural fact in this file
that could NOT be re-derived from an in-repo artifact in the environment
that froze this model; it is recorded as a named re-verification item in
reports/SXT-028i/EVIDENCE.md section 0, not as a verified read.

SCENE-A REACHABILITY (a real difference from the sibling scene-B leaf).
Scene A is instantiated in EVERY scene mode, Single included, so a scene-A
insert slot is reachable in every patch that loads. The sibling
`rf-rf-bins12` leaf had to record per carrier whether scene B exists at all
(Single-mode patches never instantiate it); here that gate does not exist,
and all five named carriers are Single/Dual-mode patches whose ains3/ains4
slots are reachable. Recorded per carrier as
`scene_context.scene_a_instantiated` (always true) rather than assumed
silently.

FORM SCOPE ONLY (issue #61 / SXT-028i). This leaf models the scene-A
extended-half insert wiring, the ains3 -> ains4 slot-order schedule,
`fx_bypass`/`fx_disable` gating (bits 8/9), the per-slot instance lifecycle
(patch-change reload, slot-off, panic/reset), and the per-instance-state
isolation of hosting TWO concurrently-active insert instances on ONE scene
bus. It makes **no** claim about any specific Surge FX algorithm's fidelity
-- "algorithm behavior stays with the per-algorithm leaves" (issue #61 scope
note; AGENTS.md). The per-slot "occupant" exercised here is a **synthetic
TDF2 biquad primitive** (structure: the same Direct-Form-II-Transposed
recurrence every landed leaf's biquad stage uses -- Delay/Chorus's
per-sample-lag `Biquad` (model/effects/delay/delay_model.py), Reverb1's
instant-coefficient `biq_stage` (model/effects/reverb1/reverb1_fixed.py),
and the sibling routing leaves' `BiquadInstance`
(model/effects/rf-rf-global2/rf_global2_model.py,
model/effects/rf-rf-bins12/rf_bins12_model.py) -- with coefficients supplied
as arbitrary control-plane stimulus, NOT derived from any concrete Surge FX
class's parameters). It exists only to give the routing/scheduling claim a
real, per-instance-stateful, tail-bearing arithmetic path to verify
order-sensitivity, state isolation, lifecycle behavior, and tail
continuation against. No preset-support or algorithm-fidelity claim follows
from it, and it must never be reported as a substitute for a concrete
occupant algorithm under a support claim (issue #61 negative control:
"Generic substitute").

Frozen word formats (this leaf; format-family-consistent with the SXT-023
table in model/effects/README.md and IDENTICAL in family to the two landed
routing leaves so that the three routing forms can be compared directly):

  scene-bus audio words    Q10.21 signed 32-bit   ("A_FMT"; matches the
                                                   Delay/EQ/Chorus bus scale)
  biquad coefficients      Q3.29  signed 32-bit   ("C_FMT"; block-constant,
                                                   NO per-sample lag -- a
                                                   declared scope omission;
                                                   coefficient smoothing is
                                                   algorithm-leaf scope)
  biquad TDF2 accumulator  80-bit signed          (Reverb1 REG_LIM
                                                   precedent: headroom for
                                                   arbitrary/adversarial
                                                   negative-control
                                                   coefficients without a
                                                   stability argument)

Arithmetic rules (FROZEN, self-contained -- mirrors model/effects/qmath.py's
round-half-up / saturating conventions without mutating its shared format
registry; reverb1_fixed.py, rf_global2_model.py and rf_bins12_model.py
precedent for a leaf-local kernel): exact products, round-half-up
`(p + 2**(s-1)) >> s`, saturating; no floating point at audio run time.

This file is deliberately SELF-CONTAINED and does not import a sibling
leaf's kernel: `model_revision()` (sha256 of this file) is the
frozen-revision pin consumed by the RTL comparator and the stale-harness
negative control, so a sibling leaf's future edit must never be able to
change this leaf's frozen behavior without changing this leaf's own pin.

Per-instance state: one `InsertSlotInstance` holds ONE `BiquadInstance`
(4 accumulator words: reg0/reg1 x {L,R}) plus its own `occupied` flag. The
two configured scene-A extended insert slots
(`SceneAExtendedInsertBus.slot3` = ains3, `.slot4` = ains4) are two disjoint
`InsertSlotInstance` objects -- no accumulator state is ever shared between
them, even though both instances run through the SAME arithmetic kernel
class (`BiquadInstance.process_sample`); this is exactly the "shared
arithmetic, independent per-instance state" contract (AGENTS.md; issue #61
"State" section).

Declared control-plane boundary (one control word set per block, applied by
`apply_control()` BEFORE the audio block and independent of `fx_bypass` --
the engine's load/unload path is control-rate and runs whether or not the
audio stage is bypassed): `fx_bypass` (2-bit mode), `fx_disable` (16-bit
mask, engine bit layout; only bits 8/9 are consumed here), and per slot:
`occupied`, `reload` (a patch-change pulse -- `loadFx()`), and 5 biquad
coefficients (Q3.29). The scene-A live/ringing flag as it ARRIVES at the
extended half (`sc_in`, the engine's `sc_state[0]` after the base half has
run) is OUT of this leaf's scope (voice/scene activity is the voice-stage
leaves' scope; the ains1/ains2 base half, the send buses and the global bus
are other `rf-*` leaves' scope) and is supplied as a per-block synthetic
boolean stimulus.

Instance lifecycle rule (FROZEN; identical in the model and the RTL):
  * `occupied` false                      -> instance released: registers
                                             cleared, stage no-ops.
  * `occupied` rising (unoccupied -> occupied), or `reload` pulse while
    occupied                              -> FRESH instance (`loadFx()`):
                                             THAT slot's registers are
                                             cleared and the new
                                             coefficients adopted; the
                                             sibling slot's history is
                                             untouched and the scene ring
                                             flag is NOT cleared (a
                                             patch change mid-tail does not
                                             silence the other slot's tail).
  * `occupied` steady and no `reload`     -> the coefficients are adopted
                                             WITHOUT clearing state (an
                                             abrupt parameter change; the
                                             engine's own per-parameter
                                             smoothing is algorithm-leaf
                                             scope -- declared omission).
  * `panic_reset()`                       -> both instances cleared and the
                                             bus's own ring memory dropped
                                             (the engine's all-notes-off /
                                             suspend path).

Declared scope omissions (fail-closed):
  * The ains1/ains2 BASE half of this same scene-A insert chain (a sibling
    `rf-ains12`-class leaf's scope), the scene-B insert bus (`rf-bins*`,
    slots 1-2 landed as `rf-rf-bins12`), the send buses and `return_level` /
    per-scene `send_level` smoothing (send-form `rf-send*` leaves), and the
    global bus (`rf-global*`, slot 2 landed as `rf-rf-global2`). This leaf
    models exactly the pinned-source `roles: [ains3, ains4]` scope.
  * The scene-A bus's own downstream summation into the master bus.
  * Per-sample coefficient smoothing/ramping into the occupant
    (algorithm-leaf scope).
  * Any concrete Surge FX algorithm's own ring-out DECISION: this occupant
    reports ringing exactly while `indata` is true (see
    `InsertSlotInstance.process_ringout`); its arithmetic tail (nonzero
    output after the input goes silent) is real and is exercised, but a
    tail-bearing occupant's own `process_ringout` return policy is
    algorithm-leaf scope.
"""

import hashlib
import os

BLOCK = 32

A_FRAC, A_BITS = 21, 32     # Q10.21 scene-bus audio words
C_FRAC, C_BITS = 29, 32     # Q3.29 biquad coefficients (instant)
R_BITS = 80                 # TDF2 accumulator width (Reverb1 REG_LIM class)
REG_LIM = 1 << (R_BITS - 1)

FXB_ALL_FX, FXB_NO_SENDS, FXB_SCENE_FX_ONLY, FXB_NO_FX = 0, 1, 2, 3

# SurgeStorage.h fxslot_positions (re-derivable in-repo from
# tools/export_normalized_graphs.py FX_ROLES / corpus/normalized/graphs.jsonl)
FXSLOT_AINS3, FXSLOT_AINS4 = 8, 9

# The bypass modes in which the INSERT (scene) stage runs. Declared contract
# of this leaf -- see the module docstring's "BYPASS-MODE PARTITION" note.
INSERT_ACTIVE_MODES = (FXB_ALL_FX, FXB_NO_SENDS, FXB_SCENE_FX_ONLY)

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


class InsertSlotInstance:
    """Per-instance state for ONE scene-insert FX slot occupant. `occupied`
    mirrors `fx[v] != nullptr`; disabling is a separate, routing-level
    control (`SceneAExtendedInsertBus.fx_disable`), matching the engine's two
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
        for a patch change on an already-occupied slot (mid-tail reload)."""
        self.occupied = True
        self.biquad.reset()
        self.biquad.set_coeffs(b0, b1, b2, a1, a2)

    def unload(self):
        """`enqueueFXOff()`: instance released -- state gone, slot empty."""
        self.occupied = False
        self.biquad.reset()

    def process_ringout(self, in_l, in_r, indata):
        """Mirrors `Effect::process_ringout(L, R, indata) -> bool`: while
        `indata` (the scene live/ringing flag as it arrives at this slot) is
        true, process every sample of the block IN PLACE on the scene bus and
        report still-ringing; otherwise pass the bus through untouched and
        report not-ringing. This occupant declares no ring-out policy of its
        own, so its own ring decision reduces to `indata` exactly (a
        tail-bearing occupant's own policy is algorithm-leaf scope); its
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


class SceneAExtendedInsertBus:
    """The EXTENDED half of scene A's insert FX chain: TWO
    concurrently-active insert slot instances (ains3, ains4) wired in SERIES,
    IN PLACE, on scene A's own stereo bus, reproducing
    SurgeSynthesizer::process()'s per-scene insert schedule for scene A's
    extended slots. The bus and ring flag handed in have already passed the
    ains1/ains2 base half (declared scope omission -- see the module
    docstring's "EXTENDED RACK HALF" note). Per-instance state:
    `slot3.biquad` and `slot4.biquad` are two independent `BiquadInstance`
    objects; state is never pooled (AGENTS.md; issue #61 acceptance
    "Per-instance state")."""

    def __init__(self):
        self.slot3 = InsertSlotInstance("ains3", FXSLOT_AINS3)
        self.slot4 = InsertSlotInstance("ains4", FXSLOT_AINS4)
        self.fx_bypass = FXB_ALL_FX
        self.fx_disable = 0   # 16-bit mask, engine bit layout
        self.sc_ring = False  # this bus's own memory of the scene ring flag

    # ---------------------------------------------------------- control
    def apply_control(self, fx_bypass, fx_disable,
                      occupied3, reload3, coeffs3,
                      occupied4, reload4, coeffs4):
        """Control-rate pass, applied BEFORE the audio block and
        independent of `fx_bypass` (the engine's load/unload path is
        control-rate). Implements the frozen instance-lifecycle rule --
        see the module docstring."""
        self.fx_bypass = fx_bypass
        self.fx_disable = fx_disable
        for slot, occ, rld, co in ((self.slot3, occupied3, reload3, coeffs3),
                                   (self.slot4, occupied4, reload4, coeffs4)):
            if not occ:
                slot.unload()
            elif rld or not slot.occupied:
                slot.load(*co)          # fresh instance: THIS slot only
            else:
                slot.biquad.set_coeffs(*co)   # unchanged occupancy: no clear

    def panic_reset(self):
        """All-notes-off / suspend: both instances cleared, ring memory
        dropped. Occupancy (the loaded patch) is NOT changed."""
        self.slot3.biquad.reset()
        self.slot4.biquad.reset()
        self.sc_ring = False

    def slot_disabled(self, bit):
        return bool((self.fx_disable >> bit) & 1)

    # ------------------------------------------------------------ audio
    def process_block(self, in_l, in_r, sc_in):
        """Returns (out_l, out_r, sc_out) for scene A's own bus at the output
        of the extended half.

        Mirrors process()'s per-scene insert block for scene A's extended
        slots:
            if fx_bypass != fxb_no_fx:          # {ALL_FX, NO_SENDS,
                sc = sc_in                      #  SCENE_FX_ONLY}
                for (slot, bit) in (ains3, 8), (ains4, 9):
                    if slot.occupied and not fx_disable_bit(bit):
                        (bus, sc) = slot.process_ringout(bus, sc)
            else:
                bus unchanged; the ring state is NOT computed/updated (the
                engine never enters the block, so the scene ring flag
                simply passes through this stage untouched).
        """
        if self.fx_bypass not in INSERT_ACTIVE_MODES:
            self.sc_ring = bool(sc_in)
            return list(in_l), list(in_r), sc_in
        bus_l, bus_r = list(in_l), list(in_r)
        sc = sc_in
        for slot in (self.slot3, self.slot4):
            if slot.occupied and not self.slot_disabled(slot.slot_bit):
                bus_l, bus_r, sc = slot.process_ringout(bus_l, bus_r, sc)
        self.sc_ring = bool(sc)
        return bus_l, bus_r, sc

    def checkpoint(self):
        """Exact-equality checkpoint tuple (RTL-vs-model comparator)."""
        return (
            tuple(self.slot3.biquad.reg0), tuple(self.slot3.biquad.reg1),
            tuple(self.slot4.biquad.reg0), tuple(self.slot4.biquad.reg1),
        )
