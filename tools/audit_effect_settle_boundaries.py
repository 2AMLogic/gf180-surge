#!/usr/bin/env python3
"""#318: audit every `model/effects/run_*_model.py` for the settle boundary.

The SXT-012 fixture render runs a 0.25 s silent settle (375 blocks of 32 at
48 kHz) before the first scheduled event and discards it. A model runner
that reads the fixture's dry (or per-slot bypass) bus must decide whether
that settle also belongs to the EFFECT -- i.e. whether to run N blocks of
silence through the model before the fixture audio. #136 measured, for the
Distortion SSE leaf, that the engine's effect does NOT evolve during a silent
settle and that pre-rolling silence through the model costs 73 dB on the
harness anchor (`reports/SXT-028e-sse/artifacts/settle-boundary.json`).

This tool asks the same question of every runner, with the same three legs
as `tools/probe_distortion_sse_settle_boundary.py` (reused here as method,
through small per-runner adapters; that probe and its committed record are
left untouched):

  A. settle-length invariance  -- engine wet bus, 375-block vs 3750-block
     settle. ORACLE-GATED.
  B. construction invariance   -- engine wet bus of the carrier as rendered
     vs saved to `.fxp` and re-loaded into a fresh instance through the
     ordinary `loadPatch` path. ORACLE-GATED.
  C. the model boundary        -- the leaf's frozen model run with each
     candidate silent pre-roll (0, the runner's production value, the
     fixture's own settle), each graded by the LEAF'S OWN declared comparator
     against the COMMITTED engine wet bus. Needs no oracle: the committed
     fixture buses are the engine side.

Fail-closed rules (inherited from the probe, never relaxed here):

  * the boundary is RESOLVED only when A and B are both measured and both
    byte-identical; then the engine's effect provably starts the first audio
    block in its init() state and the declared pre-roll is 0;
  * if A or B is measured and NOT byte-identical the boundary is UNRESOLVED
    (row status NO_VERDICT) -- no pre-roll is chosen by which one scores
    better, ever;
  * if A/B could not be measured the row is BLOCKED on the named dependency
    (or NOT_RUN with its reason), never assumed correct;
  * C is recorded, not tuned. Its comparator verdicts are data for the
    boundary question, not an answer to it.

A/B output invariance establishes the tested OUTPUT behaviour only; it does
not prove that every internal state variable of the effect stayed unchanged.

Production runner defaults are never edited: the adapters run each runner in
a fresh subprocess and override its pre-roll constant in memory only
(`_leg` subcommand). The production leg must reproduce the committed model
render byte-for-byte, which is also the adapter's own self-check.

Original tool, Apache-2.0. Drives the GPL engine (live A/B only) through
`surgepy`; imports no engine source.
"""

import argparse
import ast
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
EFFECTS = os.path.join(REPO, "model", "effects")
for _p in (os.path.join(REPO, "oracle"), TOOLS, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SCHEMA_VERSION = 1
SR = 48000
BLOCK = 32
LONG_SETTLE_S = 2.5            # 10x the declared 0.25 s, as in the probe
ENGINE_PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"
DEFAULT_OUT = os.path.join(REPO, "reports", "effect-settle-boundary-audit")
STATUSES = ("PASS", "FAIL", "NOT_RUN", "BLOCKED", "NO_VERDICT", "STALE")
METRIC_KEYS = ("max_abs_diff_lsb", "rms_diff_dbfs", "spectral_corr",
               "best_shift", "frames")
ORACLE_DEPENDENCY = ("pinned oracle (surgepy built from surge-synthesizer/"
                     "surge@" + ENGINE_PIN + ") unavailable on this host")


class AuditRefused(RuntimeError):
    """A malformed input the audit will not grade (fail-closed)."""


# --------------------------------------------------------------------------
# Declared inventory. Every run_*_model.py must appear here; an unlisted
# runner makes `inventory()` refuse rather than silently skip it.
# --------------------------------------------------------------------------

def _seqs(slugs, seqs=("seq-notes-coverage-v1", "seq-poly-8-v1")):
    return [(s, q) for s in slugs for q in seqs]


RUNNERS = {
    "run_fx_model.py": {
        "leaves": ["SXT-023 (fx:Delay)", "SXT-023 (fx:EQ)"],
        "report": "reports/sxt-023",
        "preroll_source": {"kind": "module_constant",
                           "name": "SETTLE_BLOCKS"},
        "comparator": "tools/compare_fx_reference.py",
        "baseline": "artifacts/audio-{slug}.json",
        "baseline_model": "artifacts/model__{slug}__{seq}.f32.wav",
        "input_bus": "all-off dry bus (sidecar 'dry')",
        "carriers": [
            {"slug": "dexie", "seq": "seq-notes-coverage-v1",
             "leaf": "SXT-023 (fx:Delay)",
             "chain": "ains: delay(0)"},
            {"slug": "metallic", "seq": "seq-notes-coverage-v1",
             "leaf": "SXT-023 (fx:Delay)",
             "chain": "ains: delay(0); sends: delay(4)"},
            {"slug": "fm_bass_1", "seq": "seq-notes-coverage-v1",
             "leaf": "SXT-023 (fx:EQ)",
             "chain": "ains: eq(0)"},
        ],
        "unreachable": [],
    },
    "run_chorus_model.py": {
        "leaves": ["SXT-028c (fx:Chorus)"],
        "report": "reports/SXT-028c",
        "preroll_source": {"kind": "module_constant",
                           "name": "SETTLE_BLOCKS"},
        "comparator": "tools/compare_chorus_reference.py",
        "baseline": "artifacts/compare-{slug}__{seq}.json",
        "baseline_model": "artifacts/model__{slug}__{seq}.f32.wav",
        "input_bus": "all-off dry bus (sidecar 'dry')",
        "carriers": (
            [{"slug": s, "seq": q, "leaf": "SXT-028c (fx:Chorus)",
              "chain": "globals: reverb1(6), chorus(7)"}
             for s, q in _seqs(["alienappears"])]
            + [{"slug": s, "seq": q, "leaf": "SXT-028c (fx:Chorus)",
                "chain": "ains: eq(0), chorus(1)"}
               for s, q in _seqs(["fmcombo"])]
            + [{"slug": s, "seq": q, "leaf": "SXT-028c (fx:Chorus)",
                "chain": "ains: chorus(0)"}
               for s, q in _seqs(["fmtwang2"])]),
        "unreachable": [
            {"slug": "melon", "leaf": "SXT-028c (fx:Chorus)",
             "reason": "no committed fixture: the pinned-engine render was "
                       "REFUSED by its 3x determinism gate "
                       "(reports/SXT-028c/artifacts/render-refusals.txt)"},
        ],
    },
    "run_phaser_model.py": {
        "leaves": ["SXT-028g (fx:Phaser)"],
        "report": "reports/SXT-028g",
        "preroll_source": {"kind": "imported_constant",
                           "name": "SETTLE_BLOCKS",
                           "from": "run_chorus_model.py"},
        "comparator": "tools/compare_phaser_reference.py",
        "baseline": None,
        "baseline_model": None,
        "input_bus": "all-off dry bus (sidecar 'dry')",
        "carriers": [],
        "unreachable": [
            {"slug": s, "leaf": "SXT-028g (fx:Phaser)",
             "reason": "no committed fixture buses and no oracle-extracted "
                       "input record (fx_inputs/type-phaser-%s.json is a "
                       "'synthetic-corner' record, which the runner refuses "
                       "for a reference render); every SXT-028g reference "
                       "leg is NOT_RUN (reports/SXT-028g/artifacts/"
                       "oracle-status.json)" % s}
            for s in ("synth-a", "synth-b", "synth-c", "synth-clamp-a",
                      "synth-clamp-b", "synth-legacy-a", "synth-legacy-b",
                      "synth-maxst")],
    },
    "run_reverb2_model.py": {
        "leaves": ["SXT-028f (fx:Reverb 2)"],
        "report": "reports/SXT-028f",
        "preroll_source": {"kind": "module_constant",
                           "name": "SETTLE_BLOCKS"},
        "comparator": "tools/compare_reverb2_reference.py",
        "baseline": "artifacts/compare-{slug}__{seq}.json",
        "baseline_model": "artifacts/model__{slug}__{seq}.f32.wav",
        "input_bus": "per-slot bypass bus of the Reverb 2 slot (sidecar "
                     "'bypass')",
        "carriers": [{"slug": s, "seq": q, "leaf": "SXT-028f (fx:Reverb 2)",
                      "chain": "Reverb 2 last active global slot (model "
                               "input = engine per-slot bypass bus)"}
                     for s, q in _seqs(["moire1", "mystical", "tacobell"])],
        "unreachable": [
            {"slug": s, "leaf": "SXT-028f (fx:Reverb 2)",
             "reason": "no committed fixture: the pinned-engine render was "
                       "REFUSED by its 3x determinism gate "
                       "(reports/SXT-028f/artifacts/render-refusals.txt)"}
            for s in ("grant_me", "harp", "novuo")],
    },
    "run_distortion_sse_model.py": {
        "leaves": ["SXT-028e-sse (fx:Distortion, SSE models)"],
        "report": "reports/SXT-028e-sse",
        "preroll_source": {"kind": "kwarg_default",
                           "function": "run",
                           "name": "silent_preroll_blocks"},
        "comparator": "tools/compare_distortion_sse_reference.py",
        "baseline": "artifacts/compare-{slug}__{seq}.json",
        "baseline_model": "artifacts/model__{slug}__{seq}.f32.wav",
        "input_bus": "all-off dry bus (sidecar legs.dry, sha-verified by "
                     "the runner)",
        "committed_ab_record": "artifacts/settle-boundary.json",
        "carriers": [
            {"slug": "syn-d0-m3", "seq": "seq-poly-8-v1",
             "leaf": "SXT-028e-sse (fx:Distortion, SSE models)",
             "chain": "ains: distortion(0) -- the #136 harness anchor"},
        ],
        "unreachable": [
            {"slug": "syn-m3..m7, syn-d6/d12/d18-m3",
             "leaf": "SXT-028e-sse (fx:Distortion, SSE models)",
             "reason": "bounded audit: the leaf's A/B was measured on the "
                       "anchor only (#136), and its committed records already "
                       "run the measured pre-roll 0; C is not re-derived for "
                       "the other synthetic carriers here"},
        ],
    },
}

# Effect model directories NOT reached by any run_*_model.py runner. They
# are listed so coverage is explicit; their own harnesses' settle handling is
# outside this audit and is NOT_RUN here, never assumed correct.
NON_RUNNER_MODELS = {
    "reverb1": "SXT-024 leaf harness (tools/render_reverb_reference.py); "
               "also a chain occupant inside run_chorus_model.py "
               "(alienappears), where it IS covered by that runner's rows",
    "aw-4": "own leaf harness (tools/aw4_*); no run_*_model.py runner",
    "aw-49": "own leaf harness (tools/render_aw49_reference.py, "
             "tools/compare_aw49_reference.py); no run_*_model.py runner",
    "rf-rf-ains34": "routing-family model; no run_*_model.py runner",
    "rf-rf-bins12": "routing-family model; no run_*_model.py runner",
    "rf-rf-global2": "routing-family model; no run_*_model.py runner",
    "rf-rf-global34": "routing-family model; no run_*_model.py runner",
    "rf-rf-send34": "routing-family model; no run_*_model.py runner",
    "type-conditioner": "no run_*_model.py runner",
    "type-distortion": "SXT-028e (non-SSE Distortion); no run_*_model.py "
                       "runner",
}
RUNNER_MODELS = {
    "delay": "run_fx_model.py (+ chain occupant in run_chorus_model.py / "
             "run_phaser_model.py)",
    "eq": "run_fx_model.py (+ chain occupant in run_chorus_model.py / "
          "run_phaser_model.py)",
    "type-chorus": "run_chorus_model.py",
    "type-phaser": "run_phaser_model.py",
    "type-reverb 2": "run_reverb2_model.py",
    "type-distortion-sse": "run_distortion_sse_model.py",
}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(path):
    """Git blob id of a SOURCE file, for provenance.

    Deliberately not a sha256: a committed record carrying the sha256 of a
    tracked .py's current bytes makes that file a recorded source in the
    byte-frozen registry (tests/test_byte_frozen_sources.py). This audit pins
    nothing; the blob id + source revision identify what ran.
    """
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256_buf(a):
    import numpy as np
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def rel(path):
    return os.path.relpath(path, REPO)


def engine_settle_blocks(render, block_size=None):
    """The fixture renderer's own settle (`int(settle_s * SR) // bs`)."""
    bs = int(block_size or render.get("block_size") or 0)
    if bs <= 0 or render.get("settle_s") is None:
        raise AuditRefused("sidecar render block declares no settle_s / "
                           "block_size: %r" % (render,))
    return int(float(render["settle_s"]) * int(render.get("sample_rate",
                                                          SR))) // bs


def parse_runner_preroll(path):
    """Read a runner's silent pre-roll from its SOURCE (no import).

    Returns {"kind", "value" (int or None), "inherited_from", "detail"}.
    """
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    consts = {}
    imported = {}
    kwdefaults = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, int):
            consts[node.targets[0].id] = node.value.value
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                imported[a.asname or a.name] = node.module
        elif isinstance(node, ast.FunctionDef):
            args = node.args.args
            defs = node.args.defaults
            for a, d in zip(args[len(args) - len(defs):], defs):
                if isinstance(d, ast.Constant):
                    kwdefaults[(node.name, a.arg)] = d.value
    return {"constants": consts, "imported": imported,
            "kwdefaults": kwdefaults}


def resolve_preroll(runner_name, decl=None, parsed=None):
    """The production pre-roll a runner actually uses, from source."""
    decl = decl or RUNNERS[runner_name]["preroll_source"]
    path = os.path.join(EFFECTS, runner_name)
    parsed = parsed or parse_runner_preroll(path)
    kind = decl["kind"]
    if kind == "module_constant":
        if decl["name"] not in parsed["constants"]:
            raise AuditRefused("%s declares no module constant %s"
                               % (runner_name, decl["name"]))
        return {"blocks": parsed["constants"][decl["name"]],
                "source": "%s = %d (module constant)"
                          % (decl["name"], parsed["constants"][decl["name"]]),
                "inherited_from": None}
    if kind == "imported_constant":
        mod = parsed["imported"].get(decl["name"])
        if mod is None or mod + ".py" != decl["from"]:
            raise AuditRefused("%s does not import %s from %s (found %r)"
                               % (runner_name, decl["name"], decl["from"],
                                  mod))
        up = resolve_preroll(decl["from"])
        return {"blocks": up["blocks"],
                "source": "%s imported from %s (%s)"
                          % (decl["name"], decl["from"], up["source"]),
                "inherited_from": decl["from"]}
    if kind == "kwarg_default":
        key = (decl["function"], decl["name"])
        if key not in parsed["kwdefaults"]:
            raise AuditRefused("%s: %s() has no default for %s"
                               % (runner_name, *key))
        v = parsed["kwdefaults"][key]
        return {"blocks": int(v),
                "source": "%s(%s=%d) default" % (key[0], key[1], v),
                "inherited_from": None}
    raise AuditRefused("unknown pre-roll source kind %r" % kind)


def inventory():
    """Live inventory of every runner, refusing on an unaudited one."""
    import glob
    found = sorted(os.path.basename(p) for p in
                   glob.glob(os.path.join(EFFECTS, "run_*_model.py")))
    missing = [r for r in found if r not in RUNNERS]
    if missing:
        raise AuditRefused("unaudited runner(s) present: %s -- add them to "
                           "RUNNERS before this audit may report coverage"
                           % ", ".join(missing))
    stale = [r for r in RUNNERS if r not in found]
    if stale:
        raise AuditRefused("RUNNERS lists runner(s) not in the tree: %s"
                           % ", ".join(stale))
    rows = []
    for name in found:
        d = RUNNERS[name]
        pr = resolve_preroll(name)
        carriers = []
        for c in d["carriers"]:
            sc_path = os.path.join(REPO, d["report"], "fixtures",
                                   "%s__%s.json" % (c["slug"], c["seq"]))
            entry = dict(c)
            if os.path.exists(sc_path):
                sc = json.load(open(sc_path))
                eng = engine_settle_blocks(sc["render"])
                entry.update({
                    "fixture_sidecar": rel(sc_path),
                    "fixture_sidecar_sha256": sha256_file(sc_path),
                    "fixture_settle_s": sc["render"]["settle_s"],
                    "fixture_block_size": sc["render"]["block_size"],
                    "fixture_settle_blocks": eng,
                    "runner_preroll_blocks": pr["blocks"],
                    "runner_preroll_equals_fixture_settle":
                        pr["blocks"] == eng,
                    "runner_preroll_seconds":
                        pr["blocks"] * sc["render"]["block_size"] / SR,
                })
            else:
                entry["fixture_sidecar"] = None
            carriers.append(entry)
        rows.append({
            "runner": "model/effects/" + name,
            "runner_git_blob_sha1": git_blob_sha1(os.path.join(EFFECTS, name)),
            "leaves": d["leaves"],
            "production_preroll_blocks": pr["blocks"],
            "production_preroll_source": pr["source"],
            "inherited_from": pr["inherited_from"],
            "input_bus": d["input_bus"],
            "comparator": d["comparator"],
            "carriers": carriers,
            "unreachable_carriers": d["unreachable"],
        })
    model_dirs = sorted(
        e for e in os.listdir(EFFECTS)
        if os.path.isdir(os.path.join(EFFECTS, e))
        and e not in ("fx_inputs", "__pycache__"))
    unclassified = [m for m in model_dirs
                    if m not in NON_RUNNER_MODELS and m not in RUNNER_MODELS]
    if unclassified:
        raise AuditRefused("effect model dir(s) not classified as runner-"
                           "reached or not: %s" % ", ".join(unclassified))
    return {
        "runners": rows,
        "runner_reached_models": {m: RUNNER_MODELS[m] for m in model_dirs
                                  if m in RUNNER_MODELS},
        "not_runner_reached_models": {
            m: {"status": "NOT_RUN",
                "reason": "outside the run_*_model.py inventory; its own "
                          "harness's settle handling is not audited here "
                          "(never assumed correct)",
                "harness": NON_RUNNER_MODELS[m]}
            for m in model_dirs if m in NON_RUNNER_MODELS},
    }


# --------------------------------------------------------------------------
# The fail-closed boundary decision (the probe's rule, factored out)
# --------------------------------------------------------------------------

def decide_boundary(a_identical, b_identical):
    """A/B byte-identity -> (boundary_status, declared_preroll_blocks).

    `None` means the leg was not measured. Nothing here looks at C.
    """
    if a_identical is None or b_identical is None:
        if a_identical is False or b_identical is False:
            return "UNRESOLVED", None
        return "NOT_MEASURED", None
    if a_identical is True and b_identical is True:
        return "RESOLVED", 0
    return "UNRESOLVED", None


def runner_verdict(boundary_status, declared, runner_preroll, ab_status):
    """Whether the runner's production pre-roll matches the measured
    boundary. Returns (status, reason)."""
    if boundary_status == "RESOLVED":
        if runner_preroll == declared:
            return "PASS", ("runner pre-roll %d equals the measured boundary "
                            "%d" % (runner_preroll, declared))
        return "FAIL", ("runner pre-roll %d but the measured boundary is %d"
                        % (runner_preroll, declared))
    if boundary_status == "UNRESOLVED":
        return "NO_VERDICT", ("A or B not byte-identical: the boundary is "
                              "UNRESOLVED and no pre-roll is chosen by score")
    if ab_status == "BLOCKED":
        return "BLOCKED", ("A/B not measured: " + ORACLE_DEPENDENCY)
    return "NOT_RUN", "A/B not measured"


# --------------------------------------------------------------------------
# Comparator records: validation, metric extraction, deltas
# --------------------------------------------------------------------------

def validate_compare_record(rec, where="record"):
    """Refuse a malformed / refused / incomplete comparator record."""
    if not isinstance(rec, dict):
        raise AuditRefused("%s: not a JSON object" % where)
    if "channels" not in rec:
        raise AuditRefused("%s: no channels (refused or malformed: %s)"
                           % (where, rec.get("reason") or rec.get("verdict")))
    chs = rec["channels"]
    for ch in ("L", "R", "mono"):
        if ch not in chs:
            raise AuditRefused("%s: channel %s missing (per-channel data "
                               "must be preserved)" % (where, ch))
        for k in METRIC_KEYS:
            if k not in chs[ch]:
                raise AuditRefused("%s: channel %s lacks %s" % (where, ch, k))
    for k in ("spectral_corr_definition", "verdict"):
        if k not in rec:
            raise AuditRefused("%s: no %s" % (where, k))
    return rec


def extract_metrics(rec):
    validate_compare_record(rec)
    out = {ch: {k: rec["channels"][ch][k] for k in METRIC_KEYS}
           for ch in ("L", "R", "mono")}
    tc = rec.get("tail_check") or {}
    return {
        "channels": out,
        "spectral_corr_definition": rec["spectral_corr_definition"],
        "proposed_budget_results": rec.get("proposed_budget_results"),
        "tail_rms_rel_db": tc.get("tail_rms_rel_db"),
        "tail_gate_ok": rec.get("tail_gate_ok"),
        "verdict": rec["verdict"],
        "verdict_class": verdict_class(rec["verdict"]),
    }


def verdict_class(v):
    v = str(v)
    if v.startswith("PASS"):
        return "PASS"
    if v.startswith("FAIL"):
        return "FAIL"
    return "NO_VERDICT"


def metric_delta(base, other, current_definition):
    """other - base, per channel; refuses mixed spectral definitions."""
    if base["spectral_corr_definition"] != other["spectral_corr_definition"]:
        raise AuditRefused(
            "incompatible spectral_corr definitions (%r vs %r): a delta "
            "across definitions would be attributed to pre-roll wrongly"
            % (base["spectral_corr_definition"],
               other["spectral_corr_definition"]))
    if base["spectral_corr_definition"] != current_definition:
        raise AuditRefused("spectral_corr definition %r is not the current "
                           "declared one %r"
                           % (base["spectral_corr_definition"],
                              current_definition))
    d = {}
    for ch in ("L", "R", "mono"):
        b, o = base["channels"][ch], other["channels"][ch]
        if b["frames"] != o["frames"]:
            raise AuditRefused("frame counts differ (%d vs %d): outputs must "
                               "be full and equal-length" % (b["frames"],
                                                             o["frames"]))
        d[ch] = {k: o[k] - b[k] for k in ("max_abs_diff_lsb",
                                          "rms_diff_dbfs", "spectral_corr")}
    return d


# The comparator's metrics are float64 reductions (FFT spectra, RMS); across
# numpy builds/platforms they agree to rounding, not bit-for-bit. The MODEL
# side is checked bit-exactly (model WAV sha256); the metric re-derivation
# is accepted within this relative tolerance and the deviation is recorded.
METRIC_REL_TOL = 1e-9


def metrics_deviation(a, b):
    """(within_tolerance, max_relative_deviation, integer_keys_equal)."""
    worst = 0.0
    ints_ok = True
    for ch in ("L", "R", "mono"):
        for k in METRIC_KEYS:
            x, y = a["channels"][ch][k], b["channels"][ch][k]
            if k in ("frames", "best_shift"):
                ints_ok = ints_ok and x == y
                continue
            dev = abs(x - y) / max(1.0, abs(x))
            worst = max(worst, dev)
    return ints_ok and worst <= METRIC_REL_TOL, worst, ints_ok


def metrics_equal(a, b):
    return all(a["channels"][ch][k] == b["channels"][ch][k]
               for ch in ("L", "R", "mono") for k in METRIC_KEYS)


# --------------------------------------------------------------------------
# Offline leg C: adapters (subprocess-isolated) + the leaf's comparator
# --------------------------------------------------------------------------

def _leg_main(argv):
    """Internal: run ONE runner with an in-memory pre-roll override.

    Executed in a fresh interpreter so the override cannot leak between
    legs. The runner source file is never written.
    """
    ap = argparse.ArgumentParser(prog="audit_effect_settle_boundaries _leg")
    ap.add_argument("--runner", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", required=True)
    ap.add_argument("--pre", type=int, required=True)
    ap.add_argument("--fixtures-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    for p in (os.path.join(EFFECTS, "type-chorus"),
              os.path.join(EFFECTS, "type-phaser"),
              os.path.join(EFFECTS, "type-reverb 2"),
              os.path.join(EFFECTS, "type-distortion-sse"),
              os.path.join(EFFECTS, "reverb1"), EFFECTS, TOOLS, REPO):
        if p not in sys.path:
            sys.path.insert(0, p)
    import importlib
    mod_name = a.runner[:-3]
    if a.runner == "run_fx_model.py":
        m = importlib.import_module(mod_name)
        m.SETTLE_BLOCKS = a.pre
        sys.argv = [m.__file__, "--slug", a.slug, "--fixtures-dir",
                    a.fixtures_dir, "--out-dir", a.out_dir]
        m.main()
        produced = "model__%s__seq-notes-coverage-v1.f32.wav" % a.slug
    elif a.runner in ("run_chorus_model.py", "run_phaser_model.py"):
        rc = importlib.import_module("run_chorus_model")
        rc.SETTLE_BLOCKS = a.pre
        m = importlib.import_module(mod_name)
        m.SETTLE_BLOCKS = a.pre
        sys.argv = [m.__file__, "--slug", a.slug, "--seq", a.seq,
                    "--fixtures-dir", a.fixtures_dir, "--out-dir", a.out_dir]
        m.main()
        produced = "model__%s__%s.f32.wav" % (a.slug, a.seq)
    elif a.runner == "run_reverb2_model.py":
        m = importlib.import_module(mod_name)
        m.SETTLE_BLOCKS = a.pre
        with open(os.path.join(EFFECTS, "fx_inputs",
                               "type-reverb 2-%s.json" % a.slug)) as f:
            cfg = json.load(f)
        m.run(a.slug, a.seq, cfg, a.fixtures_dir, a.out_dir)
        produced = "model__%s__%s.f32.wav" % (a.slug, a.seq)
    elif a.runner == "run_distortion_sse_model.py":
        m = importlib.import_module(mod_name)
        m.run(a.slug, a.seq, a.fixtures_dir,
              os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts",
                           "synthetic"),
              a.out_dir, silent_preroll_blocks=a.pre)
        produced = "model__%s__%s.f32.wav" % (a.slug, a.seq)
    else:
        raise AuditRefused("no adapter for %s" % a.runner)
    print(json.dumps({"wav": os.path.join(a.out_dir, produced)}))
    return 0


def run_model_leg(runner, slug, seq, pre, fixtures_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cmd = [sys.executable, os.path.abspath(__file__), "_leg",
           "--runner", runner, "--slug", slug, "--seq", seq,
           "--pre", str(pre), "--fixtures-dir", fixtures_dir,
           "--out-dir", out_dir]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if p.returncode != 0:
        raise AuditRefused("model leg %s %s__%s pre=%d failed (exit %d): %s"
                           % (runner, slug, seq, pre, p.returncode,
                              p.stderr.strip()[-600:]))
    wav = json.loads(p.stdout.strip().splitlines()[-1])["wav"]
    return wav, cmd


def run_comparator(runner, slug, seq, fixtures_dir, model_wav, work):
    d = RUNNERS[runner]
    out_json = os.path.join(work, "compare.json")
    py = sys.executable
    if runner == "run_fx_model.py":
        cmd = [py, os.path.join(REPO, d["comparator"]),
               "--ref", os.path.join(fixtures_dir,
                                     "%s__%s-wet.f32.wav" % (slug, seq)),
               "--model", model_wav, "--preset", slug,
               "--sidecar", os.path.join(fixtures_dir,
                                         "%s__%s.json" % (slug, seq)),
               "--json", out_json]
    elif runner == "run_chorus_model.py":
        cmd = [py, os.path.join(REPO, d["comparator"]), "--slug", slug,
               "--seq", seq, "--fixtures-dir", fixtures_dir,
               "--model", model_wav, "--json", out_json]
    elif runner == "run_reverb2_model.py":
        # --art-dir = the leg's own out dir, so the comparator reads the
        # manifest THIS leg's runner wrote (wet-sha cross-check)
        cmd = [py, os.path.join(REPO, d["comparator"]), "--slug", slug,
               "--seq", seq, "--fixtures-dir", fixtures_dir,
               "--art-dir", os.path.dirname(model_wav),
               "--model", model_wav, "--json", out_json]
    elif runner == "run_distortion_sse_model.py":
        cmd = [py, os.path.join(REPO, d["comparator"]), "--slug", slug,
               "--seq", seq, "--fixtures-dir", fixtures_dir,
               "--art-dir", work, "--model", model_wav, "--json", out_json]
    else:
        raise AuditRefused("no comparator adapter for %s" % runner)
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if not os.path.exists(out_json):
        raise AuditRefused("comparator wrote no record (exit %d): %s"
                           % (p.returncode, p.stderr.strip()[-600:]))
    rec = json.load(open(out_json))
    if p.returncode != 0:
        raise AuditRefused("comparator refused (exit %d): %s"
                           % (p.returncode, rec.get("reason")))
    return rec, cmd


def equal_length_check(ref_path, model_path):
    from compare_chorus_reference import read_wav_stereo_f32  # noqa: PLC0415
    ref, sr = read_wav_stereo_f32(ref_path)
    mod, sr2 = read_wav_stereo_f32(model_path)
    if sr != SR or sr2 != SR:
        raise AuditRefused("sample rate %r/%r != %d" % (sr, sr2, SR))
    if ref.shape != mod.shape:
        raise AuditRefused("model %s is %r, reference %s is %r: outputs must "
                           "be full and equal-length (no truncation)"
                           % (rel(model_path), ref.shape, rel(ref_path),
                              mod.shape))
    return int(ref.shape[1])


def reference_wav(runner, sidecar):
    if runner == "run_distortion_sse_model.py":
        return os.path.join(REPO, sidecar["legs"]["original"]["wav"])
    return os.path.join(REPO, sidecar["wet"]["wav"])


def reference_buffer_sha(runner, sidecar):
    """The sidecar's declared determinism-gate BUFFER hash of the wet bus
    (comparable to the probe's `sha256_buf`)."""
    gate = sidecar.get("determinism_gate") or {}
    if runner == "run_distortion_sse_model.py":
        return (gate.get("per_leg_sha256_all") or {}).get("original",
                                                          [None])[0]
    if "wet_sha256_all" in gate:
        return gate["wet_sha256_all"][0]
    wet = sidecar.get("wet") or {}
    return (wet.get("determinism_sha256_all") or [None])[0]


def offline_c(runner, carrier, work_root, prerolls=None):
    """Leg C for one carrier: every candidate pre-roll, graded by the leaf's
    own comparator against the committed engine bus."""
    import compare_audio_reference as car  # noqa: PLC0415
    from compare_chorus_reference import read_wav_stereo_f32  # noqa: PLC0415
    d = RUNNERS[runner]
    slug, seq = carrier["slug"], carrier["seq"]
    fixtures_dir = os.path.join(REPO, d["report"], "fixtures")
    sc_path = os.path.join(fixtures_dir, "%s__%s.json" % (slug, seq))
    sidecar = json.load(open(sc_path))
    prod = resolve_preroll(runner)["blocks"]
    eng = engine_settle_blocks(sidecar["render"])
    cands = sorted(set(prerolls or (0, prod, eng)))
    ref_path = reference_wav(runner, sidecar)
    ref_buf, _ = read_wav_stereo_f32(ref_path)
    legs = {}
    for pre in cands:
        leg_dir = os.path.join(work_root, "%s__%s" % (slug, seq),
                               "preroll-%d" % pre)
        wav, run_cmd = run_model_leg(runner, slug, seq, pre, fixtures_dir,
                                     leg_dir)
        frames = equal_length_check(ref_path, wav)
        rec, cmp_cmd = run_comparator(runner, slug, seq, fixtures_dir, wav,
                                      leg_dir)
        legs[str(pre)] = {
            "silent_preroll_blocks": pre,
            "role": ("production" if pre == prod else
                     "fixture-settle" if pre == eng else "zero"),
            "model_wav_sha256": sha256_file(wav),
            "frames": frames,
            "metrics": extract_metrics(rec),
            "commands": {"model": _portable(run_cmd),
                         "comparator": _portable(cmp_cmd)},
        }
    prod_leg = legs[str(prod)]
    sensitive = len({leg["model_wav_sha256"] for leg in legs.values()}) > 1
    groups = {}
    for k, leg in sorted(legs.items(), key=lambda kv: int(kv[0])):
        groups.setdefault(leg["model_wav_sha256"], []).append(int(k))
    deltas = {}
    for k, leg in legs.items():
        if k == str(prod):
            continue
        deltas["%s_minus_production" % k] = metric_delta(
            prod_leg["metrics"], leg["metrics"], car.SPECTRAL_CORR_DEFINITION)
    verdicts = {k: leg["metrics"]["verdict_class"] for k, leg in legs.items()}
    return {
        "status": "MEASURED",
        "reference": {"wav": rel(ref_path), "wav_sha256": sha256_file(ref_path),
                      "buffer_sha256": sha256_buf(ref_buf),
                      "sidecar_declared_buffer_sha256":
                          reference_buffer_sha(runner, sidecar)},
        "fixture_settle_blocks": eng,
        "production_preroll_blocks": prod,
        "legs": legs,
        "model_output_preroll_sensitive": sensitive,
        "model_output_identity_groups": sorted(groups.values()),
        "deltas_vs_production": deltas,
        "comparator_verdict_by_preroll": verdicts,
        "comparator_verdict_depends_on_preroll":
            len(set(verdicts.values())) > 1,
        "note": "recorded, not tuned: no pre-roll is selected by these "
                "numbers",
    }


def _portable(cmd):
    out = []
    for c in cmd:
        if c == sys.executable:
            out.append("python3")
        elif isinstance(c, str) and c.startswith(REPO + os.sep):
            out.append(rel(c))
        elif isinstance(c, str) and c.startswith(tempfile.gettempdir()):
            out.append("<work>" + c[len(tempfile.gettempdir()):])
        else:
            out.append(c)
    return out


def baseline_check(runner, carrier, c_leg):
    """Tie leg C's production leg to the COMMITTED model render + record."""
    import compare_audio_reference as car  # noqa: PLC0415
    d = RUNNERS[runner]
    fmt = {"slug": carrier["slug"], "seq": carrier["seq"]}
    bpath = os.path.join(REPO, d["report"], d["baseline"].format(**fmt))
    mpath = os.path.join(REPO, d["report"], d["baseline_model"].format(**fmt))
    out = {"record": rel(bpath), "model_wav": rel(mpath)}
    if not os.path.exists(bpath):
        out.update(status="NOT_RUN", reason="no committed baseline record")
        return out
    out["record_sha256"] = sha256_file(bpath)
    rec = json.load(open(bpath))
    base = extract_metrics(validate_compare_record(rec, rel(bpath)))
    out["committed_metrics"] = base
    out["committed_verdict_class"] = base["verdict_class"]
    out["committed_spectral_corr_definition"] = \
        base["spectral_corr_definition"]
    out["definition_matches_current"] = (base["spectral_corr_definition"]
                                         == car.SPECTRAL_CORR_DEFINITION)
    prod = c_leg["legs"][str(c_leg["production_preroll_blocks"])]
    if os.path.exists(mpath):
        out["model_wav_sha256"] = sha256_file(mpath)
        out["production_leg_reproduces_committed_model"] = (
            out["model_wav_sha256"] == prod["model_wav_sha256"])
    else:
        out["production_leg_reproduces_committed_model"] = None
    if not out["definition_matches_current"]:
        out.update(status="STALE", reason=(
            "committed record uses a different spectral_corr definition; "
            "its numbers are reported but no delta is attributed to "
            "pre-roll across definitions"))
        return out
    ok, worst, ints_ok = metrics_deviation(base, prod["metrics"])
    out["production_leg_metrics_bit_identical_to_committed"] = metrics_equal(
        base, prod["metrics"])
    out["production_leg_metrics_max_rel_deviation"] = worst
    out["production_leg_metrics_within_tolerance"] = ok
    out["metric_tolerance"] = {
        "relative": METRIC_REL_TOL,
        "why": "comparator metrics are float64 reductions (FFT, RMS) that "
               "agree across numpy builds/platforms to rounding only; the "
               "model render itself is compared bit-exactly by sha256",
    }
    out["verdict_class_reproduced"] = (
        prod["metrics"]["verdict_class"] == base["verdict_class"])
    if out["production_leg_reproduces_committed_model"] is False or not ok \
            or not out["verdict_class_reproduced"]:
        out.update(status="STALE", reason=(
            "the production leg does not reproduce the committed model "
            "render / metrics / verdict on this host; the committed record "
            "is STALE for this comparison"))
    else:
        out["status"] = "PASS"
    out["deltas_vs_committed"] = {
        "%s_minus_committed" % k: metric_delta(
            base, leg["metrics"], car.SPECTRAL_CORR_DEFINITION)
        for k, leg in c_leg["legs"].items()}
    return out


# --------------------------------------------------------------------------
# Legs A/B
# --------------------------------------------------------------------------

def oracle_status():
    """Is the pinned oracle importable here? Never installs anything."""
    import oracle_common as oc  # noqa: PLC0415
    so_dir = os.path.join(oc.build_dir(), "src", "surge-python")
    info = {"engine_dir_probed": oc.engine_dir(),
            "engine_dir_present": os.path.isdir(oc.engine_dir()),
            "surgepy_dir_present": os.path.isdir(so_dir),
            "ORACLE_PREBUILT_URL_set": bool(os.environ.get(
                "ORACLE_PREBUILT_URL")),
            "ORACLE_SURGE_DIR_set": bool(os.environ.get("ORACLE_SURGE_DIR"))}
    if not info["surgepy_dir_present"]:
        info.update(available=False, reason=(
            "no surgepy build under %s" % so_dir))
        return info
    p = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, %r); import surgepy; "
                        "print(surgepy.getVersion())" % so_dir],
                       capture_output=True, text=True)
    info["surgepy_importable"] = p.returncode == 0
    info["available"] = p.returncode == 0
    info["reason"] = (p.stdout.strip() if p.returncode == 0
                      else p.stderr.strip()[-300:])
    return info


def committed_ab(runner, carrier):
    """A/B from a COMMITTED measured record (SXT-028e-sse, #136), tied to
    the committed fixture by its buffer hash."""
    d = RUNNERS[runner]
    path = os.path.join(REPO, d["report"], d["committed_ab_record"])
    rec = json.load(open(path))
    if rec.get("probe_carrier") != carrier["slug"] \
            or rec.get("sequence") != carrier["seq"]:
        raise AuditRefused("committed A/B record is for %s__%s, not %s__%s"
                           % (rec.get("probe_carrier"), rec.get("sequence"),
                              carrier["slug"], carrier["seq"]))
    if ENGINE_PIN not in str(rec.get("engine_pin")):
        raise AuditRefused("committed A/B record engine pin %r is not %s"
                           % (rec.get("engine_pin"), ENGINE_PIN))
    a = rec["A_settle_length_invariance"]
    b = rec["B_construction_invariance"]
    return {
        "source": "committed record %s (sha256 %s), measured by "
                  "tools/probe_distortion_sse_settle_boundary.py (#136); "
                  "not re-run here (the probe would overwrite its committed "
                  "record)" % (rel(path), sha256_file(path)),
        "A": {"status": "MEASURED", "byte_identical": bool(a["byte_identical"]),
              "settle_blocks_compared": a["settle_blocks_compared"],
              "sha256": a["sha256"]},
        "B": {"status": "MEASURED", "byte_identical": bool(b["byte_identical"]),
              "instantiation": "synthetic carrier constructed in place vs "
                               "saved to .fxp and re-loaded via loadPatch",
              "sha256": [b["sha256_constructed_in_place"],
                         b["sha256_saved_and_reloaded"]]},
        "a_short_buffer_sha256": a["sha256"][0],
        "recorded_C": rec.get("C_model_boundary_vs_engine"),
    }


def live_ab_factory(surgepy, sidecar, seq_id, tmpdir):
    """A/B on the pinned engine for an ORDINARY factory/3rd-party preset.

    UNEXERCISED on the host that wrote this tool (no oracle): its first live
    run is itself evidence to retain. B is instantiated as native loadPatch
    vs savePatch-then-loadPatch into a fresh instance (the ordinary load
    path for a real carrier; there is no synthetic construction to test).
    The dry bus is rendered at both settle lengths as a diagnostic: a dry
    difference means the settle sensitivity is synth-side, which still
    leaves the effect boundary UNRESOLVED (fail-closed).
    """
    import oracle_common as oc  # noqa: PLC0415
    import render_fx_fixtures as rfx  # noqa: PLC0415  (oracle-gated import)
    import render_fixture as rf  # noqa: PLC0415
    preset_abs = os.path.join(oc.engine_dir(), sidecar["preset"]["path"])
    seq = rf.load_sequence(seq_id)[0]

    def render(path, settle_s, fx_off=False):
        buf, _h, info = rfx.render_bus_stereo(
            surgepy, path, dict(seq, settle_s=settle_s), fx_off, repeats=1)
        return buf, info

    short, _ = render(preset_abs, 0.25)
    long_, _ = render(preset_abs, LONG_SETTLE_S)
    dshort, _ = render(preset_abs, 0.25, True)
    dlong, _ = render(preset_abs, LONG_SETTLE_S, True)
    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise AuditRefused("loadPatch failed: %s" % preset_abs)
        saved = os.path.join(tmpdir, "reloaded.fxp")
        s.savePatch(saved)
    finally:
        del s
    reloaded, _ = render(saved, 0.25)
    hs, hl, hr = sha256_buf(short), sha256_buf(long_), sha256_buf(reloaded)
    return {
        "source": "live, this run",
        "A": {"status": "MEASURED", "byte_identical": hs == hl,
              "settle_blocks_compared": [
                  int(0.25 * SR) // BLOCK, int(LONG_SETTLE_S * SR) // BLOCK],
              "sha256": [hs, hl],
              "dry_diagnostic_byte_identical":
                  sha256_buf(dshort) == sha256_buf(dlong)},
        "B": {"status": "MEASURED", "byte_identical": hs == hr,
              "instantiation": "native loadPatch vs savePatch + loadPatch "
                               "into a fresh instance",
              "sha256": [hs, hr]},
        "a_short_buffer_sha256": hs,
    }


# --------------------------------------------------------------------------
# One row
# --------------------------------------------------------------------------

def audit_row(runner, carrier, work_root, oracle, surgepy=None,
              c_runner=offline_c):
    d = RUNNERS[runner]
    prod = resolve_preroll(runner)
    sc_path = os.path.join(REPO, d["report"], "fixtures",
                           "%s__%s.json" % (carrier["slug"], carrier["seq"]))
    row = {"leaf": carrier["leaf"], "runner": "model/effects/" + runner,
           "carrier": carrier["slug"], "sequence": carrier["seq"],
           "chain": carrier.get("chain"),
           "runner_preroll_blocks": prod["blocks"],
           "runner_preroll_source": prod["source"]}
    if not os.path.exists(sc_path):
        row.update(status="NOT_RUN", coverage="none",
                   reason="no committed fixture sidecar %s" % rel(sc_path))
        return row
    sidecar = json.load(open(sc_path))
    row["fixture"] = {
        "sidecar": rel(sc_path), "sidecar_sha256": sha256_file(sc_path),
        "engine": sidecar.get("engine"),
        "sequence": sidecar.get("sequence"),
        "sequence_file_sha256": sha256_file(os.path.join(
            REPO, "fixtures", "sequences", carrier["seq"] + ".json")),
        "sample_rate": sidecar["render"].get("sample_rate"),
        "block_size": sidecar["render"]["block_size"],
        "settle_s": sidecar["render"]["settle_s"],
        "settle_blocks": engine_settle_blocks(sidecar["render"]),
        "render_tool": sidecar.get("tool"),
    }
    # --- A/B -------------------------------------------------------------
    if d.get("committed_ab_record"):
        ab = committed_ab(runner, carrier)
    elif oracle.get("available") and surgepy is not None:
        with tempfile.TemporaryDirectory(prefix="sxt318-ab-") as td:
            ab = live_ab_factory(surgepy, sidecar, carrier["seq"], td)
    else:
        ab = {"source": None,
              "A": {"status": "BLOCKED", "reason": ORACLE_DEPENDENCY},
              "B": {"status": "BLOCKED", "reason": ORACLE_DEPENDENCY}}
    row["A_settle_length_invariance"] = ab["A"]
    row["B_construction_invariance"] = ab["B"]
    row["ab_source"] = ab["source"]
    a_id = ab["A"].get("byte_identical") if ab["A"]["status"] == "MEASURED" \
        else None
    b_id = ab["B"].get("byte_identical") if ab["B"]["status"] == "MEASURED" \
        else None
    bstat, declared = decide_boundary(a_id, b_id)
    row["boundary"] = {"status": bstat, "declared_preroll_blocks": declared,
                       "rule": "RESOLVED (declared 0) only if A and B are "
                               "both measured byte-identical; otherwise no "
                               "pre-roll is declared"}
    ab_status = "BLOCKED" if ab["A"]["status"] == "BLOCKED" else (
        "MEASURED" if ab["A"]["status"] == "MEASURED" else "NOT_RUN")
    # --- C ---------------------------------------------------------------
    c = c_runner(runner, carrier, work_root)
    row["C_model_boundary_vs_engine"] = c
    if "a_short_buffer_sha256" in ab:
        row["A_short_matches_committed_reference"] = (
            ab["a_short_buffer_sha256"] == c["reference"]["buffer_sha256"])
    row["baseline"] = baseline_check(runner, carrier, c)
    # --- verdicts --------------------------------------------------------
    vstat, vwhy = runner_verdict(bstat, declared, prod["blocks"], ab_status)
    row["runner_boundary_verdict"] = {"status": vstat, "reason": vwhy}
    row["committed_numbers_dependence"] = (
        "SENSITIVE" if c["model_output_preroll_sensitive"] else "INSENSITIVE")
    row["source_reconciliation"] = source_reconciliation(
        prod["blocks"], row["fixture"]["settle_blocks"])
    row["nc_c_control"] = nc_c_control(bstat, declared, prod["blocks"], c)
    row["escalation"] = escalation(vstat, row["baseline"], c, declared,
                                   row["source_reconciliation"])
    row["status"] = vstat
    row["coverage"] = ("A,B,C" if ab_status == "MEASURED" else "C only")
    return row


def nc_c_control(bstat, declared, prod, c):
    """NC-C shape: the WRONG boundary must FAIL the declared comparison."""
    if not c["model_output_preroll_sensitive"]:
        return {"status": "NOT_RUN", "reason": (
            "not applicable: the model output is byte-identical for every "
            "candidate pre-roll (measured), so no wrong-boundary control can "
            "discriminate; insensitivity is the recorded fact")}
    if bstat != "RESOLVED":
        return {"status": "NOT_RUN", "reason": (
            "the wrong boundary is not yet known (boundary %s); each "
            "candidate's comparator verdict is already recorded under C so "
            "the control is designated, not re-run, once A/B resolve" % bstat)}
    wrong = [k for k, leg in c["legs"].items()
             if leg["silent_preroll_blocks"] != declared]
    res = {k: c["legs"][k]["metrics"]["verdict_class"] for k in wrong}
    ok = all(v == "FAIL" for v in res.values())
    return {"status": "PASS" if ok else "FAIL",
            "wrong_boundary_verdicts": res,
            "reason": ("every wrong-boundary leg FAILs the declared "
                       "comparison" if ok else
                       "a wrong-boundary leg does not FAIL: the comparison "
                       "cannot discriminate the boundary on this carrier")}


def source_reconciliation(prod, fixture_settle):
    """Is the runner's pre-roll one of the two candidate boundaries at all?

    The candidates are 0 (the effect starts the first audio block in its
    init() state -- the only value the probe's rule can ever declare) and the
    fixture's own settle (the effect saw every settle block). A pre-roll that
    is neither cannot be the engine's boundary under either hypothesis; this
    is a source fact, independent of A/B, and is reported as such.
    """
    cands = [0, fixture_settle]
    ok = prod in cands
    return {
        "check": "runner pre-roll in {0, fixture settle}",
        "candidates": cands,
        "runner_preroll_blocks": prod,
        "status": "PASS" if ok else "FAIL",
        "reason": ("pre-roll %d is candidate %s" % (
            prod, "0 (init state)" if prod == 0 else
            "'fixture settle' (%d blocks)" % fixture_settle) if ok else
            "pre-roll %d matches neither candidate boundary (0 or the "
            "fixture settle %d): it cannot be the engine's boundary under "
            "either hypothesis" % (prod, fixture_settle)),
        "limitation": "the probe's rule can positively RESOLVE only the 0 "
                      "boundary; a runner using the fixture settle can at "
                      "best be NO_VERDICT under this method",
    }


def escalation(vstat, baseline, c, declared, src=None):
    if vstat != "FAIL" and src is not None and src["status"] == "FAIL":
        return {"route": "#12 (SXT-017)",
                "trigger": "runner pre-roll matches neither candidate "
                           "boundary (source reconciliation FAIL); the "
                           "boundary itself is not measured",
                "committed_verdict": baseline.get("committed_verdict_class"),
                "verdict_by_candidate_preroll": {
                    k: v["metrics"]["verdict_class"]
                    for k, v in c["legs"].items()
                    if int(k) in src["candidates"]},
                "reason": "the committed numbers were produced at a "
                          "boundary no measurement can declare; both "
                          "candidate results are retained here and the "
                          "committed record is NOT replaced by this audit"}
    if vstat != "FAIL":
        return None
    right = c["legs"].get(str(declared))
    if right is None:
        return {"route": "#12", "reason": "runner boundary measured wrong; "
                "correct-boundary leg not in C"}
    return {"route": "#12 (SXT-017)",
            "committed_verdict": baseline.get("committed_verdict_class"),
            "correct_boundary_verdict": right["metrics"]["verdict_class"],
            "reason": "the runner's pre-roll is measured wrong; both numbers "
                      "are retained here and the committed record is NOT "
                      "replaced by this audit"}


# --------------------------------------------------------------------------
# Environment / provenance
# --------------------------------------------------------------------------

def environment():
    import numpy as np
    import compare_audio_reference as car  # noqa: PLC0415

    def git(*a):
        p = subprocess.run(["git", "-C", REPO] + list(a), capture_output=True,
                           text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    man = os.path.join(REPO, "oracle", "manifest.json")
    m = json.load(open(man))
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "source_revision": git("rev-parse", "HEAD"),
        "source_tree_dirty": bool(git("status", "--porcelain",
                                      "--untracked-files=no")),
        "oracle_manifest": rel(man),
        "oracle_manifest_sha256": sha256_file(man),
        "engine_commit": m["engine"]["commit"],
        "engine_submodules_sha256": hashlib.sha256(json.dumps(
            m.get("submodules"), sort_keys=True).encode()).hexdigest(),
        "audit_tool_git_blob_sha1": git_blob_sha1(os.path.abspath(__file__)),
        "comparator_spectral_corr_definition": car.SPECTRAL_CORR_DEFINITION,
        "sample_rate": SR,
        "block_size": BLOCK,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def leaf_file(runner):
    return runner[len("run_"):-len("_model.py")]


def cmd_inventory(args):
    inv = inventory()
    inv.update(schema_version=SCHEMA_VERSION, issue="#318",
               claim_scope="source inventory of run_*_model.py pre-roll "
                           "conventions; establishes no boundary, agreement "
                           "or support claim")
    write_json(os.path.join(args.out, "inventory.json"), inv)
    print(json.dumps({r["runner"]: r["production_preroll_blocks"]
                      for r in inv["runners"]}, indent=2))
    return 0


def cmd_run(args):
    inventory()                       # refuses on an unaudited runner
    oracle = oracle_status()
    surgepy = None
    if oracle.get("available"):
        import oracle_common as oc  # noqa: PLC0415
        surgepy = oc.import_surgepy()
        oc.apply_engine_env()
    env = environment()
    runners = [args.runner] if args.runner else list(RUNNERS)
    work = args.work or tempfile.mkdtemp(prefix="sxt318-work-")
    for runner in runners:
        d = RUNNERS[runner]
        rows = []
        for c in d["carriers"]:
            if args.carrier and "%s__%s" % (c["slug"], c["seq"]) \
                    not in args.carrier:
                continue
            try:
                rows.append(audit_row(runner, c, os.path.join(
                    work, leaf_file(runner)), oracle, surgepy))
            except AuditRefused as e:
                rows.append({"leaf": c["leaf"], "carrier": c["slug"],
                             "sequence": c["seq"], "status": "NO_VERDICT",
                             "coverage": "refused",
                             "reason": "audit refused: %s" % e})
            print("%s %s__%s -> %s" % (runner, c["slug"], c["seq"],
                                       rows[-1]["status"]), flush=True)
        for u in d["unreachable"]:
            rows.append({"leaf": u["leaf"], "carrier": u["slug"],
                         "status": "NOT_RUN", "coverage": "none",
                         "reason": u["reason"],
                         "A_settle_length_invariance": {
                             "status": "BLOCKED" if not oracle.get(
                                 "available") else "NOT_RUN",
                             "reason": ORACLE_DEPENDENCY if not oracle.get(
                                 "available") else u["reason"]}})
        rec = {
            "schema_version": SCHEMA_VERSION,
            "issue": "#318",
            "runner": "model/effects/" + runner,
            "runner_git_blob_sha1": git_blob_sha1(os.path.join(EFFECTS,
                                                              runner)),
            "leaves": d["leaves"],
            "production_preroll": resolve_preroll(runner),
            "comparator": d["comparator"],
            "comparator_git_blob_sha1": git_blob_sha1(os.path.join(REPO,
                                                          d["comparator"])),
            "oracle": oracle,
            "environment": env,
            "rows": rows,
            "claim_scope": "a harness settle-boundary audit. Not a fidelity "
                           "result, not a support claim; A/B output "
                           "invariance would establish the tested output "
                           "behaviour only, not every internal state "
                           "variable. Committed leaf records are not "
                           "modified.",
        }
        out = os.path.join(args.out, "%s.json" % leaf_file(runner))
        if args.carrier and os.path.exists(out):
            out = os.path.join(args.out, "%s.partial.json" % leaf_file(runner))
        write_json(out, rec)
        print("wrote %s" % rel(out), flush=True)
    return 0


def fmt_db(x):
    return "n/a" if x is None else "%.2f" % x


def cmd_table(args):
    """Render the per-leaf table (markdown) from the per-leaf JSON records."""
    lines = ["| leaf | carrier / seq | runner pre-roll | fixture settle | "
             "A (settle-length) | B (construction) | boundary | "
             "C: model sensitive? | C mono rms dBFS / max LSB by pre-roll | "
             "comparator verdict by pre-roll | committed record | "
             "pre-roll in {0, settle}? | runner verdict | coverage |",
             "|" + "---|" * 14]
    for runner in RUNNERS:
        p = os.path.join(args.out, "%s.json" % leaf_file(runner))
        if not os.path.exists(p):
            continue
        rec = json.load(open(p))
        for r in rec["rows"]:
            a = r.get("A_settle_length_invariance") or {}
            b = r.get("B_construction_invariance") or {}
            c = r.get("C_model_boundary_vs_engine")

            def ab(x):
                if x.get("status") == "MEASURED":
                    return "identical" if x["byte_identical"] else "DIFFERS"
                return x.get("status", "NOT_RUN")
            if c:
                cm = "; ".join(
                    "%s: %s / %.1f" % (k, fmt_db(v["metrics"]["channels"]
                                                ["mono"]["rms_diff_dbfs"]),
                                       v["metrics"]["channels"]["mono"]
                                       ["max_abs_diff_lsb"])
                    for k, v in sorted(c["legs"].items(),
                                       key=lambda kv: int(kv[0])))
                cv = "; ".join("%s: %s" % (k, v) for k, v in sorted(
                    c["comparator_verdict_by_preroll"].items(),
                    key=lambda kv: int(kv[0])))
                sens = "yes" if c["model_output_preroll_sensitive"] else "no"
                bl = r["baseline"]
                bls = "committed %s; reproduced here: %s" % (
                    bl.get("committed_verdict_class", "-"), bl.get("status"))
            else:
                cm = cv = sens = bls = "NOT_RUN"
            src = (r.get("source_reconciliation") or {}).get("status", "-")
            lines.append("| %s | %s%s | %s | %s | %s | %s | %s | %s | %s | %s "
                         "| %s | %s | %s | %s |" % (
                             r["leaf"], r["carrier"],
                             (" / " + r["sequence"]) if r.get("sequence")
                             else "",
                             r.get("runner_preroll_blocks", "-"),
                             (r.get("fixture") or {}).get("settle_blocks",
                                                          "-"),
                             ab(a), ab(b),
                             (r.get("boundary") or {}).get("status", "-"),
                             sens, cm, cv, bls, src, r["status"],
                             r.get("coverage", "-")))
    out = os.path.join(args.out, "audit-table.md")
    with open(out, "w") as f:
        f.write("<!-- generated by tools/audit_effect_settle_boundaries.py "
                "table; do not edit by hand -->\n")
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "_leg":
        return _leg_main(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("inventory", "run", "table"):
        sp = sub.add_parser(name)
        sp.add_argument("--out", default=DEFAULT_OUT)
        if name == "run":
            sp.add_argument("--runner", choices=sorted(RUNNERS))
            sp.add_argument("--carrier", action="append",
                            help="slug__seq (repeatable); default all")
            sp.add_argument("--work", help="scratch dir for model renders "
                                           "(default: a fresh temp dir)")
    args = ap.parse_args(argv)
    return {"inventory": cmd_inventory, "run": cmd_run,
            "table": cmd_table}[args.cmd](args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditRefused as e:
        print("REFUSING: %s" % e, file=sys.stderr)
        sys.exit(2)
