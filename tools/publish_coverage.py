#!/usr/bin/env python3
"""SXT-029 apparatus: deterministic per-preset coverage reconciliation.

Publishes reports/coverage-v1/ (per-preset.csv + coverage.json): every corpus
entry (3,561) gets exactly one headline status -- supported / adapted /
unsupported / unresolved -- computed as the CONSERVATIVE CONJUNCTION of the
committed evidence:

    supported  = normalized AND compiled AND every required leaf verified
                 (voice slice, all active FX classes, wavetable envelope,
                 routing forms) AND the fidelity-freeze gate PASS.
    adapted    = renderable only with disclosed edits per committed records
                 (SXT-017 polylimit-reduction policy; SXT-025 finding F-1).
                 Never counted toward supported.
    unsupported= the compile scan structurally rejects the preset's original
                 graph (machine-readable rejection codes).
    unresolved = otherwise; the row carries the named missing step(s).

This tool reconciles committed artifacts; it renders nothing, measures
nothing, and verifies nothing new. Prediction is not qualification: the
SXT-017 B4-broad prediction appears only as a prospective per-row column and
is never an input to the headline status. Coverage (counts) is reported
separately from agreement (fidelity metrics live only in the linked evidence
records) and from listening outcomes (none exist; #8/#9 BLOCKED).

FAIL-CLOSED: every structural input is pinned by its full sha256; a missing
or mismatched input REFUSES the run (exit 2), as does any reconciliation gap
(a corpus entry with no compile-scan outcome, a sha disagreement, a count
mismatch). Leaf/gate EVIDENCE pins behave differently: a mismatch or missing
file marks that leaf STALE and DOWNGRADES every preset whose path requires it
-- it can never report them supported (negative control: staleness must
downgrade, not pass).

Verification statuses use the PASS/FAIL/NOT_RUN/BLOCKED/NO_VERDICT/STALE
vocabulary; NOT_RUN is never counted as a pass. The empty string means the
gate was not reached (structural status preceded it) or is vacuous for the
preset (e.g. no FX required); it is never a pass.

Deterministic: same committed inputs => byte-identical outputs (sorted keys,
no clock, no randomness, fixed column order). Python 3 standard library only.
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TOOL_VERSION = "sxt-029-coverage/1.0.0"
SCHEMA_VERSION = "sxt-029-coverage/1.0.0"
ISSUE = "SXT-029 (#22)"

GRAPH_DEFAULT = "corpus/normalized/graphs.jsonl"
SCAN_DEFAULT = "reports/sxt-020/compile-corpus-scan.json"
PREDICTION_DEFAULT = "reports/sxt-017/predictions/B4-broad.json"
SLATES = [
    "reports/sxt-013/candidates/slate-256-balanced.json",
    "reports/sxt-013/candidates/slate-256-contributor-lean.json",
    "reports/sxt-013/candidates/slate-256-factory-lean.json",
]
LEAF_LEDGER_INPUTS = [
    "reports/sxt-027/leaves-filed.json",
    "reports/sxt-027/leaf-backlog.json",
    "reports/sxt-028/leaves-filed.json",
    "reports/sxt-028/leaf-backlog.json",
]
SELECTION_SCAN = "model/integration/selection-scan.json"
TABLE_DEFAULT = "reports/coverage-v1/leaf-verification.json"
# #122 / decision record 0013: the measured set of corpus presets carrying an
# effect whose sound depends on an RNG stream that cannot be pinned under the
# SXT-010 manifest. Published as a coverage REDUCTION: the denominators do
# not move, the affected presets can never be reported supported.
RNG_EXCLUSION_DEFAULT = "reports/SXT-028-rng/artifacts/coverage-impact.json"

# Full sha256 pins of the structural inputs (no truncation). A mismatch
# REFUSES the run. Legitimate data updates are visible contract revisions:
# the pin changes in the same commit as the data.
STRUCTURAL_INPUTS = {
    GRAPH_DEFAULT: "c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715",
    SCAN_DEFAULT: "e23e351c7850c2d4936afc887f3adca5274e800395f9b84232e4ede0dc4ed0d6",
    # revised by #117: SXT-015 Conditioner state_bytes 8192 -> 2444 (SXT-028b
    # measurement) changes on_chip_state_bytes only; no preset status moved.
    PREDICTION_DEFAULT: "11d5c2710e079a6c3d364a8d0188066b3b726cfdca6f6d423614a4da2e74795f",
    "reports/sxt-013/candidates/slate-256-balanced.json": "23cb4e51b8ee8cbe0461ea168ec102a0815d5cd5e96ba5fc1b58d56d247f1f90",
    "reports/sxt-013/candidates/slate-256-contributor-lean.json": "0393aa5c4bd7b1ea8f257c41b45194345239cef99b4cb7d673b4556a7b51b06e",
    "reports/sxt-013/candidates/slate-256-factory-lean.json": "2426773096e226122fd52d008cc8d016187291dba743d6343c01fef5110e9883",
    "reports/sxt-027/leaves-filed.json": "639b51de26efeb1e4d94a60a9c38dd56f58346c42a8fbf2d81b843bb4fb95c5f",
    "reports/sxt-027/leaf-backlog.json": "76e526549c1cca7cb6f070640c1a1b4e5ee5364be1992adf66305df917c8ebd2",
    "reports/sxt-028/leaves-filed.json": "b6ade0fe36a0ed2b4eae7637b92f1492915c1f2350b0f07fccdf0c23e15ad6d4",
    # revised by #117: SXT-028b leaf title corrected (no gate, no LFO).
    "reports/sxt-028/leaf-backlog.json": "d6120066b307f5b901dae5d0102836b1d3352681b6a06a6e2baf53a075a244dc",
    SELECTION_SCAN: "7d0ab62d5d098d930e84c4bb78809d18eddac9932c536e70e086aeb88ee92d4f",
    # added by #122 (decision record 0013): measured FX-RNG exclusion set.
    RNG_EXCLUSION_DEFAULT: "c358b4764f2d789cdd663237639216cdf25849f54ef0b75a7c7eee3c44ed26aa",
}

STATUS_VOCAB = ["PASS", "FAIL", "NOT_RUN", "BLOCKED", "NO_VERDICT", "STALE"]
HEADLINE_STATUSES = ["supported", "adapted", "unsupported", "unresolved"]

# Effect class -> leaf key in the verification table. Classes outside this
# map cannot appear on a compiled preset (compile-scan invariant, asserted).
FX_TYPE_TO_LEAF = {
    "Delay": "fx:Delay",
    "EQ": "fx:EQ",
    "Reverb 1": "fx:Reverb1",
    "Chorus": "fx:Chorus",
    "Conditioner": "fx:Conditioner",
    "Distortion": "fx:Distortion",
    "Reverb 2": "fx:Reverb2",
    "Phaser": "fx:Phaser",
}
FX_BUNDLE_ALLOW = set(FX_TYPE_TO_LEAF) | {"Airwindows"}

BANKS = ["contributor", "factory"]

CSV_COLUMNS = [
    "bank", "path", "blob_sha1", "headline_status",
    "normalized", "compile_gate", "compile_codes",
    "voice_leaf_gate", "fx_leaves_gate", "fx_rng_gate",
    "wavetable_leaf_gate",
    "routing_leaves_gate", "fidelity_contract_gate", "essentiality_listening",
    "fx_required", "b4_prediction", "slates", "reasons",
]


class Refuse(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(repo: Path, rel: str):
    path = repo / rel
    if not path.is_file():
        raise Refuse(f"missing required input: {rel}")
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def check_pin(repo: Path, rel: str, expected: str) -> None:
    path = repo / rel
    if not path.is_file():
        raise Refuse(f"missing required input: {rel}")
    actual = sha256_file(path)
    if actual != expected:
        raise Refuse(
            f"input integrity mismatch for {rel}: expected sha256 {expected}, "
            f"found {actual} (refusing; data updates must revise the pin)"
        )


# ---------------------------------------------------------------- gate logic

WORST_ORDER = ["", "PASS", "NO_VERDICT", "NOT_RUN", "BLOCKED", "FAIL", "STALE"]


def worst(a: str, b: str) -> str:
    return a if WORST_ORDER.index(a) >= WORST_ORDER.index(b) else b


def leaf_ready(leaf: dict) -> bool:
    v = leaf.get("verification", {})
    return v.get("rtl_vs_model") == "PASS" and v.get("model_vs_reference") == "PASS"


def evidence_state(repo: Path, evidence: list) -> tuple:
    """Return (state, detail). state in {OK, STALE}."""
    for item in evidence or []:
        path = repo / item["path"]
        if not path.is_file():
            return "STALE", f"missing evidence file {item['path']}"
        actual = sha256_file(path)
        if actual != item["sha256"]:
            return "STALE", (
                f"evidence hash mismatch for {item['path']}: expected "
                f"{item['sha256']}, found {actual}"
            )
    return "OK", ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    ap.add_argument("--outdir", default="reports/coverage-v1")
    ap.add_argument("--leaf-table", default=None,
                    help="override the committed leaf-verification table "
                         "(negative-control scenarios only; published runs "
                         "must use the committed default)")
    ap.add_argument("--control-allow-input-drift", action="store_true",
                    help="skip structural input hash pins (negative-control "
                         "scenarios only; reconciliation checks stay live). "
                         "Never valid for a published run.")
    ap.add_argument("--rng-exclusion", default=None,
                    help="override the committed #122/DR-0013 FX-RNG "
                         "exclusion artifact (negative-control scenarios "
                         "only; published runs must use the committed "
                         "default)")
    ap.add_argument("--control-ignore-rng-exclusion", action="store_true",
                    help="ignore the #122/DR-0013 FX-RNG exclusion gate "
                         "(negative-control scenarios only, to show the gate "
                         "is load-bearing). Never valid for a published run.")
    args = ap.parse_args()
    repo = Path(args.repo_root).resolve()

    try:
        run(repo, args)
    except Refuse as e:
        print(f"REFUSE: {e}", file=sys.stderr)
        return 2
    return 0


def run(repo: Path, args) -> None:
    # ---- inputs + integrity -------------------------------------------
    if not args.control_allow_input_drift:
        for rel, pin in sorted(STRUCTURAL_INPUTS.items()):
            check_pin(repo, rel, pin)
    else:
        for rel in sorted(STRUCTURAL_INPUTS):
            if not (repo / rel).is_file():
                raise Refuse(f"missing required input: {rel}")

    table_rel = args.leaf_table or TABLE_DEFAULT
    table_path = Path(table_path_abs(repo, table_rel))
    if not table_path.is_file():
        raise Refuse(f"missing leaf-verification table: {table_rel}")
    table = json.loads(table_path.read_text(encoding="utf-8"))

    graphs = []  # ordered as committed
    with open(repo / GRAPH_DEFAULT, "rb") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                graphs.append(json.loads(line.decode("utf-8")))
            except json.JSONDecodeError as e:
                raise Refuse(f"{GRAPH_DEFAULT}:{lineno}: bad JSON: {e}")
    if len(graphs) != 3561:
        raise Refuse(f"expected 3,561 corpus entries, found {len(graphs)}")

    scan = load_json(repo, SCAN_DEFAULT)
    pred = load_json(repo, PREDICTION_DEFAULT)
    slates = {rel: load_json(repo, rel) for rel in SLATES}
    sel = load_json(repo, SELECTION_SCAN)
    ledgers = {rel: load_json(repo, rel) for rel in LEAF_LEDGER_INPUTS}

    # #122 / DR-0013: measured FX-RNG exclusion set. Fail-closed -- a missing
    # or self-contradictory artifact REFUSES rather than silently gating
    # nothing. --control-ignore-rng-exclusion disables the gate for negative
    # controls only and is never valid for a published run.
    rng_rel = args.rng_exclusion or RNG_EXCLUSION_DEFAULT
    rng_path = Path(table_path_abs(repo, rng_rel))
    if not rng_path.is_file():
        raise Refuse(f"missing FX-RNG exclusion artifact: {rng_rel}")
    rng_doc = json.loads(rng_path.read_text(encoding="utf-8"))
    if rng_doc["corpus"]["denominator"] != len(graphs):
        raise Refuse(
            f"FX-RNG exclusion artifact counted "
            f"{rng_doc['corpus']['denominator']} corpus entries, coverage "
            f"sees {len(graphs)}"
        )
    rng_affected = {}
    for rec in rng_doc["affected_presets"]:
        rng_affected[rec["path"]] = sorted(
            {c["fx_type_name"] for c in rec["classes"]})
    if len(rng_affected) != rng_doc["corpus"]["affected_presets"]:
        raise Refuse("FX-RNG exclusion artifact row count disagrees with its "
                     "own total")
    rng_gate_active = not args.control_ignore_rng_exclusion

    # ---- reconciliation (fail-closed) ---------------------------------
    by_path = {}
    for e in graphs:
        p = e["p"]
        if p in by_path:
            raise Refuse(f"duplicate corpus path: {p}")
        by_path[p] = e
    for p in sorted(rng_affected):
        if p not in by_path:
            raise Refuse(f"FX-RNG exclusion path not in corpus: {p}")

    outcomes = scan["outcomes"]
    outcome_by_path = {}
    for o in outcomes:
        p = o["path"]
        if p not in by_path:
            raise Refuse(f"compile-scan outcome without corpus entry: {p}")
        if p in outcome_by_path:
            raise Refuse(f"duplicate compile-scan outcome: {p}")
        if o["sha"] != by_path[p]["sha"]:
            raise Refuse(
                f"sha disagreement for {p}: scan {o['sha']} vs graphs "
                f"{by_path[p]['sha']}"
            )
        outcome_by_path[p] = o
    missing = sorted(set(by_path) - set(outcome_by_path))
    if missing:
        raise Refuse(
            f"{len(missing)} corpus entries have no coverage row (no "
            f"compile-scan outcome), e.g. {missing[0]}; failing closed"
        )
    if scan["totals"]["total"] != len(graphs):
        raise Refuse("scan totals.total disagrees with corpus size")

    pred_by_path = {}
    for p in pred["presets"]:
        if p["path"] in pred_by_path:
            raise Refuse(f"duplicate prediction row: {p['path']}")
        pred_by_path[p["path"]] = p
    if set(pred_by_path) != set(by_path):
        raise Refuse("prediction rows do not cover the corpus exactly")

    slate_members = {}
    for rel in SLATES:
        s = slates[rel]
        name = s["artifact"]
        for c in s["candidates"]:
            p = c["path"]
            if p not in by_path:
                raise Refuse(f"slate {name} path not in corpus: {p}")
            slate_members.setdefault(p, []).append(name)

    # F-1 facts from the committed selection scan (never hardcoded).
    if sel.get("finding", {}).get("id") != "F-1":
        raise Refuse("selection-scan finding F-1 absent")
    f1_path = sel["selection"]["path"]
    tier4 = [t["path"] for t in sel["tier4_survivors_any_fx"]]
    voice_leaf = table["leaves"][table["voice_leaf_key"]]
    fixture_verified = voice_leaf.get("fixture_verified_paths", [])
    overlap = voice_leaf.get("overlap_paths_not_fixture_verified", [])
    if not set(fixture_verified) <= set(tier4):
        raise Refuse("table fixture-verified voice paths outside F-1 tier-4 set")
    if not set(overlap) <= set(tier4):
        raise Refuse("table overlap voice paths outside F-1 tier-4 set")
    if f1_path not in by_path:
        raise Refuse(f"F-1 integration preset not in corpus: {f1_path}")

    # Transcription guard: every routing/airwindows leaf id in the table
    # must exist in the committed SXT-028 artifacts (filed or backlog).
    known_028 = set()
    for rel in ("reports/sxt-028/leaves-filed.json",
                "reports/sxt-028/leaf-backlog.json"):
        block = ledgers[rel]
        for item in block.get("filed", []) + block.get("leaves", []) + block.get("backlog", []):
            if "leaf_id" in item:
                known_028.add(item["leaf_id"])
            elif "leaf" in item and isinstance(item["leaf"], dict):
                known_028.add(item["leaf"].get("leaf_id", item["leaf"].get("leaf_key", "")))
    for section in ("routing_leaves", "airwindows_leaves"):
        for role, lf in table[section].items():
            lid = lf.get("leaf_id")
            if lid and lid not in known_028:
                raise Refuse(f"table {section}[{role}] leaf {lid} not in committed SXT-028 artifacts")

    # ---- leaf/gate states (STALE detection) ---------------------------
    leaf_states = {}
    for lid, lf in table["leaves"].items():
        state, detail = evidence_state(repo, lf.get("evidence"))
        leaf_states[lid] = {
            "landed": bool(lf.get("landed")),
            "ready": bool(lf.get("landed")) and leaf_ready(lf),
            "stale": state == "STALE",
            "stale_detail": detail,
            "verification": lf.get("verification", {}),
        }
    gate_states = {}
    for gid, gf in table["gates"].items():
        state, detail = evidence_state(repo, gf.get("evidence"))
        gate_states[gid] = {
            "status": gf.get("status"),
            "stale": state == "STALE",
            "stale_detail": detail,
        }

    freeze_pass = gate_states["fidelity_freeze"]["status"] == "PASS" \
        and not gate_states["fidelity_freeze"]["stale"]
    voice_scope_all = voice_leaf.get("verified_scope") == "all"

    # ---- per-preset evaluation ----------------------------------------
    rows = []
    for e in graphs:
        p = e["p"]
        bank = e["b"]
        g = e.get("g", {})
        o = outcome_by_path[p]
        outcome = o["outcome"]
        codes = sorted(o.get("codes", []))

        reasons = set()
        normalized = "PASS" if e.get("st") == "normalized" else "FAIL"
        if normalized != "PASS":
            reasons.add("corpus_entry_not_normalized")

        # required FX (on AND not individually disabled), matching the
        # compile scan's notion of a required effect instance
        fxd = g.get("fxd", 0)
        required = []
        for fx in g.get("fx", []):
            if fx.get("on") == 1 and not (fxd & (1 << fx["i"])):
                required.append(fx)
        req_classes = []
        for fx in required:
            tn = fx["tn"]
            if tn == "Airwindows":
                req_classes.append(("Airwindows", str(fx.get("aw")), fx.get("awn", "")))
            else:
                req_classes.append((tn, None, None))
            if outcome == "compiled" and tn not in FX_BUNDLE_ALLOW:
                raise Refuse(
                    f"compiled-preset invariant broken: {p} requires "
                    f"out-of-bundle effect {tn} (scan said {outcome})"
                )

        if outcome == "rejected":
            compile_gate = "FAIL"
        elif outcome == "unresolved":
            compile_gate = "NO_VERDICT"
        else:
            compile_gate = "PASS"
        for c in codes:
            reasons.add(f"scan_code:{c}")

        # adapted classes (disclosed edits, committed records)
        adapted = False
        if outcome == "rejected" and set(codes) == {"polylimit_reduction_required"}:
            adapted = True
            reasons.add(
                "adapted_edit:polylimit_reduction_required(SXT-017-poly_gate-adapted_beyond_pool)"
            )
        elif "polylimit_reduction_required" in codes:
            reasons.add("also_requires_edit:polylimit_reduction_required")
        # SXT-026a (#48) resolved finding F-1: the adapted-by-substitution
        # status holds only while the voice leaf does NOT fixture-verify the
        # F-1 preset's original voice stage (fail-closed against the table).
        if p == f1_path and p not in fixture_verified:
            adapted = True
            reasons.add(
                "adapted_edit:sxt025_F1_voice_boundary(voice-stage-host-side;#48-blocks-original-voice)"
            )
        elif p == f1_path:
            reasons.add(
                "f1_resolved:SXT-026a-original-voice-stage(fixture-verified;#48)"
            )

        # voice leaf gate (leaf gates are reached only past the structural
        # compile verdict; rejected/unresolved rows keep their scan codes)
        evaluate_leaves = outcome == "compiled"
        vg = table["voice_leaf_key"]
        vs = leaf_states[vg]
        voice_gate = ""
        if evaluate_leaves:
            if vs["stale"]:
                voice_gate = "STALE"
                reasons.add(f"stale_leaf:{vg}({vs['stale_detail']})")
            elif voice_scope_all:
                voice_gate = "PASS" if vs["ready"] else "NO_VERDICT"
                if not vs["ready"]:
                    reasons.add("voice_leaf_verification_incomplete")
            elif p in fixture_verified:
                if vs["ready"]:
                    voice_gate = "PASS"
                else:
                    voice_gate = "NO_VERDICT"
                    v = vs["verification"]
                    if v.get("model_vs_reference") == "NO_VERDICT":
                        reasons.add(
                            "voice_leaf_caveat:model-vs-reference-NO_VERDICT"
                            "-vs-proposed(ledger-note;freeze-#12)"
                        )
                    else:
                        reasons.add("voice_leaf_verification_incomplete")
            elif p in overlap:
                voice_gate = "NOT_RUN"
                reasons.add(
                    "voice_scope_unfixture_verified:Quickspit(F-1-arithmetic-overlap-only)"
                )
            else:
                voice_gate = "NOT_RUN"
                reasons.add(
                    "voice_leaf_scope_exceeded:outside-fixture-verified-set"
                    "(SXT-026a;voice-family-leaves-#66-#77-backlog)"
                )

        # fx leaves gate (in-bundle classes only; out-of-bundle classes on
        # rejected/unresolved rows are already carried by their scan codes
        # and cannot change the headline)
        fx_gate = ""
        for tn, aw_id, awn in (req_classes if evaluate_leaves else []):
            if tn == "Airwindows":
                lf = table["airwindows_leaves"].get(aw_id)
                if lf is None:
                    fx_gate = worst(fx_gate, "NOT_RUN")
                    reasons.add(f"fx_leaf_unfiled:Airwindows:aw{aw_id}-{awn}")
                    continue
                lid = f"fx:Airwindows:{lf['leaf_id']}"
                landed = lf.get("landed", False)
                label = f"fx:Airwindows:aw{aw_id}-{awn}"
            else:
                lid = FX_TYPE_TO_LEAF.get(tn)
                if lid is None:
                    if outcome == "compiled":
                        raise Refuse(
                            f"compiled-preset invariant broken: {p} requires "
                            f"effect {tn} with no leaf mapping"
                        )
                    continue
                lf = table["leaves"][lid]
                landed = lf.get("landed", False)
                label = f"fx:{tn}"
            st = leaf_states.get(lid)
            if st is None:
                st = {
                    "landed": landed,
                    "ready": landed and leaf_ready(lf),
                    "stale": False,
                    "stale_detail": "",
                    "verification": lf.get("verification", {}),
                }
            if st["stale"]:
                fx_gate = worst(fx_gate, "STALE")
                reasons.add(f"stale_leaf:{label}({st['stale_detail']})")
            elif not st["landed"]:
                fx_gate = worst(fx_gate, "NOT_RUN")
                issue = lf.get("issue")
                extra = ""
                if lf.get("requires_freeze_decision"):
                    extra = "+needs-#12"
                if lf.get("filed", True) and issue:
                    reasons.add(f"leaf_not_landed:{label}(#{issue}{extra})")
                else:
                    reasons.add(
                        f"leaf_backlog_not_filed:{label}({lf.get('leaf_id','unfiled')})"
                    )
            elif not st["ready"]:
                fx_gate = worst(fx_gate, "FAIL")
                v = st["verification"]
                if v.get("rtl_vs_model") == "FAIL" and v.get("model_vs_reference") == "FAIL":
                    reasons.add(
                        f"leaf_unverified:{label}(#16-RTL-and-reference-FAIL->#12-decision)"
                    )
                else:
                    reasons.add(f"leaf_verification_incomplete:{label}")
            else:
                fx_gate = worst(fx_gate, "PASS")

        # FX-RNG gate (#122 / DR-0013). An effect whose sound depends on an
        # unpinnable RNG stream cannot have its ORIGINAL wet sound
        # reproduced, so the preset can never be reported supported. The
        # gate is BLOCKED, not FAIL: nothing was measured and found wrong --
        # a product-owner decision is outstanding (#12).
        rng_gate = ""
        rng_classes = rng_affected.get(p)
        if rng_classes and rng_gate_active:
            rng_gate = "BLOCKED"
            reasons.add(
                "rng_stream_unpinnable:" + "+".join(rng_classes)
                + "(DR-0013;#122->#12;coverage-reduction-published)"
            )
        elif rng_classes:
            reasons.add(
                "rng_gate_bypassed:negative-control-only(never-a-published-run)"
            )

        # wavetable leaf gate
        wt_gate = ""
        if evaluate_leaves and g.get("wta"):
            lid = "osc:Wavetable"
            st = leaf_states[lid]
            lf = table["leaves"][lid]
            if st["stale"]:
                wt_gate = "STALE"
                reasons.add(f"stale_leaf:{lid}({st['stale_detail']})")
            elif not st["ready"]:
                wt_gate = "NOT_RUN"
                reasons.add(
                    "leaf_partial:osc:Wavetable(SXT-026-s4-deep-mip-finding->#12)"
                )
            else:
                wt_gate = "PASS"

        # routing-form leaves gate
        rt_gate = ""
        for fx in (required if evaluate_leaves else []):
            role = fx["r"]
            if role in table["routing_roles_no_leaf_required"]:
                continue
            lf = table["routing_leaves"].get(role)
            if lf is None:
                rt_gate = worst(rt_gate, "NOT_RUN")
                reasons.add(f"routing_leaf_unfiled:{role}")
                continue
            st = leaf_states.get(f"routing:{lf['leaf_id']}")
            if st is None:
                st = {
                    "landed": lf.get("landed", False),
                    "ready": lf.get("landed", False) and leaf_ready(lf),
                    "stale": False,
                    "stale_detail": "",
                    "verification": lf.get("verification", {}),
                }
            if st["stale"]:
                rt_gate = worst(rt_gate, "STALE")
                reasons.add(f"stale_leaf:routing:{role}({st['stale_detail']})")
            elif not st["landed"]:
                rt_gate = worst(rt_gate, "NOT_RUN")
                reasons.add(f"leaf_not_landed:routing:{role}({lf['leaf_id']}#{lf.get('issue')})")
            elif not st["ready"]:
                rt_gate = worst(rt_gate, "FAIL")
                reasons.add(f"leaf_verification_incomplete:routing:{role}")
            else:
                rt_gate = worst(rt_gate, "PASS")

        # fidelity-contract gate (reached only past the structural gates)
        fid_gate = ""
        if outcome == "compiled":
            gst = gate_states["fidelity_freeze"]
            if gst["stale"]:
                fid_gate = "STALE"
                reasons.add(f"stale_gate:fidelity_freeze({gst['stale_detail']})")
            elif freeze_pass:
                fid_gate = "PASS"
            else:
                fid_gate = "BLOCKED"
                reasons.add("fidelity_freeze_pending:#12/SXT-017(budgets-PENDING-FREEZE)")

        # headline status (conservative conjunction)
        if adapted:
            headline = "adapted"
        elif outcome == "rejected":
            headline = "unsupported"
        elif outcome == "unresolved":
            headline = "unresolved"
        else:
            gates_ok = (
                normalized == "PASS"
                and voice_gate == "PASS"
                and fx_gate in ("", "PASS")
                and rng_gate == ""
                and wt_gate in ("", "PASS")
                and rt_gate in ("", "PASS")
                and fid_gate == "PASS"
            )
            headline = "supported" if gates_ok else "unresolved"
        if "STALE" in (voice_gate, fx_gate, wt_gate, rt_gate, fid_gate):
            if headline == "supported":
                raise Refuse(f"internal: stale gates cannot support {p}")
            reasons.add("stale_downgrade:never-reported-supported")

        # essentiality (listening) column -- separate from coverage
        ess = ""
        if slate_members.get(p):
            gst = gate_states["listening_labels"]
            ess = "STALE" if gst["stale"] else gst["status"]
            if gst["stale"]:
                reasons.add(f"stale_gate:listening_labels({gst['stale_detail']})")

        req_display = []
        for tn, aw_id, awn in req_classes:
            req_display.append(f"Airwindows:{awn}(aw{aw_id})" if aw_id else tn)

        rows.append({
            "bank": bank,
            "path": p,
            "blob_sha1": e["sha"],
            "headline_status": headline,
            "normalized": normalized,
            "compile_gate": compile_gate,
            "compile_codes": ";".join(codes),
            "voice_leaf_gate": voice_gate,
            "fx_leaves_gate": fx_gate,
            "fx_rng_gate": rng_gate,
            "wavetable_leaf_gate": wt_gate,
            "routing_leaves_gate": rt_gate,
            "fidelity_contract_gate": fid_gate,
            "essentiality_listening": ess,
            "fx_required": ";".join(sorted(req_display)),
            "b4_prediction": pred_by_path[p]["status"],
            "slates": ";".join(sorted(slate_members.get(p, []))),
            "reasons": ";".join(sorted(reasons)),
        })

    if len(rows) != len(graphs):
        raise Refuse("coverage row count disagrees with corpus size")

    # ---- outputs -------------------------------------------------------
    outdir = repo / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    csv_path = outdir / "per-preset.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    coverage = build_coverage(
        repo, rows, table, scan, pred, slates, sel, ledgers,
        leaf_states, gate_states, outcomes, by_path,
        input_pins=None if args.control_allow_input_drift else dict(STRUCTURAL_INPUTS),
        table_rel=table_rel,
        drift_allowed=args.control_allow_input_drift,
        rng_affected=rng_affected, rng_doc=rng_doc,
        rng_gate_active=rng_gate_active, rng_rel=rng_rel,
    )
    json_path = outdir / "coverage.json"
    with open(json_path, "w", newline="") as f:
        f.write(json.dumps(coverage, indent=1, sort_keys=True) + "\n")

    print(f"wrote {csv_path} ({len(rows)} rows)")
    print(f"wrote {json_path}")


def table_path_abs(repo: Path, table_rel: str) -> str:
    p = Path(table_rel)
    return str(p if p.is_absolute() else repo / p)


def build_coverage(repo, rows, table, scan, pred, slates, sel, ledgers,
                   leaf_states, gate_states, outcomes, by_path,
                   input_pins, table_rel, drift_allowed,
                   rng_affected, rng_doc, rng_gate_active, rng_rel):
    totals = Counter(r["headline_status"] for r in rows)
    per_bank = {b: Counter(r["headline_status"] for r in rows if r["bank"] == b)
                for b in BANKS}
    gates_per_bank = {
        b: {
            col: Counter(r[col] for r in rows if r["bank"] == b)
            for col in ("voice_leaf_gate", "fx_leaves_gate",
                        "wavetable_leaf_gate", "routing_leaves_gate",
                        "fidelity_contract_gate")
        }
        for b in BANKS
    }

    b4_matrix = Counter(
        (r["b4_prediction"], r["headline_status"]) for r in rows
    )
    disagreements = [
        {"path": r["path"], "b4_prediction": r["b4_prediction"],
         "headline": r["headline_status"], "compile_codes": r["compile_codes"]}
        for r in rows
        if r["b4_prediction"] == "supported" and r["headline_status"] != "supported"
        and r["headline_status"] != "unresolved"
    ]

    slate_cov = {}
    for rel in SLATES:
        s = slates[rel]
        name = s["artifact"]
        member_rows = [r for r in rows if f"{name}" in r["slates"].split(";")]
        sc = Counter(r["headline_status"] for r in member_rows)
        slate_cov[name] = {
            "prospective_only": True,
            "size": len(member_rows),
            "per_status": {k: sc.get(k, 0) for k in HEADLINE_STATUSES},
            "favorites_target_assessment": {
                "policy": "#8 profile: >=205 of 256 supported",
                "measured_supported": sc.get("supported", 0),
                "assessment": "NO_VERDICT",
                "blocked_by": [
                    "#8/#9 listening labels (essentiality UNVERIFIED)",
                    "#12/SXT-017 fidelity freeze (budgets PENDING-FREEZE)",
                    "landed-leaf gaps (see leaf_ledger and per-row reasons)",
                ],
                "note": (
                    "prospective proposal slates only; the frozen favorites "
                    "set does not exist; NO_VERDICT is the only honest "
                    "assessment and must never be read as PASS"
                ),
            },
        }

    # leaf ledger from the committed generator artifacts
    f27 = ledgers["reports/sxt-027/leaves-filed.json"]
    b27 = ledgers["reports/sxt-027/leaf-backlog.json"]
    f28 = ledgers["reports/sxt-028/leaves-filed.json"]
    b28 = ledgers["reports/sxt-028/leaf-backlog.json"]
    filed_leaves = (
        [{"source": "sxt-027", "issue": l["issue"], "leaf": l["leaf_key"],
          "sxt": l["sxt"], "title": l["title"],
          "recovery_basis_count": l["recovery_basis_count"]}
         for l in sorted(f27["leaves"], key=lambda x: x["issue"])]
        + [{"source": "sxt-028", "issue": l["issue_number"],
            "leaf": l["leaf_id"], "sxt": l["leaf_id"].replace("SXT-028", "028"),
            "title": l["title"],
            "recovery_basis_count": l.get("b4_scope_candidate_presets")}
           for l in sorted(f28["filed"], key=lambda x: x["issue_number"])]
    )
    backlog_027 = b27["leaves"]
    backlog_028 = [l for l in b28["leaves"] if not l.get("filed_now")]
    zero_basis_027 = sum(
        1 for l in backlog_027 if l.get("recovery", {}).get("basis_count", 0) == 0
    )

    leaf_ledger = {
        "leaves": {
            lid: {
                "landed": st["landed"],
                "support_ready": st["ready"],
                "evidence_state": "STALE" if st["stale"] else "OK",
                "verification": st["verification"],
            }
            for lid, st in sorted(leaf_states.items())
        },
        "gates": {
            gid: {
                "status": st["status"],
                "evidence_state": "STALE" if st["stale"] else "OK",
            }
            for gid, st in sorted(gate_states.items())
        },
        "filed_open_leaves": filed_leaves,
        "filed_open_count": len(filed_leaves),
        "first_class_voice_scope_leaf": {"issue": 48, "leaf": "SXT-026a"},
        "backlog_unfiled": {
            "sxt-027": {"count": len(backlog_027),
                        "zero_basis_deferred": zero_basis_027},
            "sxt-028": {"count": len(backlog_028)},
        },
        "note": (
            "filing a leaf issue is not progress on the claim ladder; only "
            "the leaves' own evidence records are"
        ),
    }

    open_decisions = [
        {"decision": "#12/SXT-017 freeze profile v1 (fidelity budgets)",
         "state": "OPEN",
         "blocks": "every supported promotion; all model-vs-reference verdicts are PENDING-FREEZE"},
        {"decision": "#16->#12 delay budget/exactness decision",
         "state": "OPEN",
         "blocks": "every preset requiring an active Delay slot (SXT-023 A1/A2 FAIL; routing of Chorus budgets too, SXT-028c)"},
        {"decision": "#8/#9 listening labels (essentiality / recovery ordering)",
         "state": "BLOCKED-on-human",
         "blocks": "favorites-target assessment (NO_VERDICT); leaf ordering; never a support gate"},
        {"decision": "#23 (SXT-030) FPGA + external memory qualification",
         "state": "OPEN",
         "blocks": "hardware playback claims; out of scope here (non-goal)"},
        {"decision": "#24 (SXT-031) gf180 implementation qualification",
         "state": "OPEN",
         "blocks": "silicon claims; out of scope here (non-goal)"},
        {"decision": "#122 -> #12 FX-modulation RNG exclusion "
                     "(decision record 0013)",
         "state": "RECORDED-CONTRACT-REVISION (owner ratification pending)",
         "blocks": f"{len(rng_affected)} corpus presets carrying an effect "
                   "whose sound depends on an unpinnable RNG stream; they "
                   "can never be reported supported while DR-0013 stands"},
    ]

    inputs_prov = {}
    if input_pins:
        for rel, pin in sorted(input_pins.items()):
            inputs_prov[rel] = {"role": "structural input (pinned)", "sha256": pin}
    inputs_prov[table_rel if Path(table_rel).is_absolute() else table_rel] = {
        "role": "leaf/gate verification table",
        "sha256": sha256_file(Path(table_rel) if Path(table_rel).is_absolute() else repo / table_rel),
    }
    for lid, lf in sorted(table["leaves"].items()):
        for item in lf.get("evidence", []):
            inputs_prov.setdefault(item["path"], {
                "role": f"evidence record for leaf {lid}",
                "sha256": item["sha256"],
            })
    for gid, gf in sorted(table["gates"].items()):
        for item in gf.get("evidence", []):
            inputs_prov.setdefault(item["path"], {
                "role": f"evidence record for gate {gid}",
                "sha256": item["sha256"],
            })

    agreement_links = [
        {"record": "reports/sxt-022/EVIDENCE.md",
         "subject": "dry voice slice (Attacky): RTL-vs-model exact; audio vs reference mixed vs [PROPOSED]"},
        {"record": "reports/sxt-023/EVIDENCE.md",
         "subject": "EQ leaf verified; Delay leaf FAIL (RTL + reference) with per-instance-state PASS; decision routed #16->#12"},
        {"record": "reports/sxt-024/EVIDENCE.md",
         "subject": "Reverb1 leaf: RTL exact; reference within [PROPOSED] budgets (one bounded finding)"},
        {"record": "reports/sxt-025/EVIDENCE.md",
         "subject": "integrated wet path diagnostic milestone; adapted-only (F-1); never counted toward coverage"},
        {"record": "reports/sxt-026/EVIDENCE.md",
         "subject": "wavetable leaf: RTL exact; reference PARTIAL (deep-mip finding, section 4)"},
    ]

    polylimit_rows = sum(
        1 for r in rows if "adapted_edit:polylimit_reduction_required(SXT-017-poly_gate-adapted_beyond_pool)" in r["reasons"]
    )

    return {
        "artifact": "sxt-029-coverage-v1",
        "issue": ISSUE,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "claim_scope": (
            "Claim counts, not a completion percentage. Headline statuses are "
            "the conservative conjunction of committed evidence: prediction "
            "(SXT-017) is not qualification; compiled (SXT-020) is not "
            "support; a verified leaf is not a supported preset; nothing here "
            "is a fidelity, musical-quality, FPGA/gf180mcu, or "
            "hardware-playback claim. Coverage counts are reported separately "
            "from agreement (fidelity metrics live only in the linked "
            "evidence records) and from listening outcomes (none exist)."
        ),
        "status_vocabulary": STATUS_VOCAB,
        "headline_rule": (
            "supported = normalized AND compiled AND every required leaf "
            "verified AND fidelity-freeze PASS; adapted = disclosed-edit "
            "classes (SXT-017 polylimit policy, SXT-025 F-1) and never "
            "counted toward supported; unsupported = structural compile "
            "rejection; unresolved = named missing step(s) in reasons"
        ),
        "denominators": {
            "corpus_total": len(rows),
            "per_bank": {b: sum(per_bank[b].values()) for b in BANKS},
            "favorites_slate": "256 per SXT-013 proposal slate (prospective only; no frozen favorites set exists)",
        },
        "totals": {k: totals.get(k, 0) for k in HEADLINE_STATUSES},
        "per_bank": {
            b: {k: per_bank[b].get(k, 0) for k in HEADLINE_STATUSES}
            for b in BANKS
        },
        "gate_columns_per_bank": gates_per_bank,
        "supported_set": {
            "count": totals.get("supported", 0),
            "composition": [
                {"path": r["path"], "bank": r["bank"]}
                for r in rows if r["headline_status"] == "supported"
            ],
            "note": (
                "empty today: the honest result. No compiled preset has a "
                "verified voice path (F-1: the only two in-slice presets "
                "carry no FX and only Attacky is fixture-verified), the "
                "Delay leaf is FAIL, wavetable is partial at deep mips, the "
                "fidelity freeze (#12) is open, and no listening record "
                "exists. 1,685 B4 'supported' predictions qualify nothing."
            ),
        },
        "favorites_slates": slate_cov,
        "fx_rng_exclusion": {
            "issue": "#122",
            "decision_record":
                "decision-records/0013-fx-modulation-rng-stream.md",
            "measurement": rng_rel,
            "gate_active": rng_gate_active,
            "gate_column": "fx_rng_gate",
            "gate_value": "BLOCKED",
            "rule": (
                "A preset carrying an effect whose sound depends on an RNG "
                "stream that cannot be pinned under the SXT-010 manifest can "
                "never be reported supported: its ORIGINAL wet sound cannot "
                "be reproduced or compared. This is a published coverage "
                "REDUCTION -- the denominators below are unchanged and no "
                "preset was removed from the corpus."
            ),
            "corpus_affected": len(rng_affected),
            "corpus_denominator": len(rows),
            "per_class": rng_doc["corpus"]["per_class"],
            "scopes": rng_doc["scopes"],
            "slates": {name: s["affected"]
                       for name, s in sorted(rng_doc["slates"].items())},
            "rows_affected_in_this_run": sum(
                1 for r in rows if r["fx_rng_gate"] == "BLOCKED"),
            "rows_that_would_be_supported_without_the_gate": (
                "measured by tools/coverage_negative_controls.py "
                "NC-RNG-EXCLUSION against the counterfactual verified world; "
                "not derivable from this published run, in which nothing is "
                "supported for independent reasons"
            ),
        },
        "leaf_ledger": leaf_ledger,
        "open_decisions": open_decisions,
        "reconciliation": {
            "b4_prediction_x_headline": {
                f"{a}|{b}": v for (a, b), v in sorted(b4_matrix.items())
            },
            "polylimit_reconciliation": (
                f"{polylimit_rows} presets are adapted by the pure "
                f"polylimit-rejection class; this equals the SXT-017 B4 "
                f"adapted-not-predicted count (164) and is a subset of the "
                f"SXT-020 rejection codes (212 carry the code, 48 of those "
                f"with additional blockers keep their harder headline)"
            ),
            "prediction_vs_qualification_examples": disagreements,
            "note": (
                "two B4-predicted-supported presets are structurally rejected "
                "by the compile scan (send_levels_not_exported, "
                "asset_unresolved): prediction is not qualification, which is "
                "why predictions never feed the headline"
            ),
        },
        "agreement_evidence_links": agreement_links,
        "agreement_separation_note": (
            "no fidelity metric is copied into this artifact; agreement "
            "lives in the linked evidence records only"
        ),
        "inputs": inputs_prov,
        "input_integrity": (
            "refuse-on-mismatch" if input_pins else
            "CONTROL MODE: structural pins skipped (--control-allow-input-drift); "
            "not valid for a published run"
        ),
        "negative_controls": {
            "transcript": "reports/coverage-v1/negative-controls.txt",
            "runner": "tools/coverage_negative_controls.py",
            "contract": (
                "a stale/silent leaf evidence must DOWNGRADE affected presets "
                "from supported to unresolved (never report them supported); "
                "any corpus entry without a coverage row must refuse the run "
                "fail-closed"
            ),
        },
        "determinism": (
            "same committed inputs produce byte-identical outputs (sorted "
            "keys, fixed column order, no clock)"
        ),
    }


if __name__ == "__main__":
    sys.exit(main())
