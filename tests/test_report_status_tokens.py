#!/usr/bin/env python3
"""#365 -- committed report verdict tokens conform to the six-status vocabulary.

PINS: every string under `status`/`verdict`/`comparison`/`result` in committed
`reports/**/*.json` is a canonical status (optionally with a free-text
qualifier) or is in the reviewed `docs/report-status-allowlist.json`; the
allowlist never maps an extra token to PASS nor a refusal to a pass-like
meaning.  Live negative controls run on temporary copies.

DOES NOT: establish that any recorded result is correct, nor endorse tokens
allowlisted as NON_VERDICT/OPEN as verdicts.  Vocabulary only.
"""

import copy
import importlib.util
import json
import os
import shutil

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "audit_report_status_tokens",
    os.path.join(REPO, "tools", "audit_report_status_tokens.py"))
aud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aud)


@pytest.fixture(scope="module")
def allow():
    with open(aud.DEFAULT_ALLOWLIST, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def test_committed_reports_conform(allow):
    res = aud.audit(aud.DEFAULT_REPORTS, allow)
    assert res["allowlist_errors"] == []
    assert res["violations"] == [], aud.render(res)
    assert res["ok"]
    # the survey must actually have walked something (not a vacuous pass)
    assert sum(e["count"] for e in res["inventory"]["status"].values()) > 1000
    assert "REFUSED" in res["inventory"]["status"]


def test_no_allowlist_entry_maps_to_pass(allow):
    for key, ents in allow["keys"].items():
        for tok, ent in ents.items():
            assert ent["to"] != "PASS", (key, tok)
            assert ent["reason"].strip(), (key, tok)
            if "REFUS" in tok.upper():
                assert ent["to"] in aud.REFUSAL_OK_TARGETS


def test_refused_maps_to_not_run(allow):
    assert allow["keys"]["status"]["REFUSED"]["to"] == "NOT_RUN"


@pytest.mark.parametrize("bad", ["PASSED", "GREEN"])
def test_control_unlisted_token_fails(tmp_path, allow, bad):
    d = str(tmp_path / "reports")
    shutil.copytree(aud.DEFAULT_REPORTS, d)
    _write(os.path.join(d, "zz-control", "x.json"), {"status": bad})
    res = aud.audit(d, allow)
    assert not res["ok"]
    assert [(k, t) for k, t, _ in res["violations"]] == [("status", bad)]


def test_control_unlisted_token_in_every_key_fails(tmp_path, allow):
    d = str(tmp_path / "reports")
    _write(os.path.join(d, "a.json"),
           {"a": {"verdict": "GREEN"}, "b": [{"comparison": "OKAY"}],
            "c": {"result": "PASSED"}})
    res = aud.audit(d, allow)
    assert {k for k, _, _ in res["violations"]} == {
        "verdict", "comparison", "result"}


def test_control_refused_removed_from_allowlist_fails(tmp_path, allow):
    a = copy.deepcopy(allow)
    del a["keys"]["status"]["REFUSED"]
    res = aud.audit(aud.DEFAULT_REPORTS, a)
    assert not res["ok"]
    assert ("status", "REFUSED") in [(k, t) for k, t, _ in res["violations"]]


def test_control_extra_token_mapped_to_pass_rejected(allow):
    a = copy.deepcopy(allow)
    a["keys"]["status"]["REFUSED"]["to"] = "PASS"
    res = aud.audit(aud.DEFAULT_REPORTS, a)
    assert not res["ok"]
    assert any("never map to PASS" in e for e in res["allowlist_errors"])
    a2 = copy.deepcopy(allow)
    a2["keys"]["status"]["REFUSED"]["to"] = "NON_VERDICT"
    assert any("refusal" in e for e in aud.validate_allowlist(a2))
    a3 = copy.deepcopy(allow)
    a3["keys"]["status"]["VERIFIED"]["to"] = "PASS"
    assert not aud.audit(aud.DEFAULT_REPORTS, a3)["ok"]


def test_prefix_does_not_match_inside_a_longer_word(allow):
    assert aud.classify("status", "PASSED", allow)[0] == "violation"
    assert aud.classify("status", "PASS-ISH", allow)[0] == "violation"
    assert aud.classify("status", "PASS (note)", allow)[:2] == ("qualified", "PASS")
    assert aud.classify("status", "REFUSED", allow)[:2] == ("allowlisted", "NOT_RUN")


def test_cli_exit_codes(tmp_path, capsys):
    assert aud.main([]) == 0
    d = str(tmp_path / "r")
    _write(os.path.join(d, "a.json"), {"status": "GREEN"})
    assert aud.main(["--reports", d]) == 1
    assert "VIOLATION" in capsys.readouterr().out


def test_sxt013_dry_run_status_stays_not_listening_evidence(allow):
    # The SXT-013 machine dry-run is allowlisted as NOT_RUN (human listening
    # did not run), never a pass; `comparison: dry` is a render-kind descriptor.
    assert aud.classify("status", "DRY_RUN_NOT_HUMAN_LISTENING", allow)[:2] == (
        "allowlisted", "NOT_RUN")
    assert aud.classify("comparison", "dry", allow)[:2] == (
        "allowlisted", "NON_VERDICT")
    # Live control: without the entry, the committed SXT-013 record fails.
    a = copy.deepcopy(allow)
    del a["keys"]["status"]["DRY_RUN_NOT_HUMAN_LISTENING"]
    res = aud.audit(aud.DEFAULT_REPORTS, a)
    assert not res["ok"]
    assert ("status", "DRY_RUN_NOT_HUMAN_LISTENING") in [
        (k, t) for k, t, _ in res["violations"]]
