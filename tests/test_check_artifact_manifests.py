"""#532 -- checker for manifests/artifacts/ (schema, artifact: URIs, no bucket
strings, no stored object also committed).

PINS: the committed tree passes; each live negative control (non-artifact URI,
bucket string, tracked duplicate bytes, bad schema, tracked scratch file,
missing summary) makes the checker fail on a temporary git repo.
DOES NOT: check that objects exist in the store (klt artifact verify) or make
any fidelity claim.
"""
import copy
import hashlib
import importlib.util
import json
import os
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "check_artifact_manifests",
    os.path.join(REPO, "tools", "check_artifact_manifests.py"))
chk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chk)

DATA = b"raw evidence bytes\n"
SHA = hashlib.sha256(DATA).hexdigest()
GOOD = {
    "schema_version": 1,
    "entries": [{
        "sha256": SHA, "size": len(DATA), "kind": "evidence",
        "producer": {"tool": "klt", "version": "0"},
        "uri": f"artifact:evidence/o__r/{SHA[:2]}/{SHA}",
        "name": "out.bin", "media_type": "application/octet-stream",
    }],
}


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    return tmp_path


def _write_manifest(root, doc, stem="b-1", summary=True):
    d = root / "manifests" / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.manifest.json").write_text(json.dumps(doc))
    if summary:
        shas = " ".join(e.get("sha256", "") for e in doc.get("entries", [])
                        if isinstance(e, dict))
        (d / f"{stem}.summary.md").write_text(shas + "\n")


def _commit_all(root):
    _git(root, "add", "-A")


def test_committed_tree_passes():
    problems, cov = chk.check_tree(chk.REPO_ROOT)
    assert problems == []
    assert cov["manifests"] >= 1 and cov["entries"] >= 1


def test_good_manifest_passes(repo):
    _write_manifest(repo, GOOD)
    _commit_all(repo)
    problems, cov = chk.check_tree(repo)
    assert problems == [] and cov["manifests"] == 1


@pytest.mark.parametrize("uri", [
    "https://example.invalid/x", "s3-bucket/key", "file:///tmp/x", "artifact:",
    "artifact:has space"])
def test_negative_non_artifact_uri(repo, uri):
    doc = copy.deepcopy(GOOD)
    doc["entries"][0]["uri"] = uri
    _write_manifest(repo, doc)
    _commit_all(repo)
    problems, _ = chk.check_tree(repo)
    assert any("uri" in p for p in problems)


@pytest.mark.parametrize("bad", ["s3://bucket/key", "arn:aws:s3:::b",
                                 "b.s3.amazonaws.com", "X-Amz-Signature=1"])
def test_negative_bucket_string_anywhere(repo, bad):
    _write_manifest(repo, GOOD)
    (repo / "manifests/artifacts/b-1.summary.md").write_text(SHA + " " + bad)
    _commit_all(repo)
    problems, _ = chk.check_tree(repo)
    assert any("forbidden string" in p for p in problems)


def test_negative_tracked_duplicate_bytes(repo):
    _write_manifest(repo, GOOD)
    (repo / "reports").mkdir()
    (repo / "reports" / "copy.bin").write_bytes(DATA)
    _commit_all(repo)
    problems, cov = chk.check_tree(repo)
    assert any("also committed as reports/copy.bin" in p for p in problems)
    assert cov["tracked_files_hashed"] >= 1


def test_same_size_different_bytes_is_not_a_duplicate(repo):
    _write_manifest(repo, GOOD)
    (repo / "other.bin").write_bytes(b"x" * len(DATA))
    _commit_all(repo)
    problems, cov = chk.check_tree(repo)
    assert problems == [] and cov["tracked_files_hashed"] == 1


def test_negative_tracked_scratch_file(repo):
    _write_manifest(repo, GOOD)
    (repo / ".evidence-scratch").mkdir()
    (repo / ".evidence-scratch" / "f").write_text("different")
    _commit_all(repo)
    problems, _ = chk.check_tree(repo)
    assert any("scratch file is tracked" in p for p in problems)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version=2),
    lambda d: d.update(entries=[]),
    lambda d: d["entries"][0].update(sha256="abc"),
    lambda d: d["entries"][0].update(size=True),
    lambda d: d["entries"][0].update(kind="other"),
    lambda d: d["entries"][0].pop("producer"),
    lambda d: d["entries"][0].update(name="../escape"),
    lambda d: d["entries"].append(copy.deepcopy(d["entries"][0])),
])
def test_negative_bad_schema(repo, mutate):
    doc = copy.deepcopy(GOOD)
    mutate(doc)
    _write_manifest(repo, doc)
    _commit_all(repo)
    problems, _ = chk.check_tree(repo)
    assert problems


def test_negative_missing_summary(repo):
    _write_manifest(repo, GOOD, summary=False)
    _commit_all(repo)
    problems, _ = chk.check_tree(repo)
    assert any("missing sibling" in p for p in problems)


def test_unparsable_json_fails(repo):
    d = repo / "manifests" / "artifacts"
    d.mkdir(parents=True)
    (d / "b-1.manifest.json").write_text("{not json")
    _commit_all(repo)
    problems, _ = chk.check_tree(repo)
    assert any("unreadable JSON" in p for p in problems)


def test_no_manifests_is_not_run_not_pass(repo, capsys):
    assert chk.main(["--root", str(repo)]) == 2
    assert "NOT_RUN" in capsys.readouterr().out
