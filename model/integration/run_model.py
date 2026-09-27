#!/usr/bin/env python3
"""SXT-025: run the integrated model over an integration sequence.

Outputs (under --out-dir):
  model__<seq>-wet.f32.wav   model wet bus (stereo float32)
  trace__<seq>.json          control decisions, event-to-output timing,
                             external-traffic ledger, tail record, image
                             placement/order/gain manifest
  rtl/cfg.hex                reverb1 coefficient plane (86 words, SXT-024
                             frozen format)
  rtl/blocks.hex             send-block stimulus (s24) for the kernel
  rtl/events.hex             control-plane event stream (SXT-021 format)

Original to this repository (Apache-2.0).
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import numpy as np  # noqa: E402

from model.integration.integration_model import (  # noqa: E402
    IntegrationRun, Reverb1Counted, q21_to_s24, SETTLE_BLOCKS,
)
from model.integration.extract_preset_inputs import (  # noqa: E402
    IMAGE_JSON, OUT_PATH as INPUTS_JSON,
)
from tools.render_fx_fixtures import write_wav_stereo_f32  # noqa: E402
from tools.run_reverb_rtl import (  # noqa: E402
    coefficient_words, gen_blocks,
)
from model.effects.reverb1 import reverb1_fixed as rf  # noqa: E402

FIXTURES = os.path.join(REPO, "reports", "sxt-025", "fixtures")
SEQ_DIR = os.path.join(REPO, "model", "integration", "sequences")


def read_wav_stereo_f32(path):
    import struct

    with open(path, "rb") as f:
        data = f.read()
    pos = 12
    fmt = raw = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        sz = int.from_bytes(data[pos + 4:pos + 8], "little")
        body = data[pos + 8:pos + 8 + sz]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            raw = body
        pos += 8 + sz + (sz & 1)
    audio_fmt, nch, sr, _b, _a, bits = fmt
    if audio_fmt != 3 or bits != 32 or nch != 2:
        raise ValueError(f"expected stereo float32: {path}")
    a = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    return a.T.copy(), sr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", required=True,
                    help="sequence id under model/integration/sequences")
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports", "sxt-025",
                                                      "artifacts"))
    ap.add_argument("--voice-dry-wav", default=None,
                    help="SXT-026a (#48): original voice stage -- feed the "
                         "landed voice model's int16 mono render (L=R) as "
                         "the dry bus instead of the engine dry bus (the "
                         "SXT-025 finding-F-1 adapted path). Refuses a "
                         "frame-count mismatch with the upstream fixture.")
    args = ap.parse_args()
    seq_name = args.sequence
    seq = json.load(open(os.path.join(SEQ_DIR, seq_name + ".json")))
    sidecar = json.load(open(os.path.join(
        FIXTURES, f"hells_bells__{seq_name}.json")))
    if args.voice_dry_wav:
        import wave

        with open(args.voice_dry_wav, "rb") as f:
            w = wave.open(f)
            assert w.getnchannels() == 1 and w.getsampwidth() == 2 \
                and w.getframerate() == 48000, "expected int16 mono 48k wav"
            raw = w.readframes(w.getnframes())
        mono = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        dry = np.vstack([mono, mono])
    else:
        dry, sr = read_wav_stereo_f32(os.path.join(
            REPO, sidecar["dry"]["wav"]))
        assert sr == 48000
    frames = sidecar["render"]["frames"]
    assert dry.shape[1] == frames

    run = IntegrationRun(IMAGE_JSON, INPUTS_JSON, dry, frames)
    res = run.run(seq)

    os.makedirs(args.out_dir, exist_ok=True)
    wet = np.vstack([np.asarray(res["wet_l"], dtype=np.float32),
                     np.asarray(res["wet_r"], dtype=np.float32)])
    wav_path = os.path.join(args.out_dir, f"model__{seq_name}-wet.f32.wav")
    write_wav_stereo_f32(wav_path, wet)

    # ---------------------------------------------------------------- trace
    inst_ledger = []
    for inst_rec, inst in zip(res["instances"], run.instances):
        rec = dict(inst_rec)
        if isinstance(inst.model, Reverb1Counted):
            n_samples = res["blocks_total"] * 32
            rec["traffic"] = {
                "reads": inst.model.total_reads,
                "writes": inst.model.total_writes,
                "words_per_output_frame":
                    (inst.model.total_reads + inst.model.total_writes)
                    // n_samples,
                "bytes_per_output_frame":
                    4 * (inst.model.total_reads + inst.model.total_writes)
                    // n_samples,
                "buffer_words": rf.TAP_WORDS + rf.MAX_REV_DLY,
                "buffer_bytes": 4 * (rf.TAP_WORDS + rf.MAX_REV_DLY),
            }
        inst_ledger.append(rec)
    trace = {
        "schema_version": 1,
        "issue": "SXT-025 (#18)",
        "sequence": seq_name,
        "preset": run.inputs["path"],
        "image": {"sha256": run.inputs["compiled_image_sha256"],
                  "path": run.inputs["compiled_image"]},
        "placement_order": [
            {"slot": i.slot, "role": i.role, "phase": i.phase_name,
             "order_in_phase": i.order_in_phase,
             "engine_order": i.engine_order, "kind": i.kind}
            for i in run.instances],
        "gain_staging": {
            "master_volume_db": run.inputs["volume_f"],
            "a_q": run.a_q,
            "volume_note": run.inputs.get("volume_note"),
            "instances": {f"slot{i.slot}": {
                "send_gain_f": i.send_gain_f, "return_f": i.return_f,
                "send_gain_q": i.send_gain_q, "return_q": i.return_q}
                for i in run.instances if i.send_gain_q is not None},
        },
        "event_timing": {
            "max_event_latency_samples": res["max_event_latency_samples"],
            "worst_events_per_block": res["worst_events_per_block"],
            "reserve_per_block": 8,
            "reserve_exceeded_blocks": res["reserve_exceeded_blocks"],
            "decisions_total": sum(len(r["decisions"])
                                   for r in res["control_rows"]),
        },
        "tail": {
            "last_note_event_t": res["last_note_event_t"],
            "last_noteoff_applied_sample": res["last_noteoff_applied_sample"],
            "tail_s": res["tail_s"],
            "tail_frames": res["frames"] - res["last_noteoff_applied_sample"],
            "reverb1_nominal_t60_s": 2.0 ** run.instances[0].plane["decaytime"],
        },
        "traffic_ledger": inst_ledger,
        "blocks_total": res["blocks_total"],
        "frames": res["frames"],
        "control_rows": res["control_rows"],
    }
    trace_path = os.path.join(args.out_dir, f"trace__{seq_name}.json")
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=1, sort_keys=True)
        f.write("\n")

    # --------------------------------------------------------- rtl stimulus
    rtl_dir = os.path.join(args.out_dir, "rtl", seq_name)
    os.makedirs(rtl_dir, exist_ok=True)
    inst = next(i for i in run.instances if i.kind == "reverb1")
    with open(os.path.join(rtl_dir, "cfg.hex"), "w") as f:
        for w in coefficient_words(inst.plane):
            f.write(f"{w & 0xFFFFFFFF:08x}\n")
    # send-scaled s24 blocks (the kernel's input at the declared boundary)
    import model.effects.qmath as qm  # noqa: E402

    sg = inst.send_gain_q
    n_blocks = res["blocks_total"]
    bl, br = [], []
    for b in range(n_blocks):
        lo = (b - SETTLE_BLOCKS) * 32 if b >= SETTLE_BLOCKS else 0
        if b >= SETTLE_BLOCKS and lo < run.frames:
            sl = [qm.qmul(sg, int(run.dry_deamped[0][lo + k]),
                          "Q13.18", "Q10.21", "Q10.21") for k in range(32)]
            sr_ = [qm.qmul(sg, int(run.dry_deamped[1][lo + k]),
                           "Q13.18", "Q10.21", "Q10.21") for k in range(32)]
        else:
            sl = [0] * 32
            sr_ = [0] * 32
        bl.append([q21_to_s24(v) for v in sl])
        br.append([q21_to_s24(v) for v in sr_])
    gen_blocks(os.path.join(rtl_dir, "blocks.hex"), bl, br, set())
    ev_words = [len(seq["events"]), res["blocks_total"] * 32]
    from model.control.control_model import Event as CtlEvent  # noqa: E402
    for raw in seq["events"]:
        name = raw["type"]
        p1 = raw.get("note", raw.get("controller", raw.get("value", 0)))
        p2 = raw.get("velocity", 0)
        ev = CtlEvent(seq=0, t=raw["t"],
                      type={"note_on": 0, "note_off": 1, "cc": 2,
                            "pitch_bend": 3, "channel_pressure": 4,
                            "patch_change": 5, "tempo": 6}[name],
                      p1=p1, p2=p2)
        ev_words.append(ev.to_word())
    with open(os.path.join(rtl_dir, "events.hex"), "w") as f:
        f.write(f"{len(seq['events']):x}\n")
        f.write(f"{res['blocks_total'] * 32:x}\n")
        for w in ev_words[2:]:
            f.write(f"{w & ((1 << 80) - 1):020x}\n")

    print(json.dumps({
        "sequence": seq_name,
        "model_wav": os.path.relpath(wav_path, REPO),
        "trace": os.path.relpath(trace_path, REPO),
        "blocks_total": res["blocks_total"],
        "max_event_latency_samples": res["max_event_latency_samples"],
        "reverb1_traffic_words_per_output_frame":
            (inst_ledger[0].get("traffic", {})
             .get("words_per_output_frame")),
        "tail_frames": trace["tail"]["tail_frames"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
