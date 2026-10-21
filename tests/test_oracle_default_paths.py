"""Oracle default-path resolution: repo-relative, env-overridable, no personal paths (#524)."""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import oracle_common as oc  # noqa: E402

DEFAULT = os.path.join(REPO, "oracle", "build", "surge")


def test_defaults_are_repo_relative(monkeypatch):
    monkeypatch.delenv("ORACLE_SURGE_DIR", raising=False)
    monkeypatch.delenv("ORACLE_SURGE_DATA", raising=False)
    assert oc.engine_dir() == DEFAULT
    assert oc.data_dir() == os.path.join(DEFAULT, "resources", "data")
    assert "/Users/" not in oc.engine_dir() + oc.data_dir()


def test_engine_dir_override_moves_data_root(monkeypatch):
    monkeypatch.setenv("ORACLE_SURGE_DIR", "/x y")
    monkeypatch.delenv("ORACLE_SURGE_DATA", raising=False)
    assert oc.engine_dir() == "/x y"
    assert oc.data_dir() == os.path.join("/x y", "resources", "data")


def test_data_override_wins(monkeypatch):
    monkeypatch.setenv("ORACLE_SURGE_DIR", "/x")
    monkeypatch.setenv("ORACLE_SURGE_DATA", "/y")
    assert oc.data_dir() == "/y"


def test_build_dir_is_gitignored():
    r = subprocess.run(["git", "check-ignore", "-q", "oracle/build/surge"], cwd=REPO)
    assert r.returncode == 0


def test_verify_only_fails_naming_default_path(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORACLE_")}
    env["ORACLE_SURGE_DIR"] = str(tmp_path / "absent")
    r = subprocess.run([os.path.join(REPO, "oracle", "fetch-and-build.sh"), "--verify-only"],
                       capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert str(tmp_path / "absent") in r.stderr


def test_no_personal_paths_in_live_sources():
    needle = "/Users/" + "joseph"
    files = ["oracle/oracle_common.py", "oracle/fetch-and-build.sh", "oracle/README.md",
             "model/oscillators/wavetable/wt_model.py", "tools/run_sxt026_checks.py",
             "tests/test_sxt026_wavetable.py", "tests/test_wt_decimation_stage.py"]
    for f in files:
        with open(os.path.join(REPO, f), encoding="utf-8") as fh:
            assert needle not in fh.read(), f
