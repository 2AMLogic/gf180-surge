#!/usr/bin/env python3
"""SXT-026 model runner: render a fixture sequence through the frozen
wavetable model and emit the RTL stimulus.

Outputs (under --out-dir):
  model.wav           int16 mono render (fixtures WAV convention)
  model_trace.json    declared checkpoints + full sample stream
  traffic.json        per-block impulse / external-read accounting
  rtl/init.hex        one-time control-plane constants
  rtl/ctrl.hex        per-block control words (see word order below)
  rtl/sinc_main.hex   sinctable ROM (main taps), 32-bit hex words
  rtl/sinc_deriv.hex  sinctable ROM (derivative taps)
  rtl/wt_table.hex    wavetable mip table memory (DERIVED AT RUN TIME from
                      the external pinned tree — never committed; see
                      decision-records/0004)
  rtl/table_index.json  mip-level offsets/lengths into wt_table.hex

Declared control-plane boundary: pitchmult_inv / a_cov / hpf ramp endpoints
(coef-rate words), the sinc ROM, and the derived mip tables are streamed to
the RTL. The RTL reproduces the morph lag, tableid/tableipol stepping, mip
selection, the full impulse loop (per unison voice), and the hpf output
stage, and must match the model trace EXACTLY at every declared checkpoint
(integer equality; enforced by tools/compare_wt_rtl_model.py).

init.hex word order (32-bit words):
  0 wave_size   1 n_tables   2 built_levels   3 n_unison   4 nointerp
  5 deform_mode (0=xt14_continuous, 1=xt134_legacy)
  6 out_attenuation  7 detune_bias  8 detune_offset  9 udet_ext (Q10.21)
 10 t_shape 11 t_vskew 12 t_hskew 13 t_clip 14 formant_t 15 lag_rate
 16 tableipol_init 17 tableid_init 18 last_tableipol_init 19 last_tableid_init
 20 hpf_init

ctrl.hex: per block a header [b, slotmask] then one 8-word record per
non-empty slot (slot order 0..31): key, flags(b0 gate,b1 checkpoint,
b2 created,b3 released), pmi(Q13.18), pitchmult(Q4.27), a_cov(Q4.27),
hpf_start(Q10.21), hpf_d(Q10.21).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "wavetable"))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import wt_model as wm  # noqa: E402
import voice_model as vm  # noqa: E402

FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
CHECKPOINT_EVERY = 64
N_SLOTS = 4


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", required=True,
                    help="inputs/<name>.json (extract_inputs.py output)")
    ap.add_argument("--sequence", required=True,
                    help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--rtl", action="store_true",
                    help="emit the RTL stimulus files")
    ap.add_argument("--max-blocks", type=int, default=None,
                    help="cap the render at N blocks (RTL exactness runs "
                         "use short deterministic prefixes)")
    args = ap.parse_args()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences",
                                seq_path + ".json")
    seq = vm.load_sequence(seq_path)
    inp = wm.Inputs(args.inputs)

    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    if not notes:
        raise RuntimeError("sequence has no notes")
    last_t = max(e["t"] for e in notes)
    total_samples = last_t + int(float(seq.get("tail_s", 1.5)) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)
    if args.max_blocks:
        total_blocks = min(total_blocks, args.max_blocks)
        total_samples = total_blocks * BLOCK_SIZE

    voices = []
    events = list(seq["events"])
    ei = 0
    out_mono = []
    blocks_json = []
    traffic_blocks = []
    ctrl = []

    for b in range(total_blocks):
        blk = {"b": b, "create": [], "release": [], "voices": []}
        while ei < len(events) and -(-events[ei]["t"] // BLOCK_SIZE) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = wm.Slice(inp, e["note"], e.get("velocity", 100))
                v.slot = slot
                voices.append(v)
                blk["create"].append(slot)
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.gate = False
                        blk["release"].append(v.slot)
                        break
            ei += 1

        alive = []
        mono = [0] * BLOCK_SIZE
        blk_traffic = {"b": b, "slots": []}
        slotmask = 0
        slot_records = []
        for v in voices:
            m, osout, keep = v.process_block(b)
            for k in range(BLOCK_SIZE):
                mono[k] += m[k]
            impulses = v.osc.block_impulses
            # external asset reads: 2 words per impulse (frame pair) plus
            # on-demand frame fills of the active mip (cache-cold touches)
            fills = 0
            for st in v.osc.voices:
                keyf = (st["mipmap"], v.osc.tableid)
                cache = getattr(v, "_fillcache", None)
                if cache is None:
                    cache = v._fillcache = set()
                if keyf not in cache:
                    cache.add(keyf)
                    fills += v.osc.wave_size >> st["mipmap"]
            blk_traffic["slots"].append({
                "slot": v.slot, "impulses": impulses,
                "mips": sorted({st["mipmap"] for st in v.osc.voices}),
                "frame_fills_words": fills,
            })
            voices_full = (b % CHECKPOINT_EVERY == 0) or (not v.gate) or b < 2
            rec = {"slot": v.slot, "key": v.key, "gate": v.gate}
            if voices_full:
                rec["oscout_block"] = osout
                rec["after"] = {
                    "aeg": {"state": v.aeg.state, "phase": v.aeg.phase,
                            "output": v.aeg.output},
                    "oscstate": [st["oscstate"] for st in v.osc.voices],
                    "osc_state": [st["state"] for st in v.osc.voices],
                    "last_level": [st["last_level"] for st in v.osc.voices],
                    "mipmap": [st["mipmap"] for st in v.osc.voices],
                    "mipmap_ofs": [st["mipmap_ofs"] for st in v.osc.voices],
                    "tableid": v.osc.tableid,
                    "tableipol": v.osc.tableipol,
                    "last_tableipol": v.osc.last_tableipol,
                    "l_shape": v.osc.l_shape,
                    "osc_out": v.osc.osc_out,
                    "bufpos": v.osc.bufpos,
                    "hpf_prev": v.osc.hpf_prev,
                }
            blk["voices"].append(rec)
            if keep:
                alive.append(v)
                slotmask |= (1 << v.slot)
            # rtl ctrl words for this slot (7-word record)
            if args.rtl:
                osc = v.osc
                slot_records.append([
                    v.key & 0xFF,
                    (1 if v.gate else 0) | (2 if voices_full else 0)
                    | (4 if v.slot in blk["create"] else 0)
                    | (8 if v.slot in blk["release"] else 0),
                    osc.ctrl["pmi"], osc.ctrl["pitchmult"],
                    osc.ctrl["a_cov"],
                    osc.ctrl["hpf_start"], osc.ctrl["hpf_d"],
                ])
        voices = alive

        mono = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in mono]
        for k in range(BLOCK_SIZE):
            m = vm.limit_i(mono[k], -wm.ONE, wm.ONE)
            s = (m * 32767) >> FQ if m >= 0 else -((-m * 32767) >> FQ)
            out_mono.append(s)
        blk["mono_block"] = mono
        blocks_json.append(blk)
        total_imp = sum(s["impulses"] for s in blk_traffic["slots"])
        total_fills = sum(s["frame_fills_words"] for s in blk_traffic["slots"])
        blk_traffic["impulses"] = total_imp
        blk_traffic["ext_read_words"] = 2 * total_imp + total_fills
        traffic_blocks.append(blk_traffic)

        if args.rtl:
            ctrl.extend([b, slotmask])
            for rec in slot_records:
                ctrl.extend(rec)

    os.makedirs(args.out_dir, exist_ok=True)
    rtl_dir = os.path.join(args.out_dir, "rtl")
    if args.rtl:
        os.makedirs(rtl_dir, exist_ok=True)

    wm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "format": "sxt-026-wavetable-trace/1",
            "sequence": seq["id"],
            "inputs": os.path.relpath(args.inputs, REPO),
            "engine_pin": ("surge-synthesizer/surge@"
                           "58914e59c608ed4384ba6002e44c3465c58b2e71"),
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q10.21", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18", "oscstate": "Q10.21/64"},
            "unison": inp.unison,
            "deform_mode": inp.deform_mode,
            "n_tables": inp.wt["wave_count"],
            "nointerp": 0 if inp.extend_range else 1,
            "legacy": 1 if inp.deform_mode == "xt134_legacy" else 0,
            "wave_size": inp.wt["wave_size"],
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    with open(os.path.join(args.out_dir, "traffic.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "format": "sxt-026-wavetable-traffic/1",
            "declared_model": "external asset reads = 2 words/impulse "
                              "(morph frame pair) + on-demand active-mip "
                              "frame fills (4-byte f32 words)",
            "blocks": traffic_blocks,
            "totals": {
                "impulses": sum(t["impulses"] for t in traffic_blocks),
                "ext_read_words": sum(t["ext_read_words"]
                                      for t in traffic_blocks),
                "ext_read_bytes": 4 * sum(t["ext_read_words"]
                                          for t in traffic_blocks),
            },
        }, f, indent=1)
        f.write("\n")

    if args.rtl:
        osc0 = wm.WavetableOsc(inp, 60)
        morph_scale = wm.qint((inp.wt["wave_count"] - 1
                               + (0 if inp.extend_range else 1)) * 0.99999)
        tempt_words = []
        for v in range(16):
            if v < inp.unison:
                detune_v = 0
                if inp.unison > 1:
                    detune_v = vm.qmul(inp.udet_ext_q,
                                       vm.qmul(osc0.detune_bias,
                                               wm.qint(float(v)))
                                       + osc0.detune_offset)
                tempt_words.append(vm.ntpi_tuningctr(detune_v))
            else:
                tempt_words.append(vm.ntpi_tuningctr(0))
        init_words = [
            inp.wt["wave_size"], inp.wt["wave_count"],
            len(inp.mip_tables), inp.unison,
            0 if inp.extend_range else 1,
            0 if inp.deform_mode == "xt14_continuous" else 1,
            osc0.out_attenuation, osc0.detune_bias, osc0.detune_offset,
            wm.qint(12.0 * inp.udet),
            osc0.t_shape, osc0.t_vskew, osc0.t_hskew, osc0.t_clip,
            osc0.formant_t, wm.LAG_RATE,
            osc0.tableipol, osc0.tableid,
            osc0.last_tableipol, osc0.last_tableid,
            wm.INTEGRATOR_HPF,
            morph_scale, wm.TAYLORSCALE, osc0.dt,
            *tempt_words,
        ]
        write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
        write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)
        write_hex(os.path.join(rtl_dir, "sinc_main.hex"), vm.SINC_MAIN)
        write_hex(os.path.join(rtl_dir, "sinc_deriv.hex"), vm.SINC_DERIV)
        tbl = []
        index = []
        off = 0
        for lvl, words in enumerate(inp.mip_tables):
            tbl.extend(words)
            index.append({"level": lvl, "offset": off,
                          "words": len(words)})
            off += len(words)
        write_hex(os.path.join(rtl_dir, "wt_table.hex"), tbl)
        with open(os.path.join(rtl_dir, "table_index.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"stride_note": "frame-major per level: "
                                      "table*(size>>level) + idx",
                       "levels": index}, f, indent=1)
            f.write("\n")

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "samples": len(out_mono),
        "impulses": sum(t["impulses"] for t in traffic_blocks),
        "ext_read_bytes": 4 * sum(t["ext_read_words"]
                                  for t in traffic_blocks),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
