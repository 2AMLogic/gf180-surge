#!/usr/bin/env python3
"""#382 (follow-up of #310 / F-028f-3): one-factor voice-path diagnostic for the
Novuo Reverb 2 carrier on the ALL-OFF dry bus.

CLAIM SCOPE.  Reference-vs-reference repeatability of the pinned engine under
the recorded environment only.  A stable dry variant identifies a CONTRIBUTING
factor for the tested sequences; it is not a determinism claim, not a unique
engine root cause, not original-preset support, and not a model or RTL claim.
Variants are diagnostic/adapted input only (decision record 0019 invariant 4):
nothing here promotes a variant to a fixture or to original-preset coverage,
widens the 3x gate, or applies a seed/drift control (options B/C are routed to
the owner / SXT-017, not applied).  The original wet reference is never
overwritten.

STRUCTURE.  Everything that decides a status (variant matrix, isolation,
read-back accounting, controls, classification) is pure Python with no oracle
dependency, so it is unit-testable.  Oracle work (``render-shard``) imports the
pinned engine lazily and refuses (BLOCKED) when it is unavailable.  This tool
never launches render grids itself: ``render-shard`` renders exactly one
(variant, sequence) shard in one process; fan-out is the authorized batch
route's job, and ``assemble`` classifies the returned shard files.

Subcommands:
  plan          write the frozen manifest (variants, reps, job ids, outputs)
  probe         check oracle availability; exit 3 + BLOCKED record if absent
  render-shard  ORACLE HOST ONLY: one shard (variant x sequence | control)
  assemble      classify shard files into the transcript (never PASS on gaps)

Original tool, Apache-2.0.  No Surge source, tables or presets are copied;
the engine stays external and is reached only through its Python binding.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ISSUE = 382
SR = 48000
BLOCK = 32
FX_SLOTS = 16
REPS = 20          # per bus, frozen (matches the SXT-028f baseline)
GATE_REPS = 3      # the 3x gate, recorded separately from the stress run

CARRIER_SLUG = "novuo"
CARRIER = "resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp"
CONTROL_SLUG = "lapharp"
CONTROL = "resources/data/patches_3rdparty/Luna/MPE/Lap Harp.fxp"
PERTURBER = "resources/data/patches_3rdparty/A.Liv/Keys/Grant Me....fxp"
SEQUENCES = ["seq-notes-coverage-v1", "seq-poly-8-v1"]
POSITIVE_CONTROLS = ["fmcombo", "fmtwang2", "alienappears"]
POSITIVE_CONTROL_SEQ = "seq-poly-8-v1"

DEFAULT_OUT = os.path.join(REPO, "reports", "sxt-012", "diagnostics", "novuo")

STATUSES = ("PASS", "FAIL", "NOT_RUN", "BLOCKED", "NO_VERDICT", "STALE")

# Candidate factors.  `kind` selects how the parameter is resolved from the
# loaded patch dict; resolution against the real binding is itself part of
# the recorded read-back (an unresolvable one is `not_exposed`, a limit, not
# a silent skip).  Names are declared here and verified by the live run only
# (NOT_RUN until then).
SCENES = (0, 1)
OSCS = (0, 1, 2)


def _factors():
    out = []
    for sc in SCENES:
        for o in OSCS:
            out.append({"id": f"osc_type_s{sc}_o{o}", "kind": "osc_type",
                        "scene": sc, "osc": o, "target": "ot_sine",
                        "note": "oscillator REPLACEMENT; the loader may reset "
                                "the oscillator's dependent params, which is "
                                "recorded, so the cause is not isolated to a "
                                "scalar"})
        for o in OSCS:
            out.append({"id": f"unison_voices_s{sc}_o{o}", "kind": "unison",
                        "scene": sc, "osc": o, "target": 1})
        out.append({"id": f"noise_level_s{sc}", "kind": "noise_level",
                    "scene": sc, "target": 0.0})
        out.append({"id": f"noise_colour_s{sc}", "kind": "noise_colour",
                    "scene": sc, "target": 0.0,
                    "note": "colour has no effect if level is nonzero-free; "
                            "recorded as tried"})
    out.append({"id": "drift_all_osc", "kind": "drift", "target": 0.0,
                "note": "normalized read-back first, then set to 0 on every "
                        "oscillator (a single named native factor)"})
    for sc in SCENES:
        out.append({"id": f"lfo_random_s{sc}", "kind": "lfo_random",
                    "scene": sc, "target": "ls_sine",
                    "note": "every LFO of the scene whose shape is a random "
                            "or S&H source is replaced by a sine shape"})
    return out


FACTORS = _factors()


class Blocked(Exception):
    """Oracle or batch route unavailable (status BLOCKED)."""


# --------------------------------------------------------------------------
# Pure logic: matrix, isolation, classification.
# --------------------------------------------------------------------------

def build_variants(factors=None):
    """Original plus exactly one variant per factor.

    Every variant is defined relative to the fresh native-loaded ORIGINAL and
    carries exactly one declared factor; nothing accumulates.
    """
    factors = FACTORS if factors is None else factors
    variants = [{"id": "original", "start_from": "original", "factors": []}]
    for f in factors:
        variants.append({"id": f["id"], "start_from": "original",
                         "factors": [f]})
    return variants


def validate_matrix(variants):
    """Return a list of isolation violations (empty == isolated)."""
    bad = []
    ids = [v["id"] for v in variants]
    if len(set(ids)) != len(ids):
        bad.append("duplicate variant ids")
    if not variants or variants[0]["id"] != "original" or variants[0]["factors"]:
        bad.append("first variant must be the unmodified original")
    for v in variants:
        if v.get("start_from") != "original":
            bad.append(f"{v['id']}: does not start from the original")
        if v["id"] != "original" and len(v["factors"]) != 1:
            bad.append(f"{v['id']}: {len(v['factors'])} factors (need exactly 1)")
    return bad


def plan(variants=None, reps=REPS, out_dir=None):
    variants = build_variants() if variants is None else variants
    bad = validate_matrix(variants)
    if bad:
        raise ValueError("; ".join(bad))
    out_dir = out_dir or os.path.relpath(DEFAULT_OUT, REPO)
    shards = []
    for v in variants:
        for seq in SEQUENCES:
            shards.append({"job_id": f"{CARRIER_SLUG}:{v['id']}:{seq}",
                           "kind": "variant", "variant": v["id"],
                           "sequence": seq,
                           "output": f"{out_dir}/shards/{v['id']}__{seq}.json"})
    for seq in SEQUENCES:
        shards.append({"job_id": f"{CONTROL_SLUG}:original:{seq}",
                       "kind": "flake_control", "variant": "original",
                       "sequence": seq,
                       "output": f"{out_dir}/shards/{CONTROL_SLUG}__{seq}.json"})
    shards.append({"job_id": "positive-controls", "kind": "positive_control",
                   "output": f"{out_dir}/shards/positive-controls.json"})
    return {"schema_version": 1, "issue": ISSUE, "carrier": CARRIER,
            "carrier_slug": CARRIER_SLUG, "control": CONTROL,
            "sequences": SEQUENCES, "reps_per_bus": reps,
            "gate_reps": GATE_REPS, "sample_rate": SR, "block_size": BLOCK,
            "perturbing_preset": PERTURBER, "variants": variants,
            "shards": shards,
            "interleaved_control": "lapharp is stress-rendered in the same "
                                   "process/shard family as the carrier",
            "status": "NOT_RUN"}


def bus_summary(hashes):
    counts = {}
    for h in hashes:
        counts[h] = counts.get(h, 0) + 1
    return {"repeats": len(hashes), "distinct_buffers": len(counts),
            "buffer_counts": dict(sorted(counts.items()))}


def bus_stable(obs):
    """A bus is stable only if it has observations and exactly one buffer."""
    return bool(obs) and obs.get("repeats", 0) > 0 \
        and obs.get("distinct_buffers") == 1


def stress_stable(row):
    return bus_stable(row.get("dry")) and bus_stable(row.get("wet"))


def classify_control(rows, classify=stress_stable):
    """The Lap Harp control must NOT be called stable on any sequence.

    ``classify`` is injectable so a deliberately broken always-stable
    classifier can be shown to fail this control.
    """
    if not rows:
        return {"status": "NO_VERDICT", "reason": "no Lap Harp observations"}
    stable = [r["sequence"] for r in rows if classify(r)]
    if stable:
        return {"status": "FAIL",
                "reason": f"Lap Harp classified stable on {stable}"}
    return {"status": "PASS",
            "reason": "Lap Harp not reported stable on any tested sequence"}


def classify_positive_controls(rows):
    want = set(POSITIVE_CONTROLS)
    got = {r.get("slug") for r in rows or []}
    if want - got:
        return {"status": "NO_VERDICT",
                "reason": f"missing re-derivations: {sorted(want - got)}"}
    badrows = [r["slug"] for r in rows
               if r.get("gate_3x") != "PASS" or r.get("byte_identical") is not True]
    if badrows:
        return {"status": "NO_VERDICT",
                "reason": f"positive-control re-derivation failed: {badrows}"}
    return {"status": "PASS", "reason": "all three wet sha256 re-derived"}


def isolation_audit(readback):
    """From a variant's read-back, report the isolation facts.

    readback = {"declared": {param: {"before":..,"after":..}},
                "candidates_before": {...}, "candidates_after": {...}}
    Returns {"effective", "not_exposed", "loader_dependent_changes"}.
    """
    declared = readback.get("declared", {})
    if not declared:
        return {"effective": False, "not_exposed": True,
                "loader_dependent_changes": []}
    eff = any(d.get("after") != d.get("before") for d in declared.values())
    before = readback.get("candidates_before", {})
    after = readback.get("candidates_after", {})
    dep = sorted(k for k in before
                 if k not in declared and after.get(k) != before.get(k))
    return {"effective": eff, "not_exposed": False,
            "loader_dependent_changes": dep}


def evaluate(shards, matrix_variants=None):
    """Classify a complete set of shard results into the transcript verdict.

    shards: {"positive_control": [...rows], "variants": {vid: {seq: {...}}},
             "flake_control": {seq: {...}}}
    where each variant/seq entry is {"gate_3x": {...}, "dry": bus_summary,
    "wet": bus_summary, "readback": {...}, "status": optional}.
    Never returns PASS on a missing observation.
    """
    variants = matrix_variants or build_variants()
    pc = classify_positive_controls(shards.get("positive_control"))
    out = {"positive_control": pc, "factors": [], "limits": []}

    if pc["status"] != "PASS":
        out.update(status="NO_VERDICT", conclusion=None,
                   reason="positive-control: " + pc["reason"])
        return out

    fl_rows = []
    for seq in SEQUENCES:
        e = (shards.get("flake_control") or {}).get(seq)
        if e:
            fl_rows.append({"sequence": seq, "dry": e.get("dry"),
                            "wet": e.get("wet")})
    ctl = classify_control(fl_rows)
    out["lap_harp_control"] = ctl
    if ctl["status"] != "PASS":
        out.update(status="NO_VERDICT", conclusion=None,
                   reason="Lap Harp control: " + ctl["reason"])
        return out

    vres = shards.get("variants") or {}
    orig = vres.get("original", {})
    missing = [f"original:{s}" for s in SEQUENCES if s not in orig]
    if missing:
        out.update(status="NO_VERDICT", conclusion=None,
                   reason=f"missing original observations: {missing}")
        return out
    stable_orig = [s for s in SEQUENCES if bus_stable(orig[s].get("dry"))]
    if stable_orig:
        out.update(status="NO_VERDICT", conclusion=None,
                   reason="original ALL-OFF dry bus stable on "
                          f"{stable_orig}: environment does not reproduce "
                          "F-028f-3")
        return out

    tried, identified, incomplete = [], [], []
    for v in variants[1:]:
        fid = v["id"]
        per = vres.get(fid, {})
        row = {"factor": fid, "sequences": {}}
        complete = all(s in per for s in SEQUENCES)
        for s in SEQUENCES:
            e = per.get(s)
            if not e:
                row["sequences"][s] = {"status": "NOT_RUN"}
                continue
            iso = isolation_audit(e.get("readback", {}))
            row["sequences"][s] = {
                "status": e.get("status", "OBSERVED"),
                "distinct_dry_buffers":
                    (e.get("dry") or {}).get("distinct_buffers"),
                "distinct_wet_buffers":
                    (e.get("wet") or {}).get("distinct_buffers"),
                "dry_stable": bus_stable(e.get("dry")),
                "isolation": iso}
        if not complete:
            incomplete.append(fid)
            row["verdict"] = "NOT_RUN"
        else:
            ok = all(row["sequences"][s]["dry_stable"]
                     and row["sequences"][s]["isolation"]["effective"]
                     and not row["sequences"][s]["isolation"]["not_exposed"]
                     for s in SEQUENCES)
            row["verdict"] = "REPEATABLE_DRY" if ok else "STILL_UNSTABLE_OR_INEFFECTIVE"
            if ok:
                identified.append(fid)
            if any(row["sequences"][s]["isolation"]["loader_dependent_changes"]
                   for s in SEQUENCES):
                out["limits"].append(
                    f"{fid}: loader-dependent parameter changes recorded; "
                    "cause not isolated to a scalar")
        tried.append(fid)
        out["factors"].append(row)

    out["factors_tried"] = tried
    out["incomplete_factors"] = incomplete
    if incomplete:
        out.update(status="NO_VERDICT", conclusion=None,
                   reason=f"partial results; no observation for {incomplete}")
        return out
    if identified:
        out.update(status="PASS", contributing_factors=identified,
                   reason="removal of the named factor alone makes the dry "
                          "bus repeatable under the recorded environment on "
                          "the tested sequences",
                   conclusion="repeatable under the recorded environment "
                              "(not a determinism claim): " + ", ".join(identified))
    else:
        out.update(status="NO_VERDICT", conclusion=None,
                   reason="no single factor makes the dry bus repeatable; "
                          "factors tried: " + ", ".join(tried))
    return out


# --------------------------------------------------------------------------
# Oracle-facing helpers (lazy imports; used only on the oracle host).
# --------------------------------------------------------------------------

def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def repo_commit():
    try:
        return subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def provenance():
    with open(os.path.join(REPO, "oracle", "manifest.json"),
              encoding="utf-8") as f:
        m = json.load(f)
    return {"engine_commit": m["engine"]["commit"],
            "submodules": m.get("submodules"),
            "runtime": m.get("runtime"),
            "environment": m.get("environment"),
            "harness_script": "tools/diagnose_carrier_variation.py",
            "harness_script_sha256": sha256_file(os.path.abspath(__file__)),
            "repo_commit": repo_commit(),
            "sample_rate": SR, "block_size": BLOCK}


def probe_oracle():
    """Return (ok, error).  Does not render anything."""
    sys.path.insert(0, os.path.join(REPO, "oracle"))
    try:
        import oracle_common as oc
        eng = oc.engine_dir()
        if not os.path.isdir(eng):
            return False, f"engine checkout not found: {eng}"
        oc.import_surgepy()
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    return True, None


def _resolve(patch, f):
    """Return {name: param-handle} for the factor's parameters (may be empty)."""
    handles = {}
    kind = f["kind"]
    try:
        if kind in ("osc_type", "unison"):
            osc = patch["scene"][f["scene"]]["osc"][f["osc"]]
            if kind == "osc_type":
                handles[f"s{f['scene']}.o{f['osc']}.type"] = osc["type"]
            else:
                # canonical name is the p-slot, so the watch list cannot alias it
                handles[f"s{f['scene']}.o{f['osc']}.p7"] = osc["p"][7]
        elif kind == "noise_level":
            handles[f"s{f['scene']}.level_noise"] = \
                patch["scene"][f["scene"]]["level_noise"]
        elif kind == "noise_colour":
            handles[f"s{f['scene']}.noise_colour"] = \
                patch["scene"][f["scene"]]["noise_colour"]
        elif kind == "drift":
            for sc in SCENES:
                for o in OSCS:
                    handles[f"s{sc}.o{o}.drift"] = \
                        patch["scene"][sc]["osc"][o]["drift"]
        elif kind == "lfo_random":
            for i, lfo in enumerate(patch["scene"][f["scene"]]["lfo"]):
                handles[f"s{f['scene']}.lfo{i}.shape"] = lfo["shape"]
    except (KeyError, IndexError, TypeError):
        return {}
    return handles


def _target_value(surgepy_constants, f):
    t = f["target"]
    if isinstance(t, str):
        return float(getattr(surgepy_constants, t))
    return float(t)


def read_candidates(s):
    """Normalized native read-back of every candidate factor."""
    patch = s.getPatch()
    out = {}
    for f in FACTORS:
        for name, h in _resolve(patch, f).items():
            out[name] = _read(s, h)
    # dependents watched so loader-induced side effects are visible: every
    # generic oscillator parameter slot of every oscillator
    for sc in SCENES:
        for o in OSCS:
            try:
                ps = patch["scene"][sc]["osc"][o]["p"]
            except (KeyError, IndexError, TypeError):
                continue
            for i, h in enumerate(ps):
                out.setdefault(f"s{sc}.o{o}.p{i}", _read(s, h))
    return out


def _read(s, h):
    try:
        return float(s.getParamVal(h))
    except Exception as e:  # noqa: BLE001
        return f"unreadable: {type(e).__name__}: {e}"


def apply_factor(s, constants, f):
    """Apply ONE factor to a fresh instance; return the read-back record."""
    before = read_candidates(s)
    if f is None:
        return {"declared": {}, "candidates_before": before,
                "candidates_after": before, "applied": False}
    patch = s.getPatch()
    handles = _resolve(patch, f)
    declared = {}
    if not handles:
        return {"declared": {}, "candidates_before": before,
                "candidates_after": before, "applied": False,
                "limit": "parameter not exposed by the binding"}
    tv = _target_value(constants, f)
    for name, h in handles.items():
        declared[name] = {"before": before.get(name)}
        if f["kind"] == "lfo_random":
            # only LFOs whose shape is a random/S&H source are touched
            rnd = {float(getattr(constants, n)) for n in
                   ("ls_noise", "ls_snh") if hasattr(constants, n)}
            if before.get(name) not in rnd:
                declared[name]["after"] = before.get(name)
                declared[name]["skipped"] = "not a random source"
                continue
        s.setParamVal(h, tv)
    after = read_candidates(s)
    for name in declared:
        declared[name].setdefault("after", after.get(name))
    return {"declared": declared, "candidates_before": before,
            "candidates_after": after, "applied": True}


def _render_once(surgepy, rfx, preset_abs, seq, fx_off, factor):
    import numpy as np
    import surgepy.constants as C

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
        rb = apply_factor(s, C, factor)
        if fx_off:
            for i in range(FX_SLOTS):
                s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
        bs = int(s.getBlockSize())
        sbuf = s.createMultiBlock(int(seq.get("settle_s", 0.25) * SR) // bs)
        s.processMultiBlock(sbuf)
        if fx_off:
            types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                     for i in range(FX_SLOTS)]
            if any(t != C.fxt_off for t in types):
                raise rfx.Refuse(f"dry bus: FX types not Off: {types}")
        events = seq["events"]
        notes = [e for e in events if e["type"] in ("note_on", "note_off")]
        last_t = max(e["t"] for e in notes) if notes else 0
        total_blocks = -(-(last_t + int(float(seq.get("tail_s", 2.5)) * SR)) // bs)
        buf = s.createMultiBlock(total_blocks)
        quant = lambda t: -(-t // bs)  # noqa: E731
        done = b = 0
        while b < total_blocks:
            nxt = rfx.rf.dispatch(s, events[done:], b, quant) + done
            if nxt < len(events) and quant(events[nxt]["t"]) <= b:
                raise rfx.Refuse("scheduler failed to advance")
            seg = (total_blocks if nxt >= len(events)
                   else max(quant(events[nxt]["t"]), b + 1))
            s.processMultiBlock(buf, b, seg - b)
            b, done = seg, nxt
        return rfx.sha256_buf(np.asarray(buf, dtype=np.float32)), rb
    finally:
        del s


def render_shard(shard, plan_doc, out_path):
    """ORACLE HOST: render one shard. Raises Blocked when unavailable."""
    ok, err = probe_oracle()
    if not ok:
        raise Blocked(err)
    sys.path.insert(0, os.path.join(REPO, "oracle"))
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import oracle_common as oc
    oc.reexec_under_pinned_python(REPO)
    import render_fx_fixtures as rfx
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    reps = plan_doc["reps_per_bus"]
    rec = {"job_id": shard["job_id"], "kind": shard["kind"],
           "provenance": provenance()}
    if shard["kind"] == "positive_control":
        import render_reverb2_fixtures as rr2
        rec["rows"] = rr2.positive_control(surgepy)
    else:
        seq, _p, seq_sha = rfx.rf.load_sequence(shard["sequence"])
        path = CARRIER if shard["kind"] == "variant" else CONTROL
        abs_path = os.path.join(oc.engine_dir(), path)
        perturb = os.path.join(oc.engine_dir(), PERTURBER)
        var = next(v for v in plan_doc["variants"] if v["id"] == shard["variant"])
        factor = var["factors"][0] if var["factors"] else None
        rec.update(sequence=shard["sequence"], sequence_sha256=seq_sha,
                   preset=path, variant=shard["variant"])
        # 3x gate (separate from the stress observations), per bus
        gate = {}
        readback = None
        for bus, off in (("wet", False), ("dry", True)):
            hs = []
            for _ in range(GATE_REPS):
                h, readback = _render_once(surgepy, rfx, abs_path, seq, off, factor)
                hs.append(h)
            gate[bus] = {"hashes": hs, "bit_identical": len(set(hs)) == 1}
        rec["gate_3x"] = gate
        # interleaved stress: perturber render precedes every repeat
        for bus, off in (("wet", False), ("dry", True)):
            hs = []
            for _ in range(reps):
                try:
                    _render_once(surgepy, rfx, perturb, seq, False, None)
                except rfx.Refuse:
                    pass
                h, readback = _render_once(surgepy, rfx, abs_path, seq, off, factor)
                hs.append(h)
            rec[bus] = bus_summary(hs)
            rec[bus]["hashes_in_order"] = hs
        rec["readback"] = readback
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, sort_keys=True)
        f.write("\n")
    return rec


def load_shards(plan_doc, base=REPO):
    """Read shard files named by the plan; absent files stay absent."""
    res = {"positive_control": None, "variants": {}, "flake_control": {}}
    for sh in plan_doc["shards"]:
        p = os.path.join(base, sh["output"])
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        if sh["kind"] == "positive_control":
            res["positive_control"] = r.get("rows")
        elif sh["kind"] == "flake_control":
            res["flake_control"][sh["sequence"]] = r
        else:
            res["variants"].setdefault(sh["variant"], {})[sh["sequence"]] = r
    return res


def assemble(plan_doc, base=REPO, probe=None):
    """Transcript from shard files.  Oracle unavailable AND no shards ->
    BLOCKED with the actual error (never PASS, never a local fallback)."""
    shards = load_shards(plan_doc, base)
    have_any = shards["positive_control"] or shards["variants"] \
        or shards["flake_control"]
    if not have_any:
        ok, err = (probe or probe_oracle)()
        res = {"status": "BLOCKED" if not ok else "NOT_RUN",
               "conclusion": None,
               "reason": (f"oracle/batch route unavailable: {err}" if not ok
                          else "no shard results returned yet"),
               "positive_control": {"status": "NOT_RUN"}, "factors": [],
               "limits": []}
    else:
        res = evaluate(shards, plan_doc["variants"])
    res["plan_ref"] = {"issue": ISSUE, "reps_per_bus": plan_doc["reps_per_bus"],
                       "sequences": plan_doc["sequences"]}
    res["claim_scope"] = ("reference-vs-reference repeatability under the "
                          "recorded environment; not a determinism claim, not "
                          "original-preset support; variants are adapted "
                          "diagnostic input only")
    assert res["status"] in STATUSES
    return res


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("plan", "probe", "assemble", "render-shard"):
        p = sub.add_parser(n)
        p.add_argument("--out-dir", default=DEFAULT_OUT)
        if n == "render-shard":
            p.add_argument("--job-id", required=True)
    a = ap.parse_args(argv)
    plan_path = os.path.join(a.out_dir, "plan.json")
    if a.cmd == "plan":
        _write(plan_path, plan(out_dir=os.path.relpath(a.out_dir, REPO)))
        print(f"wrote {plan_path}")
        return 0
    if a.cmd == "probe":
        ok, err = probe_oracle()
        print("oracle available" if ok else f"BLOCKED: {err}")
        return 0 if ok else 3
    with open(plan_path, encoding="utf-8") as f:
        pd = json.load(f)
    if a.cmd == "render-shard":
        sh = next(s for s in pd["shards"] if s["job_id"] == a.job_id)
        try:
            render_shard(sh, pd, os.path.join(REPO, sh["output"]))
        except Blocked as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            return 3
        return 0
    res = assemble(pd, base=REPO)
    res["provenance"] = provenance()
    _write(os.path.join(a.out_dir, "transcript.json"), res)
    print(f"{res['status']}: {res.get('reason')}")
    return 0 if res["status"] == "PASS" else (3 if res["status"] == "BLOCKED" else 1)


if __name__ == "__main__":
    sys.exit(main())
