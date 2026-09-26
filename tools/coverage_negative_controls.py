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

Exit 0 iff every control is healthy; transcript goes to
reports/coverage-v1/negative-controls.txt.
"""

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
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
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_tool(root: Path, outdir: Path, leaf_table: Path = None,
             allow_drift: bool = False, rng_exclusion: Path = None,
             ignore_rng: bool = False):
    cmd = [sys.executable, str(TOOL), "--repo-root", str(root),
           "--outdir", str(outdir)]
    if leaf_table is not None:
        cmd += ["--leaf-table", str(leaf_table)]
    if allow_drift:
        cmd += ["--control-allow-input-drift"]
    if rng_exclusion is not None:
        cmd += ["--rng-exclusion", str(rng_exclusion)]
    if ignore_rng:
        cmd += ["--control-ignore-rng-exclusion"]
    return subprocess.run(cmd, capture_output=True, text=True)


def read_rows(outdir: Path):
    with open(outdir / "per-preset.csv", newline="") as f:
        return list(csv.DictReader(f))


def counterfactual_table(dest: Path) -> Path:
    """Synthetic verified-world table (test fixture; never published).

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
                item["sha256"] = sha256_file(p)

    for section in ("leaves", "gates", "routing_leaves", "airwindows_leaves"):
        for block in table.get(section, {}).values():
            refresh(block)
    for lid, lf in table["leaves"].items():
        lf["landed"] = True
        lf["verification"] = dict(PASS_VERIF)
    table["leaves"]["voice:attacky-slice"]["verified_scope"] = "all"
    for section in ("routing_leaves", "airwindows_leaves"):
        for lf in table[section].values():
            lf["landed"] = True
            lf["verification"] = dict(PASS_VERIF)
            lf["filed"] = True
    table["gates"]["fidelity_freeze"]["status"] = "PASS"
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
    r = run_tool(REPO, base, leaf_table=cf)
    assert r.returncode == 0, r.stderr
    table = json.loads(cf.read_text(encoding="utf-8"))
    # point the EQ leaf's evidence hash at a *different committed file*
    mismatch = sha256_file(REPO / "reports/sxt-024/EVIDENCE.md")
    table["leaves"]["fx:EQ"]["evidence"][0]["sha256"] = mismatch
    cf2 = NC_ROOT / "stale-hash" / "counterfactual-stale.json"
    cf2.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    r = run_tool(REPO, tamp, leaf_table=cf2)
    assert r.returncode == 0, (
        f"STALE must downgrade (exit 0), not refuse: rc={r.returncode} {r.stderr}"
    )
    assert_stale_downgrade(base, tamp, transcript)


def control_stale_missing(transcript) -> None:
    transcript.append("NC-STALE-MISSING: silent stub (evidence file absent)")
    base = NC_ROOT / "stale-missing" / "base"
    tamp = NC_ROOT / "stale-missing" / "tampered"
    cf = counterfactual_table(NC_ROOT / "stale-missing" / "counterfactual.json")
    r = run_tool(REPO, base, leaf_table=cf)
    assert r.returncode == 0, r.stderr
    table = json.loads(cf.read_text(encoding="utf-8"))
    table["leaves"]["fx:EQ"]["evidence"] = [
        {"path": str(NC_ROOT / "stale-missing" / "evidence-absent.md"),
         "sha256": "0" * 64}
    ]
    cf2 = NC_ROOT / "stale-missing" / "counterfactual-stale.json"
    cf2.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    r = run_tool(REPO, tamp, leaf_table=cf2)
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

    r = run_tool(REPO, base, leaf_table=cf)
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

    r = run_tool(REPO, tamp, leaf_table=cf, rng_exclusion=synth)
    assert r.returncode == 0, f"gate must downgrade, not refuse: {r.stderr}"
    s1, _, by1 = load_supported(tamp)

    r = run_tool(REPO, bypass, leaf_table=cf, rng_exclusion=synth,
                 ignore_rng=True)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcript",
                    default="reports/coverage-v1/negative-controls.txt")
    ap.add_argument("--only", action="append", default=None,
                    help="run only the named control(s): stale_hash, "
                         "stale_missing, row_missing, sha_disagree, "
                         "rng_exclusion. Used by #122 to record its own "
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
