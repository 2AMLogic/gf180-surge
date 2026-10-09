#!/usr/bin/env python3
"""#318 -- the cross-runner settle-boundary audit is complete and fail-closed.

What this pins, and what it does NOT:

  * PINS: every `model/effects/run_*_model.py` is in the audit's inventory
    with the pre-roll it actually uses (read from source, including the
    Phaser runner's inherited constant); the boundary decision is the
    probe's fail-closed rule (RESOLVED only on measured A and B byte
    identity, never chosen from C); an unmeasured A/B is BLOCKED/NOT_RUN and
    never PASS; malformed or refused comparator records, mixed spectral
    definitions and unequal-length outputs are refused; the committed audit
    records keep that vocabulary and their provenance links.
  * DOES NOT: run the engine (A/B are oracle-gated), re-run any model leg
    (the committed per-leaf records carry those numbers), or establish any
    agreement, support or quality claim. A unit suite cannot discharge the
    live acceptance of #318.
"""

import json
import os
import struct
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import audit_effect_settle_boundaries as aud  # noqa: E402

OUT = os.path.join(REPO, "reports", "effect-settle-boundary-audit")


# ------------------------------------------------------------------ helpers
def committed(name):
    with open(os.path.join(REPO, name)) as f:
        return json.load(f)


def write_wav(path, frames, nch=2):
    data = struct.pack("<%df" % (frames * nch), *([0.0] * frames * nch))
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, nch, 48000,
                                 48000 * nch * 4, nch * 4, 32)
    hdr += b"data" + struct.pack("<I", len(data))
    with open(path, "wb") as f:
        f.write(hdr + data)


def stub_c(prod_metrics, alt_metrics, prod, alt, sensitive=True,
           model_sha=None):
    """A leg-C result shaped like `offline_c`, without running a model."""
    legs = {
        str(prod): {"silent_preroll_blocks": prod, "role": "production",
                    "model_wav_sha256": model_sha or "p" * 64,
                    "frames": prod_metrics["channels"]["mono"]["frames"],
                    "metrics": prod_metrics},
        str(alt): {"silent_preroll_blocks": alt, "role": "zero",
                   "model_wav_sha256": ("a" * 64 if sensitive
                                        else model_sha or "p" * 64),
                   "frames": alt_metrics["channels"]["mono"]["frames"],
                   "metrics": alt_metrics},
    }
    return {
        "status": "MEASURED",
        "reference": {"buffer_sha256": "r" * 64},
        "fixture_settle_blocks": 375,
        "production_preroll_blocks": prod,
        "legs": legs,
        "model_output_preroll_sensitive": sensitive,
        "deltas_vs_production": {},
        "comparator_verdict_by_preroll": {
            k: v["metrics"]["verdict_class"] for k, v in legs.items()},
        "comparator_verdict_depends_on_preroll": True,
    }


def failing_copy(metrics):
    m = json.loads(json.dumps(metrics))
    m["verdict"] = "FAIL against proposed budgets (budget: rms_diff_dbfs)"
    m["verdict_class"] = "FAIL"
    return m


CHORUS = "run_chorus_model.py"
CHORUS_CARRIER = aud.RUNNERS[CHORUS]["carriers"][2]       # fmcombo notes


def chorus_baseline_metrics():
    c = CHORUS_CARRIER
    return aud.extract_metrics(committed(
        "reports/SXT-028c/artifacts/compare-%s__%s.json"
        % (c["slug"], c["seq"])))


# ------------------------------------------------- inventory completeness
def test_inventory_lists_every_runner_with_its_source_preroll():
    inv = aud.inventory()
    got = {r["runner"]: r["production_preroll_blocks"]
           for r in inv["runners"]}
    assert got == {
        "model/effects/run_chorus_model.py": 375,
        "model/effects/run_distortion_sse_model.py": 0,
        "model/effects/run_fx_model.py": 375,   # 240 until issue #16 (F-318-1)
        "model/effects/run_phaser_model.py": 375,
        "model/effects/run_reverb2_model.py": 375,
    }


def test_phaser_preroll_is_inherited_not_redeclared():
    inv = {r["runner"]: r for r in aud.inventory()["runners"]}
    ph = inv["model/effects/run_phaser_model.py"]
    assert ph["inherited_from"] == "run_chorus_model.py"
    assert "imported from run_chorus_model.py" in \
        ph["production_preroll_source"]


def test_every_fixture_carrier_reconciles_settle_and_block_size():
    """The fixture settle is re-derived from each sidecar, never assumed."""
    for r in aud.inventory()["runners"]:
        for c in r["carriers"]:
            assert c["fixture_sidecar"], (r["runner"], c["slug"])
            assert c["fixture_block_size"] == 32
            assert c["fixture_settle_blocks"] == 375
            assert c["runner_preroll_equals_fixture_settle"] == (
                r["production_preroll_blocks"] == 375)


def test_delay_eq_runner_preroll_is_neither_zero_nor_the_fixture_settle():
    """The curated discrepancy: 240 blocks = 0.16 s, not 0.25 s."""
    inv = {r["runner"]: r for r in aud.inventory()["runners"]}
    fx = inv["model/effects/run_fx_model.py"]
    assert fx["production_preroll_blocks"] == 240
    assert all(c["runner_preroll_seconds"] == 0.16 for c in fx["carriers"])


def test_inventory_refuses_an_unaudited_runner(monkeypatch):
    shrunk = dict(aud.RUNNERS)
    shrunk.pop("run_reverb2_model.py")
    monkeypatch.setattr(aud, "RUNNERS", shrunk)
    with pytest.raises(aud.AuditRefused, match="unaudited runner"):
        aud.inventory()


def test_inventory_refuses_an_unclassified_effect_model(monkeypatch):
    nr = dict(aud.NON_RUNNER_MODELS)
    nr.pop("aw-49")
    monkeypatch.setattr(aud, "NON_RUNNER_MODELS", nr)
    with pytest.raises(aud.AuditRefused, match="not classified"):
        aud.inventory()


def test_preroll_resolution_refuses_a_missing_constant(tmp_path):
    src = tmp_path / "run_x_model.py"
    src.write_text("OTHER = 3\n")
    parsed = aud.parse_runner_preroll(str(src))
    with pytest.raises(aud.AuditRefused, match="no module constant"):
        aud.resolve_preroll("run_x_model.py",
                            {"kind": "module_constant",
                             "name": "SETTLE_BLOCKS"}, parsed)


def test_every_runner_reached_model_dir_is_named():
    inv = aud.inventory()
    assert set(inv["runner_reached_models"]) == {
        "delay", "eq", "type-chorus", "type-phaser", "type-reverb 2",
        "type-distortion-sse"}
    for m, v in inv["not_runner_reached_models"].items():
        assert v["status"] == "NOT_RUN", m


# ---------------------------------------------- fail-closed decision rule
@pytest.mark.parametrize("a,b,want", [
    (True, True, ("RESOLVED", 0)),
    (True, False, ("UNRESOLVED", None)),
    (False, True, ("UNRESOLVED", None)),
    (False, False, ("UNRESOLVED", None)),
    (False, None, ("UNRESOLVED", None)),
    (None, None, ("NOT_MEASURED", None)),
    (True, None, ("NOT_MEASURED", None)),
])
def test_probe_rule_v1_is_preserved_verbatim(a, b, want):
    """The #136 probe's own rule, kept so a changed reading stays visible."""
    assert aud.decide_boundary_v1(a, b) == want


@pytest.mark.parametrize("a,b,early,want", [
    (True, True, True, ("RESOLVED", 0)),
    (True, True, False, ("UNRESOLVED", None)),     # fm_bass_1's shape
    (True, True, None, ("NOT_MEASURED", None)),    # committed record only
    (False, True, True, ("UNRESOLVED", None)),
    (True, False, True, ("UNRESOLVED", None)),
    (None, None, None, ("NOT_MEASURED", None)),
    (False, None, None, ("UNRESOLVED", None)),
])
def test_decide_boundary_is_the_probe_rule_tightened(a, b, early, want):
    """RESOLVED needs A, A_early AND B measured identical: strictly fewer
    RESOLVED outcomes than the probe's rule, never more."""
    assert aud.decide_boundary(a, b, None, early) == want
    v1 = aud.decide_boundary_v1(a, b)
    if want[0] == "RESOLVED":
        assert v1 == want


@pytest.mark.parametrize("bstat,declared,pre,ab,want", [
    ("RESOLVED", 0, 0, "MEASURED", "PASS"),
    ("RESOLVED", 0, 375, "MEASURED", "FAIL"),
    ("RESOLVED", 0, 240, "MEASURED", "FAIL"),
    ("UNRESOLVED", None, 375, "MEASURED", "NO_VERDICT"),
    ("NOT_MEASURED", None, 375, "BLOCKED", "BLOCKED"),
    ("NOT_MEASURED", None, 375, "NOT_RUN", "NOT_RUN"),
])
def test_runner_verdict(bstat, declared, pre, ab, want):
    assert aud.runner_verdict(bstat, declared, pre, ab)[0] == want


def test_unmeasured_ab_is_blocked_never_pass():
    base = chorus_baseline_metrics()
    c = stub_c(base, failing_copy(base), 375, 0)
    row = aud.audit_row(CHORUS, CHORUS_CARRIER, "/nonexistent",
                        {"available": False},
                        c_runner=lambda *_a, **_k: c)
    assert row["status"] == "BLOCKED"
    assert row["A_settle_length_invariance"]["status"] == "BLOCKED"
    assert row["boundary"]["status"] == "NOT_MEASURED"
    assert row["boundary"]["declared_preroll_blocks"] is None
    assert row["nc_c_control"]["status"] == "NOT_RUN"
    assert row["coverage"] == "C only"


def test_failed_invariance_is_no_verdict_even_when_c_discriminates(
        monkeypatch):
    """C says 'production PASSes, the other FAILs' -- irrelevant: A failed,
    so the boundary is UNRESOLVED and nothing is chosen by score."""
    base = chorus_baseline_metrics()
    c = stub_c(base, failing_copy(base), 375, 0)
    monkeypatch.setattr(aud, "live_ab_factory", lambda *_a, **_k: {
        "source": "test",
        "A": {"status": "MEASURED", "byte_identical": False},
        "B": {"status": "MEASURED", "byte_identical": True}})
    row = aud.audit_row(CHORUS, CHORUS_CARRIER, "/nonexistent",
                        {"available": True}, surgepy=object(),
                        c_runner=lambda *_a, **_k: c)
    assert row["boundary"]["status"] == "UNRESOLVED"
    assert row["status"] == "NO_VERDICT"
    assert row["escalation"] is None


def test_failed_construction_invariance_is_no_verdict(monkeypatch):
    base = chorus_baseline_metrics()
    c = stub_c(base, base, 375, 0, sensitive=False)
    monkeypatch.setattr(aud, "live_ab_factory", lambda *_a, **_k: {
        "source": "test",
        "A": {"status": "MEASURED", "byte_identical": True},
        "B": {"status": "MEASURED", "byte_identical": False}})
    row = aud.audit_row(CHORUS, CHORUS_CARRIER, "/nonexistent",
                        {"available": True}, surgepy=object(),
                        c_runner=lambda *_a, **_k: c)
    assert row["status"] == "NO_VERDICT"


def test_resolved_wrong_runner_boundary_fails_and_routes_to_12(monkeypatch):
    base = chorus_baseline_metrics()
    c = stub_c(base, failing_copy(base), 375, 0)
    monkeypatch.setattr(aud, "live_ab_factory", lambda *_a, **_k: {
        "source": "test",
        "A": {"status": "MEASURED", "byte_identical": True},
        "A_early": {"status": "MEASURED", "byte_identical": True},
        "B": {"status": "MEASURED", "byte_identical": True}})
    row = aud.audit_row(CHORUS, CHORUS_CARRIER, "/nonexistent",
                        {"available": True}, surgepy=object(),
                        c_runner=lambda *_a, **_k: c)
    assert row["status"] == "FAIL"
    assert row["escalation"]["route"].startswith("#12")
    assert row["escalation"]["committed_verdict"] == "PASS"
    assert row["escalation"]["correct_boundary_verdict"] == "FAIL"
    # NC-C shape: the wrong (production) boundary PASSes -> control FAILs
    assert row["nc_c_control"]["status"] == "FAIL"


def test_missing_fixture_is_a_reasoned_not_run():
    carrier = {"slug": "no-such-carrier", "seq": "seq-poly-8-v1",
               "leaf": "SXT-028c (fx:Chorus)"}
    row = aud.audit_row(CHORUS, carrier, "/nonexistent",
                        {"available": False},
                        c_runner=lambda *_a, **_k: pytest.fail("ran C"))
    assert row["status"] == "NOT_RUN"
    assert "no committed fixture sidecar" in row["reason"]


# ------------------------------------- baselines, definitions, lengths
def test_refused_comparator_record_is_rejected():
    with pytest.raises(aud.AuditRefused, match="no channels"):
        aud.validate_compare_record(
            {"verdict": "NO_VERDICT (refused)", "reason": "x"})


@pytest.mark.parametrize("drop", ["R", "mono"])
def test_missing_channel_is_rejected(drop):
    rec = committed("reports/SXT-028c/artifacts/"
                    "compare-fmcombo__seq-notes-coverage-v1.json")
    del rec["channels"][drop]
    with pytest.raises(aud.AuditRefused, match="channel %s missing" % drop):
        aud.validate_compare_record(rec)


def test_missing_metric_is_rejected():
    rec = committed("reports/SXT-028c/artifacts/"
                    "compare-fmcombo__seq-notes-coverage-v1.json")
    del rec["channels"]["L"]["spectral_corr"]
    with pytest.raises(aud.AuditRefused, match="lacks spectral_corr"):
        aud.validate_compare_record(rec)


def test_metric_delta_refuses_mixed_definitions():
    import compare_audio_reference as car
    base = chorus_baseline_metrics()
    other = json.loads(json.dumps(base))
    other["spectral_corr_definition"] = "legacy-log1p"
    with pytest.raises(aud.AuditRefused, match="incompatible"):
        aud.metric_delta(base, other, car.SPECTRAL_CORR_DEFINITION)


def test_metric_delta_refuses_unequal_lengths_and_keeps_channels():
    import compare_audio_reference as car
    base = chorus_baseline_metrics()
    d = aud.metric_delta(base, base, car.SPECTRAL_CORR_DEFINITION)
    assert set(d) == {"L", "R", "mono"}
    assert all(v == 0 for ch in d.values() for v in ch.values())
    short = json.loads(json.dumps(base))
    short["channels"]["L"]["frames"] -= 32
    with pytest.raises(aud.AuditRefused, match="equal-length"):
        aud.metric_delta(base, short, car.SPECTRAL_CORR_DEFINITION)


def test_equal_length_check_refuses_truncated_model(tmp_path):
    ref, mod = tmp_path / "ref.wav", tmp_path / "mod.wav"
    write_wav(str(ref), 64)
    write_wav(str(mod), 32)
    with pytest.raises(aud.AuditRefused, match="no truncation"):
        aud.equal_length_check(str(ref), str(mod))
    write_wav(str(mod), 64)
    assert aud.equal_length_check(str(ref), str(mod)) == 64


# ---------------------------------------------- committed-record provenance
def test_committed_ab_record_is_tied_to_the_committed_fixture():
    """The #136 A/B record's short-settle buffer IS the committed anchor
    fixture: the audit may ingest it rather than re-run the probe."""
    from compare_chorus_reference import read_wav_stereo_f32
    runner = "run_distortion_sse_model.py"
    carrier = aud.RUNNERS[runner]["carriers"][0]
    ab = aud.committed_ab(runner, carrier)
    assert ab["A"]["byte_identical"] and ab["B"]["byte_identical"]
    buf, _ = read_wav_stereo_f32(os.path.join(
        REPO, "reports", "SXT-028e-sse", "fixtures",
        "syn-d0-m3__seq-poly-8-v1-original.f32.wav"))
    assert aud.sha256_buf(buf) == ab["a_short_buffer_sha256"]


def per_leaf_records():
    out = {}
    for runner in aud.RUNNERS:
        p = os.path.join(OUT, "%s.json" % aud.leaf_file(runner))
        if os.path.exists(p):
            out[runner] = committed(os.path.relpath(p, REPO))
    return out


def test_every_runner_has_a_committed_audit_record():
    assert set(per_leaf_records()) == set(aud.RUNNERS)


def test_committed_rows_use_only_the_status_vocabulary():
    for runner, rec in per_leaf_records().items():
        assert rec["rows"], runner
        for r in rec["rows"]:
            assert r["status"] in aud.STATUSES, (runner, r)


def test_no_committed_row_passes_without_measured_a_and_b():
    for runner, rec in per_leaf_records().items():
        for r in rec["rows"]:
            a = r.get("A_settle_length_invariance") or {}
            if r["status"] == "PASS":
                assert a.get("status") == "MEASURED", (runner, r["carrier"])
                assert r["boundary"]["status"] == "RESOLVED"
                assert r["coverage"] == "A,B,C"
            if a.get("status") in ("BLOCKED", "NOT_RUN"):
                assert r["status"] in ("BLOCKED", "NOT_RUN"), \
                    (runner, r["carrier"])


def test_committed_rows_carry_both_preroll_results_and_provenance():
    for runner, rec in per_leaf_records().items():
        env = rec["environment"]
        for k in ("platform", "python", "numpy", "source_revision",
                  "engine_commit", "oracle_manifest_sha256"):
            assert env.get(k), (runner, k)
        assert env["engine_commit"] == aud.ENGINE_PIN
        for r in rec["rows"]:
            c = r.get("C_model_boundary_vs_engine")
            if not c:
                assert r["status"] in ("NOT_RUN", "BLOCKED", "NO_VERDICT")
                assert r.get("reason"), (runner, r)
                continue
            assert len(c["legs"]) >= 2, (runner, r["carrier"])
            assert str(r["runner_preroll_blocks"]) in c["legs"]
            for leg in c["legs"].values():
                assert set(leg["metrics"]["channels"]) == {"L", "R", "mono"}
            fx = r["fixture"]
            assert fx["sidecar_sha256"] and fx["sequence_file_sha256"]
            assert fx["block_size"] == 32 and fx["settle_blocks"] == 375
            b = r["baseline"]
            assert b["status"] in ("PASS", "STALE", "NOT_RUN"), b


def test_committed_sse_row_reproduces_the_worked_example():
    """C on the #136 anchor: 0 -> 10.5 LSB, 375 -> 672,130 LSB (mono)."""
    rec = per_leaf_records()["run_distortion_sse_model.py"]
    row = rec["rows"][0]
    want = committed("reports/SXT-028e-sse/artifacts/settle-boundary.json")
    got = row["C_model_boundary_vs_engine"]["legs"]
    for pre in ("0", "375"):
        assert got[pre]["metrics"]["channels"]["mono"]["max_abs_diff_lsb"] \
            == want["C_model_boundary_vs_engine"]["silent_preroll_blocks"][
                pre]["max_abs_diff_lsb"]
    # #136's probe rule (A, B) reads this row RESOLVED/PASS; this audit's
    # stricter rule (A0 + A_early) withholds that reading, so the row is
    # NO_VERDICT with the probe reading retained alongside, never relabeled.
    assert row["boundary"]["probe_rule_v1"]["status"] == "RESOLVED"
    assert row["boundary"]["probe_rule_v1"]["runner_verdict_under_v1"] \
        == "PASS"
    assert row["status"] == "NO_VERDICT"
    assert row["A_early_settle_invariance"]["attribution"] \
        == "CONFOUNDED_SYNTH_SIDE"
    assert row["probe_rule_v1_reading_changed"]["route"].startswith("#12")
    assert row["nc_c_control"]["status"] == "NOT_RUN"
    # the wrong boundary (375) still FAILs the declared comparison (data)
    assert got["375"]["metrics"]["verdict_class"] == "FAIL"
    assert got["0"]["metrics"]["verdict_class"] == "PASS"


# ------------------------------------------------- source reconciliation
@pytest.mark.parametrize("pre,want", [(0, "PASS"), (375, "PASS"),
                                      (240, "FAIL"), (374, "FAIL")])
def test_source_reconciliation(pre, want):
    assert aud.source_reconciliation(pre, 375)["status"] == want


def test_source_reconciliation_failure_routes_to_12_without_a_verdict():
    base = chorus_baseline_metrics()
    c = stub_c(base, failing_copy(base), 240, 375)
    esc = aud.escalation("BLOCKED", {"committed_verdict_class": "FAIL"}, c,
                         None, aud.source_reconciliation(240, 375))
    assert esc["route"].startswith("#12")
    assert esc["verdict_by_candidate_preroll"] == {"375": "FAIL"}
    assert aud.escalation("BLOCKED", {}, c, None,
                          aud.source_reconciliation(375, 375)) is None


def test_metric_reproduction_tolerates_rounding_not_a_real_change():
    base = chorus_baseline_metrics()
    ulp = json.loads(json.dumps(base))
    ulp["channels"]["mono"]["spectral_corr"] += 4e-16
    ok, worst, ints_ok = aud.metrics_deviation(base, ulp)
    assert ok and ints_ok and 0 < worst < aud.METRIC_REL_TOL
    real = json.loads(json.dumps(base))
    real["channels"]["mono"]["rms_diff_dbfs"] += 0.01
    assert not aud.metrics_deviation(base, real)[0]
    shifted = json.loads(json.dumps(base))
    shifted["channels"]["R"]["best_shift"] += 1
    assert not aud.metrics_deviation(base, shifted)[0]


# ------------------------------------------ A0 repeatability (fail-closed)
@pytest.mark.parametrize("a,b", [(True, True), (False, True), (None, None),
                                 (True, None)])
def test_unrepeatable_live_render_is_unresolved(a, b):
    """A render that does not reproduce itself cannot support ANY byte-
    identity reading: a nondeterministic engine would otherwise read as
    'the effect evolved during the settle' (or, worse, as identity)."""
    assert aud.decide_boundary(a, b, repeatable=False) == ("UNRESOLVED", None)


def test_measured_repeatability_leaves_the_rule_unchanged():
    assert aud.decide_boundary(True, True, True, True) == ("RESOLVED", 0)
    assert aud.decide_boundary(None, None, repeatable=None) == \
        ("NOT_MEASURED", None)


def test_a_early_failure_is_no_verdict_and_keeps_the_v1_reading(monkeypatch):
    """fm_bass_1's measured shape: A and B identical, A_early differs. The
    probe's rule would RESOLVE 0 and FAIL the runner; this audit reports
    NO_VERDICT and records the changed reading for #12 instead of hiding
    either one."""
    base = chorus_baseline_metrics()
    c = stub_c(base, failing_copy(base), 375, 0)
    monkeypatch.setattr(aud, "live_ab_factory", lambda *_a, **_k: {
        "source": "test",
        "A0_repeatability": {"status": "MEASURED",
                             "all_buses_repeatable": True},
        "A": {"status": "MEASURED", "byte_identical": True},
        "A_early": {"status": "MEASURED", "byte_identical": False},
        "B": {"status": "MEASURED", "byte_identical": True}})
    row = aud.audit_row(CHORUS, CHORUS_CARRIER, "/nonexistent",
                        {"available": True}, surgepy=object(),
                        c_runner=lambda *_a, **_k: c)
    assert row["boundary"]["status"] == "UNRESOLVED"
    assert row["status"] == "NO_VERDICT"
    assert "A_early DIFFERS" in row["runner_boundary_verdict"]["reason"]
    v1 = row["boundary"]["probe_rule_v1"]
    assert v1["status"] == "RESOLVED" and v1["runner_verdict_under_v1"] == \
        "FAIL"
    ch = row["probe_rule_v1_reading_changed"]
    assert ch["under_probe_rule_v1"] == "FAIL"
    assert ch["under_this_audit"] == "NO_VERDICT"
    assert ch["committed_verdict"] == "PASS"
    assert ch["verdict_at_v1_declared_preroll"] == "FAIL"
    assert ch["route"].startswith("#12")


def test_a0_failure_is_no_verdict_even_with_identical_a_and_b(monkeypatch):
    base = chorus_baseline_metrics()
    c = stub_c(base, failing_copy(base), 375, 0)
    monkeypatch.setattr(aud, "live_ab_factory", lambda *_a, **_k: {
        "source": "test",
        "A0_repeatability": {"status": "MEASURED",
                             "all_buses_repeatable": False},
        "A": {"status": "MEASURED", "byte_identical": True},
        "B": {"status": "MEASURED", "byte_identical": True}})
    row = aud.audit_row(CHORUS, CHORUS_CARRIER, "/nonexistent",
                        {"available": True}, surgepy=object(),
                        c_runner=lambda *_a, **_k: c)
    assert row["boundary"]["status"] == "UNRESOLVED"
    assert row["status"] == "NO_VERDICT"
    assert "A0 FAIL" in row["runner_boundary_verdict"]["reason"]
    assert row["D_settle_tracking"]["status"] == "NOT_RUN"


def test_ab_only_row_without_oracle_is_blocked_never_pass():
    runner = "run_phaser_model.py"
    carrier = aud.RUNNERS[runner]["ab_only_carriers"][0]
    row = aud.ab_only_row(runner, carrier, "/nonexistent",
                          {"available": False})
    assert row["status"] == "BLOCKED"
    assert row["C_model_boundary_vs_engine"] is None
    assert "NOT_RUN" in row["C_reason"]


def test_ab_only_carriers_are_the_leaf_renderers_queue():
    """The Phaser A/B-only carriers are exactly the presets the leaf's own
    renderer queues (source-read, no import: the renderer is oracle-gated)."""
    import ast
    src = open(os.path.join(REPO, "tools", "render_phaser_fixtures.py")).read()
    presets = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(
                node.targets[0], "id", None) == "PRESETS":
            presets = ast.literal_eval(node.value)
    got = {(c["slug"], c["preset"])
           for c in aud.RUNNERS["run_phaser_model.py"]["ab_only_carriers"]}
    assert got == set(presets.items())


# ---------------------------------------------------- oracle identity
def _prebuilt(tmp_path, commit=None, sha=None, write_sha=True):
    man = committed("oracle/manifest.json")
    (tmp_path / "BUILDINFO.json").write_text(json.dumps({
        "engine_commit": commit or man["engine"]["commit"],
        "platform": "linux-x86_64"}))
    if write_sha:
        (tmp_path / ".installed-sha256").write_text(
            (sha or man["prebuilt"]["linux-x86_64"]["sha256"]) + "\n")
    return aud.oracle_identity(str(tmp_path))


def test_oracle_identity_accepts_the_manifest_prebuilt(tmp_path):
    idn = _prebuilt(tmp_path)
    assert idn["matches_manifest"] and idn["kind"].startswith("prebuilt")


@pytest.mark.parametrize("kw", [{"commit": "0" * 40}, {"sha": "f" * 64},
                                {"write_sha": False}])
def test_oracle_identity_refuses_a_foreign_prebuilt(tmp_path, kw):
    assert not _prebuilt(tmp_path, **kw)["matches_manifest"]


def test_source_build_identity_defers_to_the_drift_gate(tmp_path):
    idn = aud.oracle_identity(str(tmp_path))
    assert idn["matches_manifest"] and "source build" in idn["kind"]


# ------------------------------------------------------ diagnostics
def test_diff_stats_locates_the_first_differing_block():
    import numpy as np
    a = np.zeros((2, 320), dtype=np.float32)
    b = a.copy()
    assert aud.diff_stats(a, b)["frames_differing"] == 0
    assert aud.diff_stats(a, b)["first_differing_block"] is None
    b[1, 70] = 2.0 ** -21
    d = aud.diff_stats(a, b)
    assert d["first_differing_frame"] == 70
    assert d["first_differing_block"] == 2
    assert d["max_abs_diff_lsb_q10_21"] == 1.0
    assert "shape_mismatch" in aud.diff_stats(a, b[:, :32])


# ------------------------------------------- leg D scratch bundle
def _fake_buses(frames, repeatable=True, slots=()):
    import numpy as np
    z = np.zeros((2, frames), dtype=np.float32)
    names = ["wet", "dry"] + ["bypass_fx%d" % k for k in slots]
    return {"%s_%d" % (n, t): aud._Bus(z, ["h" * 64] * aud.LIVE_REPEATS,
                                       repeatable)
            for n in names for t in (375, 3750)}


@pytest.mark.parametrize("blocks", [2, 32, 120, 240, 375, 3750])
def test_settle_s_for_is_exact_in_the_renderers_arithmetic(blocks):
    s = aud.settle_s_for(blocks)
    assert int(s * 48000) // 32 == blocks


@pytest.mark.parametrize("n", [375, 3750])
def test_d_bundle_is_a_declared_scratch_fixture(tmp_path, n):
    import compare_audio_reference as car
    c = CHORUS_CARRIER
    sc_path = os.path.join(REPO, "reports", "SXT-028c", "fixtures",
                           "%s__%s.json" % (c["slug"], c["seq"]))
    side = committed(os.path.relpath(sc_path, REPO))
    out, ref = aud.d_bundle(CHORUS, c, side, sc_path,
                            _fake_buses(side["render"]["frames"]), n,
                            str(tmp_path / "fx"))
    assert os.path.exists(ref)
    sc = json.load(open(os.path.join(out, "%s__%s.json"
                                     % (c["slug"], c["seq"]))))
    assert int(sc["render"]["settle_s"] * 48000) // 32 == n
    assert sc["audit_scratch"]["settle_blocks"] == n
    assert sc["wet"]["sha256"] == aud.sha256_file(sc["wet"]["wav"])
    assert sc["determinism_gate"]["bit_identical"] is True
    assert not sc["wet"]["wav"].startswith(os.path.join(REPO, "reports"))
    car.declared_tail_region(os.path.join(out, "%s__%s.json"
                                          % (c["slug"], c["seq"])), "wet")


def test_d_bundle_carries_a_failed_gate_and_refuses_wrong_length(tmp_path):
    c = CHORUS_CARRIER
    sc_path = os.path.join(REPO, "reports", "SXT-028c", "fixtures",
                           "%s__%s.json" % (c["slug"], c["seq"]))
    side = committed(os.path.relpath(sc_path, REPO))
    frames = side["render"]["frames"]
    out, _ref = aud.d_bundle(CHORUS, c, side, sc_path,
                             _fake_buses(frames, repeatable=False), 375,
                             str(tmp_path / "a"))
    sc = json.load(open(os.path.join(out, "%s__%s.json"
                                     % (c["slug"], c["seq"]))))
    assert sc["determinism_gate"]["bit_identical"] is False
    with pytest.raises(aud.AuditRefused, match="frames"):
        aud.d_bundle(CHORUS, c, side, sc_path, _fake_buses(frames - 32),
                     375, str(tmp_path / "b"))


# ------------------------------------------- NC-D: D must discriminate
def _d(verdicts):
    return {"status": "MEASURED", "by_settle": {
        n: {"comparator_verdict_by_preroll": v} for n, v in verdicts.items()}}


def test_nc_d_passes_only_when_every_mismatched_preroll_fails():
    ok = _d({"375": {"0": "FAIL", "375": "PASS"},
             "3750": {"0": "FAIL", "375": "FAIL", "3750": "PASS"}})
    assert aud.nc_d_control(ok)["status"] == "PASS"
    blind = _d({"375": {"0": "PASS", "375": "PASS"},
                "3750": {"0": "PASS", "375": "PASS", "3750": "PASS"}})
    r = aud.nc_d_control(blind)
    assert r["status"] == "FAIL"
    assert r["mismatched_verdicts"]["settle 3750 / pre-roll 375"] == "PASS"
    assert aud.nc_d_control({"status": "NOT_RUN"})["status"] == "NOT_RUN"


def test_nc_d_never_decides_the_boundary():
    """Even a perfectly discriminating D leaves an UNRESOLVED row NO_VERDICT:
    the boundary decision takes A0/A/A_early/B only."""
    import inspect
    assert set(inspect.signature(aud.decide_boundary).parameters) == {
        "a_identical", "b_identical", "repeatable", "a_early_identical"}


def test_attribute_a_early_confounded_by_dry_difference():
    ae = {"status": "MEASURED", "byte_identical": False,
          "dry_diagnostic_byte_identical": False}
    assert aud.attribute_a_early(dict(ae))["attribution"] \
        == "CONFOUNDED_SYNTH_SIDE"
    ae["dry_diagnostic_byte_identical"] = True
    assert aud.attribute_a_early(dict(ae))["attribution"] == "EFFECT_SIDE"
    ae["dry_diagnostic_byte_identical"] = None
    assert aud.attribute_a_early(dict(ae))["attribution"] == "UNATTRIBUTED"
    assert "attribution" not in aud.attribute_a_early(
        {"status": "MEASURED", "byte_identical": True})
