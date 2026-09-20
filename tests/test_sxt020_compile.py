"""SXT-020 patch-image compiler tests (issue #13; run by CI).

Covers the automatable guarantees only:
  - the golden suite is green (byte-identical recompiles, graph
    losslessness, allocation reconciliation, expected rejection codes),
  - compiled outputs are byte-deterministic across runs,
  - the committed corpus scan is current (re-run reproduces it
    byte-identically) and reconciles with the committed SXT-017 B4
    prediction,
  - negative controls: a crafted graph carrying a profile-unsupported
    feature produces the SPECIFIC rejection and NEVER an image; a
    corrupted-checksum image fails verification; FM3 compiles under
    B4-broad (in the allowlist) and rejects under B2 (not),
  - the rejection catalog is internally consistent and every emitted code
    is cataloged (fail-closed check),
  - no rejection record in the golden set ships an image beside it.

These tests make NO claim about sound fidelity, preset quality, preset
support, or any frozen profile, and no technology claim (allocation numbers
are SXT-015 placeholders). No engine tree is required or used.

Python 3 standard library only (pytest as runner).
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPILER = REPO / "compiler"
VERIFY = COMPILER / "verify.py"
COMPILE = COMPILER / "compile.py"
GRAPHS = REPO / "corpus" / "normalized" / "graphs.jsonl"
BUNDLE = REPO / "contracts" / "profile-v1-bundle-DRAFT.json"
SCAN = REPO / "reports" / "sxt-020" / "compile-corpus-scan.json"
PREDICTION = REPO / "reports" / "sxt-017" / "predictions" / "B4-broad.json"

SIMPLE = "resources/data/patches_factory/Basses/Attacky.fxp"


def run_py(script, *args):
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True, cwd=REPO)


def test_golden_suite_green():
    r = run_py(VERIFY, "golden")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_negative_controls_green():
    r = run_py(VERIFY, "controls")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_compile_is_byte_deterministic(tmp_path):
    outs = []
    for i in range(2):
        d = tmp_path / ("run%d" % i)
        r = run_py(COMPILE, "compile", "--path", SIMPLE,
                   "--out-dir", str(d))
        assert r.returncode == 0, r.stderr
        assert "outcome=compiled" in r.stdout
        bins = list(d.glob("*.image.bin"))
        assert len(bins) == 1
        outs.append(bins[0].read_bytes())
    assert outs[0] == outs[1]


def test_rejected_compile_emits_record_and_no_image(tmp_path):
    r = run_py(COMPILE, "compile",
               "--path", "resources/data/patches_3rdparty/A.Liv/Basses/Sqweird.fxp",
               "--out-dir", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "outcome=rejected" in r.stdout
    assert "oscillator_family_not_in_bundle" in r.stdout
    assert not list(tmp_path.glob("*.image.bin")), "rejection shipped an image"
    rec = json.loads(next(tmp_path.glob("*.rejection.json")).read_text())
    assert rec["outcome"] == "rejected"
    assert rec["codes"], "rejection record without codes"
    catalog = {c["code"] for c in
               json.loads((COMPILER / "rejections.json").read_text())["codes"]}
    assert {c["code"] for c in rec["codes"]} <= catalog


def test_scan_is_current_and_reconciles(tmp_path):
    out = tmp_path / "scan.json"
    r = run_py(COMPILE, "scan", "--out", str(out),
               "--reconcile", str(PREDICTION.relative_to(REPO)))
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == SCAN.read_bytes(), (
        "committed compile-corpus-scan.json is stale; regenerate with "
        "compiler/compile.py scan")
    d = json.loads(out.read_text())
    assert d["totals"]["total"] == 3561
    assert (d["totals"]["compiled"] + d["totals"]["rejected"]
            + d["totals"]["unresolved"] == 3561)
    rec = d["reconciliation"]
    assert rec["graphs_sha256_match"] is True
    pred = json.loads(PREDICTION.read_text())
    # the compiler may only be STRICTER than the predictor: compiled counts
    # can never exceed predicted supported, and every delta is enumerated
    assert d["totals"]["compiled"] <= pred["totals"]["supported"]
    assert len(rec["deltas"]) == pred["totals"]["supported"] - d["totals"]["compiled"]
    for delta in rec["deltas"]:
        assert delta["predictor_status"] == "supported"
        assert delta["compiler_outcome"] == "rejected"
        assert delta["compiler_codes"], "delta without a named code"


def test_corrupted_image_fails_verification(tmp_path):
    good = tmp_path / "good.image.bin"
    r = run_py(COMPILE, "compile", "--path", SIMPLE, "--out-dir", str(tmp_path))
    assert r.returncode == 0, r.stderr
    good = next(tmp_path.glob("*.image.bin"))
    data = good.read_bytes()
    corrupt = tmp_path / "corrupt.image.bin"
    flip = data[:len(data) // 2] + bytes([data[len(data) // 2] ^ 0xFF]) \
        + data[len(data) // 2 + 1:]
    corrupt.write_bytes(flip)
    r = run_py(VERIFY, "image", str(corrupt))
    assert r.returncode != 0
    assert "image/parse" in r.stdout and "FAIL" in r.stdout


def test_rejection_catalog_integrity():
    cat = json.loads((COMPILER / "rejections.json").read_text())
    codes = [c["code"] for c in cat["codes"]]
    assert len(codes) == len(set(codes)), "duplicate catalog codes"
    for c in cat["codes"]:
        assert c["class"] in ("unsupported", "unresolved", "adaptation")
        assert c["meaning"] and c["gate"]
    # codes shared with SXT-017 keep the predictor's names (reconciliation)
    sxt017_codes = {
        "loader_analysis_failure", "mseg_or_formula_contents_not_exported",
        "audio_input_dependency", "scene_mode_not_in_bundle",
        "oscillator_family_not_in_bundle", "wavetable_assets_not_in_bundle",
        "filter_algorithm_not_in_bundle", "waveshaper_not_in_bundle",
        "effect_class_not_in_bundle", "airwindows_algorithm_not_selected",
        "fx_instance_overflow", "event_queue_overflow",
        "scene_mode_unaccountable", "on_chip_ram_exceeded",
        "external_writable_capacity_exceeded", "external_bandwidth_exceeded",
        "polylimit_reduction_required", "unison_reduction_required",
    }
    assert sxt017_codes <= set(codes)


def test_golden_manifest_covers_the_required_span():
    m = json.loads((COMPILER / "golden" / "manifest.json").read_text())
    cases = {c["case"]: c for c in m["cases"]}
    compiled = [c for c in cases.values()
                if c["expected"]["outcome"] == "compiled"]
    rejected = [c for c in cases.values()
                if c["expected"]["outcome"] != "compiled"]
    assert len(compiled) >= 8
    assert len(rejected) >= 6
    for required in ("simple-classic", "wavetable-asset", "dual-scene",
                     "four-fx-instance", "supersaw-96osc", "reject-july",
                     "reject-asset-unresolved", "reject-send-levels",
                     "synthetic-airwindows-point"):
        assert required in cases, required
    # every synthetic case is labeled as such
    for name, c in cases.items():
        if name.startswith("synthetic"):
            assert c["source"].get("synthetic") is True
    # every rejection case names its codes; every compiled case pins bytes
    for c in rejected:
        assert c["expected"]["codes"]
    for c in compiled:
        assert c["expected"]["image_sha256"]
