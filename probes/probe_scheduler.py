"""SXT-016 probe: control/scheduler overhead per output frame.

CANDIDATE-ARITHMETIC COST ESTIMATOR for the per-frame control path:
event queue processing, voice allocation search, and fixed per-frame
bookkeeping (scene LFO tick, audio DMA handshake, mixer bookkeeping).

Event-rate inputs (committed fixtures, SXT-012 library):
fixtures/sequences/*.json -- events carry tick times (480 ticks/quarter)
with tempo events; tick->frame conversion is computed per tempo segment
at the fixture's own BPM. The worst observed coincident burst in one
frame is 8 simultaneous note-ons (seq-poly-8-v1 at t=0), matching the
SXT-015 event model (max_coincident_events=8,
peak_events_per_second=13.333333 from the same library) -- reconciled
and re-derived here rather than trusted.

Structure citations (file-level, read from the pinned tree; no code
copied): surge@58914e59 src/common/SurgeSynthesizer.cpp (processControl/
processThread voice allocation and event handling; MIDI queue drains
bounded per block), src/common/SurgeVoice.cpp (voice allocation/
envelope trigger; calc_ctrldata modrouting loop). SXT-015 event model:
model/resources/params.py event_queue_depth=16.

Per-event and per-frame costs are NAMED CANDIDATE SCHEDULES (counted op
lists), not measurements. Replaces the SXT-015 cyc_event_frame
placeholder and provides the control/transfer/contention split the
plan-section-5 closure formula subtracts before DSP.
"""
import glob
import json
import os

from .common import (CLOCK_CANDIDATES_HZ, FS_HZ, OpCounter, TECH, closure,
                     op_cycles)

PROBE = "probe_scheduler"
SEQ_DIR = os.path.join("fixtures", "sequences")
TICKS_PER_QUARTER = 480
DEFAULT_BPM = 120.0

CITES = [
    "surge@58914e59 src/common/SurgeSynthesizer.cpp (processControl: MIDI "
    "event drain and dispatch per block; voice allocation/stealing)",
    "surge@58914e59 src/common/SurgeVoice.cpp (::calc_ctrldata: per-voice "
    "LFO + envelope + modrouting evaluation; allocation on note-on)",
    "fixtures/sequences/*.json (SXT-012 library, committed)",
    "SXT-015 model/resources/params.py (event_queue_depth=16; event model)",
]


def load_event_stats():
    """Re-derive worst-case event statistics from the fixture library.

    Deterministic. Returns dict with max coincident events in one frame,
    peak events in any 1-second window, and the source file list.
    """
    stats = {"max_coincident_per_frame": 0,
             "max_events_per_second_window": 0,
             "total_events": 0,
             "files": []}
    for path in sorted(glob.glob(os.path.join(SEQ_DIR, "*.json"))):
        doc = json.load(open(path))
        events = doc["events"] if isinstance(doc, dict) else doc
        stats["files"].append(os.path.basename(path))
        stats["total_events"] += len(events)
        # tick -> seconds, honoring tempo events (sorted by tick)
        tempos = sorted([(e["t"], e["bpm"]) for e in events
                         if e.get("type") == "tempo"])
        frames = []
        for e in events:
            if e.get("type") == "tempo":
                continue
            t = e["t"]
            sec = 0.0
            last_tick, last_bpm, last_sec = 0, DEFAULT_BPM, 0.0
            for tt, bpm in tempos:
                if tt >= t:
                    break
                sec = last_sec + (tt - last_tick) / TICKS_PER_QUARTER \
                    * 60.0 / last_bpm
                last_tick, last_bpm, last_sec = tt, bpm, sec
            sec = last_sec + (t - last_tick) / TICKS_PER_QUARTER \
                * 60.0 / last_bpm
            frames.append(int(sec * FS_HZ))
        if frames:
            per_frame = {}
            for f in frames:
                per_frame[f] = per_frame.get(f, 0) + 1
            stats["max_coincident_per_frame"] = max(
                stats["max_coincident_per_frame"], max(per_frame.values()))
            per_sec = {}
            for f in frames:
                per_sec[f // FS_HZ] = per_sec.get(f // FS_HZ, 0) + 1
            stats["max_events_per_second_window"] = max(
                stats["max_events_per_second_window"],
                max(per_sec.values()))
    return stats


def per_event_ops(o):
    """Named candidate schedule for one event (note-on worst case)."""
    o.add(32)   # queue pop + timestamp compare
    o.add(32)
    o.cmp()
    for _ in range(32):     # voice pool allocation search (worst 32 entries)
        o.cmp()
        o.add(8)
    for _ in range(8):      # envelope + LFO trigger init writes
        o.add(32)
    for _ in range(12):     # param routing / mixer refresh ops
        o.add(32)
    o.mul(32)


def per_frame_control_ops(o):
    """Fixed per-frame control path (named schedule)."""
    for _ in range(32):     # voice pool scan (active flags)
        o.cmp()
    for _ in range(6):     # scene LFO tick (6 SLFO instances)
        o.mul(32)
        o.add(32)
    for _ in range(8):      # audio DMA handshake + FIFO pointers
        o.add(16)
    for _ in range(20):     # mixer/VCA/bookkeeping ops
        o.add(32)


TRANSFER_CYCLES_PER_FRAME = 8   # A-CTL-1: stereo output word push (named)


def run(outdir):
    from .emit import build_record, write_record
    stats = load_event_stats()
    paths = []
    for mult in ("M18", "M32"):
        oe = OpCounter()
        per_event_ops(oe)
        ev_cycles = op_cycles(oe, mult)
        oc = OpCounter()
        per_frame_control_ops(oc)
        control_cycles = op_cycles(oc, mult)
        worst_events = stats["max_coincident_per_frame"]
        events_cycles = worst_events * ev_cycles
        # contention: this probe names the arbitration allowance the closure
        # formula subtracts (worst-case external wait per frame, from the
        # delay/reverb probes' latency-bound access counts at E1).
        contention = 33 * TECH["external"]["E1"]["latency_cycles"]  # reverb1 worst
        transfer = TRANSFER_CYCLES_PER_FRAME
        cpf = control_cycles + events_cycles
        cl = {c: closure(c, cpf, control=control_cycles, transfer=transfer,
                         contention=contention)
              for c in CLOCK_CANDIDATES_HZ}
        rec = build_record(
            probe=PROBE, kernel="event_queue_and_control",
            word_lengths={"audio_bits": 24,
                          "control_word_bits": 32,
                          "multiplier": mult},
            has_phase_accumulator=False,
            memory_model={"name": "onchip_1rw_sram",
                          "onchip_sram": TECH["onchip_sram"]
                          + " (event queue and voice table on-chip)",
                          "external": {"name": "none",
                                       "detail": "control path does not "
                                                 "touch external memory"}},
            assumptions=[
                TECH["multipliers"][mult]["assumption"], TECH["adder"],
                TECH["clock"],
                "A-CTL-1: audio output transfer service = 8 cycles/frame "
                "(stereo word push into the output FIFO; named, not "
                "measured).",
                "A-CTL-2: contention allowance = worst-case external "
                "arbitration wait per frame, taken as 33 same-frame "
                "external accesses (Reverb1 worst, probe_fx_reverb1) x "
                "30-cycle E1 latency; the closure formula subtracts it "
                "before DSP.",
                "Voice pool scan 32 entries; event worst case = the "
                "fixture-derived coincident burst; per-event cost is a "
                "named candidate schedule (queue pop, 32-entry alloc "
                "search, 8 envelope/LFO trigger writes, 12 routing ops).",
                "audio_bits=24 names the output FIFO word width; the "
                "control path itself is integer 32-bit.",
            ],
            citations=CITES, ops={
                "per_event": oe.ops_dict(),
                "per_frame_control": oc.ops_dict(),
            },
            cycles_per_frame=cpf,
            state_ram_bits=16 * 32,  # event queue depth 16 x 32-bit entries
            ext_bytes_per_frame=0,
            closure_at_clocks=cl,
            sxt015_replacement={
                "replaces": "cyc_event_frame",
                "sxt015_value": 40,
                "scope": "per queued event (ev_cycles_per_event below); "
                         "plus the control/transfer/contention split the "
                         "plan-section-5 formula subtracts",
            },
            extra={
                "event_stats_source": "fixtures/sequences/ re-derived "
                                      "(tick->frames per tempo segment)",
                "fixture_files": stats["files"],
                "max_coincident_events_per_frame": worst_events,
                "max_events_per_second_window":
                    stats["max_events_per_second_window"],
                "total_events_across_fixtures": stats["total_events"],
                "sxt015_event_model_reconciliation": {
                    "sxt015_max_coincident": 8,
                    "sxt015_peak_events_per_second": 13.333333,
                    "rederived_max_coincident": worst_events,
                    "match": worst_events == 8,
                },
                "cycles_per_event": ev_cycles,
                "control_cycles_per_frame": control_cycles,
                "transfer_cycles_per_frame": transfer,
                "contention_cycles_per_frame": contention,
                "closure_scope_note": "closure here includes the "
                                      "control/transfer/contention "
                                      "subtractions; per-instance DSP "
                                      "records close against their own "
                                      "cost only (worked bundles combine)",
            })
        paths.append(write_record(rec, outdir))
    return paths
