#!/usr/bin/env python3
"""SXT-028e-sse: validate the FuzzTable<1> re-derivation against a build of
the PINNED headers, which live OUTSIDE this repository.

DR-0014 clause 2 (as first recorded) claimed the `wst_fuzzsoft` LUT is a
RE-DERIVATION from the pinned construction formula, not quoted engine data. That claim has one
implementation-defined step -- the standard library's uniform real-valued
draw -- which the pinned header does NOT pin (it only de-typedefs the LCG).
This tool discharges the claim by construction rather than by assertion:

  1. It resolves the pinned, GPL-3.0-or-later sst-waveshapers and
     sst-basic-blocks headers in an EXTERNAL checkout (never in this tree),
     and refuses to proceed unless each resolved checkout's HEAD equals the
     submodule SHA pinned in `oracle/manifest.json`.
  2. It writes a ~15-line driver -- original to this repository, carrying no
     Surge/SST source text: it `#include`s those headers and instantiates
     the engine's OWN `LUTBase<1024, FuzzTable<1>>` -- compiles it against
     the external checkout, and dumps all 1025 float32 bit patterns.
  3. It compares them, BIT FOR BIT, with
     `model/effects/type-distortion-sse/sse_tables.build_fuzz1_row()`'s own
     pre-quantization float32 values.

No GPL-licensed source text is transcribed, embedded, or committed by this
tool: the engine's expression is never copied, it is *included* from the
pinned tree, so this check is also insensitive to transcription error.

A mismatch means the re-derivation claim is false and the table would have to
be re-classified as quoted data (a DR-0014 amendment), so this check is a
LIVE guard on a licensing-relevant claim, not decoration. That has happened:
the libc++ build on an alternate arm64 macOS host reported MISMATCH at
default flags (#135), and DR-0014 clause 3 (amended) conservatively
re-classifies the row as quoted data with provenance; the pinned-host leg is
NOT_RUN.

The pinned headers are not present on an ordinary build host. Fetch them
externally (they are never written into this repository) with:

    oracle/fetch-waveshaper-headers.sh

or point the tool at a full pinned engine checkout with `ORACLE_SURGE_DIR`.
With neither reachable the tool reports **NOT_RUN** -- never a silent pass.

LIMIT OF THE CHECK (stated, not hidden): it validates against whichever
standard library AND floating-point contraction policy the driver build
uses; both are recorded in the transcript. The standard library is detected
with the driver's own flags and include path (so `--cxxflag=-stdlib=...` is
honoured), and a failed detection is recorded as UNKNOWN, never guessed. The
transcript also compares the host with the frozen `environment` of
`oracle/manifest.json`; a run elsewhere is recorded as an
ALTERNATE-ENVIRONMENT OBSERVATION and leaves the pinned-host leg NOT_RUN.
The libstdc++ transcript is `fuzz-table-rederivation.json`. On an arm64
macOS / libc++ host that is NOT the pinned environment (Darwin 27.0.0, Apple
clang-2100.3.34.2; #135) Apple clang's DEFAULT -ffp-contract fuses
`x * a + b` into an FMA and the check reports MISMATCH (305/1025); with
`--cxxflag=-ffp-contract=off` it reports MATCH 1025/1025. The pinned
environment (macOS 26.5.1 / clang-2100.1.1.101) has NOT been run. See
DR-0014 clause 3 and EVIDENCE.md section 8.

Usage: python3 tools/check_fuzz_table_rederivation.py [--out JSON] [--cxxflag F]...
                  [--sst-include DIR]... [--cxx CXX]
Exit 0 = MATCH, 1 = MISMATCH, 77 = NOT_RUN (no toolchain / no pinned
headers), 78 = BLOCKED (the external checkout drifted from the pins).
Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))

import sse_tables as st  # noqa: E402

MANIFEST = os.path.join(REPO, "oracle", "manifest.json")

# Submodule paths inside a full pinned engine checkout, and the standalone
# directory names the external fetch helper creates.
WAVESHAPERS = ("libs/sst/sst-waveshapers", "sst-waveshapers")
BASICBLOCKS = ("libs/sst/sst-basic-blocks", "sst-basic-blocks")
SIMDE = ("libs/simde", "simde")

DEFAULT_HEADERS_DIR = os.environ.get(
    "SXT_ORACLE_HEADERS_DIR",
    os.path.join(os.environ.get("TMPDIR", "/tmp"), "sxt-oracle"))

# The driver is ORIGINAL to this repository (Apache-2.0). It contains no
# engine expression, no engine constant and no engine data: it names the
# pinned library's own types and prints what the library itself computes.
# `<string>` / `<cstdint>` are included because the pinned headers rely on
# them transitively; that is a property of the pinned tree, not of the LUT.
DRIVER_CPP = """
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <sst/waveshapers.h>

int main()
{{
    using Table = sst::waveshapers::LUTBase<{n}, sst::waveshapers::FuzzTable<{scale}>>;
    static Table table;
    for (int i = 0; i < Table::N + 1; ++i)
    {{
        unsigned u;
        std::memcpy(&u, &table.data[i], sizeof(u));
        std::printf("%08x\\n", u);
    }}
    return 0;
}}
"""


def _u32(x):
    return struct.unpack("I", struct.pack("f", x))[0]


def python_row_bits():
    """The generator's float32 values BEFORE the Q2.29 quantization."""
    draws = st._fuzz_table_scale1_sequence(st.FUZZ_SIZE)
    dx = st._f32(2.0 / st.FUZZ_N)
    rng_range = st._f32(0.1 * 1)
    one_minus = st._f32(1 - rng_range)
    out = []
    for i in range(st.FUZZ_SIZE):
        x = st._f32(st._f32(i * dx) - 1.0)
        out.append(_u32(st._f32(st._f32(x * one_minus) + draws[i])))
    return out


# ------------------------------------------------------- external headers
def pinned_shas():
    """The submodule SHAs this repository pins (oracle/manifest.json)."""
    with open(MANIFEST) as f:
        man = json.load(f)
    return {s["path"]: s["commit"] for s in man["submodules"]}


def _git_head(path):
    """HEAD of the git work tree containing `path`, or None if not a repo."""
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def _candidate_roots(names, extra_roots):
    """Directories that might BE the named external checkout."""
    sub, standalone = names
    out = []
    for root in extra_roots:
        out.append(os.path.join(root, sub))
        out.append(os.path.join(root, standalone))
    return out


def resolve_checkout(names, explicit, extra_roots):
    """Return (checkout_dir, include_dir) for one pinned dependency."""
    for d in list(explicit) + _candidate_roots(names, extra_roots):
        inc = os.path.join(d, "include")
        if os.path.isdir(inc):
            return os.path.abspath(d), os.path.abspath(inc)
        # simde has no include/ subdirectory: it IS the include root.
        if names is SIMDE and os.path.isdir(os.path.join(d, "simde", "x86")):
            return os.path.abspath(d), os.path.abspath(d)
    return None, None


def resolve_headers(args):
    """Resolve + pin-verify the external headers.

    Returns (include_dirs, defines, provenance, blocked_reason_or_None,
             missing_or_None).
    """
    extra_roots = []
    if args.oracle_surge_dir:
        extra_roots.append(args.oracle_surge_dir)
    if os.path.isdir(DEFAULT_HEADERS_DIR):
        extra_roots.append(DEFAULT_HEADERS_DIR)

    explicit = [os.path.abspath(d) for d in (args.sst_include or [])]

    pins = pinned_shas()
    prov, incs, defines = {}, [], []
    missing = []

    for key, names in (("sst-waveshapers", WAVESHAPERS),
                       ("sst-basic-blocks", BASICBLOCKS)):
        d, inc = resolve_checkout(names, explicit, extra_roots)
        if inc is None:
            missing.append(key)
            continue
        incs.append(inc)
        prov[key] = {"checkout": d, "include": inc,
                     "pinned_commit": pins[names[0]],
                     "commit": _git_head(d)}
    if missing:
        return None, None, prov, None, missing

    simde_dir, simde_inc = resolve_checkout(SIMDE, explicit, extra_roots)
    if simde_inc is not None:
        incs.append(simde_inc)
        prov["simde"] = {"checkout": simde_dir, "include": simde_inc,
                         "pinned_commit": pins[SIMDE[0]],
                         "commit": _git_head(simde_dir)}
    else:
        # Without simde the pinned SIMD setup header only has a native path,
        # which exists on x86-64 only. Anywhere else, refuse rather than
        # quietly validate a different SIMD backend than the pins name.
        if platform.machine().lower() not in ("x86_64", "amd64"):
            return None, None, prov, (
                f"the pinned {SIMDE[0]} checkout is not reachable and this "
                f"host is {platform.machine()} (not native x86-64), so the "
                "pinned SIMD setup header has no usable backend"), None
        defines.append("-DSIMDE_UNAVAILABLE")
        prov["simde"] = {"checkout": None, "include": None,
                         "pinned_commit": pins[SIMDE[0]], "commit": None,
                         "note": "not needed: native x86-64 SSE path selected "
                                 "with -DSIMDE_UNAVAILABLE"}

    # Fail closed on ANY drift from the pins, exactly as oracle/
    # fetch-and-build.sh does for the engine itself.
    for key, p in prov.items():
        if p["include"] is None:
            continue
        if p["commit"] is None:
            return None, None, prov, (
                f"{key} at {p['checkout']} is not a git checkout, so its "
                f"pinned SHA {p['pinned_commit']} cannot be verified"), None
        if p["commit"] != p["pinned_commit"]:
            return None, None, prov, (
                f"{key} at {p['checkout']} is {p['commit']}, not the pinned "
                f"{p['pinned_commit']}"), None

    return incs, defines, prov, None, None


def stdlib_detection_cmd(cxx, flags, incs):
    """The preprocessor-only command that reports which C++ standard library
    the DRIVER compile selects. It carries the driver's exact `flags`
    (including every --cxxflag, e.g. -stdlib=..., -nostdinc++, --sysroot)
    and include directories, so the recorded library is the one the driver
    was actually built against -- not the compiler's bare default."""
    return ([cxx] + list(flags) + [f"-I{d}" for d in incs]
            + ["-dM", "-E", "-x", "c++", "-include", "cstddef", os.devnull])


def detect_stdlib(cxx, flags, incs, run=subprocess.run):
    """Return (stdlib, detection_record).

    `stdlib` is "libc++ (...)", "libstdc++ (...)" or an explicit
    "UNKNOWN (...)" -- a failed or inconclusive detection is recorded as
    such, never guessed from the compiler's name."""
    cmd = stdlib_detection_cmd(cxx, flags, incs)
    det = {"command": " ".join(cmd)}
    try:
        pre = run(cmd, capture_output=True, text=True)
    except OSError as e:
        det.update(returncode=None, error=f"{type(e).__name__}: {e}")
        return f"UNKNOWN (stdlib macro detection could not run: {e})", det
    det["returncode"] = pre.returncode
    if pre.returncode != 0:
        err = (pre.stderr or "").strip().splitlines()
        det["error"] = err[-1] if err else "no diagnostic"
        return ("UNKNOWN (stdlib macro detection failed, exit "
                f"{pre.returncode}: {det['error']})"), det
    libcxx = glibcxx = None
    for line in (pre.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[:2] == ["#define", "_LIBCPP_VERSION"]:
            libcxx = parts[2]
        if len(parts) >= 3 and parts[:2] == ["#define", "__GLIBCXX__"]:
            glibcxx = parts[2]
    if libcxx and glibcxx:
        det["error"] = "both _LIBCPP_VERSION and __GLIBCXX__ defined"
        return ("UNKNOWN (both _LIBCPP_VERSION and __GLIBCXX__ are "
                "defined)"), det
    if libcxx:
        return f"libc++ (_LIBCPP_VERSION {libcxx})", det
    if glibcxx:
        return f"libstdc++ (__GLIBCXX__ {glibcxx})", det
    det["error"] = "neither _LIBCPP_VERSION nor __GLIBCXX__ defined"
    return ("UNKNOWN (neither _LIBCPP_VERSION nor __GLIBCXX__ is "
            "defined)"), det


def environment_scope(toolchain_version, mac_ver=None, manifest=MANIFEST):
    """Compare this host to the frozen `environment` in oracle/manifest.json.

    A transcript produced anywhere else is an ALTERNATE-ENVIRONMENT
    OBSERVATION: it does not discharge the pinned-host acceptance leg, which
    stays NOT_RUN. A string match on OS version + clang build is necessary,
    not sufficient -- it is recorded, and the acceptance decision stays with
    the evidence record."""
    if mac_ver is None:
        mac_ver = platform.mac_ver()[0] if platform.system() == "Darwin" \
            else ""
    with open(manifest) as f:
        env = json.load(f).get("environment", {})
    pin_os, pin_clang = env.get("os", ""), env.get("clang", "")
    pin_os_ver = pin_os.split()[1] if pin_os.startswith("macOS ") else None
    pin_clang_id = None
    if "(" in pin_clang and ")" in pin_clang:
        pin_clang_id = pin_clang.split("(", 1)[1].split(")", 1)[0]
    os_ok = bool(pin_os_ver) and mac_ver == pin_os_ver
    clang_ok = bool(pin_clang_id) and \
        f"({pin_clang_id})" in (toolchain_version or "")
    match = os_ok and clang_ok
    return {
        "pinned_environment": {"os": pin_os, "clang": pin_clang},
        "host_os_version": mac_ver or platform.platform(),
        "os_matches_pin": os_ok,
        "clang_matches_pin": clang_ok,
        "scope": ("host OS version and clang build match the "
                  "oracle/manifest.json environment strings"
                  if match else
                  "ALTERNATE-ENVIRONMENT OBSERVATION: this host is not the "
                  "oracle/manifest.json frozen environment; it does not "
                  "discharge the pinned-host acceptance leg (NOT_RUN)"),
        "pinned_host_acceptance": "see scope" if match else "NOT_RUN",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028e-sse", "artifacts",
        "fuzz-table-rederivation.json"))
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    ap.add_argument("--cxxflag", action="append", default=[], metavar="FLAG",
                    help="extra compiler flag (repeatable), e.g. "
                         "--cxxflag=-ffp-contract=off; recorded verbatim")
    ap.add_argument("--sst-include", action="append", metavar="DIR",
                    help="external checkout of a pinned dependency "
                         "(repeatable; sst-waveshapers, sst-basic-blocks, "
                         "simde)")
    ap.add_argument("--oracle-surge-dir",
                    default=os.environ.get("ORACLE_SURGE_DIR"),
                    help="full pinned engine checkout (its libs/sst/... "
                         "submodules are used)")
    args = ap.parse_args()

    py = python_row_bits()
    rec = {"schema_version": 2, "leaf": "SXT-028e-sse",
           "what": "FuzzTable<1> (FX model 7, wst_fuzzsoft) 1025-entry LUT: "
                   "re-derivation vs a build of the PINNED headers "
                   "themselves, from an external checkout",
           "entries": len(py),
           "decision_record":
               "decision-records/0014-distortion-sse-quad-waveshaper-"
               "constants.md clause 2",
           "table_digest": st.table_digest(),
           "probe_kind": "external-header-build",
           "probe_source_committed": False,
           "probe_source_note":
               "no Surge/SST source text is transcribed or committed here: "
               "the driver compiled by this tool only #includes the pinned "
               "GPL-3.0-or-later headers from an EXTERNAL checkout and "
               "instantiates the library's own LUT type"}

    cxx = shutil.which(args.cxx)
    if cxx is None:
        rec.update(status="NOT_RUN",
                   reason=f"no C++ toolchain ({args.cxx}) on this host",
                   mismatches=None, external_headers=None)
        _write(args.out, rec)
        print("NOT_RUN: no C++ toolchain; the re-derivation claim is "
              "UNVALIDATED on this host")
        return 77

    incs, defines, prov, blocked, missing = resolve_headers(args)
    rec["external_headers"] = prov
    if missing:
        rec.update(status="NOT_RUN", mismatches=None,
                   reason="the pinned GPL-3.0-or-later headers are not "
                          f"reachable on this host (missing: "
                          f"{', '.join(missing)}); they are deliberately NOT "
                          "in this repository -- run "
                          "oracle/fetch-waveshaper-headers.sh or set "
                          "ORACLE_SURGE_DIR")
        _write(args.out, rec)
        print(f"NOT_RUN: {rec['reason']}")
        return 77
    if blocked:
        rec.update(status="BLOCKED", mismatches=None, reason=blocked)
        _write(args.out, rec)
        print(f"BLOCKED: {blocked}")
        return 78

    flags = ["-O2", "-std=c++20"] + defines + list(args.cxxflag)
    with tempfile.TemporaryDirectory(prefix="sxt028e-sse-fuzz-") as td:
        src = os.path.join(td, "driver.cpp")
        exe = os.path.join(td, "driver")
        with open(src, "w") as f:
            f.write(DRIVER_CPP.format(n=st.FUZZ_N, scale=1))
        ver = subprocess.run([cxx, "--version"], capture_output=True,
                             text=True)
        # Same flags and include path as the driver compile below, so the
        # recorded library is the one the driver is actually built against.
        stdlib, stdlib_det = detect_stdlib(cxx, flags, incs)
        cmd =[cxx] + flags + [f"-I{d}" for d in incs] + ["-o", exe, src]
        subprocess.run(cmd, check=True)
        got = subprocess.run([exe], capture_output=True, text=True,
                             check=True).stdout.split()

    cpp = [int(w, 16) for w in got]
    mismatches = [i for i in range(min(len(py), len(cpp))) if py[i] != cpp[i]]
    if stdlib.startswith("libc++ "):
        libcxx_eq = "see status: this transcript was built against " + stdlib
    elif stdlib.startswith("libstdc++ "):
        libcxx_eq = ("UNVERIFIED-BY-BUILD (this run used libstdc++; derived "
                     "by reading libc++'s generate_canonical, see "
                     "sse_tables.py)")
    else:
        libcxx_eq = ("UNVERIFIED-BY-BUILD (the standard library of this "
                     "build could not be identified: " + stdlib + ")")
    rec.update(
        status="MATCH" if (not mismatches and len(py) == len(cpp))
               else "MISMATCH",
        toolchain=(ver.stdout or "").splitlines()[0] if ver.stdout else cxx,
        compile_flags=" ".join(flags),
        stdlib_validated=stdlib,
        stdlib_detection=stdlib_det,
        host={"uname": " ".join(platform.uname()),
              "machine": platform.machine()},
        environment=environment_scope(ver.stdout or ""),
        libcxx_equivalence=libcxx_eq,
        cpp_entries=len(cpp), mismatches=len(mismatches),
        first_mismatch_index=mismatches[0] if mismatches else None)
    _write(args.out, rec)
    print(f"{rec['status']}: {len(cpp)} entries, {len(mismatches)} mismatches "
          f"({rec['toolchain']})")
    return 0 if rec["status"] == "MATCH" else 1


def _write(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rec, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    sys.exit(main())
