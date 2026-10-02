#!/usr/bin/env python3
"""SXT-036 (#70) oracle gate probe and frozen backfill plan.

Sixth oracle-independent increment. Acceptance items 2 (model-vs-pinned-engine
dry-render budgets) and 5 (reference-budget negative controls) have been
reported NOT_RUN by every previous increment on the strength of a hand-run
`python3 -c "import surgepy"` plus prose in `reports/SXT-036/EVIDENCE.md`.
This tool makes that status **measured and machine-readable** instead, the way
the sibling leaves already do it (`tools/rf_send34_oracle_status.py`,
`tools/rf_global34_oracle_status.py`, `tools/phaser_oracle_status.py` ->
`reports/SXT-028*/artifacts/oracle-status.json`), and it freezes the backfill
plan the `oracle:backfill` queue marker on #70 points at.

It does NOT run any oracle-dependent leg and it can never move an acceptance
item to PASS. A leg that did not run is recorded NOT_RUN (or BLOCKED), never
a pass (AGENTS.md verification-status rule).

Three things this records that prose did not
--------------------------------------------
1. **The gate is measured, and measured STRICTLY.** A bare `import surgepy`
   is not evidence of the pinned oracle: any importable `surgepy` on
   `PYTHONPATH` satisfies it. This probe additionally requires EITHER a git
   checkout to exist, to be a git work tree, and to sit at the SXT-010
   pinned commit ("git-worktree" provisioning), OR a sha256-verified
   prebuilt install whose `.installed-sha256` equals the pinned
   `oracle/manifest.json` `prebuilt.<platform>.sha256` ("prebuilt"
   provisioning, #232) -- and in both cases the imported module file must
   live INSIDE the probed directory. A bare directory listing is refused
   either way: an unverified prebuilt-shaped directory (missing/mismatched
   `.installed-sha256`) falls through to the git-worktree reading, which
   correctly reports it UNAVAILABLE (control O8). The difference between
   the naive and strict readings is a live negative control (O1).

2. **The legs are split by which gate they need.** Blob-verifying the three
   carrier `.fxp` payloads named by #70, plus the Attacky fixture carrier,
   needs the pinned CHECKOUT only -- not a built `surgepy`. Recording that
   stops the cheapest leg of the backfill from being bundled behind the
   expensive one. This leg has since been RUN (seventh increment,
   `model/voice/blob_verify_vel_carriers.py`, PASS 4/4;
   `attacky_vel_inputs.json.preset.blob_verified` is now `true`) -- the
   point above is about this table's own design, not a claim that the leg
   is still outstanding.

3. **Every tool #70 names is resolved to a committed path.** #70's "Fixtures
   and oracle" section names `tools/render_fixture.py`, and
   `reports/SXT-036/EVIDENCE.md` repeats it -- that path does not exist in
   this repository (the SXT-012 harness is `fixtures/render_fixture.py`). An
   oracle host following the prose would chase a missing file. The resolution
   table is checked live, with a control (O7) that a bogus name is reported
   MISSING rather than rubber-stamped.

Statuses emitted for the oracle gate
------------------------------------
  AVAILABLE          EITHER a git checkout present, at the pin, with surgepy
                     importing from inside it ("git-worktree" provisioning),
                     OR a sha256-verified prebuilt install
                     (`oracle/fetch-and-build.sh --prebuilt`, #232) whose
                     `.installed-sha256` equals the manifest's
                     `prebuilt.<platform>.sha256`, with surgepy importing
                     from inside it ("prebuilt" provisioning). Both are
                     accepted; neither replaces the other.
  PIN_MISMATCH       a checkout is present but its HEAD is not the pinned
                     commit -- refused, never treated as the oracle
  UNPINNED_SURGEPY   some surgepy imports, but not from the pinned checkout
                     -- refused loudly rather than silently accepted
  UNAVAILABLE        no git checkout and no sha256-verified prebuilt install,
                     and/or no importable surgepy from either

Fail-closed (exit 2) on: an `oracle/manifest.json` engine pin that disagrees
with the commit #70 pins; a missing or drifted committed prediction artifact.

Exit codes: 0 = probe recorded and every control fired; 2 = fail-closed
refusal; 1 = run error.

Usage:
  python3 tools/vel_oracle_status.py --artifacts reports/SXT-036/artifacts
  python3 tools/vel_oracle_status.py --dry-run --json   # probe only, no write

Original work, Apache-2.0. The pinned engine is cited, never copied.
"""

import argparse
import json
import os
import platform as _platform_mod
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The engine commit pinned by #70's body (and by AGENTS.md / CLAUDE.md).
# oracle/manifest.json must agree with this; disagreement is a refusal.
ISSUE_PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"

DEFAULT_ARTIFACTS = os.path.join(REPO, "reports", "SXT-036", "artifacts")
DEFAULT_MANIFEST = os.path.join(REPO, "oracle", "manifest.json")

LEG_STATUS_VOCABULARY = ("NOT_RUN", "RUNNABLE", "BLOCKED")

# Gate kinds: what an oracle host actually needs for each leg.
GATE_CHECKOUT = "pinned checkout only (no built surgepy needed)"
GATE_FULL = "pinned checkout + surgepy built from it"

# Every oracle-gated leg of #70, with the acceptance item it serves and the
# committed tool (or sibling pattern) that runs it.
ORACLE_LEGS = [
    {
        "name": "blob-verify-carriers",
        "item": "1 (fixture provenance under item 1)",
        "gate": GATE_CHECKOUT,
        "tool": "model/voice/blob_verify_vel_carriers.py "
                "(oracle/oracle_common.py::git_blob_sha1)",
        "what": "hash the .fxp payloads of the three carriers #70 names, plus "
                "the Attacky fixture carrier, in the pinned checkout and "
                "compare against the census blob SHA-1s. RUN on this leaf's "
                "seventh increment (reports/SXT-036/artifacts/"
                "blob-verify-carriers.json, PASS 4/4); the audit's prior "
                "census-vs-graphs agreement alone was strictly weaker than "
                "this payload hash. This entry still describes the LEG, not "
                "the run -- this table never emits PASS (see build_legs()).",
    },
    {
        "name": "extract-fixture-depths",
        "item": "1 (replaces the DECLARED depths behind items 2 and 5)",
        "gate": GATE_FULL,
        "tool": "model/voice/extract_vel_inputs.py (to be written on the "
                "oracle host, modelled on model/voice/extract_mw_inputs.py)",
        "what": "replace model/voice/attacky_vel_inputs.json -- whose own "
                "provenance field says the depths are hand-declared, NOT "
                "engine readbacks -- with setModDepth01/getModDepth01 "
                "read-back words, and cross-check the live getAllModRoutings "
                "against the normalized graphs.jsonl rows. Until this lands, "
                "no reference-budget number produced from that file means "
                "anything.",
    },
    {
        "name": "render-reference",
        "item": "2",
        "gate": GATE_FULL,
        "tool": "fixtures/render_vel_fixture.py (to be written on the oracle "
                "host, modelled on fixtures/render_mw_fixture.py)",
        "what": "dry pinned-engine reference renders under the SXT-012 "
                "policies (fresh instance, controller reset, 0.25 s settle "
                "discarded, block-quantized events, mono int16, no "
                "normalization / time warping / fades) for the declared "
                "fixture across the three sequences #70 names plus the two "
                "leaf-local stimuli.",
    },
    {
        "name": "compare-budgets",
        "item": "2",
        "gate": GATE_FULL,
        "tool": "tools/compare_audio_reference.py",
        "what": "model-vs-pinned-engine dry-render budgets on the carrier "
                "fixtures: ACHIEVED numbers recorded, not tuned "
                "(PENDING-FREEZE per the fidelity policy draft).",
    },
    {
        "name": "reference-budget-controls",
        "item": "5",
        "gate": GATE_FULL,
        "tool": "tools/vel_negative_controls.py (exactness side, landed) + "
                "tools/compare_audio_reference.py (budget side, this leg)",
        "what": "the routing-zeroed control (depth forced to 0, per "
                "destination class) and the source-swap control (landed "
                "modwheel in place of velocity / release velocity) must BOTH "
                "FAIL the reference-budget check. Both mutations already run "
                "and already fail the RTL-vs-model EXACTNESS check (E1/E2) -- "
                "that is a different check and is not a substitute.",
    },
]

# Tool paths named by #70's body / by reports/SXT-036/EVIDENCE.md, resolved
# against the committed tree. `resolved` None means the named path is real.
NAMED_TOOLS = [
    ("tools/render_fixture.py", "fixtures/render_fixture.py",
     "#70 'Fixtures and oracle'; repeated in EVIDENCE.md 'Backfill'"),
    ("tools/compare_audio_reference.py", None, "#70 'Fixtures and oracle'"),
    ("tools/compare_rtl_model.py", None, "#70 acceptance item 3"),
    ("model/voice/extract_inputs.py", None, "#70 'Inputs / outputs / state'"),
]


def detect_platform():
    """Platform key matching oracle/manifest.json's `prebuilt.<platform>`
    table (mirrors oracle/fetch-and-build.sh's `--prebuilt` case statement)."""
    sysname = _platform_mod.system()
    machine = _platform_mod.machine()
    table = {("Linux", "x86_64"): "linux-x86_64",
             ("Darwin", "arm64"): "darwin-arm64"}
    return table.get((sysname, machine),
                     f"{sysname.lower()}-{machine}")


def _fail(msg):
    print(f"REFUSED: {msg}", file=sys.stderr)
    return 2


def load_manifest(path):
    """Load the SXT-010 manifest and refuse if its pin is not #70's pin."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"oracle manifest missing: {path}")
    with open(path, "r", encoding="utf-8") as f:
        m = json.load(f)
    commit = m.get("engine", {}).get("commit")
    if commit != ISSUE_PIN:
        raise ValueError(
            f"engine pin drift: manifest {commit!r} != #70 pin {ISSUE_PIN!r}. "
            "The oracle backfill must not run against an unpinned engine.")
    return m


def _run(cmd, env=None, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          env=env, cwd=cwd)


_SURGEPY_PROBE = r"""
import json, os, sys
mode = sys.argv[1]
if mode == "pinned":
    sys.path.insert(0, sys.argv[2])
out = {"mode": mode}
try:
    import surgepy
    out["ok"] = True
    out["file"] = getattr(surgepy, "__file__", None)
except Exception as e:
    out["ok"] = False
    out["file"] = None
    out["err"] = f"{type(e).__name__}: {e}"
print(json.dumps(out))
"""


def probe(manifest, engine_dir_override=None):
    """Measure the oracle gate. Never raises on a missing oracle."""
    d = {}
    expected = manifest["engine"]["expected_checkout"][
        "location_used_for_evidence"]
    env_dir = engine_dir_override or os.environ.get("ORACLE_SURGE_DIR")
    d["engine_pin"] = manifest["engine"]["commit"]
    d["expected_checkout"] = expected
    d["oracle_surge_dir_env_set"] = bool(os.environ.get("ORACLE_SURGE_DIR"))
    engine_dir = env_dir or expected
    d["engine_dir_probed"] = engine_dir
    d["engine_dir_present"] = bool(engine_dir and os.path.isdir(engine_dir))

    # A directory is not a checkout, and a checkout is not THE checkout.
    d["engine_dir_is_git_worktree"] = False
    d["engine_head"] = None
    d["engine_head_matches_pin"] = False
    if d["engine_dir_present"]:
        r = _run(["git", "-C", engine_dir, "rev-parse", "HEAD"])
        if r.returncode == 0:
            d["engine_dir_is_git_worktree"] = True
            d["engine_head"] = r.stdout.strip()
            d["engine_head_matches_pin"] = d["engine_head"] == d["engine_pin"]

    # Prebuilt provisioning (#232): a sha256-verified install is accepted
    # ALONGSIDE the git-worktree reading above, never instead of it. Fails
    # closed -- a missing/unreadable/mismatched .installed-sha256 leaves
    # d["prebuilt_sha256_matches"] False and classify() falls through to the
    # git-worktree logic, which correctly reports a bare directory
    # UNAVAILABLE (control O8).
    plat = detect_platform()
    d["platform"] = plat
    prebuilt_manifest = (manifest.get("prebuilt") or {}).get(plat) or {}
    d["prebuilt_manifest_sha256"] = prebuilt_manifest.get("sha256")
    installed_sha_path = (os.path.join(engine_dir, ".installed-sha256")
                         if engine_dir else None)
    d["prebuilt_installed_sha256_path"] = installed_sha_path
    installed_sha = None
    if installed_sha_path and os.path.isfile(installed_sha_path):
        try:
            with open(installed_sha_path, "r", encoding="utf-8") as f:
                installed_sha = f.read().strip()
        except OSError:
            installed_sha = None
    d["prebuilt_installed_sha256"] = installed_sha
    d["prebuilt_sha256_matches"] = bool(
        installed_sha and d["prebuilt_manifest_sha256"]
        and installed_sha == d["prebuilt_manifest_sha256"])
    buildinfo_path = (os.path.join(engine_dir, "BUILDINFO.json")
                      if engine_dir else None)
    d["prebuilt_buildinfo_present"] = bool(
        buildinfo_path and os.path.isfile(buildinfo_path))

    build_rel = os.environ.get("ORACLE_BUILD_DIR_REL", "build-py311")
    so_dir = os.path.join(engine_dir, build_rel, "src", "surge-python")
    d["surgepy_so_dir_probed"] = so_dir
    d["surgepy_so_dir_present"] = os.path.isdir(so_dir)

    # Two readings, deliberately both recorded (see control O1):
    #   naive  -- a bare `import surgepy`, what every previous increment ran;
    #   pinned -- import via the oracle_common .so path AND require the
    #             resulting module file to live inside the pinned checkout.
    naive = _run([sys.executable, "-c", _SURGEPY_PROBE, "naive"])
    pinned = _run([sys.executable, "-c", _SURGEPY_PROBE, "pinned", so_dir])
    try:
        d["surgepy_naive"] = json.loads(naive.stdout or "{}")
    except json.JSONDecodeError:
        d["surgepy_naive"] = {"ok": False, "err": "probe produced no JSON"}
    try:
        d["surgepy_pinned"] = json.loads(pinned.stdout or "{}")
    except json.JSONDecodeError:
        d["surgepy_pinned"] = {"ok": False, "err": "probe produced no JSON"}

    f = d["surgepy_pinned"].get("file")
    inside = bool(
        f and d["engine_dir_present"]
        and os.path.realpath(f).startswith(os.path.realpath(engine_dir) + os.sep))
    d["surgepy_importable_naive"] = bool(d["surgepy_naive"].get("ok"))
    d["surgepy_importable"] = bool(d["surgepy_pinned"].get("ok"))
    d["surgepy_under_engine_dir"] = inside
    return d


def classify(p):
    """Map a probe to an oracle-gate status plus a stated reason.

    Two AVAILABLE provisioning shapes are accepted, checked in this order
    (neither replaces the other -- #70 backfill note):
      1. git-worktree: checkout present, HEAD == pin, surgepy importable
         from inside it.
      2. prebuilt: `.installed-sha256` present and equal to the manifest's
         `prebuilt.<platform>.sha256`, surgepy importable from inside it.
    A directory that satisfies neither (control O2: empty; control O8: a
    prebuilt-shaped directory with a missing/mismatched
    `.installed-sha256`) falls through to UNAVAILABLE/PIN_MISMATCH exactly
    as before this provisioning shape was added.
    """
    if (p["engine_dir_present"] and p["engine_head_matches_pin"]
            and p["surgepy_importable"] and p["surgepy_under_engine_dir"]):
        return "AVAILABLE", (
            "git-worktree provisioning: checkout present at the pinned "
            f"commit {p['engine_pin']!r}, surgepy imports from inside it")
    if (p["engine_dir_present"] and p["prebuilt_sha256_matches"]
            and p["surgepy_importable"] and p["surgepy_under_engine_dir"]):
        return "AVAILABLE", (
            "prebuilt provisioning (#232): .installed-sha256 matches "
            f"manifest prebuilt.{p['platform']}.sha256 "
            f"{p['prebuilt_manifest_sha256']!r}, surgepy imports from "
            "inside it")
    if p["surgepy_importable"] and not p["surgepy_under_engine_dir"]:
        return "UNPINNED_SURGEPY", (
            "a surgepy module is importable but does not live inside the "
            f"probed checkout ({p['surgepy_pinned'].get('file')!r}); it is "
            "NOT the pinned oracle and is refused, not accepted")
    if p["engine_dir_present"] and not p["engine_dir_is_git_worktree"]:
        return "UNAVAILABLE", (
            f"{p['engine_dir_probed']!r} exists but is not a git work tree "
            "and is not a sha256-verified prebuilt install "
            f"(.installed-sha256 present={p['prebuilt_installed_sha256'] is not None}, "
            f"matches manifest={p['prebuilt_sha256_matches']}); a bare "
            "directory is neither a pinned checkout nor a verified prebuilt")
    if p["engine_dir_present"] and not p["engine_head_matches_pin"]:
        return "PIN_MISMATCH", (
            f"checkout HEAD {p['engine_head']!r} != pinned "
            f"{p['engine_pin']!r}; refused, never treated as the oracle")
    return "UNAVAILABLE", (
        "no pinned-engine checkout and no sha256-verified prebuilt install "
        "in this environment; the oracle-gated legs were not run and must "
        "never be reported as a pass (#96, #232)")


def resolve_named_tools():
    rows = []
    for named, actual, where in NAMED_TOOLS:
        named_exists = os.path.exists(os.path.join(REPO, named))
        resolved = named if named_exists else actual
        resolved_exists = bool(
            resolved and os.path.exists(os.path.join(REPO, resolved)))
        rows.append({
            "named_by_issue": named,
            "named_path_exists": named_exists,
            "resolves_to": resolved if resolved_exists else None,
            "status": "OK" if named_exists else (
                "CORRECTED" if resolved_exists else "MISSING"),
            "cited_in": where,
        })
    return rows


def build_legs(status):
    """Leg statuses. This function can never emit PASS -- see control O6."""
    available = status == "AVAILABLE"
    legs = {}
    for leg in ORACLE_LEGS:
        legs[leg["name"]] = {
            "acceptance_item": leg["item"],
            "gate": leg["gate"],
            "tool": leg["tool"],
            "what": leg["what"],
            "status": "RUNNABLE" if available else "NOT_RUN",
            "reason": None if available else (
                "pinned oracle unavailable on dispatch host (#96); the leg "
                "was not run"),
        }
    return validate_legs(legs)


def validate_legs(legs):
    """Reject any leg status outside the NOT_RUN/RUNNABLE/BLOCKED vocabulary.

    A leg this tool did not run must never carry PASS. This guard is what
    control O6 mutates.
    """
    for name, leg in legs.items():
        if leg["status"] not in LEG_STATUS_VOCABULARY:
            raise ValueError(
                f"leg {name!r} status {leg['status']!r} is outside the "
                f"permitted vocabulary {LEG_STATUS_VOCABULARY}; this tool "
                "runs no oracle-gated leg and may never report one as a pass")
    return legs


def load_predictions(artifacts):
    """Consolidate the falsifiable predictions the oracle host must confirm.

    Read from the COMMITTED artifacts rather than restated, so the plan cannot
    silently drift away from the evidence it came from (control O5).
    """
    audit_p = os.path.join(artifacts, "carrier-route-audit.json")
    corners_p = os.path.join(artifacts, "param-corners.json")
    for p in (audit_p, corners_p):
        if not os.path.exists(p):
            raise FileNotFoundError(
                f"prediction source missing: {p}. The backfill plan is "
                "derived from committed artifacts, never restated by hand.")
    with open(audit_p, "r", encoding="utf-8") as f:
        audit = json.load(f)
    with open(corners_p, "r", encoding="utf-8") as f:
        corners = json.load(f)

    graphs_a = audit.get("graphs_sha256")
    graphs_c = corners.get("derived_ranges", {}).get("graphs_sha256")
    if graphs_a != graphs_c:
        raise ValueError(
            f"prediction drift: carrier-route-audit graphs_sha256 {graphs_a!r} "
            f"!= param-corners {graphs_c!r}; the two prediction sets no longer "
            "describe the same corpus state")
    if not audit.get("graphs_sha256_matches_issue_pin"):
        raise ValueError(
            "carrier-route-audit reports graphs.jsonl does NOT match the "
            "sha256 #70 pins; predictions derived from it are not usable")

    routes = audit.get("oracle_host_backfill_predictions") or []
    if not routes:
        raise ValueError(
            "carrier-route-audit carries no oracle_host_backfill_predictions; "
            "there is nothing for the oracle host to confirm or contradict")
    extents = corners.get("derived_ranges", {}).get("extents") or {}
    if sorted(extents) != sorted(audit.get("frozen_destination_class", {})):
        raise ValueError(
            "prediction drift: the derived destination extents and the frozen "
            "destination class no longer cover the same destination ids")

    return {
        "graphs_sha256": graphs_a,
        "frozen_destination_class": audit["frozen_destination_class"],
        "carrier_routes": routes,
        "destination_extents": {
            k: v["extent"] for k, v in sorted(extents.items())},
        "observed_source_normalized_range": corners["derived_ranges"][
            "observed_source_normalized_range"],
        "rule": "a disagreement on an oracle host is a finding about the "
                "corpus pipeline or about the cited reading of the engine -- "
                "never a tuning opportunity, and never a reason to re-derive "
                "the corners so they stay green",
    }


# --------------------------------------------------------------------------
# Live negative controls. Each must demonstrably fail the check it targets.
# --------------------------------------------------------------------------

def _self(args, env=None):
    """Spawn a scoped dry-run probe of this tool.

    `PYTHONPATH` is deliberately SCRUBBED from the inherited environment
    before `env` is applied: now that a real oracle can be genuinely
    available on the invoking shell (#232 prebuilt provisioning), an
    operator following this tool's own documented re-run command
    (`PYTHONPATH=... python tools/vel_oracle_status.py`) would otherwise
    leak the REAL engine's surgepy onto every control subprocess's
    PYTHONPATH regardless of the `ORACLE_SURGE_DIR` override a control sets
    -- masking a wrong-commit (O3) or unbuilt (O9) ORACLE_SURGE_DIR override
    with a real surgepy import that did not come from the directory under
    test. Each control that needs PYTHONPATH sets it explicitly via `env`
    (O1's stub); every other control now runs against a clean PYTHONPATH,
    so its probed `ORACLE_SURGE_DIR` is the only thing that can produce a
    surgepy import.
    """
    cmd = [sys.executable, os.path.abspath(__file__), "--dry-run", "--json"]
    cmd += args
    e = dict(os.environ)
    e.pop("PYTHONPATH", None)
    if env:
        e.update(env)
    return _run(cmd, env=e)


def _self_json(args, env=None):
    r = _self(args, env)
    try:
        return r.returncode, json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.returncode, None


def run_controls(artifacts, log):
    """Return (controls, all_fired)."""
    out = []

    def rec(cid, target, expect, got, fired, detail=""):
        out.append({"id": cid, "targets": target, "expected": expect,
                    "observed": got, "fired": bool(fired), "detail": detail})
        log(f"  {cid} {'FIRED' if fired else 'DID NOT FIRE'}: {target}")
        log(f"      expected: {expect}")
        log(f"      observed: {got}")
        if detail:
            log(f"      note: {detail}")

    tmproot = tempfile.mkdtemp(prefix="sxt036-oracle-controls-")
    try:
        # O1 -- a stub surgepy on PYTHONPATH. The naive `import surgepy`
        # reading every previous increment used is FOOLED by it; the pinned
        # reading must refuse it. ORACLE_SURGE_DIR is deliberately pointed at
        # an empty, non-engine directory (not inherited from the invoking
        # shell): now that a real oracle can genuinely be installed (#232),
        # leaving ORACLE_SURGE_DIR ambient would let the "pinned" reading
        # find the REAL engine and correctly report AVAILABLE -- a true
        # result, but not what this control is testing (whether a stub
        # alone, with NO real oracle backing it, can fool the pinned
        # reading).
        stub = os.path.join(tmproot, "stub")
        os.makedirs(stub)
        with open(os.path.join(stub, "surgepy.py"), "w", encoding="utf-8") as f:
            f.write("# SXT-036 control O1: not the pinned engine.\n"
                    "SurgeSynthesizer = None\n")
        no_engine = os.path.join(tmproot, "o1-no-engine-here")
        rc, doc = _self_json(
            [], {"PYTHONPATH": stub, "ORACLE_SURGE_DIR": no_engine})
        naive = doc and doc["probe"]["surgepy_importable_naive"]
        status = doc and doc["oracle_gate"]["status"]
        under = doc and doc["probe"]["surgepy_under_engine_dir"]
        rec("O1", "a bare `import surgepy` accepted as proof of the pinned "
                  "oracle (the reading used by increments 1-5)",
            "naive reading TRUE (fooled), pinned reading refuses: status "
            "UNPINNED_SURGEPY, surgepy_under_engine_dir False",
            f"rc={rc} naive={naive} status={status} under_engine_dir={under}",
            rc == 0 and naive is True and status == "UNPINNED_SURGEPY"
            and under is False,
            "the stub is importable and carries no engine; accepting it would "
            "have reported an oracle that does not exist")

        # O2 -- an empty directory is not a checkout.
        empty = os.path.join(tmproot, "empty-not-a-checkout")
        os.makedirs(empty)
        rc, doc = _self_json([], {"ORACLE_SURGE_DIR": empty})
        present = doc and doc["probe"]["engine_dir_present"]
        isgit = doc and doc["probe"]["engine_dir_is_git_worktree"]
        status = doc and doc["oracle_gate"]["status"]
        rec("O2", "an `os.path.isdir` reading of ORACLE_SURGE_DIR accepted as "
                  "a pinned checkout",
            "dir present TRUE but git worktree FALSE and status != AVAILABLE",
            f"rc={rc} present={present} git_worktree={isgit} status={status}",
            rc == 0 and present is True and isgit is False
            and status != "AVAILABLE")

        # O3 -- a real git checkout at the WRONG commit must be refused.
        wrong = os.path.join(tmproot, "wrong-commit")
        os.makedirs(wrong)
        genv = dict(os.environ, GIT_AUTHOR_NAME="sxt036", GIT_AUTHOR_EMAIL="c@x",
                    GIT_COMMITTER_NAME="sxt036", GIT_COMMITTER_EMAIL="c@x",
                    GIT_CONFIG_GLOBAL=os.path.join(tmproot, "gitconfig"),
                    GIT_CONFIG_SYSTEM=os.path.join(tmproot, "gitconfig-sys"))
        _run(["git", "init", "-q", wrong], env=genv)
        with open(os.path.join(wrong, "README"), "w", encoding="utf-8") as f:
            f.write("not the pinned engine\n")
        _run(["git", "-C", wrong, "add", "README"], env=genv)
        _run(["git", "-C", wrong, "commit", "-q", "-m", "not surge"], env=genv)
        rc, doc = _self_json([], {"ORACLE_SURGE_DIR": wrong})
        isgit = doc and doc["probe"]["engine_dir_is_git_worktree"]
        head = doc and doc["probe"]["engine_head"]
        status = doc and doc["oracle_gate"]["status"]
        # The control repo's HEAD is a fresh hash on every run; record the
        # PREDICATE, not the hash, so the committed artifact is reproducible.
        rec("O3", "any git checkout at ORACLE_SURGE_DIR accepted as THE "
                  "pinned checkout regardless of its HEAD",
            "git worktree TRUE, HEAD != pin, status PIN_MISMATCH",
            f"rc={rc} git_worktree={isgit} head_present={head is not None} "
            f"head_is_pin={head == ISSUE_PIN} status={status}",
            rc == 0 and isgit is True and head not in (None, ISSUE_PIN)
            and status == "PIN_MISMATCH")

        # O4 -- a drifted engine pin in oracle/manifest.json must refuse.
        with open(DEFAULT_MANIFEST, "r", encoding="utf-8") as f:
            man = json.load(f)
        man["engine"]["commit"] = "0" * 40
        mpath = os.path.join(tmproot, "manifest-drifted.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(man, f)
        r = _self(["--manifest", mpath])
        rec("O4", "an oracle/manifest.json engine pin that disagrees with the "
                  "commit #70 pins",
            "exit 2 (fail-closed refusal), 'engine pin drift' on stderr",
            f"rc={r.returncode} stderr={r.stderr.strip().splitlines()[-1:]}",
            r.returncode == 2 and "engine pin drift" in r.stderr)

        # O5 -- a drifted / missing committed prediction artifact must refuse.
        acopy = os.path.join(tmproot, "artifacts")
        shutil.copytree(artifacts, acopy)
        ap = os.path.join(acopy, "carrier-route-audit.json")
        with open(ap, "r", encoding="utf-8") as f:
            aud = json.load(f)
        aud["graphs_sha256"] = "f" * 64
        with open(ap, "w", encoding="utf-8") as f:
            json.dump(aud, f)
        r = _self(["--artifacts", acopy])
        fired_drift = r.returncode == 2 and "prediction drift" in r.stderr
        bare = os.path.join(tmproot, "artifacts-empty")
        os.makedirs(bare)
        r2 = _self(["--artifacts", bare])
        fired_missing = (r2.returncode == 2
                         and "prediction source missing" in r2.stderr)
        rec("O5", "the consolidated backfill predictions drifting away from, "
                  "or being restated without, the committed artifacts they "
                  "are derived from",
            "both exit 2: 'prediction drift' on a mutated artifact, "
            "'prediction source missing' on an absent one",
            f"drift rc={r.returncode} fired={fired_drift}; "
            f"missing rc={r2.returncode} fired={fired_missing}",
            fired_drift and fired_missing)

        # O6 -- the emitter must refuse to report an unrun leg as a pass.
        legs = build_legs("UNAVAILABLE")
        name = sorted(legs)[0]
        mutated = json.loads(json.dumps(legs))
        mutated[name]["status"] = "PASS"
        raised = False
        try:
            validate_legs(mutated)
        except ValueError:
            raised = True
        rec("O6", "an oracle-gated leg this tool never ran being emitted as "
                  "PASS",
            "validate_legs rejects the mutated 'PASS' status; the unmutated "
            "leg set validates",
            f"mutated_rejected={raised} baseline_statuses="
            f"{sorted({v['status'] for v in legs.values()})}",
            raised and all(v["status"] in LEG_STATUS_VOCABULARY
                           for v in legs.values()))

        # O7 -- the named-tool resolver must not rubber-stamp a bogus name.
        real = resolve_named_tools()
        saved = list(NAMED_TOOLS)
        try:
            NAMED_TOOLS.append(
                ("tools/definitely_not_a_tool.py", None, "control O7"))
            bogus = resolve_named_tools()[-1]
        finally:
            NAMED_TOOLS[:] = saved
        corrected = [r_["named_by_issue"] for r_ in real
                     if r_["status"] == "CORRECTED"]
        rec("O7", "a tool path named by #70 being reported as resolved "
                  "without checking the tree",
            "a bogus name resolves to MISSING; the real table reports "
            "tools/render_fixture.py as CORRECTED",
            f"bogus={bogus['status']} corrected={corrected}",
            bogus["status"] == "MISSING"
            and "tools/render_fixture.py" in corrected)

        # O8 -- a prebuilt-SHAPED directory (has .installed-sha256) whose
        # hash does NOT match oracle/manifest.json's prebuilt.<platform>
        # entry must be refused, never accepted as the prebuilt provisioning
        # shape (#232's whole point is that an unverified artifact is never
        # imported).
        with open(DEFAULT_MANIFEST, "r", encoding="utf-8") as f:
            real_manifest = json.load(f)
        plat = detect_platform()
        pinned_sha = (real_manifest.get("prebuilt") or {}).get(plat, {}).get(
            "sha256")
        wrong_sha_dir = os.path.join(tmproot, "prebuilt-wrong-sha")
        os.makedirs(wrong_sha_dir)
        with open(os.path.join(wrong_sha_dir, ".installed-sha256"), "w",
                 encoding="utf-8") as f:
            f.write("0" * 64)
        rc, doc = _self_json([], {"ORACLE_SURGE_DIR": wrong_sha_dir})
        matches = doc and doc["probe"]["prebuilt_sha256_matches"]
        status = doc and doc["oracle_gate"]["status"]
        rec("O8", "a prebuilt-shaped directory (.installed-sha256 present) "
                  "whose hash disagrees with manifest.prebuilt.<platform>."
                  "sha256 being accepted as a verified prebuilt install",
            "prebuilt_sha256_matches FALSE, status != AVAILABLE"
            + ("" if pinned_sha else " (no manifest entry for this platform "
                                     "-- control still meaningful: 64 zeros "
                                     "never matches None)"),
            f"rc={rc} prebuilt_sha256_matches={matches} status={status}",
            rc == 0 and matches is False and status != "AVAILABLE")

        # O9 -- a prebuilt-shaped directory whose .installed-sha256 DOES
        # match the manifest, but carries no real surgepy build, must still
        # be refused: a matching hash alone is not sufficient, only
        # sha-match AND a real importable-from-inside-it surgepy together
        # are (classify()'s AND, not OR).
        if pinned_sha:
            right_sha_dir = os.path.join(tmproot, "prebuilt-right-sha-no-build")
            os.makedirs(right_sha_dir)
            with open(os.path.join(right_sha_dir, ".installed-sha256"), "w",
                     encoding="utf-8") as f:
                f.write(pinned_sha)
            rc, doc = _self_json([], {"ORACLE_SURGE_DIR": right_sha_dir})
            matches = doc and doc["probe"]["prebuilt_sha256_matches"]
            importable = doc and doc["probe"]["surgepy_importable"]
            status = doc and doc["oracle_gate"]["status"]
            rec("O9", "a sha256-matched prebuilt directory with no real "
                      "surgepy build underneath it being accepted as "
                      "AVAILABLE on the strength of the hash alone",
                "prebuilt_sha256_matches TRUE, surgepy_importable FALSE, "
                "status != AVAILABLE",
                f"rc={rc} prebuilt_sha256_matches={matches} "
                f"surgepy_importable={importable} status={status}",
                rc == 0 and matches is True and importable is False
                and status != "AVAILABLE")
        else:
            rec("O9", "a sha256-matched prebuilt directory with no real "
                      "surgepy build underneath it being accepted as "
                      "AVAILABLE on the strength of the hash alone",
                "SKIPPED: no manifest.prebuilt entry for this platform "
                f"({plat!r}) to construct a matching hash from",
                "n/a", True,
                "not a gap: O8 already shows a non-matching hash is "
                "refused; this sub-case needs a real platform entry to "
                "construct a matching-but-unbuilt directory")
    finally:
        shutil.rmtree(tmproot, ignore_errors=True)

    return out, all(c["fired"] for c in out)


TRANSCRIPT = """\
SXT-036 (#70) oracle gate and backfill plan
===========================================
oracle gate: {status}
reason: {reason}

probed engine dir : {engine_dir} (present={present}, git worktree={isgit})
probed HEAD       : {head} (pin {pin}, matches={matches})
prebuilt (#232)   : platform={platform} installed_sha256={installed_sha} matches_manifest={prebuilt_matches}
surgepy, naive    : {naive}   <- a bare `import surgepy`; NOT proof of the pin
surgepy, pinned   : {pinned} (module inside the checkout={under})

Acceptance items 2 and 5 of #70 are therefore {item_status}. A leg that did
not run is never reported as a pass (AGENTS.md). Nothing in this leaf's
evidence is estimated, extrapolated, or substituted in place of a real oracle
render.

Legs, split by the gate each one actually needs
-----------------------------------------------
{legs}

Tool paths named by #70, resolved against the committed tree
------------------------------------------------------------
{tools}

Falsifiable predictions for the oracle host
-------------------------------------------
{predictions}

{rule}

Negative controls (each must demonstrably fail the check it targets)
--------------------------------------------------------------------
{controls}

Re-run on an oracle host
------------------------
  python3 tools/vel_oracle_status.py --artifacts reports/SXT-036/artifacts
  #   -> flips the gate; every leg below becomes RUNNABLE, none becomes PASS.
  # then, in order:
  #   1. blob-verify the carriers (checkout only)
  #   2. write model/voice/extract_vel_inputs.py and replace the DECLARED
  #      model/voice/attacky_vel_inputs.json with read-back depths
  #   3. write fixtures/render_vel_fixture.py and render the references
  #   4. python3 tools/compare_audio_reference.py      -> acceptance item 2
  #   5. re-run the routing-zeroed and source-swap mutations through step 4;
  #      BOTH must FAIL the reference-budget check   -> acceptance item 5
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--artifacts", default=DEFAULT_ARTIFACTS,
                    help="artifacts directory (read predictions, write status)")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--dry-run", action="store_true",
                    help="probe and assemble, but write nothing and run no "
                         "controls (used by the controls themselves)")
    ap.add_argument("--json", action="store_true",
                    help="print the assembled document to stdout")
    args = ap.parse_args()

    try:
        manifest = load_manifest(args.manifest)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        return _fail(str(e))

    p = probe(manifest)
    status, reason = classify(p)
    try:
        legs = build_legs(status)
        predictions = load_predictions(args.artifacts)
    except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        return _fail(str(e))
    tools = resolve_named_tools()

    doc = {
        "schema_version": 1,
        "tool": "vel_oracle_status/1",
        "leaf": "SXT-036",
        "issue": 70,
        "oracle_gate": {"status": status, "reason": reason},
        "probe": p,
        "legs": legs,
        "named_tool_resolution": tools,
        "backfill_predictions": predictions,
        "acceptance_items_gated": {
            "2": "NOT_RUN" if status != "AVAILABLE" else "RUNNABLE",
            "5": "NOT_RUN" if status != "AVAILABLE" else "RUNNABLE",
        },
        "rule": "AGENTS.md: a test that did not run must never be reported as "
                "a pass. This tool runs no oracle-gated leg; it records "
                "whether they COULD run. It can never move an acceptance item "
                "to PASS, and it establishes no model-vs-reference agreement, "
                "no fidelity, and no preset support.",
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(doc, indent=2, sort_keys=True))
        return 0

    lines = []

    def log(s=""):
        lines.append(s)
        print(s)

    log(f"SXT-036 oracle gate: {status}")
    log(f"  reason: {reason}")
    log("")
    log("Negative controls:")
    controls, all_fired = run_controls(args.artifacts, log)
    doc["controls"] = controls
    doc["controls_all_fired"] = all_fired
    log("")
    if not all_fired:
        log("CONTROL FAILURE: at least one control did not fire; the gate "
            "measurement above is not trustworthy.")

    os.makedirs(args.artifacts, exist_ok=True)
    with open(os.path.join(args.artifacts, "oracle-status.json"), "w",
              encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    legtxt = "\n".join(
        f"  {n:<26} item {v['acceptance_item']:<38} {v['status']}\n"
        f"      gate: {v['gate']}\n      tool: {v['tool']}"
        for n, v in sorted(legs.items()))
    tooltxt = "\n".join(
        f"  {t['named_by_issue']:<36} {t['status']:<10} "
        f"-> {t['resolves_to']}" for t in tools)
    predtxt = "\n".join(
        [f"  graphs.jsonl sha256 {predictions['graphs_sha256']}"]
        + [f"  route  {r['preset'].split('/')[-1]}: {r['modsource']} -> "
           f"{r['dest_id']} ({r['dest_name']}) depth_normalized "
           f"{r['expected_depth_normalized']}"
           for r in predictions["carrier_routes"]]
        + [f"  extent dest {k} = {v}"
           for k, v in predictions["destination_extents"].items()]
        + [f"  observed normalized range {k}: "
           f"[{v['min']}, {v['max']}] over {v['rows']} rows"
           for k, v in sorted(
               predictions["observed_source_normalized_range"].items())])
    ctltxt = "\n".join(
        f"  {c['id']} {'FIRED' if c['fired'] else 'DID NOT FIRE'}  "
        f"{c['targets']}" for c in controls)

    with open(os.path.join(args.artifacts, "oracle-backfill.txt"), "w",
              encoding="utf-8") as f:
        f.write(TRANSCRIPT.format(
            status=status, reason=reason,
            engine_dir=p["engine_dir_probed"], present=p["engine_dir_present"],
            isgit=p["engine_dir_is_git_worktree"], head=p["engine_head"],
            pin=p["engine_pin"], matches=p["engine_head_matches_pin"],
            platform=p["platform"], installed_sha=p["prebuilt_installed_sha256"],
            prebuilt_matches=p["prebuilt_sha256_matches"],
            naive=p["surgepy_importable_naive"],
            pinned=p["surgepy_importable"], under=p["surgepy_under_engine_dir"],
            item_status=doc["acceptance_items_gated"]["2"],
            legs=legtxt, tools=tooltxt, predictions=predtxt,
            rule=predictions["rule"], controls=ctltxt))

    if args.json:
        print(json.dumps(doc, indent=2, sort_keys=True))
    return 0 if all_fired else 1


if __name__ == "__main__":
    sys.exit(main())
