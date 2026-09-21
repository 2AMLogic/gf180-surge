"""SXT-025 integration evidence tests (fast: verify committed artifacts)."""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEL = os.path.join(REPO, "model", "integration", "selection-scan.json")
IMAGE_BIN = os.path.join(REPO, "model", "integration", "preset",
                         "Hell_s_Bells__e499f78d.image.bin")
IMAGE_JSON = os.path.join(REPO, "model", "integration", "preset",
                          "Hell_s_Bells__e499f78d.image.json")
INPUTS = os.path.join(REPO, "model", "integration", "bells_inputs.json")
ART = os.path.join(REPO, "reports", "sxt025")
SEQUENCES = ["sxt025-smoke-v1", "sxt025-accept-v1"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_selection_record_pins_the_corpus():
    rec = _load(SEL)
    assert rec["inputs"]["graphs_jsonl_sha256"] == (
        "c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715")
    t = rec["tier_counts"]
    assert t["compiled"] == 1683
    assert t["tier3_declared_voice_gates"] == 1
    assert t["tier4_landed_voice_model_with_fx"] == 0
    # the unique Tier-3 survivor is the selection, carrying only legal FX
    survivor = rec["tier3_survivors_with_legal_fx"][0]
    assert survivor["path"] == rec["selection"]["path"]
    fx = {tuple(x) for x in survivor["fx"]}
    assert fx == {("send2", "Reverb 1")}


def test_compiled_image_verifies_and_matches_record():
    rec = _load(SEL)
    import hashlib

    h = hashlib.sha256(open(IMAGE_BIN, "rb").read()).hexdigest()
    assert h == rec["selection"]["compiled_image_sha256"]
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "compiler", "verify.py"),
         "image", IMAGE_BIN], capture_output=True, text=True)
    assert "PASS" in r.stdout or r.returncode == 0, r.stdout + r.stderr


def test_extraction_matches_image():
    inputs = _load(INPUTS)
    image = _load(IMAGE_JSON)
    graph = image["body"]["graph"]
    assert image["header"]["source"]["census_blob_sha1"] == \
        inputs["census_blob_sha1"]
    eng_types = [fx.get("t", 0) for fx in graph["fx_slots"]]
    slots = [e["slot"] for e in inputs["fx_instances"]]
    for s in slots:
        assert eng_types[s] == 2  # Reverb 1
        assert graph["fx_slots"][s]["r"] == e_role(inputs, s)
    assert inputs["scene_mode"] == 0 and inputs["scene_active"] == 0
    assert inputs["drifts_asserted_zero"] == [0.0]


def e_role(inputs, slot):
    return next(e["role"] for e in inputs["fx_instances"] if e["slot"] == slot)


@pytest.mark.parametrize("seq", SEQUENCES)
def test_compare_artifacts(seq):
    cmp_path = os.path.join(ART, "artifacts", f"compare__{seq}.json")
    assert os.path.exists(cmp_path), "run model/integration/compare_integration.py"
    c = _load(cmp_path)
    assert c["statuses"]["full_render"] == "PASS"
    assert c["statuses"]["event_timing"] == "PASS"
    assert c["statuses"]["placement_order_gain"] == "PASS"
    assert c["statuses"]["memory_traffic"] == "PASS"
    # the tail's band-energy sub-budget FAILS on a recorded bounded finding
    # (fixed-grid HF decay floor); every other tail budget passes
    assert c["statuses"]["tail"].startswith("FAIL_BAND_ENERGY_SUBBUDGET")
    assert c["tail"]["band_energy_finding"]
    assert c["tail"]["tail_rms_ok"] and c["tail"]["tail_continuity_ok"]
    assert c["tail"]["decay_curve_ok"] and c["tail"]["stereo_corr_ok"]
    mono = c["full_render"]["channels"]["mono"]
    assert mono["best_shift"] == 0
    assert mono["spectral_corr"] >= 0.98


@pytest.mark.parametrize("seq", SEQUENCES)
def test_trace_invariants(seq):
    trace = _load(os.path.join(ART, "artifacts", f"trace__{seq}.json"))
    po = trace["placement_order"]
    assert [p["engine_order"] for p in po] == sorted(
        p["engine_order"] for p in po)
    assert po[0]["role"] == "send2" and po[0]["kind"] == "reverb1"
    et = trace["event_timing"]
    assert et["max_event_latency_samples"] <= 64
    assert et["worst_events_per_block"] <= et["reserve_per_block"]
    for inst in trace["traffic_ledger"]:
        t = inst.get("traffic")
        if t:
            assert t["words_per_output_frame"] == 34
            assert t["bytes_per_output_frame"] == 136
            assert t["buffer_bytes"] == 4 * (524288 + 32768)
    tail = trace["tail"]
    assert tail["tail_frames"] >= 0.5 * 48000 * 1.5  # tail captured, not cut


def test_schedule_closure():
    sc = _load(os.path.join(ART, "schedule-closure.json"))
    rows = sc["closure_at_clocks"]
    assert rows["192000000"]["closure"] == "within_budget"
    assert rows["480000000"]["closure"] == "within_budget"
    assert rows["48000000"]["closure"] == "OVERFLOW"
    assert rows["48000000"]["rejection"]["code"] == "schedule_budget_overflow"
    assert sc["event_reserve_respected"]
    for m in sc["memory_stall_accounting"]:
        assert m["reconciles_sxt024_model"]
        assert m["flash_is_not_writable_storage"]


def test_rtl_exactness_evidence():
    r = _load(os.path.join(ART, "rtl-exactness.json"))
    assert r["status"] == "PASS"
    integrated = next(c for c in r["cases"] if c["case"] == "integrated")
    assert integrated["exact"]
    assert integrated["control_snapshots_exact"]
    assert integrated["control_decisions_exact"]
    assert integrated["kernel_checkpoints_outputs_exact"]
    assert integrated["txn_log_exact"]
    assert integrated["traffic_exact_34_per_frame"]
    assert integrated["underruns"] == 0
    assert integrated["kernel_cycles"]["within_budget"]
    mutant = next(c for c in r["cases"] if c["case"] == "mutant")
    assert mutant["verdict"].startswith("CONTROL-OK")


def test_negative_controls_healthy():
    txt = open(os.path.join(ART, "negative-controls.txt"),
               encoding="utf-8").read()
    assert "ALL CONTROLS HEALTHY" in txt
    ncdir = os.path.join(ART, "negative-controls")
    for name in ("nc-a", "nc-b", "nc-c"):
        found = [f for f in os.listdir(ncdir) if f.startswith(name)]
        assert found, name
        r = _load(os.path.join(ncdir, found[0]))
        assert r["detected"] is True


def test_fixture_determinism_gates():
    for seq in SEQUENCES:
        side = _load(os.path.join(ART, "fixtures",
                                  f"hells_bells__{seq}.json"))
        g = side["determinism_gate"]
        assert g["repeats"] == 3 and g["bit_identical"]
        assert side["dry"]["dry_fx_bypass_verified"]
