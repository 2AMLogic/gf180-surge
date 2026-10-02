#!/usr/bin/env python3
"""SXT-028f reference fixtures: stereo float renders of the Reverb 2 carriers.

Inherits the SXT-012/023 fixture policy by importing
tools/render_fx_fixtures.py (fresh instance per bus, census-blob-verified
load, controller reset, 0.25 s settle, block-quantized scheduling, identical
tails, 3x bit-identical determinism gate, all-off DRY bus with read-back).

Three legs per carrier x sequence (issue #126 / finding F-028f-1):

  ORIGINAL ("wet")   the preset's unmodified chain. This is the reference
                     every agreement number is graded against and it is
                     NEVER modified by the bypass legs (AGENTS.md: "Bypass
                     tests must retain the unmodified wet reference").
  PER-SLOT BYPASS    one extra render per active Reverb 2 slot with ONLY
                     that slot's type set to Off; every other slot keeps
                     the preset's own value. Read-back verified.
  ALL-OFF DRY        all 16 FX-slot types set Off, read-back verified.

All three legs carry the sequence's full declared tail (`tail_s`); nothing
is truncated, faded or normalized.

Why the per-slot bypass leg exists here. It is the declared model INPUT
boundary for this leaf (see model/effects/run_reverb2_model.py): for a
Reverb 2 in a *global* slot the bypass bus is exactly the signal the engine
feeds the Reverb 2, and for a *send* slot the bypass bus is exactly the
engine's output with the Reverb 2 return removed, so the send return can be
added back by the model without modelling the sibling classes in the chain.
That keeps the comparison a Reverb-2-class measurement rather than a
measurement of a stack of sibling models.

WAVs are this project's own renders of loaded presets (not redistributed
upstream content). Original tool, Apache-2.0.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402

import render_fx_fixtures as rfx  # noqa: E402  (SXT-023 policies inherited)

SR = 48000
FX_SLOTS = 16
FX_TYPE_REVERB2 = 11

# The three issue-named B4-scope carriers (#58, #126). All three are
# ATTEMPTED here and all three are REFUSED empirically by the 3x gate; the
# measured divergence is written to the gate record, never papered over.
NAMED_CARRIERS = {
    "grant_me": "resources/data/patches_3rdparty/A.Liv/Keys/Grant Me....fxp",
    "novuo": "resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp",
    "harp": "resources/data/patches_3rdparty/Aleksey Zhehanov/Strings/Harp.fxp",
}

# Deterministic Reverb 2 carriers selected from the committed corpus ledger
# (reports/SXT-028f/artifacts/carrier-ledger.json) by the screen in
# tools/screen_reverb2_carriers.py and then confirmed empirically by this
# harness's own 3x gate. Same precedent as SXT-028c, whose issue-named
# carriers were likewise refused and replaced by screened deterministic
# ones. Each has its Reverb 2 in the LAST active FX slot in a global role,
# which is the declared model input boundary (see
# model/effects/run_reverb2_model.py).
DETERMINISTIC_CARRIERS = {
    "tacobell": "resources/data/patches_3rdparty/Luna/Bells/Taco Bell.fxp",
    "moire1": "resources/data/patches_3rdparty/Jacky Ligon/Soundscapes/Moire 1.fxp",
    "mystical": "resources/data/patches_3rdparty/TNMG/Bells/Mystical Creature.fxp",
}

# Live control on the 3x gate's own resolving power (--stress). `Lap Harp`
# passes a 3x gate most of the time and is nonetheless BIMODAL: its wet bus
# settles on exactly one of two distinct buffers while its all-off dry bus
# is stable, so the nondeterminism is FX-side, not source-side. It is
# deliberately NOT a committed carrier; it is the counter-example proving
# that "3x passed once" is weaker evidence than it looks.
FLAKE_CONTROL = {
    "lapharp": "resources/data/patches_3rdparty/Luna/MPE/Lap Harp.fxp",
}

# An RNG-using preset rendered between stress repeats, so a flake that only
# appears once other engine instances have run in the same process is not
# missed (that is how the `lapharp` bimodality was first observed).
STRESS_PERTURBER = "resources/data/patches_3rdparty/A.Liv/Keys/Grant Me....fxp"

PRESETS = dict(NAMED_CARRIERS, **DETERMINISTIC_CARRIERS)
SEQUENCES = ["seq-notes-coverage-v1", "seq-poly-8-v1"]


class DeterminismRefusal(rfx.Refuse):
    """A 3x-gate refusal that carries the MEASURED divergence.

    A refusal that only says "the hashes differ" cannot be distinguished
    from a broken harness, so the measurement travels with the refusal and
    is written into the gate record.
    """

    def __init__(self, hashes, stats):
        super().__init__("determinism gate failed over %d repeats "
                         "(max |divergence| = %.3e of peak %.3e, %d/%d "
                         "frames differ): %s"
                         % (len(hashes), stats["max_abs_divergence"],
                            stats["peak_abs"], stats["frames_differing"],
                            stats["frames"], hashes))
        self.hashes = hashes
        self.stats = stats


def _divergence_stats(bufs):
    ref = bufs[0]
    worst = 0.0
    differing = 0
    for other in bufs[1:]:
        d = np.abs(ref - other)
        worst = max(worst, float(d.max()) if d.size else 0.0)
        differing = max(differing, int(np.count_nonzero(d.max(axis=0))))
    return {
        "frames": int(ref.shape[1]),
        "frames_differing": differing,
        "peak_abs": float(np.max(np.abs(ref))) if ref.size else 0.0,
        "max_abs_divergence": worst,
    }


def render_bus_slots(surgepy, preset_abs, seq, off_slots, repeats=3):
    """Render one bus `repeats` times in fresh instances.

    `off_slots` is the set of FX slot indices forced to `fxt_off` before the
    settle; everything else keeps the preset's own value. `off_slots=None`
    means the unmodified ORIGINAL chain. Refuses unless all repeats are
    bit-identical (the SXT-023 determinism gate).
    """
    import surgepy.constants as C

    bufs, infos = [], []
    for _ in range(repeats):
        s = surgepy.createSurge(float(SR))
        try:
            if not s.loadPatch(preset_abs):
                raise rfx.Refuse(f"loadPatch failed: {preset_abs}")
            s.pitchBend(0, 0)
            s.channelController(0, 64, 0)
            s.channelController(0, 1, 0)
            s.channelController(0, 11, 0)
            s.channelAftertouch(0, 0)
            s.allNotesOff()
            if off_slots:
                for i in sorted(off_slots):
                    s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
            bs = int(s.getBlockSize())
            settle_blocks = int(seq.get("settle_s", 0.25) * SR) // bs
            sbuf = s.createMultiBlock(settle_blocks)
            s.processMultiBlock(sbuf)
            types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                     for i in range(FX_SLOTS)]
            if off_slots:
                bad = [i for i in off_slots if types[i] != C.fxt_off]
                if bad:
                    raise rfx.Refuse(
                        f"bypass render: slots {bad} did not read back Off: "
                        f"{types}")
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
                    raise rfx.Refuse("scheduler failed to advance")
                seg = (total_blocks if nxt >= len(events)
                       else max(quant(events[nxt]["t"]), b + 1))
                s.processMultiBlock(buf, b, seg - b)
                b = seg
                dispatched = nxt
            stereo = np.asarray(buf, dtype=np.float32).copy()
            bufs.append(stereo)
            infos.append({
                "blocks": total_blocks,
                "frames": total_blocks * bs,
                "last_event_sample": int(last_t),
                "peak_abs": float(np.max(np.abs(stereo))) if stereo.size else 0.0,
                "fx_types_readback": types,
            })
        finally:
            del s
    hashes = [rfx.sha256_buf(x) for x in bufs]
    if any(h != hashes[0] for h in hashes):
        raise DeterminismRefusal(hashes, _divergence_stats(bufs))
    return bufs[0], hashes, infos[0]


def active_reverb2_slots(surgepy, preset_abs):
    import surgepy.constants as C  # noqa: F401

    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise rfx.Refuse(f"loadPatch failed: {preset_abs}")
        patch = s.getPatch()
        slots = [i for i in range(FX_SLOTS)
                 if int(s.getParamVal(patch["fx"][i]["type"])) == FX_TYPE_REVERB2]
        types = [int(s.getParamVal(patch["fx"][i]["type"])) for i in range(FX_SLOTS)]
    finally:
        del s
    return slots, types


def bus_entry(path, info, hashes, extra=None):
    d = {
        "wav": os.path.relpath(path, REPO),
        "sha256": rfx.rf.sha256_file(path),
        "bytes": os.path.getsize(path),
        "frames": info["frames"],
        "last_event_sample": info["last_event_sample"],
        "peak_abs_float": info["peak_abs"],
        "determinism_sha256_all": hashes,
        "bit_identical_3x": True,
    }
    if extra:
        d.update(extra)
    return d


def render_fixture(surgepy, slug, rel_path, seq_id, out_dir):
    seq, _seq_path, seq_sha = rfx.rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    blob, graphs = rfx.census_entry(rel_path)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise rfx.Refuse(f"census blob mismatch: {rel_path}")

    rev2_slots, all_types = active_reverb2_slots(surgepy, abs_path)
    if not rev2_slots:
        raise rfx.Refuse(f"no active Reverb 2 slot: {rel_path}")

    os.makedirs(out_dir, exist_ok=True)
    tail_s = float(seq.get("tail_s", 2.5))

    wet, wet_hashes, winfo = render_bus_slots(surgepy, abs_path, seq, None)
    wet_path = os.path.join(out_dir, f"{slug}__{seq_id}-wet.f32.wav")
    rfx.write_wav_stereo_f32(wet_path, wet)

    dry, dry_hashes, dinfo = render_bus_slots(
        surgepy, abs_path, seq, set(range(FX_SLOTS)))
    dry_path = os.path.join(out_dir, f"{slug}__{seq_id}-dry.f32.wav")
    rfx.write_wav_stereo_f32(dry_path, dry)

    bypass = {}
    for slot in rev2_slots:
        bp, bp_hashes, binfo = render_bus_slots(surgepy, abs_path, seq, {slot})
        bp_path = os.path.join(out_dir,
                               f"{slug}__{seq_id}-bypass-fx{slot}.f32.wav")
        rfx.write_wav_stereo_f32(bp_path, bp)
        bypass[f"fx{slot}"] = bus_entry(bp_path, binfo, bp_hashes, {
            "slot": slot,
            "bypass_method": "ONLY this Reverb 2 slot's type param -> fxt_off "
                             "via setParamVal before settle; every other slot "
                             "keeps the preset value; read-back verified; "
                             "fresh instance",
            "other_slots_unmodified": True,
            "fx_types_readback": binfo["fx_types_readback"],
        })

    sidecar = {
        "schema_version": 1,
        "fixture_id": f"{slug}__{seq_id}",
        "issue": "SXT-028f",
        "follow_up": "F-028f-1 (#126)",
        "claim_scope": "reference-vs-reference wet / per-slot-bypass / all-off "
                       "dry buses of the pinned engine under the SXT-012/023 "
                       "policies; no fidelity, support, coverage or quality "
                       "claim",
        "preset": {
            "slug": slug,
            "path": rel_path,
            "census_blob_sha1": blob,
            "graphs_sha256_prefix": graphs["sha"][:16],
        },
        "sequence": {"id": seq_id, "sha256": seq_sha},
        "render": {
            "sample_rate": SR,
            "block_size": 32,
            "frames": winfo["frames"],
            "duration_s": round(winfo["frames"] / SR, 6),
            "policies_inherited": "fixtures/render_fixture.py via "
                                  "tools/render_fx_fixtures.py (reset/"
                                  "scheduling/tail/dry-bypass); see "
                                  "fixtures/README.md",
            "tail_s": tail_s,
            "settle_s": seq.get("settle_s", 0.25),
            "tails_included": True,
        },
        "audio_policy": "stereo float32 (IEEE fmt 3), raw engine output, no "
                        "clip, no normalization, no fades, no time-warp",
        "determinism_gate": {
            "repeats": 3,
            "scope": "every committed bus (wet, all-off dry, each per-slot "
                     "bypass) rendered 3x in fresh instances; all three "
                     "buffers bit-identical (sha256) or the fixture is "
                     "REFUSED and nothing is committed",
            "bit_identical": True,
            "drift_asserted": 0,
        },
        "reverb2_slots": rev2_slots,
        "fx_types": all_types,
        "wet": bus_entry(wet_path, winfo, wet_hashes, {
            "leg": "ORIGINAL (unmodified preset chain) -- the wet reference; "
                   "never modified by the bypass legs",
        }),
        "dry": bus_entry(dry_path, dinfo, dry_hashes, {
            "bypass_method": "all 16 FX-slot type params -> fxt_off via "
                             "setParamVal before settle; read-back verified "
                             "Off; fresh instance",
            "dry_fx_bypass_verified": dinfo["fx_types_readback"] == [0] * FX_SLOTS,
        }),
        "bypass": bypass,
        "engine": rfx.rf.engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "tool": rfx.rf.tool_version(),
    }
    sp = os.path.join(out_dir, f"{slug}__{seq_id}.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"rendered {slug}__{seq_id}: wet {sidecar['wet']['sha256'][:12]} "
          f"dry {sidecar['dry']['sha256'][:12]} "
          f"bypass {sorted(bypass)} peak {winfo['peak_abs']:.4f}")
    return sidecar


def positive_control(surgepy, seq_id="seq-poly-8-v1"):
    """Liveness control for the 3x gate itself.

    A gate that refuses every preset is indistinguishable from a broken
    harness or a nondeterministic host, so re-derive three SXT-028c
    carriers whose wet-bus sha256 is already committed: they must pass this
    harness's own gate AND reproduce the committed hash byte-for-byte.
    """
    import tempfile

    rows = []
    for slug, rel in (
        ("fmcombo", "resources/data/patches_factory/Basses/FM Combo.fxp"),
        ("fmtwang2", "resources/data/patches_3rdparty/Luna/MPE/FM Twang 2.fxp"),
        ("alienappears",
         "resources/data/patches_3rdparty/Giana Brotherz/FX/Alien Appears.fxp"),
    ):
        seq, _p, _s = rfx.rf.load_sequence(seq_id)
        row = {"slug": slug, "sequence": seq_id,
               "committed_in": f"reports/SXT-028c/fixtures/{slug}__{seq_id}.json"}
        try:
            wet, _h, _i = render_bus_slots(
                surgepy, os.path.join(oc.engine_dir(), rel), seq, None)
            row["gate_3x"] = "PASS"
            with tempfile.TemporaryDirectory() as td:
                p = os.path.join(td, "x.wav")
                rfx.write_wav_stereo_f32(p, wet)
                got = rfx.rf.sha256_file(p)
            sc = os.path.join(REPO, "reports", "SXT-028c", "fixtures",
                              f"{slug}__{seq_id}.json")
            with open(sc) as f:
                want = json.load(f)["wet"]["sha256"]
            row["committed_wet_sha256"] = want
            row["rederived_wet_sha256"] = got
            row["byte_identical"] = got == want
        except rfx.Refuse as e:
            row["gate_3x"] = "FAIL"
            row["refusal"] = str(e)
            row["byte_identical"] = False
        rows.append(row)
        print("positive-control %s: gate %s byte-identical %s"
              % (slug, row["gate_3x"], row.get("byte_identical")))
    return rows


def stress_screen(surgepy, carriers, seqs, repeats):
    """Interleaved stress screen: `repeats` single renders per bus, each
    preceded by a render of an RNG-using preset in the SAME process.

    Reports the number of DISTINCT buffers observed per bus. 1 = stable
    under this screen; >1 = the carrier is nondeterministic even though a
    single 3x gate may pass it.
    """
    rows = []
    for slug, rel in sorted(carriers.items()):
        abs_path = os.path.join(oc.engine_dir(), rel)
        perturb = os.path.join(oc.engine_dir(), STRESS_PERTURBER)
        for seq_id in seqs:
            seq, _p, _s = rfx.rf.load_sequence(seq_id)
            seen = {"wet": [], "dry": []}
            for bus in ("wet", "dry"):
                off = None if bus == "wet" else set(range(FX_SLOTS))
                for _ in range(repeats):
                    try:
                        render_bus_slots(surgepy, perturb, seq, None, repeats=1)
                    except rfx.Refuse:
                        pass
                    _w, h, _i = render_bus_slots(surgepy, abs_path, seq, off,
                                                 repeats=1)
                    seen[bus].append(h[0])
            counts = {bus: {h: vals.count(h) for h in sorted(set(vals))}
                      for bus, vals in seen.items()}
            row = {"slug": slug, "preset": rel, "sequence": seq_id,
                   "repeats_per_bus": repeats,
                   "distinct_wet_buffers": len(counts["wet"]),
                   "distinct_dry_buffers": len(counts["dry"]),
                   "wet_buffer_counts": counts["wet"],
                   "dry_buffer_counts": counts["dry"],
                   "stable": len(counts["wet"]) == 1 and len(counts["dry"]) == 1}
            rows.append(row)
            print("stress %-10s %-24s wet=%d dry=%d %s"
                  % (slug, seq_id, row["distinct_wet_buffers"],
                     row["distinct_dry_buffers"],
                     "STABLE" if row["stable"] else "FLAKY"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "SXT-028f", "fixtures"))
    ap.add_argument("--presets", help="comma-separated subset")
    ap.add_argument("--seqs", help="comma-separated subset")
    ap.add_argument("--art-dir",
                    default=os.path.join(REPO, "reports", "SXT-028f", "artifacts"))
    ap.add_argument("--no-control", action="store_true",
                    help="skip the gate liveness control (debugging only)")
    ap.add_argument("--stress", type=int, default=0, metavar="N",
                    help="also run the interleaved stress screen with N "
                         "repeats over the committed carriers and the "
                         "bimodal flake control")
    args = ap.parse_args()
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    slugs = args.presets.split(",") if args.presets else sorted(PRESETS)
    seqs = args.seqs.split(",") if args.seqs else SEQUENCES
    refusals = []
    gate_rows = []
    for slug in slugs:
        for seq_id in seqs:
            row = {"slug": slug, "preset": PRESETS[slug], "sequence": seq_id,
                   "named_carrier": slug in NAMED_CARRIERS}
            try:
                side = render_fixture(surgepy, slug, PRESETS[slug], seq_id,
                                      args.out_dir)
                row["status"] = "PASS"
                row["drift_asserted"] = 0
                row["buses"] = (["wet", "dry"]
                                + sorted(side["bypass"]))
            except DeterminismRefusal as e:
                msg = f"{slug}__{seq_id}: REFUSED: {e}"
                refusals.append(msg)
                print(msg, file=sys.stderr)
                row["status"] = "REFUSED"
                row["refusal_class"] = "determinism-gate"
                row["drift_asserted"] = None
                row["measured"] = e.stats
                row["repeat_sha256"] = e.hashes
            except rfx.Refuse as e:
                msg = f"{slug}__{seq_id}: REFUSED: {e}"
                refusals.append(msg)
                print(msg, file=sys.stderr)
                row["status"] = "REFUSED"
                row["refusal_class"] = "other"
                row["drift_asserted"] = None
                row["refusal"] = str(e)
            gate_rows.append(row)

    os.makedirs(args.art_dir, exist_ok=True)
    with open(os.path.join(args.art_dir, "render-refusals.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(refusals) + ("\n" if refusals else ""))
    gate = {
        "schema_version": 1,
        "leaf": "SXT-028f",
        "follow_up": "F-028f-1 (#126)",
        "gate": "SXT-012/023 3x bit-identical render determinism gate",
        "claim_scope": "reference-vs-reference repeatability of the pinned "
                       "engine under a defined environment; NOT a fidelity, "
                       "support, coverage or quality claim",
        "repeats": 3,
        "sequences": seqs,
        "engine": rfx.rf.engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "positive_control": ([] if args.no_control
                             else positive_control(surgepy)),
        "positive_control_note":
            "SXT-028c carriers with a committed wet sha256: they must pass "
            "this harness's own gate and re-derive byte-identically, or a "
            "refusal below says nothing about the carrier",
        "results": gate_rows,
        "stress_screen": (
            stress_screen(surgepy,
                          dict(DETERMINISTIC_CARRIERS, **FLAKE_CONTROL,
                               **NAMED_CARRIERS),
                          seqs, args.stress) if args.stress else []),
        "stress_screen_note":
            "live control on the 3x gate's own resolving power: each repeat "
            "is preceded by a render of an RNG-using preset in the same "
            "process. `lapharp` is the counter-example -- it passes a 3x "
            "gate most of the time and is still bimodal on the wet bus "
            "while its all-off dry bus is stable, so a single 3x PASS is "
            "weaker evidence than it looks and is NOT, by itself, a "
            "determinism claim. The three issue-named carriers are included "
            "so their REFUSAL is characterised rather than merely asserted: "
            "a carrier whose ALL-OFF DRY bus is already unstable is "
            "nondeterministic in the voice path, upstream of every FX slot, "
            "which is a property of the preset and not of fx:Reverb 2.",
        "tool": rfx.rf.tool_version(),
    }
    with open(os.path.join(args.art_dir, "determinism-gate.json"), "w",
              encoding="utf-8") as f:
        json.dump(gate, f, indent=2, sort_keys=True)
        f.write("\n")
    npass = sum(1 for r in gate_rows if r["status"] == "PASS")
    print("determinism gate: %d PASS / %d REFUSED"
          % (npass, len(gate_rows) - npass))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rfx.Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
