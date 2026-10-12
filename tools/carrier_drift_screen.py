#!/usr/bin/env python3
"""#423 (prerequisite for #331 leaves #424-#426): reusable, shape-preserving
carrier drift screen.

Given an EXPLICIT, caller-supplied routing/occupancy shape predicate, this
helper
  1. enumerates the COMPLETE ordered candidate denominator from
     corpus/normalized/graphs.jsonl (corpus order, no sampling);
  2. verifies each candidate's corpus/census blob identity (graphs sha vs
     census git_blob_sha1, 40-hex form, census `content_verified`) BEFORE any
     native `loadPatch` inspection -- a mismatch REFUSES that candidate and it
     stays in the denominator with NO drift value;
  3. LIVE (pinned oracle, via a loader): re-verifies the blob inside the
     pinned checkout, `loadPatch()`es it (the native loader's normalized state
     is authoritative, never the raw .fxp), asks the caller's shape check to
     cross-check the predicate against that native state, then runs the SAME
     per-scene drift gate the SXT-028l tools use
     (`extract_rf_send34_inputs.drift_gate`: Single mode -> the active scene,
     other modes -> both scenes, read-back rounded to 9 decimals before the
     == 0 comparison). No new threshold, no stronger exact-zero claim.

Claims kept separate (never inferred from one another):
  * COVERAGE: candidates enumerated / attempted / screened / refused.
  * REFUSALS: per-candidate reason codes; NOT verification-status tokens.
  * DRIFT-GATE observation per candidate: PASS / FAIL, with per-scene values.
  * RUN STATUS `status` (= `coverage_status`, verification token): NOT_RUN
    (oracle absent), BLOCKED (run-level provenance/denominator refusal),
    NO_VERDICT (coverage incomplete: at least one candidate refused or
    unattempted), PASS (every candidate attempted and screened; says NOTHING
    about how many have drift 0).
  * DRIFT OUTCOME `drift_gate_status`, a separate field: FAIL if any screened
    candidate fails the gate, PASS only with complete coverage and every gate
    PASS, else NO_VERDICT. Never quote `status` PASS as drift-clean.
  * ENGINE PROVENANCE (`engine.provenance`): established in full before any
    loadPatch -- full pinned HEAD + clean tracked tree + submodule pins for a
    source checkout, or the manifest-pinned prebuilt artifact stamp/layout --
    plus the pinned Python runtime, the manifest build dir and the validated
    binding inside it. A getVersion() prefix alone is never accepted.
  * Drift gate PASS establishes only the drift screening condition. It is
    necessary, never sufficient, for render eligibility; downstream
    repeatability checks remain required. `assert_drift_gate_passed` is the
    eligibility assertion consumers must use.

Nothing here seeds RNG, zeroes drift, widens a predicate, copies oracle DSP or
assets, or parses raw .fxp. A record produced with an injected (non-live)
loader is refused by `write_record`; without the oracle the run is NOT_RUN and
no committed live evidence is touched.

CLI (run under the oracle interpreter, see oracle/fetch-and-build.sh):
  carrier_drift_screen.py --predicate-id ID --predicate pkg.mod:callable \\
      [--expected-count N] [--out PATH]
`callable(graph_record) -> bool` is the explicit predicate. Exit codes:
0 PASS, 3 NO_VERDICT, 1 BLOCKED, 2 NOT_RUN.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only.
"""

import argparse
import csv
import hashlib
import importlib
import json
import os
import platform
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import extract_rf_send34_inputs as ex  # noqa: E402
from refusal import Refuse  # noqa: E402

GRAPHS = ex.GRAPHS
CENSUS_CSV = ex.CENSUS_CSV
ORACLE_MANIFEST = os.path.join(REPO, "oracle", "manifest.json")

ENGINE_PIN = ex.ENGINE_PIN
SAMPLE_RATE = ex.SAMPLE_RATE

# The shared gate, referenced (not reimplemented) so semantics cannot drift.
DRIFT_GATE = ex.drift_gate

CLAIM_SCOPE = (
    "ENGINE-SIDE drift screen only. Nothing was rendered. Establishes NO "
    "model-vs-engine agreement, NO preset-support claim, NO musical-quality "
    "claim and NO repeatability claim: a drift-gate PASS is necessary, not "
    "sufficient, for render eligibility.")

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")

# Per-candidate refusal codes (reasons, NOT verification-status tokens).
R_NO_CENSUS_ROW = "no_census_row"
R_BAD_HASH = "invalid_blob_hash"
R_HASH_MISMATCH = "census_graphs_blob_mismatch"
R_NOT_VERIFIED = "census_content_not_verified"
R_BLOB_MISMATCH = "pinned_checkout_blob_mismatch"
R_LOAD_FAILED = "native_load_failed"
R_SHAPE_MISMATCH = "native_shape_disagreement"
R_NOT_ATTEMPTED = "not_attempted"
# Unexpected (non-Refuse) exceptions are contained per candidate, never
# allowed to abort the run, and are kept distinct from deliberate refusals.
R_LOAD_ERROR = "native_load_error"
R_SHAPE_CHECK_ERROR = "shape_check_error"
R_GATE_ERROR = "drift_gate_error"

# Engine provenance modes accepted by PinnedSurgepyLoader.open().
PROV_SOURCE = "source_checkout"
PROV_PREBUILT = "manifest_prebuilt_artifact"
PREBUILT_STAMP = ".installed-sha256"   # written by oracle/fetch-and-build.sh


class OracleAbsent(Exception):
    """The pinned oracle is not available in this environment (NOT_RUN)."""


class LoadRefusal(Refuse):
    """A per-candidate native load refusal. `code` is a refusal reason."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class RunBlocked(Refuse):
    """Run-level refusal (BLOCKED): denominator or pin provenance wrong."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canon_sha256(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     separators=(",", ":")).encode()
                          ).hexdigest()


def enumerate_candidates(predicate, graphs_path=None):
    """Every corpus graph record for which the caller's `predicate(record)` is
    truthy, in corpus order. Returns the full ordered manifest; nothing is
    dropped or sampled. Pure function of the graphs file and the predicate."""
    if not callable(predicate):
        raise RunBlocked("an explicit callable shape predicate is required")
    out = []
    with open(graphs_path or GRAPHS, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            g = json.loads(line)
            if predicate(g):
                out.append({"path": g["p"], "graphs_blob_sha1": g.get("sha"),
                            "bank": g.get("b"), "graph": g["g"]})
    return out


def load_census(census_csv=None):
    with open(census_csv or CENSUS_CSV, newline="", encoding="utf-8") as f:
        return {row["path"]: row for row in csv.DictReader(f)}


def check_provenance(cand, census):
    """Return None when the corpus identity of `cand` holds, else a
    (code, detail) refusal. Runs before any native inspection."""
    row = census.get(cand["path"])
    if row is None:
        return R_NO_CENSUS_ROW, f"preset not in census: {cand['path']}"
    g_sha, c_sha = cand["graphs_blob_sha1"], row.get("git_blob_sha1")
    for label, v in (("graphs", g_sha), ("census", c_sha)):
        if not isinstance(v, str) or not _SHA1_RE.match(v):
            return R_BAD_HASH, (f"{label} blob sha1 is not 40 lowercase hex "
                                f"for {cand['path']}: {v!r}")
    if g_sha != c_sha:
        return R_HASH_MISMATCH, (f"census/graphs blob sha1 mismatch for "
                                 f"{cand['path']}: census={c_sha} "
                                 f"graphs={g_sha}")
    if row.get("content_verified") != "True":
        return R_NOT_VERIFIED, f"census content not verified: {cand['path']}"
    return None


def input_digests(graphs_path=None, census_csv=None, manifest_path=None):
    paths = {"graphs_jsonl": graphs_path or GRAPHS,
             "census_per_preset_csv": census_csv or CENSUS_CSV,
             "oracle_manifest": manifest_path or ORACLE_MANIFEST}
    return {k: ({"sha256": sha256_file(p)} if os.path.exists(p)
                else {"sha256": None, "status": "MISSING"})
            for k, p in paths.items()}


def check_manifest_pin(manifest_path=None):
    """Refuse if oracle/manifest.json does not carry the pinned commit."""
    p = manifest_path or ORACLE_MANIFEST
    if not os.path.exists(p):
        raise RunBlocked(f"oracle manifest missing: {p}")
    with open(p, encoding="utf-8") as f:
        commit = json.load(f).get("engine", {}).get("commit")
    if commit != ENGINE_PIN:
        raise RunBlocked(f"oracle manifest engine commit {commit!r} is not "
                         f"the pin {ENGINE_PIN}")
    return commit


def run_git(args, cwd):
    """(returncode, stripped stdout) of `git -C cwd args`; never raises."""
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                           text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)
    return p.returncode, p.stdout.strip()


def host_platform_key():
    """Platform key with the same spelling oracle/fetch-and-build.sh uses."""
    s, m = platform.system(), platform.machine()
    return {("Linux", "x86_64"): "linux-x86_64",
            ("Darwin", "arm64"): "darwin-arm64"}.get((s, m),
                                                     f"{s.lower()}-{m}")


def _git_toplevel(git, d):
    rc, out = git(["rev-parse", "--show-toplevel"], d)
    return os.path.realpath(out) if rc == 0 and out else None


def _git_head(git, d):
    rc, out = git(["rev-parse", "HEAD"], d)
    return out if rc == 0 else None


def _verify_source_checkout(engine, manifest, git):
    pin = manifest["engine"]["commit"]
    head = _git_head(git, engine)
    if head != pin:
        raise RunBlocked(f"engine checkout HEAD {head!r} is not the full pin "
                         f"{pin} (a getVersion() prefix is not provenance)")
    rc, out = git(["status", "--porcelain", "--untracked-files=no",
                   "--ignore-submodules=none"], engine)
    if rc != 0:
        raise RunBlocked(f"cannot read engine tree status at {engine}: {out}")
    if out:
        raise RunBlocked(f"engine tree has modified tracked files or dirty "
                         f"submodules at {engine}: "
                         f"{out.splitlines()[:5]}")
    subs = []
    for s in manifest.get("submodules", []):
        path, spin = s["path"], s["commit"]
        sub = os.path.join(engine, path)
        if not os.path.isdir(sub):
            raise RunBlocked(f"pinned submodule not present: {path}")
        if _git_toplevel(git, sub) != os.path.realpath(sub):
            raise RunBlocked(f"pinned submodule not initialized as its own "
                             f"work tree: {path}")
        shead = _git_head(git, sub)
        if shead != spin:
            raise RunBlocked(f"submodule drift at {path}: pin {spin}, "
                             f"checkout {shead}")
        rc, link = git(["rev-parse", f"HEAD:{path}"], engine)
        if rc != 0 or link != spin:
            raise RunBlocked(f"superproject gitlink for {path} is {link!r}, "
                             f"manifest pins {spin}")
        subs.append({"path": path, "commit": shead})
    nested = []
    for s in manifest.get("nested_submodules_observed", []):
        path, spin = s["path"], s["commit"]
        sub = os.path.join(engine, path)
        if (not os.path.isdir(sub)
                or _git_toplevel(git, sub) != os.path.realpath(sub)):
            # fetch-and-build.sh tolerates absent nested submodules too.
            nested.append({"path": path, "commit": None, "status": "absent"})
            continue
        shead = _git_head(git, sub)
        if shead != spin:
            raise RunBlocked(f"nested submodule drift at {path}: pin {spin}, "
                             f"checkout {shead}")
        nested.append({"path": path, "commit": shead, "status": "verified"})
    return {"mode": PROV_SOURCE, "engine_head": head,
            "tracked_tree_clean": True, "submodules_verified": subs,
            "nested_submodules": nested,
            "expected_python": manifest["build"]["python_version"]}


def _verify_prebuilt(engine, manifest, plat):
    pin = manifest["engine"]["commit"]
    entry = manifest.get("prebuilt", {}).get(plat)
    if not entry:
        raise RunBlocked(f"{engine} is not a git checkout and the manifest "
                         f"has no prebuilt entry for platform {plat}")
    stamp_path = os.path.join(engine, PREBUILT_STAMP)
    if not os.path.isfile(stamp_path):
        raise RunBlocked(f"{engine} is neither the pinned git checkout nor a "
                         f"fetch-and-build.sh prebuilt install "
                         f"(no {PREBUILT_STAMP})")
    with open(stamp_path, encoding="utf-8") as f:
        stamp = f.read().strip()
    if stamp != entry["sha256"]:
        raise RunBlocked(f"prebuilt install stamp {stamp!r} is not the "
                         f"manifest-pinned artifact sha256 {entry['sha256']}")
    real = os.path.realpath(engine)
    if (os.path.basename(real) != plat
            or os.path.basename(os.path.dirname(real)) != pin):
        raise RunBlocked(f"prebuilt install {real} is not at the "
                         f"<root>/{pin}/{plat} layout fetch-and-build.sh "
                         f"installs")
    return {"mode": PROV_PREBUILT, "platform": plat,
            "artifact": entry["artifact"],
            "artifact_sha256": entry["sha256"],
            "source_tree_verification": (
                "performed by oracle/fetch-and-build.sh when the artifact was "
                "built (manifest prebuilt.built_in); the artifact carries no "
                "git checkout, so HEAD/clean-tree/submodule pins are NOT "
                "re-verified live -- identity rests on the pinned sha256"),
            "expected_python": entry["python"]["version"]}


def verify_engine_provenance(engine, manifest, *, git=run_git,
                             platform_key=None, python_version=None):
    """Full engine provenance, or RunBlocked. Accepts exactly two modes:
    (a) a git checkout at the FULL pinned commit with a clean tracked tree
        and every manifest submodule (and present nested submodule) at its
        pin; (b) a manifest-pinned prebuilt artifact installed by
        oracle/fetch-and-build.sh (sha256 stamp + <pin>/<platform> layout).
    The running interpreter must match that mode's pinned Python version.
    Anything else (wrong/dirty source, foreign directory) BLOCKS."""
    if manifest.get("engine", {}).get("commit") != ENGINE_PIN:
        raise RunBlocked(f"manifest engine commit is not the pin {ENGINE_PIN}")
    if _git_toplevel(git, engine) == os.path.realpath(engine):
        prov = _verify_source_checkout(engine, manifest, git)
    else:
        prov = _verify_prebuilt(engine, manifest,
                                platform_key or host_platform_key())
    py = python_version or platform.python_version()
    if py != prov["expected_python"]:
        raise RunBlocked(f"running Python {py} is not the pinned oracle "
                         f"runtime {prov['expected_python']} ({prov['mode']})")
    prov["python"] = py
    return prov


class PinnedSurgepyLoader:
    """Live loader against the pinned native oracle (surgepy).

    `open()` raises OracleAbsent when no oracle is installed here and
    RunBlocked unless FULL provenance holds (verify_engine_provenance, the
    manifest-selected build directory, the validated binding inside it, and a
    consistent getVersion()). All of it is established before any loadPatch.
    `load()` mirrors SXT-028l's blob re-verification + `loadPatch`.

    `oc`, `manifest_path`, `git`, `platform_key` and `python_version` are
    injection points for tests only; production uses the defaults."""

    is_live = True

    def __init__(self, oc=None, manifest_path=None, git=run_git,
                 platform_key=None, python_version=None):
        self.surgepy = None
        self.oc = oc
        self.engine = None
        self._manifest_path = manifest_path or ORACLE_MANIFEST
        self._git = git
        self._platform_key = platform_key
        self._python_version = python_version

    def open(self):
        oc = self.oc
        if oc is None:
            try:
                import oracle_common as oc  # noqa: PLC0415
            except Exception as e:  # environment-dependent
                raise OracleAbsent(f"oracle harness unavailable: {e}") from e
        try:
            with open(self._manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError) as e:
            raise RunBlocked(f"oracle manifest unreadable: {e}") from e
        engine = oc.engine_dir()
        if not os.path.isdir(engine):
            raise OracleAbsent(f"pinned oracle not installed here: "
                               f"ORACLE_SURGE_DIR {engine} does not exist")
        prov = verify_engine_provenance(
            engine, manifest, git=self._git, platform_key=self._platform_key,
            python_version=self._python_version)
        build_rel = manifest["build"]["products"]["surgepy_module"].split(
            "/")[0]
        want_build = os.path.realpath(os.path.join(engine, build_rel))
        if os.path.realpath(oc.build_dir()) != want_build:
            raise RunBlocked(f"selected build dir {oc.build_dir()} is not the "
                             f"manifest build {want_build}")
        try:
            surgepy = oc.import_surgepy()
        except Exception as e:  # environment-dependent
            raise OracleAbsent(f"surgepy unavailable (pinned oracle not "
                               f"built/installed here): {e}") from e
        try:
            binding = oc.binding_provenance(surgepy)
        except Exception as e:
            raise RunBlocked(f"surgepy binding not validated: {e}") from e
        mod = os.path.realpath(binding["module_path"])
        if os.path.commonpath([mod, want_build]) != want_build:
            raise RunBlocked(f"loaded surgepy {mod} is outside the verified "
                             f"build {want_build}")
        oc.apply_engine_env()
        version = surgepy.getVersion()
        if ENGINE_PIN[:9] not in version:
            raise RunBlocked(f"live surgepy reports {version!r}, which does "
                             f"not carry the pinned commit {ENGINE_PIN[:9]}")
        self.surgepy, self.oc, self.engine = surgepy, oc, engine
        return {"pin": ENGINE_PIN, "surgepy_version": version,
                "sample_rate": SAMPLE_RATE, "oracle_surge_dir": engine,
                "provenance": prov, "binding": dict(binding)}

    def load(self, rel, declared_sha1):
        if self.surgepy is None:
            raise RunBlocked("load() before a provenance-verified open()")
        oc = self.oc
        abs_path = os.path.join(self.engine, rel)
        if not os.path.exists(abs_path):
            raise LoadRefusal(R_BLOB_MISMATCH,
                              f"pinned engine checkout does not carry {rel}")
        on_disk = oc.git_blob_sha1(abs_path)
        if on_disk != declared_sha1:
            raise LoadRefusal(R_BLOB_MISMATCH,
                              f"pinned-checkout blob sha1 mismatch for {rel}: "
                              f"on disk={on_disk} declared={declared_sha1}")
        s = self.surgepy.createSurge(SAMPLE_RATE)
        if not s.loadPatch(abs_path):
            raise LoadRefusal(R_LOAD_FAILED,
                              f"loadPatch failed in the pinned engine: {rel}")
        return s, s.getPatch(), on_disk


def screen_candidate(loader, cand, shape_check, gate):
    """Native screen of one provenance-verified candidate. Returns a record;
    per-candidate refusals are captured with NO drift values. An unexpected
    exception from the loader, the caller's shape check or the gate (or a
    gate result that is not a PASS/FAIL dict) becomes a per-candidate refusal
    with a distinct code; it never aborts the run or yields a drift value."""
    rec = {"path": cand["path"], "graphs_blob_sha1": cand["graphs_blob_sha1"],
           "attempted": True, "screened": False, "refusal": None,
           "determinism_gate": None}

    def _stage(code, fn, *args):
        try:
            return fn(*args)
        except Refuse:
            raise
        except Exception as e:  # contained per candidate (never aborts)
            raise LoadRefusal(code, f"unexpected {type(e).__name__} in "
                                    f"{code}: {e}") from e

    try:
        s, patch, on_disk = _stage(R_LOAD_ERROR, loader.load, cand["path"],
                                   cand["graphs_blob_sha1"])
        rec["pinned_checkout_blob_sha1"] = on_disk
        mismatch = _stage(R_SHAPE_CHECK_ERROR, shape_check, s, patch, cand)
        if mismatch:
            raise LoadRefusal(R_SHAPE_MISMATCH, str(mismatch))
        g = _stage(R_GATE_ERROR, gate, s, patch)
        if not isinstance(g, dict) or g.get("status") not in ("PASS", "FAIL"):
            raise LoadRefusal(R_GATE_ERROR, f"gate returned no PASS/FAIL "
                                            f"observation: {g!r}")
        rec["determinism_gate"] = g
        rec["screened"] = True
    except LoadRefusal as e:
        rec["refusal"] = {"code": e.code, "detail": e.detail}
    except Refuse as e:
        rec["refusal"] = {"code": R_LOAD_FAILED, "detail": str(e)}
    return rec


def run_screen(predicate_id, predicate, shape_check, loader, *,
               expected_count=None, gate=DRIFT_GATE, graphs_path=None,
               census_csv=None, manifest_path=None, check_pin=True):
    """Run the screen and return the record (a dict). Never raises for an
    absent oracle / blocked run: those are reported via `status`.

    predicate_id : stable identifier of the shape predicate (recorded).
    predicate    : callable(graph_record) -> bool (explicit, caller-owned).
    shape_check  : callable(session, patch, cand) -> None | mismatch string;
                   cross-checks the shape against the NATIVE normalized state.
    loader       : object with open() / load(rel, sha1) / is_live.
    expected_count: optional committed denominator; a disagreement BLOCKS.
    """
    doc = {"schema_version": 1, "issue": "#423", "claim_scope": CLAIM_SCOPE,
           "shape_predicate_id": predicate_id,
           "host": {"platform": platform.platform(),
                    "python": platform.python_version()},
           "live": False, "status": None, "status_reason": None}
    try:
        if check_pin:
            check_manifest_pin(manifest_path)
        doc["input_digests"] = input_digests(graphs_path, census_csv,
                                             manifest_path)
        cands = enumerate_candidates(predicate, graphs_path)
        census = load_census(census_csv)
    except (Refuse, OSError, ValueError, KeyError) as e:
        doc.update(status="BLOCKED", status_reason=str(e))
        return doc
    manifest = [{"path": c["path"], "graphs_blob_sha1": c["graphs_blob_sha1"]}
                for c in cands]
    doc["candidate_manifest"] = manifest
    doc["candidate_manifest_sha256"] = _canon_sha256(manifest)
    n = len(cands)
    if expected_count is not None and n != expected_count:
        doc.update(status="BLOCKED",
                   status_reason=f"candidate count {n} disagrees with the "
                                 f"expected denominator {expected_count}; "
                                 f"refusing to screen a different denominator")
        return doc

    records = []
    prov_refusals = {}
    for c in cands:
        r = check_provenance(c, census)
        if r:
            prov_refusals[c["path"]] = r

    try:
        doc["engine"] = loader.open()
    except OracleAbsent as e:
        doc.update(status="NOT_RUN", status_reason=str(e))
        return doc
    except Refuse as e:
        doc.update(status="BLOCKED", status_reason=str(e))
        return doc
    doc["live"] = bool(getattr(loader, "is_live", False))

    for c in cands:
        if c["path"] in prov_refusals:
            code, detail = prov_refusals[c["path"]]
            records.append({"path": c["path"],
                            "graphs_blob_sha1": c["graphs_blob_sha1"],
                            "attempted": False, "screened": False,
                            "refusal": {"code": code, "detail": detail},
                            "determinism_gate": None})
        else:
            records.append(screen_candidate(loader, c, shape_check, gate))

    screened = [r for r in records if r["screened"]]
    passing = [r["path"] for r in screened
               if r["determinism_gate"]["status"] == "PASS"]
    failing = [r["path"] for r in screened
               if r["determinism_gate"]["status"] != "PASS"]
    refused = [r["path"] for r in records if r["refusal"]]
    complete = len(screened) == n
    doc["coverage"] = {"candidates_in_corpus": n,
                       "candidates_attempted": sum(r["attempted"]
                                                   for r in records),
                       "candidates_screened": len(screened),
                       "candidates_refused": len(refused),
                       "refused_paths": refused}
    doc["observations"] = {"drift_gate_pass": len(passing),
                           "drift_gate_fail": len(failing),
                           "drift_gate_pass_paths": passing,
                           "drift_gate_fail_paths": failing,
                           "what": "per-scene drift gate observations; "
                                   "separate from coverage"}
    doc["render_eligibility"] = ("NOT_ESTABLISHED -- drift-gate PASS is "
                                 "necessary, never sufficient")
    doc["candidates"] = records
    # `status` is the RUN/COVERAGE status only. The drift outcome is a
    # separate verdict (`drift_gate_status`) so a coverage PASS can never be
    # quoted as "drift-clean": drift_gate_status is PASS only when coverage is
    # complete AND every screened candidate's gate is PASS.
    coverage_status = "PASS" if complete else "NO_VERDICT"
    if failing:
        drift_status = "FAIL"
    elif complete and n > 0:
        drift_status = "PASS"
    else:
        drift_status = "NO_VERDICT"
    doc["status_scope"] = ("coverage only: status says every candidate was "
                           "attempted and screened, NOT that any candidate "
                           "has drift 0; see drift_gate_status")
    doc["coverage_status"] = coverage_status
    doc["drift_gate_status"] = drift_status
    doc["drift_gate_status_reason"] = (
        f"{len(passing)} PASS, {len(failing)} FAIL, "
        f"{n - len(screened)} not screened, of {n} candidates")
    doc["status"] = coverage_status
    doc["status_reason"] = (
        f"coverage complete: {n}/{n} screened (coverage status only; drift "
        f"outcome is drift_gate_status={drift_status})" if complete else
        f"coverage incomplete: {len(screened)}/{n} screened, {len(refused)} "
        f"refused (drift_gate_status={drift_status})")
    return doc


def assert_drift_gate_passed(candidate_record):
    """Eligibility assertion for the drift screening condition only. Raises
    AssertionError unless the candidate was screened AND its gate is PASS."""
    gate = candidate_record.get("determinism_gate")
    if not candidate_record.get("screened") or gate is None:
        raise AssertionError(f"{candidate_record.get('path')}: not screened "
                             f"({candidate_record.get('refusal')})")
    if gate.get("status") != "PASS":
        raise AssertionError(
            f"{candidate_record['path']}: drift gate {gate.get('status')} "
            f"{gate.get('drift_per_voicing_scene')}")
    return True


def write_record(doc, out_path):
    """Write a record only when the live oracle leg actually ran."""
    if doc.get("status") in (None, "NOT_RUN", "BLOCKED") or not doc.get("live"):
        raise Refuse(f"refusing to write a non-live/{doc.get('status')} "
                     f"record as oracle evidence")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")


def _resolve(spec):
    mod, _, name = spec.partition(":")
    return getattr(importlib.import_module(mod), name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--predicate-id", required=True)
    ap.add_argument("--predicate", required=True, help="pkg.mod:callable")
    ap.add_argument("--shape-check", help="pkg.mod:callable(s, patch, cand)")
    ap.add_argument("--expected-count", type=int)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if not a.shape_check:
        print("BLOCKED: an explicit --shape-check against native state is "
              "required")
        return 1
    doc = run_screen(a.predicate_id, _resolve(a.predicate),
                     _resolve(a.shape_check), PinnedSurgepyLoader(),
                     expected_count=a.expected_count)
    st = doc["status"]
    print(f"carrier drift screen [{a.predicate_id}]: {st} "
          f"({doc['status_reason']})")
    if "coverage" in doc:
        print(f"coverage: {doc['coverage']}")
        print(f"drift_gate_status: {doc['drift_gate_status']} "
              f"({doc['drift_gate_status_reason']}) -- separate from the "
              f"coverage status above")
    if st == "NOT_RUN" or st == "BLOCKED":
        return 2 if st == "NOT_RUN" else 1
    if a.out:
        write_record(doc, a.out)
        print(f"wrote {a.out}")
    return 0 if st == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
