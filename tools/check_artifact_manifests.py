#!/usr/bin/env python3
"""Check `manifests/artifacts/` -- evidence manifests that point at the store.

Method adapted (no code copied) from 2AMLogic/sg13g2-comparator PR #319
(merge b46d54afe3d87d619f20a94b44ceece3a29ada1b, manifest check + CI) and
PR #321 (merge 9cce50129f2d35c80f7dc90f6ec4d7af56cda3df, `artifact:<key>`
URIs); both Apache-2.0. Written natively for this repository.

Rules enforced:
  1. Schema: `schema_version` 1, a non-empty `entries` list; each entry has a
     64-hex `sha256`, an integer `size`, `kind` "evidence", a `producer`
     object with a `tool`, a safe relative `name`, and a `uri`.
  2. Every `uri` starts with `artifact:` (no URL, no bucket path).
  3. No file under `manifests/artifacts/` names a storage bucket, cloud
     account, or presigned-URL marker.
  4. No stored object's bytes are also committed: the sha256 of every
     git-tracked file whose size equals an entry's size is compared with the
     entry's sha256, and the scratch directory must hold no tracked file.
  5. Every manifest has a sibling `<stem>.summary.md` listing each entry's
     sha256.

A pass proves the manifests are well-formed, point at the store, and that no
stored object is also committed. It does NOT prove the objects exist in the
store (`klt artifact verify` does that, from a worker with the broker) and
establishes no RTL-vs-model, model-vs-reference, or listening claim.

Python 3 standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = "manifests/artifacts"
SCRATCH_DIR = ".evidence-scratch"
MANIFEST_SUFFIX = ".manifest.json"
SUMMARY_SUFFIX = ".summary.md"
SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"[0-9a-f]{64}")
URI_RE = re.compile(r"artifact:[A-Za-z0-9][A-Za-z0-9_./:=@+-]*")
# Substrings no committed file under manifests/artifacts/ may contain.
FORBIDDEN = ("s3://", "arn:aws:", "amazonaws.com", "X-Amz-")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def schema_problems(doc):
    """Return a list of problems with one parsed manifest document."""
    if not isinstance(doc, dict):
        return ["manifest is not a JSON object"]
    problems = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        problems.append("entries must be a non-empty list")
        return problems
    names = set()
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(e, dict):
            problems.append(f"{where} is not an object")
            continue
        sha = e.get("sha256")
        if not (isinstance(sha, str) and SHA256_RE.fullmatch(sha)):
            problems.append(f"{where}.sha256 is not 64 lowercase hex")
        if not _is_int(e.get("size")) or e["size"] < 0:
            problems.append(f"{where}.size is not a non-negative integer")
        if e.get("kind") != "evidence":
            problems.append(f"{where}.kind must be 'evidence'")
        prod = e.get("producer")
        if not (isinstance(prod, dict) and isinstance(prod.get("tool"), str)
                and prod["tool"]):
            problems.append(f"{where}.producer.tool missing")
        name = e.get("name")
        if not (isinstance(name, str) and name and not name.startswith("/")
                and ".." not in Path(name).parts and "\\" not in name):
            problems.append(f"{where}.name is not a safe relative path")
        elif name in names:
            problems.append(f"{where}.name {name!r} is duplicated")
        else:
            names.add(name)
        uri = e.get("uri")
        if not isinstance(uri, str) or not uri.startswith("artifact:"):
            problems.append(f"{where}.uri must start with 'artifact:'")
        elif not URI_RE.fullmatch(uri):
            problems.append(f"{where}.uri is not a plain artifact key")
        if "media_type" in e and not isinstance(e["media_type"], str):
            problems.append(f"{where}.media_type is not a string")
    return problems


def forbidden_problems(text, label):
    return [f"{label}: contains forbidden string {s!r}"
            for s in FORBIDDEN if s in text]


def tracked_files(root):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def duplicate_byte_problems(root, entries_by_manifest, tracked):
    """Flag tracked files whose bytes are a stored object (size, then sha)."""
    wanted = {}  # size -> {sha256: [manifest label, ...]}
    for label, entries in entries_by_manifest.items():
        for e in entries:
            if isinstance(e, dict) and _is_int(e.get("size")) \
                    and isinstance(e.get("sha256"), str):
                wanted.setdefault(e["size"], {}).setdefault(
                    e["sha256"], []).append(label)
    problems, hashed = [], 0
    for rel in tracked:
        path = Path(root) / rel
        try:
            if path.is_symlink() or not path.is_file():
                continue
            size = path.stat().st_size
        except OSError:
            continue
        if size not in wanted:
            continue
        hashed += 1
        digest = _sha256_file(path)
        for label in wanted[size].get(digest, ()):
            problems.append(
                f"{label}: stored object {digest[:12]} is also committed "
                f"as {rel}")
    return problems, hashed


def check_tree(root=REPO_ROOT):
    """Return (problems, coverage) for the repository rooted at `root`."""
    root = Path(root)
    mdir = root / MANIFEST_DIR
    problems = []
    manifests = sorted(mdir.glob("*" + MANIFEST_SUFFIX)) if mdir.is_dir() else []
    entries_by_manifest = {}
    for path in sorted(p for p in mdir.rglob("*") if p.is_file()) \
            if mdir.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        problems += forbidden_problems(text, rel)
    for path in manifests:
        rel = path.relative_to(root).as_posix()
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{rel}: unreadable JSON ({exc})")
            continue
        problems += [f"{rel}: {p}" for p in schema_problems(doc)]
        entries = doc.get("entries") if isinstance(doc, dict) else None
        entries = entries if isinstance(entries, list) else []
        entries_by_manifest[rel] = entries
        summary = path.with_name(path.name[:-len(MANIFEST_SUFFIX)]
                                 + SUMMARY_SUFFIX)
        if not summary.is_file():
            problems.append(f"{rel}: missing sibling {summary.name}")
        else:
            stext = summary.read_text(encoding="utf-8", errors="replace")
            for e in entries:
                sha = e.get("sha256") if isinstance(e, dict) else None
                if isinstance(sha, str) and sha not in stext:
                    problems.append(
                        f"{rel}: {summary.name} does not list {sha[:12]}")
    tracked = tracked_files(root)
    scratch = [t for t in tracked if t.startswith(SCRATCH_DIR + "/")]
    problems += [f"{t}: scratch file is tracked by git" for t in scratch]
    dup, hashed = duplicate_byte_problems(root, entries_by_manifest, tracked)
    problems += dup
    coverage = {
        "manifests": len(manifests),
        "entries": sum(len(v) for v in entries_by_manifest.values()),
        "tracked_files_hashed": hashed,
    }
    return problems, coverage


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(REPO_ROOT))
    args = ap.parse_args(argv)
    problems, cov = check_tree(args.root)
    print(f"coverage: {cov['manifests']} manifest(s), {cov['entries']} "
          f"entr(ies), {cov['tracked_files_hashed']} size-matched tracked "
          "file(s) hashed")
    if cov["manifests"] == 0:
        print("NOT_RUN: no manifests found; nothing was checked "
              "(coverage: none -- this is not a pass)")
        return 2
    if problems:
        for p in problems:
            print("FAIL:", p)
        return 1
    print("PASS: manifests well-formed, artifact: URIs only, no stored "
          "object committed. Existence in the store is NOT checked here "
          "(klt artifact verify).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
