"""SXT-028d frozen fixed-point model -- routing form: Global FX slots 1+2
series bus (the second concurrent global-FX instance).

Structure authority (READ + cited; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 -- no code
or tables copied):

  src/common/SurgeSynthesizer.cpp  process() -- the "apply global effects"
    block:
        if ((fx_bypass == fxb_all_fx) || (fx_bypass == fxb_no_sends)) {
            bool glob = sc_state[0] || sc_state[1];
            for (i = 0; i < n_send_slots; ++i) glob = glob || sendused[i];
            for (auto v : {fxslot_global1, fxslot_global2, fxslot_global3,
                           fxslot_global4})
                if (fx[v] && !(storage.getPatch().fx_disable.val.i & (1<<v)))
                    glob = fx[v]->process_ringout(output[0], output[1], glob);
        }
    -- in-place, SERIES chaining on the summed master bus; the per-slot
    `process_ringout` return value threads forward as the next slot's
    `indata` argument (the ring-out/tail-continuation contract).
  src/common/SurgeStorage.h -- `fxslot_positions` (fxslot_global1 = 6,
    fxslot_global2 = 7; global3/4 = 14/15, out of this leaf's `roles`),
    `fxb_*` bypass enum (fxb_all_fx=0, fxb_no_sends=1, fxb_scene_fx_only=2,
    fxb_no_fx=3), `n_fx_slots` = 16 (fx_disable bit width).
  src/common/dsp/effects/SurgeSSTFXAdapter.h + SurgeEffect.h -- instance
    construction/suspend per slot (`fx[v] == nullptr` <=> slot unoccupied;
    modeled here as `GlobalSlotInstance.occupied`).

FORM SCOPE ONLY (issue #56 / SXT-028d). This leaf models the bus wiring,
slot-order scheduling, `fx_bypass`/`fx_disable` gating, and the per-instance-
state isolation of hosting TWO concurrently-active global-FX slot instances
on the master output bus. It makes **no** claim about any specific Surge FX
algorithm's fidelity -- "algorithm behavior stays with the per-algorithm
leaves" (issue #56 scope note; AGENTS.md). The per-slot "occupant" exercised
here is a **synthetic TDF2 biquad primitive** (structure: the same
Direct-Form-II-Transposed recurrence every landed leaf's biquad stages use --
Delay/Chorus's per-sample-lag `Biquad` (model/effects/delay/delay_model.py)
and Reverb1's instant-coefficient `biq_stage` (model/effects/reverb1/
reverb1_fixed.py) -- with coefficients supplied as arbitrary control-plane
stimulus, NOT derived from any concrete Surge FX class's parameters). It is
used only to give the routing/scheduling claim a real, per-instance-stateful
arithmetic path to verify order-sensitivity, state isolation, and tail
(ring-out) propagation against; no preset-support or algorithm-fidelity
claim follows from it, and it must never be reported as a substitute for a
concrete occupant algorithm under a support claim (issue #56 negative
control: "Generic substitute").

Frozen word formats (this leaf; independent of, but format-family-
consistent with, the SXT-023 table in model/effects/README.md):

  master bus audio words   Q10.21 signed 32-bit   ("A_FMT"; matches the
                                                    Delay/EQ/Chorus bus scale)
  biquad coefficients      Q3.29  signed 32-bit    ("C_FMT"; block-constant,
                                                    NO per-sample lag -- a
                                                    declared scope omission,
                                                    coefficient smoothing is
                                                    algorithm-leaf scope)
  biquad TDF2 accumulator  80-bit signed           (Reverb1 REG_LIM
                                                    precedent: headroom for
                                                    arbitrary/adversarial
                                                    negative-control
                                                    coefficients without a
                                                    stability argument)

Arithmetic rules (FROZEN, self-contained -- mirrors model/effects/qmath.py's
round-half-up / saturating conventions without mutating its shared format
registry; reverb1_fixed.py precedent for a leaf-local kernel): exact
products, round-half-up `(p + 2**(s-1)) >> s`, saturating; no floating point
at audio run time.

Per-instance state: one `GlobalSlotInstance` holds ONE `BiquadInstance`
(4 accumulator words: reg0/reg1 x {L,R}) plus its own `occupied` flag. Two
configured global slots (`RoutingState.slot1`, `RoutingState.slot2`) are two
disjoint `GlobalSlotInstance` objects -- no accumulator state is ever shared
between them, even though both instances run through the SAME arithmetic
kernel class (`BiquadInstance.process_sample`); this is exactly the "shared
arithmetic, independent per-instance state" contract (AGENTS.md; issue #56
"State" section).

Declared control-plane boundary: `fx_bypass` (2-bit mode) and `fx_disable`
(16-bit mask, engine bit layout) are patch-level control registers, set
here per call for testability; each slot's 5 biquad coefficients (Q3.29)
and its `occupied` flag are per-instance control-plane inputs, loaded via
`GlobalSlotInstance.load()`. The upstream ring/live flag (`glob_in`, the
`sc_state[0] || sc_state[1] || any(sendused)` expression) is OUT of this
leaf's scope (scene/send routing is other `rf-*` leaves' scope) and is
supplied as a per-block synthetic boolean stimulus.

Declared scope omissions (fail-closed):
  * global3/global4 (SXT-028's `rf-global34` leaf, `roles: [global3,
    global4]`) -- this leaf models exactly the pinned-source `roles:
    [global2]` scope: the two-slot series segment ending at global2.
  * Per-sample coefficient smoothing/ramping into the occupant (algorithm-
    leaf scope; the real engine's own FX classes each declare their own
    ramp/lag behavior).
  * Any concrete Surge FX algorithm's own tail generation -- the occupant
    here has no extended tail of its own; `process_ringout`'s ringing
    decision for this occupant is exactly `indata` (see
    `GlobalSlotInstance.process_ringout`).
"""

import hashlib
import os

BLOCK = 32

A_FRAC, A_BITS = 21, 32     # Q10.21 master-bus audio words
C_FRAC, C_BITS = 29, 32     # Q3.29 biquad coefficients (instant)
R_BITS = 80                 # TDF2 accumulator width (Reverb1 REG_LIM class)
REG_LIM = 1 << (R_BITS - 1)

FXB_ALL_FX, FXB_NO_SENDS, FXB_SCENE_FX_ONLY, FXB_NO_FX = 0, 1, 2, 3
FXSLOT_GLOBAL1, FXSLOT_GLOBAL2 = 6, 7   # SurgeStorage.h fxslot_positions

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
    """Per-slot occupant TDF2 biquad: y[n] = b0*x[n] + reg0; reg0' = b1*x[n]
    - a1*y[n] + reg1; reg1' = b2*x[n] - a2*y[n] (Direct Form II Transposed,
    the structure every landed leaf's biquad stage shares -- Reverb1's
    `biq_stage`, Delay/Chorus's per-sample-lag `Biquad`). Block-constant
    (instant) coefficients; NO per-sample lag is modeled (declared scope
    omission -- see module docstring)."""

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
    """Per-instance state for ONE global-FX slot occupant. `occupied`
    mirrors `fx[v] != nullptr`; disabling is a separate, routing-level
    control (`RoutingState.fx_disable`), matching the engine's two
    independent gates (slot loaded vs. slot disabled)."""

    def __init__(self, name):
        self.name = name
        self.occupied = False
        self.biquad = BiquadInstance()
        self.ext_reads = 0     # declared 0: this occupant is register-only
        self.ext_writes = 0    # (on-chip); a real occupant owns its own
                                # external-memory accounting (SXT-015/016)

    def load(self, b0, b1, b2, a1, a2):
        self.occupied = True
        self.biquad.set_coeffs(b0, b1, b2, a1, a2)

    def unload(self):
        self.occupied = False
        self.biquad.reset()

    def process_ringout(self, in_l, in_r, indata):
        """Mirrors `Effect::process_ringout(L, R, indata) -> bool`: while
        `indata` (upstream live/ringing) is true, process every sample of
        the block and report still-ringing; otherwise pass the bus through
        untouched and report not-ringing. This occupant declares no
        extended tail of its own, so its own ring decision reduces to
        `indata` exactly (a tail-bearing occupant is algorithm-leaf scope)."""
        if not indata:
            return list(in_l), list(in_r), False
        out_l = [0] * len(in_l)
        out_r = [0] * len(in_r)
        for k in range(len(in_l)):
            out_l[k] = self.biquad.process_sample(in_l[k], 0)
            out_r[k] = self.biquad.process_sample(in_r[k], 1)
        return out_l, out_r, True


class RoutingState:
    """Two concurrently-active global-FX slot instances (global1, global2)
    wired in SERIES on the master output bus, exactly reproducing
    SurgeSynthesizer::process()'s "apply global effects" schedule. Per-
    instance state: `slot1.biquad` and `slot2.biquad` are two independent
    `BiquadInstance` objects; state is never pooled (AGENTS.md; issue #56
    acceptance "Per-instance state")."""

    def __init__(self):
        self.slot1 = GlobalSlotInstance("global1")
        self.slot2 = GlobalSlotInstance("global2")
        self.fx_bypass = FXB_ALL_FX
        self.fx_disable = 0   # 16-bit mask, engine bit layout

    def slot_disabled(self, bit):
        return bool((self.fx_disable >> bit) & 1)

    def process_block(self, in_l, in_r, glob_in):
        """Returns (out_l, out_r, glob_out).

        Mirrors process()'s "apply global effects" block exactly:
            if ((fx_bypass == fxb_all_fx) || (fx_bypass == fxb_no_sends)):
                glob = glob_in
                for (slot, bit) in (slot1, GLOBAL1), (slot2, GLOBAL2):
                    if slot.occupied and not fx_disable_bit(bit):
                        (bus, glob) = slot.process_ringout(bus, glob)
            else:
                bus unchanged; ring state NOT computed/updated (the engine
                never enters the block, so `glob` simply never exists for
                this call -- the caller's own ring tracking, out of this
                leaf's scope, is untouched)."""
        if self.fx_bypass not in (FXB_ALL_FX, FXB_NO_SENDS):
            return list(in_l), list(in_r), glob_in
        bus_l, bus_r = list(in_l), list(in_r)
        glob = glob_in
        for slot, bit in ((self.slot1, FXSLOT_GLOBAL1),
                          (self.slot2, FXSLOT_GLOBAL2)):
            if slot.occupied and not self.slot_disabled(bit):
                bus_l, bus_r, glob = slot.process_ringout(bus_l, bus_r, glob)
        return bus_l, bus_r, glob

    def checkpoint(self):
        """Exact-equality checkpoint tuple (RTL-vs-model comparator)."""
        return (
            tuple(self.slot1.biquad.reg0), tuple(self.slot1.biquad.reg1),
            tuple(self.slot2.biquad.reg0), tuple(self.slot2.biquad.reg1),
        )
