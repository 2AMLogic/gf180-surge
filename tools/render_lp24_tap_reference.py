#!/usr/bin/env python3
"""SXT-307 / SXT-038 F-038-1: full-engine LP 24 dB tap leg (oracle-side adapter).

Drives the EXTERNAL, DR-0005-class tap-instrumented build of the pinned engine
(decision-records/0019-lp24-full-engine-tap.md).  This file is original to this
repository; it contains no engine source.  The tap patch and the patched tree
stay on the oracle host.

For each committed SXT-038 case it:

  1. renders the case carrier natively three ways in separate processes
       tap       patched build, SXT307_TAP_DIR set        (writes the tap files)
       untapped  patched build, SXT307_TAP_DIR unset
       base      unpatched build of the same pin, same host/toolchain/runtime
     and records the three WAV sha256s plus a same-build repeat of `untapped`
     (the engine-determinism leg).  Neutrality is only decisive when the
     engine is deterministic for that case; otherwise it is NO_VERDICT.
  2. splits the tap stream into one candidate bundle per unit instance, in the
     layout model/voice/filter_lp24/run_filter_leg.py consumes (tag/lane/seq
     records, five registers per block, coefficient records with C/dC);
  3. offers each case's candidate bundles to the UNCHANGED runner with the
     UNCHANGED case file and records the runner's verdict.  A runner REFUSE is a
     bounded finding (the native control plane differs from the committed
     plan); nothing here edits coefficient metadata or the plan to pass.

Environment:
  ORACLE_TAP_SURGEPY_DIR    dir holding the tap-instrumented surgepy module
  ORACLE_BASE_SURGEPY_DIR   dir holding the unpatched surgepy module
  ORACLE_SURGE_DIR          engine checkout (SURGE_DATA_HOME = <it>/resources/data)

Usage:
  python3 tools/render_lp24_tap_reference.py --case edges --out-dir DIR
  python3 tools/render_lp24_tap_reference.py --case all   --out-dir DIR
"""

import argparse
import collections
import hashlib
import json
import os
import struct
import subprocess
import sys
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_DIR = os.path.join(REPO, "reports", "SXT-038", "artifacts", "cases")
RUNNER = os.path.join(REPO, "model", "voice", "filter_lp24", "run_filter_leg.py")
SR = 48000
FX_SLOTS = 16
FILTER_KEYS = {"cut": "cutoff", "res": "resonance", "subtype": "subtype"}
N_REG = 5


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(path):
    data = open(path, "rb").read()
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


# Deterministic LP 24 dB control (factory scene A unit 0 is fut_lp24; two untapped
# renders on the baseline are bit-identical).  The decisive same-build tapped/untapped
# neutrality gate runs here, because several carriers (e.g. Edges Rhythm) are
# engine-nondeterministic (SXT-012 drift/retrigger class).  Not an SXT-038 case.
CONTROL = {
    "case": "neutrality-control-bass3",
    "carrier": {"rel": "resources/data/patches_factory/Basses/Bass 3.fxp",
                "census_blob_sha1": "9c55b7c50bc3d48c5cb4f4e6adfd23c28b4f5ae0",
                "scene": 0, "unit": 0},
    "sequence": "seq-notes-repeated-v1",
    "filter": {"type": 2},
    "stimulus": {"blocks": 0},
}


def case_names():
    return sorted(f[:-5] for f in os.listdir(CASES_DIR) if f.endswith(".json"))


def load_case(name):
    if name == CONTROL["case"]:
        return CONTROL
    return json.load(open(os.path.join(CASES_DIR, name + ".json"), encoding="utf-8"))


# ---------------------------------------------------------------- worker ----

def worker(args):
    """Render one case in THIS process against the engine module in --engine-dir."""
    import numpy as np

    sys.path.insert(0, args.engine_dir)
    engine = os.environ["ORACLE_SURGE_DIR"]
    os.environ["SURGE_DATA_HOME"] = os.path.join(engine, "resources", "data")
    if args.tap_dir:
        os.environ["SXT307_TAP_DIR"] = args.tap_dir
    else:
        os.environ.pop("SXT307_TAP_DIR", None)
    import surgepy
    import surgepy.constants as C

    case = load_case(args.case)
    rel = case["carrier"]["rel"]
    preset = os.path.join(engine, rel)
    if git_blob_sha1(preset) != case["carrier"]["census_blob_sha1"]:
        print("REFUSING: carrier blob differs from the census pin", file=sys.stderr)
        return 2
    seq = json.load(open(os.path.join(REPO, "fixtures", "sequences",
                                      case["sequence"] + ".json"), encoding="utf-8"))
    scene, unit = int(case["carrier"]["scene"]), int(case["carrier"]["unit"])

    s = surgepy.createSurge(float(SR))
    if not s.loadPatch(preset):
        print("REFUSING: loadPatch failed", file=sys.stderr)
        return 2
    s.pitchBend(0, 0)
    for cc in (64, 1, 11):
        s.channelController(0, cc, 0)
    s.channelAftertouch(0, 0)
    s.allNotesOff()
    for i in range(FX_SLOTS):
        s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
    fu = s.getPatch()["scene"][scene]["filterunit"][unit]
    ov = case.get("overrides", {})
    for k, pk in FILTER_KEYS.items():
        if k in ov:
            s.setParamVal(fu[pk], float(ov[k]))
    s.processMultiBlock(s.createMultiBlock(240))   # settle

    bs = int(s.getBlockSize())
    events = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in events)
    total = -(-(last_t + int(seq.get("tail_s", 2.5) * SR)) // bs)
    toggle = ov.get("toggle_from_segment")
    note_ons = [e for e in events if e["type"] == "note_on"]
    toggle_block = None
    if toggle is not None:
        toggle_block = -(-int(note_ons[int(toggle)]["t"]) // bs)

    buf = s.createMultiBlock(total)

    def quant(t):
        return -(-t // bs)

    b, i = 0, 0
    marks = sorted({quant(e["t"]) for e in events} | ({toggle_block} if toggle_block else set()))
    while b < total:
        while i < len(events) and quant(events[i]["t"]) <= b:
            e = events[i]
            if e["type"] == "note_on":
                s.playNote(e["channel"], e["note"], e["velocity"], 0)
            else:
                s.releaseNote(e["channel"], e["note"], e.get("velocity", 0))
            i += 1
        if toggle_block is not None and b == toggle_block:
            s.setParamVal(fu["subtype"], float(ov["toggle_subtype"]))
        nxt = min([m for m in marks if m > b] + [total])
        s.processMultiBlock(buf, b, nxt - b)
        b = nxt
    stereo = np.asarray(buf)
    version = surgepy.getVersion()
    del s
    pcm = (np.ascontiguousarray(np.clip(stereo, -1, 1).T) * 32767.0).astype("<i2")
    with wave.open(args.wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(json.dumps({"version": version, "blocks": total, "wav_sha256": sha256_file(args.wav)}))
    return 0


# ------------------------------------------------------------ splitting ----

def split_bundles(tap_dir, out_dir, case, version):
    """One candidate bundle per tapped unit instance (tag)."""
    coeffs = collections.defaultdict(list)
    for line in open(os.path.join(tap_dir, "coeffs.jsonl"), encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            coeffs[r["tag"]].append(r)
    audio = collections.defaultdict(list)
    raw = open(os.path.join(tap_dir, "units.bin"), "rb").read()
    rec = struct.calcsize("<IIIff")
    if len(raw) % rec:
        raise SystemExit("REFUSING: truncated units.bin")
    for k in range(len(raw) // rec):
        tag, lane, sq, fin, fout = struct.unpack_from("<IIIff", raw, k * rec)
        audio[tag].append((lane, sq, fin, fout))
    regs = collections.defaultdict(list)
    raw = open(os.path.join(tap_dir, "regs.bin"), "rb").read()
    rrec = struct.calcsize("<II5f")
    if len(raw) % rrec:
        raise SystemExit("REFUSING: truncated regs.bin")
    for k in range(len(raw) // rrec):
        v = struct.unpack_from("<II5f", raw, k * rrec)
        regs[v[0]].append(v[2:])

    insts = []
    for tag in sorted(coeffs):
        recs = coeffs[tag]
        d = os.path.join(out_dir, f"inst-{tag:06d}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "coeffs.jsonl"), "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps({k: r[k] for k in
                                    ("unit", "lane", "first", "type", "sub",
                                     "cut", "reso", "C", "dC")}) + "\n")
        with open(os.path.join(d, "units.bin"), "wb") as f:
            for n, (lane, _sq, fin, fout) in enumerate(audio.get(tag, [])):
                f.write(struct.pack("<IIIff", 0, 0, n, fin, fout))
        with open(os.path.join(d, "regs.bin"), "wb") as f:
            for r in regs.get(tag, []):
                f.write(struct.pack("<5f", *r))
        meta = {
            "schema": "sxt-307-tap-bundle/1", "case": case["case"],
            "source": "full-engine-tap", "engine_version": version,
            "identity": {k: recs[0][k] for k in ("tag", "vid", "scene", "key",
                                                  "channel", "lane", "unit")},
            "reference": {"kind": "full-engine-tap", "engine_version": version},
            "carrier": case["carrier"], "filter": case["filter"],
            "overrides": case.get("overrides", {}),
            "blocks": len(recs), "os_samples": len(audio.get(tag, [])),
            "reg_blocks": len(regs.get(tag, [])),
        }
        json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=1, sort_keys=True)
        insts.append((tag, recs[0], len(recs), d))
    return insts


def concat_bundle(insts, out_dir, case, version):
    """All instances (in tag order) concatenated: the plan's one-lane-in-time shape."""
    d = os.path.join(out_dir, "concat")
    os.makedirs(d, exist_ok=True)
    seq = 0
    with open(os.path.join(d, "coeffs.jsonl"), "w") as fc, \
            open(os.path.join(d, "units.bin"), "wb") as fu, \
            open(os.path.join(d, "regs.bin"), "wb") as fr:
        for _tag, _r0, _n, src in insts:
            fc.write(open(os.path.join(src, "coeffs.jsonl")).read())
            raw = open(os.path.join(src, "units.bin"), "rb").read()
            rec = struct.calcsize("<IIIff")
            for k in range(len(raw) // rec):
                _t, _l, _s, fin, fout = struct.unpack_from("<IIIff", raw, k * rec)
                fu.write(struct.pack("<IIIff", 0, 0, seq, fin, fout))
                seq += 1
            fr.write(open(os.path.join(src, "regs.bin"), "rb").read())
    json.dump({"schema": "sxt-307-tap-bundle/1", "kind": "concat", "case": case["case"],
               "reference": {"kind": "full-engine-tap", "engine_version": version},
               "carrier": case["carrier"], "filter": case["filter"],
               "overrides": case.get("overrides", {})},
              open(os.path.join(d, "meta.json"), "w"))
    return d


def offer_to_runner(bundle, scratch):
    p = subprocess.run([sys.executable, RUNNER, "--bundle", bundle, "--out-dir", scratch,
                        "--no-trace"], capture_output=True, text=True)
    tail = (p.stderr.strip() or p.stdout.strip()).splitlines()
    return {"exit": p.returncode, "message": tail[-1] if tail else ""}


# ----------------------------------------------------------------- main ----

def run_variant(args, case, variant, out_dir, repeat=0):
    eng = os.environ["ORACLE_BASE_SURGEPY_DIR" if variant == "base"
                     else "ORACLE_TAP_SURGEPY_DIR"]
    tap_dir = ""
    if variant == "tap":
        tap_dir = os.path.join(out_dir, "tap-raw")
        os.makedirs(tap_dir, exist_ok=True)
    wav = os.path.join(out_dir, f"{variant}{repeat or ''}.wav")
    cmd = [sys.executable, os.path.abspath(__file__), "--worker", "--case", case,
           "--engine-dir", eng, "--wav", wav]
    if tap_dir:
        cmd += ["--tap-dir", tap_dir]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"{variant} worker failed: {p.stderr.strip()[-400:]}")
    info = json.loads(p.stdout.strip().splitlines()[-1])
    os.remove(wav)
    if variant == "tap":
        # a baseline-only or wrong-tap build is NOT a full-engine tap reference
        if "sxt307-tap" not in info["version"]:
            raise SystemExit(f"REFUSING: engine version {info['version']!r} is not the "
                             "SXT-307 tap build")
        c = os.path.join(tap_dir, "coeffs.jsonl")
        if not os.path.exists(c) or os.path.getsize(c) == 0:
            raise SystemExit("REFUSING: tap build produced no LP24 coefficient records")
    return info


def one_case(args, name):
    out = os.path.join(args.out_dir, name)
    os.makedirs(out, exist_ok=True)
    case = load_case(name)
    tap = run_variant(args, name, "tap", out)
    unt = run_variant(args, name, "untapped", out)
    unt2 = run_variant(args, name, "untapped", out, repeat=2)
    base = run_variant(args, name, "base", out)
    det = unt["wav_sha256"] == unt2["wav_sha256"]
    if not det:
        neutral = "NO_VERDICT"
    else:
        neutral = ("PASS" if tap["wav_sha256"] == unt["wav_sha256"] == base["wav_sha256"]
                   else "FAIL")
    if name == CONTROL["case"]:
        result = {"case": name, "role": "same-build neutrality control (not an SXT-038 case)",
                  "engine_version_tap": tap["version"], "engine_version_base": base["version"],
                  "wav_sha256": {"tap": tap["wav_sha256"], "untapped": unt["wav_sha256"],
                                 "untapped_repeat": unt2["wav_sha256"],
                                 "base": base["wav_sha256"]},
                  "engine_deterministic_same_build": det, "neutrality": neutral}
        json.dump(result, open(os.path.join(out, "result.json"), "w"), indent=1, sort_keys=True)
        return result
    insts = split_bundles(os.path.join(out, "tap-raw"), os.path.join(out, "bundles"),
                          case, tap["version"])
    want = [i for i in insts if i[1]["scene"] == case["carrier"]["scene"]
            and i[1]["unit"] == case["carrier"]["unit"] and i[1]["type"] == 2]
    result = {
        "case": name, "engine_version_tap": tap["version"], "engine_version_base": base["version"],
        "wav_sha256": {"tap": tap["wav_sha256"], "untapped": unt["wav_sha256"],
                       "untapped_repeat": unt2["wav_sha256"], "base": base["wav_sha256"]},
        "engine_deterministic_same_build": det, "neutrality": neutral,
        "instances_total": len(insts), "instances_for_carrier_unit": len(want),
        "instance_blocks": [i[2] for i in want],
        "plan_blocks": int(case["stimulus"]["blocks"]),
        "runner": {},
    }
    scratch = os.path.join(out, "runner-scratch")
    if want:
        cat = concat_bundle(want, out, case, tap["version"])
        result["runner"]["concat"] = offer_to_runner(cat, scratch)
        longest = max(want, key=lambda i: i[2])
        result["runner"]["longest_instance"] = offer_to_runner(longest[3], scratch)
        result["availability"] = ("PASS" if all(v["exit"] == 0
                                                for v in result["runner"].values())
                                  else "BLOCKED")
    else:
        result["availability"] = "BLOCKED"
    json.dump(result, open(os.path.join(out, "result.json"), "w"), indent=1, sort_keys=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case", default="all")
    ap.add_argument("--out-dir")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--engine-dir")
    ap.add_argument("--tap-dir", default="")
    ap.add_argument("--wav")
    args = ap.parse_args()
    if args.worker:
        return worker(args)
    for v in ("ORACLE_TAP_SURGEPY_DIR", "ORACLE_BASE_SURGEPY_DIR", "ORACLE_SURGE_DIR"):
        if not os.environ.get(v):
            print(f"REFUSING: {v} is not set (external tap/base builds required)",
                  file=sys.stderr)
            return 3
    if not args.out_dir:
        ap.error("--out-dir required")
    names = (case_names() + [CONTROL["case"]]) if args.case == "all" else [args.case]
    for n in names:
        r = one_case(args, n)
        print(json.dumps({k: r[k] for k in ("case", "neutrality", "availability",
                                            "instances_for_carrier_unit") if k in r}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
