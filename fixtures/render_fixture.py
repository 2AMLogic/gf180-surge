#!/usr/bin/env python3
"""SXT-012: render versioned fixtures through the pinned native Surge oracle.

Drives the externally pinned engine (surgepy binding) with event sequences
from fixtures/sequences/ and produces:

  - WET renders (unmodified loaded patch, all patch-defined effects active),
  - diagnostic DRY renders (identical engine instance and sequence, with all
    FX slots set to fxt_off through surgepy parameter setters before any
    audio is processed),
  - per-fixture metadata JSON and the aggregate fixtures/manifest.json.

Policies implemented here (normative; see fixtures/README.md):

  RESET      1. fresh surgepy instance per render (createSurge(48000));
             2. loadPatch() of the census-blob-verified preset file;
             3. controller reset on channel 0: pitch bend 0, CC64 0, CC1 0,
                CC11 0, channel pressure 0, allNotesOff();
             4. settle: 0.25 s (240 blocks) of silence processed and
                discarded - fixture t=0 begins after the settle tail.
  SCHEDULING event times are integer samples at 48 kHz; the engine consumes
             events only at compiled block boundaries (32 samples), so each
             event is dispatched before the first block whose start sample is
             >= t (ceil quantization; an event never sounds before its
             scheduled time, at most 31 samples late). Same-block events are
             dispatched in sequence-file order. Sub-block timing is not
             representable through the process API (documented limitation).
  TAIL       render span = last event time + tail_s (default 2.5 s), rounded
             up to whole blocks; identical for wet and dry of a fixture.
  DRY        after the controller reset, all 16 patch FX-slot "type"
             parameters are set to surgepy.constants.fxt_off (0) via
             setParamVal - the official host parameter-change path, which
             makes the engine's loadFx swap every slot to Off at the next
             control pass (the settle pass). After settle, the harness reads
             the types back and refuses to emit a dry fixture unless all 16
             read back as Off. Nothing else differs from the wet render.
  AUDIO      stereo float output downmixed to mono (L+R)/2, written as
             16-bit PCM WAV; samples hard-clipped to [-1, 1] and any clipped
             sample count is recorded. No normalization, no time warping,
             no fade-in/out.
  TEMPO      surgepy exposes no transport-tempo setter; "tempo" events are
             counted and reported (tempo_events_applied=false) but cannot be
             applied mid-render. Renders run at the pinned 120 BPM.

The WAV files are this project's own renders of loaded presets, not
redistributed upstream content.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

# Enforce the pinned interpreter before importing numpy (ABI-specific build).
oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402

SR = 48000
FX_SLOTS = 16
MANIFEST_PATH = os.path.join(REPO, "fixtures", "manifest.json")
SEQ_DIR = os.path.join(REPO, "fixtures", "sequences")
AUDIO_DIR = os.path.join(REPO, "fixtures", "audio")
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
REPEATABILITY_PATH = os.path.join(REPO, "reports", "sxt-012", "repeatability.json")

PILOT_PRESETS = {
    "sub4": "Basses/Sub 4.fxp",
    "koala2": "Leads/Koala 2.fxp",
    "behemoth": "Basses/Behemoth.fxp",
}

EVENT_TYPES = {"note_on", "note_off", "cc", "pitch_bend", "channel_pressure", "tempo"}


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_version():
    """Repo commit at render time + this script's content hash."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "fixtures/sequences", "fixtures/render_fixture.py",
             "fixtures/verify_fixtures.py", "fixtures/diagnose_variation.py", "oracle/"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
        inputs_clean = dirty == ""
    except Exception as e:  # pragma: no cover
        commit, inputs_clean = f"unavailable: {e}", False
    self_sha = sha256_file(os.path.abspath(__file__))
    return {"repo_commit": commit, "pinned_inputs_clean": inputs_clean, "script_sha256": self_sha}


def census_blob(relname):
    """Census blob SHA-1 for a factory preset name, e.g. 'Basses/Sub 4.fxp'."""
    rel = "resources/data/patches_factory/" + relname
    import csv

    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {relname}")


def load_sequence(ref):
    """Load + validate a sequence by id (library) or path (negative controls)."""
    if os.path.sep not in ref and ref.endswith(".json") is False:
        path = os.path.join(SEQ_DIR, ref + ".json")
    else:
        path = ref if os.path.isabs(ref) else os.path.join(os.getcwd(), ref)
    with open(path, "r", encoding="utf-8") as f:
        seq = json.load(f)
    if seq.get("schema_version") != 1:
        raise Refuse(f"{path}: unsupported schema_version")
    if "events" not in seq or not seq["events"]:
        raise Refuse(f"{path}: no events")
    pair_state = {}
    for i, e in enumerate(seq["events"]):
        if e.get("type") not in EVENT_TYPES:
            raise Refuse(f"{path}: event {i} bad type {e.get('type')!r}")
        if not isinstance(e.get("t"), int) or e["t"] < 0:
            raise Refuse(f"{path}: event {i} bad t")
        if e["type"] in ("note_on", "note_off"):
            ch, n = e["channel"], e["note"]
            v = e.get("velocity", 0)
            if not (0 <= v <= 127 and 0 <= n <= 127):
                raise Refuse(f"{path}: event {i} out of range")
            if e["type"] == "note_on":
                if pair_state.get((ch, n)) == "on":
                    raise Refuse(f"{path}: event {i} overlapping note_on {n}")
                pair_state[(ch, n)] = "on"
            else:
                if pair_state.get((ch, n)) != "on":
                    raise Refuse(f"{path}: event {i} note_off without note_on {n}")
                pair_state[(ch, n)] = "off"
        if e["type"] == "cc" and not (0 <= e["controller"] <= 127 and 0 <= e["value"] <= 127):
            raise Refuse(f"{path}: event {i} cc out of range")
        if e["type"] == "pitch_bend" and not (-8192 <= e["value"] <= 8191):
            raise Refuse(f"{path}: event {i} bend out of range")
        if e["type"] == "channel_pressure" and not (0 <= e["value"] <= 127):
            raise Refuse(f"{path}: event {i} pressure out of range")
        if e["type"] == "tempo" and not (20 <= e["bpm"] <= 400):
            raise Refuse(f"{path}: event {i} tempo out of range")
    dangling = [k for k, v in pair_state.items() if v == "on"]
    if dangling:
        raise Refuse(f"{path}: note_on without note_off: {dangling}")
    order = [(e["t"], i) for i, e in enumerate(seq["events"])]
    if order != sorted(order):
        raise Refuse(f"{path}: events not time-sorted")
    return seq, path, sha256_file(path)


def import_surgepy():
    oc.apply_engine_env()
    return oc.import_surgepy()


def engine_identity(surgepy, s):
    so_path = os.path.join(oc.build_dir(), "src", "surge-python")
    so = [f for f in os.listdir(so_path) if f.startswith("surgepy") and f.endswith(".so")]
    with open(os.path.join(REPO, "oracle", "manifest.json"), encoding="utf-8") as f:
        commit = json.load(f)["engine"]["commit"]
    return {
        "engine_commit": commit,
        "engine_version_string": surgepy.getVersion(),
        "surgepy_module": so[0] if so else "unknown",
        "sample_rate": int(s.getSampleRate()),
        "block_size_samples": int(s.getBlockSize()),
        "tempo_bpm": 120,
    }


def dispatch(s, events, block, quant):
    """Dispatch all events whose ceil-quantized block is <= block. Returns index."""
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
        # "tempo" events are counted by the caller; surgepy cannot apply them
        i += 1
    return i


def render_bus(surgepy, preset_abs, seq, fx_off):
    """One full render in a fresh instance. Returns (mono, info)."""
    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse(f"loadPatch failed: {preset_abs}")
        # controller reset (channel 0), defensive on a fresh instance
        s.pitchBend(0, 0)
        s.channelController(0, 64, 0)
        s.channelController(0, 1, 0)
        s.channelController(0, 11, 0)
        s.channelAftertouch(0, 0)
        s.allNotesOff()

        dry_types_after = None
        if fx_off:
            import surgepy.constants as C

            for i in range(FX_SLOTS):
                s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)

        bs = int(s.getBlockSize())
        settle_blocks = int(seq.get("settle_s", 0.25) * SR) // bs
        sbuf = s.createMultiBlock(settle_blocks)
        s.processMultiBlock(sbuf)

        if fx_off:
            import surgepy.constants as C

            types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"])) for i in range(FX_SLOTS)]
            if any(t != C.fxt_off for t in types):
                raise Refuse(f"dry render: FX types did not read back Off: {types}")
            dry_types_after = types

        events = seq["events"]
        tempo_total = sum(1 for e in events if e["type"] == "tempo")
        notes = [e for e in events if e["type"] in ("note_on", "note_off")]
        last_t = max(e["t"] for e in notes) if notes else 0
        tail_s = float(seq.get("tail_s", 2.5))
        total_samples = last_t + int(tail_s * SR)
        total_blocks = -(-total_samples // bs)
        buf = s.createMultiBlock(total_blocks)

        quant = lambda t: -(-t // bs)  # noqa: E731  ceil to block index
        dispatched = 0
        b = 0
        while b < total_blocks:
            nxt = dispatch(s, events[dispatched:], b, quant) + dispatched
            if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                raise Refuse("scheduler failed to advance")
            seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
            s.processMultiBlock(buf, b, seg - b)
            b = seg
            dispatched = nxt

        stereo = np.asarray(buf)
        mono = 0.5 * (stereo[0] + stereo[1])
        samples = total_blocks * bs
        clipped = int(np.sum(np.abs(mono) > 1.0))
        info = {
            "blocks": total_blocks,
            "frames": samples,
            "peak_abs_float": float(np.max(np.abs(mono))) if samples else 0.0,
            "clipped_samples": clipped,
            "tempo_events_total": tempo_total,
            "tempo_events_applied": 0,
            "dry_fx_types_readback": dry_types_after,
            "last_event_sample": int(last_t),
            "tail_s": tail_s,
            "settle_s": float(seq.get("settle_s", 0.25)),
        }
        return mono, info
    finally:
        del s


def fixture_id(preset_slug, seq):
    return f"{preset_slug}__{seq['id']}"


def render_and_record(surgepy, preset_slug, preset_rel, seq, seq_path, seq_sha, out_dir):
    """Render wet+dry, write WAVs + sidecar. Returns sidecar dict."""
    fid = fixture_id(preset_slug, seq)
    preset_abs = os.path.join(oc.data_home(), "patches_factory", preset_rel)
    actual_blob = oc.git_blob_sha1(preset_abs)
    expected_blob = census_blob(preset_rel)
    if actual_blob != expected_blob:
        raise Refuse(f"preset blob {actual_blob} != census {expected_blob}: {preset_rel}")

    wet, wet_info = render_bus(surgepy, preset_abs, seq, fx_off=False)
    dry, dry_info = render_bus(surgepy, preset_abs, seq, fx_off=True)

    os.makedirs(out_dir, exist_ok=True)
    wet_path = os.path.join(out_dir, f"{seq['id']}-wet.wav")
    dry_path = os.path.join(out_dir, f"{seq['id']}-dry.wav")
    oc.write_wav_mono16(wet_path, wet, SR)
    oc.write_wav_mono16(dry_path, dry, SR)

    sidecar = {
        "schema_version": 1,
        "fixture_id": fid,
        "preset": {
            "slug": preset_slug,
            "path": "resources/data/patches_factory/" + preset_rel,
            "census_blob_sha1": expected_blob,
            "actual_blob_sha1": actual_blob,
        },
        "sequence": {"id": seq["id"], "sha256": seq_sha, "path": os.path.relpath(seq_path, REPO)},
        "render": {
            "sample_rate": SR,
            "scheduling": "block-quantized (32 samples), ceil to next block start",
            "duration_s": round(wet_info["frames"] / SR, 6),
        },
        "wet": {
            "wav": os.path.relpath(wet_path, REPO),
            "sha256": sha256_file(wet_path),
            "bytes": os.path.getsize(wet_path),
            **wet_info,
        },
        "dry": {
            "wav": os.path.relpath(dry_path, REPO),
            "sha256": sha256_file(dry_path),
            "bytes": os.path.getsize(dry_path),
            "bypass_method": "all 16 FX-slot type params set to fxt_off via setParamVal "
                             "before settle; read-back verified Off; otherwise identical "
                             "fresh-instance render",
            **{k: v for k, v in dry_info.items() if k != "dry_fx_types_readback"},
            "dry_fx_bypass_verified": dry_info["dry_fx_types_readback"] == [0] * FX_SLOTS,
        },
        "audio_policy": "mono (L+R)/2, int16 PCM, hard clip to [-1,1], no normalization, "
                        "no time warping, no fades",
        "tool": tool_version(),
        "engine": engine_identity(surgepy, surgepy.createSurge(float(SR))),
    }
    sidecar_path = os.path.join(out_dir, f"{seq['id']}.json")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    return sidecar


def rebuild_manifest(surgepy):
    """Rebuild fixtures/manifest.json from all sidecars on disk."""
    sidecars = []
    for root, _dirs, files in os.walk(AUDIO_DIR):
        for fn in sorted(files):
            if fn.endswith(".json") and not fn.endswith(".wav.json"):
                p = os.path.join(root, fn)
                with open(p, encoding="utf-8") as f:
                    sidecars.append(json.load(f))
    sidecars.sort(key=lambda sc: sc["fixture_id"])
    seqs = {}
    for fn in sorted(os.listdir(SEQ_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(SEQ_DIR, fn), encoding="utf-8") as f:
                seqs[json.load(f)["id"]] = sha256_file(os.path.join(SEQ_DIR, fn))
    presets = {}
    for sc in sidecars:
        presets[sc["preset"]["slug"]] = {
            "path": sc["preset"]["path"],
            "census_blob_sha1": sc["preset"]["census_blob_sha1"],
        }
    fixtures = []
    total_bytes = 0
    for sc in sidecars:
        total_bytes += sc["wet"]["bytes"] + sc["dry"]["bytes"]
        fixtures.append(
            {
                "fixture_id": sc["fixture_id"],
                "preset": sc["preset"]["slug"],
                "sequence": sc["sequence"]["id"],
                "duration_s": sc["render"]["duration_s"],
                "frames": sc["wet"]["frames"],
                "wet": {"wav": sc["wet"]["wav"], "sha256": sc["wet"]["sha256"]},
                "dry": {"wav": sc["dry"]["wav"], "sha256": sc["dry"]["sha256"]},
                "sidecar": os.path.relpath(
                    os.path.join(AUDIO_DIR, sc["preset"]["slug"], sc["sequence"]["id"] + ".json"),
                    REPO,
                ),
            }
        )
    manifest = {
        "manifest_version": 1,
        "issue": "SXT-012",
        "claim_scope": "reference-vs-reference fixtures only; no fidelity, support, or "
                       "quality claim is made by or for these fixtures",
        "generated_by": {"tool": "fixtures/render_fixture.py", **tool_version()},
        "engine": engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "sequence_library": seqs,
        "presets": presets,
        "policies": {
            "reset": "fresh instance per bus render; blob-verified patch load; controller "
                     "reset (bend/CC64/CC1/CC11/pressure/allNotesOff); settle 0.25 s "
                     "discarded before t=0",
            "scheduling": "event t = integer samples @48 kHz, ceil-quantized to 32-sample "
                          "block starts; same-block events in file order; sub-block timing "
                          "not representable via surgepy process API",
            "tail": "render = last event + tail_s (default 2.5 s), whole blocks; identical "
                    "for wet and dry; long-tail presets will need larger per-sequence tails",
            "audio": "mono (L+R)/2, 16-bit PCM, hard clip [-1,1] with clipped count recorded; "
                     "raw renders - no normalization, no time warping, no fades",
            "dry": "all 16 FX-slot types -> fxt_off via setParamVal before settle; read-back "
                   "verified; wet renders remain the unmodified product reference",
            "tempo": "surgepy cannot set transport tempo; tempo events recorded, applied=0; "
                     "renders at pinned 120 BPM",
        },
        "fixtures": fixtures,
        "totals": {
            "fixture_count": len(fixtures),
            "wav_count": 2 * len(fixtures),
            "audio_bytes": total_bytes,
        },
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return manifest


def cmd_render(args):
    surgepy = import_surgepy()
    seq, seq_path, seq_sha = load_sequence(args.sequence)
    if args.preset_file:
        preset_slug = os.path.splitext(os.path.basename(args.preset_file))[0].replace(" ", "_")
        preset_rel = args.preset_file
        preset_abs = args.preset_file if os.path.isabs(args.preset_file) else os.path.join(
            oc.data_home(), "patches_factory", preset_rel
        )
        out_dir = args.out or os.path.join(os.getcwd(), "render-out")
        os.makedirs(out_dir, exist_ok=True)
        wet, winfo = render_bus(surgepy, preset_abs, seq, fx_off=False)
        dry, dinfo = render_bus(surgepy, preset_abs, seq, fx_off=True)
        wp = os.path.join(out_dir, f"{seq['id']}-wet.wav")
        dp = os.path.join(out_dir, f"{seq['id']}-dry.wav")
        oc.write_wav_mono16(wp, wet, SR)
        oc.write_wav_mono16(dp, dry, SR)
        print(json.dumps({"sequence": seq["id"], "preset": preset_rel, "wet": wp,
                          "dry": dp, "wet_sha256": sha256_file(wp),
                          "dry_sha256": sha256_file(dp), "frames": winfo["frames"]}, indent=2))
        return 0

    if args.preset not in PILOT_PRESETS:
        raise Refuse(f"unknown preset slug {args.preset!r}; known: {sorted(PILOT_PRESETS)}")
    preset_rel = PILOT_PRESETS[args.preset]
    out_dir = os.path.join(AUDIO_DIR, args.preset)
    sidecar = render_and_record(
        surgepy, args.preset, preset_rel, seq, seq_path, seq_sha, out_dir
    )
    manifest = rebuild_manifest(surgepy)
    print(json.dumps({"fixture_id": sidecar["fixture_id"], "wet_sha256": sidecar["wet"]["sha256"],
                      "dry_sha256": sidecar["dry"]["sha256"],
                      "audio_bytes_total": manifest["totals"]["audio_bytes"]}, indent=2))
    return 0


def cmd_render_all(args):
    surgepy = import_surgepy()
    seqs = sorted(fn[:-5] for fn in os.listdir(SEQ_DIR) if fn.endswith(".json") and fn != "generate_sequences.py")
    presets = args.presets.split(",") if args.presets else sorted(PILOT_PRESETS)
    for slug in presets:
        if slug not in PILOT_PRESETS:
            raise Refuse(f"unknown preset slug {slug!r}")
    for slug in presets:
        for sid in seqs:
            seq, seq_path, seq_sha = load_sequence(sid)
            sidecar = render_and_record(surgepy, slug, PILOT_PRESETS[slug], seq, seq_path, seq_sha,
                                        os.path.join(AUDIO_DIR, slug))
            print(f"rendered {sidecar['fixture_id']}: wet {sidecar['wet']['sha256'][:12]}… "
                  f"dry {sidecar['dry']['sha256'][:12]}… peak {sidecar['wet']['peak_abs_float']:.4f}")
    manifest = rebuild_manifest(surgepy)
    print(json.dumps(manifest["totals"], indent=2))
    return 0


def variation_metrics(a, b):
    d = np.abs(a - b)
    first = int(np.argmax(d > 0)) if (d > 0).any() else None
    return {
        "max_abs_diff": float(d.max()),
        "mean_abs_diff": float(d.mean()),
        "first_divergence_sample": first,
    }


def cmd_repeatability(args):
    surgepy = import_surgepy()
    seqs = sorted(fn[:-5] for fn in os.listdir(SEQ_DIR) if fn.endswith(".json") and fn != "generate_sequences.py")
    presets = args.presets.split(",") if args.presets else sorted(PILOT_PRESETS)
    results = []
    for slug in presets:
        preset_rel = PILOT_PRESETS[slug]
        preset_abs = os.path.join(oc.data_home(), "patches_factory", preset_rel)
        expected_blob = census_blob(preset_rel)
        actual_blob = oc.git_blob_sha1(preset_abs)
        if actual_blob != expected_blob:
            raise Refuse(f"preset blob mismatch: {preset_rel}")
        for sid in seqs:
            seq, _p, seq_sha = load_sequence(sid)
            entry = {
                "fixture_id": fixture_id(slug, seq),
                "preset": slug,
                "sequence": sid,
                "sequence_sha256": seq_sha,
                "preset_census_blob_sha1": expected_blob,
                "repeats": args.repeats,
                "wet": {"sha256": [], "bit_identical": None},
                "dry": {"sha256": [], "bit_identical": None},
            }
            for bus, fx_off in (("wet", False), ("dry", True)):
                renders, hashes = [], []
                for _ in range(args.repeats):
                    mono, _info = render_bus(surgepy, preset_abs, seq, fx_off=fx_off)
                    hashes.append(hashlib.sha256(np.ascontiguousarray(mono).tobytes()).hexdigest())
                    renders.append(mono)
                ident = all(h == hashes[0] for h in hashes)
                e = entry[bus]
                e["sha256"] = hashes
                e["bit_identical"] = ident
                if not ident:
                    e["variation_vs_render1"] = [
                        variation_metrics(renders[0], renders[i]) for i in range(1, args.repeats)
                    ]
                    e["peak_abs_float_render1"] = float(np.max(np.abs(renders[0])))
                    e["relative_max_diff"] = [
                        round(v["max_abs_diff"] / max(e["peak_abs_float_render1"], 1e-12), 6)
                        for v in e["variation_vs_render1"]
                    ]
            results.append(entry)
            print(f"{entry['fixture_id']}: wet identical={entry['wet']['bit_identical']} "
                  f"dry identical={entry['dry']['bit_identical']}")
    out = {
        "schema_version": 1,
        "issue": "SXT-012",
        "claim_scope": "reference-vs-reference repeatability of the pinned engine under this "
                       "harness only. This is NOT model-vs-reference fidelity, NOT RTL "
                       "agreement, and NOT a support or quality claim.",
        "method": "each fixture re-rendered N times, each render in a fresh surgepy instance "
                  "(full reset policy), sha256 of raw float mono buffer compared; "
                  "non-identical fixtures quantified vs render 1",
        "repeats": args.repeats,
        "engine": engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "tool": tool_version(),
        "fixtures": results,
        "summary": {
            "fixtures": len(results),
            "bit_identical_wet": sum(1 for r in results if r["wet"]["bit_identical"]),
            "bit_identical_dry": sum(1 for r in results if r["dry"]["bit_identical"]),
            "quantified_variation": sum(1 for r in results
                                        if not (r["wet"]["bit_identical"] and r["dry"]["bit_identical"])),
        },
    }
    os.makedirs(os.path.dirname(REPEATABILITY_PATH), exist_ok=True)
    with open(REPEATABILITY_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(out["summary"], indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("render", help="render one fixture (wet+dry) and update the manifest")
    p.add_argument("--preset", help="pilot preset slug (sub4|koala2|behemoth)")
    p.add_argument("--sequence", help="sequence id or JSON path")
    p.add_argument("--preset-file", help="render an arbitrary preset file (no manifest write)")
    p.add_argument("--out", help="output dir for --preset-file mode")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("render-all", help="render the full pilot set")
    p.add_argument("--presets", help="comma-separated slugs (default all)")
    p.set_defaults(func=cmd_render_all)

    p = sub.add_parser("repeatability", help="re-render each fixture N times, report hashes")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--presets", help="comma-separated slugs (default all)")
    p.set_defaults(func=cmd_repeatability)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
