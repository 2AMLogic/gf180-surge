#!/usr/bin/env python3
"""SXT-014: one-effect-at-a-time FX ablation renders through the pinned oracle.

For each selected preset + fixture sequence this tool renders, each in a fresh
engine instance under the SXT-012 reset policy:

  original     the unmodified loaded patch (all patch-defined effects active)
               -- the product-family reference; NEVER overwritten;
  bypass-slot  one non-Off FX slot bypassed (its "type" parameter set to
               fxt_off via the official surgepy parameter path before settle),
               everything else untouched;
  dry-allfxoff all 16 FX slots set to Off (the diagnostic dry bus);
  offslot-ctrl NEGATIVE CONTROL: one already-Off slot "bypassed" -- must be
               bit-identical to the original render for presets in the
               bit-identical repeatability class (retrigger-on);
  permuted     NEGATIVE CONTROL: two same-type FX slots exchange parameter
               sets (wrong arrangement); the comparator must flag it;
  substituted  ADAPTATION: one slot's type swapped to a different effect.
               Substitution renders go ONLY into an adapted/ subtree and are
               labeled ADAPTED -- a generic substitution disqualifies
               original-preset support (plan section 3, AGENTS.md).

Essential/optional/unresolved effect labels are LISTENING judgments (issue #9
acceptance): this tool produces renders + metadata only. Numeric deltas are
produced by tools/ablation_delta.py and are diagnostic only.

Policies are inherited from fixtures/render_fixture.py (reset, scheduling,
tail, audio); every render is verified non-perturbing: after the mutation and
settle, every non-mutated slot's type, 12 params and return level must read
back bit-identically to the pristine post-load state, and every mutated slot
must read back in its intended state. Original renders are cross-checkable
against the committed SXT-012 fixtures for bit-identical-class presets.

Metadata sidecars (one JSON per render) record: preset path + census blob
SHA-1 + file SHA-256, slot (index, role, type id/name, Airwindows id/name),
sequence id + SHA-256, engine pin, WAV SHA-256/bytes, the non-perturbation
proof, the render policy, and tool identity. `verify` re-derives all hashes
and refuses on any mismatch (metadata-tamper negative control).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "fixtures"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

# Enforce the pinned interpreter before importing the engine binding.
oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402
import render_fixture as rf  # noqa: E402  (policies + sequence library, reused)

SR = rf.SR
FX_SLOTS = rf.FX_SLOTS
GRAPHS_JSONL = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
DEFAULT_OUT = os.path.join(REPO, "reports", "sxt-014", "ablations")
DEFAULT_SEQS = ["seq-notes-coverage-v1", "seq-poly-8-v1"]

PILOT_PRESETS = {
    "doomsday": "Basses/Doomsday.fxp",
    "width": "Basses/Width.fxp",
    "behemoth": "Basses/Behemoth.fxp",
    "koala2": "Leads/Koala 2.fxp",
    "fmcombo": "Basses/FM Combo.fxp",
    "fmod09": "Tutorials/Formula Modulator/09 Example - Crossfading Oscillators.fxp",
}
CONTROL_PRESETS = {
    "sub4": "Basses/Sub 4.fxp",   # all 16 slots Off; bit-identical class
    "fuji": "Leads/Fuji.fxp",     # Delay in slots 0 and 4; wrong-order control
}
ALL_PRESETS = {**PILOT_PRESETS, **CONTROL_PRESETS}

BIT_IDENTICAL_CLASS = {"sub4", "behemoth"}        # per reports/sxt-012/repeatability.json
FREE_PHASE_CLASS = {"koala2"}                     # quantified variation, not bit-identical


class Refuse(Exception):
    pass


def sha256_file(path):
    return oc.sha256_file(path)


def tool_version():
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "tools/ablate_fx.py", "tools/ablation_delta.py",
             "oracle/", "fixtures/sequences", "fixtures/render_fixture.py",
             "corpus/normalized/graphs.jsonl", "corpus/census-v0.1/results/per-preset.csv"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
        inputs_clean = dirty == ""
    except Exception as e:  # pragma: no cover
        commit, inputs_clean = f"unavailable: {e}", False
    return {"repo_commit": commit, "pinned_inputs_clean": inputs_clean,
            "script_sha256": sha256_file(os.path.abspath(__file__))}


def load_graphs():
    by_path = {}
    with open(GRAPHS_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by_path[r["p"]] = r
    return by_path


def graph_for(graphs, preset_rel):
    key = "resources/data/patches_factory/" + preset_rel
    if key not in graphs:
        raise Refuse(f"no normalized graph for {preset_rel}")
    return graphs[key]


def slot_meta(graph, slot_index):
    for s in graph["g"]["fx"]:
        if s["i"] == slot_index:
            meta = {"index": slot_index, "role": s["r"], "type_id": s["t"], "type_name": s["tn"]}
            if "aw" in s:
                meta["airwindows"] = {"algorithm_id": s["aw"], "algorithm_name": s["awn"]}
            return meta
    raise Refuse(f"graph has no slot {slot_index}")


def type_slug(type_name):
    return "".join(ch for ch in type_name if ch.isalnum())


def snapshot_slots(s, patch):
    """Exact float snapshot of all 16 slots: (type, [12 params], return_level)."""
    snap = []
    for i in range(FX_SLOTS):
        sl = patch["fx"][i]
        snap.append((
            float(s.getParamVal(sl["type"])),
            [float(s.getParamVal(h)) for h in sl["p"]],
            float(s.getParamVal(sl["return_level"])),
        ))
    return snap


def slots_equal(a, b):
    return a == b


def verify_preset_blob(preset_rel):
    preset_abs = os.path.join(oc.data_home(), "patches_factory", preset_rel)
    actual = oc.git_blob_sha1(preset_abs)
    expected = rf.census_blob(preset_rel)
    if actual != expected:
        raise Refuse(f"preset blob {actual} != census {expected}: {preset_rel}")
    return preset_abs, expected, sha256_file(preset_abs)


def render_variant(surgepy, preset_abs, seq, out_dir, base_name,
                   bypass_slots=(), mutate=None, mutated_slots=(), kinds=None):
    """One render in a fresh instance under the SXT-012 policies.

    bypass_slots: slot indices whose "type" param is set to fxt_off before settle.
    mutate: optional callable(s, patch) applied after the bypass setters (used by
    the permuted/substituted controls); its readback is recorded, not assumed.
    mutated_slots: all slot indices intentionally changed (bypass setters + mutate);
    every other slot must read back bit-identically (non-perturbation proof).
    Returns the sidecar dict. Refuses to overwrite existing files.
    """
    import surgepy.constants as C

    wav_path = os.path.join(out_dir, base_name + ".wav")
    json_path = os.path.join(out_dir, base_name + ".json")
    for p in (wav_path, json_path):
        if os.path.exists(p):
            raise Refuse(f"refusing to overwrite existing render: {p}")

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
        pristine = snapshot_slots(s, patch)

        for i in bypass_slots:
            s.setParamVal(patch["fx"][i]["type"], C.fxt_off)
        mutation_record = None
        if mutate is not None:
            mutation_record = mutate(s, patch)

        bs = int(s.getBlockSize())
        settle_blocks = int(seq.get("settle_s", 0.25) * SR) // bs
        sbuf = s.createMultiBlock(settle_blocks)
        s.processMultiBlock(sbuf)

        # Readback verification: mutated slots in intended state, every other
        # slot bit-identical to the pristine post-load state.
        after = snapshot_slots(s, patch)
        for i in bypass_slots:
            if int(after[i][0]) != int(C.fxt_off):
                raise Refuse(f"slot {i} did not read back Off")
        others = [i for i in range(FX_SLOTS) if i not in set(bypass_slots) | set(mutated_slots)]
        n_params = sum(1 + len(pristine[i][1]) + 1 for i in others)
        diff = [i for i in others if after[i] != pristine[i]]
        if diff:
            raise Refuse(f"non-perturbation proof failed for slots {diff}")

        events = seq["events"]
        tempo_total = sum(1 for e in events if e["type"] == "tempo")
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
            nxt = rf.dispatch(s, events[dispatched:], b, quant) + dispatched
            if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                raise Refuse("scheduler failed to advance")
            seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
            s.processMultiBlock(buf, b, seg - b)
            b = seg
            dispatched = nxt

        stereo = np.asarray(buf)
        mono = 0.5 * (stereo[0] + stereo[1])
        clipped = int(np.sum(np.abs(mono) > 1.0))
    finally:
        del s

    os.makedirs(out_dir, exist_ok=True)
    oc.write_wav_mono16(wav_path, mono, SR)

    sidecar = {
        "schema_version": 1,
        "issue": "SXT-014",
        "claim_scope": "reference-vs-reference ablation apparatus only: renders of the pinned "
                       "engine under the SXT-012 policies with one FX slot bypassed/mutated. "
                       "Numeric deltas are diagnostic; essential/optional/unresolved labels "
                       "require listening records and are BLOCKED-on-human (issue #9).",
        "ablation_id": os.path.relpath(json_path, DEFAULT_OUT).replace(".json", ""),
        "kind": kinds["kind"],
        "label": kinds["label"],
        "adapted": kinds.get("adapted", False),
        "bypassed_slots": sorted(bypass_slots),
        "mutated_slots": sorted(set(bypass_slots) | set(mutated_slots)),
        "slot": kinds.get("slot"),
        "repeatability_class": kinds.get("repeatability_class"),
        "mutation": mutation_record,
        "preset": kinds["preset"],
        "sequence": kinds["sequence"],
        "engine": rf.engine_identity(surgepy, surgepy.createSurge(float(SR))),
        "render": {
            "sample_rate": SR,
            "scheduling": "block-quantized (32 samples), ceil to next block start",
            "frames": int(total_blocks * bs),
            "duration_s": round(total_blocks * bs / SR, 6),
            "tail_s": tail_s,
            "settle_s": float(seq.get("settle_s", 0.25)),
            "peak_abs_float": float(np.max(np.abs(mono))) if mono.size else 0.0,
            "clipped_samples": clipped,
            "tempo_events_total": tempo_total,
            "tempo_events_applied": 0,
            "audio_policy": "mono (L+R)/2, int16 PCM, hard clip [-1,1], no normalization, "
                            "no time warping, no fades",
        },
        "non_perturbation_proof": {
            "method": "post-settle exact readback of type + 12 params + return_level for every "
                      "non-mutated slot vs the pristine post-load snapshot",
            "other_slots_bit_unchanged": True,
            "slots_checked": len(others),
            "values_checked": n_params,
        },
        "wav": {"path": os.path.relpath(wav_path, REPO), "sha256": sha256_file(wav_path),
                "bytes": os.path.getsize(wav_path)},
        "tool": tool_version(),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
        f.write("\n")
    return sidecar


def kinds_common(preset_slug, preset_rel, seq, seq_path, seq_sha):
    preset_abs, blob, psha = verify_preset_blob(preset_rel)
    return {
        "preset": {
            "slug": preset_slug,
            "path": "resources/data/patches_factory/" + preset_rel,
            "census_blob_sha1": blob,
            "file_sha256": psha,
        },
        "sequence": {"id": seq["id"], "sha256": seq_sha, "path": os.path.relpath(seq_path, REPO)},
    }, preset_abs


def engine_slot_types(surgepy, preset_abs):
    """Non-Off slots per the engine at load: {slot: type_id}, cross-checkable vs graphs."""
    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse(f"loadPatch failed: {preset_abs}")
        patch = s.getPatch()
        return {i: int(s.getParamVal(patch["fx"][i]["type"])) for i in range(FX_SLOTS)
                if int(s.getParamVal(patch["fx"][i]["type"])) != 0}
    finally:
        del s


def cmd_ablate(args):
    surgepy = rf.import_surgepy()
    graphs = load_graphs()
    seq_ids = args.sequences.split(",") if args.sequences else DEFAULT_SEQS
    run_entries = []
    for slug in (args.presets.split(",") if args.presets else sorted(PILOT_PRESETS)):
        if slug not in PILOT_PRESETS:
            raise Refuse(f"unknown pilot preset {slug!r}")
        preset_rel = PILOT_PRESETS[slug]
        graph = graph_for(graphs, preset_rel)
        for sid in seq_ids:
            seq, seq_path, seq_sha = rf.load_sequence(sid)
            common, preset_abs = kinds_common(slug, preset_rel, seq, seq_path, seq_sha)
            out_dir = os.path.join(args.out, slug)

            active = engine_slot_types(surgepy, preset_abs)
            gtypes = {s["i"]: s["t"] for s in graph["g"]["fx"]}
            for i, t in active.items():
                if gtypes.get(i) != t:
                    raise Refuse(f"graphs/engine type mismatch at slot {i}: {preset_rel}")

            # (a) original
            run_entries.append(render_variant(
                surgepy, preset_abs, seq, out_dir, f"{sid}-original",
                kinds={"kind": "original", "label": "reference: unmodified loaded patch "
                        "(all patch-defined effects active)", **common, }
            ))
            # (b) per-slot bypass
            for i in active:
                meta = slot_meta(graph, i)
                label = f"ablation variant: slot {i} ({meta['type_name']}"
                if "airwindows" in meta:
                    label += f" / {meta['airwindows']['algorithm_name']}"
                label += ") bypassed; original-preset family"
                run_entries.append(render_variant(
                    surgepy, preset_abs, seq, out_dir,
                    f"{sid}-bypass-slot{i:02d}-{type_slug(meta['type_name'])}",
                    bypass_slots=[i],
                    kinds={"kind": "bypass-slot", "label": label, "slot": meta,
                           **common},
                ))
            # (c) all-FX-off dry
            run_entries.append(render_variant(
                surgepy, preset_abs, seq, out_dir, f"{sid}-dry-allfxoff",
                bypass_slots=list(range(FX_SLOTS)),
                kinds={"kind": "dry-allfxoff",
                       "label": "diagnostic dry bus: all 16 FX slots Off", **common},
            ))
            print(f"ablated {slug} / {sid}: {1 + len(active) + 1} renders")
    write_run_manifest(run_entries, args.out, "ablate")
    return 0


def cmd_offslot_control(args):
    """Off-slot bypass must be bit-identical to the original render.

    Proof is per repeatability class (reports/sxt-012/repeatability.json):
    bit-identical for retrigger-on presets (sub4, behemoth); for free-phase
    presets (koala2) bit-identity is NOT expected across instances -- the
    variant is compared against the repeat-render variation bounds instead
    (diagnostic only, decided by the delta tool).
    """
    surgepy = rf.import_surgepy()
    graphs = load_graphs()
    slug = args.preset
    if slug not in ALL_PRESETS:
        raise Refuse(f"unknown preset {slug!r}")
    preset_rel = ALL_PRESETS[slug]
    graph = graph_for(graphs, preset_rel)
    seq, seq_path, seq_sha = rf.load_sequence(args.sequence)
    common, preset_abs = kinds_common(slug, preset_rel, seq, seq_path, seq_sha)
    out_dir = os.path.join(args.out, slug)

    gtypes = {s["i"]: s for s in graph["g"]["fx"]}
    run_entries = []
    if args.render_original_anchor:
        run_entries.append(render_variant(
            surgepy, preset_abs, seq, out_dir, f"{seq['id']}-original",
            kinds={"kind": "original",
                   "label": "reference: unmodified loaded patch (control anchor)", **common},
        ))
    for i in [int(x) for x in str(args.slots).split(",")]:
        if gtypes.get(i, {}).get("t") != 0:
            raise Refuse(f"slot {i} is not Off in the normalized graph: {preset_rel}")
        kind = "offslot-ctrl"
        label = ("negative control: already-Off slot %d bypassed; expected bit-identical "
                 "to the original render in the bit-identical repeatability class" % i)
        run_entries.append(render_variant(
            surgepy, preset_abs, seq, out_dir, f"{seq['id']}-offslot-ctrl-slot{i:02d}",
            bypass_slots=[i], kinds={"kind": kind, "label": label, "slot": slot_meta(graph, i),
                                     "repeatability_class": ("bit-identical" if slug in BIT_IDENTICAL_CLASS
                                                             else "free-phase"), **common},
        ))
    write_run_manifest(run_entries, args.out, f"offslot-control-{slug}")
    return 0


def make_permutation(slot_a, slot_b):
    """Swap the full contents (type + params + return level) of two slots.

    Transfer through setParamVal is NOT guaranteed bit-exact (float32 path +
    engine deactivation markers); the readback diff is recorded per render so
    the control's interpretation is honest about what moved.
    """
    def mutate(s, patch):
        def snap(i):
            sl = patch["fx"][i]
            return (float(s.getParamVal(sl["type"])),
                    [float(s.getParamVal(h)) for h in sl["p"]],
                    float(s.getParamVal(sl["return_level"])))
        sa, sb = snap(slot_a), snap(slot_b)
        for i, want in ((slot_b, sa), (slot_a, sb)):
            sl = patch["fx"][i]
            s.setParamVal(sl["type"], want[0])
            for h, v in zip(sl["p"], want[1]):
                s.setParamVal(h, v)
            s.setParamVal(sl["return_level"], want[2])
        got_a, got_b = snap(slot_a), snap(slot_b)
        return {
            "method": f"contents of slots {slot_a} and {slot_b} exchanged via setParamVal "
                      "(type + 12 params + return level), read back and recorded",
            "slots": [slot_a, slot_b],
            "transfer_exact": bool(got_a == sb and got_b == sa),
            "transfer_diff": {
                f"slot{slot_a}": [{"param_index": k, "intended": v, "readback": g}
                                  for k, (v, g) in enumerate(zip(sb[1], got_a[1])) if v != g],
                f"slot{slot_b}": [{"param_index": k, "intended": v, "readback": g}
                                  for k, (v, g) in enumerate(zip(sa[1], got_b[1])) if v != g],
            },
            "interpretation_caveat": "the permuted render differs from the original through "
                                     " BOTH the arrangement change and any param-transfer "
                                     "epsilon; numeric detection of the permutation is the "
                                     "control's claim, order-only attribution is not",
        }
    return mutate


def cmd_permute(args):
    surgepy = rf.import_surgepy()
    graphs = load_graphs()
    slug = args.preset
    preset_rel = ALL_PRESETS[slug]
    graph = graph_for(graphs, preset_rel)
    seq, seq_path, seq_sha = rf.load_sequence(args.sequence)
    common, preset_abs = kinds_common(slug, preset_rel, seq, seq_path, seq_sha)
    out_dir = os.path.join(args.out, slug)
    a, b = [int(x) for x in str(args.slots).split(",")]
    gslots = {s["i"]: s for s in graph["g"]["fx"]}
    ta, tb = gslots[a]["tn"], gslots[b]["tn"]
    if ta != tb:
        raise Refuse(f"permutation control requires same-type slots; got {ta!r} vs {tb!r}")
    run_entries = []
    if args.render_original_anchor:
        run_entries.append(render_variant(
            surgepy, preset_abs, seq, out_dir, f"{seq['id']}-original",
            kinds={"kind": "original",
                   "label": "reference: unmodified loaded patch (control anchor)", **common},
        ))
    run_entries.append(render_variant(
        surgepy, preset_abs, seq, out_dir,
        f"{seq['id']}-permuted-swap{a:02d}-with{b:02d}",
        mutate=make_permutation(a, b), mutated_slots=[a, b],
        kinds={"kind": "permuted",
               "label": f"negative control: same-type slots {a}/{b} ({ta}) exchanged -- "
                        f"wrong arrangement; comparator must flag", **common},
    ))
    write_run_manifest(run_entries, args.out, f"permute-{slug}")
    return 0


def make_substitution(slot, target_type_name):
    """Swap one slot's type to another effect; renders are ADAPTED.

    Params are NOT copied: the slot keeps whatever the engine does on a type
    swap (recorded by readback). A substituted render is an adaptation of the
    preset and is excluded from original-preset coverage by definition.
    """
    import surgepy.constants as C
    target_id = getattr(C, target_type_name, None)
    if target_id is None:
        raise Refuse(f"unknown fxt constant {target_type_name!r}")

    def mutate(s, patch):
        s.setParamVal(patch["fx"][slot]["type"], target_id)
        after = snapshot_slots(s, patch)[slot]
        return {
            "method": f"slot {slot} type set to {target_type_name} ({int(target_id)}) via "
                      f"setParamVal; params not copied (engine state after swap recorded)",
            "slot": slot,
            "target_type": {"constant": target_type_name, "id": int(target_id)},
            "slot_readback_after": {"type": after[0], "params": after[1],
                                    "return_level": after[2]},
        }
    return mutate


def cmd_substitute(args):
    surgepy = rf.import_surgepy()
    graphs = load_graphs()
    slug = args.preset
    if slug not in PILOT_PRESETS:
        raise Refuse(f"unknown pilot preset {slug!r}")
    preset_rel = PILOT_PRESETS[slug]
    graph = graph_for(graphs, preset_rel)
    seq, seq_path, seq_sha = rf.load_sequence(args.sequence)
    common, preset_abs = kinds_common(slug, preset_rel, seq, seq_path, seq_sha)
    meta = slot_meta(graph, args.slot)
    out_dir = os.path.join(args.out, slug, "adapted")
    target = args.to_type
    base = f"{seq['id']}-subst-slot{args.slot:02d}-{type_slug(meta['type_name'])}" \
           f"-to-{target.replace('fxt_', '')}__ADAPTED"
    entry = render_variant(
        surgepy, preset_abs, seq, out_dir, base,
        mutate=make_substitution(args.slot, target), mutated_slots=[args.slot],
        kinds={"kind": "substituted",
               "label": f"ADAPTED: slot {args.slot} ({meta['type_name']}) substituted with "
                        f"{target.replace('fxt_', '')}; generic substitution DISQUALIFIES "
                        f"original-preset support; excluded from coverage",
               "slot": meta, "adapted": True, **common},
    )
    write_run_manifest([entry], args.out, f"substitute-{slug}")
    return 0


def write_run_manifest(entries, out_root, tag):
    entries = sorted(entries, key=lambda e: e["ablation_id"])
    man = {
        "schema_version": 1,
        "issue": "SXT-014",
        "run": tag,
        "tool": tool_version(),
        "renders": [{"ablation_id": e["ablation_id"], "kind": e["kind"],
                     "wav": e["wav"], "sidecar": e["ablation_id"] + ".json"}
                    for e in entries],
        "totals": {"renders": len(entries),
                   "wav_bytes": sum(e["wav"]["bytes"] for e in entries)},
    }
    path = os.path.join(out_root, f"run-{tag}.json")
    if os.path.exists(path):
        prev = json.load(open(path, encoding="utf-8"))
        prev["renders"].extend(man["renders"])
        prev["renders"].sort(key=lambda r: r["ablation_id"])
        prev["totals"] = {"renders": len(prev["renders"]),
                          "wav_bytes": sum(r["wav"]["bytes"] for r in prev["renders"])}
        man = prev
    with open(path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2, sort_keys=True)
        f.write("\n")


def cmd_verify(args):
    """Re-derive every hash in the ablation tree; refuse on any mismatch."""
    root = args.root
    checked, failures = 0, []
    graphs = load_graphs()
    seq_dir = os.path.join(REPO, "fixtures", "sequences")
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            if not fn.endswith(".json") or fn.startswith("run-"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as f:
                sc = json.load(f)
            checked += 1
            def fail(msg):
                failures.append(f"{os.path.relpath(path, REPO)}: {msg}")
            wav_abs = os.path.join(REPO, sc["wav"]["path"])
            if not os.path.exists(wav_abs):
                fail("wav missing")
            else:
                if sha256_file(wav_abs) != sc["wav"]["sha256"]:
                    fail("wav sha256 mismatch (metadata tamper or corruption)")
                if os.path.getsize(wav_abs) != sc["wav"]["bytes"]:
                    fail("wav byte length mismatch")
            preset_rel = sc["preset"]["path"].replace("resources/data/patches_factory/", "")
            preset_abs = os.path.join(oc.data_home(), "patches_factory", preset_rel)
            if not os.path.exists(preset_abs):
                fail("preset file missing from pinned engine tree")
            elif oc.git_blob_sha1(preset_abs) != sc["preset"]["census_blob_sha1"]:
                fail("preset census blob mismatch")
            seq_lib = os.path.join(seq_dir, sc["sequence"]["id"] + ".json")
            if sha256_file(seq_lib) != sc["sequence"]["sha256"]:
                fail("sequence sha256 mismatch vs library")
            with open(os.path.join(REPO, "oracle", "manifest.json"), encoding="utf-8") as f:
                if sc["engine"]["engine_commit"] != json.load(f)["engine"]["commit"]:
                    fail("engine pin mismatch vs oracle manifest")
            if sc["adapted"] and "/adapted/" not in path.replace(os.sep, "/"):
                fail("adapted render outside adapted/ tree")
            if not sc["adapted"] and graphs.get(sc["preset"]["path"]) is None:
                fail("preset has no normalized graph")
    if failures:
        print("REFUSING: ablation tree integrity check failed:")
        for m in failures:
            print("  " + m)
        return 2
    print(f"verify OK: {checked} sidecars, all hashes and pins consistent")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ablate", help="original + per-active-slot bypass + dry per preset/sequence")
    p.add_argument("--presets", help="comma-separated pilot slugs (default all)")
    p.add_argument("--sequences", help="comma-separated sequence ids (default 2-pilot)")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.set_defaults(func=cmd_ablate)

    p = sub.add_parser("offslot-control", help="negative control: bypass an already-Off slot")
    p.add_argument("--preset", required=True)
    p.add_argument("--slots", required=True, help="comma-separated Off slot indices")
    p.add_argument("--sequence", default="seq-notes-coverage-v1")
    p.add_argument("--render-original-anchor", action="store_true")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.set_defaults(func=cmd_offslot_control)

    p = sub.add_parser("permute", help="negative control: exchange two same-type slots")
    p.add_argument("--preset", required=True)
    p.add_argument("--slots", required=True, help="two slot indices, e.g. 0,4")
    p.add_argument("--sequence", default="seq-notes-coverage-v1")
    p.add_argument("--render-original-anchor", action="store_true")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.set_defaults(func=cmd_permute)

    p = sub.add_parser("substitute", help="ADAPTED render: swap one slot's effect type")
    p.add_argument("--preset", required=True)
    p.add_argument("--slot", type=int, required=True)
    p.add_argument("--to-type", required=True, help="surgepy fxt_ constant, e.g. fxt_reverb2")
    p.add_argument("--sequence", default="seq-notes-coverage-v1")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.set_defaults(func=cmd_substitute)

    p = sub.add_parser("verify", help="integrity pass over the ablation tree")
    p.add_argument("--root", default=DEFAULT_OUT)
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
