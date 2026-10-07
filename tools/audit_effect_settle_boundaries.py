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

SCHEMA_VERSION = 2             # 2: A0 repeatability, A/B diagnostics, leg D
SR = 48000
BLOCK = 32
LONG_SETTLE_S = 2.5            # 10x the declared 0.25 s, as in the probe
LIVE_REPEATS = 2               # A0: every live bus, fresh instances
SETTLE_BLOCKS_FIXTURE = 375    # int(0.25 * 48000) // 32, the fixture settle
LONG_SETTLE_BLOCKS = 3750      # int(2.5 * 48000) // 32
EARLY_SETTLE_BLOCKS = 2        # A_early: the shortest settle EVERY carrier
                               # accepts (the SSE synthetic construction
                               # needs its rebuild block + one settle block)
SWEEP_SETTLE_BLOCKS = (32, 120, 240)   # convergence diagnostic only
LSB_Q21 = float(1 << 21)
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
        # Engine-side A/B needs only the engine and a preset, not committed
        # fixtures: the leaf's queued factory carriers
        # (tools/render_phaser_fixtures.py PRESETS, census-blob verified at
        # run time). C stays NOT_RUN for them (no fixture buses / extracted
        # inputs: that is the SXT-028g reference leg, not this audit).
        "ab_only_carriers": [
            {"slug": s, "seq": q, "leaf": "SXT-028g (fx:Phaser)",
             "preset": p, "chain": "factory preset chain (engine-side A/B "
                                   "only)"}
            for s, p in (
                ("phasey", "resources/data/patches_factory/Polysynths/"
                           "Phasey.fxp"),
                ("squelch", "resources/data/patches_factory/Leads/"
                            "Squelch.fxp"),
                ("sticky", "resources/data/patches_factory/MPE/Sticky.fxp"))
            for q in ("seq-notes-coverage-v1", "seq-poly-8-v1")],
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

def decide_boundary_v1(a_identical, b_identical):
    """The #136 probe's rule, verbatim (kept for transparency only).

    RESOLVED (0) on A (375 vs 3750) and B byte identity. #318's live run
    measured that A cannot see an engine state that evolves during the
    settle and converges before block 375 (A_early), so this rule is no
    longer the audit's decision; every row records what it WOULD say.
    """
    if a_identical is None or b_identical is None:
        if a_identical is False or b_identical is False:
            return "UNRESOLVED", None
        return "NOT_MEASURED", None
    if a_identical is True and b_identical is True:
        return "RESOLVED", 0
    return "UNRESOLVED", None


def decide_boundary(a_identical, b_identical, repeatable=None,
                    a_early_identical=None):
    """A0/A/A_early/B -> (boundary_status, declared_preroll_blocks).

    The probe's fail-closed rule, TIGHTENED (never relaxed): the boundary is
    RESOLVED (declared pre-roll 0) only if A, A_early and B are all measured
    byte-identical and A0 did not fail. `None` means not measured. Nothing
    here looks at C (or D).

    * `repeatable` is the A0 control: a live render that does not reproduce
      itself in a fresh instance supports no byte-identity reading, so a
      measured `False` is UNRESOLVED.
    * `a_early_identical`: A (375 vs 3750) alone cannot tell "no evolution
      during the settle" from "evolution that converged before block 375";
      without A_early the boundary is not RESOLVED.
    """
    if repeatable is False:
        return "UNRESOLVED", None
    legs = (a_identical, b_identical, a_early_identical)
    if any(x is False for x in legs):
        return "UNRESOLVED", None
    if any(x is None for x in legs):
        return "NOT_MEASURED", None
    return "RESOLVED", 0


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
    info["identity"] = oracle_identity(oc.engine_dir())
    if info["available"] and ENGINE_PIN[:9] not in info["reason"]:
        info["identity"]["mismatches"].append(
            "surgepy version %r does not name the pinned commit"
            % info["reason"])
        info["identity"]["matches_manifest"] = False
    if info["available"] and not info["identity"]["matches_manifest"]:
        info.update(available=False, reason=(
            "oracle present but its identity does not match "
            "oracle/manifest.json: %s" % info["identity"]["mismatches"]))
    info["engine_dir_probed"] = _home(info["engine_dir_probed"])
    return info


def _home(path):
    h = os.path.expanduser("~")
    return ("~" + path[len(h):]) if path and path.startswith(h + os.sep) \
        else path


def oracle_identity(engine_dir):
    """Tie the oracle that ran to oracle/manifest.json (fail-closed).

    For a prebuilt install (#232) the install root carries BUILDINFO.json and
    .installed-sha256 (the artifact sha256 verified before unpacking). Their
    engine commit and artifact sha must equal the manifest's pins, or the
    oracle is treated as unavailable.
    """
    man = json.load(open(os.path.join(REPO, "oracle", "manifest.json")))
    out = {"manifest_engine_commit": man["engine"]["commit"],
           "mismatches": []}
    bi = os.path.join(engine_dir, "BUILDINFO.json")
    inst = os.path.join(engine_dir, ".installed-sha256")
    if os.path.exists(bi):
        b = json.load(open(bi))
        out["buildinfo"] = b
        plat = b.get("platform")
        pre = (man.get("prebuilt") or {}).get(plat) or {}
        out["manifest_prebuilt_platform"] = plat
        out["manifest_prebuilt_sha256"] = pre.get("sha256")
        if b.get("engine_commit") != man["engine"]["commit"]:
            out["mismatches"].append("BUILDINFO engine_commit %r"
                                     % b.get("engine_commit"))
        if os.path.exists(inst):
            got = open(inst).read().strip()
            out["installed_artifact_sha256"] = got
            if got != pre.get("sha256"):
                out["mismatches"].append("installed artifact sha256 %r != "
                                         "manifest prebuilt %r"
                                         % (got, pre.get("sha256")))
        else:
            out["mismatches"].append("prebuilt install has no "
                                     ".installed-sha256")
        out["kind"] = "prebuilt (#232)"
    else:
        out["kind"] = ("source build (no BUILDINFO.json; drift gate is "
                       "oracle/fetch-and-build.sh)")
    out["matches_manifest"] = not out["mismatches"]
    return out


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


FX_SLOTS = 16


def diff_stats(a, b):
    """Magnitude of a byte-identity failure (diagnostic, never a verdict)."""
    import numpy as np
    if a.shape != b.shape:
        return {"shape_mismatch": [list(a.shape), list(b.shape)]}
    d = np.abs(a.astype(np.float64) - b.astype(np.float64))
    per_frame = d.max(axis=0) if d.size else d
    nz = np.nonzero(per_frame)[0]
    first = int(nz[0]) if nz.size else None
    return {
        "max_abs_diff": float(d.max()) if d.size else 0.0,
        "max_abs_diff_lsb_q10_21": float(d.max() * LSB_Q21) if d.size else 0.0,
        "frames": int(a.shape[1]),
        "frames_differing": int(nz.size),
        "first_differing_frame": first,
        "first_differing_block": None if first is None else first // BLOCK,
    }


class _Bus:
    """One live bus, rendered LIVE_REPEATS times in fresh instances."""

    def __init__(self, buf, hashes, repeatable, divergence=None):
        self.buf, self.hashes = buf, hashes
        self.repeatable, self.divergence = repeatable, divergence

    @property
    def sha(self):
        return self.hashes[0] if self.hashes else None

    def record(self):
        return {"repeats": LIVE_REPEATS, "sha256_all": self.hashes,
                "byte_identical": self.repeatable,
                "divergence": self.divergence}


def live_bus(surgepy, path, seq, settle_s, off_slots=None,
             mutate_factory=None):
    """Render one bus under the SXT-012/023 fixture policy, A0-checked.

    Wet/dry/per-slot-bypass go through `render_reverb2_fixtures.
    render_bus_slots` (off_slots None = the unmodified chain, all 16 = the
    all-off dry bus, {k} = per-slot bypass) -- procedurally the committed
    renderers' path; `A_short_matches_committed_reference` checks that
    against committed bytes. `mutate` (SSE synthetic construction) goes
    through `render_distortion_sse_fixtures._render_once`, the probe's path
    (`mutate_factory()` builds a fresh mutator per render, as the probe does).
    A non-repeatable bus is RETURNED (buffer of the first repeat) with
    repeatable=False; the caller fails closed.
    """
    import render_fx_fixtures as rfx  # noqa: PLC0415  (oracle-gated)
    seq = dict(seq, settle_s=settle_s)
    if mutate_factory is not None:
        import numpy as np  # noqa: PLC0415
        import render_distortion_sse_fixtures as rdf  # noqa: PLC0415
        bufs = [np.asarray(rdf._render_once(surgepy, path, seq,
                                            mutate_factory())[0],
                           dtype=np.float32)
                for _ in range(LIVE_REPEATS)]
    else:
        import render_reverb2_fixtures as rr2  # noqa: PLC0415
        try:
            buf, hashes, _info = rr2.render_bus_slots(
                surgepy, path, seq, off_slots, repeats=LIVE_REPEATS)
            return _Bus(buf, hashes, True)
        except rr2.DeterminismRefusal as e:
            buf, _h, _i = rr2.render_bus_slots(surgepy, path, seq, off_slots,
                                               repeats=1)
            return _Bus(buf, e.hashes, False, e.stats)
    hashes = [rfx.sha256_buf(b) for b in bufs]
    ok = all(h == hashes[0] for h in hashes)
    return _Bus(bufs[0], hashes, ok,
                None if ok else diff_stats(bufs[0], bufs[1]))


def settle_s_for(blocks):
    """settle_s that the fixture renderers turn into exactly `blocks`
    (`int(settle_s * SR) // 32`); the +0.5 sample guards float floor."""
    s = (blocks * BLOCK + 0.5) / SR
    assert int(s * SR) // BLOCK == blocks, blocks
    return s


def _settle_buses(render, prefix, settles):
    """{"<prefix>_<settle>": bus} for each settle length in blocks."""
    return {"%s_%d" % (prefix, n): render(n) for n in settles}


def _a_records(buses, have_bypass_slots=(), have_dry=True):
    """A (375 vs 3750), A_early (EARLY vs 375) and the convergence sweep.

    Diagnostics (never verdicts): the all-off dry bus at the same settles (a
    difference there is synth-side and makes any wet difference
    unattributable) and, for a per-slot-bypass leaf, that bus (a difference
    there is upstream of the leaf).
    """
    def pair(prefix, n0, n1):
        x, y = buses["%s_%d" % (prefix, n0)], buses["%s_%d" % (prefix, n1)]
        return {"byte_identical": x.sha == y.sha,
                "diff": diff_stats(x.buf, y.buf)}

    def leg(n0, n1, extra=None):
        p = pair("wet", n0, n1)
        rec = {"status": "MEASURED", "byte_identical": p["byte_identical"],
               "settle_blocks_compared": [n0, n1],
               "sha256": [buses["wet_%d" % n0].sha, buses["wet_%d" % n1].sha],
               "diff": p["diff"]}
        if have_dry:
            d = pair("dry", n0, n1)
            rec["dry_diagnostic_byte_identical"] = d["byte_identical"]
            rec["dry_diagnostic_diff"] = d["diff"]
        if have_bypass_slots:
            rec["bypass_diagnostic"] = {
                "fx%d" % k: pair("bypass_fx%d" % k, n0, n1)
                for k in have_bypass_slots}
        rec.update(extra or {})
        return rec
    a = leg(SETTLE_BLOCKS_FIXTURE, LONG_SETTLE_BLOCKS)
    a_early = leg(EARLY_SETTLE_BLOCKS, SETTLE_BLOCKS_FIXTURE, {
        "why": "A compares 375 with 3750 settle blocks only. An engine "
               "state that evolves during the settle and has converged to "
               "a fixed point before block 375 passes A while the effect "
               "did NOT start the audio in its init() state. A_early "
               "compares the earliest settle every carrier accepts with "
               "375; only if it is ALSO identical is 'no evolution during "
               "the settle' measured."})
    sweep = {"settle_blocks": [], "wet_equals_fixture_settle": [],
             "dry_equals_fixture_settle": []}
    for n in sorted({EARLY_SETTLE_BLOCKS, *SWEEP_SETTLE_BLOCKS,
                     LONG_SETTLE_BLOCKS}):
        sweep["settle_blocks"].append(n)
        sweep["wet_equals_fixture_settle"].append(
            buses["wet_%d" % n].sha == buses["wet_375"].sha)
        if have_dry:
            sweep["dry_equals_fixture_settle"].append(
                buses["dry_%d" % n].sha == buses["dry_375"].sha)
    sweep["note"] = ("convergence diagnostic: which settle lengths reproduce "
                     "the 375-block fixture settle byte-for-byte")
    return a, a_early, sweep


def _a0(buses):
    ok = all(b.repeatable for b in buses.values())
    return {"status": "MEASURED", "repeats": LIVE_REPEATS,
            "all_buses_repeatable": ok,
            "non_repeatable_buses": sorted(k for k, b in buses.items()
                                           if not b.repeatable),
            "per_bus": {k: b.record() for k, b in buses.items()}}


def _b_record(short, reloaded, instantiation, extra=None):
    b = {"status": "MEASURED", "byte_identical": short.sha == reloaded.sha,
         "instantiation": instantiation, "sha256": [short.sha, reloaded.sha],
         "diff": diff_stats(short.buf, reloaded.buf)}
    b.update(extra or {})
    return b


def _settles():
    return sorted({EARLY_SETTLE_BLOCKS, *SWEEP_SETTLE_BLOCKS,
                   SETTLE_BLOCKS_FIXTURE, LONG_SETTLE_BLOCKS})


def live_ab_factory(surgepy, sidecar, seq_id, tmpdir, bypass_slots=(),
                    keep_buffers=False):
    """A/B on the pinned engine for an ORDINARY factory/3rd-party preset.

    First exercised live by #318's second increment (prebuilt oracle, #232).

    A0 (repeatability control): every bus below is rendered LIVE_REPEATS
       times in fresh instances; any non-repeatable bus makes the boundary
       UNRESOLVED -- without it a nondeterministic engine would read as
       "the effect evolved during the settle".
    A:  wet bus, 375- vs 3750-block settle (the probe's leg).
    A_early: wet bus, EARLY_SETTLE_BLOCKS vs 375 (see `_a_records`).
    B:  native loadPatch vs savePatch + loadPatch into a fresh instance (the
       ordinary load path for a real carrier; there is no synthetic
       construction). Diagnostics: whether a second save/reload is a fixed
       point.
    """
    import oracle_common as oc  # noqa: PLC0415
    import render_fx_fixtures as rfx  # noqa: PLC0415  (oracle-gated)
    rf = rfx.rf                       # fixtures/render_fixture.py
    preset_abs = os.path.join(oc.engine_dir(), sidecar["preset"]["path"])
    seq = rf.load_sequence(seq_id)[0]
    all_off = set(range(FX_SLOTS))
    settles = _settles()
    buses = {}
    buses.update(_settle_buses(lambda n: live_bus(
        surgepy, preset_abs, seq, settle_s_for(n)), "wet", settles))
    buses.update(_settle_buses(lambda n: live_bus(
        surgepy, preset_abs, seq, settle_s_for(n), all_off), "dry", settles))
    for k in bypass_slots:
        buses.update(_settle_buses(lambda n, k=k: live_bus(
            surgepy, preset_abs, seq, settle_s_for(n), {k}),
            "bypass_fx%d" % k,
            (EARLY_SETTLE_BLOCKS, SETTLE_BLOCKS_FIXTURE, LONG_SETTLE_BLOCKS)))
    saved = os.path.join(tmpdir, "reloaded.fxp")
    saved2 = os.path.join(tmpdir, "reloaded2.fxp")
    for src, dst in ((preset_abs, saved), (saved, saved2)):
        s = surgepy.createSurge(float(SR))
        try:
            if not s.loadPatch(src):
                raise AuditRefused("loadPatch failed: %s" % src)
            s.savePatch(dst)
        finally:
            del s
    buses["wet_reloaded"] = live_bus(surgepy, saved, seq,
                                     settle_s_for(SETTLE_BLOCKS_FIXTURE))
    buses["wet_reloaded_twice"] = live_bus(
        surgepy, saved2, seq, settle_s_for(SETTLE_BLOCKS_FIXTURE))
    a, a_early, sweep = _a_records(buses, bypass_slots)
    b = _b_record(
        buses["wet_375"], buses["wet_reloaded"],
        "native loadPatch vs savePatch + loadPatch into a fresh instance", {
            "reload_round_trip_fixed_point":
                buses["wet_reloaded"].sha == buses["wet_reloaded_twice"].sha,
            "saved_patch_sha256": sha256_file(saved),
            "saved_twice_patch_sha256": sha256_file(saved2),
            "source_patch_sha256": sha256_file(preset_abs)})
    out = {"source": "live, this run", "A0_repeatability": _a0(buses),
           "A": a, "A_early": a_early, "settle_sweep": sweep, "B": b,
           "a_short_buffer_sha256": buses["wet_375"].sha}
    if keep_buffers:
        out["_buses"] = buses
    return out


def live_ab_sse(surgepy, carrier, tmpdir, keep_buffers=False):
    """Live re-measurement of the #136 probe's A/B on this host, plus A0,
    A_early and the dry diagnostic (all-off mutator of the leaf's renderer).

    The probe's own legs (synthetic construction in place, A at 375 vs 3750,
    B as constructed vs savePatch + loadPatch). The probe itself is not run:
    it would overwrite its committed record.
    """
    import oracle_common as oc  # noqa: PLC0415
    import render_fx_fixtures as rfx  # noqa: PLC0415  (oracle-gated)
    rf = rfx.rf
    import distortion_sse_synthetic as syn  # noqa: PLC0415
    import render_distortion_sse_fixtures as rdf  # noqa: PLC0415
    slug = carrier["slug"]
    base = os.path.join(oc.engine_dir(), syn.SYN_BASE)
    if not os.path.exists(base):
        raise AuditRefused("synthetic base patch absent: %s" % base)
    slots = syn.carrier_slots(slug)
    seq = rf.load_sequence(carrier["seq"])[0]

    def mut():
        return rdf.synthetic_mutator(slug, slots)
    settles = _settles()
    buses = {}
    buses.update(_settle_buses(lambda n: live_bus(
        surgepy, base, seq, settle_s_for(n), mutate_factory=mut),
        "wet", settles))
    buses.update(_settle_buses(lambda n: live_bus(
        surgepy, base, seq, settle_s_for(n),
        mutate_factory=rdf.all_off_mutator), "dry", settles))
    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(base):
            raise AuditRefused("loadPatch failed: %s" % base)
        s.pitchBend(0, 0)
        s.channelController(0, 64, 0)
        s.channelController(0, 1, 0)
        s.channelController(0, 11, 0)
        s.channelAftertouch(0, 0)
        s.allNotesOff()
        syn.construct(s, slug, slots, SETTLE_BLOCKS_FIXTURE)
        saved = os.path.join(tmpdir, "constructed.fxp")
        s.savePatch(saved)
    finally:
        del s
    buses["wet_reloaded"] = live_bus(surgepy, saved, seq,
                                     settle_s_for(SETTLE_BLOCKS_FIXTURE))
    a, a_early, sweep = _a_records(buses)
    b = _b_record(buses["wet_375"], buses["wet_reloaded"],
                  "synthetic carrier constructed in place vs saved to .fxp "
                  "and re-loaded via loadPatch")
    out = {"source": "live, this run (the #136 probe's legs re-measured; "
                     "probe not run)",
           "A0_repeatability": _a0(buses), "A": a, "A_early": a_early,
           "settle_sweep": sweep, "B": b,
           "a_short_buffer_sha256": buses["wet_375"].sha}
    if keep_buffers:
        out["_buses"] = buses
    return out


# --------------------------------------------------------------------------
# Leg D (DIAGNOSTIC): does the model track the engine across settle lengths?
# --------------------------------------------------------------------------

D_NOTE = ("DIAGNOSTIC ONLY. Not an input to the boundary decision, which "
          "stays the A0/A/A_early/B rule: a pre-roll is never chosen from "
          "these numbers. D asks whether the model, pre-rolled N blocks, "
          "tracks the engine rendered with an N-block settle, for N = 375 "
          "and 3750, each graded by the leaf's own comparator against LIVE "
          "buses of this host's engine (input bus re-rendered at the same N).")


def _write_bus(path, buf):
    import render_fx_fixtures as rfx  # noqa: PLC0415
    rfx.write_wav_stereo_f32(path, buf)
    return {"wav": path, "sha256": sha256_file(path),
            "bytes": os.path.getsize(path), "frames": int(buf.shape[1])}


def d_bundle(runner, carrier, sidecar, sc_path, buses, n, out_dir):
    """A scratch fixture bundle of live buses at an n-block settle, shaped
    like the committed one so the production runner and the leaf's
    comparator read it unchanged. Never written under reports/."""
    import copy
    slug, seq = carrier["slug"], carrier["seq"]
    os.makedirs(out_dir, exist_ok=True)
    side = copy.deepcopy(sidecar)
    settle_s = settle_s_for(n)
    side["render"]["settle_s"] = settle_s
    wet = buses["wet_%d" % n]
    if wet.buf.shape[1] != int(side["render"]["frames"]):
        raise AuditRefused("live wet frames %d != declared %r"
                           % (wet.buf.shape[1], side["render"]["frames"]))
    wet_e = _write_bus(os.path.join(out_dir, "%s__%s-wet.f32.wav"
                                    % (slug, seq)), wet.buf)
    dry_e = _write_bus(os.path.join(out_dir, "%s__%s-dry.f32.wav"
                                    % (slug, seq)), buses["dry_%d" % n].buf)
    if "legs" in side:                 # SXT-028e-sse bundle shape
        for key in ("original",):
            side[key] = dict(side.get(key) or {}, **wet_e)
            side["legs"][key] = dict(side["legs"].get(key) or {}, **wet_e)
        side["dry"] = dict(side.get("dry") or {}, **dry_e)
        side["legs"]["dry"] = dict(side["legs"].get("dry") or {}, **dry_e)
    else:
        side["wet"] = dict(side.get("wet") or {}, **wet_e)
        side["dry"] = dict(side.get("dry") or {}, **dry_e)
    for key in list((side.get("bypass") or {})):
        k = int(key[2:])
        side["bypass"][key] = dict(side["bypass"][key], **_write_bus(
            os.path.join(out_dir, "%s__%s-bypass-fx%d.f32.wav"
                         % (slug, seq, k)),
            buses["bypass_fx%d_%d" % (k, n)].buf))
    used = [b for name, b in buses.items() if name.endswith("_%d" % n)]
    side["determinism_gate"] = {
        "repeats": LIVE_REPEATS, "drift_asserted": 0,
        "bit_identical": all(b.repeatable for b in used),
        "wet_sha256_all": wet.hashes,
        "scope": "#318 leg D scratch bundle: every bus re-rendered live "
                 "%dx in fresh instances on this host" % LIVE_REPEATS}
    side["audit_scratch"] = {"derived_from": rel(sc_path),
                             "settle_blocks": n,
                             "note": "scratch, never committed"}
    write_json(os.path.join(out_dir, "%s__%s.json" % (slug, seq)), side)
    return out_dir, wet_e["wav"]


def live_settle_tracking(runner, carrier, sidecar, sc_path, buses,
                         work_root):
    slug, seq = carrier["slug"], carrier["seq"]
    prod = resolve_preroll(runner)["blocks"]
    out = {"status": "MEASURED", "note": D_NOTE, "by_settle": {}}
    for n in (SETTLE_BLOCKS_FIXTURE, LONG_SETTLE_BLOCKS):
        root = os.path.join(work_root, "%s__%s" % (slug, seq),
                            "D-settle-%d" % n)
        fx_dir, ref = d_bundle(runner, carrier, sidecar, sc_path, buses, n,
                               os.path.join(root, "fixtures"))
        legs = {}
        for pre in sorted({0, prod, n}):
            leg_dir = os.path.join(root, "preroll-%d" % pre)
            wav, run_cmd = run_model_leg(runner, slug, seq, pre, fx_dir,
                                         leg_dir)
            frames = equal_length_check(ref, wav)
            rec, cmp_cmd = run_comparator(runner, slug, seq, fx_dir, wav,
                                          leg_dir)
            legs[str(pre)] = {
                "silent_preroll_blocks": pre,
                "role": ("pre-roll = engine settle" if pre == n else
                         "zero" if pre == 0 else "production"),
                "model_wav_sha256": sha256_file(wav), "frames": frames,
                "metrics": extract_metrics(rec),
                "commands": {"model": _portable(run_cmd),
                             "comparator": _portable(cmp_cmd)}}
        out["by_settle"][str(n)] = {
            "engine_settle_blocks": n,
            "engine_wet_sha256": buses["wet_%d" % n].sha,
            "legs": legs,
            "comparator_verdict_by_preroll": {
                k: v["metrics"]["verdict_class"] for k, v in legs.items()}}
    s, lg = (out["by_settle"][str(SETTLE_BLOCKS_FIXTURE)],
             out["by_settle"][str(LONG_SETTLE_BLOCKS)])
    out["summary"] = {
        "preroll_equals_settle_verdicts": [
            s["comparator_verdict_by_preroll"][str(SETTLE_BLOCKS_FIXTURE)],
            lg["comparator_verdict_by_preroll"][str(LONG_SETTLE_BLOCKS)]],
        "preroll_zero_verdicts": [s["comparator_verdict_by_preroll"]["0"],
                                  lg["comparator_verdict_by_preroll"]["0"]],
        "production_preroll_verdicts": [
            s["comparator_verdict_by_preroll"][str(prod)],
            lg["comparator_verdict_by_preroll"][str(prod)]],
        "reading": "verdict pairs are [engine settle 375, engine settle "
                   "3750]; recorded, not used to choose a pre-roll"}
    return out


def nc_d_control(dd):
    """NC-C's shape applied to the D DIAGNOSTIC: the wrong settle must FAIL.

    At each engine settle N, every model pre-roll that is NOT N must FAIL
    the leaf's own comparator, or D cannot tell settle histories apart on
    this carrier (and its "pre-roll = settle tracks" reading is empty). A
    control on D only: it never resolves a boundary and never turns a
    NO_VERDICT row into a verdict.
    """
    if not dd or dd.get("status") != "MEASURED":
        return {"status": "NOT_RUN", "reason": "leg D not measured on this "
                                               "row"}
    wrong = {}
    for n, v in sorted(dd["by_settle"].items(), key=lambda kv: int(kv[0])):
        for k, verdict in sorted(v["comparator_verdict_by_preroll"].items(),
                                 key=lambda kv: int(kv[0])):
            if k != n:
                wrong["settle %s / pre-roll %s" % (n, k)] = verdict
    ok = bool(wrong) and all(v == "FAIL" for v in wrong.values())
    return {
        "status": "PASS" if ok else "FAIL",
        "targets": "leg D (diagnostic): a model pre-roll that does not equal "
                   "the engine settle must FAIL the leaf's own comparator "
                   "at that settle",
        "mismatched_verdicts": wrong,
        "reason": ("every mismatched pre-roll FAILs: D discriminates settle "
                   "history on this carrier" if ok else
                   "a mismatched pre-roll does not FAIL: D cannot "
                   "discriminate settle history on this carrier"),
        "scope": "a control on the D diagnostic only; the boundary decision "
                 "is unchanged (A0/A/B)",
    }


def derive_controls(rec):
    """Derived, measurement-free fields of a per-leaf record (pure functions
    of recorded legs). Applied by `run` and re-applied by `rederive`."""
    for r in rec.get("rows", []):
        if "D_settle_tracking" in r:
            r["nc_d_control"] = nc_d_control(r["D_settle_tracking"])
    return rec


def cmd_rederive(args):
    """Re-apply `derive_controls` to committed per-leaf records.

    No engine, model or comparator runs: only fields that are pure functions
    of already-recorded leg results are (re)computed, and the record says so.
    """
    for runner in RUNNERS:
        p = os.path.join(args.out, "%s.json" % leaf_file(runner))
        if not os.path.exists(p):
            continue
        rec = derive_controls(json.load(open(p)))
        rec["derived_fields"] = {
            "fields": ["rows[].nc_d_control"],
            "how": "tools/audit_effect_settle_boundaries.py rederive: pure "
                   "functions of the recorded leg-D comparator verdicts; "
                   "nothing re-measured",
            "audit_tool_git_blob_sha1": git_blob_sha1(
                os.path.abspath(__file__)),
        }
        write_json(p, rec)
        print("rederived %s" % rel(p))
    return 0


# --------------------------------------------------------------------------
# One row
# --------------------------------------------------------------------------

def attribute_a_early(ae):
    """Say whether an A_early difference is attributable to the effect.

    The all-off dry bus (effects bypassed) is rendered at the same settles;
    if it also differs, the wet difference is not attributable to the effect.
    Annotation only: the boundary decision does not read it.
    """
    if ae.get("status") == "MEASURED" and ae.get("byte_identical") is False:
        if ae.get("dry_diagnostic_byte_identical") is False:
            ae["attribution"] = "CONFOUNDED_SYNTH_SIDE"
            ae["attribution_note"] = (
                "the all-off dry bus (effects bypassed) ALSO differs at "
                "these settle lengths, so the wet difference is not "
                "attributable to the effect: part or all of it is synth-side "
                "evolution (voices/filters/envelopes still settling). "
                "A_early therefore cannot establish effect-state evolution "
                "either; it only withholds RESOLVED.")
        elif ae.get("dry_diagnostic_byte_identical") is True:
            ae["attribution"] = "EFFECT_SIDE"
            ae["attribution_note"] = (
                "the dry bus is identical at these settle lengths while "
                "the wet bus differs: the difference is at or downstream "
                "of the effect chain.")
        else:
            ae["attribution"] = "UNATTRIBUTED"
            ae["attribution_note"] = "no dry diagnostic for this carrier."
    return ae


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
    live = oracle.get("available") and surgepy is not None
    a0 = None
    if d.get("committed_ab_record"):
        ab = committed_ab(runner, carrier)
        ab["A_early"] = {"status": "NOT_RUN", "reason": (
            "the committed #136 record has no A_early leg")}
        if live:
            with tempfile.TemporaryDirectory(prefix="sxt318-ab-") as td:
                rc = live_ab_sse(surgepy, carrier, td, keep_buffers=True)
            ab["_buses"] = rc.pop("_buses")
            row["live_recheck"] = rc
            row["live_recheck_matches_committed_record"] = (
                rc["A"]["sha256"] == ab["A"]["sha256"]
                and rc["B"]["sha256"] == ab["B"]["sha256"])
            # fail-closed: the committed AND the live measurement must hold
            for leg in ("A", "B"):
                ab[leg] = dict(ab[leg], byte_identical=bool(
                    ab[leg]["byte_identical"]
                    and rc[leg]["byte_identical"]))
            ab["A_early"] = rc["A_early"]
            ab["settle_sweep"] = rc["settle_sweep"]
            a0 = rc["A0_repeatability"]
            ab["source"] += "; re-measured live on this host (live_recheck)"
    elif live:
        with tempfile.TemporaryDirectory(prefix="sxt318-ab-") as td:
            ab = live_ab_factory(
                surgepy, sidecar, carrier["seq"], td,
                bypass_slots=tuple(sidecar.get("reverb2_slots") or ())
                if runner == "run_reverb2_model.py" else (),
                keep_buffers=True)
        a0 = ab.get("A0_repeatability")
    else:
        ab = {"source": None,
              "A": {"status": "BLOCKED", "reason": ORACLE_DEPENDENCY},
              "A_early": {"status": "BLOCKED", "reason": ORACLE_DEPENDENCY},
              "B": {"status": "BLOCKED", "reason": ORACLE_DEPENDENCY}}
    buses = ab.pop("_buses", None)
    ab.setdefault("A_early", {"status": "NOT_RUN",
                              "reason": "the A/B source has no A_early leg"})
    row["A0_repeatability"] = a0 or {
        "status": "NOT_RUN",
        "reason": "no live render on this run" if not live else
                  "the A/B source carries no repeatability leg"}
    row["A_settle_length_invariance"] = ab["A"]
    ae = attribute_a_early(ab["A_early"])
    row["A_early_settle_invariance"] = ae
    if ab.get("settle_sweep"):
        row["settle_sweep"] = ab["settle_sweep"]
    row["B_construction_invariance"] = ab["B"]
    row["ab_source"] = ab["source"]

    def measured(x):
        return x.get("byte_identical") if x.get("status") == "MEASURED" \
            else None
    a_id, b_id, e_id = (measured(ab["A"]), measured(ab["B"]),
                        measured(ab["A_early"]))
    repeatable = a0.get("all_buses_repeatable") if a0 else None
    bstat, declared = decide_boundary(a_id, b_id, repeatable, e_id)
    v1stat, v1decl = decide_boundary_v1(a_id, b_id)
    ab_status = "BLOCKED" if ab["A"]["status"] == "BLOCKED" else (
        "MEASURED" if ab["A"]["status"] == "MEASURED" else "NOT_RUN")
    row["boundary"] = {
        "status": bstat, "declared_preroll_blocks": declared,
        "rule": "RESOLVED (declared 0) only if A (375 vs 3750), A_early "
                "(%d vs 375) and B are all measured byte-identical and A0 "
                "did not fail; otherwise no pre-roll is declared"
                % EARLY_SETTLE_BLOCKS,
        "probe_rule_v1": {
            "status": v1stat, "declared_preroll_blocks": v1decl,
            "runner_verdict_under_v1": runner_verdict(
                v1stat, v1decl, prod["blocks"], ab_status)[0],
            "note": "the #136 probe's rule (A and B only), recorded so a "
                    "changed reading is visible, never silently relabeled"},
    }
    # --- C ---------------------------------------------------------------
    c = c_runner(runner, carrier, work_root)
    row["C_model_boundary_vs_engine"] = c
    if "a_short_buffer_sha256" in ab:
        row["A_short_matches_committed_reference"] = (
            ab["a_short_buffer_sha256"] == c["reference"]["buffer_sha256"])
        if buses is not None and not row["A_short_matches_committed_reference"]:
            from compare_chorus_reference import (  # noqa: PLC0415
                read_wav_stereo_f32)
            ref_buf, _ = read_wav_stereo_f32(os.path.join(
                REPO, c["reference"]["wav"]))
            row["A_short_vs_committed_reference_diff"] = diff_stats(
                ref_buf, buses["wet_%d" % SETTLE_BLOCKS_FIXTURE].buf)
    row["baseline"] = baseline_check(runner, carrier, c)
    # --- D (diagnostic) --------------------------------------------------
    if buses is None:
        row["D_settle_tracking"] = {
            "status": "NOT_RUN", "note": D_NOTE,
            "reason": "no live buses on this run (needs the pinned oracle)"}
    elif bstat == "RESOLVED":
        row["D_settle_tracking"] = {
            "status": "NOT_RUN", "note": D_NOTE,
            "reason": "boundary RESOLVED by A0/A/A_early/B; D is only "
                      "recorded for unresolved rows"}
    elif repeatable is False:
        row["D_settle_tracking"] = {
            "status": "NOT_RUN", "note": D_NOTE,
            "reason": "A0 FAIL: a live bus is not repeatable, so no live "
                      "bundle can carry a determinism gate"}
    else:
        row["D_settle_tracking"] = live_settle_tracking(
            runner, carrier, sidecar, sc_path, buses, work_root)
    # --- verdicts --------------------------------------------------------
    vstat, vwhy = runner_verdict(bstat, declared, prod["blocks"], ab_status)
    if repeatable is False:
        vwhy = ("A0 FAIL: a live render is not repeatable in a fresh "
                "instance; no byte-identity reading is possible, the "
                "boundary is UNRESOLVED")
    elif e_id is False and a_id is not False:
        vwhy = ("A_early DIFFERS (settle %d vs 375) while A (375 vs 3750) "
                "is identical: the bus evolves during the first settle "
                "blocks and converges before block 375, so A's identity "
                "does not establish an init-state start; the boundary is "
                "UNRESOLVED and no pre-roll is chosen by score. %s"
                % (EARLY_SETTLE_BLOCKS, row["A_early_settle_invariance"]
                   .get("attribution_note", "")))
    row["runner_boundary_verdict"] = {"status": vstat, "reason": vwhy}
    row["committed_numbers_dependence"] = (
        "SENSITIVE" if c["model_output_preroll_sensitive"] else "INSENSITIVE")
    row["source_reconciliation"] = source_reconciliation(
        prod["blocks"], row["fixture"]["settle_blocks"])
    row["nc_c_control"] = nc_c_control(bstat, declared, prod["blocks"], c)
    row["escalation"] = escalation(vstat, row["baseline"], c, declared,
                                   row["source_reconciliation"])
    v1 = row["boundary"]["probe_rule_v1"]
    if v1["runner_verdict_under_v1"] != vstat:
        row["probe_rule_v1_reading_changed"] = {
            "under_probe_rule_v1": v1["runner_verdict_under_v1"],
            "under_this_audit": vstat,
            "committed_verdict": row["baseline"].get(
                "committed_verdict_class"),
            "verdict_at_v1_declared_preroll": (
                c["legs"][str(v1["declared_preroll_blocks"])]["metrics"]
                ["verdict_class"]
                if v1["declared_preroll_blocks"] is not None
                and str(v1["declared_preroll_blocks"]) in c["legs"]
                else None),
            "route": "#12 (SXT-017)",
            "reason": "the probe's rule would read this row %s; this "
                      "audit's stricter rule (A_early, A0) withholds that "
                      "reading (A_early attribution: %s). Both readings and "
                      "both numbers are retained; nothing is relabeled and "
                      "no pre-roll is chosen by score."
                      % (v1["runner_verdict_under_v1"],
                         ae.get("attribution", "n/a"))}
    row["status"] = vstat
    row["coverage"] = ("A,B,C" if ab_status == "MEASURED" else "C only")
    if row["D_settle_tracking"]["status"] == "MEASURED":
        row["coverage"] += " (+D diagnostic)"
    return row


def ab_only_row(runner, carrier, work_root, oracle, surgepy=None):
    """Engine-side A/B for a carrier with no committed fixture (C NOT_RUN).

    Records the measured boundary for a leaf whose reference leg has not
    run yet, so its runner's pre-roll can be checked before it produces any
    committed number. Census-blob verified, as the leaf's own renderer is.
    """
    prod = resolve_preroll(runner)
    row = {"leaf": carrier["leaf"], "runner": "model/effects/" + runner,
           "carrier": carrier["slug"], "sequence": carrier["seq"],
           "chain": carrier.get("chain"), "preset": carrier["preset"],
           "runner_preroll_blocks": prod["blocks"],
           "runner_preroll_source": prod["source"],
           "C_model_boundary_vs_engine": None,
           "C_reason": "NOT_RUN: no committed fixture buses or extracted "
                       "model inputs for this carrier (the leaf's reference "
                       "leg, not this audit)"}
    if not (oracle.get("available") and surgepy is not None):
        row.update(status="BLOCKED", coverage="none",
                   reason="A/B not measured: " + ORACLE_DEPENDENCY,
                   A_settle_length_invariance={"status": "BLOCKED",
                                               "reason": ORACLE_DEPENDENCY})
        return row
    import oracle_common as oc  # noqa: PLC0415
    import render_fx_fixtures as rfx  # noqa: PLC0415
    blob, _graphs = rfx.census_entry(carrier["preset"])
    got = oc.git_blob_sha1(os.path.join(oc.engine_dir(), carrier["preset"]))
    row["census_blob_sha1"] = blob
    if got != blob:
        row.update(status="NO_VERDICT", coverage="refused",
                   reason="census blob mismatch: %s (%s != %s)"
                          % (carrier["preset"], got, blob))
        return row
    with tempfile.TemporaryDirectory(prefix="sxt318-ab-") as td:
        ab = live_ab_factory(surgepy, {"preset": {"path": carrier["preset"]}},
                             carrier["seq"], td)
    a0 = ab["A0_repeatability"]
    row["sequence_file_sha256"] = sha256_file(os.path.join(
        REPO, "fixtures", "sequences", carrier["seq"] + ".json"))
    row["A0_repeatability"] = a0
    row["A_settle_length_invariance"] = ab["A"]
    ae = attribute_a_early(ab["A_early"])
    row["A_early_settle_invariance"] = ae
    row["settle_sweep"] = ab["settle_sweep"]
    row["B_construction_invariance"] = ab["B"]
    row["ab_source"] = ab["source"]
    a_id, b_id, e_id = (ab["A"]["byte_identical"], ab["B"]["byte_identical"],
                        ab["A_early"]["byte_identical"])
    bstat, declared = decide_boundary(a_id, b_id,
                                      a0["all_buses_repeatable"], e_id)
    v1stat, v1decl = decide_boundary_v1(a_id, b_id)
    row["boundary"] = {
        "status": bstat, "declared_preroll_blocks": declared,
        "probe_rule_v1": {
            "status": v1stat, "declared_preroll_blocks": v1decl,
            "runner_verdict_under_v1": runner_verdict(
                v1stat, v1decl, prod["blocks"], "MEASURED")[0]}}
    vstat, vwhy = runner_verdict(bstat, declared, prod["blocks"], "MEASURED")
    if a0["all_buses_repeatable"] is False:
        vwhy = ("A0 FAIL: a live render is not repeatable in a fresh "
                "instance; the boundary is UNRESOLVED")
    elif e_id is False and a_id is not False:
        vwhy = ("A_early DIFFERS while A is identical: the bus evolves "
                "during the first settle blocks and converges before block "
                "375; the boundary is UNRESOLVED. %s"
                % ae.get("attribution_note", ""))
    row["runner_boundary_verdict"] = {"status": vstat, "reason": vwhy}
    row["reason"] = vwhy
    row["nc_c_control"] = {"status": "NOT_RUN",
                           "reason": "no leg C on this carrier"}
    row["escalation"] = None
    if vstat == "FAIL":
        row["finding"] = (
            "latent: the runner's pre-roll %d is measured wrong for this "
            "carrier (boundary %d) BEFORE the leaf has any committed "
            "model-vs-reference number; no committed PASS moves, so this is "
            "not a #12 stop. It must be resolved before the leaf's "
            "reference leg runs." % (prod["blocks"], declared))
    row["status"] = vstat
    row["coverage"] = "A,B only"
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
        for c in d.get("ab_only_carriers", []):
            if args.carrier and "%s__%s" % (c["slug"], c["seq"]) \
                    not in args.carrier:
                continue
            try:
                rows.append(ab_only_row(runner, c, os.path.join(
                    work, leaf_file(runner)), oracle, surgepy))
            except AuditRefused as e:
                rows.append({"leaf": c["leaf"], "carrier": c["slug"],
                             "sequence": c["seq"], "status": "NO_VERDICT",
                             "coverage": "refused",
                             "reason": "audit refused: %s" % e})
            print("%s %s__%s (A/B only) -> %s" % (
                runner, c["slug"], c["seq"], rows[-1]["status"]), flush=True)
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
        derive_controls(rec)
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
             "A0 (repeat) | A (375 vs 3750) | A_early (2 vs 375) | "
             "B (construction) | "
             "boundary | C: model sensitive? | "
             "C mono rms dBFS / max LSB by pre-roll | "
             "C comparator verdict by pre-roll | committed record | "
             "D (diagnostic) verdicts [settle 375, 3750] by pre-roll | "
             "pre-roll in {0, settle}? | runner verdict | coverage |",
             "|" + "---|" * 17]
    for runner in RUNNERS:
        p = os.path.join(args.out, "%s.json" % leaf_file(runner))
        if not os.path.exists(p):
            continue
        rec = json.load(open(p))
        for r in rec["rows"]:
            a = r.get("A_settle_length_invariance") or {}
            ae = r.get("A_early_settle_invariance") or {}
            b = r.get("B_construction_invariance") or {}
            c = r.get("C_model_boundary_vs_engine")
            a0 = r.get("A0_repeatability") or {}
            dd = r.get("D_settle_tracking") or {}

            def ab(x):
                if x.get("status") == "MEASURED":
                    return "identical" if x["byte_identical"] else "DIFFERS"
                return x.get("status", "NOT_RUN")
            a0s = ("PASS" if a0.get("all_buses_repeatable") else "FAIL") \
                if a0.get("status") == "MEASURED" else \
                a0.get("status", "NOT_RUN")
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
            if dd.get("status") == "MEASURED":
                bs = dd["by_settle"]
                pres = sorted({int(k) for v in bs.values()
                               for k in v["legs"]})
                ds = "; ".join(
                    "%d: [%s]" % (k, ", ".join(
                        bs[n]["comparator_verdict_by_preroll"].get(
                            str(k), "-") for n in ("375", "3750")))
                    for k in pres)
            else:
                ds = dd.get("status", "NOT_RUN")
            src = (r.get("source_reconciliation") or {}).get("status", "-")
            lines.append("| %s | %s%s | %s | %s | %s | %s | %s | %s | %s | %s "
                         "| %s | %s | %s | %s | %s | %s | %s |" % (
                             r["leaf"], r["carrier"],
                             (" / " + r["sequence"]) if r.get("sequence")
                             else "",
                             r.get("runner_preroll_blocks", "-"),
                             (r.get("fixture") or {}).get("settle_blocks",
                                                          "-"),
                             a0s, ab(a), ab(ae), ab(b),
                             (r.get("boundary") or {}).get("status", "-"),
                             sens, cm, cv, bls, ds, src, r["status"],
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
    for name in ("inventory", "run", "table", "rederive"):
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
            "table": cmd_table, "rederive": cmd_rederive}[args.cmd](args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditRefused as e:
        print("REFUSING: %s" % e, file=sys.stderr)
        sys.exit(2)
