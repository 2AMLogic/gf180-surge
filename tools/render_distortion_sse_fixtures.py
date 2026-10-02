#!/usr/bin/env python3
"""SXT-028e-sse reference fixtures (issue #136): the Distortion SSE branch.

Inherits the SXT-023 fixture policy by importing `tools/render_fx_fixtures.py`
(fresh instance per bus, controller reset, 0.25 s settle, block-quantized
scheduling, identical tails, 3x bit-identical determinism gate, stereo float32
IEEE WAV, no clipping, no normalization, no fades) and the SXT-028c Chorus
pair's bundle shape.

TWO CARRIER FAMILIES, and the record keeps them apart
=====================================================
1. **Corpus carriers** — the three #121 inventory carriers. This tool
   ATTEMPTS each one and records the measured reason it cannot be rendered.
   None of them is committed as a fixture: `Trance Pluck` and `Mutant Lo-Fi
   Acoustic …` fail the static SXT-012 screens (modulation into FX
   parameters, drift, retrigger), and `Reverse Crash` passes those screens
   but FAILS the empirical 3x bit-identical determinism gate — in its ALL-OFF
   DRY bus, i.e. in the voice layer, before any FX. (Same class as SXT-028c's
   `dronebee`/`melon`.) A render that cannot be produced is **NOT_RUN**,
   never a pass, and no fixture and no `compare-*.json` is written for it.

2. **Declared synthetic carriers** — `tools/distortion_sse_synthetic.py`,
   five of them, one per shaper, constructed in the pinned engine and
   labelled `DECLARED-SYNTHETIC` in every artifact they touch. They carry no
   corpus reach and no support claim. They exist because the issue's
   acceptance requires a measured reference number and the corpus cannot
   supply one for ANY of the five shapers.

BUNDLE LEGS (per carrier x sequence)
====================================
  `original`      the unmodified synthetic wet reference (both Distortion
                  instances active)
  `bypass-fx0`    scene-A insert slot switched Off; the send instance still
                  wet. The `original` wet reference is NOT modified — the
                  bypass leg is an ADDITIONAL reference bus.
  `bypass-fx4`    send-1 slot switched Off; the insert instance still wet
  `dry`           all 16 FX slots Off (the model's declared input bus)

Every leg is rendered 3x in fresh instances and refused unless all three
buffers are bit-identical. Tails are the sequence's own declared tail, which
is checked to span at least the effect's declared 1600-block ring-out window.

HARNESS/HOST CONTROL (`--control`)
==================================
Re-renders the committed SXT-028c `fmcombo` wet bus and compares its sha256
with the committed one. That equality is what makes a determinism REFUSAL
above a statement about the preset rather than about this host: if the
control fails, nothing else in this tool should be believed.

Original tool, Apache-2.0; drives the GPL engine at runtime only.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "fixtures"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402
import distortion_sse_synthetic as syn  # noqa: E402
import render_fx_fixtures as rfx  # noqa: E402  (SXT-023 policies inherited)
from refusal import Refuse  # noqa: E402

SR = 48000
FX_SLOTS = 16
LEAF = "SXT-028e-sse"
SEQUENCES = ["seq-notes-coverage-v1", "seq-poly-8-v1"]

# The effect's declared ring-out window (DistortionEffect.h:48, reused from
# #57 and recorded in reports/SXT-028e-sse/EVIDENCE.md section 6).
RINGOUT_BLOCKS = 1600
BLOCK = 32

CORPUS_CARRIERS = {
    "reversecrash": "resources/data/patches_3rdparty/Damon Armani/Drums/"
                    "Reverse Crash.fxp",
    "trancepluck": "resources/data/patches_3rdparty/Damon Armani/Plucks/"
                   "Trance Pluck.fxp",
    "mutantlofiacoustic": "resources/data/patches_3rdparty/Kinsey Dulcet/"
                          "Guitars/Mutant Lo-Fi Acoustic Guitar "
                          "Workstation.fxp",
}
CONTROL_PRESET = "resources/data/patches_factory/Basses/FM Combo.fxp"
CONTROL_SIDECAR = os.path.join(REPO, "reports", "SXT-028c", "fixtures",
                               "fmcombo__seq-notes-coverage-v1.json")


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def _render_once(surgepy, preset_abs, seq, mutate):
    """One render in a fresh instance, SXT-023 policies verbatim.

    `mutate(s, settle_blocks)` is called after the controller reset and is
    responsible for the whole settle (that is what lets the synthetic
    construction interleave its single FX-rebuild block with the settle).
    `mutate=None` reproduces `render_fx_fixtures.render_bus_stereo(..., False)`
    exactly, which `--control` relies on.
    """
    import surgepy.constants as C  # noqa: F401, PLC0415

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
        info = {}
        if mutate is None:
            s.processMultiBlock(s.createMultiBlock(settle_blocks))
        else:
            info = mutate(s, settle_blocks) or {}
        events = seq["events"]
        notes = [e for e in events if e["type"] in ("note_on", "note_off")]
        last_t = max(e["t"] for e in notes) if notes else 0
        tail_s = float(seq.get("tail_s", 2.5))
        total_samples = last_t + int(tail_s * SR)
        total_blocks = -(-total_samples // bs)
        buf = s.createMultiBlock(total_blocks)
        quant = lambda t: -(-t // bs)  # noqa: E731
        dispatched = 0
        b = 0
        while b < total_blocks:
            nxt = rfx.rf.dispatch(s, events[dispatched:], b, quant) + dispatched
            if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                raise Refuse("scheduler failed to advance")
            seg = (total_blocks if nxt >= len(events)
                   else max(quant(events[nxt]["t"]), b + 1))
            s.processMultiBlock(buf, b, seg - b)
            b = seg
            dispatched = nxt
        stereo = np.asarray(buf, dtype=np.float32).copy()
        info.update({
            "blocks": total_blocks,
            "frames": total_blocks * bs,
            "last_event_sample": last_t,
            "tail_s": tail_s,
            "settle_blocks": settle_blocks,
            "peak_abs": float(np.max(np.abs(stereo))) if stereo.size else 0.0,
        })
        return stereo, info
    finally:
        del s


def render_leg(surgepy, preset_abs, seq, mutate, repeats=3):
    """Render a leg `repeats` times; refuse unless all repeats are identical."""
    bufs, infos = [], []
    for _ in range(repeats):
        a, i = _render_once(surgepy, preset_abs, seq, mutate)
        bufs.append(a)
        infos.append(i)
    hashes = [rfx.sha256_buf(x) for x in bufs]
    if any(h != hashes[0] for h in hashes):
        raise Refuse(f"determinism gate failed over {repeats} repeats: "
                     f"{hashes}")
    return bufs[0], hashes, infos[0]


def synthetic_mutator(slug, active_slots):
    def mutate(s, settle_blocks):
        try:
            return {"construction": syn.construct(s, slug, active_slots,
                                                  settle_blocks)}
        except syn.SyntheticRefused as e:
            raise Refuse(f"synthetic construction refused: {e}")
    return mutate


def all_off_mutator():
    def mutate(s, settle_blocks):
        import surgepy.constants as C  # noqa: PLC0415
        for i in range(FX_SLOTS):
            s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
        s.processMultiBlock(s.createMultiBlock(settle_blocks))
        types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                 for i in range(FX_SLOTS)]
        if any(t != C.fxt_off for t in types):
            raise Refuse(f"dry render: FX types did not read back Off: {types}")
        return {"fx_types_readback": types}
    return mutate


# ---------------------------------------------------------------------------
# bundles
# ---------------------------------------------------------------------------
def render_dry_leg(surgepy, seq_id, out_dir):
    """The all-off DRY bus — SHARED by every synthetic bundle of a sequence.

    It is literally the same render for all five shapers: all 16 FX slots are
    Off and no Distortion parameter is written, so nothing model-specific
    exists. Rendered once per sequence and referenced by every bundle, rather
    than committed five times over; `main()` asserts the sha256 that each
    bundle references is the one that was rendered.
    """
    seq, _p, _s = rfx.rf.load_sequence(seq_id)
    base_abs = os.path.join(oc.engine_dir(), syn.SYN_BASE)
    buf, hashes, info = render_leg(surgepy, base_abs, seq, all_off_mutator())
    os.makedirs(out_dir, exist_ok=True)
    wav = os.path.join(out_dir, f"syn-shared__{seq_id}-dry.f32.wav")
    rfx.write_wav_stereo_f32(wav, buf)
    return {
        "wav": os.path.relpath(wav, REPO),
        "sha256": rfx.rf.sha256_file(wav),
        "bytes": os.path.getsize(wav),
        "peak_abs_float": info["peak_abs"],
        "active_distortion_slots": [],
        "determinism_sha256_all": hashes,
        "bit_identical": True,
        "frames": info["frames"],
        "tail_s": info["tail_s"],
        "last_event_sample": info["last_event_sample"],
        "bypass_method": "all 16 FX-slot type params -> fxt_off via "
                         "setParamVal before the settle; read-back verified "
                         "Off; fresh instance",
        "dry_fx_bypass_verified": info.get("fx_types_readback") == [0] * FX_SLOTS,
        "shared_across_models": "yes — the all-off dry bus carries no "
                                "model-specific state; one render per "
                                "sequence serves every bundle",
    }


def render_synthetic_bundle(surgepy, slug, model_i, seq_id, out_dir, dry_leg):
    seq, _seq_path, seq_sha = rfx.rf.load_sequence(seq_id)
    base_abs = os.path.join(oc.engine_dir(), syn.SYN_BASE)
    on_disk = oc.git_blob_sha1(base_abs)
    if on_disk != syn.SYN_BASE_CENSUS_SHA1:
        raise Refuse(f"synthetic base blob drift: census "
                     f"{syn.SYN_BASE_CENSUS_SHA1}, on disk {on_disk}")

    tail_blocks = int(float(seq.get("tail_s", 2.5)) * SR) // BLOCK
    if tail_blocks < RINGOUT_BLOCKS:
        raise Refuse(
            f"sequence {seq_id} declares a {tail_blocks}-block tail, shorter "
            f"than the effect's declared {RINGOUT_BLOCKS}-block ring-out "
            "window; the tail region would not span the declared ring-out")

    os.makedirs(out_dir, exist_ok=True)
    legs = {"dry": dict(dry_leg)}
    for leg in syn.carrier_legs(slug):
        if leg == "dry":
            continue
        active = syn.leg_active_slots(slug, leg)
        mutate = synthetic_mutator(slug, active)
        buf, hashes, info = render_leg(surgepy, base_abs, seq, mutate)
        wav = os.path.join(out_dir, f"{slug}__{seq_id}-{leg}.f32.wav")
        rfx.write_wav_stereo_f32(wav, buf)
        legs[leg] = {
            "wav": os.path.relpath(wav, REPO),
            "sha256": rfx.rf.sha256_file(wav),
            "bytes": os.path.getsize(wav),
            "peak_abs_float": info["peak_abs"],
            "active_distortion_slots": list(active),
            "determinism_sha256_all": hashes,
            "bit_identical": True,
            "frames": info["frames"],
            "tail_s": info["tail_s"],
            "last_event_sample": info["last_event_sample"],
        }
        legs[leg]["construction_readback"] = info["construction"]
    if legs["dry"]["frames"] != legs["original"]["frames"]:
        raise Refuse(
            f"shared dry leg declares {legs['dry']['frames']} frames but the "
            f"original leg has {legs['original']['frames']}")
    sidecar = {
        "schema_version": 1,
        "fixture_id": f"{slug}__{seq_id}",
        "issue": "SXT-028e-sse (#136)",
        "leaf": LEAF,
        "carrier_kind": "DECLARED-SYNTHETIC",
        "declaration": syn.DECLARATION,
        "corpus_reach": "NONE",
        "claim_scope": "reference-vs-reference buses of the pinned engine "
                       "under the SXT-012/023 policies, on a DECLARED "
                       "SYNTHETIC patch; no fidelity, support or quality "
                       "claim follows from their existence",
        "fx_model_index": model_i,
        "quad_waveshaper": syn.SSE_SHAPER_OF[model_i],
        "fxws_name": syn.FXWS_NAMES[model_i],
        "preset": {
            "slug": slug,
            "base_path": syn.SYN_BASE,
            "base_census_blob_sha1": syn.SYN_BASE_CENSUS_SHA1,
        },
        "sequence": {"id": seq_id, "sha256": seq_sha},
        "render": {
            "sample_rate": SR,
            "block_size": BLOCK,
            "frames": legs["original"]["frames"],
            "duration_s": round(legs["original"]["frames"] / SR, 6),
            "tail_s": legs["original"]["tail_s"],
            "settle_s": seq.get("settle_s", 0.25),
            "tail_blocks": tail_blocks,
            "declared_ringout_blocks": RINGOUT_BLOCKS,
            "tail_spans_declared_ringout": tail_blocks >= RINGOUT_BLOCKS,
            "policies_inherited": "fixtures/render_fixture.py via "
                                  "tools/render_fx_fixtures.py (reset/"
                                  "scheduling/tail/dry-bypass); see "
                                  "fixtures/README.md",
            "declared_deviation": "the synthetic construction spends one of "
                                  "the 375 settle blocks materialising the FX "
                                  "instances before writing their parameters; "
                                  "the total settle is unchanged at 0.25 s",
        },
        "audio_policy": "stereo float32 (IEEE fmt 3), raw engine output, no "
                        "clip, no normalization, no fades",
        "determinism_gate": {
            "repeats": 3,
            "bit_identical": True,
            "per_leg_sha256_all": {k: v["determinism_sha256_all"]
                                   for k, v in legs.items()},
        },
        "legs": legs,
        # The comparator reads its declared tail region from the `original`
        # bus block (issue #93/#100 reader, bus name passed explicitly). No
        # `wet` alias is written: a second copy of the same bytes would be a
        # second thing to keep in sync.
        "wet_bus_name": "original",
        "original": legs["original"],
        "dry": legs["dry"],
        "engine": rfx.rf.engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "tool": rfx.rf.tool_version(),
    }
    sp = os.path.join(out_dir, f"{slug}__{seq_id}.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"rendered {slug}__{seq_id}: "
          + " ".join(f"{k}={v['sha256'][:8]}/{v['peak_abs_float']:.4f}"
                     for k, v in legs.items()))
    return sidecar


def attempt_corpus_carrier(surgepy, slug, rel_path, seq_id):
    """Attempt a corpus carrier and return the measured refusal reason (or None).

    Applies the static screens from the committed extraction record first (so
    the reason is the record's own, not a second opinion), then the empirical
    3x determinism gate on the WET and the all-off DRY bus.
    """
    rec_path = os.path.join(REPO, "model", "effects", "fx_inputs",
                            f"type-distortion-sse-{slug}.json")
    if not os.path.exists(rec_path):
        return f"no extraction record at {os.path.relpath(rec_path, REPO)}"
    rec = json.load(open(rec_path))
    screens = rec.get("render_screens")
    if screens is None:
        return ("extraction record carries no render_screens block (re-run "
                "tools/extract_distortion_sse_inputs.py --mode oracle)")
    reasons = list(screens.get("refusal_reasons") or [])
    if rec.get("unlanded_classes_in_chain"):
        reasons.append("unlanded class(es) in the active chain: "
                       + ", ".join(rec["unlanded_classes_in_chain"])
                       + " — a complete-wet comparison would need a model "
                         "this project has not landed, and substituting a "
                         "generic is refused")
    if reasons:
        return "static screens: " + "; ".join(reasons)

    seq, _p, _s = rfx.rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    blob, _graphs = rfx.census_entry(rel_path)
    if oc.git_blob_sha1(abs_path) != blob:
        return f"census blob mismatch on the oracle host: {rel_path}"
    for leg, mutate in (("dry", all_off_mutator()), ("wet", None)):
        try:
            render_leg(surgepy, abs_path, seq, mutate)
        except Refuse as e:
            return f"{leg} bus: {e}"
    return None


# ---------------------------------------------------------------------------
def harness_control(surgepy):
    """Re-render a committed SXT-028c bus and compare its sha256 (CONTROL)."""
    sc = json.load(open(CONTROL_SIDECAR))
    seq, _p, _s = rfx.rf.load_sequence(sc["sequence"]["id"])
    abs_path = os.path.join(oc.engine_dir(), CONTROL_PRESET)
    buf, hashes, _info = render_leg(surgepy, abs_path, seq, None)
    tmp = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts",
                       "control-fmcombo-rerender.f32.wav")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    rfx.write_wav_stereo_f32(tmp, buf)
    got = rfx.rf.sha256_file(tmp)
    os.unlink(tmp)
    out = {
        "control": "SXT-028c fmcombo wet bus re-rendered through this host's "
                   "prebuilt pinned oracle",
        "purpose": "makes a determinism REFUSAL below a statement about the "
                   "preset, not about this host or this harness",
        "sidecar": os.path.relpath(CONTROL_SIDECAR, REPO),
        "committed_sha256": sc["wet"]["sha256"],
        "rerendered_sha256": got,
        "determinism_sha256_all": hashes,
        "status": "PASS" if got == sc["wet"]["sha256"] else "FAIL",
    }
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "SXT-028e-sse",
                                         "fixtures"))
    ap.add_argument("--art-dir",
                    default=os.path.join(REPO, "reports", "SXT-028e-sse",
                                         "artifacts"))
    ap.add_argument("--carriers", help="comma-separated synthetic carrier subset")
    ap.add_argument("--seqs", help="comma-separated sequence subset")
    ap.add_argument("--control", action="store_true",
                    help="run the harness/host control only")
    ap.add_argument("--skip-corpus", action="store_true")
    args = ap.parse_args()

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    os.makedirs(args.art_dir, exist_ok=True)

    if args.control:
        ctl = harness_control(surgepy)
        with open(os.path.join(args.art_dir, "harness-host-control.json"),
                  "w") as f:
            json.dump(ctl, f, indent=2)
            f.write("\n")
        return 0 if ctl["status"] == "PASS" else 2

    ctl = harness_control(surgepy)
    with open(os.path.join(args.art_dir, "harness-host-control.json"), "w") as f:
        json.dump(ctl, f, indent=2)
        f.write("\n")
    if ctl["status"] != "PASS":
        raise Refuse("harness/host control FAILED; refusing to render or "
                     "refuse anything else on this host")

    seqs = args.seqs.split(",") if args.seqs else SEQUENCES
    carriers = (args.carriers.split(",") if args.carriers
                else sorted(syn.CARRIERS))
    unknown = [c for c in carriers if c not in syn.CARRIERS]
    if unknown:
        raise Refuse(f"unknown synthetic carrier(s): {unknown}")

    refusals = []
    if not args.skip_corpus:
        for slug, rel in sorted(CORPUS_CARRIERS.items()):
            for seq_id in seqs:
                why = attempt_corpus_carrier(surgepy, slug, rel, seq_id)
                if why:
                    msg = (f"NOT_RUN {slug}__{seq_id} ({rel}): {why}")
                    refusals.append(msg)
                    print(msg, file=sys.stderr)
                else:
                    msg = (f"UNEXPECTED {slug}__{seq_id}: passed every screen "
                           "and the determinism gate — the record's NOT_RUN "
                           "claim is STALE and must be re-derived")
                    refusals.append(msg)
                    print(msg, file=sys.stderr)

    dry_legs = {}
    for seq_id in seqs:
        try:
            dry_legs[seq_id] = render_dry_leg(surgepy, seq_id, args.out_dir)
            print(f"rendered shared dry leg {seq_id}: "
                  f"{dry_legs[seq_id]['sha256'][:8]}")
        except Refuse as e:
            msg = f"NOT_RUN syn-shared__{seq_id} (dry bus): {e}"
            refusals.append(msg)
            print(msg, file=sys.stderr)

    for slug in carriers:
        model_i = syn.CARRIERS[slug]["model"]
        for seq_id in [q for q in seqs if q in syn.SEQUENCES_FOR[slug]]:
            if seq_id not in dry_legs:
                refusals.append(f"NOT_RUN {slug}__{seq_id}: the shared dry "
                                "bus for this sequence was refused")
                continue
            try:
                render_synthetic_bundle(surgepy, slug, model_i, seq_id,
                                        args.out_dir, dry_legs[seq_id])
            except Refuse as e:
                msg = f"NOT_RUN {slug}__{seq_id} (DECLARED-SYNTHETIC): {e}"
                refusals.append(msg)
                print(msg, file=sys.stderr)

    path = os.path.join(args.art_dir, "render-refusals.txt")
    header = (f"{LEAF} reference-render transcript (issue #136)\n"
              "engine pin surge-synthesizer/surge@"
              "58914e59c608ed4384ba6002e44c3465c58b2e71, 48 kHz, block 32\n"
              f"harness/host control: {ctl['status']} "
              f"({ctl['committed_sha256'][:16]}…)\n"
              "a render that could not be produced is NOT_RUN, never a pass; "
              "no fixture and no compare-*.json exists for one\n"
              "NOTE: a `determinism gate failed` row quotes the hashes OF "
              "THAT RUN. Those three hashes differ from run to run by "
              "definition — that is the finding — so this transcript is "
              "reproducible in its rows and reasons, not byte-for-byte.\n\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(refusals) + ("\n" if refusals else ""))
    print(f"\n{len(refusals)} NOT_RUN row(s) recorded -> "
          f"{os.path.relpath(path, REPO)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
