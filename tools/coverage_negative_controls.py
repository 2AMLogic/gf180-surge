#!/usr/bin/env python3
"""SXT-029 negative controls for the coverage pipeline (issue #22 acceptance).

Each control must demonstrably fail the behavior it targets; the control is
"healthy" when the PIPELINE behaves fail-closed. Runs entirely against /tmp
copies with a fixed root; published outputs are never touched.

NC-STALE-HASH   counterfactual world (declared synthetic table: all leaves
                landed+verified, freeze PASS) in which N presets are
                supported; then the fx:EQ leaf's evidence hash is pointed at
                a mismatching file. Required: every affected preset is
                DOWNGRADED supported -> unresolved with a stale reason, and
                none is ever reported supported.
NC-STALE-MISSING  same counterfactual, but the fx:EQ leaf's evidence file is
                missing entirely (silent-stub class). Same downgrade
                requirement; the pipeline must not crash or pass silently.
NC-ROW-MISSING  a corpus entry with no compile-scan outcome (row deleted from
                a /tmp scan copy). Required: the pipeline REFUSES (exit 2)
                and writes no outputs (fails closed).
NC-SHA-DISAGREE a graphs line whose blob sha disagrees with the scan copy.
                Required: REFUSE (exit 2).
NC-RNG-EXCLUSION (#122 / decision record 0013) same counterfactual world,
                with a DECLARED SYNTHETIC exclusion artifact that adds N
                presets which ARE supported in that world. Required: all N
                are downgraded supported -> unresolved carrying an
                `rng_stream_unpinnable:` reason and `fx_rng_gate=BLOCKED`;
                and re-running the same synthetic artifact with
                --control-ignore-rng-exclusion restores exactly those N,
                proving the RNG gate (not some other gate) caused the
                downgrade. A gate that changed nothing either way would be
                a broken control.
NC-INTEGRATION-* (#384) preset-scoped complete-wet integration gate. The
                counterfactual world above also carries a DECLARED SYNTHETIC
                integration ledger with one matching original-scope PASS
                record per compiled preset (and a synthetic frozen-policy
                pin on the freeze gate). Required: (a) the same
                component-PASS, freeze-PASS world with the COMMITTED ledger
                (no PASS record) supports nothing and every otherwise-ready
                row reads integration_gate=NOT_RUN -- freezing budgets and
                verifying leaves alone cannot promote a preset; the
                synthetic PASS ledger restores the supported set, so the
                gate is load-bearing; (b) holding every component gate PASS,
                each single-record mutation of one victim preset (record
                removed, evidence hash corrupted, blob identity changed,
                graph identity changed, placement/order identity changed,
                adapted-only record, dropped-tail FAIL, wrong-order FAIL,
                integrated RTL-vs-model FAIL, model-vs-reference FAIL,
                explicit blocker, unresolved interpretation, policy identity
                mismatch) removes exactly that preset from the supported set
                with the expected gate value and a named integration_
                reason; (c) a record relabelled from one preset onto another
                qualifies neither the other preset nor anything else.

Exit 0 iff every control is healthy; transcript goes to
reports/coverage-v1/negative-controls.txt.
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "oracle"))

import oracle_common as oc  # noqa: E402

sys.path.insert(0, str(REPO / "tools"))
import publish_coverage as pc  # noqa: E402

TOOL = REPO / "tools" / "publish_coverage.py"
NC_ROOT = Path("/tmp/sxt029-negative-controls")

PASS_VERIF = {"rtl_vs_model": "PASS", "model_vs_reference": "PASS"}

COPY_PATHS = [
    "corpus/normalized/graphs.jsonl",
    "model/integration/selection-scan.json",
    "reports/sxt-020/compile-corpus-scan.json",
    "reports/sxt-017/predictions/B4-broad.json",
    "reports/sxt-013/candidates/slate-256-balanced.json",
    "reports/sxt-013/candidates/slate-256-contributor-lean.json",
    "reports/sxt-013/candidates/slate-256-factory-lean.json",
    "reports/sxt-027/leaves-filed.json",
    "reports/sxt-027/leaf-backlog.json",
    "reports/sxt-028/leaves-filed.json",
    "reports/sxt-028/leaf-backlog.json",
    "reports/sxt-022/EVIDENCE.md",
    "reports/sxt-023/EVIDENCE.md",
    "reports/sxt-024/EVIDENCE.md",
    "reports/sxt-025/EVIDENCE.md",
    "reports/sxt-026/EVIDENCE.md",
    "reports/coverage-v1/leaf-verification.json",
    "reports/SXT-028-rng/artifacts/coverage-impact.json",
    "reports/coverage-v1/integration-ledger.json",
]


def run_tool(root: Path, outdir: Path, leaf_table: Path = None,
             allow_drift: bool = False, rng_exclusion: Path = None,
             ignore_rng: bool = False, integration_ledger: Path = None,
             tool: "Path | None" = None):
    cmd = [sys.executable, str(tool or TOOL), "--repo-root", str(root),
           "--outdir", str(outdir)]
    if leaf_table is not None:
        cmd += ["--leaf-table", str(leaf_table)]
    if allow_drift:
        cmd += ["--control-allow-input-drift"]
    if rng_exclusion is not None:
        cmd += ["--rng-exclusion", str(rng_exclusion)]
    if ignore_rng:
        cmd += ["--control-ignore-rng-exclusion"]
    if integration_ledger is not None:
        cmd += ["--integration-ledger", str(integration_ledger)]
    return subprocess.run(cmd, capture_output=True, text=True)


def read_rows(outdir: Path):
    with open(outdir / "per-preset.csv", newline="") as f:
        return list(csv.DictReader(f))


def ledger_for(table_path: Path) -> Path:
    """The synthetic integration ledger written next to a counterfactual
    table by counterfactual_table()."""
    return table_path.parent / "integration-ledger-synthetic.json"


def _stub_pin(directory: Path, name: str, body: str) -> dict:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return {"path": str(path), "sha256": oc.sha256_file(path)}


def synthetic_integration_ledger(directory: Path, root: Path = REPO) -> tuple:
    """Declared SYNTHETIC integration ledger (test fixture; never published).

    One original-scope PASS record per COMPILED corpus preset, carrying that
    preset's own bank/path/blob, normalized-graph sha256 and placement/order
    identity, all pins pointed at declared synthetic stub files. Returns
    (ledger_doc, frozen_policy_pin). The publisher refuses synthetic records
    unless the ledger is passed through --integration-ledger.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stub = "SYNTHETIC negative-control stub (#384); NEVER evidence.\n"
    policy = _stub_pin(directory, "frozen-policy-synthetic.txt",
                       "SYNTHETIC frozen fidelity policy (#384 control)\n")
    image = _stub_pin(directory, "patch-image-synthetic.txt", stub)
    fixture = _stub_pin(directory, "oracle-fixture-synthetic.txt", stub)
    seq = _stub_pin(directory, "event-sequence-synthetic.txt", stub)
    ev = _stub_pin(directory, "integrated-evidence-synthetic.txt", stub)
    scan = json.loads((REPO / "reports/sxt-020/compile-corpus-scan.json")
                      .read_text(encoding="utf-8"))
    compiled = {o["path"] for o in scan["outcomes"]
                if o["outcome"] == "compiled"}
    records = []
    with open(root / pc.GRAPH_DEFAULT, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e["p"] not in compiled:
                continue
            records.append({
                "record_id": "synthetic:" + e["sha"],
                "synthetic": True,
                "bank": e["b"], "path": e["p"], "blob_sha1": e["sha"],
                "qualification_scope": "original",
                "normalized_graph_sha256": pc.graph_sha256(e["g"]),
                "fx_placement_order": pc.fx_placement_order(e["g"]),
                "patch_image": dict(image),
                "oracle_fixture": dict(fixture),
                "event_sequence": dict(seq),
                "fidelity_policy": dict(policy),
                "evidence": [dict(ev)],
                "rtl_vs_model": "PASS",
                "model_vs_reference": "PASS",
                "aspects": {a: "PASS" for a in pc.INTEGRATION_ASPECTS},
                "blocker": None,
            })
    doc = {
        "artifact": "sxt-029-integration-ledger",
        "schema_version": pc.INTEGRATION_SCHEMA,
        "required_aspects": list(pc.INTEGRATION_ASPECTS),
        "synthetic_control": "NC-INTEGRATION scenario artifact; NEVER published",
        "records": records,
    }
    return doc, policy


def write_ledger(doc: dict, dest: Path) -> Path:
    dest.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return dest


def counterfactual_table(dest: Path, root: Path = REPO) -> Path:
    """Synthetic verified-world table (test fixture; never published).

    #384: the verified world also needs preset-scoped complete-wet
    integration evidence; a DECLARED SYNTHETIC ledger with a matching PASS
    record per compiled preset is written to ledger_for(dest), and the
    freeze gate is given a synthetic frozen-policy pin those records name.

    Evidence sha256 pins are REFRESHED from the on-disk files here. A
    synthetic *verified* world is by construction a world in which no
    evidence is stale, and refreshing makes these controls immune to
    ordinary drift between a committed EVIDENCE.md and the committed leaf
    table -- drift that would otherwise make every control fail for a reason
    unrelated to what it tests (observed at d6f9ced: six pins stale, the
    baseline world produced 0 supported presets and all controls failed).
    A missing evidence file is left alone so NC-STALE-MISSING still fires.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    table = json.loads((REPO / "reports/coverage-v1/leaf-verification.json")
                       .read_text(encoding="utf-8"))

    def refresh(block):
        for item in block.get("evidence") or []:
            p = REPO / item["path"]
            if p.is_file():
                item["sha256"] = oc.sha256_file(p)

    for section in ("leaves", "gates", "routing_leaves", "airwindows_leaves"):
        for block in table.get(section, {}).values():
            refresh(block)
    for lid, lf in table["leaves"].items():
        lf["landed"] = True
        lf["verification"] = dict(PASS_VERIF)
    table["leaves"][table["voice_leaf_key"]]["verified_scope"] = "all"
    for section in ("routing_leaves", "airwindows_leaves"):
        for lf in table[section].values():
            lf["landed"] = True
            lf["verification"] = dict(PASS_VERIF)
            lf["filed"] = True
    # #432: a readiness claim needs a nonempty valid evidence collection, so
    # the declared-synthetic verified world pins every claim that carries no
    # pin of its own to a committed record (synthetic; never published).
    default_pin = {"path": "reports/sxt-023/EVIDENCE.md",
                   "sha256": oc.sha256_file(REPO / "reports/sxt-023/EVIDENCE.md")}
    for section in ("leaves", "routing_leaves", "airwindows_leaves"):
        for block in table.get(section, {}).values():
            if not block.get("evidence"):
                block["evidence"] = [dict(default_pin)]
    table["gates"]["fidelity_freeze"]["status"] = "PASS"
    ledger, policy = synthetic_integration_ledger(dest.parent, root)
    table["gates"]["fidelity_freeze"]["frozen_policy"] = policy
    write_ledger(ledger, ledger_for(dest))
    dest.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return dest


def load_supported(outdir: Path):
    rows = read_rows(outdir)
    supported = {r["path"] for r in rows if r["headline_status"] == "supported"}
    eq = {r["path"] for r in rows
          if "EQ" in r["fx_required"].split(";") and r["compile_gate"] == "PASS"}
    by_path = {r["path"]: r for r in rows}
    return supported, eq, by_path


def assert_stale_downgrade(base: Path, tampered: Path, transcript) -> None:
    s0, eq0, by0 = load_supported(base)
    s1, _, by1 = load_supported(tampered)
    affected = eq0 & s0
    transcript.append(f"    baseline supported            : {len(s0)}")
    transcript.append(f"    affected (supported AND EQ)   : {len(affected)}")
    assert len(s0) > 0, "counterfactual world produced no supported presets"
    assert len(affected) > 0, "no EQ-carrying preset was supported in baseline"
    assert affected.isdisjoint(s1), "stale-affected preset still reported supported"
    assert s1 == s0 - affected, (
        f"downgrade inexact: dropped={len(s0 - s1)} expected={len(affected)} "
        f"gained={len(s1 - s0)}"
    )
    for p in sorted(affected):
        r = by1[p]
        assert r["headline_status"] == "unresolved", p
        assert "stale_leaf:" in r["reasons"], p
    cov = json.loads((tampered / "coverage.json").read_text(encoding="utf-8"))
    eq_state = cov["leaf_ledger"]["leaves"]["fx:EQ"]["evidence_state"]
    assert eq_state == "STALE", f"leaf ledger did not mark fx:EQ STALE: {eq_state}"
    transcript.append(f"    after tamper supported        : {len(s1)}")
    transcript.append(f"    downgraded supported->unresolved: {len(affected)} "
                      f"(all carry stale_leaf: reasons; fx:EQ evidence_state=STALE)")
    transcript.append("    PASS: affected presets downgraded; none reported supported")


def control_stale_hash(transcript) -> None:
    transcript.append("NC-STALE-HASH: evidence hash pointed at a mismatching file")
    base = NC_ROOT / "stale-hash" / "base"
    tamp = NC_ROOT / "stale-hash" / "tampered"
    cf = counterfactual_table(NC_ROOT / "stale-hash" / "counterfactual.json")
    r = run_tool(REPO, base, leaf_table=cf, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, r.stderr
    table = json.loads(cf.read_text(encoding="utf-8"))
    # point the EQ leaf's evidence hash at a *different committed file*
    mismatch = oc.sha256_file(REPO / "reports/sxt-024/EVIDENCE.md")
    table["leaves"]["fx:EQ"]["evidence"][0]["sha256"] = mismatch
    cf2 = NC_ROOT / "stale-hash" / "counterfactual-stale.json"
    cf2.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    r = run_tool(REPO, tamp, leaf_table=cf2, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, (
        f"STALE must downgrade (exit 0), not refuse: rc={r.returncode} {r.stderr}"
    )
    assert_stale_downgrade(base, tamp, transcript)


def control_stale_missing(transcript) -> None:
    transcript.append("NC-STALE-MISSING: silent stub (evidence file absent)")
    base = NC_ROOT / "stale-missing" / "base"
    tamp = NC_ROOT / "stale-missing" / "tampered"
    cf = counterfactual_table(NC_ROOT / "stale-missing" / "counterfactual.json")
    r = run_tool(REPO, base, leaf_table=cf, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, r.stderr
    table = json.loads(cf.read_text(encoding="utf-8"))
    table["leaves"]["fx:EQ"]["evidence"] = [
        {"path": str(NC_ROOT / "stale-missing" / "evidence-absent.md"),
         "sha256": "0" * 64}
    ]
    cf2 = NC_ROOT / "stale-missing" / "counterfactual-stale.json"
    cf2.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    r = run_tool(REPO, tamp, leaf_table=cf2, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, (
        f"missing evidence must downgrade (exit 0), not crash/refuse: "
        f"rc={r.returncode} {r.stderr}"
    )
    assert_stale_downgrade(base, tamp, transcript)


RNG_EXCLUSION_REL = "reports/SXT-028-rng/artifacts/coverage-impact.json"
NC_RNG_SYNTHETIC_N = 5


def control_rng_exclusion(transcript) -> None:
    transcript.append("NC-RNG-EXCLUSION: FX-RNG exclusion gate (#122/DR-0013)")
    base = NC_ROOT / "rng-exclusion" / "base"
    tamp = NC_ROOT / "rng-exclusion" / "tampered"
    bypass = NC_ROOT / "rng-exclusion" / "bypassed"
    cf = counterfactual_table(NC_ROOT / "rng-exclusion" / "counterfactual.json")

    r = run_tool(REPO, base, leaf_table=cf, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, r.stderr
    s0, _, by0 = load_supported(base)
    assert len(s0) > NC_RNG_SYNTHETIC_N, \
        "counterfactual world produced too few supported presets"

    # Declared SYNTHETIC exclusion artifact: the committed one plus N presets
    # that ARE supported in the counterfactual world. Never published.
    doc = json.loads((REPO / RNG_EXCLUSION_REL).read_text(encoding="utf-8"))
    victims = sorted(s0)[:NC_RNG_SYNTHETIC_N]
    rows = {r0["path"]: r0 for r0 in doc["affected_presets"]}
    for p in victims:
        rows[p] = {
            "path": p, "bank": by0[p]["bank"], "census_blob_sha1":
                by0[p]["blob_sha1"],
            "classes": [{"fx_type_name": "SYNTHETIC-CONTROL", "slot": 0,
                         "role": "ains1", "generator": "synthetic",
                         "why": "negative control only; never published"}],
        }
    doc["affected_presets"] = [rows[p] for p in sorted(rows)]
    doc["corpus"]["affected_presets"] = len(rows)
    doc["synthetic_control"] = (
        "NC-RNG-EXCLUSION scenario artifact; NEVER a published measurement")
    synth = NC_ROOT / "rng-exclusion" / "exclusion-synthetic.json"
    synth.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                     encoding="utf-8")

    r = run_tool(REPO, tamp, leaf_table=cf, rng_exclusion=synth,
                 integration_ledger=ledger_for(cf))
    assert r.returncode == 0, f"gate must downgrade, not refuse: {r.stderr}"
    s1, _, by1 = load_supported(tamp)

    r = run_tool(REPO, bypass, leaf_table=cf, rng_exclusion=synth,
                 ignore_rng=True, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, r.stderr
    s2, _, _ = load_supported(bypass)

    transcript.append(f"    baseline supported                  : {len(s0)}")
    transcript.append(f"    synthetic exclusions added          : "
                      f"{len(victims)}")
    transcript.append(f"    after gate supported                : {len(s1)}")
    assert set(victims).isdisjoint(s1), \
        "an RNG-excluded preset was still reported supported"
    assert s1 == s0 - set(victims), (
        f"downgrade inexact: dropped={len(s0 - s1)} "
        f"expected={len(victims)} gained={len(s1 - s0)}"
    )
    for p in victims:
        row = by1[p]
        assert row["headline_status"] == "unresolved", p
        assert row["fx_rng_gate"] == "BLOCKED", p
        assert "rng_stream_unpinnable:" in row["reasons"], p
    transcript.append(f"    downgraded supported->unresolved    : "
                      f"{len(victims)} (all carry fx_rng_gate=BLOCKED and an "
                      f"rng_stream_unpinnable: reason)")
    assert s2 == s0, (
        "the gate is not load-bearing: bypassing it did not restore the "
        f"downgraded presets (bypassed={len(s2)} baseline={len(s0)})"
    )
    transcript.append(f"    with --control-ignore-rng-exclusion : {len(s2)} "
                      f"(exactly the baseline -- the RNG gate, and nothing "
                      f"else, caused the downgrade)")
    cov = json.loads((tamp / "coverage.json").read_text(encoding="utf-8"))
    assert cov["denominators"]["corpus_total"] == 3561, \
        "the exclusion moved a denominator (it must publish a reduction)"
    assert cov["fx_rng_exclusion"]["gate_active"] is True
    transcript.append("    denominator unchanged               : 3561 "
                      "(reduction published, nothing dropped)")
    transcript.append("    PASS: affected presets downgraded; gate proven "
                      "load-bearing; denominator preserved")


def make_tmp_repo(tag: str) -> Path:
    root = NC_ROOT / tag / "repo"
    for rel in COPY_PATHS:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dst)
    return root


def control_row_missing(transcript) -> None:
    transcript.append("NC-ROW-MISSING: corpus entry with no coverage row")
    root = make_tmp_repo("row-missing")
    scan_rel = "reports/sxt-020/compile-corpus-scan.json"
    scan = json.loads((root / scan_rel).read_text(encoding="utf-8"))
    victim = "resources/data/patches_factory/Basses/Attacky.fxp"
    scan["outcomes"] = [o for o in scan["outcomes"] if o["path"] != victim]
    (root / scan_rel).write_text(
        json.dumps(scan, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    outdir = NC_ROOT / "row-missing" / "out"
    r = run_tool(root, outdir, allow_drift=True)
    assert r.returncode == 2, f"expected refuse (exit 2), got {r.returncode}"
    assert "no coverage row" in r.stderr, r.stderr
    assert not (outdir / "per-preset.csv").exists(), "outputs written despite refuse"
    transcript.append(f"    REFUSED as required: {r.stderr.strip()[:120]}")
    transcript.append("    PASS: fail-closed, no outputs written")


def control_sha_disagree(transcript) -> None:
    transcript.append("NC-SHA-DISAGREE: graphs blob sha disagrees with scan")
    root = make_tmp_repo("sha-disagree")
    graphs_rel = "corpus/normalized/graphs.jsonl"
    lines = (root / graphs_rel).read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["sha"] = ("0" if first["sha"][0] != "0" else "1") + first["sha"][1:]
    lines[0] = json.dumps(first, sort_keys=True)
    (root / graphs_rel).write_text("\n".join(lines) + "\n", encoding="utf-8")
    outdir = NC_ROOT / "sha-disagree" / "out"
    r = run_tool(root, outdir, allow_drift=True)
    assert r.returncode == 2, f"expected refuse (exit 2), got {r.returncode}"
    assert "sha disagreement" in r.stderr, r.stderr
    assert not (outdir / "per-preset.csv").exists(), "outputs written despite refuse"
    transcript.append(f"    REFUSED as required: {r.stderr.strip()[:120]}")
    transcript.append("    PASS: fail-closed, no outputs written")


HB = "resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp"
F1_SUBST = "adapted_edit:sxt025_F1_voice_boundary"


def control_f1_original_stage(transcript) -> None:
    transcript.append("NC-F1-ORIGINAL-STAGE: SXT-026a fixture verification "
                      "removed -> substitution-based adapted class restored (#353)")
    base = NC_ROOT / "f1-original-stage" / "base"
    tamp = NC_ROOT / "f1-original-stage" / "tampered"
    committed = REPO / "reports/coverage-v1/leaf-verification.json"
    r = run_tool(REPO, base, leaf_table=committed)
    assert r.returncode == 0, r.stderr
    b = read_rows(base)
    hb = {x["path"]: x for x in b}[HB]
    assert F1_SUBST not in hb["reasons"] and hb["headline_status"] != "adapted", \
        "committed ledger still carries the substitution-based adapted class"
    table = json.loads(committed.read_text(encoding="utf-8"))
    leaf = table["leaves"][table["voice_leaf_key"]]
    leaf["fixture_verified_paths"] = [
        x for x in leaf["fixture_verified_paths"] if x != HB]
    cf = NC_ROOT / "f1-original-stage" / "ledger-no-hb.json"
    cf.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                  encoding="utf-8")
    r = run_tool(REPO, tamp, leaf_table=cf)
    assert r.returncode == 0, r.stderr
    t = {x["path"]: x for x in read_rows(tamp)}[HB]
    assert t["headline_status"] == "adapted" and F1_SUBST in t["reasons"], \
        f"substitution class not restored: {t['headline_status']}"
    transcript.append(f"    committed ledger : {hb['headline_status']} "
                      "(no substitution reason)")
    transcript.append(f"    fixture removed  : {t['headline_status']} "
                      "(adapted_edit:sxt025_F1_voice_boundary restored)")
    transcript.append("    PASS: control demonstrably restores the old class")


def control_voice_pin_corrupt(transcript) -> None:
    transcript.append("NC-VOICE-PIN-CORRUPT: newly selected voice leaf "
                      "evidence pin corrupted -> no support-ready gate (#353)")
    base = NC_ROOT / "voice-pin-corrupt" / "base"
    tamp = NC_ROOT / "voice-pin-corrupt" / "tampered"
    cf = counterfactual_table(NC_ROOT / "voice-pin-corrupt" / "cf.json")
    r = run_tool(REPO, base, leaf_table=cf, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, r.stderr
    s0, _, _ = load_supported(base)
    assert len(s0) > 0, "counterfactual world produced no supported presets"
    table = json.loads(cf.read_text(encoding="utf-8"))
    key = table["voice_leaf_key"]
    assert key == "voice:sine-fm-lp24-v2", key
    ev = table["leaves"][key]["evidence"]
    ev[-1]["sha256"] = "0" * 64
    cf2 = NC_ROOT / "voice-pin-corrupt" / "cf-corrupt.json"
    cf2.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    r = run_tool(REPO, tamp, leaf_table=cf2, integration_ledger=ledger_for(cf))
    assert r.returncode == 0, r.stderr
    s1, _, _ = load_supported(tamp)
    rows = read_rows(tamp)
    assert len(s1) == 0, f"{len(s1)} presets supported with corrupt voice pin"
    stale = [x for x in rows if x["voice_leaf_gate"] == "STALE"]
    assert stale and all("stale_leaf:" + key in x["reasons"] for x in stale)
    transcript.append(f"    baseline supported : {len(s0)}")
    transcript.append(f"    corrupt-pin supported: {len(s1)} "
                      f"({len(stale)} rows voice_leaf_gate=STALE)")
    transcript.append("    PASS: corrupt pin cannot produce a support-ready gate")


def _victims(by0: dict, s0: set, ledger: dict) -> tuple:
    """Deterministic victim V (supported, >= 2 distinct required effect
    instances so a placement/order permutation is observable) and a second
    supported preset W for the cross-preset control."""
    recs = {r["path"]: r for r in ledger["records"]}
    multi = [p for p in sorted(s0)
             if len(set(recs[p]["fx_placement_order"])) >= 2]
    assert multi, "no supported preset with >= 2 effect instances"
    v = multi[0]
    others = [p for p in sorted(s0) if p != v and by0[p]["blob_sha1"]
              != by0[v]["blob_sha1"]]
    assert others, "no second supported preset"
    return v, others[0]


def _mutations(v_rec: dict, other_rec: dict) -> list:
    """(name, mutate(record) -> record-or-None, expected gate, reason)."""
    def m_order(r):
        r["fx_placement_order"] = list(reversed(r["fx_placement_order"]))
        return r

    def m_graph(r):
        r["normalized_graph_sha256"] = other_rec["normalized_graph_sha256"]
        return r

    def m_blob(r):
        r["blob_sha1"] = other_rec["blob_sha1"]
        return r

    def m_hash(r):
        r["evidence"][0]["sha256"] = "0" * 64
        return r

    def m_set(key, value):
        def f(r):
            r[key] = value
            return r
        return f

    def m_aspect(a, st):
        def f(r):
            r["aspects"][a] = st
            return r
        return f

    def m_adapted(r):
        r["qualification_scope"] = "adapted"
        r["adaptation"] = "SYNTHETIC control: generic reverb substituted"
        return r

    def m_policy(r):
        r["fidelity_policy"] = dict(r["evidence"][0])
        return r

    return [
        ("record-removed", lambda r: None, "NOT_RUN",
         "integration_not_run:"),
        ("evidence-hash-corrupted", m_hash, "STALE",
         "integration_evidence_stale:"),
        ("preset-identity-changed", m_blob, "NOT_RUN",
         "integration_preset_identity_mismatch:"),
        ("graph-identity-changed", m_graph, "STALE",
         "integration_graph_identity_mismatch:"),
        ("order-identity-changed", m_order, "STALE",
         "integration_order_identity_mismatch:"),
        ("adapted-only-record", m_adapted, "NOT_RUN",
         "integration_adapted_only:"),
        ("dropped-tail-FAIL", m_aspect("tails", "FAIL"), "FAIL",
         "integration_aspect_tails_FAIL:"),
        ("wrong-order-FAIL", m_aspect("routing_order", "FAIL"), "FAIL",
         "integration_aspect_routing_order_FAIL:"),
        ("shared-instance-state-FAIL", m_aspect("per_instance_state", "FAIL"),
         "FAIL", "integration_aspect_per_instance_state_FAIL:"),
        ("rtl-vs-model-FAIL", m_set("rtl_vs_model", "FAIL"), "FAIL",
         "integration_rtl_vs_model_FAIL:"),
        ("model-vs-reference-FAIL", m_set("model_vs_reference", "FAIL"),
         "FAIL", "integration_model_vs_reference_FAIL:"),
        ("explicit-blocker", m_set("blocker", "SYNTHETIC control blocker"),
         "BLOCKED", "integration_blocked:"),
        ("unresolved-interpretation",
         m_set("model_vs_reference", "NO_VERDICT"), "NO_VERDICT",
         "integration_model_vs_reference_NO_VERDICT:"),
        ("policy-identity-mismatch", m_policy, "STALE",
         "integration_policy_identity_mismatch:"),
    ]


def control_integration_gate(transcript) -> None:
    transcript.append("NC-INTEGRATION: preset-scoped complete-wet integration "
                      "gate (#384)")
    root = NC_ROOT / "integration"
    cf = counterfactual_table(root / "counterfactual.json")
    synth = ledger_for(cf)
    ledger = json.loads(synth.read_text(encoding="utf-8"))

    # (a) load-bearing: component PASS + freeze PASS, committed ledger (no
    # PASS record) -> nothing supported; synthetic PASS ledger -> restored.
    base = root / "base"
    r = run_tool(REPO, base, leaf_table=cf, integration_ledger=synth)
    assert r.returncode == 0, r.stderr
    s0, _, by0 = load_supported(base)
    assert len(s0) > 0, "counterfactual world produced no supported presets"
    for p in s0:
        assert by0[p]["integration_gate"] == "PASS", p
    no_int = root / "committed-ledger"
    r = run_tool(REPO, no_int, leaf_table=cf)
    assert r.returncode == 0, r.stderr
    s_none, _, by_none = load_supported(no_int)
    assert len(s_none) == 0, (
        f"{len(s_none)} presets supported with component gates and freeze "
        "PASS but no matching integration PASS record")
    for p in s0:
        row = by_none[p]
        assert row["integration_gate"] in ("NOT_RUN", "NO_VERDICT"), \
            (p, row["integration_gate"])
        assert row["headline_status"] == "unresolved", p
        for col in ("voice_leaf_gate", "fidelity_contract_gate"):
            assert row[col] == "PASS", (p, col, row[col])
        assert "integration_" in row["reasons"], p
    not_run = sum(1 for p in s0 if by_none[p]["integration_gate"] == "NOT_RUN")
    transcript.append(f"    component+freeze PASS, synthetic PASS ledger : "
                      f"{len(s0)} supported")
    transcript.append(f"    same world, committed ledger (no PASS record): "
                      f"{len(s_none)} supported ({not_run} of the {len(s0)} "
                      f"rows integration_gate=NOT_RUN; component gates still "
                      f"PASS)")
    transcript.append("    -> freezing budgets + verifying leaves alone "
                      "promotes nothing; the integration gate is load-bearing")

    # (b) single-record mutations of one victim, component evidence held PASS
    v, w = _victims(by0, s0, ledger)
    idx = {rec["path"]: i for i, rec in enumerate(ledger["records"])}
    transcript.append(f"    victim V: {v} "
                      f"({'|'.join(ledger['records'][idx[v]]['fx_placement_order'])})")
    for name, mutate, want, reason in _mutations(
            ledger["records"][idx[v]], ledger["records"][idx[w]]):
        doc = json.loads(json.dumps(ledger))
        rec = mutate(doc["records"][idx[v]])
        if rec is None:
            del doc["records"][idx[v]]
        led = write_ledger(doc, root / f"ledger-{name}.json")
        out = root / f"out-{name}"
        r = run_tool(REPO, out, leaf_table=cf, integration_ledger=led)
        assert r.returncode == 0, f"{name}: must downgrade, not refuse: {r.stderr}"
        s1, _, by1 = load_supported(out)
        row = by1[v]
        assert v not in s1, f"{name}: victim still supported"
        assert s1 == s0 - {v}, (
            f"{name}: inexact: dropped={len(s0 - s1)} gained={len(s1 - s0)}")
        assert row["headline_status"] == "unresolved", (name, row["headline_status"])
        assert row["integration_gate"] == want, (name, row["integration_gate"])
        assert reason in row["reasons"], (name, row["reasons"])
        for col in ("voice_leaf_gate", "fidelity_contract_gate"):
            assert row[col] == "PASS", (name, col, row[col])
        assert row["fx_leaves_gate"] in ("", "PASS"), name
        assert row["routing_leaves_gate"] in ("", "PASS"), name
        transcript.append(f"    {name:<28}: V {row['integration_gate']:<10} "
                          f"supported {len(s1)} (= baseline - V) "
                          f"reason {reason}")

    # (c) a record for one preset cannot qualify another: V's PASS record
    # relabelled onto W's path (W's own record removed).
    doc = json.loads(json.dumps(ledger))
    moved = doc["records"][idx[v]]
    moved = json.loads(json.dumps(moved))
    moved["record_id"] = "synthetic:relabelled-V-onto-W"
    moved["path"] = w
    doc["records"] = [r0 for r0 in doc["records"] if r0["path"] != w]
    doc["records"].append(moved)
    led = write_ledger(doc, root / "ledger-cross-preset.json")
    out = root / "out-cross-preset"
    r = run_tool(REPO, out, leaf_table=cf, integration_ledger=led)
    assert r.returncode == 0, r.stderr
    s1, _, by1 = load_supported(out)
    assert w not in s1, "a record for V qualified W"
    assert s1 == s0 - {w}, (
        f"cross-preset: dropped={len(s0 - s1)} gained={len(s1 - s0)}")
    assert by1[w]["integration_gate"] == "NOT_RUN", by1[w]["integration_gate"]
    assert "integration_preset_identity_mismatch:" in by1[w]["reasons"]
    transcript.append(f"    {'cross-preset (V record on W)':<28}: W "
                      f"{by1[w]['integration_gate']:<10} supported {len(s1)} "
                      f"(= baseline - W) reason "
                      f"integration_preset_identity_mismatch:")

    # (d) synthetic records are refused outside the control override
    tmp = make_tmp_repo("integration-synthetic-refused")
    shutil.copyfile(synth, tmp / "reports/coverage-v1/integration-ledger.json")
    out = root / "out-synthetic-refused"
    r = run_tool(tmp, out, allow_drift=True)
    assert r.returncode == 2, f"expected refuse, got {r.returncode}"
    assert "SYNTHETIC" in r.stderr, r.stderr
    assert not (out / "per-preset.csv").exists()
    transcript.append("    synthetic ledger as the default input  : REFUSED "
                      "(exit 2; synthetic records never valid in a published "
                      "run)")
    transcript.append("    PASS: integration gate load-bearing; every "
                      "mutation prevents support with a named reason; no "
                      "cross-preset qualification")


# ----------------------------------------------- evidence-backed readiness
# (#432) Every readiness claim -- ordinary leaf, routing leaf, Airwindows
# leaf, qualification gate -- must resolve a nonempty collection of valid
# evidence pins. The scenarios below are written once and run both against
# the real publisher (must hold) and against temporary mutated copies that
# restore the pre-#432 shortcuts (must FAIL a TARGETED assertion).

TARGETED = "TARGETED"


def _write_json(doc: dict, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return dest


def _targeted(cond, msg: str) -> None:
    if not cond:
        raise AssertionError(f"{TARGETED}: {msg}")


def _rows_by_path(outdir: Path) -> dict:
    return {r["path"]: r for r in read_rows(outdir)}


def _graphs() -> dict:
    out = {}
    with open(REPO / "corpus/normalized/graphs.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                out[e["p"]] = e
    return out


def scenario_ordinary(root: Path, tool: Path, transcript) -> None:
    """EQ in the all-other-gates-PASS world: evidence member absent / null /
    empty list must leave NO reached gate ready; malformed shapes refuse
    before any output is written."""
    cf = counterfactual_table(root / "counterfactual.json")
    led = ledger_for(cf)
    base = root / "base"
    r = run_tool(REPO, base, leaf_table=cf, integration_ledger=led, tool=tool)
    assert r.returncode == 0, r.stderr
    b = _rows_by_path(base)
    s0 = {p for p, x in b.items() if x["headline_status"] == "supported"}
    affected = {p for p, x in b.items()
                if "EQ" in x["fx_required"].split(";")
                and x["fx_leaves_gate"] == "PASS"}
    assert s0 and affected & s0, "synthetic world has no reached EQ victims"
    transcript.append(f"    ordinary leaf fx:EQ: baseline supported={len(s0)}; "
                      f"reached EQ gates (PASS)={len(affected)}; "
                      f"supported victims={len(affected & s0)}")
    table = json.loads(cf.read_text(encoding="utf-8"))
    for mode in ("absent", "null", "empty"):
        t = json.loads(json.dumps(table))
        if mode == "absent":
            del t["leaves"]["fx:EQ"]["evidence"]
        elif mode == "null":
            t["leaves"]["fx:EQ"]["evidence"] = None
        else:
            t["leaves"]["fx:EQ"]["evidence"] = []
        tp = _write_json(t, root / f"cf-{mode}.json")
        out = root / f"out-{mode}"
        r = run_tool(REPO, out, leaf_table=tp, integration_ledger=led, tool=tool)
        assert r.returncode == 0, f"{mode}: must downgrade, not crash: {r.stderr}"
        rows = _rows_by_path(out)
        s1 = {p for p, x in rows.items() if x["headline_status"] == "supported"}
        still = sorted(p for p in affected if rows[p]["fx_leaves_gate"] == "PASS")
        _targeted(not still,
                  f"evidence {mode}: {len(still)}/{len(affected)} reached "
                  "EQ gates remain PASS on an evidence-free claim")
        for p in affected:
            _targeted("leaf_evidence_missing:fx:EQ" in rows[p]["reasons"],
                      f"evidence {mode}: {p} has no named reason")
        _targeted(s1 == s0 - affected,
                  f"evidence {mode}: supported set not exactly baseline - "
                  "affected")
        cov = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
        _targeted(cov["leaf_ledger"]["leaves"]["fx:EQ"]["evidence_state"]
                  == "MISSING", f"evidence {mode}: ledger not MISSING")
        transcript.append(f"    evidence {mode:<6}: reached EQ gates "
                          f"{sorted({rows[p]['fx_leaves_gate'] for p in affected})} "
                          f"supported {len(s1)} (= baseline - {len(affected & s0)})"
                          " reason leaf_evidence_missing:fx:EQ")
    for name, bad in (("string", "oops"), ("bad-item", [{"path": 1}]),
                      ("short-sha", [{"path": "x", "sha256": "ab"}])):
        t = json.loads(json.dumps(table))
        t["leaves"]["fx:EQ"]["evidence"] = bad
        tp = _write_json(t, root / f"cf-bad-{name}.json")
        out = root / f"out-bad-{name}"
        r = run_tool(REPO, out, leaf_table=tp, integration_ledger=led, tool=tool)
        assert r.returncode == 2, f"malformed {name}: rc={r.returncode}"
        assert not (out / "per-preset.csv").exists(), name
        assert not (out / "coverage.json").exists(), name
    transcript.append("    malformed evidence (string / bad item / short sha): "
                      "REFUSED exit 2, no output written")


def _affected_for(section: str, key: str, b: dict, graphs: dict) -> set:
    out = set()
    for p, x in b.items():
        if x["compile_gate"] != "PASS":
            continue
        if section == "routing_leaves":
            col = x["routing_leaves_gate"]
            g = graphs[p]["g"]
            fxd = g.get("fxd", 0)
            if col and any(fx["r"] == key and fx.get("on") == 1
                           and not (fxd & (1 << fx["i"]))
                           for fx in g.get("fx", [])):
                out.add(p)
        else:
            if x["fx_leaves_gate"] and f"(aw{key})" in x["fx_required"]:
                out.add(p)
    return out


AW_MIRROR_KEY = "49"
AW_MIRROR_N = 6


def _aw_mirror(dest: Path, base_rows: dict, graphs: dict) -> Path:
    """Symlink mirror of the repo whose corpus/normalized/graphs.jsonl has an
    Airwindows slot (streamed id AW_MIRROR_KEY) enabled on the first
    AW_MIRROR_N supported presets that have an Off slot. Synthetic."""
    chosen = {}
    for p in sorted(base_rows):
        if len(chosen) == AW_MIRROR_N:
            break
        if base_rows[p]["headline_status"] != "supported":
            continue
        for fx in graphs[p]["g"].get("fx", []):
            if fx.get("on") == 0 and fx.get("tn") == "Off":
                chosen[p] = fx["i"]
                break
    assert chosen, "no supported preset with an Off slot for the AW mirror"
    dest.mkdir(parents=True)
    for child in REPO.iterdir():
        if child.name in (".git", ".loom", "corpus"):
            continue
        (dest / child.name).symlink_to(child)
    (dest / "corpus/normalized").mkdir(parents=True)
    for child in (REPO / "corpus").iterdir():
        if child.name != "normalized":
            (dest / "corpus" / child.name).symlink_to(child)
    for child in (REPO / "corpus/normalized").iterdir():
        if child.name != "graphs.jsonl":
            (dest / "corpus/normalized" / child.name).symlink_to(child)
    lines = []
    with open(REPO / pc.GRAPH_DEFAULT, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e["p"] in chosen:
                for fx in e["g"]["fx"]:
                    if fx["i"] == chosen[e["p"]]:
                        fx.update({"on": 1, "tn": "Airwindows",
                                   "aw": int(AW_MIRROR_KEY),
                                   "awn": "SyntheticAW"})
            lines.append(json.dumps(e, sort_keys=True, separators=(",", ":")))
    (dest / pc.GRAPH_DEFAULT).write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")
    return dest


def scenario_section(root: Path, tool: Path, section: str, mapping: str,
                     transcript) -> None:
    """Routing / Airwindows leaf in the synthetic world, made ready with a
    valid pin (section-local record, or a declared canonical mapping), then
    its pin is corrupted / its file removed."""
    assert section in ("routing_leaves", "airwindows_leaves")
    assert mapping in ("local", "canonical")
    cf = counterfactual_table(root / "counterfactual.json")
    led = ledger_for(cf)
    table = json.loads(cf.read_text(encoding="utf-8"))
    graphs = _graphs()
    base0 = root / "base0"
    rp, drift = REPO, False
    r = run_tool(REPO, base0, leaf_table=cf, integration_ledger=led, tool=tool)
    assert r.returncode == 0, r.stderr
    b0 = _rows_by_path(base0)
    if section == "airwindows_leaves":
        # No compiled corpus preset requires an Airwindows effect, so no
        # Airwindows gate is reachable in the real corpus. Reach it in a
        # DECLARED SYNTHETIC mirror whose graph input enables an Airwindows
        # slot on a few supported presets (scratch only; never published).
        rp, drift = _aw_mirror(root / "mirror", b0, graphs), True
        cf = counterfactual_table(root / "cf-aw" / "counterfactual.json", rp)
        led = ledger_for(cf)
        table = json.loads(cf.read_text(encoding="utf-8"))
        graphs = {}
        with open(rp / pc.GRAPH_DEFAULT, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    graphs[e["p"]] = e
        base0 = root / "base0-aw"
        r = run_tool(rp, base0, leaf_table=cf, integration_ledger=led,
                     allow_drift=True, tool=tool)
        assert r.returncode == 0, r.stderr
        b0 = _rows_by_path(base0)
    s_all = {p for p, x in b0.items() if x["headline_status"] == "supported"}
    key = None
    for k in sorted(table[section]):
        aff = _affected_for(section, k, b0, graphs)
        if aff & s_all and (set(b0) - aff):
            key = k
            break
    assert key is not None, f"no {section} entry reaches a supported victim"
    label = f"{section}[{key}] ({mapping})"
    ev = root / "evidence-record.md"
    ev.write_text(f"synthetic {section} {key} evidence record\n",
                  encoding="utf-8")
    pin = {"path": str(ev), "sha256": oc.sha256_file(ev)}
    canon = f"canon:{section}:{key}"
    t = json.loads(json.dumps(table))
    entry = t[section][key]
    if mapping == "local":
        entry["evidence"] = [dict(pin)]
    else:
        entry.pop("evidence", None)
        entry["canonical_leaf"] = canon
        t["leaves"][canon] = {"landed": True, "evidence": [dict(pin)],
                              "verification": dict(PASS_VERIF)}
    good = _write_json(t, root / "cf-good.json")
    base = root / "base"
    r = run_tool(rp, base, leaf_table=good, integration_ledger=led,
                 allow_drift=drift, tool=tool)
    assert r.returncode == 0, r.stderr
    b = _rows_by_path(base)
    s0 = {p for p, x in b.items() if x["headline_status"] == "supported"}
    affected = _affected_for(section, key, b, graphs)
    col = "routing_leaves_gate" if section == "routing_leaves" else "fx_leaves_gate"
    victims = affected & s0
    assert affected and victims, f"{label}: empty affected/victim set"
    assert all(b[p][col] == "PASS" for p in affected), label
    cov = json.loads((base / "coverage.json").read_text(encoding="utf-8"))
    assert str(ev) in cov["inputs"], f"{label}: pin absent from provenance"
    transcript.append(f"    {label}: valid pin -> affected={len(affected)} "
                      f"(gates PASS), supported victims={len(victims)}, "
                      "pin in provenance")
    prefix = (f"stale_leaf:routing:{key}(" if section == "routing_leaves"
              else f"stale_leaf:fx:Airwindows:aw{key}-")
    for how in ("hash", "missing"):
        t2 = json.loads(json.dumps(t))
        tgt = (t2[section][key] if mapping == "local" else t2["leaves"][canon])
        if how == "hash":
            tgt["evidence"][0]["sha256"] = oc.sha256_file(
                REPO / "reports/sxt-024/EVIDENCE.md")
        else:
            tgt["evidence"][0]["path"] = str(root / "evidence-absent.md")
        tp = _write_json(t2, root / f"cf-{how}.json")
        out = root / f"out-{how}"
        r = run_tool(rp, out, leaf_table=tp, integration_ledger=led,
                     allow_drift=drift, tool=tool)
        assert r.returncode == 0, f"{label} {how}: must downgrade: {r.stderr}"
        rows = _rows_by_path(out)
        s1 = {p for p, x in rows.items() if x["headline_status"] == "supported"}
        notstale = sorted(p for p in affected if rows[p][col] != "STALE")
        _targeted(not notstale, f"{label} {how}: {len(notstale)}/"
                  f"{len(affected)} affected gates not STALE")
        for p in affected:
            _targeted(prefix in rows[p]["reasons"],
                      f"{label} {how}: {p} lacks reason {prefix}")
        _targeted(s1 == s0 - affected,
                  f"{label} {how}: supported set not exactly baseline - "
                  "affected")
        for p in victims:
            _targeted(rows[p]["headline_status"] == "unresolved",
                      f"{label} {how}: victim {p} not unresolved")
        for p in set(b) - affected:
            _targeted(rows[p] == b[p],
                      f"{label} {how}: unaffected row {p} changed")
        transcript.append(f"    {label} {how:<7}: affected gates -> STALE "
                          f"({len(affected)}); supported {len(s0)} -> {len(s1)}"
                          f"; victims unresolved; {len(set(b) - affected)} "
                          "unaffected rows byte-equal")


def _mutant_tool(tag: str, old: str, new: str) -> Path:
    """Temporary copy of the publisher with one pre-#432 shortcut restored.
    The replacement must match exactly once or the control is not live."""
    src = (REPO / "tools/publish_coverage.py").read_text(encoding="utf-8")
    assert src.count(old) == 1, f"mutant {tag}: anchor not found exactly once"
    d = NC_ROOT / f"mutant-{tag}"
    (d / "tools").mkdir(parents=True)
    (d / "tools/publish_coverage.py").write_text(src.replace(old, new),
                                                 encoding="utf-8")
    (d / "oracle").symlink_to(REPO / "oracle")
    (d / "refusal.py").symlink_to(REPO / "refusal.py")
    return d / "tools/publish_coverage.py"


FALLBACK = ('return {"landed": bool(lf.get("landed")), '
            '"ready": bool(lf.get("landed")) and leaf_ready(lf), '
            '"stale": False, "unevidenced": False, "stale_detail": "", '
            '"verification": lf.get("verification", {})}')


def control_evidence_readiness(transcript) -> None:
    transcript.append("NC-EVIDENCE-READINESS: every coverage leaf/gate "
                      "readiness claim needs current evidence (#432)")
    root = NC_ROOT / "evidence-readiness"
    scenario_ordinary(root / "ordinary", TOOL, transcript)
    for section in ("routing_leaves", "airwindows_leaves"):
        for mapping in ("local", "canonical"):
            scenario_section(root / f"{section}-{mapping}", TOOL, section,
                             mapping, transcript)

    # live failure controls: each restored shortcut must FAIL its targeted
    # assertion; a control that changes no reached gate is FAIL.
    sec_old = "    return build_leaf_state(repo, lf, owner)\n"
    can_old = "        return leaf_states[canon]\n"
    mutants = [
        ("empty-list-shortcut", "if require and not pins:", "if False:",
         lambda tool, tr: scenario_ordinary(root / "m1", tool, tr)),
        ("stale-false-fallback-routing", sec_old,
         f'    if section == "routing_leaves":\n        {FALLBACK}\n' + sec_old,
         lambda tool, tr: scenario_section(
             root / "m2", tool, "routing_leaves", "local", tr)),
        ("stale-false-fallback-airwindows", sec_old,
         f'    if section == "airwindows_leaves":\n        {FALLBACK}\n' + sec_old,
         lambda tool, tr: scenario_section(
             root / "m3", tool, "airwindows_leaves", "local", tr)),
        ("canonical-mapping-ignored", can_old,
         f"        {FALLBACK}\n",
         lambda tool, tr: scenario_section(
             root / "m4", tool, "routing_leaves", "canonical", tr)),
    ]
    for tag, old, new, scenario in mutants:
        tool = _mutant_tool(tag, old, new)
        sink = []
        try:
            scenario(tool, sink)
        except AssertionError as e:
            msg = str(e)
            assert msg.startswith(f"{TARGETED}:"), (
                f"live control {tag}: failed for an untargeted reason "
                f"(CONTROL-BROKEN): {msg}")
            transcript.append(f"    live control {tag}: mutated copy FAILS "
                              f"the targeted assertion ({msg[:110]})")
        else:
            raise AssertionError(
                f"live control {tag}: mutated copy passed every targeted "
                "assertion (CONTROL-BROKEN: changed no reached gate)")
    transcript.append("    PASS: absent/null/empty evidence never ready; "
                      "stale section/canonical evidence STALEs every reached "
                      "gate; restored shortcuts each fail their assertion")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcript",
                    default="reports/coverage-v1/negative-controls.txt")
    ap.add_argument("--only", action="append", default=None,
                    help="run only the named control(s): stale_hash, "
                         "stale_missing, row_missing, sha_disagree, "
                         "rng_exclusion, f1_original_stage, "
                         "voice_pin_corrupt, integration_gate, "
                         "evidence_readiness. Used by #122 to record its own "
                         "gate control under reports/SXT-028-rng/.")
    args = ap.parse_args()

    if NC_ROOT.exists():
        shutil.rmtree(NC_ROOT)
    NC_ROOT.mkdir(parents=True)

    transcript = [
        "SXT-029 negative controls — coverage pipeline (issue #22 acceptance)",
        "runner: tools/coverage_negative_controls.py; scratch root: "
        "/tmp/sxt029-negative-controls (recreated each run; published "
        "outputs never touched)",
        "controls are healthy when the PIPELINE fails as designed: a stale "
        "or missing leaf evidence must DOWNGRADE affected presets from "
        "supported to unresolved (never report them supported); a corpus "
        "entry without a coverage row must REFUSE fail-closed.",
        "",
    ]
    controls = [
        control_stale_hash,
        control_stale_missing,
        control_row_missing,
        control_sha_disagree,
        control_rng_exclusion,
        control_f1_original_stage,
        control_voice_pin_corrupt,
        control_integration_gate,
        control_evidence_readiness,
    ]
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {c.__name__[len("control_"):] for c in controls}
        if unknown:
            print(f"unknown control(s): {sorted(unknown)}", file=sys.stderr)
            return 2
        controls = [c for c in controls
                    if c.__name__[len("control_"):] in wanted]
        transcript.insert(3, f"SUBSET RUN: only {sorted(wanted)}")
    failed = []
    for c in controls:
        try:
            c(transcript)
        except AssertionError as e:
            failed.append(c.__name__)
            transcript.append(f"    FAIL: {e}")
        transcript.append("")

    if failed:
        transcript.append(f"RESULT: FAIL — unhealthy controls: {', '.join(failed)}")
        status = 1
    else:
        transcript.append("RESULT: PASS — all controls healthy (each "
                          "demonstrably fails the check it targets)")
        status = 0
    transcript_path = REPO / args.transcript
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("\n".join(transcript) + "\n", encoding="utf-8")
    print("\n".join(transcript))
    return status


if __name__ == "__main__":
    sys.exit(main())
