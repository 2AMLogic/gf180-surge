"""SXT-036 (#70) oracle-gate probe tests (pytest, no iverilog, no oracle).

Covers the sixth increment's oracle-independent machinery: the strict reading
of the oracle gate (a bare `import surgepy` is not proof of the pin), the
fail-closed refusals, the leg-status vocabulary that can never emit PASS, the
named-tool resolution table, and the consolidated backfill predictions.

These are bookkeeping tests. They establish nothing about model-vs-pinned-
engine agreement (item 2, NOT_RUN on this host, #96), nothing about the
reference-budget controls (item 5, NOT_RUN), and nothing about fidelity or
sound quality. The whole point of the module under test is to make those
NOT_RUN statuses MEASURED rather than asserted -- these tests check that the
measurement cannot be talked into a pass.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import vel_oracle_status as vos                # noqa: E402

ARTIFACTS = os.path.join(REPO, "reports", "SXT-036", "artifacts")
STATUS_JSON = os.path.join(ARTIFACTS, "oracle-status.json")


@pytest.fixture(scope="module")
def manifest():
    return vos.load_manifest(vos.DEFAULT_MANIFEST)


@pytest.fixture(scope="module")
def committed():
    with open(STATUS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _probe(**overrides):
    """A probe dict with the fields the classifier reads, all off by default."""
    p = {
        "engine_pin": vos.ISSUE_PIN,
        "engine_dir_probed": "/nowhere",
        "engine_dir_present": False,
        "engine_dir_is_git_worktree": False,
        "engine_head": None,
        "engine_head_matches_pin": False,
        "surgepy_importable": False,
        "surgepy_under_engine_dir": False,
        "surgepy_pinned": {"ok": False, "file": None},
        "platform": "linux-x86_64",
        "prebuilt_manifest_sha256": "f" * 64,
        "prebuilt_installed_sha256_path": "/nowhere/.installed-sha256",
        "prebuilt_installed_sha256": None,
        "prebuilt_sha256_matches": False,
        "prebuilt_buildinfo_present": False,
    }
    p.update(overrides)
    return p


# ------------------------------------------------------------ the pin itself -
def test_manifest_pin_equals_the_commit_the_issue_pins(manifest):
    assert manifest["engine"]["commit"] == vos.ISSUE_PIN


def test_manifest_pin_drift_is_a_refusal(tmp_path):
    with open(vos.DEFAULT_MANIFEST, "r", encoding="utf-8") as f:
        m = json.load(f)
    m["engine"]["commit"] = "0" * 40
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="engine pin drift"):
        vos.load_manifest(str(p))


def test_missing_manifest_is_a_refusal(tmp_path):
    with pytest.raises(FileNotFoundError):
        vos.load_manifest(str(tmp_path / "absent.json"))


# --------------------------------------------------- the strict gate reading -
def test_full_house_is_the_only_path_to_available():
    ok = _probe(engine_dir_present=True, engine_dir_is_git_worktree=True,
                engine_head=vos.ISSUE_PIN, engine_head_matches_pin=True,
                surgepy_importable=True, surgepy_under_engine_dir=True)
    assert vos.classify(ok)[0] == "AVAILABLE"


@pytest.mark.parametrize("drop", [
    "engine_dir_present", "engine_head_matches_pin",
    "surgepy_importable", "surgepy_under_engine_dir",
])
def test_dropping_any_single_requirement_loses_available(drop):
    """No one condition may stand in for the whole gate."""
    p = _probe(engine_dir_present=True, engine_dir_is_git_worktree=True,
               engine_head=vos.ISSUE_PIN, engine_head_matches_pin=True,
               surgepy_importable=True, surgepy_under_engine_dir=True)
    p[drop] = False
    assert vos.classify(p)[0] != "AVAILABLE"


def test_importable_surgepy_outside_the_checkout_is_refused_loudly():
    """Control O1 as a unit test: a stub on PYTHONPATH is NOT the oracle."""
    p = _probe(engine_dir_present=True, engine_dir_is_git_worktree=True,
               engine_head=vos.ISSUE_PIN, engine_head_matches_pin=True,
               surgepy_importable=True, surgepy_under_engine_dir=False,
               surgepy_pinned={"ok": True, "file": "/tmp/stub/surgepy.py"})
    status, reason = vos.classify(p)
    assert status == "UNPINNED_SURGEPY"
    assert "not the pinned oracle" in reason.lower()


def test_a_plain_directory_is_not_a_checkout():
    """Control O2 as a unit test."""
    p = _probe(engine_dir_present=True, engine_dir_is_git_worktree=False)
    status, reason = vos.classify(p)
    assert status == "UNAVAILABLE"
    assert "not a git work tree" in reason


def test_a_checkout_at_the_wrong_commit_is_pin_mismatch():
    """Control O3 as a unit test: wrong HEAD is refused, not downgraded."""
    p = _probe(engine_dir_present=True, engine_dir_is_git_worktree=True,
               engine_head="a" * 40, engine_head_matches_pin=False)
    status, reason = vos.classify(p)
    assert status == "PIN_MISMATCH"
    assert "refused" in reason


def test_every_classified_status_is_in_the_documented_set():
    known = {"AVAILABLE", "PIN_MISMATCH", "UNPINNED_SURGEPY", "UNAVAILABLE"}
    for kw in ({}, {"engine_dir_present": True},
               {"engine_dir_present": True, "engine_dir_is_git_worktree": True},
               {"surgepy_importable": True}):
        assert vos.classify(_probe(**kw))[0] in known


# --------------------------------------------- prebuilt provisioning (#232) --
def test_prebuilt_sha256_match_is_a_second_path_to_available():
    """A sha256-verified prebuilt install is AVAILABLE even with no git
    checkout at all -- the whole point of accepting this provisioning shape."""
    p = _probe(engine_dir_present=True, engine_dir_is_git_worktree=False,
               prebuilt_sha256_matches=True,
               surgepy_importable=True, surgepy_under_engine_dir=True)
    assert vos.classify(p)[0] == "AVAILABLE"


def test_prebuilt_path_does_not_replace_the_git_worktree_path():
    """Dropping the git-worktree fields must not matter when prebuilt-verified
    (and conversely, a prebuilt mismatch must not break a real git checkout)."""
    git_ok = _probe(engine_dir_present=True, engine_dir_is_git_worktree=True,
                    engine_head=vos.ISSUE_PIN, engine_head_matches_pin=True,
                    surgepy_importable=True, surgepy_under_engine_dir=True,
                    prebuilt_sha256_matches=False)
    assert vos.classify(git_ok)[0] == "AVAILABLE"


@pytest.mark.parametrize("drop", [
    "engine_dir_present", "surgepy_importable", "surgepy_under_engine_dir",
])
def test_dropping_any_prebuilt_requirement_loses_available(drop):
    p = _probe(engine_dir_present=True, prebuilt_sha256_matches=True,
               surgepy_importable=True, surgepy_under_engine_dir=True)
    p[drop] = False
    assert vos.classify(p)[0] != "AVAILABLE"


def test_prebuilt_sha256_mismatch_fails_closed_even_with_real_surgepy():
    """Control O8 as a unit test: a wrong hash is refused even though the
    rest of the probe looks exactly like a real, working install -- the
    sha256 check must gate, not merely corroborate."""
    p = _probe(engine_dir_present=True, engine_dir_is_git_worktree=False,
               prebuilt_sha256_matches=False,
               surgepy_importable=True, surgepy_under_engine_dir=True)
    status, reason = vos.classify(p)
    assert status != "AVAILABLE"
    assert "prebuilt" in reason.lower() or "verified prebuilt" in reason.lower()


def test_prebuilt_sha256_match_alone_is_not_sufficient():
    """Control O9 as a unit test: a matching hash with no real surgepy build
    underneath it must not be accepted on the hash alone."""
    p = _probe(engine_dir_present=True, engine_dir_is_git_worktree=False,
               prebuilt_sha256_matches=True,
               surgepy_importable=False, surgepy_under_engine_dir=False)
    assert vos.classify(p)[0] != "AVAILABLE"


def test_platform_detection_matches_fetch_and_build_cases():
    """detect_platform() must agree with oracle/fetch-and-build.sh's own
    `--prebuilt` case statement for the two platforms it names explicitly."""
    import platform as _p
    plat = vos.detect_platform()
    if (_p.system(), _p.machine()) == ("Linux", "x86_64"):
        assert plat == "linux-x86_64"
    elif (_p.system(), _p.machine()) == ("Darwin", "arm64"):
        assert plat == "darwin-arm64"


# ------------------------------------------------- legs may never say "PASS" -
def test_unavailable_gate_marks_every_leg_not_run():
    legs = vos.build_legs("UNAVAILABLE")
    assert legs
    assert {v["status"] for v in legs.values()} == {"NOT_RUN"}
    assert all(v["reason"] for v in legs.values())


def test_available_gate_marks_legs_runnable_never_pass():
    """An available oracle makes a leg RUNNABLE -- running it is a separate act."""
    legs = vos.build_legs("AVAILABLE")
    assert {v["status"] for v in legs.values()} == {"RUNNABLE"}
    assert "PASS" not in vos.LEG_STATUS_VOCABULARY


def test_validate_legs_rejects_an_injected_pass():
    """Control O6 as a unit test."""
    legs = vos.build_legs("UNAVAILABLE")
    legs[sorted(legs)[0]]["status"] = "PASS"
    with pytest.raises(ValueError, match="may never report one as a pass"):
        vos.validate_legs(legs)


@pytest.mark.parametrize("bogus", ["PASS", "pass", "OK", "GREEN", ""])
def test_no_pass_like_status_survives_validation(bogus):
    legs = vos.build_legs("UNAVAILABLE")
    legs[sorted(legs)[0]]["status"] = bogus
    with pytest.raises(ValueError):
        vos.validate_legs(legs)


def test_both_gated_acceptance_items_are_covered_by_a_leg():
    items = {leg["item"].split()[0] for leg in vos.ORACLE_LEGS}
    assert "2" in items and "5" in items


def test_the_blob_verification_leg_needs_only_the_checkout():
    """The cheapest leg must not be bundled behind a built surgepy."""
    leg = next(x for x in vos.ORACLE_LEGS if x["name"] == "blob-verify-carriers")
    assert leg["gate"] == vos.GATE_CHECKOUT
    assert all(x["gate"] == vos.GATE_FULL for x in vos.ORACLE_LEGS
               if x["name"] != "blob-verify-carriers")


# ------------------------------------------------------ named-tool resolution -
def test_render_fixture_path_named_by_the_issue_does_not_exist():
    """#70 and EVIDENCE.md both name tools/render_fixture.py; it is not there.

    If this ever fails, the repository grew the file and the correction row
    below should be retired rather than kept as a stale redirect.
    """
    assert not os.path.exists(os.path.join(REPO, "tools", "render_fixture.py"))
    assert os.path.exists(os.path.join(REPO, "fixtures", "render_fixture.py"))


def test_every_named_tool_resolves_to_a_committed_path():
    for row in vos.resolve_named_tools():
        assert row["status"] in ("OK", "CORRECTED"), row
        assert row["resolves_to"]
        assert os.path.exists(os.path.join(REPO, row["resolves_to"]))


def test_resolver_reports_a_bogus_name_missing():
    """Control O7 as a unit test: the resolver must not rubber-stamp."""
    saved = list(vos.NAMED_TOOLS)
    try:
        vos.NAMED_TOOLS.append(("tools/no_such_tool.py", None, "test"))
        row = vos.resolve_named_tools()[-1]
    finally:
        vos.NAMED_TOOLS[:] = saved
    assert row["status"] == "MISSING"
    assert row["resolves_to"] is None


def test_sibling_patterns_the_backfill_is_modelled_on_exist():
    """The plan tells the oracle host to copy two real sibling tools."""
    for p in ("model/voice/extract_mw_inputs.py",
              "fixtures/render_mw_fixture.py",
              "tools/compare_audio_reference.py"):
        assert os.path.exists(os.path.join(REPO, p)), p


# -------------------------------------------------------------- predictions -
def test_predictions_are_read_from_the_committed_artifacts():
    pred = vos.load_predictions(ARTIFACTS)
    assert len(pred["graphs_sha256"]) == 64
    assert pred["carrier_routes"]
    assert sorted(pred["destination_extents"]) == \
        sorted(pred["frozen_destination_class"])


def test_prediction_drift_is_a_refusal(tmp_path):
    """Control O5 as a unit test."""
    import shutil
    dst = tmp_path / "artifacts"
    shutil.copytree(ARTIFACTS, dst)
    p = dst / "carrier-route-audit.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["graphs_sha256"] = "f" * 64
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="prediction drift"):
        vos.load_predictions(str(dst))


def test_a_corpus_pin_mismatch_invalidates_the_predictions(tmp_path):
    import shutil
    dst = tmp_path / "artifacts"
    shutil.copytree(ARTIFACTS, dst)
    p = dst / "carrier-route-audit.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["graphs_sha256_matches_issue_pin"] = False
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="does NOT match the sha256"):
        vos.load_predictions(str(dst))


def test_missing_prediction_source_is_a_refusal(tmp_path):
    with pytest.raises(FileNotFoundError, match="prediction source missing"):
        vos.load_predictions(str(tmp_path))


def test_predictions_carry_the_no_tuning_rule():
    pred = vos.load_predictions(ARTIFACTS)
    assert "never a tuning opportunity" in pred["rule"]


# --------------------------------------------- the committed artifact itself -
def test_committed_status_reflects_the_measured_gate_on_the_host_that_wrote_it(
        committed):
    """This file is a snapshot of whatever host last ran the tool, not a
    live probe -- so it is checked for internal consistency (the gate status
    and the gated items must agree, and a leg may never read PASS), not
    pinned to one particular gate value. #70's own backfill note: a host
    with the oracle genuinely installed (#232) is expected to flip this to
    AVAILABLE/RUNNABLE; a host without it is expected to show
    UNAVAILABLE/NOT_RUN. Both are legitimate committed snapshots."""
    gate = committed["oracle_gate"]["status"]
    expected_item_status = "RUNNABLE" if gate == "AVAILABLE" else "NOT_RUN"
    assert committed["acceptance_items_gated"] == {
        "2": expected_item_status, "5": expected_item_status}
    for leg in committed["legs"].values():
        assert leg["status"] in vos.LEG_STATUS_VOCABULARY


def test_committed_status_has_no_pass_anywhere_in_its_legs(committed):
    for name, leg in committed["legs"].items():
        assert leg["status"] in vos.LEG_STATUS_VOCABULARY, name


def test_committed_status_records_every_control_as_fired(committed):
    assert committed["controls_all_fired"] is True
    ids = {c["id"] for c in committed["controls"]}
    assert ids == {"O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8", "O9"}
    assert all(c["fired"] for c in committed["controls"])


def test_committed_status_records_the_naive_reading_as_insufficient(committed):
    """The probe records BOTH readings; that is what makes O1 falsifiable."""
    assert "surgepy_importable_naive" in committed["probe"]
    assert "surgepy_under_engine_dir" in committed["probe"]


def test_dry_run_writes_nothing_and_exits_zero(tmp_path):
    out = tmp_path / "artifacts"
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "vel_oracle_status.py"),
         "--dry-run", "--json", "--artifacts", ARTIFACTS],
        capture_output=True, text=True)
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["leaf"] == "SXT-036" and doc["issue"] == 70
    assert not out.exists()
