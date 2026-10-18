#!/usr/bin/env python3
"""SXT-028j (#150): pinned-engine reference fixtures and model-vs-engine
record for the routing form "Global FX slots 3-4".

Needs the pinned oracle (oracle/fetch-and-build.sh --prebuilt); without it the
tool REFUSES (exit 2) and writes nothing -- a leg that did not run is never a
pass. Inherits the SXT-012/SXT-023 render policies (fresh instance per bus,
census-blob-verified load, controller reset, 0.25 s settle, block-quantized
scheduling, identical tails, 3x bit-identity determinism gate) by reusing
tools/render_fx_fixtures.py and fixtures/render_fixture.py.

For every carrier x sequence it renders these stereo float buses (raw engine
output, no clip, no normalization):

  orig             the patch as loaded (complete wet bus)
  g3off / g4off    ONE extended-rack slot switched off (per-slot bypass)
  g34off           both off: the bus ENTERING the global3/global4 stage
  dry              all 16 slots off (SXT-012 dry policy)
  sends_off        send1-4 off, everything else as loaded
  sends_g34_off    sends + global3/4 off
  nonins_off       send1-4 + global1-4 off (scene inserts only)
  byp_*            the patch's fx_bypass parameter forced to No sends /
                   Scene FX only / No FX

and then reports, separately:

  * ENGINE ROUTING CHECKS (exact float equality between engine buses; nothing
    modeled): which fx_bypass modes run the global stage, and when an FX-off
    request takes effect (the enqueueFXOff queue-drain block). These back
    EVIDENCE section 0b's two declared contracts empirically; the pinned-
    source re-read is recorded in the EVIDENCE record. The fx_disable bit
    gate (bits 14|15) cannot be probed live: surgepy's setParamVal on the
    int fx_disable parameter reads back -2147483648 for every value
    (recorded as BLOCKED), and the only carrier with the bits set natively
    (Bassoon.fxp) is source-nonrepeatable.
  * MODEL-vs-ENGINE ROUTING AGREEMENT: the frozen model's stage-active
    prediction (model/effects/rf-rf-global34, driven by the engine's own
    stage-input bus) against the engine's observed behavior. Boolean, exact.
  * MODEL-vs-ENGINE WAVEFORM (max/rms/corr against the [PROPOSED] budgets,
    tail gate included). The frozen model's per-slot occupant is a SYNTHETIC
    biquad (model README "Form scope, not algorithm scope"), so for any
    carrier whose engine occupant is enabled this number is MEASURED but not
    an agreement claim (agreement_claim NO_VERDICT, reason
    occupant_not_modeled); the concrete occupants belong to the algorithm
    leaves. Budgets are never widened or frozen here (SXT-017, #12).
  * LIVE NEGATIVE CONTROLS for the routing comparison (wrong bypass
    partition, bypass ignored): each must disagree with the engine on a
    discriminating source, or the control is broken.

Reference WAVs are written to --wav-dir (default: a scratch directory, NOT
committed: tens of MB); the committed evidence is the manifests with
per-bus sha256 of the raw float buffers.

Original to this repository (Apache-2.0); imports the GPL engine at run time
only and copies no engine source, table, or asset.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "fixtures"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global34"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402
import render_fixture as rf  # noqa: E402  (SXT-012 harness: policies inherited)
import compare_audio_reference as car  # noqa: E402
import compare_fx_reference as cfr  # noqa: E402
import render_fx_fixtures as rff  # noqa: E402
import rf_global34_model as rm  # noqa: E402
from refusal import Refuse  # noqa: E402

ENGINE_PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"
SR = 48000
BS = 32
FX_SLOTS = 16
SEQUENCES = ["seq-notes-coverage-v1", "seq-poly-8-v1"]
REPEATS = 3
SLOT_G3, SLOT_G4 = rm.FXSLOT_GLOBAL3, rm.FXSLOT_GLOBAL4
DIAG_PRESET = "resources/data/patches_factory/Basses/Sub 4.fxp"
DIAG_SET = {SLOT_G3: "fxt_distortion", SLOT_G4: "fxt_delay"}

FIXTURES_DIR = os.path.join(REPO, "reports", "SXT-028j", "fixtures")
ARTIFACTS = os.path.join(REPO, "reports", "SXT-028j", "artifacts")
RECORD = os.path.join(REPO, "reports", "SXT-028j", "model-vs-reference.json")
REFUSALS = os.path.join(ARTIFACTS, "render-refusals.txt")
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")

# [PROPOSED, not frozen] synthetic occupant used to drive the frozen model on
# the engine's own stage-input bus: a pure gain of 0.5 (b0 only).
SYNTH_COEFFS = (rm.to_q(0.5, rm.C_FRAC, rm.C_BITS), 0, 0, 0, 0)
PREDICT_BLOCKS = 1024

# fx_bypass enum values (SurgeStorage.h fxb_*; mirrored by the frozen model)
BYPASS_VALUES = {"byp_no_sends": rm.FXB_NO_SENDS,
                 "byp_scene_fx_only": rm.FXB_SCENE_FX_ONLY,
                 "byp_no_fx": rm.FXB_NO_FX}


def slot_roles(graph):
    return {fx["r"]: fx["i"] for fx in graph["g"]["fx"]}


def bus_specs(roles, base_set=None):
    """name -> mods. off: slot indices forced to fxt_off; bypass: forced
    fx_bypass value; dis: bits OR-ed into fx_disable."""
    sends = [roles[f"send{i}"] for i in range(1, 5)]
    globs = [roles[f"global{i}"] for i in range(1, 5)]
    g3, g4 = roles["global3"], roles["global4"]
    specs = {
        "orig": {},
        "g3off": {"off": [g3]},
        "g4off": {"off": [g4]},
        "g34off": {"off": [g3, g4]},
        "dry": {"off": list(range(FX_SLOTS))},
        "sends_off": {"off": sends},
        "sends_g34_off": {"off": sends + [g3, g4]},
        "nonins_off": {"off": sends + globs},
    }
    for name, val in BYPASS_VALUES.items():
        specs[name] = {"bypass": val}
    if base_set:
        for mods in specs.values():
            mods["set"] = dict(base_set)
    return specs


def render_bus(surgepy, preset_abs, seq, mods, repeats=REPEATS,
               queue_off=None, strict=True):
    """Render one bus `repeats` times in fresh instances; REFUSE unless all
    repeats are bit-identical. `queue_off=(block, slot)` sets that slot's type
    to Off between processMultiBlock calls at that block index (counted from
    the start of the event buffer, after the settle)."""
    import surgepy.constants as C

    bufs = []
    for _ in range(repeats):
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
            patch = s.getPatch()
            # one write per slot: an override followed by an Off on the same
            # slot before the first control pass does not read back as Off
            want = {int(i): int(getattr(C, t))
                    for i, t in mods.get("set", {}).items()}
            want.update({i: int(C.fxt_off) for i in mods.get("off", [])})
            for i, t in want.items():
                s.setParamVal(patch["fx"][i]["type"], float(t))
            if "bypass" in mods:
                s.setParamVal(patch["fx_bypass"], float(mods["bypass"]))
            bs = int(s.getBlockSize())
            if bs != BS:
                raise Refuse(f"engine block size {bs} != {BS}")
            settle = int(seq.get("settle_s", 0.25) * SR) // bs
            s.processMultiBlock(s.createMultiBlock(settle))
            for i, want_t in want.items():
                t = int(round(s.getParamVal(patch["fx"][i]["type"])))
                if t != want_t:
                    raise Refuse(f"slot {i} read back type {t}, wanted "
                                 f"{want_t}")
            if "bypass" in mods and \
                    int(round(s.getParamVal(patch["fx_bypass"]))) != mods["bypass"]:
                raise Refuse("fx_bypass did not read back as forced")
            events = seq["events"]
            notes = [e for e in events if e["type"] in ("note_on", "note_off")]
            last_t = max(e["t"] for e in notes) if notes else 0
            total_blocks = -(-(last_t + int(float(seq.get("tail_s", 2.5)) * SR))
                             // bs)
            buf = s.createMultiBlock(total_blocks)
            quant = lambda t: -(-t // bs)  # noqa: E731
            dispatched, b, queued = 0, 0, queue_off is None
            while b < total_blocks:
                if not queued and b == queue_off[0]:
                    s.setParamVal(patch["fx"][queue_off[1]]["type"], C.fxt_off)
                    queued = True
                nxt = rf.dispatch(s, events[dispatched:], b, quant) + dispatched
                if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                    raise Refuse("scheduler failed to advance")
                seg = total_blocks if nxt >= len(events) else \
                    max(quant(events[nxt]["t"]), b + 1)
                if not queued and queue_off[0] > b:
                    seg = min(seg, queue_off[0])
                s.processMultiBlock(buf, b, seg - b)
                b, dispatched = seg, nxt
            bufs.append(np.asarray(buf, dtype=np.float32).copy())
        finally:
            del s
    hashes = [rff.sha256_buf(x) for x in bufs]
    if strict and any(h != hashes[0] for h in hashes):
        raise Refuse(f"determinism gate failed over {repeats} repeats: "
                     f"{hashes}")
    if not np.all(np.isfinite(bufs[0])):
        raise Refuse("non-finite sample in the engine render")
    return bufs[0], hashes


def same(a, b):
    return bool(a.shape == b.shape and np.array_equal(a, b))


def first_diff_block(a, b):
    """Index of the first 32-frame block in which the buses differ, or None."""
    n = min(a.shape[1], b.shape[1])
    d = np.flatnonzero(np.any(a[:, :n] != b[:, :n], axis=0))
    return int(d[0]) // BS if d.size else None


def quantize(bus):
    return np.clip(np.rint(bus.astype(np.float64) * (1 << rm.A_FRAC)),
                   -(1 << 31), (1 << 31) - 1).astype(np.int64)


def make_rack(fxb, fxd, occ3, occ4):
    rack = rm.ExtendedGlobalRack()
    rack.apply_control(fxb, fxd, occ3, True, SYNTH_COEFFS, occ4, True,
                       SYNTH_COEFFS)
    return rack


def drive_rack(rack, q, first_block, n_blocks):
    """Drive the frozen model over the engine's own stage-input bus. Returns
    True iff the model changed any sample (stage observably active)."""
    changed = False
    for blk in range(first_block, first_block + n_blocks):
        lo = blk * BS
        if lo + BS > q.shape[1]:
            break
        il, ir = q[0, lo:lo + BS].tolist(), q[1, lo:lo + BS].tolist()
        ol, orr, _ = rack.process_block(il, ir, True)
        if ol != il or orr != ir:
            changed = True
    return changed


def predict_active(stage_in_q, fxb, fxd, occ3, occ4, wrong=None):
    """Model-predicted 'global3/4 stage changes the bus' for a config.
    `wrong` selects a deliberately broken model for the live controls."""
    saved = rm.GLOBAL_ACTIVE_MODES
    try:
        if wrong == "partition":
            rm.GLOBAL_ACTIVE_MODES = (rm.FXB_ALL_FX, rm.FXB_NO_SENDS,
                                      rm.FXB_SCENE_FX_ONLY)
        elif wrong == "ignore-bypass":
            rm.GLOBAL_ACTIVE_MODES = (rm.FXB_ALL_FX, rm.FXB_NO_SENDS,
                                      rm.FXB_SCENE_FX_ONLY, rm.FXB_NO_FX)
        rack = make_rack(fxb, fxd, occ3, occ4)
        nz = np.flatnonzero(np.any(stage_in_q != 0, axis=0))
        if nz.size == 0:
            return False
        return drive_rack(rack, stage_in_q, int(nz[0]) // BS, PREDICT_BLOCKS)
    finally:
        rm.GLOBAL_ACTIVE_MODES = saved


def waveform_leg(orig, stage_in, fxb, fxd, occ3, occ4, sidecar):
    """Frozen model (synthetic biquad occupants) over the whole engine
    stage-input bus vs the engine's complete wet bus."""
    q = quantize(stage_in)
    rack = make_rack(fxb, fxd, occ3, occ4)
    out = np.zeros_like(q)
    n_blocks = q.shape[1] // BS
    for blk in range(n_blocks):
        lo = blk * BS
        ol, orr, _ = rack.process_block(q[0, lo:lo + BS].tolist(),
                                        q[1, lo:lo + BS].tolist(), True)
        out[0, lo:lo + BS], out[1, lo:lo + BS] = ol, orr
    n = n_blocks * BS
    model = (out[:, :n].astype(np.float64) / (1 << rm.A_FRAC)).astype(np.float32)
    ref = orig[:, :n]
    chs = {"L": cfr.channel_metrics(ref[0], model[0]),
           "R": cfr.channel_metrics(ref[1], model[1]),
           "mono": cfr.channel_metrics(0.5 * (ref[0] + ref[1]),
                                       0.5 * (model[0] + model[1]))}
    m = chs["mono"]
    budgets = {
        "max_abs_diff_lsb": m["max_abs_diff_lsb"] <= cfr.PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": m["rms_diff_dbfs"] <= cfr.PROPOSED["rms_diff_dbfs"],
        "spectral_corr": m["spectral_corr"] >= cfr.PROPOSED["spectral_corr_min"],
    }
    region = car.declared_tail_region(sidecar, "wet")
    why = car.validate_region_against_render(region, SR, n, sidecar)
    if why:
        tail = {"gate": "NO_VERDICT", "reason": why}
        tail_ok = False
    else:
        tc, tc_lr, tail_ok, tail_reason = car.stereo_tail_gate(
            ref, model, region, cfr.LSB)
        tail = {"gate": "PASS" if tail_ok else "FAIL", "reason": tail_reason,
                "tail_check": tc, "tail_check_lr": tc_lr}
    return {"frames_compared": n, "channels": chs,
            "proposed_budgets": cfr.PROPOSED,
            "proposed_budget_results": budgets,
            "tail": tail,
            "budget_verdict": "PASS" if (all(budgets.values()) and tail_ok)
            else "FAIL"}


def load_carrier_inputs():
    out = []
    for fn in sorted(os.listdir(FX_INPUTS)):
        if fn.startswith("rf-rf-global34-") and fn.endswith(".json"):
            with open(os.path.join(FX_INPUTS, fn), encoding="utf-8") as f:
                out.append(json.load(f))
    if not out:
        raise Refuse("no rf-rf-global34 carrier inputs found")
    return out


def src_from_carrier(c):
    return {"path": c["preset"]["path"],
            "declared_sha1": c["preset"]["census_blob_sha1_verified"],
            "carrier_source": c["carrier_source"], "diagnostic": False,
            "base_set": {},
            "occ3": bool(c["global3"]["occupied"]),
            "occ4": bool(c["global4"]["occupied"]),
            "dis3": bool(c["global3"]["fx_disable_bit"]),
            "dis4": bool(c["global4"]["fx_disable_bit"]),
            "fxb": c["patch_level"]["fx_bypass"],
            "fxd": c["patch_level"]["fx_disable_mask"],
            "type3": c["global3"]["type_name"],
            "type4": c["global4"]["type_name"]}


def src_diagnostic():
    """DIAGNOSTIC host (decision record 0019 invariant 4): a repeatable
    factory voice path with global3/global4 populated by explicit type
    overrides. Exercises the engine's routing semantics only; never an
    original-preset carrier, never counted toward coverage."""
    return {"path": DIAG_PRESET, "declared_sha1": None,
            "carrier_source": "DIAGNOSTIC adaptation: repeatable factory "
                              "voice with global3/global4 set by override; "
                              "not an original carrier",
            "diagnostic": True, "base_set": dict(DIAG_SET),
            "occ3": True, "occ4": True, "dis3": False, "dis4": False,
            "fxb": rm.FXB_ALL_FX, "fxd": 0,
            "type3": DIAG_SET[SLOT_G3], "type4": DIAG_SET[SLOT_G4]}


def run_pair(surgepy, src, seq_id, wav_dir):
    rel = src["path"]
    seq, _, seq_sha = rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel)
    blob, graph = rff.census_entry(rel)
    if oc.git_blob_sha1(abs_path) != blob:
        raise Refuse(f"census blob mismatch: {rel}")
    if src["declared_sha1"] and blob != src["declared_sha1"]:
        raise Refuse(f"carrier input blob drifted from census: {rel}")
    roles = slot_roles(graph)
    specs = bus_specs(roles, src["base_set"])
    slug = ("diag-" if src["diagnostic"] else "") + \
        rel.rsplit("/", 1)[-1][:-4].lower().replace(" ", "-")
    pair_id = f"{slug}__{seq_id}"

    buses, hashes = {}, {}
    for name, mods in specs.items():
        buses[name], hashes[name] = render_bus(surgepy, abs_path, seq, mods)
    frames = buses["orig"].shape[1]
    for name, b in buses.items():
        if b.shape[1] != frames:
            raise Refuse(f"bus {name} length differs from orig")

    occ3, occ4, fxb, fxd = src["occ3"], src["occ4"], src["fxb"], src["fxd"]
    en3 = occ3 and not src["dis3"]
    en4 = occ4 and not src["dis4"]
    stage_in = buses["g34off"]
    q_stage = quantize(stage_in)

    # ---- manifest (committed): hashes only, WAVs stay in the scratch dir
    os.makedirs(wav_dir, exist_ok=True)
    bus_docs = {}
    for name, b in buses.items():
        wp = os.path.join(wav_dir, f"{pair_id}-{name}.f32.wav")
        rff.write_wav_stereo_f32(wp, b)
        bus_docs[name] = {
            "mods": specs[name],
            "sha256_raw_float32": hashes[name][0],
            "determinism_repeats_bit_identical": REPEATS,
            "peak_abs_float": float(np.max(np.abs(b))),
            "wav_sha256": rf.sha256_file(wp),
        }
    manifest = {
        "schema_version": 1,
        "fixture_id": pair_id,
        "issue": "SXT-028j / #150",
        "claim_scope": "reference-vs-reference buses of the pinned engine "
                       "under the SXT-012 policies; no fidelity, support or "
                       "quality claim",
        "preset": {"path": rel, "census_blob_sha1": blob,
                   "carrier_source": src["carrier_source"],
                   "diagnostic": src["diagnostic"],
                   "slot_type_overrides": src["base_set"]},
        "sequence": {"id": seq_id, "sha256": seq_sha},
        "render": {"sample_rate": SR, "block_size": BS, "frames": frames,
                   "duration_s": round(frames / SR, 6),
                   "tail_s": seq.get("tail_s", 2.5),
                   "settle_s": seq.get("settle_s", 0.25),
                   "policies_inherited": "fixtures/render_fixture.py + "
                                         "tools/render_fx_fixtures.py"},
        "wet": {"frames": frames, "tail_s": seq.get("tail_s", 2.5),
                "bus": "orig"},
        "audio_policy": "stereo float32 (IEEE fmt 3), raw engine output, no "
                        "clip, no normalization, no fades",
        "wavs_committed": False,
        "wav_scratch_note": "WAVs are regenerable (tens of MB); identity is "
                            "the per-bus sha256_raw_float32 below",
        "slot_roles": roles,
        "buses": bus_docs,
        "engine": rf.engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "tool": rf.tool_version(),
    }
    sidecar = os.path.join(FIXTURES_DIR, f"{pair_id}.json")
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    # ---- engine routing checks (exact equality, nothing modeled)
    stage_active_orig = not same(buses["orig"], stage_in)
    routing = {
        "stage_active_in_orig": stage_active_orig,
        "bypass_no_fx_equals_dry": same(buses["byp_no_fx"], buses["dry"]),
        "bypass_scene_fx_only_equals_inserts_only":
            same(buses["byp_scene_fx_only"], buses["nonins_off"]),
        "bypass_no_sends_equals_sends_off_when_stage_inert":
            same(buses["byp_no_sends"], buses["sends_off"]),
        "bypass_no_sends_stage_active":
            not same(buses["byp_no_sends"], buses["sends_g34_off"]),
        "slot3_bypass_changes_bus": not same(buses["g3off"], buses["orig"]),
        "slot4_bypass_changes_bus": not same(buses["g4off"], buses["orig"]),
    }

    # ---- model-vs-engine routing agreement (boolean, exact)
    obs = {
        "orig": stage_active_orig,
        "byp_no_sends": not same(buses["byp_no_sends"], buses["sends_g34_off"]),
        "byp_scene_fx_only":
            not same(buses["byp_scene_fx_only"], buses["nonins_off"]),
        "byp_no_fx": not same(buses["byp_no_fx"], buses["dry"]),
    }
    cfg = {
        "orig": (fxb, fxd),
        "byp_no_sends": (rm.FXB_NO_SENDS, fxd),
        "byp_scene_fx_only": (rm.FXB_SCENE_FX_ONLY, fxd),
        "byp_no_fx": (rm.FXB_NO_FX, fxd),
    }
    # The stage input for the modes that also drop other slots differs from
    # g34off; the boolean routing prediction uses the stage-input bus of the
    # mode's own upstream, approximated by g34off (the stage's gating does not
    # depend on the bus values, only on a nonzero signal being present).
    agreement = {}
    for name, (b, d) in cfg.items():
        pred = predict_active(q_stage, b, d, occ3, occ4)
        agreement[name] = {"model_predicts_active": pred,
                           "engine_observed_active": obs[name],
                           "agree": pred == obs[name],
                           "discriminating": bool(en3 or en4)}

    controls = {}
    for kind, name in (("partition", "byp_scene_fx_only"),
                       ("ignore-bypass", "byp_no_fx")):
        b, d = cfg[name]
        wrong = predict_active(q_stage, b, d, occ3, occ4, wrong=kind)
        controls[kind] = {"config": name, "wrong_model_predicts_active": wrong,
                          "engine_observed_active": obs[name],
                          "disagrees_with_engine": wrong != obs[name],
                          "discriminating": bool(en3 or en4)}

    # ---- enqueueFXOff drain timing (engine, exact)
    timing = None
    target = SLOT_G4 if (en4 and routing["slot4_bypass_changes_bus"]) else \
        (SLOT_G3 if (en3 and routing["slot3_bypass_changes_bus"]) else None)
    if target is not None:
        ref_off = buses["g4off"] if target == SLOT_G4 else buses["g3off"]
        n_blk = frames // BS
        pb = np.any(buses["orig"][:, :n_blk * BS] != ref_off[:, :n_blk * BS],
                    axis=0).reshape(n_blk, BS).any(axis=1)
        cand = [k for k in range(600, n_blk - 1) if pb[k] and pb[k + 1]]
        if cand:
            k = cand[0]
            q_bus, _ = render_bus(surgepy, abs_path, seq, specs["orig"],
                                  repeats=REPEATS,
                                  queue_off=(k, target))
            fd_orig = first_diff_block(q_bus, buses["orig"])
            tail_equals_off = same(q_bus[:, k * BS:], ref_off[:, k * BS:])
            timing = {
                "slot": target, "queued_before_block": k,
                "first_block_departing_from_orig": fd_orig,
                "blocks_from_k_equal_slot_off_from_start": tail_equals_off,
                "drains_at_the_control_pass_preceding_block_k":
                    bool(fd_orig == k and tail_equals_off),
            }
        else:
            timing = {"slot": target, "status": "NOT_RUN",
                      "reason": "no block >= 600 where the slot audibly "
                                "contributes in two consecutive blocks"}

    # ---- waveform leg (measured; agreement claim withheld, see docstring)
    wf = waveform_leg(buses["orig"], stage_in, fxb, fxd, occ3, occ4, sidecar)
    if en3 or en4:
        wf["agreement_claim"] = "NO_VERDICT"
        wf["agreement_claim_reason"] = (
            "occupant_not_modeled: the frozen model's per-slot occupant is a "
            "synthetic biquad; the engine's concrete algorithm "
            f"({src['type3'] if en3 else ''}"
            f"{'/' if en3 and en4 else ''}"
            f"{src['type4'] if en4 else ''}) belongs to "
            "its algorithm leaf. The numbers are measurements, not agreement.")
    else:
        wf["agreement_claim"] = wf["budget_verdict"] + \
            " (routing gate only: both slots inert in the engine and the " \
            "model; no occupant algorithm is exercised)"
        wf["agreement_claim_reason"] = "stage inert in both"
    wf["note"] = "budgets [PROPOSED, not frozen]; freeze gated on SXT-017 (#12)"

    print(f"{pair_id}: orig {hashes['orig'][0][:12]} stage_active="
          f"{stage_active_orig} budget_verdict={wf['budget_verdict']}")
    return {
        "fixture_id": pair_id, "diagnostic": src["diagnostic"],
        "manifest": os.path.relpath(sidecar, REPO),
        "occupancy": {"global3": occ3, "global4": occ4,
                      "global3_enabled": en3, "global4_enabled": en4,
                      "fx_bypass": fxb, "fx_disable_mask": fxd},
        "engine_routing_checks": routing,
        "model_vs_engine_routing_agreement": agreement,
        "live_negative_controls": controls,
        "fx_off_drain_timing": timing,
        "model_vs_engine_waveform": wf,
    }


def carrier_gate(surgepy, carrier, seq_id):
    """The SXT-012/023 exact gate on the carrier's own buses (policy #310,
    decision record 0019): 3 fresh-instance renders must be bit-identical.
    Not softened, no seed/drift conditioning. Records the FIRST DIVERGING
    bus (dry voice path before wet FX path, invariant 6)."""
    rel = carrier["preset"]["path"]
    seq, _, _ = rf.load_sequence(seq_id)
    abs_path = os.path.join(oc.engine_dir(), rel)
    blob, graph = rff.census_entry(rel)
    if oc.git_blob_sha1(abs_path) != blob:
        raise Refuse(f"census blob mismatch: {rel}")
    specs = bus_specs(slot_roles(graph))
    rows = {}
    for name in ("dry", "g34off", "orig"):
        _, hashes = render_bus(surgepy, abs_path, seq, specs[name],
                               strict=False)
        rows[name] = {"sha256_per_repeat": hashes,
                      "distinct_buffers": len(set(hashes)),
                      "bit_identical": len(set(hashes)) == 1}
    first = next((n for n in ("dry", "g34off", "orig")
                  if not rows[n]["bit_identical"]), None)
    return {"carrier": rel, "carrier_source": carrier["carrier_source"],
            "sequence": seq_id, "census_blob_sha1": blob, "buses": rows,
            "gate": "PASS" if first is None else "REFUSED",
            "first_diverging_bus": first,
            "repeats": REPEATS,
            "native_drift_gate": carrier["oracle_extraction"]["live"]
            ["determinism_gate"]["status"],
            "reading": "REFUSED = source-nonrepeatable original preset "
                       "(decision record 0019); stays recorded as REFUSED, "
                       "unsupported-pending, never silently substituted. "
                       "Native drift 0 is eligibility, not repeatability."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav-dir", default="/tmp/sxt028j-reference-wavs",
                    help="scratch dir for the (uncommitted) reference WAVs")
    args = ap.parse_args()
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    carriers = load_carrier_inputs()
    gates, pairs = [], []
    for carrier in carriers:
        if not carrier["oracle_extraction"].get("ok"):
            raise Refuse("run tools/extract_rf_global34_inputs.py on the "
                         "oracle host first (live extraction not recorded)")
        for seq_id in SEQUENCES:
            g = carrier_gate(surgepy, carrier, seq_id)
            gates.append(g)
            print(f"{os.path.basename(g['carrier'])} {seq_id}: {g['gate']} "
                  f"(first diverging bus: {g['first_diverging_bus']})")
            if g["gate"] == "PASS":
                pairs.append(run_pair(surgepy, src_from_carrier(carrier),
                                      seq_id, args.wav_dir))
    for seq_id in SEQUENCES:
        pairs.append(run_pair(surgepy, src_diagnostic(), seq_id,
                              args.wav_dir))

    diag = [p for p in pairs if p["diagnostic"]]
    disc = [p for p in diag if p["occupancy"]["global3_enabled"] or
            p["occupancy"]["global4_enabled"]]
    agree_all = all(a["agree"] for p in pairs
                    for a in p["model_vs_engine_routing_agreement"].values())
    controls_ok = {
        k: any(p["live_negative_controls"][k]["disagrees_with_engine"]
               for p in disc)
        for k in ("partition", "ignore-bypass")}
    refused = [g for g in gates if g["gate"] == "REFUSED"]
    record = {
        "schema_version": 1,
        "leaf": "SXT-028j",
        "issue": "#150",
        "engine_pin": ENGINE_PIN,
        "model_revision": rm.model_revision(),
        "claim_scope": "model-vs-pinned-engine (claim 2) for the routing "
                       "form only. NOT an RTL claim, NOT a preset-support "
                       "claim, NOT a listening record.",
        "sequences": SEQUENCES,
        "carrier_determinism_gate": gates,
        "pairs": pairs,
        "coverage": {
            "carrier_sequence_pairs_gated": len(gates),
            "carrier_sequence_pairs_refused_nonrepeatable": len(refused),
            "original_carrier_pairs_rendered": len(pairs) - len(diag),
            "diagnostic_pairs_rendered": len(diag),
            "note": "coverage is reported separately from agreement; "
                    "diagnostic pairs never count toward original-preset "
                    "coverage",
        },
        "summary": {
            "original_carrier_agreement":
                "NOT_RUN" if len(refused) == len(gates) else "PARTIAL",
            "original_carrier_agreement_reason":
                "every named/added carrier is source-nonrepeatable on the "
                "pinned engine, so no original-preset reference fixture "
                "exists to compare against (policy #310, decision record "
                "0019); blocked on a reproducibility-census carrier (#381)"
                if len(refused) == len(gates) else "see carrier gates",
            "diagnostic_model_vs_engine_routing_agreement_all_exact":
                agree_all,
            "diagnostic_live_negative_controls_fail_as_required":
                controls_ok,
            "fx_disable_gate_engine_probe":
                "BLOCKED: surgepy setParamVal cannot set the int fx_disable "
                "parameter (every value reads back -2147483648); the "
                "model's bits-14|15 gate stays a declared, source-read "
                "contract (EVIDENCE 0b)",
        },
    }
    with open(RECORD, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
    lines = ["SXT-028j pinned-engine fixture renders (#150)",
             "status: RAN -- carriers REFUSED by the exact 3x gate",
             "",
             "Policy #310 / decision record 0019: a preset whose own render "
             "is not bit-identical over 3 fresh instances is REFUSED as an "
             "original carrier; the gate is not softened.", ""]
    for g in gates:
        lines.append(f"{g['gate']}: {os.path.basename(g['carrier'])} x "
                     f"{g['sequence']}: first diverging bus="
                     f"{g['first_diverging_bus']}; distinct buffers per bus="
                     + ", ".join(f"{n}:{r['distinct_buffers']}"
                                 for n, r in g["buses"].items()))
    lines += ["", "Diagnostic routing probe (NOT an original carrier): "
              f"{DIAG_PRESET} with global3/global4 overrides; manifests in "
              "reports/SXT-028j/fixtures/.",
              "record: reports/SXT-028j/model-vs-reference.json"]
    with open(REFUSALS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps(record["summary"], indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Refuse, oc.OracleBindingError) as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
