"""SXT-028j frozen fixed-point model -- routing form: Global FX slots 3-4
(global3 -> global4, the EXTENDED RACK HALF of the master global-FX chain).

Structure authority (CITED, nothing copied; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71):

  src/common/SurgeSynthesizer.cpp  process() -- the "apply global effects"
    block. The summed MASTER bus is processed IN PLACE through the four
    global slots in slot order

        {fxslot_global1, fxslot_global2, fxslot_global3, fxslot_global4}

    with the ring/live flag threaded forward through each slot's
    `process_ringout(L, R, indata) -> bool` return value, under the
    patch-level `fx_bypass` gate and the per-slot `fx_disable` bitmask gate.
    Instance lifecycle: `loadFx()` (per-slot reload -> a FRESH instance, i.e.
    that slot's history starts from zero and the sibling slot's history is
    untouched), `enqueueFXOff()` (slot off -> instance released),
    `reorderFx()` (slot-content permutation -- the order axis this leaf's
    wrong-order negative control attacks).
  src/common/SurgeStorage.h -- `fxslot_positions` (ains1/2 = 0/1,
    bins1/2 = 2/3, send1/2 = 4/5, global1/2 = 6/7, ains3/4 = 8/9,
    bins3/4 = 10/11, send3/4 = 12/13, **global3 = 14, global4 = 15**),
    `fxb_*` bypass enum (fxb_all_fx = 0, fxb_no_sends = 1,
    fxb_scene_fx_only = 2, fxb_no_fx = 3), `n_fx_slots` = 16 (`fx_disable`
    bit width), `n_send_slots` = 4 (send-form leaves' scope, not this
    leaf's).
  src/common/dsp/effects/SurgeSSTFXAdapter.h + SurgeEffect.h -- instance
    construction/suspend per slot (`fx[v] == nullptr` <=> slot unoccupied;
    modeled here as `GlobalSlotInstance.occupied`).

  In-repo re-derivation of the slot-index constants (does NOT depend on a
  live oracle): `tools/export_normalized_graphs.py` `FX_ROLES` and EVERY
  record of `corpus/normalized/graphs.jsonl` carry the pinned engine's slot
  order by patch `fx[]` index -- role `global3` at index 14 and `global4` at
  index 15 in all 3,561 committed records, which is exactly FXSLOT_GLOBAL3 /
  FXSLOT_GLOBAL4 below. Asserted by
  `tests/test_sxt028j.py::test_slot_indices_agree_with_the_committed_corpus_role_table`.

WHERE THIS SEGMENT SITS IN THE CHAIN (declared seam). global3/global4 are
the LAST TWO slots of the four-slot global chain, so the bus samples and the
ring flag arriving at global3 are whatever the global1 -> global2 segment
left -- that segment is the ALREADY-LANDED sibling leaf
`model/effects/rf-rf-global2/` (SXT-028d, issue #56). This leaf models
exactly its own `roles: [global3, global4]` scope and takes the upstream bus
and `glob_in` as inputs; `tests/test_sxt028j.py::
test_seam_composes_with_the_landed_global12_segment` composes the two landed
models into the full four-slot chain and checks that all FOUR slot instances
keep independent histories. Nothing about the upstream segment is re-claimed
here.

BYPASS-MODE PARTITION (inherited, not re-derived). The GLOBAL stage runs in
`fxb_all_fx` and `fxb_no_sends` only, and is skipped in `fxb_scene_fx_only`
and `fxb_no_fx`. That set is not re-read from the pinned source here (no
oracle checkout in the environment that froze this model -- see
reports/SXT-028j/EVIDENCE.md section 0b); it is taken from the landed
sibling GLOBAL leaf `model/effects/rf-rf-global2/rf_global2_model.py`, which
pinned it while citing the same `process()` block, and it is the complement
of the INSERT set ({all_fx, no_sends, scene_fx_only}) pinned by
`model/effects/rf-rf-bins12/rf_bins12_model.py`. Recorded as a named
re-verification item rather than presented as a fresh verified read.

FORM SCOPE ONLY (issue #62 / SXT-028j). This leaf models the extended-rack
bus wiring, the global3 -> global4 slot-order schedule, `fx_bypass` /
`fx_disable` gating, the per-slot instance lifecycle (patch-change reload,
slot-off, panic/reset), and the per-instance-state isolation of hosting TWO
concurrently-active global-FX instances on the master bus. It makes **no**
claim about any specific Surge FX algorithm's fidelity -- "algorithm
behavior stays with the per-algorithm leaves" (issue #62 scope note;
AGENTS.md). The per-slot "occupant" exercised here is a **synthetic TDF2
biquad primitive** (structure: the same Direct-Form-II-Transposed recurrence
every landed leaf's biquad stage uses -- Delay/Chorus's per-sample-lag
`Biquad` (model/effects/delay/delay_model.py), Reverb1's
instant-coefficient `biq_stage` (model/effects/reverb1/reverb1_fixed.py),
and the sibling routing leaves' `BiquadInstance` -- with coefficients
supplied as arbitrary control-plane stimulus, NOT derived from any concrete
Surge FX class's parameters). It exists only to give the routing/scheduling
claim a real, per-instance-stateful, tail-bearing arithmetic path to verify
order-sensitivity, state isolation, lifecycle behavior and tail continuation
against. No preset-support or algorithm-fidelity claim follows from it, and
it must never be reported as a substitute for a concrete occupant algorithm
under a support claim (issue #62 negative control: "Generic substitute").

Frozen word formats (this leaf; format-family-consistent with the SXT-023
table in model/effects/README.md and identical in family to the sibling
routing leaves so the routing forms can be compared directly):

  master-bus audio words   Q10.21 signed 32-bit   ("A_FMT"; matches the
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
routing leaf's kernel: `model_revision()` (sha256 of this file) is the
frozen-revision pin consumed by the RTL comparator and the stale-harness
negative control, so a sibling leaf's future edit must never be able to
change this leaf's frozen behavior without changing this leaf's own pin.

Per-instance state: one `GlobalSlotInstance` holds ONE `BiquadInstance`
(4 accumulator words: reg0/reg1 x {L,R}) plus its own `occupied` flag. The
two configured extended-rack slots (`ExtendedGlobalRack.slot3` = global3,
`.slot4` = global4) are two disjoint `GlobalSlotInstance` objects -- no
accumulator state is ever shared between them, even though both instances
run through the SAME arithmetic kernel class
(`BiquadInstance.process_sample`); this is exactly the "shared arithmetic,
independent per-instance state" contract (AGENTS.md; issue #62 "State"
section). This holds even when the two slots host the SAME FX class, which
the corpus really does exercise (`John Valentine/Strings/String
Contrabass.fxp` carries Airwindows in BOTH global3 and global4).

Declared control-plane boundary (one control word set per block, applied by
`apply_control()` BEFORE the audio block and independent of `fx_bypass` --
the engine's load/unload path is control-rate and runs whether or not the
audio stage is bypassed): `fx_bypass` (2-bit mode), `fx_disable` (16-bit
mask, engine bit layout; only bits 14/15 are consumed here), and per slot:
`occupied`, `reload` (a patch-change pulse -- `loadFx()`), and 5 biquad
coefficients (Q3.29). The upstream ring/live flag (`glob_in`) is the value
the global1 -> global2 segment threaded out; computing it is OUT of this
leaf's scope (it originates in `sc_state[0] || sc_state[1] || any(sendused)`
and is then modified by the upstream global slots) and it is supplied here
as a per-block boolean stimulus.

Instance lifecycle rule (FROZEN; identical in the model and the RTL):
  * `occupied` false                      -> instance released: registers
                                             cleared, stage no-ops.
  * `occupied` rising (unoccupied -> occupied), or `reload` pulse while
    occupied                              -> FRESH instance (`loadFx()`):
                                             THAT slot's registers are
                                             cleared and the new
                                             coefficients adopted; the
                                             sibling slot's history is
                                             untouched and the ring flag is
                                             NOT cleared (a patch change
                                             mid-tail does not silence the
                                             other slot's tail).
  * `occupied` steady and no `reload`     -> the coefficients are adopted
                                             WITHOUT clearing state (an
                                             abrupt parameter change; the
                                             engine's own per-parameter
                                             smoothing is algorithm-leaf
                                             scope -- declared omission).
  * `panic_reset()`                       -> both instances cleared and the
                                             rack's own ring memory dropped
                                             (the engine's all-notes-off /
                                             suspend path). Occupancy (the
                                             loaded patch) is NOT changed.

Declared scope omissions (fail-closed):
  * The global1 -> global2 segment itself (the landed sibling leaf
    `model/effects/rf-rf-global2/`), the scene insert buses (`rf-ains*` /
    `rf-bins*`, `rf-rf-bins12` landed) and the send buses with their
    `return_level` / per-scene `send_level` smoothing (send-form `rf-send*`
    leaves). This leaf models exactly the pinned-source
    `roles: [global3, global4]` scope.
  * The master bus's own upstream summation (scene buses + send returns) and
    everything downstream of the global chain.
  * Per-sample coefficient smoothing/ramping into the occupant
    (algorithm-leaf scope).
  * Any concrete Surge FX algorithm's own ring-out DECISION: this occupant
    reports ringing exactly while `indata` is true (see
    `GlobalSlotInstance.process_ringout`); its ARITHMETIC tail (nonzero
    output after the input goes silent, straight out of the TDF2 registers)
    is real and IS exercised, but a tail-bearing occupant's own
    `process_ringout` return policy is algorithm-leaf scope.
  * The exact queue-drain timing of `enqueueFXOff()` inside the engine: this
    leaf's lifecycle applies slot-off at the control-rate pass preceding a
    block, which is a DECLARED contract of the model (and of the RTL, which
    matches it exactly), not a verified read of the engine's queue.
"""

import hashlib
import os

BLOCK = 32

A_FRAC, A_BITS = 21, 32     # Q10.21 master-bus audio words
C_FRAC, C_BITS = 29, 32     # Q3.29 biquad coefficients (instant)
R_BITS = 80                 # TDF2 accumulator width (Reverb1 REG_LIM class)
REG_LIM = 1 << (R_BITS - 1)

FXB_ALL_FX, FXB_NO_SENDS, FXB_SCENE_FX_ONLY, FXB_NO_FX = 0, 1, 2, 3

# SurgeStorage.h fxslot_positions (re-derivable in-repo from
# tools/export_normalized_graphs.py FX_ROLES / corpus/normalized/graphs.jsonl)
FXSLOT_GLOBAL3, FXSLOT_GLOBAL4 = 14, 15

# The bypass modes in which the GLOBAL stage runs -- inherited from the
# landed sibling GLOBAL leaf (model/effects/rf-rf-global2/), see the module
# docstring's "BYPASS-MODE PARTITION" note.
GLOBAL_ACTIVE_MODES = (FXB_ALL_FX, FXB_NO_SENDS)

# The full global chain, in the pinned slot order. This leaf owns the last
# two entries; the first two are the landed sibling leaf's scope.
GLOBAL_CHAIN_ORDER = ("global1", "global2", "global3", "global4")
UPSTREAM_SEGMENT_ROLES = ("global1", "global2")
THIS_LEAF_ROLES = ("global3", "global4")

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


class GlobalSlotInstance:
    """Per-instance state for ONE extended-rack global-FX slot occupant.
    `occupied` mirrors `fx[v] != nullptr`; disabling is a separate,
    routing-level control (`ExtendedGlobalRack.fx_disable`), matching the
    engine's two independent gates (slot loaded vs. slot disabled)."""

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
        `indata` (the ring/live flag threaded in from upstream) is true,
        process every sample of the block IN PLACE on the master bus and
        report still-ringing; otherwise pass the bus through untouched and
        report not-ringing. This occupant declares no ring-out policy of its
        own, so its own ring decision reduces to `indata` exactly (a
        tail-bearing occupant's own policy is algorithm-leaf scope); its
        ARITHMETIC tail -- nonzero output after the input goes silent,
        straight out of the TDF2 registers -- is real and is what the tail
        acceptance case and the dropped-tail negative control exercise."""
        if not indata:
            return list(in_l), list(in_r), False
        out_l = [0] * len(in_l)
        out_r = [0] * len(in_r)
        for k in range(len(in_l)):
            out_l[k] = self.biquad.process_sample(in_l[k], 0)
            out_r[k] = self.biquad.process_sample(in_r[k], 1)
        return out_l, out_r, True


class ExtendedGlobalRack:
    """The extended rack half of the master global-FX chain: TWO
    concurrently-active global slot instances (global3, global4) wired in
    SERIES, IN PLACE, on the master output bus, reproducing the tail half of
    SurgeSynthesizer::process()'s "apply global effects" schedule.
    Per-instance state: `slot3.biquad` and `slot4.biquad` are two
    independent `BiquadInstance` objects; state is never pooled (AGENTS.md;
    issue #62 acceptance "Per-instance state")."""

    def __init__(self):
        self.slot3 = GlobalSlotInstance("global3", FXSLOT_GLOBAL3)
        self.slot4 = GlobalSlotInstance("global4", FXSLOT_GLOBAL4)
        self.fx_bypass = FXB_ALL_FX
        self.fx_disable = 0     # 16-bit mask, engine bit layout
        self.glob_ring = False  # this rack's own memory of the ring flag

    # ---------------------------------------------------------- control
    def apply_control(self, fx_bypass, fx_disable,
                      occupied3, reload3, coeffs3,
                      occupied4, reload4, coeffs4):
        """Control-rate pass, applied BEFORE the audio block and independent
        of `fx_bypass` (the engine's load/unload path is control-rate).
        Implements the frozen instance-lifecycle rule -- see the module
        docstring."""
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
        self.glob_ring = False

    def slot_disabled(self, bit):
        return bool((self.fx_disable >> bit) & 1)

    # ------------------------------------------------------------ audio
    def process_block(self, in_l, in_r, glob_in):
        """Returns (out_l, out_r, glob_out) for the master bus.

        Mirrors the tail half of process()'s "apply global effects" block:
            if fx_bypass in {ALL_FX, NO_SENDS}:
                glob = glob_in            # as the global1->global2 segment
                for (slot, bit) in (global3, 14), (global4, 15):
                    if slot.occupied and not fx_disable_bit(bit):
                        (bus, glob) = slot.process_ringout(bus, glob)
            else:
                bus unchanged; the ring state is NOT computed/updated (the
                engine never enters the block, so the flag simply passes
                through this stage untouched).

        `in_l`/`in_r`/`glob_in` are the master bus and ring flag as the
        UPSTREAM global1 -> global2 segment left them (the landed sibling
        leaf model/effects/rf-rf-global2/). Computing them is out of scope.
        """
        if self.fx_bypass not in GLOBAL_ACTIVE_MODES:
            self.glob_ring = bool(glob_in)
            return list(in_l), list(in_r), glob_in
        bus_l, bus_r = list(in_l), list(in_r)
        glob = glob_in
        for slot in (self.slot3, self.slot4):
            if slot.occupied and not self.slot_disabled(slot.slot_bit):
                bus_l, bus_r, glob = slot.process_ringout(bus_l, bus_r, glob)
        self.glob_ring = bool(glob)
        return bus_l, bus_r, glob

    def checkpoint(self):
        """Exact-equality checkpoint tuple (RTL-vs-model comparator)."""
        return (
            tuple(self.slot3.biquad.reg0), tuple(self.slot3.biquad.reg1),
            tuple(self.slot4.biquad.reg0), tuple(self.slot4.biquad.reg1),
        )
