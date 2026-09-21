#!/usr/bin/env python3
"""SXT-025 integrated fixed pipeline (model side).

Compiled patch image -> control plane (SXT-021 event schedule) -> voice
stage (DECLARED host boundary, see README finding F-1) -> FX chain in the
preset's stored order (from the SXT-020 image, never a fixed global chain)
-> stereo output.

LEAF REUSE (no forked arithmetic):
  * control plane .... model/control/control_model.py (SXT-021, imported
    unmodified; the landed ControlModel/Event/quantize_block semantics)
  * effects .......... model/effects/{reverb1,eq,delay} (SXT-024/023 frozen
    models, imported unmodified; instantiated PER IMAGE SLOT with per-
    instance state)
  * voice ............ NOT RUN in this configuration (finding F-1: the
    landed SXT-022 Attacky-slice arithmetic cannot render the chosen
    preset's Sine/LP24 voice; per the no-fork rule this integration does
    not invent voice arithmetic). The declared leaf input boundary is used
    instead: the pinned engine's own all-off DRY bus of the SAME
    preset+sequence (the exact boundary the SXT-023/SXT-024 FX leaves were
    verified against). This makes the configuration ADAPTED -- it can
    never count as a supported preset (AGENTS.md).

Declared integration conversions (D-2, in addition to the leaves' own
frozen conventions):
  * Q10.21 -> s24 at a Reverb1 input: exact <<2 with a range assert
    (s24 = value*2^23 = (q21/2^21)*2^23); the q21 grid quantization vs the
    engine float path is part of the measured error.
  * s32i (Q4.28) -> Q10.21 at a Reverb1 send-return output: round-half-up
    at f=7, saturated; sub-Q10.21-LSB error, declared.
  * gains: send/return = amp_to_linear(level)^3 in Q13.18 (SXT-023 chain
    convention); master amplitude A = db_to_linear(volume) in Q13.18 with
    the engine getter value (loader-normalized, authoritative).
  * scene hardclip at +/-8.0 (Q10.21) after the insert phase, master
    hardclip after A -- structural, asserted inactive at fixture peaks
    (SXT-023 convention).

Everything is deterministic: no clocks, no randomness; identical inputs
give byte-identical renders and traces. Original to this repository
(Apache-2.0); the GPL engine is imported at render time only, by the
fixture tools.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))
sys.path.insert(0, os.path.join(REPO, "model", "control"))

from model.effects.qmath import (  # noqa: E402
    FRAC, to_q, qmul, qadd, sat, clip,
)
from model.effects.delay.delay_model import (  # noqa: E402
    DelayModel, DelayParams, A_FMT, G_FMT, BLOCK, db_to_linear_d,
)
from model.effects.eq.eq_model import EqModel, EqParams  # noqa: E402
from model.effects.reverb1 import coefficient_plane as cp  # noqa: E402
from model.effects.reverb1 import reverb1_fixed as rf  # noqa: E402
from model.control.control_model import (  # noqa: E402
    ControlModel, Event, NAME_TO_TYPE, BLOCK_SIZE, EV_RESERVE_PER_BLOCK,
)

SETTLE_BLOCKS = 240                      # the fixture harness's 0.25 s settle
HARDCLIP8 = 8 << FRAC[A_FMT]
SR = 48000

PHASE_ORDER = {"ains": 0, "bins": 1, "send": 2, "global": 3}


def q21_to_s24(v):
    """Declared conversion D-2a: Q10.21 -> s24, exact <<2, range-checked."""
    w = v << 2
    assert rf.S24_MIN <= w <= rf.S24_MAX, f"q21_to_s24 range: {v}"
    return w


def s32i_to_q21(v):
    """Declared conversion D-2b: s32i Q4.28 -> Q10.21, round-half-up, sat."""
    return sat((v + (1 << 6)) >> 7, "Q10.21")


class Reverb1Counted(rf.Reverb1Fixed):
    """Reverb1 leaf (unmodified arithmetic) + external-traffic counting.

    The counters mirror the SXT-024 transaction model: every tap/predelay
    read and write is one 32-bit external word. The leaf's own _rd/_wr path
    is used (attach_ext_memory hooks), so arithmetic is untouched.
    """

    def __init__(self, cp_plane, name):
        super().__init__(cp_plane)
        self.name = name
        self.frame_reads = 0
        self.frame_writes = 0
        self.total_reads = 0
        self.total_writes = 0
        self.attach_ext_memory(self._count_read, self._count_write)

    def _count_read(self, addr):
        self.frame_reads += 1
        self.total_reads += 1
        return self._ext(addr)

    def _count_write(self, addr, val):
        self.frame_writes += 1
        self.total_writes += 1
        self._ext(addr, val)

    def end_frame(self):
        r, w = self.frame_reads, self.frame_writes
        self.frame_reads = self.frame_writes = 0
        return r, w


class Instance:
    """One FX instance built from the compiled image + extracted inputs."""

    def __init__(self, spec, entry, name):
        self.slot = spec["slot"]
        self.role = spec["role"]
        self.phase = spec["phase"]
        self.phase_name = spec["phase_name"]
        self.order_in_phase = spec["order_in_phase"]
        self.engine_order = spec["engine_order"]
        self.kind = entry["type"]
        self.name = name
        self.send_slot = entry.get("send_slot")
        self.send_gain_f = entry.get("send_gain_f")
        self.return_f = entry.get("return_f")
        self.send_gain_q = None
        self.return_q = None
        self.model = None

    def finalize_gains(self):
        if self.kind in ("reverb1", "eq", "delay") and self.role.startswith("send"):
            self.send_gain_q = to_q(max(0.0, self.send_gain_f) ** 3, G_FMT)
            self.return_q = to_q(max(0.0, self.return_f) ** 3, G_FMT)


def amp_to_linear_fixed(f):
    return to_q(max(0.0, f) ** 3, G_FMT)


class IntegrationRun:
    """One deterministic end-to-end run over one sequence."""

    def __init__(self, image_path, inputs_path, dry_bus, frames, a_fixed=None):
        image = json.load(open(image_path))
        inputs = json.load(open(inputs_path))
        self.image = image
        self.inputs = inputs
        self._verify_image(image, inputs)

        body = image["body"]
        slots = {s["slot"]: s for s in body["derived"]["fx_section"]["slots"]}
        entries = {e["slot"]: e for e in inputs["fx_instances"]}
        self.instances = []
        for slot in sorted(entries):
            spec = slots[slot]
            entry = entries[slot]
            if spec["role"] != entry["role"] or \
                    spec["engine_order"] != entry["engine_order"]:
                raise ValueError(f"slot{slot}: image/inputs order mismatch")
            inst = Instance(spec, entry, f"fx{slot}")
            if entry["type"] == "reverb1":
                plane = cp.build(entry["params"],
                                 deactivated=entry["deactivated"])
                inst.plane = plane
                inst.model = Reverb1Counted(plane, inst.name)
            elif entry["type"] == "eq":
                inst.model = EqModel(EqParams(entry["params"]), inst.name)
                inst.model.initialize()
            elif entry["type"] == "delay":
                inst.model = DelayModel(DelayParams(entry["params"]), inst.name)
                inst.model.initialize()
            else:
                raise ValueError(entry["type"])
            inst.finalize_gains()
            self.instances.append(inst)
        # stored order == engine order (sorted by the image's engine_order)
        self.instances.sort(key=lambda i: i.engine_order)

        self.a_f = inputs["volume_f"]
        self.a_q = to_q(db_to_linear_d(self.a_f), G_FMT)
        if a_fixed is not None:
            self.a_q = a_fixed
        self.dry = dry_bus            # (2, N) float32, the engine dry bus
        self.frames = frames
        self.dry_deamped = self._deamp()

    # ------------------------------------------------------------ image ---
    def _verify_image(self, image, inputs):
        """Placement/order/gain invariants, fail-closed."""
        body = image["body"]
        fx = body["graph"]["fx_slots"]
        derived = body["derived"]["fx_section"]
        if derived["section_bypass_id"] != 0:
            raise ValueError("fx section bypassed")
        if derived["disable_mask_fxd"] != 0:
            raise ValueError("fx disable mask nonzero")
        # engine order is a pure function of the stored roles (engine-fixed
        # rank: ains1..4, bins1..4, sends 1..4, globals 1..4)
        def role_key(role):
            for name, ph in PHASE_ORDER.items():
                if role.startswith(name):
                    return (ph, int(role[len(name):]) - 1)
            raise ValueError(role)
        expect = sorted(
            (s["slot"] for s in derived["slots"]
             if s.get("enabled_by_fxd") and s.get("configured")),
            key=lambda s: role_key(fx[s]["r"]))
        got = sorted((e["slot"] for e in inputs["fx_instances"]),
                     key=lambda s: role_key(fx[s]["r"]))
        if expect != got:
            raise ValueError(f"enabled set mismatch image vs inputs: "
                             f"{expect} vs {got}")
        for s in derived["slots"]:
            if not (s.get("enabled_by_fxd") and s.get("configured")):
                continue
            role = fx[s["slot"]]["r"]
            ph, idx = role_key(role)
            if s["phase"] != ph or s["order_in_phase"] != idx + 1:
                raise ValueError(f"slot{s['slot']}: derived phase/order "
                                 f"disagree with the stored role {role}")
        # allocation: one external block per instance, per-instance never shared
        allocs = {a["slot"]: a for a in
                  body["derived"]["allocations"]["fx_instances"]}
        for e in inputs["fx_instances"]:
            a = allocs[e["slot"]]
            if a["region"] != "external_writable":
                raise ValueError(f"slot{e['slot']}: reverb state not external")

    def _deamp(self):
        """Fixture dry bus -> model input words (SXT-023 declared boundary):
        divide by the converged master amplitude, quantize to Q10.21."""
        import numpy as np

        a_d = float(np.float32(db_to_linear_d(self.a_f)))
        n = self.frames
        l = np.clip(np.round(self.dry[0][:n] / a_d * (1 << FRAC[A_FMT])),
                    -(1 << 30), (1 << 30) - 1).astype(np.int64)
        r = np.clip(np.round(self.dry[1][:n] / a_d * (1 << FRAC[A_FMT])),
                    -(1 << 30), (1 << 30) - 1).astype(np.int64)
        return l, r

    # ------------------------------------------------------- chain pass ---
    def process_block(self, in_l, in_r):
        """One 32-sample block through the image-ordered chain."""
        wl, wr = list(in_l), list(in_r)
        # 1. insert phases (ains, then bins) in stored order
        for inst in self.instances:
            if inst.phase_name not in ("scene_A_insert", "scene_B_insert"):
                continue
            wl, wr = self._run_instance(inst, wl, wr)
        # 2. scene hardclip (structural; asserted inactive at fixture peaks)
        wl = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wl]
        wr = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wr]
        out_l, out_r = wl, wr
        # 3. send bus phase, in stored order: send tap -> fx -> return sum
        for inst in self.instances:
            if inst.phase_name != "send_bus":
                continue
            sg, rl = inst.send_gain_q, inst.return_q
            sl = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wl]
            sr = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wr]
            if inst.kind == "reverb1":
                s24l = [q21_to_s24(v) for v in sl]
                s24r = [q21_to_s24(v) for v in sr]
                fl, fr = inst.model.process_block(s24l, s24r)
                fl = [s32i_to_q21(v) for v in fl]
                fr = [s32i_to_q21(v) for v in fr]
            else:
                fl, fr = inst.model.process_block(sl, sr)
            out_l = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                     for a, b in zip(out_l, fl)]
            out_r = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                     for a, b in zip(out_r, fr)]
        # 4. global insert phase
        for inst in self.instances:
            if inst.phase_name != "global_insert":
                continue
            out_l, out_r = self._run_instance(inst, out_l, out_r)
        # 5. master amplitude + hardclip
        out_l = [min(HARDCLIP8, max(-HARDCLIP8,
                                    qmul(self.a_q, x, G_FMT, A_FMT, A_FMT)))
                 for x in out_l]
        out_r = [min(HARDCLIP8, max(-HARDCLIP8,
                                    qmul(self.a_q, x, G_FMT, A_FMT, A_FMT)))
                 for x in out_r]
        return out_l, out_r

    def _run_instance(self, inst, wl, wr):
        if inst.kind == "reverb1":
            s24l = [q21_to_s24(v) for v in wl]
            s24r = [q21_to_s24(v) for v in wr]
            fl, fr = inst.model.process_block(s24l, s24r)
            return ([s32i_to_q21(v) for v in fl],
                    [s32i_to_q21(v) for v in fr])
        return inst.model.process_block(wl, wr)

    # ------------------------------------------------------------- run ----
    def events_from_sequence(self, seq):
        """Sequence JSON -> landed ControlModel events (fail-closed gates
        inherited from render_sequence's conventions; the integration keeps
        its own copy because render_sequence also renders a stub engine)."""
        events = []
        for raw in seq.get("events", []):
            name = raw["type"]
            if name not in NAME_TO_TYPE:
                raise ValueError(f"unknown event type {name!r}")
            t = raw["t"]
            p1 = raw.get("note", raw.get("controller", raw.get("value", 0)))
            p2 = raw.get("velocity", 0)
            events.append(Event(seq=len(events), t=t,
                                type=NAME_TO_TYPE[name], p1=p1, p2=p2))
        for a, b in zip(events, events[1:]):
            if b.t < a.t:
                raise ValueError("event stream not nondecreasing in t")
        return events

    def run(self, seq):
        """Full run: settle + body + tail. Returns a result record."""
        events = self.events_from_sequence(seq)
        notes = [e for e in events if e.type in (0, 1)]  # note_on/off
        last_t = max(e.t for e in notes) if notes else 0
        tail_s = float(seq.get("tail_s", 2.5))
        total_samples = last_t + int(tail_s * SR)
        total_blocks = -(-total_samples // BLOCK_SIZE)

        # control plane on its OWN timeline: block 0 = the first post-settle
        # block (the fixture harness's convention: events quantize UP from
        # t=0 at the first rendered block). The FX chain runs a separate
        # settle+body block index; record i of the control timeline is the
        # schedule for FX block SETTLE_BLOCKS + i.
        control = ControlModel()
        by_block = {}
        for ev in events:
            by_block.setdefault(ev.t // BLOCK_SIZE, []).append(ev)
        control_rows = []
        max_latency = 0
        reserve_exceeded = 0
        worst_events_per_block = 0
        last_noteoff_applied = None
        for cb in range(total_blocks):
            rec = control.step_block(by_block.get(cb, []))
            rec["b"] = cb
            for d in rec["decisions"]:
                max_latency = max(max_latency, d["latency_samples"])
                if d["type"] == 1:  # note_off
                    last_noteoff_applied = d["applied_sample"]
            if rec["pushes"]:
                worst_events_per_block = max(worst_events_per_block,
                                             rec["pushes"])
            if "event_reserve_exceeded" in rec["statuses"]:
                reserve_exceeded += 1
            control_rows.append(rec)

        n_total = SETTLE_BLOCKS + total_blocks
        frames_padded = n_total * BLOCK_SIZE
        model_out = [[0.0] * (frames_padded) for _ in range(2)]
        for b in range(n_total):
            lo = (b - SETTLE_BLOCKS) * BLOCK_SIZE
            if b >= SETTLE_BLOCKS and lo < self.frames:
                il = [int(self.dry_deamped[0][lo + k]) if lo + k < self.frames
                      else 0 for k in range(BLOCK_SIZE)]
                ir = [int(self.dry_deamped[1][lo + k]) if lo + k < self.frames
                      else 0 for k in range(BLOCK_SIZE)]
            else:
                il = [0] * BLOCK_SIZE
                ir = [0] * BLOCK_SIZE
            ol, orr = self.process_block(il, ir)
            for inst in self.instances:
                if isinstance(inst.model, Reverb1Counted):
                    inst.model.end_frame()
            if b >= SETTLE_BLOCKS:
                model_out[0][b * BLOCK_SIZE:(b + 1) * BLOCK_SIZE] = [
                    v / float(1 << FRAC[A_FMT]) for v in ol]
                model_out[1][b * BLOCK_SIZE:(b + 1) * BLOCK_SIZE] = [
                    v / float(1 << FRAC[A_FMT]) for v in orr]

        result = {
            "sequence_id": seq.get("id"),
            "blocks_total": n_total,
            "blocks_rendered": total_blocks,
            "settle_blocks": SETTLE_BLOCKS,
            "frames": self.frames,
            "tail_s": tail_s,
            "last_note_event_t": last_t,
            "last_noteoff_applied_sample": last_noteoff_applied,
            "max_event_latency_samples": max_latency,
            "worst_events_per_block": worst_events_per_block,
            "reserve_exceeded_blocks": reserve_exceeded,
            "control_rows": control_rows,
            "instances": [
                {"slot": i.slot, "role": i.role, "kind": i.kind,
                 "phase": i.phase_name, "engine_order": i.engine_order,
                 "send_gain_q": i.send_gain_q, "return_q": i.return_q,
                 "ext_reads": getattr(i.model, "total_reads", 0),
                 "ext_writes": getattr(i.model, "total_writes", 0)}
                for i in self.instances],
        }
        # trim to the fixture window (drop the settle), keep the full tail
        out = [[row[SETTLE_BLOCKS * BLOCK_SIZE:
                     SETTLE_BLOCKS * BLOCK_SIZE + self.frames]]
               for row in model_out]
        result["wet_l"] = out[0][0]
        result["wet_r"] = out[1][0]
        return result
