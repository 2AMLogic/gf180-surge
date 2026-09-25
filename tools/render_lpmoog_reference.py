#!/usr/bin/env python3
"""SXT-039 reference renderer: the PINNED LP Legacy Ladder kernel, built and
run OUTSIDE this repository (DR-0009).

What this produces is a **pinned-kernel reference** at the filter-stage
boundary: the pinned `sst-filters` coefficient maker and `LPMOOGquad` kernel,
at the submodule commit pinned by `oracle/manifest.json`, compiled standalone
and driven with the fixture's own float32 control plane and input samples
(`model/voice/filter_lpmoog/fixtures.py`).

What it is NOT, and never claims to be:

  * it is NOT the full pinned Surge engine.  The engine-integrated leg (a real
    carrier render through the whole voice path, with the engine's own
    cutoff/filter-EG trajectories and its own voice signal) needs the oracle
    host and the SXT-037-class tap (DR-0005); it is recorded NOT_RUN in
    `reports/SXT-039/EVIDENCE.md` and routed as a follow-up.
  * it establishes NO preset-support or musical-quality claim.

Licensing (DR-0009): the emitted harness source is original to this
repository, but it `#include`s GPL-3.0-or-later headers, so the harness source
and its binary are written **outside** the repository tree (the tool refuses
to write inside it) and are never committed.  No Surge/SST source, table or
asset is copied into this repository; the reference DATA this tool renders is
committed, exactly as the SXT-037 tap bundles are.

Fail-closed:
  * the pinned headers are sha256-verified before anything is built (exit 3);
  * a workdir inside the repository is refused (exit 3);
  * a compile or run failure is an error, never a silent skip.

Usage:
  python3 tools/render_lpmoog_reference.py --cases all \
      --sst-filters /path/to/sst-filters --sst-basic-blocks /path/to/sst-basic-blocks \
      --out-dir reports/SXT-039/artifacts
"""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lpmoog"))

import fixtures as fx  # noqa: E402

# Pinned submodule commits (oracle/manifest.json) and the sha256 of every
# pinned header this harness compiles against.  A mismatch is fail-closed.
PINS = {
    "sst-filters": {
        "commit": "e92d93a92beabde03fa4ab767b285fa21c6608d6",
        "files": {
            "include/sst/filters/FilterCoefficientMaker_Impl.h":
                "9a43b93a373e81de396ffff3b13afc6571a9d9a891d7b2613b98c3424cb56fd6",
            "include/sst/filters/QuadFilterUnit_Impl.h":
                "4e26a895cbef6915aad69f2031f4ec2181ab29f8077b2e60b9bbec369e6338d5",
            "include/sst/filters/FilterConfiguration.h":
                "6eeb8ee16b68f06edf8b6d2ac1ee5559c608aedc741b3532529b3f936a42b97c",
        },
    },
    "sst-basic-blocks": {
        "commit": "a32b8aec14d661e415bb676bb2e2a0a4da4efc96",
        "files": {
            "include/sst/basic-blocks/dsp/Clippers.h":
                "33dda63defd35a97a7f944d3da106f922fe4b72f84fa533010ab283db06af7f4",
        },
    },
}
ENGINE_PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"

# The harness: original glue only.  It calls the pinned API; it copies no
# pinned implementation.  The SurgeStorage tuning path is reproduced from the
# pinned table CONSTRUCTION FORMULAS (SurgeStorage.cpp table_pitch /
# table_two_to_the), so the coefficient input matches what the engine's own
# provider computes at standard 12-TET tuning.
HARNESS_CPP = r"""
// SXT-039 pinned-kernel reference harness (generated; NOT part of the
// gf180-surge repository -- see DR-0009).  Original glue around the pinned
// GPL-3.0-or-later sst-filters / sst-basic-blocks headers; the combined work
// is GPL-3.0-or-later and stays outside the Apache-2.0 repository.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "sst/filters/QuadFilterUnit.h"
#include "sst/filters/FilterCoefficientMaker.h"
#include "sst/filters/VintageLadders.h"
#include "sst/filters/OBXDFilter.h"
#include "sst/filters/K35Filter.h"
#include "sst/filters/DiodeLadder.h"
#include "sst/filters/CutoffWarp.h"
#include "sst/filters/ResonanceWarp.h"
#include "sst/filters/TriPoleFilter.h"
#include "sst/filters/CytomicSVFQuadForm.h"
#include "sst/filters/CytomicSVF.h"
#include "sst/filters/CytomicTilt.h"
#include "sst/filters/FastTiltNoiseFilter.h"
#include "sst/filters/FilterCoefficientMaker_Impl.h"
#include "sst/filters/QuadFilterUnit_Impl.h"

// Tuning provider reproducing SurgeStorage::note_to_pitch_ignoring_tuning at
// standard 12-TET (table construction formulas cited from SurgeStorage.cpp:
// table_pitch[i] = powf(2, (i-256)/12); table_two_to_the[i] = pow(2, i/12000)).
struct SurgeLikeTuning
{
    static constexpr int TABLE = 512;
    // Tunings::MIDI_0_FREQ (used by other filter types' coefficient makers;
    // fut_lpmoog does not read it, but the template instantiates them all)
    static constexpr double MIDI_0_FREQ = 8.17579891564371;
    float table_pitch[TABLE];
    float table_two_to_the[1001];
    SurgeLikeTuning()
    {
        for (int i = 0; i < TABLE; ++i)
            table_pitch[i] = powf(2.f, ((float)i - 256.f) * (1.f / 12.f));
        for (int i = 0; i < 1001; ++i)
            table_two_to_the[i] = (float)pow(2.0, i * 1.0 / 12.0 / 1000.0);
    }
    float note_to_pitch_ignoring_tuning(float x)
    {
        x = std::max(1.e-4f, std::min(x + 256.f, (float)TABLE - 1.e-4f));
        int e = (int)x;
        float a = x - (float)e;
        float pow2pos = a * 1000.f;
        int idx = (int)pow2pos;
        float frac = pow2pos - idx;
        float pow2v = (1 - frac) * table_two_to_the[idx] + frac * table_two_to_the[idx + 1];
        return table_pitch[e] * pow2v;
    }
    float note_to_pitch(float x) { return note_to_pitch_ignoring_tuning(x); }
    float note_to_pitch_inv_ignoring_tuning(float x)
    {
        return 1.f / note_to_pitch_ignoring_tuning(x);
    }
    // Required only so the coefficient makers of OTHER filter types still
    // instantiate (the template compiles all of them).  The fut_lpmoog path
    // never calls it; Coeff_LP4L reads note_to_pitch_ignoring_tuning only.
    void note_to_omega_ignoring_tuning(float x, float &sinu, float &cosi, float sampleRate)
    {
        auto arg = 2.f * (float)M_PI * std::min(0.5f, 440.f *
                                                          note_to_pitch_ignoring_tuning(x) /
                                                          sampleRate);
        sinu = sinf(arg);
        cosi = cosf(arg);
    }
};

struct BlockCtl
{
    int subtype, reset;
    float cut, kt, pitch, ktroot, em, fenv, reso;
};

int main(int argc, char **argv)
{
    if (argc != 5)
    {
        fprintf(stderr, "usage: %s ctl.bin stim.f32 out.f32 coeffs.bin\n", argv[0]);
        return 2;
    }
    FILE *fc = fopen(argv[1], "rb");
    if (!fc) { fprintf(stderr, "cannot open %s\n", argv[1]); return 2; }
    int nblocks = 0;
    if (fread(&nblocks, sizeof(int), 1, fc) != 1) return 2;
    std::vector<BlockCtl> ctl(nblocks);
    if ((int)fread(ctl.data(), sizeof(BlockCtl), nblocks, fc) != nblocks) return 2;
    fclose(fc);

    const int BOS = 64;
    std::vector<float> in(nblocks * BOS);
    FILE *fs = fopen(argv[2], "rb");
    if (!fs) { fprintf(stderr, "cannot open %s\n", argv[2]); return 2; }
    if ((int)fread(in.data(), sizeof(float), in.size(), fs) != (int)in.size()) return 2;
    fclose(fs);

    using namespace sst::filters;
    SurgeLikeTuning tuning;
    FilterCoefficientMaker<SurgeLikeTuning> cm;
    cm.setSampleRateAndBlockSize(96000.f, BOS);   // dsamplerate_os, BLOCK_SIZE_OS
    QuadFilterUnitState qfu{};
    memset(&qfu, 0, sizeof(qfu));
    float reg[5] = {0, 0, 0, 0, 0};               // FBP.FU[u].R (per-voice)

    std::vector<float> out(nblocks * BOS);
    std::vector<float> coefdump;
    coefdump.reserve(nblocks * 21);

    for (int b = 0; b < nblocks; ++b)
    {
        const BlockCtl &c = ctl[b];
        if (c.reset)
        {
            memset(reg, 0, sizeof(reg));          // memset(&FBP.FU[u], 0, ...)
            cm.Reset();                           // CM[u].Reset()
        }
        // SurgeVoice.cpp process_block cutoff arithmetic (float32)
        float keytrack = c.pitch - c.ktroot;
        float cutoffA = c.cut + c.kt * keytrack + c.em * c.fenv;
        cm.MakeCoeffs(cutoffA, c.reso, fut_lpmoog, (FilterSubType)c.subtype, &tuning, false);
        cm.updateState(qfu);
        for (int i = 0; i < 5; ++i)
            qfu.R[i] = SIMD_MM(set1_ps)(reg[i]);
        for (int i = 0; i < 8; ++i) coefdump.push_back(cm.C[i]);
        for (int i = 0; i < 8; ++i) coefdump.push_back(cm.dC[i]);

        auto fn = GetQFPtrFilterUnit(fut_lpmoog, (FilterSubType)c.subtype);
        if (!fn) { fprintf(stderr, "no kernel for subtype %d\n", c.subtype); return 2; }
        float lane[4];
        for (int k = 0; k < BOS; ++k)
        {
            auto y = fn(&qfu, SIMD_MM(set1_ps)(in[b * BOS + k]));
            SIMD_MM(storeu_ps)(lane, y);
            out[b * BOS + k] = lane[0];
        }
        // SurgeVoice.cpp GetQFB(): registers and advanced coefficients back
        for (int i = 0; i < 5; ++i)
        {
            SIMD_MM(storeu_ps)(lane, qfu.R[i]);
            reg[i] = lane[0];
        }
        cm.updateCoefficients(qfu);
        for (int i = 0; i < 5; ++i) coefdump.push_back(reg[i]);
    }

    FILE *fo = fopen(argv[3], "wb");
    fwrite(out.data(), sizeof(float), out.size(), fo);
    fclose(fo);
    FILE *fd = fopen(argv[4], "wb");
    fwrite(coefdump.data(), sizeof(float), coefdump.size(), fd);
    fclose(fd);
    fprintf(stdout, "OK blocks=%d samples=%zu\n", nblocks, out.size());
    return 0;
}
"""

CTL_STRUCT = "<ii7f"        # subtype, reset, cut, kt, pitch, ktroot, em, fenv, reso


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_pins(dirs):
    """Fail-closed pin verification of every pinned header (exit 3)."""
    seen = {}
    for lib, pin in PINS.items():
        root = dirs[lib]
        for rel, want in pin["files"].items():
            path = os.path.join(root, rel)
            if not os.path.exists(path):
                raise SystemExit(f"[exit 3] pinned header missing: {path}")
            got = sha256(path)
            if got != want:
                raise SystemExit(f"[exit 3] pinned header sha mismatch for {rel}:\n"
                                 f"  expected {want}\n  got      {got}\n"
                                 f"The reference leg refuses to run against an "
                                 f"off-pin tree.")
            seen[f"{lib}/{rel}"] = got
    return seen


def build_harness(dirs, workdir):
    src = os.path.join(workdir, "sxt039_lpmoog_harness.cpp")
    with open(src, "w", encoding="utf-8") as f:
        f.write(HARNESS_CPP)
    binpath = os.path.join(workdir, "sxt039_lpmoog_harness")
    cmd = ["g++", "-O2", "-std=c++20", "-msse4.2", "-DSIMDE_UNAVAILABLE",
           "-I", os.path.join(dirs["sst-filters"], "include"),
           "-I", os.path.join(dirs["sst-basic-blocks"], "include"),
           "-o", binpath, src]
    subprocess.run(cmd, check=True)
    return binpath, sha256(src), " ".join(cmd)


def render_case(binpath, case, workdir, out_dir):
    spec = fx.build(case)
    n = spec["n_blocks"]
    ctl_path = os.path.join(workdir, f"ctl-{case}.bin")
    with open(ctl_path, "wb") as f:
        f.write(struct.pack("<i", n))
        for blk in spec["blocks"]:
            f.write(struct.pack(CTL_STRUCT, int(blk["subtype"]), int(bool(blk["reset"])),
                                blk["cut"], blk["keytrack"], blk["pitch"],
                                blk["keytrack_root"], blk["envmod"], blk["fenv"],
                                blk["reso"]))
    stim_path = os.path.join(workdir, f"stim-{case}.f32")
    with open(stim_path, "wb") as f:
        f.write(struct.pack(f"<{len(spec['input'])}f", *spec["input"]))
    out_path = os.path.join(out_dir, f"ref-{case}.f32")
    coef_path = os.path.join(out_dir, f"refcoef-{case}.f32")
    subprocess.run([binpath, ctl_path, stim_path, out_path, coef_path], check=True,
                   stdout=subprocess.DEVNULL)
    return spec, out_path, coef_path, sha256(stim_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=["all"])
    ap.add_argument("--sst-filters", default=os.environ.get("SXT039_SST_FILTERS_DIR"))
    ap.add_argument("--sst-basic-blocks",
                    default=os.environ.get("SXT039_SST_BASIC_BLOCKS_DIR"))
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports", "SXT-039",
                                                      "artifacts"))
    ap.add_argument("--workdir", default=None,
                    help="external build dir (default: a fresh temp dir; must "
                         "be outside the repository)")
    ap.add_argument("--keep-workdir", action="store_true")
    args = ap.parse_args()

    if not args.sst_filters or not args.sst_basic_blocks:
        raise SystemExit("[exit 3] --sst-filters and --sst-basic-blocks are required "
                         "(pinned checkouts, kept outside this repository)")
    dirs = {"sst-filters": os.path.abspath(args.sst_filters),
            "sst-basic-blocks": os.path.abspath(args.sst_basic_blocks)}
    hashes = verify_pins(dirs)

    workdir = args.workdir or tempfile.mkdtemp(prefix="sxt039-pinned-kernel-")
    workdir = os.path.abspath(workdir)
    if os.path.commonpath([workdir, REPO]) == REPO:
        raise SystemExit(f"[exit 3] refusing to build GPL-linked harness inside the "
                         f"repository ({workdir}); pass --workdir outside {REPO}")
    os.makedirs(workdir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    binpath, harness_sha, cmdline = build_harness(dirs, workdir)
    cases = sorted(fx.CASES) if args.cases == ["all"] else args.cases
    index = {
        "schema_version": 1,
        "issue": "SXT-039",
        "leg": "L2-kernel (pinned sst-filters kernel, standalone build; NOT the "
               "full engine -- see reports/SXT-039/EVIDENCE.md)",
        "engine_pin": ENGINE_PIN,
        "submodule_pins": {k: v["commit"] for k, v in PINS.items()},
        "pinned_header_sha256": hashes,
        "harness": {
            "source_sha256": harness_sha,
            "compile_command": cmdline.replace(workdir, "<WORKDIR>"),
            "location": "external to the repository (DR-0009)",
        },
        "cases": {},
    }
    for case in cases:
        spec, out_path, coef_path, stim_sha = render_case(binpath, case, workdir,
                                                          args.out_dir)
        with open(out_path, "rb") as f:
            data = f.read()
        vals = struct.unpack(f"<{len(data) // 4}f", data)
        index["cases"][case] = {
            "samples": len(vals),
            "peak_abs": max(abs(v) for v in vals),
            "ref_sha256": sha256(out_path),
            "coef_sha256": sha256(coef_path),
            "stimulus_sha256": stim_sha,
            "subtypes": sorted({int(b["subtype"]) for b in spec["blocks"]}),
            "fenv_source": spec["fenv_source"],
            "carrier": spec["carrier"]["rel"],
            "override": spec["override"],
        }
        print(f"{case}: {len(vals)} samples, peak {index['cases'][case]['peak_abs']:.6f}")
    with open(os.path.join(args.out_dir, "reference-index.json"), "w",
              encoding="utf-8") as f:
        json.dump(index, f, indent=2)
        f.write("\n")
    if not args.keep_workdir and not args.workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
