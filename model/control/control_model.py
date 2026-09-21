"""SXT-021 deterministic timed control model.

This is the REFERENCE for `rtl/control/`: the RTL must reproduce this model's
schedule decisions and queue states EXACTLY (integer equality at every
declared checkpoint) and its stereo output byte-for-byte.

Declared conventions (normative; see model/control/README.md):

- Reset policy (deterministic):
    * power-on: block counter = 0, queue empty, all voices free, patch_id = 0,
      allocation sequence counter = 0.
    * patch-load (a `patch_change` event): voices force-cleared, pending
      queued events flushed (each recorded, never silent), patch_id set. The
      block counter keeps running (audio continuity is never re-clocked).
- Audio framing: 48 kHz, block size 32 samples (engine pin
  `fx_frame_block_size`, model/resources/params.py). One control pass per
  block, one stereo output block per block.
- Scheduling granularity (SXT-012 convention): event timestamps are integer
  samples at 48 kHz; an event with timestamp t is applied at the start of
  block ceil(t/32) — events quantize UP to the block, never down. An event is
  therefore never applied before its timestamp; event-to-output latency is
  bounded by 31 alignment samples (+ the block duration to the first DAC
  frame that follows).
- Event queue: FIFO, depth 16 (`event_queue_depth`, model/resources/params.py;
  corpus-derived). Push order = arrival (input stream) order; the stream must
  be nondecreasing in t (fail-closed otherwise). A push onto a full queue is
  an EXPLICIT detected drop (`queue_overflow`), never silent corruption.
- Declared per-block event reserve: 8 events (SXT-016 scheduler probe row:
  worst coincident events per frame = 8, fixtures-derived). A block whose
  arrivals exceed 8 is flagged `event_reserve_exceeded`; the surplus spills
  to following blocks (bounded by queue capacity) — the worst-case schedule
  accounting does not close for such renders and the record says so.
- Note allocation/stealing (declared policy v1): 8 scene-voice slots (plan
  section 3 "8 scene voices"; a DRAFT-profile revision point — bundle B4's
  working hypothesis is pool 16). note_on takes the LOWEST free slot; with no
  free slot it steals the OLDEST active voice (smallest allocation sequence
  number; tie -> lowest slot index). note_off releases the OLDEST active
  voice holding that note; with none, a recorded no-op.
- Patch change semantics v1 (declared): HARD SWITCH at the target block
  boundary — voices force-cleared and queued events flushed, all recorded.
  Tail-then-switch is the declared profile revision point for SXT-025 wet
  presets; it is NOT implemented under this v1 contract.
- Engine slot: occupied by a clearly-named STUB (`engine_stub_counter.py`).
  No DSP claim of any kind.

Determinism: no clocks, no randomness, fixed iteration orders; identical
inputs give byte-identical traces and output recordings.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Declared constants (single source shared with rtl/control via control_pkg.sv)
# ---------------------------------------------------------------------------
SAMPLE_RATE_HZ = 48000        # engine pin (model/resources/params.py)
BLOCK_SIZE = 32               # fx_frame_block_size (engine constant)
QUEUE_DEPTH = 16              # event_queue_depth (corpus_derived)
N_VOICES = 8                  # plan section 3 scene voices (v1 declaration)
EV_RESERVE_PER_BLOCK = 8      # SXT-016 scheduler probe worst coincident events
MAX_TIMESTAMP = (1 << 31) - 1  # 32-bit input timestamp field
MAX_BLOCKS = (1 << 16)        # 16-bit target-block field in the RTL queue word

# Event type codes (shared encoding with the RTL)
EVENT_NOTE_ON = 0
EVENT_NOTE_OFF = 1
EVENT_CC = 2
EVENT_PITCH_BEND = 3
EVENT_CHANNEL_PRESSURE = 4
EVENT_PATCH_CHANGE = 5
EVENT_TEMPO = 6

TYPE_NAMES = {
    EVENT_NOTE_ON: "note_on",
    EVENT_NOTE_OFF: "note_off",
    EVENT_CC: "cc",
    EVENT_PITCH_BEND: "pitch_bend",
    EVENT_CHANNEL_PRESSURE: "channel_pressure",
    EVENT_PATCH_CHANGE: "patch_change",
    EVENT_TEMPO: "tempo",
}
NAME_TO_TYPE = {v: k for k, v in TYPE_NAMES.items()}

# "no voice slot touched" sentinel (shared encoding with the RTL E lines;
# the RTL 5-bit slot field cannot hold negative values)
SLOT_NONE = 31

# Decision status codes (shared encoding with the RTL E lines)
STATUS_ALLOC = 0            # note_on onto a free slot
STATUS_STEAL = 1            # note_on stole the oldest active voice
STATUS_RELEASE = 2          # note_off released a voice
STATUS_NO_VOICE = 3         # note_off with no matching voice (recorded no-op)
STATUS_CC = 4               # recorded; consumed by real DSP later
STATUS_PITCH_BEND = 5       # recorded
STATUS_CHANNEL_PRESSURE = 6  # recorded
STATUS_TEMPO = 7            # recorded
STATUS_PATCH_CHANGE = 8     # hard switch executed (flush count carried)


def quantize_block(t: int) -> int:
    """Block that owns timestamp t: ceil(t/BLOCK_SIZE) — quantize UP."""
    if t < 0:
        raise ValueError("negative timestamp")
    return (t + BLOCK_SIZE - 1) // BLOCK_SIZE


def sample_of_block(b: int) -> int:
    return b * BLOCK_SIZE


@dataclass
class Event:
    """One input control event (arrival order = stream order)."""
    seq: int          # arrival index (global)
    t: int            # timestamp, integer samples at 48 kHz
    type: int         # EVENT_* code
    p1: int           # note / controller / value / patch id (16-bit field)
    p2: int           # velocity / value (16-bit field)

    @property
    def target_block(self) -> int:
        return quantize_block(self.t)

    def to_word(self) -> int:
        """80-bit packed word: t[79:48] type[47:40] p1[39:24] p2[23:8] rsvd[7:0]."""
        return ((self.t & 0xFFFFFFFF) << 48) | ((self.type & 0xFF) << 40) \
            | ((self.p1 & 0xFFFF) << 24) | ((self.p2 & 0xFFFF) << 8)


@dataclass
class Decision:
    """One applied (dispatched) event with its schedule outcome."""
    seq: int
    t: int
    type: int
    p1: int
    p2: int
    status: int
    slot: int          # voice slot touched (note_on/off); -1 otherwise
    steal: int         # 1 when an active voice was stolen
    flushes: int       # events flushed by a patch_change, else 0
    applied_sample: int  # first sample index the decision is effective at

    @property
    def latency_samples(self) -> int:
        return self.applied_sample - self.t

    def as_row(self) -> Dict:
        return {"seq": self.seq, "t": self.t, "type": self.type,
                "type_name": TYPE_NAMES[self.type], "p1": self.p1,
                "p2": self.p2, "status": self.status, "slot": self.slot,
                "steal": self.steal, "flushes": self.flushes,
                "applied_sample": self.applied_sample,
                "latency_samples": self.latency_samples}


@dataclass
class Voice:
    active: bool = False
    note: int = 0
    seq: int = 0        # allocation sequence number (steal order key)


@dataclass
class QueueState:
    """Event queue (FIFO, depth QUEUE_DEPTH)."""
    items: List[Event] = field(default_factory=list)

    def push(self, ev: Event) -> Optional[Event]:
        """Returns a drop record if the push overflowed (explicit, never silent)."""
        if len(self.items) >= QUEUE_DEPTH:
            return ev  # dropped: bounded overload detection point
        self.items.append(ev)
        return None

    def pop_eligible(self, block: int) -> Optional[Event]:
        if self.items and self.items[0].target_block <= block:
            return self.items.pop(0)
        return None


class ControlModel:
    """Block-stepped deterministic control plane (reference for the RTL)."""

    def __init__(self, voice_pool: int = N_VOICES):
        if voice_pool != N_VOICES:
            raise ValueError(
                "voice_pool must equal the declared v1 pool %d "
                "(profile revision point, not a knob)" % N_VOICES)
        self.power_on_reset()

    # ---------------------------------------------------------- reset policy
    def power_on_reset(self) -> None:
        """Deterministic power-on state (see module docstring)."""
        self.block = 0
        self.patch_id = 0
        self.alloc_seq = 0
        self.event_seq = 0
        self.voices: List[Voice] = [Voice() for _ in range(N_VOICES)]
        self.queue = QueueState()

    @property
    def active_count(self) -> int:
        return sum(1 for v in self.voices if v.active)

    # ------------------------------------------------------ event dispatch
    def _alloc_free_or_steal(self, note: int) -> Tuple[int, int]:
        """Declared v1 policy: lowest free slot, else steal oldest active."""
        for i, v in enumerate(self.voices):
            if not v.active:
                v.active, v.note, v.seq = True, note, self.alloc_seq
                self.alloc_seq += 1
                return i, STATUS_ALLOC
        victim = min((v.seq, i) for i, v in enumerate(self.voices) if v.active)
        i = victim[1]
        self.voices[i].note, self.voices[i].seq = note, self.alloc_seq
        self.alloc_seq += 1
        return i, STATUS_STEAL

    def _release_oldest(self, note: int) -> Tuple[int, int]:
        best: Optional[Tuple[int, int]] = None
        for i, v in enumerate(self.voices):
            if v.active and v.note == note:
                if best is None or v.seq < best[0]:
                    best = (v.seq, i)
        if best is None:
            return SLOT_NONE, STATUS_NO_VOICE
        i = best[1]
        self.voices[i] = Voice()
        return i, STATUS_RELEASE

    def dispatch(self, ev: Event, effective_block: int) -> Decision:
        # effective at the first sample of the DISPATCHING block: equal to
        # the quantized target normally, later under burst spill
        applied_sample = sample_of_block(effective_block)
        d = Decision(seq=ev.seq, t=ev.t, type=ev.type, p1=ev.p1, p2=ev.p2,
                     status=-1, slot=SLOT_NONE, steal=0, flushes=0,
                     applied_sample=applied_sample)
        if ev.type == EVENT_NOTE_ON:
            d.slot, d.status = self._alloc_free_or_steal(ev.p1)
            d.steal = 1 if d.status == STATUS_STEAL else 0
        elif ev.type == EVENT_NOTE_OFF:
            d.slot, d.status = self._release_oldest(ev.p1)
        elif ev.type == EVENT_CC:
            d.status = STATUS_CC
        elif ev.type == EVENT_PITCH_BEND:
            d.status = STATUS_PITCH_BEND
        elif ev.type == EVENT_CHANNEL_PRESSURE:
            d.status = STATUS_CHANNEL_PRESSURE
        elif ev.type == EVENT_TEMPO:
            d.status = STATUS_TEMPO
        elif ev.type == EVENT_PATCH_CHANGE:
            # v1 semantics: HARD SWITCH at the block boundary (declared).
            d.flushes = len(self.queue.items)
            for i in range(N_VOICES):
                self.voices[i] = Voice()
            self.queue.items = []
            self.patch_id = ev.p1
            d.status = STATUS_PATCH_CHANGE
        else:
            raise ValueError("unknown event type %d" % ev.type)
        return d

    # ---------------------------------------------------------- block step
    def step_block(self, arrivals: List[Event]) -> Dict:
        """One audio block: push arrivals at their exact samples -> dispatch
        -> snapshot. (Render happens outside; the caller supplies the queue
        state changes and the engine reads `snapshot_after`.)

        Sample-faithful host model (matches the RTL per-sample pushes
        exactly, including queue-overflow timing): an arrival whose t is
        exactly the block boundary is pushed BEFORE the control pass; an
        arrival later in the block is pushed where it arrives — after the
        pass — and pends in the queue for its target block (it can never be
        dispatched by this block: quantize-up guarantees target > b).
        """
        b = self.block
        lo = sample_of_block(b)
        drops: List[Dict] = []
        statuses: List[str] = []

        def _push_all(evs: List[Event]) -> None:
            for ev in evs:
                drop = self.queue.push(ev)
                if drop is not None:
                    drops.append({"seq": drop.seq, "t": drop.t,
                                  "type": drop.type,
                                  "type_name": TYPE_NAMES[drop.type],
                                  "p1": drop.p1, "p2": drop.p2})

        pre = [e for e in arrivals if e.t == lo]
        post = [e for e in arrivals if e.t != lo]
        _push_all(pre)

        if len(arrivals) > EV_RESERVE_PER_BLOCK:
            statuses.append("event_reserve_exceeded")

        decisions: List[Decision] = []
        for _ in range(EV_RESERVE_PER_BLOCK):
            ev = self.queue.pop_eligible(b)
            if ev is None:
                break
            decisions.append(self.dispatch(ev, b))
        spilled = sum(1 for e in self.queue.items if e.target_block <= b)
        if spilled:
            statuses.append("spill_pending")

        # checkpoint = end of the control pass (the RTL registers its
        # snapshot here; arrivals later in the block are queued after it
        # and first appear in the next block's snapshot)
        snapshot = {
            "qcount": len(self.queue.items),
            "patch_id": self.patch_id,
            "active_count": self.active_count,
            "voices": [{"slot": i, "active": v.active, "note": v.note,
                        "seq": v.seq} for i, v in enumerate(self.voices)],
        }

        # arrivals later in the block land in the queue now (never applied
        # by this block; may overflow here exactly as the RTL does)
        _push_all(post)
        if drops:
            statuses.append("queue_overflow")

        self.block += 1
        return {"b": b, "pushes": len(arrivals), "drops": drops,
                "statuses": statuses,
                "decisions": [d.as_row() for d in decisions],
                "snapshot_after": snapshot}


def render_sequence(seq: Dict, engine, voice_pool: int = N_VOICES) -> Tuple[Dict, bytes, Dict]:
    """Render a control sequence through the model + engine.

    Returns (trace, output_bytes, summary). The engine slot is a STUB under
    this issue (`engine_stub_counter.py`); passing any engine object keeps
    the control plane testable against the negative-control silent stub.

    Fail-closed input gates (documented conventions):
      * schema identity, rates, block size, voice pool;
      * events nondecreasing in t (FIFO-order guarantee shared with the RTL);
      * timestamps inside the rendered block range and below 2^31;
      * known event types; p1/p2 within the 16-bit field.
    """
    if seq.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if seq.get("sample_rate") != SAMPLE_RATE_HZ:
        raise ValueError("sample_rate must be the 48 kHz engine pin")
    if seq.get("block_size") != BLOCK_SIZE:
        raise ValueError("block_size must be the 32-sample engine pin")
    blocks = seq.get("blocks")
    if not isinstance(blocks, int) or blocks <= 0 or blocks > MAX_BLOCKS:
        raise ValueError("blocks out of range")
    events: List[Event] = []
    for raw in seq.get("events", []):
        t = raw["t"]
        name = raw["type"]
        if name not in NAME_TO_TYPE:
            raise ValueError("unknown event type %r" % name)
        p1, p2 = int(raw.get("p1", 0)), int(raw.get("p2", 0))
        if not (0 <= t <= MAX_TIMESTAMP):
            raise ValueError("timestamp out of 32-bit range")
        if quantize_block(t) >= blocks:
            raise ValueError("event t=%d lands beyond the rendered range" % t)
        if quantize_block(t) >= MAX_BLOCKS:
            raise ValueError("target block exceeds the 16-bit RTL field")
        if not (0 <= p1 <= 0xFFFF and 0 <= p2 <= 0xFFFF):
            raise ValueError("p1/p2 out of the 16-bit field")
        if name in ("note_on", "note_off") and p1 > 127:
            raise ValueError("note out of MIDI range")
        events.append(Event(seq=len(events), t=t, type=NAME_TO_TYPE[name],
                            p1=p1, p2=p2))
    for a, b_ in zip(events, events[1:]):
        if b_.t < a.t:
            raise ValueError("event stream not nondecreasing in t "
                             "(FIFO-order contract)")

    model = ControlModel(voice_pool=voice_pool)
    by_block: Dict[int, List[Event]] = {}
    for ev in events:
        by_block.setdefault(ev.t // BLOCK_SIZE, []).append(ev)

    out = bytearray()
    block_records = []
    underruns = 0
    max_latency = 0
    reserve_exceeded = 0
    overflow_blocks = 0
    flushed_total = 0
    for b in range(blocks):
        arrivals = by_block.get(b, [])
        rec = model.step_block(arrivals)
        # Continuous-output path: the engine slot must produce exactly one
        # stereo block per audio block (underrun = missing/partial block).
        s0 = sample_of_block(b)
        vcount = rec["snapshot_after"]["active_count"]
        frame = engine.process_block(b, vcount, s0)
        if frame is None or len(frame) != BLOCK_SIZE:
            underruns += 1
            frame = [(0, 0)] * BLOCK_SIZE  # explicit silence, recorded above
        for (l, r) in frame:
            out += l.to_bytes(2, "little") + r.to_bytes(2, "little")
        for d in rec["decisions"]:
            max_latency = max(max_latency, d["latency_samples"])
            flushed_total += d["flushes"]
        if "event_reserve_exceeded" in rec["statuses"]:
            reserve_exceeded += 1
        if "queue_overflow" in rec["statuses"]:
            overflow_blocks += 1
        rec["underruns"] = 0
        block_records.append(rec)

    trace = {
        "meta": {
            "sequence_id": seq.get("id"),
            "schema_version": 1,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "block_size": BLOCK_SIZE,
            "blocks": blocks,
            "voice_pool": N_VOICES,
            "queue_depth": QUEUE_DEPTH,
            "ev_reserve_per_block": EV_RESERVE_PER_BLOCK,
            "patch_change_semantics": "hard_switch_v1",
            "steal_policy": "oldest_active_lowest_index",
            "engine": engine.name,
            "granularity_note": "events quantize UP to the 32-sample block, "
                                "never down (SXT-012 convention)",
        },
        "blocks": block_records,
    }
    summary = {
        "blocks": blocks,
        "underruns": underruns,
        "drops_total": sum(len(r["drops"]) for r in block_records),
        "flushed_total": flushed_total,
        "max_latency_samples": max_latency,
        "reserve_exceeded_blocks": reserve_exceeded,
        "queue_overflow_blocks": overflow_blocks,
        "decisions_total": sum(len(r["decisions"]) for r in block_records),
    }
    return trace, bytes(out), summary
