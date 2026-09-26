"""SXT-028h frozen fixed-point model -- routing form: Scene-B insert FX bus,
slots 1-2 (bins1 -> bins2 series insert chain on the scene-B output bus).

Structure authority (CITED, nothing copied; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71):

  src/common/SurgeSynthesizer.cpp  process() -- the per-scene INSERT-effect
    block: each scene's own stereo bus (`sceneout[1][0]`, `sceneout[1][1]`
    for scene B) is processed IN PLACE through that scene's insert slots in
    slot order, with the scene's own ring/live flag threaded forward through
    each slot's `process_ringout(L, R, indata) -> bool` return value
    (`sc_state[1]` for scene B). The per-slot gates are (a) the slot is
    loaded (`fx[fxslot_bins1] != nullptr`) and (b) the slot is not disabled
    (`!(storage.getPatch().fx_disable.val.i & (1 << fxslot_bins1))`).
    Instance lifecycle: `loadFx()` (per-slot reload -> a FRESH instance,
    i.e. that slot's history starts from zero and the sibling slot's history
    is untouched), `enqueueFXOff()` (slot off -> instance released),
    `reorderFx()` (slot-content permutation -- the order axis this leaf's
    wrong-order negative control attacks).
  src/common/SurgeStorage.h -- `fxslot_positions` (fxslot_ains1 = 0,
    fxslot_ains2 = 1, **fxslot_bins1 = 2, fxslot_bins2 = 3**, send1/2 = 4/5,
    global1/2 = 6/7, ains3/4 = 8/9, bins3/4 = 10/11, send3/4 = 12/13,
    global3/4 = 14/15), `fxb_*` bypass enum (fxb_all_fx = 0,
    fxb_no_sends = 1, fxb_scene_fx_only = 2, fxb_no_fx = 3), `n_fx_slots`
    = 16 (`fx_disable` bit width), `n_send_slots` = 4 (send-form leaves'
    scope, not this leaf's).
  src/common/dsp/effects/SurgeSSTFXAdapter.h + SurgeEffect.h -- instance
    construction/suspend per slot (`fx[v] == nullptr` <=> slot unoccupied;
    modeled here as `InsertSlotInstance.occupied`).

  In-repo re-derivation of the slot-index constants (does NOT depend on a
  live oracle): `tools/export_normalized_graphs.py` `FX_ROLES` and every
  record of `corpus/normalized/graphs.jsonl` carry the pinned engine's slot
  order by patch `fx[]` index -- role `bins1` at index 2 and `bins2` at
  index 3, which is exactly FXSLOT_BINS1/FXSLOT_BINS2 below. The landed
  sibling routing-form leaf `model/effects/rf-rf-global2/` pins the same
  table's global1/global2 = 6/7 and pins the GLOBAL bus's bypass-mode set
  as {fxb_all_fx, fxb_no_sends}.

BYPASS-MODE PARTITION (declared contract of this leaf). The insert
(scene) stage runs in every `fx_bypass` mode EXCEPT `fxb_no_fx`, i.e. in
{fxb_all_fx, fxb_no_sends, fxb_scene_fx_only} -- `fxb_no_sends` removes the
send stage only, `fxb_scene_fx_only` keeps exactly this (scene/insert)
stage and removes sends + globals, `fxb_no_fx` removes everything. This is
the complement of the sibling leaf's already-pinned GLOBAL set
({fxb_all_fx, fxb_no_sends}) under the same enum, and it is the one
structural fact in this file that could NOT be re-derived from an in-repo
artifact in the environment that froze this model (no oracle checkout; see
reports/SXT-028h/EVIDENCE.md section 0 -- it is recorded there as a named
re-verification item, not as a verified read).

FORM SCOPE ONLY (issue #60 / SXT-028h). This leaf models the scene-B insert
bus wiring, the bins1 -> bins2 slot-order schedule, `fx_bypass`/`fx_disable`
gating, the per-slot instance lifecycle (patch-change reload, slot-off,
panic/reset), and the per-instance-state isolation of hosting TWO
concurrently-active insert instances on ONE scene bus. It makes **no** claim
about any specific Surge FX algorithm's fidelity -- "algorithm behavior
stays with the per-algorithm leaves" (issue #60 scope note; AGENTS.md). The
per-slot "occupant" exercised here is a **synthetic TDF2 biquad primitive**
(structure: the same Direct-Form-II-Transposed recurrence every landed
leaf's biquad stage uses -- Delay/Chorus's per-sample-lag `Biquad`
(model/effects/delay/delay_model.py), Reverb1's instant-coefficient
`biq_stage` (model/effects/reverb1/reverb1_fixed.py), and the sibling
routing leaf's `BiquadInstance` (model/effects/rf-rf-global2/
rf_global2_model.py) -- with coefficients supplied as arbitrary
control-plane stimulus, NOT derived from any concrete Surge FX class's
parameters). It exists only to give the routing/scheduling claim a real,
per-instance-stateful, tail-bearing arithmetic path to verify
order-sensitivity, state isolation, lifecycle behavior, and tail
continuation against. No preset-support or algorithm-fidelity claim follows
from it, and it must never be reported as a substitute for a concrete
occupant algorithm under a support claim (issue #60 negative control:
"Generic substitute").

Frozen word formats (this leaf; format-family-consistent with the SXT-023
table in model/effects/README.md and identical in family to the sibling
routing leaf so that the two routing forms can be compared directly):

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
registry; reverb1_fixed.py and rf_global2_model.py precedent for a
leaf-local kernel): exact products, round-half-up `(p + 2**(s-1)) >> s`,
saturating; no floating point at audio run time.

This file is deliberately SELF-CONTAINED and does not import the sibling
routing leaf's kernel: `model_revision()` (sha256 of this file) is the
frozen-revision pin consumed by the RTL comparator and the stale-harness
negative control, so a sibling leaf's future edit must never be able to
change this leaf's frozen behavior without changing this leaf's own pin.

Per-instance state: one `InsertSlotInstance` holds ONE `BiquadInstance`
(4 accumulator words: reg0/reg1 x {L,R}) plus its own `occupied` flag. The
two configured scene-B insert slots (`SceneBInsertBus.slot1` = bins1,
`.slot2` = bins2) are two disjoint `InsertSlotInstance` objects -- no
accumulator state is ever shared between them, even though both instances
run through the SAME arithmetic kernel class
(`BiquadInstance.process_sample`); this is exactly the "shared arithmetic,
independent per-instance state" contract (AGENTS.md; issue #60 "State"
section).

Declared control-plane boundary (one control word set per block, applied by
`apply_control()` BEFORE the audio block and independent of `fx_bypass` --
the engine's load/unload path is control-rate and runs whether or not the
audio stage is bypassed): `fx_bypass` (2-bit mode), `fx_disable` (16-bit
mask, engine bit layout; only bits 2/3 are consumed here), and per slot:
`occupied`, `reload` (a patch-change pulse -- `loadFx()`), and 5 biquad
coefficients (Q3.29). The upstream scene-B live/ringing flag (`sc_in`, the
engine's `sc_state[1]` as it arrives at the insert stage) is OUT of this
leaf's scope (voice/scene activity is the voice-stage leaves' scope; the
send/global buses are other `rf-*` leaves' scope) and is supplied as a
per-block synthetic boolean stimulus.

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
  * bins3/bins4 (SXT-028's `rf-bins34`-class leaf), the scene-A insert bus
    (`rf-ains*`), the send buses and `return_level` / per-scene `send_level`
    smoothing (send-form `rf-send*` leaves), and the global bus
    (`rf-global*`, already landed as `rf-rf-global2`). This leaf models
    exactly the pinned-source `roles: [bins1, bins2]` scope.
  * The scene-B bus's own downstream summation into the master bus and the
    scene-mode logic that decides whether scene B is instantiated at all
    (Single vs Dual/Key Split/Channel Split) -- upstream/downstream of this
    stage.
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
FXSLOT_BINS1, FXSLOT_BINS2 = 2, 3

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
    control (`SceneBInsertBus.fx_disable`), matching the engine's two
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
        `indata` (upstream scene live/ringing) is true, process every sample
        of the block IN PLACE on the scene bus and report still-ringing;
        otherwise pass the bus through untouched and report not-ringing.
        This occupant declares no ring-out policy of its own, so its own
        ring decision reduces to `indata` exactly (a tail-bearing
        occupant's own policy is algorithm-leaf scope); its ARITHMETIC tail
        -- nonzero output after the input goes silent, straight out of the
        TDF2 registers -- is real and is what the tail acceptance case and
        the dropped-tail negative control exercise."""
        if not indata:
            return list(in_l), list(in_r), False
        out_l = [0] * len(in_l)
        out_r = [0] * len(in_r)
        for k in range(len(in_l)):
            out_l[k] = self.biquad.process_sample(in_l[k], 0)
            out_r[k] = self.biquad.process_sample(in_r[k], 1)
        return out_l, out_r, True


class SceneBInsertBus:
    """The scene-B insert FX bus: TWO concurrently-active insert slot
    instances (bins1, bins2) wired in SERIES, IN PLACE, on scene B's own
    stereo bus, reproducing SurgeSynthesizer::process()'s per-scene insert
    schedule for scene B. Per-instance state: `slot1.biquad` and
    `slot2.biquad` are two independent `BiquadInstance` objects; state is
    never pooled (AGENTS.md; issue #60 acceptance "Per-instance state")."""

    def __init__(self):
        self.slot1 = InsertSlotInstance("bins1", FXSLOT_BINS1)
        self.slot2 = InsertSlotInstance("bins2", FXSLOT_BINS2)
        self.fx_bypass = FXB_ALL_FX
        self.fx_disable = 0   # 16-bit mask, engine bit layout
        self.sc_ring = False  # this bus's own memory of the scene ring flag

    # ---------------------------------------------------------- control
    def apply_control(self, fx_bypass, fx_disable,
                      occupied1, reload1, coeffs1,
                      occupied2, reload2, coeffs2):
        """Control-rate pass, applied BEFORE the audio block and
        independent of `fx_bypass` (the engine's load/unload path is
        control-rate). Implements the frozen instance-lifecycle rule --
        see the module docstring."""
        self.fx_bypass = fx_bypass
        self.fx_disable = fx_disable
        for slot, occ, rld, co in ((self.slot1, occupied1, reload1, coeffs1),
                                   (self.slot2, occupied2, reload2, coeffs2)):
            if not occ:
                slot.unload()
            elif rld or not slot.occupied:
                slot.load(*co)          # fresh instance: THIS slot only
            else:
                slot.biquad.set_coeffs(*co)   # unchanged occupancy: no clear

    def panic_reset(self):
        """All-notes-off / suspend: both instances cleared, ring memory
        dropped. Occupancy (the loaded patch) is NOT changed."""
        self.slot1.biquad.reset()
        self.slot2.biquad.reset()
        self.sc_ring = False

    def slot_disabled(self, bit):
        return bool((self.fx_disable >> bit) & 1)

    # ------------------------------------------------------------ audio
    def process_block(self, in_l, in_r, sc_in):
        """Returns (out_l, out_r, sc_out) for scene B's own bus.

        Mirrors process()'s per-scene insert block for scene B:
            if fx_bypass != fxb_no_fx:          # {ALL_FX, NO_SENDS,
                sc = sc_in                      #  SCENE_FX_ONLY}
                for (slot, bit) in (bins1, 2), (bins2, 3):
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
        for slot in (self.slot1, self.slot2):
            if slot.occupied and not self.slot_disabled(slot.slot_bit):
                bus_l, bus_r, sc = slot.process_ringout(bus_l, bus_r, sc)
        self.sc_ring = bool(sc)
        return bus_l, bus_r, sc

    def checkpoint(self):
        """Exact-equality checkpoint tuple (RTL-vs-model comparator)."""
        return (
            tuple(self.slot1.biquad.reg0), tuple(self.slot1.biquad.reg1),
            tuple(self.slot2.biquad.reg0), tuple(self.slot2.biquad.reg1),
        )
