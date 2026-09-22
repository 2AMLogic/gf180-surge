#!/usr/bin/env python3
"""SXT-028a reference fixtures: tapped slot-boundary renders of the AW-49
(Galactic) carriers through the pinned engine on the oracle host.

Runs ONLY where the DR-0006 instrumented build exists (ORACLE_BUILD_DIR_REL
= build-py311-aw49 built from the sxt028a-tap branch next to the pinned
checkout); fails closed (exit 3) elsewhere. Renders inherit the SXT-012/023
policies via fixtures/render_fixture.py (controller reset, 0.25 s settle,
block-quantized scheduling, tail).

Per fixture (all 'conditioned-on-tap' repeatability class: scene drift > 0
and/or wall-clock-seeded aw49 vibrato randomization - measured):

  * taps-ON render: wet WAV + binary taps (adapter-boundary in/out blocks
    per Airwindows slot, Galactic constructor fpd seeds, per-sample Galactic
    internal state incl. vibM) -> fixture npz + sidecar.
  * DSP-neutrality gate (DR-0005 adapted for nondeterministic fixtures): a
    PROBE render (same fixture; scene drift and aw49 Modulation forced to 0
    via setParamVal -> deterministic class) must be bit-identical taps-off
    x2, then taps-ON vs taps-OFF bit-identical. The structural side is
    pinned separately (sxt028a-tap single-commit diff, DR-0006).
  * cross-build check: the same probe on the pre-existing build-py311 tree
    (SXT-037 tap branch; FX-path DSP-identical per DR-0005) must be
    bit-identical to the patched build's taps-off probe (child process:
    pybind11 allows one module registration per process).

No complete-wet fixture claims: every carrier has unlanded sibling FX
(extraction applicability record); the comparison is slot-boundary only.

Original tool, Apache-2.0; imports the GPL engine at runtime only.
"""

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "fixtures"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402
import render_fixture as rf  # noqa: E402

SR = 48000
BUILD = os.path.join(oc.engine_dir(),
                     os.environ.get("ORACLE_BUILD_DIR_REL", "build-py311-aw49"))
BUILD_BASELINE = os.path.join(oc.engine_dir(), "build-py311")
TAP_LIB = os.path.join(BUILD, "src", "surge-python")

PRESETS = {
    "temple": "resources/data/patches_3rdparty/Altenberg/Guitars/Temple.fxp",
    "unity": "resources/data/patches_3rdparty/Altenberg/Pads/Unity.fxp",
    "fmod09": "resources/data/patches_factory/Tutorials/Formula Modulator/09 Example - Crossfading Oscillators.fxp",
}
SEQUENCES = ["seq-notes-coverage-v1", "seq-poly-8-v1"]

CROSSBUILD_SNIPPET = r"""
import sys, os, hashlib
repo, engine, seq_id, aw49_slot, tap_dir, out_dir = sys.argv[1:7]
aw49_slot = int(aw49_slot)
sys.path.insert(0, repo)
sys.path.insert(0, os.path.join(repo, "oracle"))
sys.path.insert(0, os.path.join(repo, "fixtures"))
import oracle_common as oc
oc.reexec_under_pinned_python(repo)
surgepy = oc.import_surgepy()
oc.apply_engine_env()
os.environ["SXT028A_TAP_DIR"] = tap_dir
import render_fixture as rf
import numpy as np
seq, _, _ = rf.load_sequence(seq_id)


def render_once(surgepy, preset_abs, seq):
    s2 = surgepy.createSurge(48000.0)
    try:
        if not s2.loadPatch(preset_abs):
            raise SystemExit(2)
        s2.pitchBend(0, 0); s2.channelController(0, 64, 0)
        s2.channelController(0, 1, 0); s2.channelController(0, 11, 0)
        s2.channelAftertouch(0, 0); s2.allNotesOff()
        bs = int(s2.getBlockSize())
        sb = int(seq.get("settle_s", 0.25) * 48000) // bs
        s2.processMultiBlock(s2.createMultiBlock(sb))
        notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
        last_t = max(e["t"] for e in notes) if notes else 0
        total = -(-(last_t + int(float(seq.get("tail_s", 2.5)) * 48000)) // bs)
        buf = s2.createMultiBlock(total)
        quant = lambda t: -(-t // bs)
        disp = 0; b = 0
        while b < total:
            nxt = rf.dispatch(s2, seq["events"][disp:], b, quant) + disp
            seg = total if nxt >= len(seq["events"]) else max(quant(seq["events"][nxt]["t"]), b + 1)
            s2.processMultiBlock(buf, b, seg - b); b = seg; disp = nxt
        return np.asarray(buf, dtype=np.float32).copy(), total
    finally:
        del s2


s = surgepy.createSurge(48000.0)
s.loadPatch(engine)
patch = s.getPatch()
sm = int(s.getParamVal(patch["scenemode"]))
sa = int(s.getParamVal(patch["scene_active"]))
for v in ([sa] if sm == 0 else [0, 1]):
    s.setParamVal(patch["scene"][v]["drift"], 0.0)
s.setParamVal(patch["fx"][aw49_slot]["p"][3], 0.0)
del s

# probe: forced-deterministic state via a fresh instance
s3 = surgepy.createSurge(48000.0)
s3.loadPatch(engine)
patch = s3.getPatch()
sm = int(s3.getParamVal(patch["scenemode"]))
sa = int(s3.getParamVal(patch["scene_active"]))
for v in ([sa] if sm == 0 else [0, 1]):
    s3.setParamVal(patch["scene"][v]["drift"], 0.0)
s3.setParamVal(patch["fx"][aw49_slot]["p"][3], 0.0)
probe, _ = render_once(surgepy, engine, seq)
print(hashlib.sha256(np.ascontiguousarray(probe).tobytes()).hexdigest())
"""


class Refuse(Exception):
    pass


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_buf(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def write_wav_stereo_f32(path, stereo):
    nch, frames = stereo.shape
    data = np.ascontiguousarray(stereo.T, dtype="<f4").tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, nch, SR, SR * nch * 4, nch * 4, 32)
    hdr += b"data" + struct.pack("<I", len(data))
    with open(path, "wb") as f:
        f.write(hdr + data)


def import_surgepy_from(so_dir):
    so = so_dir
    if not os.path.isdir(so) or not any(
            f.startswith("surgepy") and f.endswith(".so") for f in os.listdir(so)):
        raise Refuse(f"no surgepy build at {so_dir}")
    if so not in sys.path:
        sys.path.insert(0, so)
    import surgepy  # noqa: PLC0415
    return surgepy


def render_once(surgepy, preset_abs, seq):
    """One fresh-instance render under the SXT-012 policies (single render:
    the fixtures are conditioned-on-tap class - no 3x determinism gate)."""
    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse(f"loadPatch failed: {preset_abs}")
        s.pitchBend(0, 0)
        s.channelController(0, 64, 0)
        s.channelController(0, 1, 0)
        s.channelController(0, 11, 0)
        s.channelAftertouch(0, 0)
        s.allNotesOff()
        bs = int(s.getBlockSize())
        settle_blocks = int(seq.get("settle_s", 0.25) * SR) // bs
        s.processMultiBlock(s.createMultiBlock(settle_blocks))
        notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
        last_t = max(e["t"] for e in notes) if notes else 0
        total_samples = last_t + int(float(seq.get("tail_s", 2.5)) * SR)
        total_blocks = -(-total_samples // bs)
        buf = s.createMultiBlock(total_blocks)
        quant = lambda t: -(-t // bs)  # noqa: E731
        dispatched = 0
        b = 0
        while b < total_blocks:
            nxt = rf.dispatch(s, seq["events"][dispatched:], b, quant) + dispatched
            if nxt < len(seq["events"]) and quant(seq["events"][nxt]["t"]) <= b:
                raise Refuse("scheduler failed to advance")
            seg = total_blocks if nxt >= len(seq["events"]) else max(quant(seq["events"][nxt]["t"]), b + 1)
            s.processMultiBlock(buf, b, seg - b)
            b = seg
            dispatched = nxt
        return np.asarray(buf, dtype=np.float32).copy(), total_blocks
    finally:
        del s


def probe_render(surgepy, preset_abs, seq, aw49_slot):
    """Deterministic-class probe: scene drift and aw49 Modulation forced to
    0 so the render is bit-reproducible (required by the neutrality gate;
    the fixtures themselves are NOT in that class)."""
    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse("loadPatch failed (probe)")
        patch = s.getPatch()
        sm = int(s.getParamVal(patch["scenemode"]))
        sa = int(s.getParamVal(patch["scene_active"]))
        for v in ([sa] if sm == 0 else [0, 1]):
            s.setParamVal(patch["scene"][v]["drift"], 0.0)
        s.setParamVal(patch["fx"][aw49_slot]["p"][3], 0.0)  # aw49 C (Modulation)
        out, _ = render_once(surgepy, preset_abs, seq)
        return out
    finally:
        del s


def parse_iostream(path):
    raw = open(path, "rb").read()
    off = 0
    recs = {}
    while off < len(raw):
        tag, slot, algid, sq, n = struct.unpack_from("<iiiII", raw, off)
        off += 20
        if tag != 1:
            raise Refuse("bad tap record tag")
        data = np.frombuffer(raw, dtype="<f4", count=4 * n, offset=off).reshape(n, 4)
        off += 16 * n
        recs.setdefault((slot, algid), []).append((sq, data))
    return recs


def parse_fpd(path):
    raw = open(path, "rb").read()
    out = []
    off = 0
    while off < len(raw):
        tag, l, r = struct.unpack_from("<III", raw, off)
        off += 12
        if tag != 2:
            raise Refuse("bad fpd record tag")
        out.append((l, r))
    return out


def parse_galstate(path):
    raw = open(path, "rb").read()
    n = len(raw) // 56
    dt = np.dtype([("vibM", "<f8"), ("oldfpd", "<f8"), ("countM", "<i4"),
                   ("iirAL", "<f8"), ("iirBL", "<f8"), ("countI", "<i4"),
                   ("fbAL", "<f8"), ("fbAR", "<f8")])
    return np.frombuffer(raw[:n * 56], dtype=dt)


def run_fixture(slug, rel_path, seq_id, out_dir):
    seq, seq_path, seq_sha = rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    fxin = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs",
                                       f"aw-49-{slug}.json")))
    blob = fxin["census_blob_sha1"]
    if oc.git_blob_sha1(abs_path) != blob:
        raise Refuse(f"census blob mismatch: {rel_path}")
    aw49_slot = fxin["aw49_slot"]

    surgepy = import_surgepy_from(TAP_LIB)
    oc.apply_engine_env()

    tap_on = os.path.join(out_dir, f"tmp-{slug}-{seq_id}-on")
    tap_off = os.path.join(out_dir, f"tmp-{slug}-{seq_id}-off")
    tap_probe = os.path.join(out_dir, f"tmp-{slug}-{seq_id}-probe")
    for d in (tap_on, tap_off, tap_probe):
        os.makedirs(d, exist_ok=True)

    # taps-ON fixture render
    os.environ["SXT028A_TAP_DIR"] = tap_on
    wet, total_blocks = render_once(surgepy, abs_path, seq)

    # neutrality probes (probe renders: dedicated tap dirs so the fixture
    # tap files stay exact)
    os.environ["SXT028A_TAP_DIR"] = tap_probe
    probe_on = _probe(surgepy, abs_path, seq, aw49_slot)
    os.environ["SXT028A_TAP_DIR"] = tap_off
    probe_off = _probe(surgepy, abs_path, seq, aw49_slot)
    probe_off2 = _probe(surgepy, abs_path, seq, aw49_slot)
    os.environ.pop("SXT028A_TAP_DIR", None)
    neutral_deterministic = sha256_buf(probe_off) == sha256_buf(probe_off2)
    neutral_gate = neutral_deterministic and sha256_buf(probe_on) == sha256_buf(probe_off)

    # cross-build probe (baseline build, taps off; child process)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(BUILD_BASELINE, "src", "surge-python") + \
        ":" + env.get("PYTHONPATH", "")
    env["SXT028A_TAP_DIR"] = tap_off
    env["ORACLE_SURGE_DIR"] = oc.engine_dir()
    r = subprocess.run(
        [sys.executable, "-c", CROSSBUILD_SNIPPET, REPO, abs_path, seq_id,
         str(aw49_slot), tap_off, out_dir],
        env=env, capture_output=True, text=True, timeout=3600)
    cross_build = None
    if r.returncode == 0:
        base_sha = r.stdout.strip().splitlines()[-1]
        cross_build = base_sha == sha256_buf(probe_off)
    else:
        print("cross-build probe failed:", (r.stderr or "")[-400:])

    # parse taps
    recs = parse_iostream(os.path.join(tap_on, "aw_iostream.bin"))
    key = (aw49_slot, 49)
    if key not in recs:
        raise Refuse(f"no tap records for slot {aw49_slot} alg 49")
    series = recs[key]
    gal_in = np.stack([d[:, :2] for _, d in series])
    gal_out = np.stack([d[:, 2:4] for _, d in series])
    if len(gal_in) != total_blocks:
        raise Refuse(f"tap blocks {len(gal_in)} != render blocks {total_blocks}")
    fpds = parse_fpd(os.path.join(tap_on, "aw_fpd.bin"))
    galstate = parse_galstate(os.path.join(tap_on, "aw_galstate.bin"))
    if len(galstate) != total_blocks * 32:
        raise Refuse(f"galstate records {len(galstate)} != frames {total_blocks * 32}")

    stem = f"{slug}__{seq_id}"
    npz_path = os.path.join(out_dir, f"{stem}-aw49-taps.npz")
    np.savez_compressed(
        npz_path,
        gal_in=gal_in, gal_out=gal_out,
        vibM=np.asarray(galstate["vibM"], dtype="<f8"),
        oldfpd=np.asarray(galstate["oldfpd"], dtype="<f8"),
        countM=np.asarray(galstate["countM"], dtype="<i4"),
        countI=np.asarray(galstate["countI"], dtype="<i4"),
        iirAL=np.asarray(galstate["iirAL"], dtype="<f8"),
        iirBL=np.asarray(galstate["iirBL"], dtype="<f8"),
        fbAL=np.asarray(galstate["fbAL"], dtype="<f8"),
        fbAR=np.asarray(galstate["fbAR"], dtype="<f8"),
    )
    wav_path = os.path.join(out_dir, f"{stem}-wet.f32.wav")
    write_wav_stereo_f32(wav_path, wet)

    sidecar = {
        "schema_version": 1,
        "fixture_id": stem,
        "leaf": "SXT-028a",
        "claim_scope": "tapped slot-boundary reference of the pinned engine; "
                       "no fidelity/support/quality claim; complete-wet "
                       "renders refused (unlanded sibling FX classes)",
        "applicability_complete_wet_possible":
            fxin["applicability"]["complete_wet_render_possible"],
        "preset": {"slug": slug, "path": rel_path, "census_blob_sha1": blob,
                   "aw49_slot": aw49_slot},
        "sequence": {"id": seq_id, "sha256": seq_sha},
        "render": {"sample_rate": SR, "block_size": 32,
                   "blocks": int(total_blocks), "frames": int(total_blocks) * 32,
                   "tail_s": seq.get("tail_s", 2.5),
                   "settle_s": seq.get("settle_s", 0.25),
                   "policies": "fixtures/render_fixture.py (reset/scheduling/"
                               "tail); single render - conditioned-on-tap "
                               "repeatability class (no 3x gate; cross-instance "
                               "spread measured in EVIDENCE.md)"},
        "audio_policy": "stereo float32 (IEEE fmt 3), raw engine output, no "
                        "clip, no normalization, no fades",
        "taps": {
            "record_layout": "aw_iostream.bin {tag=1,slot,algid,seq,n}+n*"
                             "{inL,inR,outL,outR} f32; aw_fpd.bin {tag=2,"
                             "fpdL,fpdR}; aw_galstate.bin 56B/sample",
            "fpd_records": [list(x) for x in fpds],
            "aw_slot_record_counts": {f"{s}-{a}": len(v)
                                      for (s, a), v in recs.items()},
            "galactic_blocks": int(len(gal_in)),
            "npz": os.path.relpath(npz_path, REPO),
            "npz_sha256": sha256_file(npz_path),
        },
        "neutrality_gate": {
            "method": "DR-0005 adapted for nondeterministic fixtures: probe "
                      "(scene drift=0 and aw49 C=0 via setParamVal) must be "
                      "bit-identical taps-off x2, then taps-on == taps-off; "
                      "structural side pinned by the sxt028a-tap "
                      "single-commit diff (DR-0006)",
            "probe_deterministic_taps_off_x2": neutral_deterministic,
            "probe_taps_on_eq_taps_off": neutral_gate,
            "cross_build_baseline_eq": cross_build,
            "baseline_build": "build-py311 (sxt037-tap tree; FX-path "
                              "DSP-identical per DR-0005)",
        },
        "wet": {"wav": os.path.relpath(wav_path, REPO),
                "sha256": sha256_file(wav_path),
                "peak_abs_float": float(np.abs(wet).max())},
        "engine": rf.engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "tap_build": os.path.basename(BUILD),
    }
    sp = os.path.join(out_dir, f"{stem}.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    for d in (tap_on, tap_off, tap_probe):
        for fn in os.listdir(d):
            os.unlink(os.path.join(d, fn))
        os.rmdir(d)
    print(f"rendered {stem}: blocks={total_blocks} "
          f"neutrality(on==off)={neutral_gate} cross_build={cross_build}")
    return sidecar


def _probe(surgepy, abs_path, seq, aw49_slot):
    return probe_render(surgepy, abs_path, seq, aw49_slot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports", "sxt-028a", "fixtures"))
    ap.add_argument("--slugs", help="comma-separated subset")
    ap.add_argument("--seqs", help="comma-separated subset")
    args = ap.parse_args()
    if not os.path.isdir(TAP_LIB):
        print(f"REFUSING: instrumented build not found at {TAP_LIB}; this "
              "tool runs only on the oracle host with the sxt028a-tap build "
              "(DR-0006)", file=sys.stderr)
        return 3
    slugs = args.slugs.split(",") if args.slugs else sorted(PRESETS)
    seqs = args.seqs.split(",") if args.seqs else SEQUENCES
    refused = []
    for slug in slugs:
        for seq_id in seqs:
            try:
                run_fixture(slug, PRESETS[slug], seq_id, args.out_dir)
            except Refuse as e:
                print(f"REFUSED {slug}/{seq_id}: {e}")
                refused.append((slug, seq_id, str(e)))
    if refused:
        for r in refused:
            print(f"REFUSED: {r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
