#!/usr/bin/env python3
"""Store a run's raw outputs in the artifact store; commit only a manifest.

Usage:
    python3 tools/store_evidence.py --bench BENCH --run-id RUN SCRATCH_DIR

Every regular file under SCRATCH_DIR is stored with `klt artifact put`; the
entries are merged into `manifests/artifacts/<bench>-<run-id>.manifest.json`
and a Markdown summary (name, size, sha256, uri) is written beside it. Stage
raw outputs in the git-ignored `.evidence-scratch/` directory.

Fails closed: if $KLT_ARTIFACT_BROKER is unset or empty, `klt` is missing or
lacks `artifact put`, the broker is unreachable, or the resulting manifest
does not pass the checker, the exit status is nonzero and NOTHING is written.
There is no fallback to committing bytes.

Method adapted (no code copied) from 2AMLogic/sg13g2-comparator PR #319
(merge b46d54afe3d87d619f20a94b44ceece3a29ada1b) and PR #321 (merge
9cce50129f2d35c80f7dc90f6ec4d7af56cda3df), Apache-2.0.

A manifest proves the bytes were stored and their hashes recorded. It does
not establish an RTL-vs-model, model-vs-reference, or listening claim.

Python 3 standard library only.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_artifact_manifests as chk  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
EXIT_REFUSED = 2
EXIT_STORE_FAILED = 3


class Refused(Exception):
    def __init__(self, msg, code=EXIT_REFUSED):
        super().__init__(msg)
        self.code = code


def preflight(env):
    """Fail closed before touching the scratch dir or the store."""
    if not (env.get("KLT_ARTIFACT_BROKER") or "").strip():
        raise Refused("KLT_ARTIFACT_BROKER is unset or empty")
    if shutil.which("klt", path=env.get("PATH")) is None:
        raise Refused("klt not found on PATH")
    probe = subprocess.run(["klt", "artifact", "put", "--help"],
                           capture_output=True, text=True, env=env)
    if probe.returncode != 0:
        raise Refused("this klt lacks 'artifact put' (need klayout-tools "
                      "7e3561f or later)")


def collect(scratch):
    scratch = Path(scratch)
    if not scratch.is_dir():
        raise Refused(f"scratch dir {scratch} is not a directory")
    files = []
    for p in sorted(scratch.rglob("*")):
        if p.is_symlink():
            raise Refused(f"{p} is a symlink; refusing")
        if p.is_file():
            files.append(p)
    if not files:
        raise Refused(f"no files under {scratch}")
    return files


def summary_text(bench, run_id, manifest_name, entries):
    lines = [
        f"# Evidence summary: {bench} / {run_id}",
        "",
        f"Manifest: `{manifest_name}`. Raw bytes are in the artifact store, "
        "not in git.",
        "",
        "This record shows that these objects were stored and which sha256 "
        "each has. It makes no RTL-vs-model, model-vs-reference, or "
        "listening claim; `klt artifact verify` has to be run separately to "
        "check the store still holds them.",
        "",
        "| name | size | sha256 | uri |",
        "|---|---:|---|---|",
    ]
    for e in sorted(entries, key=lambda e: e["name"]):
        lines.append(f"| `{e['name']}` | {e['size']} | `{e['sha256']}` | "
                     f"`{e['uri']}` |")
    return "\n".join(lines) + "\n"


def store(bench, run_id, scratch, repo_root=REPO_ROOT, env=None):
    env = dict(os.environ if env is None else env)
    for label, value in (("bench", bench), ("run-id", run_id)):
        if not ID_RE.fullmatch(value):
            raise Refused(f"--{label} {value!r} is not a plain identifier")
    preflight(env)
    files = collect(scratch)
    mdir = Path(repo_root) / chk.MANIFEST_DIR
    final = mdir / f"{bench}-{run_id}{chk.MANIFEST_SUFFIX}"
    final_summary = mdir / f"{bench}-{run_id}{chk.SUMMARY_SUFFIX}"
    with tempfile.TemporaryDirectory(prefix="store-evidence-") as tmp:
        work = Path(tmp) / final.name
        if final.exists():
            shutil.copyfile(final, work)  # klt merges into existing entries
        for f in files:
            name = f.relative_to(scratch).as_posix()
            r = subprocess.run(
                ["klt", "artifact", "put", "--manifest", str(work),
                 "--name", name, str(f)],
                capture_output=True, text=True, env=env)
            if r.returncode != 0:
                tail = (r.stderr or r.stdout).strip()[-400:]
                raise Refused(f"klt artifact put failed for {name} "
                              f"(rc={r.returncode}): {tail}",
                              EXIT_STORE_FAILED)
        try:
            doc = json.loads(work.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Refused(f"klt wrote no readable manifest: {exc}",
                          EXIT_STORE_FAILED)
        text = work.read_text(encoding="utf-8")
        problems = chk.schema_problems(doc)
        summary = ""
        if not problems:
            summary = summary_text(bench, run_id, final.name, doc["entries"])
        problems += chk.forbidden_problems(text + summary, final.name)
        if problems:
            raise Refused("manifest rejected, nothing written: "
                          + "; ".join(problems), EXIT_STORE_FAILED)
        mdir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work, final)
        final_summary.write_text(summary, encoding="utf-8")
    return final, final_summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("scratch", help="directory of raw outputs to store")
    args = ap.parse_args(argv)
    try:
        manifest, summary = store(args.bench, args.run_id, args.scratch)
    except Refused as exc:
        print(f"REFUSED: {exc}\nnothing written; no fallback to committing "
              "bytes.", file=sys.stderr)
        return exc.code
    print(f"wrote {manifest}\nwrote {summary}\ncommit these two files only; "
          f"next: klt artifact verify {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
