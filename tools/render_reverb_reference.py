#!/usr/bin/env python3
"""SXT-024: capture Reverb1 reference behavior from the pinned oracle.

Renders (all through the pinned engine via surgepy, 48 kHz, SXT-012 render
policies -- fresh instance, blob-verified loadPatch, controller reset,
0.25 s settle, block-quantized scheduling, no normalization/fades), written
as STEREO 16-bit PCM WAV under reports/sxt-024/traces/ with sidecars:

  preset   -- WET + diagnostic DRY of a Reverb1-carrying preset + sequence
              (extended tail; stereo bus). The WET render is the product
              reference; the DRY render is the reverb's actual input signal
              (the preset's only active FX is Reverb 1 in send slot S1, so
              wet = dry + return_gain * reverb(send_gain * dry)).
  click    -- 1-block click excitation (32-sample note), wet+dry, for
              impulse-response/decay analysis. NOT a mathematical impulse;
              documented as a click, the comparison remains exact because the
              model is driven by the DRY render of the same instance.
  sweep    -- decay-time sweep via setParamVal on the Reverb1 decay param
              (official host path; diagnostic parameter-state adaptation,
              the preset's own values remain the primary case), wet only,
              for decay-vs-parameter measurement.
  reset    -- mid-render loadPatch() of the SAME preset (the engine's
              patch-change/reset path) for the no-unintended-clicks control.

This tool makes reference-vs-reference captures only. It makes no fidelity,
support, or quality claim. Deactivation flags for the reverb lowcut/highcut
are NOT exposed by surgepy; they are read from the raw .fxp XML attributes
(documented exposure-gap bridge) and cross-checked by the fidelity budget.

Original to this repository (Apache-2.0).
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402

SR = 48000
FX_SLOTS = 16
OUT_DIR = os.path.join(REPO, "reports", "sxt-024", "traces")
PRESET_REL = "Basses/Behemoth.fxp"
PRESET_SLUG = "behemoth"
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")

REV1_PARAM_IDS = ["predelay", "shape", "roomsize", "decaytime", "damping",
                  "lowcut", "freq1", "gain1", "highcut", "mix", "width"]
REV1_SLOT = 4  # send1


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_version():
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                                capture_output=True, text=True, check=True).stdout.strip()
    except Exception as e:  # pragma: no cover
        commit = f"unavailable: {e}"
    return {"repo_commit": commit, "script_sha256": sha256_file(os.path.abspath(__file__))}


def census_blob(relname):
    rel = "resources/data/patches_factory/" + relname
    import csv

    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {relname}")


def read_deactivated_flags(preset_abs):
    """Raw .fxp XML 'deactivated' attributes for the Reverb1 slot params.
    surgepy exposure gap bridge (documented); rev>=20 files stream these."""
    with open(preset_abs, "rb") as f:
        data = f.read().decode("latin-1")
    flags = {}
    for idx, name in ((5, "lowcut"), (8, "highcut")):
        m = re.search(rf"<fx{REV1_SLOT + 1}_p{idx}\b[^>]*deactivated=\"(\d)\"", data)
        flags[name] = bool(int(m.group(1))) if m else None
    return flags


def read_patch_state(s):
    """Full-precision engine state for the coefficient plane + send path."""
    patch = s.getPatch()
    fx = patch["fx"][REV1_SLOT]
    state = {
        "fx_slot": REV1_SLOT,
        "fx_type": int(s.getParamVal(fx["type"])),
        "params": {n: float(s.getParamVal(fx["p"][i])) for i, n in enumerate(REV1_PARAM_IDS)},
        "return_level": float(s.getParamVal(fx["return_level"])),
        "scene_send_level": [float(s.getParamVal(patch["scene"][sc]["send_level"][0]))
                             for sc in range(2)],
        "volume": float(s.getParamVal(patch["volume"])),
    }
    return state


def write_wav_stereo16(path, stereo, sr=SR):
    """stereo: float array [2][N]; clip to [-1,1]; int16 PCM; no fades."""
    data = np.clip(stereo, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    inter = np.empty(pcm.shape[1] * 2, dtype="<i2")
    inter[0::2] = pcm[0]
    inter[1::2] = pcm[1]
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(inter.tobytes())


def import_surgepy():
    oc.apply_engine_env()
    return oc.import_surgepy()


def dispatch(s, events, block, quant):
    i = 0
    while i < len(events) and quant(events[i]["t"]) <= block:
        e = events[i]
        if e["type"] == "note_on":
            s.playNote(e["channel"], e["note"], e["velocity"], 0)
        elif e["type"] == "note_off":
            s.releaseNote(e["channel"], e["note"], e.get("velocity", 0))
        elif e["type"] == "cc":
            s.channelController(e["channel"], e["controller"], e["value"])
        elif e["type"] == "pitch_bend":
            s.pitchBend(e["channel"], e["value"])
        elif e["type"] == "channel_pressure":
            s.channelAftertouch(e["channel"], e["value"])
        i += 1
    return i


def fresh_instance(surgepy, preset_abs, fx_off=False):
    s = surgepy.createSurge(float(SR))
    if not s.loadPatch(preset_abs):
        raise Refuse(f"loadPatch failed: {preset_abs}")
    s.pitchBend(0, 0)
    s.channelController(0, 64, 0)
    s.channelController(0, 1, 0)
    s.channelController(0, 11, 0)
    s.channelAftertouch(0, 0)
    s.allNotesOff()
    if fx_off:
        import surgepy.constants as C

        for i in range(FX_SLOTS):
            s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
    return s


def settle(s, blocks=240):
    bs = int(s.getBlockSize())
    buf = s.createMultiBlock(blocks)
    s.processMultiBlock(buf)


def run_sequence(s, events, total_blocks, base_sample=0):
    bs = int(s.getBlockSize())
    buf = s.createMultiBlock(total_blocks)

    def quant(t):
        return -(-(t - base_sample) // bs)  # ceil to block, rebased

    dispatched = 0
    b = 0
    while b < total_blocks:
        nxt = dispatch(s, events[dispatched:], b, quant) + dispatched
        if nxt < len(events) and quant(events[nxt]["t"]) <= b:
            raise Refuse("scheduler failed to advance")
        seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
        seg = min(seg, total_blocks)
        s.processMultiBlock(buf, b, seg - b)
        b = seg
        dispatched = nxt
    return np.asarray(buf), dispatched


def capture_bus(surgepy, preset_abs, seq, fx_off, tail_s, overrides=None, reload_at=None,
                hard_reset_at=None):
    """One stereo render in a fresh instance. overrides: {param_index: value}
    applied via setParamVal BEFORE settle (official host path). reload_at:
    sample time at which loadPatch(same preset) is re-issued (patch-change
    reset control), dispatched at the containing block boundary."""
    s = fresh_instance(surgepy, preset_abs, fx_off=fx_off)
    applied = {}
    if overrides:
        for idx, val in overrides.items():
            s.setParamVal(s.getPatch()["fx"][REV1_SLOT]["p"][idx], float(val))
            applied[idx] = float(val)
    settle(s)
    if fx_off:
        import surgepy.constants as C

        types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"])) for i in range(FX_SLOTS)]
        if any(t != C.fxt_off for t in types):
            raise Refuse(f"dry render: FX types did not read back Off: {types}")
    if overrides:
        # read back the overridden params for the record
        for idx in overrides:
            applied[idx] = float(s.getParamVal(s.getPatch()["fx"][REV1_SLOT]["p"][idx]))

    events = list(seq["events"])
    notes = [e for e in events if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_blocks = -(-(last_t + int(tail_s * SR)) // int(s.getBlockSize()))

    if hard_reset_at is not None:
        # FX type toggle (reverb1 -> Off -> reverb1) at the block boundary:
        # the pinned loadFx() rebuilds the effect on type change, so the long
        # buffers are cleared (the engine's explicit-reset path).
        bs = int(s.getBlockSize())
        rb = -(-int(hard_reset_at) // bs)
        pre, disp = run_sequence(s, events, rb)
        s.setParamVal(s.getPatch()["fx"][REV1_SLOT]["type"], 0)
        off_blk = s.createMultiBlock(1)
        s.processMultiBlock(off_blk)
        s.setParamVal(s.getPatch()["fx"][REV1_SLOT]["type"], 2)
        post, _ = run_sequence(s, events[disp:], total_blocks - rb - 1,
                               base_sample=(rb + 1) * bs)
        stereo = np.concatenate([pre, np.asarray(off_blk), post], axis=1)
        reload_block = rb
    elif reload_at is None:
        stereo, _ = run_sequence(s, events, total_blocks)
        reload_block = None
    else:
        bs = int(s.getBlockSize())
        reload_block = -(-int(reload_at) // bs)
        pre, disp = run_sequence(s, events, reload_block)
        if not s.loadPatch(preset_abs):
            raise Refuse("mid-render loadPatch failed")
        post, _ = run_sequence(s, events[disp:], total_blocks - reload_block,
                               base_sample=reload_block * bs)
        stereo = np.concatenate([pre, post], axis=1)
    state = read_patch_state(s)
    del s
    info = {
        "blocks": int(stereo.shape[1]),
        "frames": int(stereo.shape[1] * 32 // 32),
        "peak_abs": [float(np.max(np.abs(stereo[ch]))) for ch in range(2)],
        "clipped_samples": int(np.sum(np.abs(stereo) > 1.0)),
        "overrides_applied": {str(k): v for k, v in (applied or {}).items()},
        "reload_block": reload_block,
        "tail_s": tail_s,
    }
    return stereo, state, info


def save_trace(name, stereo, state, info, extra=None, float_npy=False):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name + ".wav")
    write_wav_stereo16(path, stereo)
    npy_info = None
    if float_npy:
        npy_path = os.path.join(OUT_DIR, name + ".npy")
        np.save(npy_path, stereo.astype(np.float32))
        npy_info = {"sha256": sha256_file(npy_path), "bytes": os.path.getsize(npy_path),
                    "format": "float32 [2][N], unclipped engine output"}
    side = {
        "schema_version": 1,
        "issue": "SXT-024",
        "trace": name,
        "preset": {
            "slug": PRESET_SLUG,
            "path": "resources/data/patches_factory/" + PRESET_REL,
            "census_blob_sha1": census_blob(PRESET_REL),
            "actual_blob_sha1": oc.git_blob_sha1(
                os.path.join(oc.data_home(), "patches_factory", PRESET_REL)),
        },
        "engine_patch_state": state,
        "deactivated_flags_raw_fxp": read_deactivated_flags(
            os.path.join(oc.data_home(), "patches_factory", PRESET_REL)),
        "wav": {"sha256": sha256_file(path), "bytes": os.path.getsize(path),
                "channels": 2, "sample_rate": SR, "frames": int(stereo.shape[1])},
        "float_npy": npy_info,
        "render": info,
        "audio_policy": "stereo int16 PCM, hard clip [-1,1], no normalization, "
                        "no time warping, no fades; SXT-012 reset/scheduling policies",
        "tool": tool_version(),
    }
    if extra:
        side.update(extra)
    with open(os.path.join(OUT_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(side, f, indent=2, sort_keys=True)
        f.write("\n")
    return side


def load_seq(path):
    with open(path, "r", encoding="utf-8") as f:
        seq = json.load(f)
    if seq.get("schema_version") != 1:
        raise Refuse(f"{path}: unsupported schema_version")
    return seq


SEQ_COV = os.path.join(REPO, "fixtures", "sequences", "seq-notes-coverage-v1.json")


def click_sequence(note_ms=250, seq_id=None):
    """Loud single-note excitation at t=0 (reverb build-up well above the
    measurement floor; a mathematical impulse is not available through the
    note path, and the comparison remains exact because the model is driven
    by the DRY render of the same instance)."""
    ident = seq_id or f"sxt024-click-{note_ms}ms-v1"
    return {
        "schema_version": 1,
        "id": ident,
        "sample_rate": SR,
        "description": f"SXT-024 excitation: single {note_ms} ms note (velocity 127) at t=0",
        "coverage": {"click": True},
        "events": [
            {"type": "note_on", "t": 0, "channel": 0, "note": 60, "velocity": 127},
            {"type": "note_off", "t": int(note_ms * SR / 1000), "channel": 0,
             "note": 60, "velocity": 0},
        ],
        "tail_s": 12.0,
        "settle_s": 0.25,
        "notes": "SXT-024 local excitation; not part of the SXT-012 library",
    }


def cmd_preset(args):
    surgepy = import_surgepy()
    preset_abs = os.path.join(oc.data_home(), "patches_factory", PRESET_REL)
    seq = load_seq(SEQ_COV)
    tail_s = args.tail
    wet, wstate, winfo = capture_bus(surgepy, preset_abs, seq, False, tail_s)
    dry, dstate, dinfo = capture_bus(surgepy, preset_abs, seq, True, tail_s)
    sw = save_trace("preset-notes-coverage-wet", wet, wstate, winfo,
                    {"sequence": {"id": seq["id"], "path": os.path.relpath(SEQ_COV, REPO),
                                  "sha256": sha256_file(SEQ_COV)}, "bus": "wet"},
                    float_npy=True)
    sd = save_trace("preset-notes-coverage-dry", dry, dstate, dinfo,
                    {"sequence": {"id": seq["id"], "path": os.path.relpath(SEQ_COV, REPO),
                                  "sha256": sha256_file(SEQ_COV)}, "bus": "dry"},
                    float_npy=True)
    # engine-vs-engine sanity: same-instance-class wet repeatability (1 repeat)
    wet2, _, _ = capture_bus(surgepy, preset_abs, seq, False, tail_s)
    ident = bool(np.array_equal(wet, wet2))
    print(json.dumps({
        "wet": sw["wav"], "dry": sd["wav"],
        "wet_sha256": sw["wav"]["sha256"][:16], "frames": winfo["frames"],
        "wet_bit_identical_repeat": ident,
        "fx_state": wstate,
    }, indent=2))
    return 0


def cmd_click(args):
    surgepy = import_surgepy()
    preset_abs = os.path.join(oc.data_home(), "patches_factory", PRESET_REL)
    seq = click_sequence()
    tail = args.tail
    wet, wstate, winfo = capture_bus(surgepy, preset_abs, seq, False, tail)
    dry, dstate, dinfo = capture_bus(surgepy, preset_abs, seq, True, tail)
    sw = save_trace("click-wet", wet, wstate, winfo,
                    {"sequence": {"id": seq["id"]}, "bus": "wet"}, float_npy=True)
    save_trace("click-dry", dry, dstate, dinfo,
               {"sequence": {"id": seq["id"]}, "bus": "dry"}, float_npy=True)
    print(json.dumps({"wet": sw["wav"]["sha256"][:16], "frames": winfo["frames"],
                      "peaks": winfo["peak_abs"]}, indent=2))
    return 0


def cmd_sweep(args):
    """Diagnostic decay-time sweep via setParamVal (official host path).
    Uses a 3 s note excitation so long decays stay above the measurement
    floor; renders the matching DRY once."""
    surgepy = import_surgepy()
    preset_abs = os.path.join(oc.data_home(), "patches_factory", PRESET_REL)
    seq = click_sequence()
    grid = args.grid or "-4,-2,0,1.879465,3,4.5,6"
    vals = [x for x in grid.split(",") if x]
    results = []
    for v in vals:
        val = float(v)
        # tail long enough to cover the measured decay: max(12 s, 1.3 * 2^decay)
        tail = max(args.tail, int(1.3 * (2.0 ** val) * 10) / 10.0)
        wet, state, info = capture_bus(surgepy, preset_abs, seq, False, tail,
                                       overrides={3: val})
        name = f"sweep-decay-{v}".replace(".", "_").replace("-", "m")
        side = save_trace(name, wet, state, info,
                          {"sequence": {"id": seq["id"]}, "bus": "wet",
                           "sweep": {"param": "fx4_p3 decaytime", "requested": val}})
        results.append({"trace": name, "requested": val,
                        "readback": info["overrides_applied"].get("3")})
    print(json.dumps(results, indent=2))
    return 0


def cmd_reset(args):
    """Mid-render loadPatch(same preset): the patch-change/reset control."""
    surgepy = import_surgepy()
    preset_abs = os.path.join(oc.data_home(), "patches_factory", PRESET_REL)
    seq = load_seq(SEQ_COV)
    reload_at = args.reload_at
    wet, state, info = capture_bus(surgepy, preset_abs, seq, False, args.tail,
                                   reload_at=reload_at)
    dry, dstate, dinfo = capture_bus(surgepy, preset_abs, seq, True, args.tail,
                                     reload_at=reload_at)
    sw = save_trace("reset-midpatch-wet", wet, state, info,
                    {"sequence": {"id": seq["id"]}, "bus": "wet",
                     "reset_control": {"reload_at_sample": reload_at,
                                       "reload_method": "loadPatch(same preset) at "
                                                        "containing block boundary"}},
                    float_npy=True)
    save_trace("reset-midpatch-dry", dry, dstate, dinfo,
               {"sequence": {"id": seq["id"]}, "bus": "dry",
                "reset_control": {"reload_at_sample": reload_at}},
               float_npy=True)
    print(json.dumps({"wet": sw["wav"]["sha256"][:16], "reload_block": info["reload_block"]},
                     indent=2))
    return 0


def cmd_hardreset(args):
    """FX type toggle (reverb1 -> Off -> reverb1) mid-render: the engine's
    explicit FX-rebuild path (loadFx clears the long buffers)."""
    surgepy = import_surgepy()
    preset_abs = os.path.join(oc.data_home(), "patches_factory", PRESET_REL)
    seq = load_seq(SEQ_COV)
    wet, state, info = capture_bus(surgepy, preset_abs, seq, False, args.tail,
                                   hard_reset_at=args.reset_at)
    dry, dstate, dinfo = capture_bus(surgepy, preset_abs, seq, True, args.tail,
                                     hard_reset_at=args.reset_at)
    sw = save_trace("hardreset-midpatch-wet", wet, state, info,
                    {"sequence": {"id": seq["id"]}, "bus": "wet",
                     "reset_control": {"type_toggle_at_sample": args.reset_at,
                                       "method": "setParamVal fx type 2->0->2 across one "
                                                 "block; loadFx rebuilds the effect and "
                                                 "clears the long buffers"}},
                    float_npy=True)
    save_trace("hardreset-midpatch-dry", dry, dstate, dinfo,
               {"sequence": {"id": seq["id"]}, "bus": "dry",
                "reset_control": {"type_toggle_at_sample": args.reset_at}},
               float_npy=True)
    print(json.dumps({"wet": sw["wav"]["sha256"][:16], "toggle_block": info["reload_block"]},
                     indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preset", help="preset WET+DRY capture (seq-notes-coverage-v1)")
    p.add_argument("--tail", type=float, default=12.0)
    p.set_defaults(func=cmd_preset)

    p = sub.add_parser("click", help="1-block click capture, wet+dry")
    p.add_argument("--tail", type=float, default=12.0)
    p.set_defaults(func=cmd_click)

    p = sub.add_parser("sweep", help="decay-time sweep via setParamVal (diagnostic)")
    p.add_argument("--tail", type=float, default=12.0)
    p.add_argument("--grid", help="comma list of decaytime values")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("hardreset", help="mid-render FX type toggle (buffers cleared)")
    p.add_argument("--tail", type=float, default=12.0)
    p.add_argument("--reset-at", type=int, default=48000)
    p.set_defaults(func=cmd_hardreset)

    p = sub.add_parser("reset", help="mid-render loadPatch reset control")
    p.add_argument("--tail", type=float, default=12.0)
    p.add_argument("--reload-at", type=int, default=48000)
    p.set_defaults(func=cmd_reset)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
