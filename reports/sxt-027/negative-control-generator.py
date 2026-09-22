#!/usr/bin/env python3
"""SXT-027 generator negative controls (issue #20 acceptance).

Injected bad cases; every case must be REFUSED by the generator's
fail-closed guards. Run from any checkout:

    python3 reports/sxt-027/negative-control-generator.py

Cases:
  NC-G1  leaf emission with an EMPTY newly-enabled preset set (issue #20:
         "leaves enabling zero preferred presets are not filed")
  NC-G2  unknown leaf keys/values through the leaf-template builder
  NC-G3  unknown oscillator family through the production feature
         extraction (real committed data, one injected mutation)
  NC-G4  unknown modsource id through the production feature extraction
  NC-G5  tampered graphs bytes through the full CLI (integrity gate)

A control that is NOT refused means the guard is broken: the run fails.
"""
import copy
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location(
    "gvl", REPO / "tools" / "generate_voice_leaves.py")
gvl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gvl)

results = []


def attempt(name, fn):
    try:
        fn()
        results.append((name, "NOT REFUSED -- CONTROL FAILED", False))
    except gvl.Refuse as e:
        results.append((name, "REFUSED: %s" % e, True))


attempt("NC-G1 zero-recovery leaf emission", lambda: gvl.emit_guard(
    "filter_type:FX Allpass", {"basis": [], "corpus": []}))

attempt("NC-G2a unknown leaf key (leaf_statics)",
        lambda: gvl.leaf_statics("osc_family:BizarreOsc"))
attempt("NC-G2b unknown leaf dimension (leaf_statics)",
        lambda: gvl.leaf_statics("bizarre_dim:thing"))
attempt("NC-G2c unknown leaf value, filter (leaf_statics)",
        lambda: gvl.leaf_statics("filter_type:Not A Filter"))
attempt("NC-G2d unknown leaf dimension (leaf_title)",
        lambda: gvl.leaf_title("bizarre_dim:thing"))

args = type("A", (), {})()
args.graphs = REPO / "corpus/normalized/graphs.jsonl"
args.prediction = REPO / "reports/sxt-017/predictions/B4-broad.json"
args.scan = REPO / "reports/sxt-020/compile-corpus-scan.json"
args.slate = [REPO / "reports/sxt-013/candidates/slate-256-balanced.json",
              REPO / "reports/sxt-013/candidates/slate-256-factory-lean.json",
              REPO / "reports/sxt-013/candidates/"
                     "slate-256-contributor-lean.json"]
data = gvl.load_inputs(args)
victim = data["supported"][0]

lines = copy.deepcopy(data["lines"])
for d in lines:
    if d["p"] == victim:
        d["g"]["sc"][0]["osc"][0]["tn"] = "BizarreOsc"
injected = dict(data)
injected["lines"] = lines
injected["by_path"] = {d["p"]: d for d in lines}
attempt("NC-G3 unknown oscillator family via feature_keys()",
        lambda: gvl.feature_keys(injected))

lines = copy.deepcopy(data["lines"])
for d in lines:
    if d["p"] == victim:
        d["g"]["md"].setdefault("s", [{}])[0].setdefault("v", []).append(
            [99, 0, 0, 0, "A Filter 1 Cutoff", 0.5, 0.5])
injected = dict(data)
injected["lines"] = lines
injected["by_path"] = {d["p"]: d for d in lines}
attempt("NC-G4 unknown modsource id via feature_keys()",
        lambda: gvl.feature_keys(injected))

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    src = (REPO / "corpus/normalized/graphs.jsonl").read_text(
        encoding="utf-8").splitlines(keepends=True)
    tampered = src[0] + src[1].replace("Attacky", "ATTACKY-TAMPERED")
    (tdp / "graphs.jsonl").write_text(tampered, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(REPO / "tools/generate_voice_leaves.py"),
         "--graphs", str(tdp / "graphs.jsonl"),
         "--out-plan", str(tdp / "p.json"),
         "--out-backlog", str(tdp / "b.json")],
        capture_output=True, text=True)
    refused = (r.returncode == 2 and "REFUSING: graphs sha256" in
               (r.stderr + r.stdout))
    results.append((
        "NC-G5 tampered graphs via full CLI",
        ("REFUSED (exit %d): %s" % (r.returncode,
                                    r.stderr.strip().splitlines()[-1])
         if refused else
         "NOT REFUSED (exit %d) -- CONTROL FAILED" % r.returncode),
        refused))

ok = True
for name, msg, passed in results:
    print("%s\n  -> %s\n" % (name, msg))
    ok = ok and passed
print("ALL GENERATOR NEGATIVE CONTROLS REFUSED: %s"
      % ("YES" if ok else "NO -- FAILING CONTROL"))
sys.exit(0 if ok else 1)
