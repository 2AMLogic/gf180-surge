"""#532 -- fail-closed evidence writer (klt stubbed, no network).

PINS: with the broker unset/empty, klt missing, klt lacking `artifact put`,
or `put` failing, the writer exits nonzero and writes nothing; on success it
writes a checker-clean manifest plus summary and merges into an existing one.
DOES NOT: exercise the real broker (see the PR for klt artifact verify).
"""
import importlib.util
import json
import os
import stat
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "store_evidence", os.path.join(REPO, "tools", "store_evidence.py"))
se = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(se)

# Fake klt: `put --help` succeeds unless FAKE_NO_PUT; `put` merges entries
# into --manifest like the real client, or fails when FAKE_PUT_FAIL is set.
FAKE_KLT = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
a = sys.argv[1:]
if a[:2] != ["artifact", "put"]:
    sys.exit(64)
if "--help" in a:
    sys.exit(2 if os.environ.get("FAKE_NO_PUT") else 0)
if os.environ.get("FAKE_PUT_FAIL"):
    sys.stderr.write("broker unreachable\n"); sys.exit(1)
man = a[a.index("--manifest") + 1]
name = a[a.index("--name") + 1]
path = a[-1]
data = open(path, "rb").read()
sha = hashlib.sha256(data).hexdigest()
doc = json.load(open(man)) if os.path.exists(man) else {"schema_version": 1, "entries": []}
doc["entries"] = [e for e in doc["entries"] if e["name"] != name]
doc["entries"].append({"sha256": sha, "size": len(data), "kind": "evidence",
    "producer": {"tool": "klt"}, "uri": "artifact:evidence/o__r/%s/%s" % (sha[:2], sha),
    "name": name})
json.dump(doc, open(man, "w"))
'''


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    klt = bindir / "klt"
    klt.write_text(FAKE_KLT)
    klt.chmod(klt.stat().st_mode | stat.S_IXUSR)
    e = {"PATH": f"{bindir}:{os.environ['PATH']}",
         "KLT_ARTIFACT_BROKER": "https://broker.invalid"}
    return e


@pytest.fixture
def scratch(tmp_path):
    d = tmp_path / "scratch"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("alpha")
    (d / "sub" / "b.txt").write_text("beta")
    return d


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    return r


def _nothing_written(root):
    return not (root / "manifests").exists()


def _run(root, scratch, env, **kw):
    return se.store("bench", "r1", scratch, repo_root=root, env=env, **kw)


def test_success_writes_manifest_and_summary(root, scratch, env):
    manifest, summary = _run(root, scratch, env)
    doc = json.loads(manifest.read_text())
    assert sorted(e["name"] for e in doc["entries"]) == ["a.txt", "sub/b.txt"]
    assert all(e["uri"].startswith("artifact:") for e in doc["entries"])
    text = summary.read_text()
    assert all(e["sha256"] in text for e in doc["entries"])
    assert "makes no RTL-vs-model" in text
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    cm = se.chk
    problems, _ = cm.check_tree(root)
    assert problems == []


def test_broker_unset_fails_closed(root, scratch, env):
    del env["KLT_ARTIFACT_BROKER"]
    with pytest.raises(se.Refused, match="BROKER"):
        _run(root, scratch, env)
    assert _nothing_written(root)


def test_broker_empty_fails_closed(root, scratch, env):
    env["KLT_ARTIFACT_BROKER"] = "  "
    with pytest.raises(se.Refused, match="BROKER"):
        _run(root, scratch, env)
    assert _nothing_written(root)


def test_klt_missing_fails_closed(root, scratch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {"PATH": str(empty), "KLT_ARTIFACT_BROKER": "https://b.invalid"}
    with pytest.raises(se.Refused, match="klt not found"):
        _run(root, scratch, env)
    assert _nothing_written(root)


def test_klt_lacking_put_fails_closed(root, scratch, env):
    env["FAKE_NO_PUT"] = "1"
    with pytest.raises(se.Refused, match="lacks 'artifact put'"):
        _run(root, scratch, env)
    assert _nothing_written(root)


def test_broker_unreachable_fails_closed(root, scratch, env):
    env["FAKE_PUT_FAIL"] = "1"
    with pytest.raises(se.Refused) as ei:
        _run(root, scratch, env)
    assert ei.value.code == se.EXIT_STORE_FAILED
    assert _nothing_written(root)


def test_empty_scratch_refused(root, tmp_path, env):
    d = tmp_path / "empty-scratch"
    d.mkdir()
    with pytest.raises(se.Refused, match="no files"):
        _run(root, d, env)
    assert _nothing_written(root)


def test_symlink_in_scratch_refused(root, scratch, env):
    os.symlink("/etc/hostname", scratch / "link")
    with pytest.raises(se.Refused, match="symlink"):
        _run(root, scratch, env)
    assert _nothing_written(root)


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".hidden/.."])
def test_bad_identifiers_refused(root, scratch, env, bad):
    with pytest.raises(se.Refused):
        se.store(bad, "r1", scratch, repo_root=root, env=env)
    assert _nothing_written(root)


def test_merge_into_existing_manifest(root, scratch, env):
    manifest, _ = _run(root, scratch, env)
    (scratch / "c.txt").write_text("gamma")
    manifest, _ = _run(root, scratch, env)
    names = sorted(e["name"] for e in json.loads(manifest.read_text())["entries"])
    assert names == ["a.txt", "c.txt", "sub/b.txt"]


def test_failed_rerun_leaves_existing_manifest_intact(root, scratch, env):
    manifest, summary = _run(root, scratch, env)
    before = (manifest.read_bytes(), summary.read_bytes())
    (scratch / "z.txt").write_text("late")
    env["FAKE_PUT_FAIL"] = "1"
    with pytest.raises(se.Refused):
        _run(root, scratch, env)
    assert (manifest.read_bytes(), summary.read_bytes()) == before


def test_main_exit_codes(scratch, env, monkeypatch, capsys):
    monkeypatch.delenv("KLT_ARTIFACT_BROKER", raising=False)
    rc = se.main(["--bench", "b", "--run-id", "r", str(scratch)])
    assert rc == se.EXIT_REFUSED
    assert "nothing written" in capsys.readouterr().err
