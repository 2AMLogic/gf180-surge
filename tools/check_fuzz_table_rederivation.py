#!/usr/bin/env python3
"""SXT-028e-sse: validate the FuzzTable<1> re-derivation against a C++ build.

DR-0014 clause 2 claims the `wst_fuzzsoft` LUT is a RE-DERIVATION from the
pinned construction formula, not quoted engine data. That claim has one
implementation-defined step -- `std::uniform_real_distribution<float>` --
which the pinned header does NOT pin (it only de-typedefs the LCG). This
tool discharges the claim by construction rather than by assertion:

  1. It writes a ~20-line C++ program containing ONLY the pinned header's own
     `FuzzTable<scale>` expression and `LUTBase`'s `data[i] = F(i*dx - 1.0)`
     loop -- transcribed, cited, and NOT committed to this repository (it is
     written to a temporary directory and deleted with it).
  2. It compiles that with the host C++ toolchain and dumps all 1025 float32
     bit patterns.
  3. It compares them, BIT FOR BIT, with
     `model/effects/type-distortion-sse/sse_tables.build_fuzz1_row()`'s own
     pre-quantization float32 values.

A mismatch means the re-derivation claim is false and the table would have to
be re-classified as quoted data (a DR-0014 amendment), so this check is a
LIVE guard on a licensing-relevant claim, not decoration.

LIMIT OF THE CHECK (stated, not hidden): it validates against whichever
standard library the host toolchain uses. On this build host that is
libstdc++. The libc++ equivalence is derived by reading its
`generate_canonical` (see sse_tables.py) and is recorded as
UNVERIFIED-BY-BUILD. The pinned oracle host is arm64 macOS / libc++
(`oracle/manifest.json`), so re-running this tool there is a named follow-up,
not a completed leg.

Usage: python3 tools/check_fuzz_table_rederivation.py [--out JSON]
Exit 0 = MATCH, 1 = MISMATCH, 77 = NOT_RUN (no C++ toolchain).
Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))

import sse_tables as st  # noqa: E402

# Transcribed from, and cited to:
#   libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce
#     include/sst/waveshapers/Fuzzes.h        (portable_minstd_rand, FuzzTable)
#     include/sst/waveshapers/WaveshaperLUT.h (LUTBase)
# GPL-3.0-or-later. Written to a TEMPORARY directory only; never committed.
PROBE_CPP = r"""
#include <random>
#include <cstdio>
#include <cstring>
using portable_minstd_rand =
    std::linear_congruential_engine<uint_fast32_t, 48271, 0, 2147483647>;
template <int scale> float FuzzTable(const float x)
{
    static auto gen = portable_minstd_rand(2112);
    const float range = 0.1 * scale;
    static auto dist = std::uniform_real_distribution<float>(-range, range);
    auto xadj = x * (1 - range) + dist(gen);
    return xadj;
}
int main()
{
    const int N = 1024;
    static constexpr float dx = 2.0 / N;
    for (int i = 0; i < N + 1; ++i)
    {
        float x = i * dx - 1.0;
        float v = FuzzTable<1>(x);
        unsigned u;
        std::memcpy(&u, &v, sizeof(u));
        printf("%08x\n", u);
    }
    return 0;
}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028e-sse", "artifacts",
        "fuzz-table-rederivation.json"))
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    args = ap.parse_args()

    py = python_row_bits()
    rec = {"schema_version": 1, "leaf": "SXT-028e-sse",
           "what": "FuzzTable<1> (FX model 7, wst_fuzzsoft) 1025-entry LUT: "
                   "re-derivation vs a build of the pinned header's own "
                   "expression",
           "entries": len(py),
           "decision_record":
               "decision-records/0014-distortion-sse-quad-waveshaper-"
               "constants.md clause 2",
           "table_digest": st.table_digest()}

    cxx = shutil.which(args.cxx)
    if cxx is None:
        rec.update(status="NOT_RUN",
                   reason=f"no C++ toolchain ({args.cxx}) on this host",
                   mismatches=None)
        _write(args.out, rec)
        print("NOT_RUN: no C++ toolchain; the re-derivation claim is "
              "UNVALIDATED on this host")
        return 77

    with tempfile.TemporaryDirectory(prefix="sxt028e-sse-fuzz-") as td:
        src = os.path.join(td, "probe.cpp")
        exe = os.path.join(td, "probe")
        with open(src, "w") as f:
            f.write(PROBE_CPP)
        ver = subprocess.run([cxx, "--version"], capture_output=True,
                             text=True)
        subprocess.run([cxx, "-O2", "-std=c++17", "-o", exe, src], check=True)
        got = subprocess.run([exe], capture_output=True, text=True,
                             check=True).stdout.split()

    cpp = [int(w, 16) for w in got]
    mismatches = [i for i in range(min(len(py), len(cpp))) if py[i] != cpp[i]]
    rec.update(
        status="MATCH" if (not mismatches and len(py) == len(cpp))
               else "MISMATCH",
        toolchain=(ver.stdout or "").splitlines()[0] if ver.stdout else cxx,
        stdlib_validated="libstdc++ (host toolchain)"
                         if "g++" in os.path.basename(cxx) else "host default",
        libcxx_equivalence="UNVERIFIED-BY-BUILD (derived by reading libc++'s "
                           "generate_canonical; see sse_tables.py). The "
                           "pinned oracle host is arm64 macOS / libc++ — "
                           "re-running this tool there is a named follow-up.",
        cpp_entries=len(cpp), mismatches=len(mismatches),
        first_mismatch_index=mismatches[0] if mismatches else None,
        probe_source_committed=False,
        probe_source_note="the C++ probe transcribes GPL-3.0-or-later header "
                          "expressions and is written to a temporary "
                          "directory only; it is never committed here")
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
