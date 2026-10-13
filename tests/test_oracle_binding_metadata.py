"""first-note.json compatibility and capture integration for oracle_binding (#436).

Uses an engine double: this establishes integration only, not native load or
reference agreement.
"""

import json
import os
import sys
import types

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import oracle_common as oc  # noqa: E402
import capture_first_note as cfn  # noqa: E402

HIST = os.path.join(REPO, "reports", "sxt-010", "first-capture", "first-note.json")
BINDING_KEYS = {"module_path", "module_sha256", "build_dir"}


def check_binding(b):
    assert set(b) == BINDING_KEYS
    assert os.path.isabs(b["module_path"]) and os.path.isabs(b["build_dir"])
    assert len(b["module_sha256"]) == 64 and int(b["module_sha256"], 16) >= 0


def test_historical_record_readable_without_binding():
    d = json.load(open(HIST))
    assert "oracle_binding" not in d
    assert d["issue"] == "SXT-010" and "files" in d


def test_provenance_requires_validated_module():
    with pytest.raises(oc.OracleBindingError):
        oc.binding_provenance(types.ModuleType("surgepy"))


class _Engine:
    def getBlockSize(self):
        return 32

    def loadPatch(self, p):
        return True

    def playNote(self, *a):
        pass

    def allNotesOff(self):
        pass

    def createMultiBlock(self, blocks):
        return np.zeros((2, blocks * 32))

    def processMultiBlock(self, buf):
        buf[:] = 0.25


def test_capture_emits_additive_oracle_binding(tmp_path, monkeypatch):
    fake = types.ModuleType("surgepy")
    fake.createSurge = lambda sr: _Engine()
    prov = {"module_path": "/x/surgepy.so", "module_sha256": "a" * 64, "build_dir": "/x"}
    monkeypatch.setattr(oc, "import_surgepy", lambda: fake)
    monkeypatch.setattr(oc, "binding_provenance", lambda m: prov if m is fake else 1 / 0)
    monkeypatch.setattr(oc, "reexec_under_pinned_python", lambda r: None)
    monkeypatch.setattr(oc, "apply_engine_env", lambda: None)
    monkeypatch.setattr(oc, "git_blob_sha1", lambda p: cfn.PRESET_CENSUS_SHA)
    repo = tmp_path / "repo"
    (repo / "oracle").mkdir(parents=True)
    (repo / "oracle" / "manifest.json").write_text(
        open(os.path.join(REPO, "oracle", "manifest.json")).read())
    monkeypatch.setattr(cfn.os.path, "dirname", cfn.os.path.dirname)  # no-op, keep real
    orig_abspath = cfn.os.path.abspath
    monkeypatch.setattr(cfn.os.path, "abspath",
                        lambda p: str(repo / "oracle" / "capture_first_note.py")
                        if p == cfn.__file__ else orig_abspath(p))
    assert cfn.main() == 0
    new = json.load(open(repo / "reports" / "sxt-010" / "first-capture" / "first-note.json"))
    check_binding(new["oracle_binding"])
    hist = json.load(open(HIST))
    assert set(new) - {"oracle_binding"} == set(hist)
    assert new["oracle_binding"] == prov
