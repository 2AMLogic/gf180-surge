#!/usr/bin/env python3
"""SXT-020 patch-image compiler (issue #13).

Compiles one SXT-011 normalized patch graph (or all of graphs.jsonl) into a
versioned patch image — header (source hashes, DRAFT profile identity), the
verbatim normalized graph (lossless: verify.py rebuilds the graph bytes from
the image and compares hashes), derived voice/FX views, deterministic
allocations from the SXT-015 resource model, event-timing requirements, and
strong checksums — or into an explicit, machine-readable rejection record.

Gate semantics: the SXT-017 DRAFT profile predictor's own evaluator
(``tools/profile_predict.py``) against the selected DRAFT bundle, so compile
outcomes reconcile with ``reports/sxt-017/predictions/`` by construction.
On top the compiler applies the gates an *image emitter* must apply
(complete asset references, expressible send routing, well-formed roles) and
is therefore stricter where the predictor could stay silent. Every
unsupported path yields a cataloged rejection code (``compiler/rejections.json``);
the compiler NEVER emits a trimmed image.

Determinism: same graph bytes + same bundle file + same compiler version =>
byte-identical image/rejection/scan artifacts (sorted-key canonical JSON, no
timestamps anywhere).

Claim discipline: compiling is a structural act. It is NOT a fidelity,
preset-support, or preset-quality claim; the DRAFT bundle is NOT FROZEN; all
allocation numbers are SXT-015 placeholders [PENDING-SXT-016].

Provenance/licensing: original to this repository (Apache-2.0 per LICENSE);
stdlib only; imports this repository's own SXT-015 accounting model and
SXT-017 predictor. No Surge code, tables, or payloads are copied.
"""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from compiler.reject import (  # noqa: E402
    OUTCOME_COMPILED, OUTCOME_REJECTED, OUTCOME_UNRESOLVED,
    engine_order, make_rejection, outcome_for, role_phase,
)
from compiler.assets.wavetable import AssetIdentityError  # noqa: E402
from compiler.version import (  # noqa: E402
    COMPILER_VERSION, CONTAINER_MAGIC, IMAGE_FORMAT_MAJOR, IMAGE_FORMAT_MINOR,
    IMAGE_FORMAT_VERSION,
)
from model.resources.accounting import MODEL_VERSION, account_graph, params_digest  # noqa: E402
from model.resources.params import REG  # noqa: E402
from tools.profile_predict import (  # noqa: E402
    Refuse, load_bundle_file, load_graphs, predict_line, validate_spec,
)

SCAN_ARTIFACT = "sxt-020-compile-corpus-scan"
RECORD_ARTIFACT = "sxt-020-rejection-record"

# Slot-index -> routing role, fixed by the engine (fxslot_positions; the
# graphs' fx[].i / fx[].r pairing). The compiler fails closed on any other
# pairing via routing_form_unsupported.
EXPECTED_ROLE_BY_SLOT = {
    0: "ains1", 1: "ains2", 2: "bins1", 3: "bins2",
    4: "send1", 5: "send2", 6: "global1", 7: "global2",
    8: "ains3", 9: "ains4", 10: "bins3", 11: "bins4",
    12: "send3", 13: "send4", 14: "global3", 15: "global4",
}

# g keys carried in body.graph, grouped. Together they reconstruct g exactly.
_GRAPH_SCALAR_KEYS = ("sm", "smn", "sa", "spl", "poly", "ch", "chn",
                      "fxb", "fxbn", "fxd", "vol")
_GRAPH_GROUP_KEYS = {
    "scenes": "sc", "fx_slots": "fx", "modulation": "md",
    "wavetable_assets": "wta", "dependencies": "dep",
    "migration_events": "mi", "raw_missing": "rwm", "raw_uninterpretable": "rwu",
}


class ImageError(Exception):
    """Fail-closed: image bytes inconsistent with their own checksums."""


# --------------------------------------------------------------------------
# canonical bytes + hashes
# --------------------------------------------------------------------------

def canonical_json(obj):
    """Deterministic JSON bytes (sorted keys, tight separators, no NaN)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def graph_sha256(g):
    return sha256_hex(canonical_json(g))


def case_name(path, blob_sha):
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(path).stem)
    return "%s__%s" % (stem, (blob_sha or "noshaw")[:8])


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------

def predictor_gate(line, spec):
    """SXT-017 gate evaluation (identical semantics, identical codes)."""
    status, reasons, _cols = predict_line(line, spec)
    return [make_rejection(r["code"], r.get("detail")) for r in reasons]


def compiler_gate(line, spec):
    """Image-emitter gates (stricter than the predictor on purpose)."""
    g = line["g"]
    fxd = g.get("fxd", 0)
    rejections = []
    for s in g.get("fx", []):
        slot, role = s.get("i"), s.get("r")
        if (not isinstance(slot, int) or not 0 <= slot <= 15
                or EXPECTED_ROLE_BY_SLOT.get(slot) != role
                or role_phase(role) is None):
            rejections.append(make_rejection("routing_form_unsupported",
                                             {"slot": slot, "role": role}))
            continue
        enabled = bool(s.get("on")) and (fxd >> slot) & 1 == 0
        if enabled and role in ("send3", "send4"):
            rejections.append(make_rejection(
                "send_levels_not_exported",
                {"slot": slot, "fx_class": s.get("tn"),
                 "gap": "scene send levels for buses 3/4 are not exported by "
                        "SXT-011 (loader defaults apply); the image cannot "
                        "express the complete send routing"}))
    for w in g.get("wta", []):
        if not (w.get("emb") or w.get("res")):
            rejections.append(make_rejection(
                "asset_unresolved",
                {"scene": w.get("sc"), "osc": w.get("osc"),
                 "display_name": w.get("name"),
                 "note": "wavetable record has neither embedded bytes nor a "
                         "resolved file; the engine default-table fallback "
                         "would be a silent substitution"}))
    return rejections


def evaluate(line, spec):
    """All gates; returns (outcome, rejections). Predictor codes first, then
    compiler codes, in stable order. Never raises for a bad graph: bad graphs
    are rejections/unresolved, not exceptions."""
    if line.get("st") != "normalized" or "g" not in line:
        why = line.get("why") or {}
        return OUTCOME_UNRESOLVED, [make_rejection("loader_analysis_failure", why)]
    rejections = predictor_gate(line, spec) + compiler_gate(line, spec)
    codes = [r["code"] for r in rejections]
    return outcome_for(codes), rejections


# --------------------------------------------------------------------------
# image construction
# --------------------------------------------------------------------------

def _account(line, spec):
    """SXT-015 account under the bundle's voice-pool override (predictor rule)."""
    with REG.override("voice_pool_limit", spec["voice_pool_limit"]):
        return account_graph(line, fx_instance_limit=spec["fx_instance_limit"])


def _derived_voice(acc, g):
    voice = acc["voice"]
    scenes = []
    for s_acc in voice["scenes"]:
        si = s_acc["scene"]
        sc = g["sc"][si]
        scenes.append({
            "scene": si,
            "active_in_mode": si in voice["active_scenes"],
            "filter_config_id": sc.get("fbc"), "filter_config_name": sc.get("fbcn"),
            "osc_slots": s_acc["osc_slots"],
            "unison_load_per_voice": s_acc["unison_load_per_voice"],
            "filter_units": s_acc["filter_units"],
            "active_filter_units": s_acc["active_filter_units"],
            "waveshaper_active": s_acc["waveshaper_active"],
            "waveshaper_type": s_acc["waveshaper_type"],
            "mseg_or_formula_lfos": s_acc["mseg_or_formula_lfos"],
            "voice_lfos": s_acc["voice_lfos"], "scene_lfos": s_acc["scene_lfos"],
        })
    return {
        "scene_mode_id": voice["scene_mode_id"], "scene_mode_name": voice["scene_mode_name"],
        "active_scenes": voice["active_scenes"], "voices_per_note": voice["voices_per_note"],
        "polylimit": voice["polylimit"], "worst_case_voices": voice["worst_case_voices"],
        "notes_held_worst_case": voice["notes_held_worst_case"],
        "unison_osc_instances_worst_case": voice["unison_osc_instances_worst_case"],
        "lfo_instances_total": voice["lfo_instances_total"],
        "envelope_instances": voice["envelope_instances"],
        "voice_state_bytes_on_chip": voice["state_bytes_on_chip"],
        "scenes": scenes,
        "note": "activity/unison annotations are the SXT-015 model's conservative "
                "derived view; the patch truth is body.graph",
    }


def _derived_fx_section(acc, g):
    by_slot = {e["slot"]: e for e in acc["fx_instances"]}
    slots = []
    for s in g.get("fx", []):
        slot, role = s["i"], s["r"]
        phase, phase_name, order = role_phase(role)
        base = {
            "slot": slot, "role": role,
            "phase": phase, "phase_name": phase_name,
            "order_in_phase": order, "engine_order": engine_order(role),
            "configured": bool(s.get("on")),
            "type_id": s.get("t"), "type_name": s.get("tn"),
        }
        e = by_slot.get(slot)
        if e is not None:
            base.update({
                "enabled_by_fxd": e["enabled_by_fxd"],
                "routing_active": not e["routing_inactive"],
                "processes_this_frame": e["processes_this_frame"],
                "state_tier": e["tier"], "state_class_unverified":
                    "class_state_unverified" in e["flags"],
                "airwindows_algorithm_selected":
                    (e.get("airwindows_algorithm") is not None
                     and "airwindows_algorithm_not_selected" not in [
                         r["code"] for r in acc["rejections"]]),
            })
        slots.append(base)
    return {
        "section_bypass_id": g.get("fxb"), "section_bypass_name": g.get("fxbn"),
        "disable_mask_fxd": g.get("fxd", 0),
        "enabled_instances": acc["fx_summary"]["enabled_instances"],
        "processing_instances": acc["fx_summary"]["processing_instances"],
        "distinct_type_count": acc["fx_summary"]["distinct_type_count"],
        "processing_order_note": "engine-fixed: A1->A4 inserts, B1->B4 inserts, "
                                 "scene sum, S1..S4 sends (per-slot return level), "
                                 "G1->G4 globals (SurgeSynthesizer::process)",
        "slots": slots,
        "note": "per-slot fxd-disabled instances hold state but neither process "
                "nor gate (SXT-015 rule); two slots of one class are two instances",
    }


def _allocations(acc, spec, wta):
    voice = acc["voice"]
    on_total, blocks_on = 0, [{
        "name": "voice_state", "kind": "voice_state_aggregate",
        "offset": 0, "size_bytes": voice["state_bytes_on_chip"],
    }]
    on_total += voice["state_bytes_on_chip"]
    for e in acc["fx_instances"]:
        if not e["external"]:
            blocks_on.append({
                "name": "fx_slot_%d" % e["slot"], "kind": "fx_instance_state",
                "slot": e["slot"], "fx_class": e["class"],
                "offset": on_total, "size_bytes": e["state_bytes"],
            })
            on_total += e["state_bytes"]
    ext_total, blocks_ext = 0, []
    for e in acc["fx_instances"]:
        if e["external"]:
            blocks_ext.append({
                "name": "fx_slot_%d" % e["slot"], "kind": "fx_instance_state",
                "slot": e["slot"], "fx_class": e["class"],
                "offset": ext_total, "size_bytes": e["state_bytes"],
            })
            ext_total += e["state_bytes"]
    flash_total, blocks_flash = 0, []
    for w in wta:
        emb = w.get("emb") or 0
        if emb > 0:
            blocks_flash.append({
                "name": "wavetable_s%d_o%d" % (w.get("sc"), w.get("osc")),
                "kind": "flash_asset_wavetable", "scene": w.get("sc"),
                "osc": w.get("osc"), "offset": flash_total, "size_bytes": emb,
            })
            flash_total += emb
    mem = acc["memory"]
    if on_total != mem["on_chip_state_bytes"]:
        raise ImageError("allocation on-chip total %d != accounting %d"
                         % (on_total, mem["on_chip_state_bytes"]))
    if ext_total != mem["external_writable_state_bytes"]:
        raise ImageError("allocation external total %d != accounting %d"
                         % (ext_total, mem["external_writable_state_bytes"]))
    if flash_total != acc["assets"]["embedded_flash_bytes"]:
        raise ImageError("allocation flash total %d != accounting %d"
                         % (flash_total, acc["assets"]["embedded_flash_bytes"]))
    fx_entries = []
    for e in acc["fx_instances"]:
        region = "external_writable" if e["external"] else "on_chip"
        base = next(b["offset"] for b in
                    (blocks_ext if e["external"] else blocks_on)
                    if b.get("slot") == e["slot"])
        fx_entries.append({
            "slot": e["slot"], "fx_class": e["class"],
            "enabled_by_fxd": e["enabled_by_fxd"],
            "routing_active": not e["routing_inactive"],
            "processes_this_frame": e["processes_this_frame"],
            "region": region, "offset": base, "size_bytes": e["state_bytes"],
            "ext_reads_per_frame": e["ext_reads_per_frame"],
            "ext_writes_per_frame": e["ext_writes_per_frame"],
            "flags": e["flags"],
        })
    b = acc["budget"]
    return {
        "basis": {
            "accounting_model_version": MODEL_VERSION,
            "params_digest": params_digest(),
            "cost_profile": REG.cost_profile,
            "note": "SXT-015 bookkeeping model; every state/cycle/bandwidth "
                    "number is a named placeholder [PENDING-SXT-016]; voice "
                    "state is one aggregate block until SXT-016/023 pin the "
                    "per-voice layout",
        },
        "budgets": {
            "on_chip_ram_bytes": spec["budgets"]["on_chip_ram_bytes"],
            "external_writable_bytes": spec["budgets"]["external_writable_bytes"],
            "external_bandwidth_bytes_per_s":
                spec["budgets"]["external_bandwidth_bytes_per_s"],
            "cycle_closure": spec["budgets"]["cycle_closure"],
        },
        "voice": {
            "worst_case_voices": voice["worst_case_voices"],
            "voices_per_note": voice["voices_per_note"],
            "polylimit": voice["polylimit"],
            "unison_osc_instances_worst_case":
                voice["unison_osc_instances_worst_case"],
            "lfo_instances_total": voice["lfo_instances_total"],
            "envelope_instances": voice["envelope_instances"],
        },
        "on_chip": {"blocks": blocks_on, "total_bytes": on_total},
        "external_writable": {"blocks": blocks_ext, "total_bytes": ext_total},
        "flash_assets": {"blocks": blocks_flash, "total_bytes": flash_total,
                         "role": "assets only; flash is never writable "
                                 "delay/reverb storage (plan section 3)"},
        "fx_instances": fx_entries,
        "bandwidth": {
            "ext_traffic_bytes_per_frame": mem["ext_traffic_bytes_per_frame"],
            "ext_traffic_bytes_per_s": mem["ext_traffic_bytes_per_s"],
        },
        "cycles_placeholder_v0": {
            "per_frame": b["cost_cycles_per_frame"],
            "dsp_budget_cycles_per_frame": b["dsp_budget_cycles_per_frame"],
            "closure": b["closure"],
            "note": "NOT GATED: placeholder-v0 columns only "
                    "[PENDING-SXT-016]",
        },
    }


def build_body(line, acc, spec):
    g = line["g"]
    scalars = {k: g[k] for k in _GRAPH_SCALAR_KEYS if k in g}
    groups = {}
    for body_key, g_key in _GRAPH_GROUP_KEYS.items():
        if g_key in g:
            groups[body_key] = g[g_key]
    graph = {"scalars": scalars}
    graph.update(groups)
    wta = g.get("wta", [])
    caveats = list(acc["anomalies"])
    derived = {
        "voice_graph": _derived_voice(acc, g),
        "fx_section": _derived_fx_section(acc, g),
        "allocations": _allocations(acc, spec, wta),
        "event_timing": dict(acc["events"]),
        "caveats": caveats,
        "caveats_note": "anomalies are recorded model observations (unison "
                        "clamp, exposure gaps, unverified-class flags); they "
                        "never alter patch content",
        "losslessness": {
            "normalized_graph_sha256": graph_sha256(g),
            "reconstruction_rule": "g = body.graph.scalars + {sc: scenes, fx: "
                                   "fx_slots, md: modulation, wta: "
                                   "wavetable_assets, dep: dependencies, mi: "
                                   "migration_events, rwm: raw_missing, rwu: "
                                   "raw_uninterpretable, raw_note}; "
                                   "sha256(canonical_json(g)) must equal "
                                   "header.normalized_graph_sha256",
        },
    }
    return {"graph": graph, "derived": derived}


def build_header(line, spec, bundle_id, bundle_status, bundle_file_sha256, body_sha):
    pin = line.get("pin", {})
    return {
        "format": IMAGE_FORMAT_VERSION,
        "format_major": IMAGE_FORMAT_MAJOR,
        "format_minor": IMAGE_FORMAT_MINOR,
        "compiler_version": COMPILER_VERSION,
        "body_sha256": body_sha,
        "source": {
            "path": line.get("p"), "bank": line.get("b"),
            "census_blob_sha1": line.get("sha"),
            "size_bytes": line.get("sz"),
        },
        "pin": {"engine_commit": pin.get("e"), "sample_rate_hz": pin.get("sr"),
                "graph_schema_version": pin.get("sv")},
        "normalized_graph_sha256": graph_sha256(line["g"]),
        "profile": {
            "artifact": "profile-v1-DRAFT",
            "bundle_id": bundle_id,
            "bundle_status": bundle_status,
            "bundle_file_sha256": bundle_file_sha256,
            "bundle_spec": spec,
            "claim_scope": "compiled against a DRAFT-NOT-FROZEN bundle; a "
                           "compiled image is not a support, fidelity, or "
                           "preset-quality claim",
        },
    }


def build_container(header, body):
    header_bytes = canonical_json(header)
    body_bytes = canonical_json(body)
    if len(header_bytes) > 0xFFFF:
        raise ImageError("header too large for container: %d" % len(header_bytes))
    if len(body_bytes) > 0xFFFFFFFF:
        raise ImageError("body too large for container")
    payload = (CONTAINER_MAGIC + struct.pack("<BBHI", IMAGE_FORMAT_MAJOR,
                                             IMAGE_FORMAT_MINOR,
                                             len(header_bytes), len(body_bytes))
               + header_bytes + body_bytes)
    return payload + sha256_hex(payload).encode("ascii")


def parse_image(data):
    """Parse + fully checksum-verify a container. Raises ImageError."""
    def fail(msg):
        raise ImageError(msg)
    if len(data) < len(CONTAINER_MAGIC) + 8 + 64:
        fail("image truncated: %d bytes" % len(data))
    if data[:4] != CONTAINER_MAGIC:
        fail("bad magic %r" % data[:4])
    major, minor, hlen, blen = struct.unpack("<BBHI", data[4:12])
    end = 12 + hlen + blen
    if len(data) != end + 64:
        fail("length mismatch: file %d, header+body+digest %d"
             % (len(data), end + 64))
    if sha256_hex(data[:end]) != data[end:].decode("ascii"):
        fail("container checksum mismatch")
    header = json.loads(data[12:12 + hlen].decode("utf-8"))
    body_bytes = data[12 + hlen:end]
    body = json.loads(body_bytes.decode("utf-8"))
    if canonical_json(body) != body_bytes:
        fail("body is not canonical (re-serialization differs)")
    if header.get("body_sha256") != sha256_hex(body_bytes):
        fail("body sha256 mismatch: header %r != actual %s"
             % (header.get("body_sha256"), sha256_hex(body_bytes)))
    if header.get("format") != IMAGE_FORMAT_VERSION:
        fail("format %r != %r" % (header.get("format"), IMAGE_FORMAT_VERSION))
    return {"format_major": major, "format_minor": minor,
            "header": header, "body": body, "body_bytes": body_bytes}


def rebuild_graph(body):
    """Lossless reconstruction of the normalized graph from an image body."""
    graph = body["graph"]
    g = dict(graph["scalars"])
    for body_key, g_key in _GRAPH_GROUP_KEYS.items():
        if body_key in graph:
            g[g_key] = graph[body_key]
    return g


# --------------------------------------------------------------------------
# top-level compile
# --------------------------------------------------------------------------

def compile_line(line, spec, bundle_id, bundle_status, bundle_file_sha256,
                 asset_root=None):
    """One graph line -> ("compiled", image_obj, container_bytes)
    or (outcome, record_obj, None).

    asset_root (SXT-026, optional): external wavetable asset root
    (resources/data of the pinned tree). When provided, every resolved
    wavetable record gains a manifest record under
    derived.wavetable_asset_manifests (identity hash + dims + mip/AA
    structure + residency, hashes only in-repo). Identity mismatches abort
    the compile (compiler/assets/wavetable.py; decision-records/0004)."""
    outcome, rejections = evaluate(line, spec)
    profile = {
        "artifact": "profile-v1-DRAFT", "bundle_id": bundle_id,
        "bundle_status": bundle_status,
        "bundle_file_sha256": bundle_file_sha256,
    }
    if outcome != OUTCOME_COMPILED:
        record = {
            "artifact": RECORD_ARTIFACT,
            "compiler_version": COMPILER_VERSION,
            "source": {"path": line.get("p"), "bank": line.get("b"),
                       "census_blob_sha1": line.get("sha")},
            "profile": dict(profile,
                            claim_scope="a rejection is a structural verdict "
                                        "against the DRAFT bundle, never a "
                                        "fidelity or quality judgment"),
            "outcome": outcome,
            "codes": rejections,
            "note": "No image was emitted. The compiler never trims: every "
                    "unsupported path is a visible, machine-readable "
                    "rejection (issue #13).",
        }
        return outcome, record, None

    acc = _account(line, spec)
    body = build_body(line, acc, spec)
    if asset_root is not None:
        # SXT-026: asset manifests are additive derived data (format 1.1).
        # The manifest reads the .wt payload in place from the external root
        # and aborts on any identity mismatch (never copies it).
        from compiler.assets import wavetable as wt_assets  # noqa: PLC0415

        body["derived"]["wavetable_asset_manifests"] = \
            wt_assets.manifests_for_graph(line["g"], asset_root)
    body_bytes = canonical_json(body)
    header = build_header(line, spec, bundle_id, bundle_status,
                          bundle_file_sha256, sha256_hex(body_bytes))
    container = build_container(header, body)
    parse_image(container)  # self-check: the emitted bytes must verify
    image = {"artifact": "sxt-020-patch-image", "header": header, "body": body}
    return OUTCOME_COMPILED, image, container


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _load_bundle(args):
    raw, bundles = load_bundle_file(Path(args.bundle))
    if args.bundle_id not in bundles:
        raise Refuse("bundle_id %r not in %s" % (args.bundle_id, args.bundle))
    lines, observed, _sha = load_graphs(Path(args.graphs))
    spec = validate_spec(bundles[args.bundle_id], observed)
    bundle_sha = sha256_hex(Path(args.bundle).read_bytes())
    status = next(b["status"] for b in raw["bundles"]
                  if b["bundle_id"] == args.bundle_id)
    return spec, status, bundle_sha


def _write_pair(out_dir, name, outcome, obj, container):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if outcome == OUTCOME_COMPILED:
        bin_path = out_dir / (name + ".image.bin")
        bin_path.write_bytes(container)
        json_path = out_dir / (name + ".image.json")
        json_path.write_text(json.dumps(obj, sort_keys=True, indent=1,
                                        ensure_ascii=True,
                                        allow_nan=False) + "\n",
                             encoding="utf-8")
        return bin_path, json_path
    rec_path = out_dir / (name + ".rejection.json")
    rec_path.write_text(json.dumps(obj, sort_keys=True, indent=1,
                                   ensure_ascii=True, allow_nan=False) + "\n",
                        encoding="utf-8")
    return rec_path, None


def cmd_compile(args):
    spec, status, bundle_sha = _load_bundle(args)
    by_path = None
    if args.path:
        with open(args.graphs, "r", encoding="utf-8") as f:
            for ln in f:
                d = json.loads(ln)
                if d.get("p") == args.path:
                    by_path = d
                    break
        if by_path is None:
            raise Refuse("path %r not found in %s" % (args.path, args.graphs))
        name = case_name(by_path["p"], by_path.get("sha"))
    elif args.entry_json:
        by_path = json.loads(Path(args.entry_json).read_text())
        for k in ("p", "b", "sha", "pin", "g"):
            if k not in by_path:
                raise Refuse("entry JSON %s lacks required key %r"
                             % (args.entry_json, k))
        name = args.name or case_name(by_path["p"], by_path.get("sha"))
    else:
        raise Refuse("compile needs --path or --entry-json")

    outcome, obj, container = compile_line(by_path, spec, args.bundle_id,
                                           status, bundle_sha,
                                           asset_root=args.asset_root)
    written = _write_pair(args.out_dir, name, outcome, obj, container)
    codes = ""
    if outcome != OUTCOME_COMPILED:
        codes = " codes=%s" % ",".join(sorted({r["code"] for r in obj["codes"]}))
    print("outcome=%s%s -> %s" % (outcome, codes,
                                  ", ".join(str(w) for w in written if w)))
    return 0


def cmd_scan(args):
    spec, status, bundle_sha = _load_bundle(args)
    lines, _observed, graphs_sha = load_graphs(Path(args.graphs))
    outcomes, code_counts, per_bank = [], {}, {}
    for bank in ("factory", "contributor"):
        per_bank[bank] = {OUTCOME_COMPILED: 0, OUTCOME_REJECTED: 0,
                          OUTCOME_UNRESOLVED: 0}
    for d in lines:
        outcome, obj, _ = compile_line(d, spec, args.bundle_id, status,
                                       bundle_sha)
        codes = sorted({r["code"] for r in obj["codes"]}) \
            if outcome != OUTCOME_COMPILED else []
        outcomes.append({"path": d["p"], "bank": d["b"], "sha": d["sha"],
                         "outcome": outcome, "codes": codes})
        per_bank[d["b"]][outcome] += 1
        for c in codes:
            code_counts[c] = code_counts.get(c, 0) + 1
    totals = {
        OUTCOME_COMPILED: per_bank["factory"][OUTCOME_COMPILED]
        + per_bank["contributor"][OUTCOME_COMPILED],
        OUTCOME_REJECTED: per_bank["factory"][OUTCOME_REJECTED]
        + per_bank["contributor"][OUTCOME_REJECTED],
        OUTCOME_UNRESOLVED: per_bank["factory"][OUTCOME_UNRESOLVED]
        + per_bank["contributor"][OUTCOME_UNRESOLVED],
    }
    top = sorted(code_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out = {
        "artifact": SCAN_ARTIFACT,
        "tool_version": COMPILER_VERSION,
        "image_format": IMAGE_FORMAT_VERSION,
        "status": "DRAFT-NOT-FROZEN: compiled against the DRAFT bundle; "
                  "outcomes are structural verdicts, not support/fidelity/"
                  "quality claims; allocations are SXT-015 placeholders "
                  "[PENDING-SXT-016]",
        "claim_scope": "compiled = the complete original graph fits the DRAFT "
                       "bundle's gates and is expressible as an image; "
                       "rejected/unresolved = explicit machine-readable codes "
                       "(compiler/rejections.json); NOTHING is ever trimmed",
        "provenance": {
            "graphs_file": getattr(args, "graphs_provenance", args.graphs),
            "graphs_sha256": graphs_sha,
            "graphs_count": len(lines),
            "bundle_file": getattr(args, "bundle_provenance", args.bundle),
            "bundle_file_sha256": bundle_sha,
            "bundle_id": args.bundle_id, "bundle_status": status,
            "accounting_model_version": MODEL_VERSION,
            "rejection_catalog": "compiler/rejections.json",
            "gate_evaluator": "tools/profile_predict.py (SXT-017 semantics, "
                              "reused unmodified for reconciliation)",
        },
        "totals": dict(totals, total=len(lines)),
        "per_bank": per_bank,
        "rejection_code_counts": dict(sorted(code_counts.items())),
        "top_rejection_codes": [{"code": c, "presets": n} for c, n in top],
        "outcomes": outcomes,
    }
    if args.reconcile:
        out["reconciliation"] = reconcile(outcomes, Path(args.reconcile),
                                          graphs_sha)
    blob = json.dumps(out, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(blob, encoding="utf-8")
    print("scan: compiled %d / rejected %d / unresolved %d of %d -> %s"
          % (totals[OUTCOME_COMPILED], totals[OUTCOME_REJECTED],
             totals[OUTCOME_UNRESOLVED], len(lines), args.out))
    if args.reconcile:
        rec = out["reconciliation"]
        print("reconciliation vs %s: %d/%d agree; %d deltas"
              % (Path(args.reconcile).name, rec["agreement_count"],
                 len(lines), len(rec["deltas"])))
        for d in rec["deltas"]:
            print("  DELTA %s: predictor %s -> compiler %s (%s)"
                  % (d["path"], d["predictor_status"], d["compiler_outcome"],
                     ",".join(d["compiler_codes"])))
    return 0


def reconcile(compiler_outcomes, predictions_path, graphs_sha):
    """Per-preset reconciliation against a committed SXT-017 prediction.

    Mapping: supported->compiled, unsupported->rejected,
    adapted-not-predicted->rejected (adaptation codes are compile
    rejections), unresolved->unresolved. The compiler's extra image-emitter
    gates (asset_unresolved, send_levels_not_exported) can only ever reject
    MORE than the predictor; every delta is enumerated with its codes."""
    pred = json.loads(predictions_path.read_text())
    pred_by_path = {e["path"]: e for e in pred["presets"]}
    expected = {"supported": OUTCOME_COMPILED,
                "unsupported": OUTCOME_REJECTED,
                "adapted-not-predicted": OUTCOME_REJECTED,
                "unresolved": OUTCOME_UNRESOLVED}
    deltas, agreement = [], 0
    for entry in compiler_outcomes:
        p = pred_by_path.get(entry["path"])
        if p is None:
            deltas.append({"path": entry["path"], "bank": entry["bank"],
                           "predictor_status": "absent-from-prediction",
                           "compiler_outcome": entry["outcome"],
                           "compiler_codes": entry["codes"],
                           "explanation": "path missing from the prediction "
                                          "artifact (graphs mismatch?)"})
            continue
        want = expected[p["status"]]
        if want == entry["outcome"]:
            agreement += 1
            continue
        deltas.append({
            "path": entry["path"], "bank": entry["bank"],
            "predictor_status": p["status"],
            "compiler_outcome": entry["outcome"],
            "compiler_codes": entry["codes"],
            "explanation": "compiler-only gate(s) %s fired: the image emitter "
                           "is stricter than the predictor by design"
                           % ",".join(entry["codes"]),
        })
    graphs_match = pred.get("provenance", {}).get("graphs_sha256") == graphs_sha
    return {
        "prediction_artifact": str(predictions_path),
        "prediction_tool_version": pred.get("tool_version"),
        "prediction_bundle_id": pred.get("bundle_id"),
        "graphs_sha256_match": graphs_match,
        "mapping_rule": {"supported": "compiled",
                         "unsupported": "rejected",
                         "adapted-not-predicted": "rejected (adaptation codes "
                                                  "are compile rejections; "
                                                  "the compiler compiles only "
                                                  "original graphs)",
                         "unresolved": "unresolved"},
        "predictor_totals": pred["totals"],
        "compiler_totals": None,  # filled by caller below
        "agreement_count": agreement,
        "deltas": deltas,
        "delta_note": "the compiler never rejects LESS than the predictor "
                      "(its gate set is a superset); a delta can only be "
                      "compiler-stricter, each one named above",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--graphs", default="corpus/normalized/graphs.jsonl")
        p.add_argument("--bundle", default="contracts/profile-v1-bundle-DRAFT.json")
        p.add_argument("--bundle-id", default="B4-broad")

    c = sub.add_parser("compile", help="compile one entry to an image/rejection")
    common(c)
    c.add_argument("--path", help="census path of a graphs.jsonl entry")
    c.add_argument("--entry-json", help="full line JSON file (synthetic inputs)")
    c.add_argument("--name", help="output case name (entry-json mode)")
    c.add_argument("--asset-root", default=None,
                   help="SXT-026: external wavetable asset root "
                        "(pinned tree resources/data); embeds "
                        "derived.wavetable_asset_manifests into the image "
                        "and aborts on asset identity mismatch")
    c.add_argument("--out-dir", required=True)
    c.set_defaults(func=cmd_compile)

    s = sub.add_parser("scan", help="compile all graphs; write the scan JSON")
    common(s)
    s.add_argument("--out", required=True)
    s.add_argument("--reconcile", help="committed SXT-017 prediction JSON")
    s.set_defaults(func=cmd_scan)

    args = ap.parse_args(argv)
    graphs = Path(args.graphs)
    if not graphs.is_absolute():
        args.graphs = str(REPO / graphs)
    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        args.bundle = str(REPO / bundle)

    def _rel(p):
        # Provenance must be repo-relative: absolute host paths make the
        # artifact byte-vary across checkouts and fail CI regeneration.
        rp = Path(p).resolve()
        try:
            return str(rp.relative_to(REPO))
        except ValueError:
            return rp.name

    args.graphs_provenance = _rel(args.graphs)
    args.bundle_provenance = _rel(args.bundle)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    except ImageError as e:
        print("IMAGE ERROR: %s" % e, file=sys.stderr)
        sys.exit(3)
    except AssetIdentityError as e:
        print("ABORT: %s" % e, file=sys.stderr)
        sys.exit(2)
