#!/usr/bin/env python3
"""SXT-037: render LP12 reference fixtures + filter tap bundles (oracle side).

Runs ONLY against the oracle tap instrumentation: an externally patched
build of the pinned engine (decision-records/0005) that writes read-only
per-sample filter taps. The patch lives outside this repository (external
GPL tree); this tool requires it and refuses (exit 3) when the loaded
surgepy module does not carry the tap entry points.

Renders (SXT-012 policies: fresh instance, census-blob-verified loadPatch,
controller reset, 0.25 s settle, block-quantized scheduling, no
normalization/fades; all FX slots Off = dry bus):

  <carrier>            the committed preset as-is (its own LP12 params)
  <carrier>-<corner>   parameter-corner adaptations via setParamVal on the
                       scene filter-unit parameters (official host path):
                       resonance/cutoff corners and a subtype toggle
                       mid-render (coefficient-reload path).

Per case this tool writes, under --out-dir:
  <case>/meta.json        pins (engine commit, patch marker, preset blob,
                          overrides, neutrality wav shas)
  <case>/coeffs.jsonl     engine MakeCoeffs records (control plane + C/dC)
  <case>/units.bin        per-OS-sample unit input/output taps (float32)
  <case>/render.wav       the dry stereo int16 render (same bits as the
                          untapped engine: neutrality is asserted per case)

Usage (on the oracle host):
  python3 tools/render_lp12_reference.py --cases all --out-dir DIR
  python3 tools/render_lp12_reference.py --cases badnews --smoke
"""

import argparse
import hashlib
import json
import os
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
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")

CARRIERS = {
    "badnews": {
        "rel": "resources/data/patches_3rdparty/Bluelight/Pads/Bad News.fxp",
        "blob": "8c61a18938fa816d0711e88eeb7a32dce41cf1cb",
        "unit": 0, "subtype": 1,
    },
    "rainy": {
        "rel": "resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp",
        "blob": "13979de9231f1b5d2b83e4370948cc33b5b52dfc",
        "unit": 0, "subtype": 1,
    },
    "t9": {
        "rel": "resources/data/patches_3rdparty/Emu/Drums/T9 Tom.fxp",
        "blob": "314e3cc7e46d76381a5073fecf41d8d715b70e8b",
        "unit": 1, "subtype": 2,
    },
    # deterministic control case (drift 0, retrigger on, SXT-022 class): the
    # decisive tapped-vs-plain bit gate runs on this preset
    "attacky-neutrality": {
        "rel": "resources/data/patches_factory/Basses/Attacky.fxp",
        "blob": "4675e423a7489b02f501f7763b4760f64ab035f9",
        "unit": 0, "subtype": 1,
    },
}
SMOKE_SEQ = "seq-lp12-smoke-v1"
MAIN_SEQ = "seq-notes-repeated-v1"


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def census_blob(rel):
    import csv

    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def git_blob_sha1(path):
    import struct
    import zlib

    data = open(path, "rb").read()
    hdr = b"blob %d\x00" % len(data)
    return hashlib.sha1(hdr + data).hexdigest()


def tool_version():
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                                capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        commit = "unavailable"
    return {"repo_commit": commit, "script_sha256": sha256_file(os.path.abspath(__file__))}


def load_seq(ref):
    path = ref if os.path.sep in ref else os.path.join(REPO, "fixtures", "sequences", ref + ".json")
    with open(path, encoding="utf-8") as f:
        seq = json.load(f)
    if seq.get("schema_version") != 1 or not seq.get("events"):
        raise Refuse(f"bad sequence: {path}")
    return seq


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
        i += 1
    return i


def fresh_instance(surgepy, preset_abs, fx_off=True):
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
    s.processMultiBlock(s.createMultiBlock(blocks))


def fu_param(s, unit, key):
    fu = s.getPatch()["scene"][0]["filterunit"][unit]
    if key not in fu:
        raise Refuse(f"filterunit[{unit}] has no param handle {key!r} "
                     f"(available: {sorted(fu.keys())})")
    return fu[key]


def run_sequence(s, seq, total_blocks, base_sample=0):
    bs = int(s.getBlockSize())
    buf = s.createMultiBlock(total_blocks)

    def quant(t):
        return -(-(t - base_sample) // bs)

    disp = 0
    b = 0
    events = seq["events"]
    while b < total_blocks:
        nxt = dispatch(s, events[disp:], b, quant) + disp
        if nxt < len(events) and quant(events[nxt]["t"]) <= b:
            raise Refuse("scheduler failed to advance")
        seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
        seg = min(seg, total_blocks)
        s.processMultiBlock(buf, b, seg - b)
        b = seg
        disp = nxt
    return np.asarray(buf)


def write_wav_stereo16(path, stereo):
    frames = np.clip(stereo, -1.0, 1.0)
    pcm = (np.ascontiguousarray(frames.T) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def capture_case(surgepy, case, carrier, seq, out_dir, overrides=None,
                 toggle_at=None, smoke=False, taps=True):
    """One render in a fresh instance; taps enabled via env (if patched)."""
    preset_abs = os.path.join(oc.data_home(), carrier["rel"][len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse(f"preset not found under oracle data home: {preset_abs}")
    actual = git_blob_sha1(preset_abs)
    expected = carrier["blob"]
    if census_blob(carrier["rel"]) != expected:
        raise Refuse("census blob drift for " + carrier["rel"])
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    os.environ["SXT037_TAP_DIR"] = out_dir
    s = fresh_instance(surgepy, preset_abs, fx_off=True)
    applied = {}
    for (unit, key), val in (overrides or {}).items():
        s.setParamVal(fu_param(s, unit, key), float(val))
        applied[f"fu{unit}.{key}"] = float(val)
    settle(s)
    import surgepy.constants as C

    types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"])) for i in range(FX_SLOTS)]
    if any(t != C.fxt_off for t in types):
        raise Refuse(f"FX types did not read back Off: {types}")
    for (unit, key), val in (overrides or {}).items():
        applied[f"fu{unit}.{key}"] = float(s.getParamVal(fu_param(s, unit, key)))

    events = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in events)
    tail = int((seq.get("tail_s", 2.5)) * SR)
    total_blocks = -(-(last_t + tail) // int(s.getBlockSize()))

    stereo = None
    bs = int(s.getBlockSize())
    if toggle_at is None:
        stereo = run_sequence(s, seq, total_blocks)
    else:
        rb = -(-int(toggle_at[0]) // bs)
        pre = run_sequence(s, seq, rb)
        s.setParamVal(fu_param(s, carrier["unit"], "subtype"), float(toggle_at[1]))
        one = s.createMultiBlock(1)
        s.processMultiBlock(one)
        applied[f"fu{carrier['unit']}.subtype@{rb}"] = float(
            s.getParamVal(fu_param(s, carrier["unit"], "subtype")))
        post = run_sequence(s, seq, total_blocks - rb - 1, base_sample=(rb + 1) * bs)
        stereo = np.concatenate([pre, np.asarray(one), post], axis=1)
    state = {
        "fu": [{k: s.getParamVal(p) for k, p in
                s.getPatch()["scene"][0]["filterunit"][u].items()}
               for u in range(2)],
    }
    del s
    os.environ.pop("SXT037_TAP_DIR", None)

    wav_path = os.path.join(out_dir, "render.wav")
    write_wav_stereo16(wav_path, stereo)

    # neutrality + determinism legs (same build, fresh instances):
    #   plain1 == tapped            -> taps DSP-neutral for this case
    #   plain1 != plain2            -> engine nondeterministic class on this
    #                                  preset (drift/retrigger); the bit gate
    #                                  is then decided on the deterministic
    #                                  Attacky control case (see EVIDENCE)
    shas = []
    for i in range(2):
        s2 = fresh_instance(surgepy, preset_abs, fx_off=True)
        for (unit, key), val in (overrides or {}).items():
            s2.setParamVal(fu_param(s2, unit, key), float(val))
        settle(s2)
        st2 = run_sequence(s2, seq, total_blocks)
        if toggle_at is not None:
            rb = -(-int(toggle_at[0]) // bs)
            pre2 = st2[:, :rb * bs]
            s2.setParamVal(fu_param(s2, carrier["unit"], "subtype"), float(toggle_at[1]))
            one2 = np.asarray(s2.createMultiBlock(1))
            post2 = run_sequence(s2, seq, total_blocks - rb - 1, base_sample=(rb + 1) * bs)
            st2 = np.concatenate([pre2, one2, post2], axis=1)
        del s2
        wav2_path = os.path.join(out_dir, f"render-plain{i + 1}.wav")
        write_wav_stereo16(wav2_path, st2)
        shas.append(sha256_file(wav2_path))
        os.remove(wav2_path)
    engine_deterministic = shas[0] == shas[1]
    neutral = (shas[0] == sha256_file(wav_path))
    if engine_deterministic and not neutral:
        raise Refuse(f"{case}: tap instrumentation is NOT DSP-neutral "
                     "(tapped vs untapped renders differ on a deterministic case)")

    meta = {
        "schema_version": 1,
        "issue": "SXT-037",
        "case": case,
        "carrier": {**carrier, "census_blob_sha1": expected, "actual_blob_sha1": actual},
        "sequence": {"id": seq.get("id"), "events": len(seq["events"]),
                     "smoke": smoke},
        "engine": {
            "commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
            "version_string": surgepy.getVersion(),
            "sample_rate": SR,
            "block_size": bs,
        },
        "overrides_applied": applied,
        "taps_enabled": taps,
        "engine_deterministic_same_case": engine_deterministic,
        "neutrality_violated": bool(engine_deterministic and not neutral),
        "neutrality": {
            "wav_sha_tapped": sha256_file(wav_path),
            "wav_sha_plain": shas[0],
            "wav_sha_plain_repeat": shas[1],
            "bit_identical": neutral,
            "note": "bit_identical is decisive only when "
                    "engine_deterministic_same_case is true; nondeterministic "
                    "carriers are SXT-012 drift/retrigger-class presets. The "
                    "decisive DSP-neutrality control runs on a deterministic "
                    "preset (see meta case attacky-neutrality).",
        },
        "render": {"frames": int(stereo.shape[1]), "peak_abs": [
            float(np.max(np.abs(stereo[ch]))) for ch in range(2)]},
        "engine_state_readback": state,
        "tool": tool_version(),
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
        f.write("\n")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cases", default="all")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    try:
        surgepy = oc.import_surgepy()
        oc.apply_engine_env()
    except Exception as e:
        raise Refuse(f"oracle unavailable: {e}")

    # tap instrumentation present? Probe: a one-block render must produce a
    # units.bin; a module without the patch silently produces none.
    import tempfile
    probe_dir = tempfile.mkdtemp(prefix="sxt037-probe-")
    os.environ["SXT037_TAP_DIR"] = probe_dir
    try:
        s = surgepy.createSurge(float(SR))
        s.processMultiBlock(s.createMultiBlock(2))
        del s
    finally:
        os.environ.pop("SXT037_TAP_DIR", None)
    if not os.path.exists(os.path.join(probe_dir, "units.bin")):
        raise Refuse("surgepy module lacks SXT-037 tap instrumentation; build the "
                     "externally patched pinned tree (decision-records/0005)")

    seq = load_seq(SMOKE_SEQ if args.smoke else MAIN_SEQ)
    cases = list(CARRIERS) if args.cases == "all" else args.cases.split(",")
    os.makedirs(args.out_dir, exist_ok=True)
    summary = {}
    for case in cases:
        smoke = args.smoke
        overrides = None
        toggle_at = None
        carrier = CARRIERS.get(case) or CARRIERS[case.split("-")[0]]
        out_dir = os.path.join(args.out_dir, case)
        os.makedirs(out_dir, exist_ok=True)
        if case.endswith("-reso1"):
            overrides = {(carrier["unit"], "resonance"): 1.0}
        elif case.endswith("-cut-hi"):
            overrides = {(carrier["unit"], "cutoff"): 96.0}
        elif case.endswith("-cut-lo"):
            overrides = {(carrier["unit"], "cutoff"): -96.0}
        elif case.endswith("-substd"):
            overrides = {(carrier["unit"], "subtype"): 0.0}
        elif case.endswith("-toggle"):
            # mid-render subtype toggle Driven(1) -> Clean(2) at ~2/3 seq
            toggle_at = (last_t_of(seq) * 2 // 3, 2.0)
        meta = capture_case(surgepy, case, carrier, seq, out_dir,
                            overrides=overrides, toggle_at=toggle_at, smoke=smoke)
        summary[case] = {"wav_sha": meta["neutrality"]["wav_sha_tapped"],
                         "neutral": meta["neutrality"]["bit_identical"],
                         "frames": meta["render"]["frames"]}
    print(json.dumps(summary, indent=2))
    return 0


def last_t_of(seq):
    return max(e["t"] for e in seq["events"]
               if e["type"] in ("note_on", "note_off"))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(3)
