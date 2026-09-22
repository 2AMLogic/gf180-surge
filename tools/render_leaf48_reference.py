#!/usr/bin/env python3
"""SXT-026a: reference renders + inertness probes for the extended voice leaf.

Reuses the SXT-012 fixtures harness (`render_fixture.py`: fresh-instance
policy, controller reset, settle, block-quantized scheduling, mono int16)
with an arbitrary corpus-relative preset path.  Renders the DRY bus (all FX
slots off, read-back verified) for the voice comparisons, plus the two
declared A/B inertness probes of issue #48 (both must be BIT-IDENTICAL to
the stock dry render for the probe evidence to record inertness):

  --probe fm     fm_switch 2 -> 0 (scene FM routing with muted FM sources)
  --probe width  scene width 1.0 -> 0.0 (width at unison 1, serial-1)

Runs under the pinned interpreter (auto re-exec via oracle_common).
"""

import argparse
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "fixtures"))

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import render_fixture as rf  # noqa: E402
import numpy as np  # noqa: E402


class Refuse(Exception):
    pass


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def census_blob(rel):
    import csv

    with open(os.path.join(REPO, "corpus", "census-v0.1", "results",
                           "per-preset.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def render_variant(surgepy, preset_abs, seq, variant):
    """One render in a fresh instance; variant applies probe param edits."""
    s = surgepy.createSurge(float(rf.SR))
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse(f"loadPatch failed: {preset_abs}")
        s.pitchBend(0, 0)
        s.channelController(0, 64, 0)
        s.channelController(0, 1, 0)
        s.channelController(0, 11, 0)
        s.channelAftertouch(0, 0)
        s.allNotesOff()

        import surgepy.constants as C

        for i in range(rf.FX_SLOTS):
            s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)

        if variant == "fm":
            sc = s.getPatch()["scene"][0]
            s.setParamVal(sc["fm_switch"], 0)
        elif variant == "width":
            sc = s.getPatch()["scene"][0]
            s.setParamVal(sc["width"], 0.0)

        bs = int(s.getBlockSize())
        settle_blocks = int(seq.get("settle_s", 0.25) * rf.SR) // bs
        sbuf = s.createMultiBlock(settle_blocks)
        s.processMultiBlock(sbuf)

        types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                 for i in range(rf.FX_SLOTS)]
        if any(t != C.fxt_off for t in types):
            raise Refuse(f"dry render: FX types did not read back Off: {types}")

        events = seq["events"]
        notes = [e for e in events if e["type"] in ("note_on", "note_off")]
        last_t = max(e["t"] for e in notes) if notes else 0
        total_samples = last_t + int(float(seq.get("tail_s", 2.5)) * rf.SR)
        total_blocks = -(-total_samples // bs)
        buf = s.createMultiBlock(total_blocks)

        quant = lambda t: -(-t // bs)  # noqa: E731
        dispatched = 0
        b = 0
        while b < total_blocks:
            nxt = rf.dispatch(s, events[dispatched:], b, quant) + dispatched
            if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                raise Refuse("scheduler failed to advance")
            seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
            s.processMultiBlock(buf, b, seg - b)
            b = seg
            dispatched = nxt

        stereo = np.asarray(buf)
        return 0.5 * (stereo[0] + stereo[1])
    finally:
        del s


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preset-rel", required=True)
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--out", required=True, help="output WAV path (dry)")
    ap.add_argument("--probe", choices=("none", "fm", "width"), default="none")
    ap.add_argument("--probe-json", help="write the probe record JSON here")
    args = ap.parse_args()

    rel = args.preset_rel
    expected_blob = census_blob(rel)
    preset_abs = os.path.join(oc.data_home(), rel[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse(f"preset not found: {preset_abs}")
    actual_blob = oc.git_blob_sha1(preset_abs)
    if actual_blob != expected_blob:
        raise Refuse(f"blob mismatch: {actual_blob} != census {expected_blob}")

    seq, seq_path, seq_sha = rf.load_sequence(args.sequence)
    surgepy = rf.import_surgepy()

    dry = render_variant(surgepy, preset_abs, seq, args.probe)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    rf.oc.write_wav_mono16(args.out, dry, rf.SR)

    rec = {
        "preset": rel,
        "census_blob_sha1": expected_blob,
        "sequence": seq["id"],
        "sequence_sha256": seq_sha,
        "probe": args.probe,
        "wav": args.out,
        "sha256": sha256_file(args.out),
        "frames": len(dry),
        "engine": rf.engine_identity(surgepy, surgepy.createSurge(float(rf.SR))),
    }
    if args.probe != "none":
        base = render_variant(surgepy, preset_abs, seq, "none")
        d = np.abs(base - dry)
        rec["baseline_sha256"] = sha_bytes(np.ascontiguousarray(base).tobytes())
        rec["probe_sha256"] = sha_bytes(np.ascontiguousarray(dry).tobytes())
        rec["bit_identical"] = bool(rec["baseline_sha256"] == rec["probe_sha256"])
        rec["max_abs_diff"] = float(d.max())
        rec["verdict"] = ("INERT (A/B bit-identical)" if rec["bit_identical"]
                          else "NOT INERT (probe differs; A/B evidence FAILS)")
    if args.probe_json:
        with open(args.probe_json, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
    print(json.dumps(rec, indent=2))
    return 0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        return 2 if False else sys.exit(2)
