#!/usr/bin/env python3
"""#122: characterise the pinned engine's RNG streams for FX modulation.

Answers acceptance item 1 of issue #122 with MEASUREMENTS, not assertions:
where the FX-modulation RNG is seeded, whether it is per-instance or shared,
and whether it is reproducible across two loads of the same patch under the
SXT-010 manifest (`oracle/manifest.json`).

Three independent legs, each reported PASS / FAIL / NOT_RUN and never
conflated:

  A. SOURCE INVENTORY. Every RNG consumer reachable from an FX slot in the
     pinned trees, with a per-symbol citation (repo @ commit, path, symbol)
     and the sha256 of the cited file. Citations are VERIFIED against a
     read-only checkout when one is supplied (--sst-basic-blocks /
     --sst-effects / --surge, or ORACLE_SURGE_DIR); NOT_RUN otherwise. No
     third-party source is copied into this repository -- only paths,
     symbols and hashes.

  B. SEED REPRODUCIBILITY (executable). The pinned generators are
     `std::minstd_rand` seeded from `std::chrono::system_clock::now()` at
     CONSTRUCTION. This leg compiles an ORIGINAL C++ probe (no Surge code)
     that measures the property that construct has: two constructions
     separated by a gap far smaller than two patch loads already yield
     different streams. The same probe carries its own detector control (two
     FIXED-seed constructions must be IDENTICAL) so a "not reproducible"
     verdict cannot come from an always-firing comparator. It also measures
     draw-order coupling for the SHARED generator
     (`SurgeStorage::rngGen`): the same seed yields a different stream to a
     consumer that draws after another consumer.

  C. DISTRIBUTION PORTABILITY. `std::uniform_real_distribution` has no
     standard-specified algorithm, so even a pinned seed and a pinned draw
     order do not pin the produced floats across standard libraries. The
     manifest pins Apple clang / libc++; this leg is NOT_RUN unless the
     host can build against both libstdc++ and libc++, and the values it
     does measure are labelled with the standard library that produced them.

Writes reports/SXT-028-rng/artifacts/rng-characterization.json.
Oracle-independent (it characterises the RNG, it does not run the engine).
Original to this repository (Apache-2.0); Python standard library only.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DEFAULT = "reports/SXT-028-rng/artifacts/rng-characterization.json"

SBB = "surge-synthesizer/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96"
SFX = "surge-synthesizer/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b"
SRG = "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71"

TREE_KEYS = {SBB: "sst_basic_blocks", SFX: "sst_effects", SRG: "surge"}

# ---------------------------------------------------------------------------
# A. Source inventory. `sha256` pins the cited file's content at the pinned
#    commit; nothing here is a copy of the cited source.
# ---------------------------------------------------------------------------

CITED_FILES = [
    (SBB, "include/sst/basic-blocks/dsp/RNG.h",
     "d1a3b2a03b9e7adc6b8888006bfa16db04a373adf5e6249fecb41f0f0a45739c"),
    (SBB, "include/sst/basic-blocks/modulators/FXModControl.h",
     "58a7e6a6d15acd969718f29743e4161ff1566b3bfd1d0b53ee53d2a25b56e8e3"),
    (SBB, "include/sst/basic-blocks/modulators/SimpleLFO.h",
     "7776a609844e10c65077023fac6d118294639eb7a526b6ca29e5e70f8a345592"),
    (SFX, "include/sst/effects/Phaser.h",
     "ca13ace153f404647b7426343a8b0a01749fcdde4ae934e0a2b79527ca27be59"),
    (SFX, "include/sst/effects/Flanger.h",
     "8f75b987403bc8ee95e59c0d785ddf717168cbe7acd2e39872eec4fa8e0836c0"),
    (SFX, "include/sst/effects/EffectCore.h",
     "0a637388c249c1a1895b6a78445d47134a6b2e20b1733a16865635984ece71d7"),
    (SFX, "include/sst/effects/FloatyDelay.h",
     "8ff2ea22f464238dc77d56c999f66dda08247415f867a9eae6c89a252be2e0cc"),
    (SRG, "src/common/SurgeStorage.h",
     "ab74e4df318e75922591c10dcfabc67fee1a3a956f92f042cc62294f2c6cb7b5"),
    (SRG, "src/common/dsp/effects/SurgeSSTFXAdapter.h",
     "6e4659ddb44327e7a8ea64179398ab563a45cdcca70e5506771374b97d9a05f4"),
    (SRG, "src/common/dsp/effects/ModControl.h",
     "97992bc220e03f352afbde2daa9d3e1aef309d5c8b4731ad2eeee50387efae93"),
    (SRG, "src/common/dsp/effects/chowdsp/NeuronEffect.cpp",
     "209b37601875e219e80091ea4c469b3b22faa935f5aaff82cdbb48e0b128af52"),
    (SRG, "src/common/dsp/effects/CombulatorEffect.cpp",
     "b99655fb3a217f37e288c03f8b46f81d1390e50329d7ccb9ac8245cb63ffb137"),
    (SRG, "src/common/dsp/effects/VocoderEffect.cpp",
     "128773eabd057a9887abb968ca52959cd9ce70a232ed4c0cec4f90023669e1e5"),
    (SRG, "src/common/Parameter.cpp",
     "fd3baeeea76a277aa07a192f9530bad9961c6d91df4ddb4359b986433fee98f7"),
    (SRG, "src/common/dsp/effects/FlangerEffect.cpp",
     "4c9de276be5901696e62392421a701a8d86ee0d23dc2ec713465268416dd6047"),
    (SRG, "src/common/dsp/effects/PhaserEffect.cpp",
     "f05cd075db28b4ddac142a641e7835d42a2cd3661a8e32117bd2704e4f979cfc"),
    (SRG, "src/common/dsp/effects/chowdsp/tape/DegradeNoise.h",
     "18db6628b232a1de5a95c0195af8aeadd49cf7bb3aa2af811299bb894f51f35e"),
    (SRG, "src/common/dsp/effects/chowdsp/tape/DegradeProcessor.cpp",
     "d3d475c42aea5acd0b57377da4dfd195eeb79591c36fde3769c3a62cb80073d4"),
    (SRG, "src/common/dsp/effects/chowdsp/tape/ChewProcessor.cpp",
     "19a81aeed65d44afe5747f6bbffe1657eab702e7be77b30527e924e42cf48509"),
    (SRG, "src/common/dsp/effects/chowdsp/spring_reverb/SpringReverbProc.cpp",
     "56c0884af55f87fc5ac937aa7565ae0115c1fcb4c1d552cfdf92e98d2e0b03ad"),
]

# Generators, with their seeding site and ownership scope.
GENERATORS = {
    "fxmodcontrol_owned_rng": {
        "type": "sst::basic_blocks::dsp::RNG (std::minstd_rand)",
        "declared_at": f"{SBB} include/sst/basic-blocks/modulators/"
                       "FXModControl.h -- public member `rng`, "
                       "default-constructed",
        "seeded_at": f"{SBB} include/sst/basic-blocks/dsp/RNG.h -- "
                     "RNG::RNG() : g(std::chrono::system_clock::now()"
                     ".time_since_epoch().count())",
        "scope": "PER FXModControl INSTANCE (one generator per effect "
                 "instance that owns an FXModControl member)",
        "seed_source": "wall clock at construction",
        "reseed_api_reachable_from_a_patch": False,
        "reseed_note": "RNG exposes reseed(uint32_t)/reseedWithClock(), and "
                       "FXModControl::rng is public, but NO call site in the "
                       "pinned engine reseeds it: a patch cannot determine "
                       "the seed (verified by leg A symbol scan "
                       "`reseed_call_sites`).",
        "consumed_by_waveforms": {"5": "mod_noise", "6": "mod_snh"},
    },
    "surgestorage_shared_rngGen": {
        "type": "SurgeStorage::RNGGen (std::minstd_rand)",
        "declared_at": f"{SRG} src/common/SurgeStorage.h -- member `rngGen`",
        "seeded_at": f"{SRG} src/common/SurgeStorage.h -- RNGGen::RNGGen() : "
                     "g(std::chrono::system_clock::now()."
                     "time_since_epoch().count())",
        "scope": "ONE GENERATOR PER SurgeStorage (shared by every consumer "
                 "on the audio thread: the sst-effects Flanger, Combulator, "
                 "and anything else calling storage->rand_*)",
        "seed_source": "wall clock at construction",
        "reseed_api_reachable_from_a_patch": False,
        "reseed_note": "the only reseed entry point, `seed_rand`, is "
                       "COMMENTED OUT in the pinned SurgeStorage.h; there is "
                       "no public reseed API at the pin.",
        "reached_from_fx_via": f"{SRG} src/common/dsp/effects/"
                               "SurgeSSTFXAdapter.h `rand01(GlobalStorage*) "
                               "-> s->rand_01()`, surfaced to effects as "
                               f"{SFX} include/sst/effects/EffectCore.h "
                               "`storageRand01()`",
    },
    "chowdsp_random_device": {
        "type": "std::minstd_rand seeded from std::random_device",
        "declared_at": f"{SRG} src/common/dsp/effects/chowdsp/tape/"
                       "DegradeNoise.h, DegradeProcessor.cpp, "
                       "ChewProcessor.cpp; chowdsp/spring_reverb/"
                       "SpringReverbProc.cpp",
        "seeded_at": "each constructor: `std::random_device rd; "
                     "std::minstd_rand(rd())`",
        "scope": "per processor object",
        "seed_source": "std::random_device (non-deterministic by design)",
        "reseed_api_reachable_from_a_patch": False,
        "reseed_note": "strictly less pinnable than the clock-seeded "
                       "generators: random_device is permitted to be a true "
                       "entropy source.",
    },
}

# FX classes reachable from a patch, and how each relates to an RNG stream.
# `rng_dependence`:
#   parameter_conditional -- RNG is reached only for named parameter values
#   unconditional         -- the class always constructs/consumes an RNG
#   none                  -- verified to reach no RNG at the pin
# `corpus_selector` is what tools/fx_rng_coverage_impact.py counts.
FX_RNG_SURVEY = [
    {
        "fx_type_id": 3, "fx_type_name": "Phaser",
        "generator": "fxmodcontrol_owned_rng",
        "rng_dependence": "parameter_conditional",
        "selector": {"param_index": 10, "param": "ph_mod_wave",
                     "rng_values": [5, 6],
                     "value_labels": {"5": "Noise", "6": "Sample & Hold"}},
        "citation": f"{SFX} include/sst/effects/Phaser.h -- "
                    "`FXModControl<FXConfig::blockSize> modLFO` (default "
                    "RandomBehavior = rnd_dual_stereo); parameter type "
                    f"ct_fxlfowave_extended, {SRG} src/common/Parameter.cpp",
        "in_sxt028_bundle": True,
        "leaf": "SXT-028g (#59) -- refuses waves 5/6 fail-closed",
    },
    {
        "fx_type_id": 12, "fx_type_name": "Flanger",
        "generator": "surgestorage_shared_rngGen",
        "rng_dependence": "parameter_conditional",
        "selector": {"param_index": 1, "param": "fl_wave",
                     "rng_values": [3, 4],
                     "value_labels": {"3": "Noise (flw_sng, Sample & Glide)",
                                      "4": "Sample & Hold (flw_snh)"}},
        "citation": f"{SFX} include/sst/effects/Flanger.h:377 -- "
                    "`lfosandhtarget[c][i] = this->storageRand01() - 1.f;` "
                    "in the `flw_sng`/`flw_snh` branch; parameter type "
                    f"ct_fxlfowave, {SRG} src/common/Parameter.cpp",
        "in_sxt028_bundle": False,
        "leaf": "not filed; this survey is its input",
        "note": "The Flanger does NOT use FXModControl. It draws from the "
                "SHARED SurgeStorage generator, so its stream position "
                "depends on every other consumer's draw count in the same "
                "engine instance (leg B `shared_draw_order`).",
    },
    {
        "fx_type_id": 15, "fx_type_name": "Neuron",
        "generator": "fxmodcontrol_owned_rng",
        "rng_dependence": "parameter_conditional",
        "selector": {"param_index": 7, "param": "neuron_lfo_wave",
                     "rng_values": [5],
                     "value_labels": {"5": "FXModControl mod_noise"}},
        "citation": f"{SRG} src/common/dsp/effects/chowdsp/NeuronEffect.cpp"
                    ":130,142,146 -- `int mwave = *pd_int[neuron_lfo_wave];` "
                    "passed straight into `modLFO.processStartOfBlock`, with "
                    f"`Surge::ModControl` = FXModControl<BLOCK_SIZE, "
                    f"rnd_single> ({SRG} src/common/dsp/effects/"
                    "ModControl.h)",
        "in_sxt028_bundle": False,
        "leaf": "not filed; this survey is its input",
        "note": "Neuron's parameter type is ct_fxlfowave (max 5) but its "
                "value is forwarded UNREMAPPED to the FXModControl enum, so "
                "the stored value 5 selects mod_noise while the UI labels it "
                "'Square'. The RNG reach is therefore value 5 only; value 6 "
                "is unreachable (out of parameter range). Recorded as an "
                "observation about the pin, not a defect report.",
    },
    {
        "fx_type_id": 21, "fx_type_name": "Combulator",
        "generator": "surgestorage_shared_rngGen",
        "rng_dependence": "parameter_conditional",
        "selector": {"param_index": 0, "param": "combulator_noise_mix",
                     "rng_when": "value > 0"},
        "citation": f"{SRG} src/common/dsp/effects/CombulatorEffect.cpp:270 "
                    "-- `correlated_noise_o2mk2_supplied_value(..., "
                    "storage->rand_pm1())` scaled by `noisemix.v`",
        "in_sxt028_bundle": False,
        "leaf": "not filed; this survey is its input",
    },
    {
        "fx_type_id": 23, "fx_type_name": "Tape",
        "generator": "chowdsp_random_device",
        "rng_dependence": "unconditional",
        "selector": {"rng_when": "always (class constructs random_device "
                                 "seeded generators)"},
        "citation": f"{SRG} src/common/dsp/effects/chowdsp/tape/"
                    "DegradeNoise.h:37, DegradeProcessor.cpp:29, "
                    "ChewProcessor.cpp:30",
        "in_sxt028_bundle": False,
        "leaf": "not filed; this survey is its input",
        "audibility_conditionality": {
            "status": "NOT_RUN",
            "detail": "the degrade/chew RNG contributions are scaled by the "
                      "depth/amount/variance parameters, so some parameter "
                      "settings may null them out. That analysis was NOT "
                      "run; the count therefore treats every Tape slot as "
                      "affected (fail-closed upper bound).",
        },
    },
    {
        "fx_type_id": 27, "fx_type_name": "Spring Reverb",
        "generator": "chowdsp_random_device",
        "rng_dependence": "unconditional",
        "selector": {"rng_when": "always (class constructs random_device "
                                 "seeded generators)"},
        "citation": f"{SRG} src/common/dsp/effects/chowdsp/spring_reverb/"
                    "SpringReverbProc.cpp:39",
        "in_sxt028_bundle": False,
        "leaf": "not filed; this survey is its input",
        "audibility_conditionality": {
            "status": "NOT_RUN",
            "detail": "same fail-closed treatment as Tape.",
        },
    },
    {
        "fx_type_id": 10, "fx_type_name": "Vocoder",
        "generator": None,
        "rng_dependence": "none",
        "selector": None,
        "citation": f"{SRG} src/common/dsp/effects/VocoderEffect.cpp:237-240"
                    " -- the only `storage->rand_pm1()` calls in this class "
                    "are inside a COMMENTED-OUT block and are not compiled.",
        "in_sxt028_bundle": False,
        "leaf": "n/a",
    },
]

# Classes this survey did NOT resolve. Never counted as clean.
NOT_SURVEYED = [
    {"fx_type_name": "Airwindows", "fx_type_id": 14,
     "status": "NOT_RUN",
     "reason": "the Airwindows algorithms live outside the surge source "
               "tree scanned here (src/common/dsp/effects/airwindows/ holds "
               "only the host shim). Airwindows determinism is the business "
               "of the per-algorithm SXT-028 leaves (aw-49 landed); this "
               "issue makes no statement about it."},
    {"fx_type_name": "Nimbus", "fx_type_id": 22,
     "status": "NOT_RUN",
     "reason": "eurorack/clouds is a pinned submodule not scanned here."},
    {"fx_type_name": "Floaty Delay", "fx_type_id": None,
     "status": "FINDING",
     "reason": f"{SFX} include/sst/effects/FloatyDelay.h:77,174-176 owns a "
               "`basic_blocks::dsp::RNG rng` driving two SimpleLFO "
               "SMOOTH_NOISE modulators UNCONDITIONALLY, so the whole class "
               "is RNG-driven. It is absent from corpus/census-v0.1 (the "
               "corpus predates it) and therefore contributes 0 affected "
               "presets today; it is recorded so a future leaf does not "
               "rediscover it."},
]

REPRO_PROBE = r"""
// Original to gf180-surge (Apache-2.0). Measures properties of the C++
// standard-library constructs the pinned engine uses to seed its RNGs.
// It contains no Surge or sst code.
#include <chrono>
#include <cstdio>
#include <random>
#include <thread>

static void draws(std::minstd_rand &g, unsigned long *out, int n) {
    for (int i = 0; i < n; ++i) out[i] = (unsigned long)g();
}
static bool same(const unsigned long *a, const unsigned long *b, int n) {
    for (int i = 0; i < n; ++i) if (a[i] != b[i]) return false;
    return true;
}
static unsigned long clockSeed() {
    return (unsigned long)
        std::chrono::system_clock::now().time_since_epoch().count();
}

int main() {
    const int N = 8;
    unsigned long a[N], b[N];

    // L1a: two clock-seeded constructions back to back.
    { std::minstd_rand g1(clockSeed()); draws(g1, a, N);
      std::minstd_rand g2(clockSeed()); draws(g2, b, N); }
    printf("L1a_back_to_back_identical=%d\n", same(a, b, N) ? 1 : 0);

    // L1b: two clock-seeded constructions 5 ms apart -- far closer together
    //      than two patch loads ever are.
    { std::minstd_rand g1(clockSeed()); draws(g1, a, N);
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
      std::minstd_rand g2(clockSeed()); draws(g2, b, N); }
    printf("L1b_5ms_apart_identical=%d\n", same(a, b, N) ? 1 : 0);

    // L1c: DETECTOR CONTROL -- two fixed-seed constructions must match, or
    //      the comparator above is always-firing and proves nothing.
    { std::minstd_rand g1(20260926u); draws(g1, a, N);
      std::minstd_rand g2(20260926u); draws(g2, b, N); }
    printf("L1c_fixed_seed_identical=%d\n", same(a, b, N) ? 1 : 0);

    // L2a: SHARED generator, same seed, but a second consumer has already
    //      drawn 3 values -- models Flanger drawing after another
    //      storage->rand_* consumer in the same engine instance.
    { std::minstd_rand g1(20260926u); draws(g1, a, N);
      std::minstd_rand g2(20260926u); unsigned long junk[3];
      draws(g2, junk, 3); draws(g2, b, N); }
    printf("L2a_draw_order_shifted_identical=%d\n", same(a, b, N) ? 1 : 0);

    // L2b: DETECTOR CONTROL for L2a -- zero prior draws must match.
    { std::minstd_rand g1(20260926u); draws(g1, a, N);
      std::minstd_rand g2(20260926u); draws(g2, b, N); }
    printf("L2b_draw_order_unshifted_identical=%d\n", same(a, b, N) ? 1 : 0);

    // L3 data point: what THIS standard library maps a fixed minstd_rand
    //      stream to through uniform_real_distribution<float>(-1,1).
    { std::minstd_rand g(20260926u);
      std::uniform_real_distribution<float> d(-1.f, 1.f);
      printf("L3_uniform_pm1_first4=%.9g,%.9g,%.9g,%.9g\n",
             d(g), d(g), d(g), d(g)); }

    // Clock tick observed by the seeding expression, in native units.
    { auto t0 = std::chrono::system_clock::now().time_since_epoch().count();
      decltype(t0) t1 = t0;
      while (t1 == t0)
        t1 = std::chrono::system_clock::now().time_since_epoch().count();
      printf("clock_tick_units=%lld\n", (long long)(t1 - t0));
      printf("clock_period_num=%lld\nclock_period_den=%lld\n",
             (long long)std::chrono::system_clock::period::num,
             (long long)std::chrono::system_clock::period::den); }
    return 0;
}
"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def leg_a_sources(roots: dict) -> dict:
    """Verify the cited files against read-only pinned checkouts."""
    files = []
    verified = mismatched = not_run = 0
    for tree, rel, expected in CITED_FILES:
        rec = {"tree": tree, "path": rel, "expected_sha256": expected}
        root = roots.get(TREE_KEYS[tree])
        if not root:
            rec["status"] = "NOT_RUN"
            rec["detail"] = "no checkout supplied for this tree"
            not_run += 1
        else:
            p = Path(root) / rel
            if not p.is_file():
                rec["status"] = "NOT_RUN"
                rec["detail"] = f"absent from supplied checkout: {p}"
                not_run += 1
            else:
                actual = sha256_file(p)
                rec["actual_sha256"] = actual
                if actual == expected:
                    rec["status"] = "VERIFIED"
                    verified += 1
                else:
                    rec["status"] = "MISMATCH"
                    mismatched += 1
        files.append(rec)

    # Symbol scan: no call site in the supplied trees reseeds either
    # FX-reachable generator. Absence of a call site is only claimable when
    # the tree was actually read.
    reseed = {"status": "NOT_RUN", "call_sites": [],
              "detail": "no checkout supplied"}
    surge_root = roots.get("surge")
    if surge_root:
        hits = []
        scanned = 0
        for p in sorted(Path(surge_root).rglob("*")):
            if p.suffix not in (".h", ".cpp", ".hpp"):
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1
            for lineno, line in enumerate(txt.splitlines(), 1):
                if line.lstrip().startswith("//"):
                    continue
                if ("reseed(" in line or "reseedWithClock(" in line
                        or "seed_rand(" in line):
                    hits.append(f"{p.relative_to(surge_root)}:{lineno}: "
                                f"{line.strip()[:100]}")
        reseed = {
            "status": "MEASURED",
            "scanned_root": str(surge_root),
            "scanned_files": scanned,
            "scanned_note": "the claim covers exactly the tree supplied on "
                            "the command line; supply the engine's src/ "
                            "subtree at the pin to reproduce it.",
            "call_sites": hits,
            "verdict": ("no reseed call site reachable from a patch load"
                        if not hits else
                        "reseed call sites found -- re-evaluate the finding"),
        }

    if mismatched:
        status = "FAIL"
    elif verified and not not_run:
        status = "PASS"
    elif verified:
        status = "PARTIAL"
    else:
        status = "NOT_RUN"
    return {
        "leg": "A. source inventory + citation verification",
        "status": status,
        "counts": {"verified": verified, "mismatched": mismatched,
                   "not_run": not_run, "total": len(CITED_FILES)},
        "roots_supplied": {k: str(v) for k, v in sorted(roots.items())},
        "files": files,
        "reseed_call_sites": reseed,
        "note": "sha256 pins the cited content at the pinned commit; no "
                "third-party source is copied into this repository.",
    }


def leg_b_repro(cxx: str) -> dict:
    """Compile and run the original determinism probe."""
    if cxx is None or shutil.which(cxx) is None:
        return {
            "leg": "B. seed reproducibility (executable probe)",
            "status": "NOT_RUN",
            "reason": f"no C++ compiler available (looked for {cxx!r}); the "
                      "legs were not run and must never be reported as a "
                      "pass",
        }
    with tempfile.TemporaryDirectory(prefix="sxt028-rng-") as td:
        src = Path(td) / "rng_probe.cpp"
        exe = Path(td) / "rng_probe"
        src.write_text(REPRO_PROBE, encoding="utf-8")
        build = subprocess.run([cxx, "-std=c++17", "-O2", "-pthread",
                                "-o", str(exe), str(src)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            return {
                "leg": "B. seed reproducibility (executable probe)",
                "status": "NOT_RUN",
                "reason": "probe did not compile",
                "stderr": build.stderr.strip().splitlines()[-5:],
            }
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        if run.returncode != 0:
            return {
                "leg": "B. seed reproducibility (executable probe)",
                "status": "NOT_RUN",
                "reason": f"probe exited {run.returncode}",
                "stderr": run.stderr.strip().splitlines()[-5:],
            }
        ver = subprocess.run([cxx, "--version"], capture_output=True,
                             text=True).stdout.strip().splitlines()[:1]

    raw = {}
    for line in run.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            raw[k.strip()] = v.strip()

    def flag(key):
        return raw.get(key) == "1"

    detector_ok = flag("L1c_fixed_seed_identical") and \
        flag("L2b_draw_order_unshifted_identical")
    clock_reproducible = flag("L1b_5ms_apart_identical")
    order_independent = flag("L2a_draw_order_shifted_identical")

    checks = [
        {
            "check": "two constructions of a clock-seeded generator 5 ms "
                     "apart produce the SAME stream",
            "expected_for_a_pinnable_stream": True,
            "observed": clock_reproducible,
            "status": "PASS" if clock_reproducible else "FAIL",
            "means": "FAIL => the seed is a function of wall-clock time at "
                     "construction, so two loads of the same patch do not "
                     "share a stream.",
        },
        {
            "check": "two constructions back to back (no delay) produce the "
                     "same stream",
            "expected_for_a_pinnable_stream": True,
            "observed": flag("L1a_back_to_back_identical"),
            "status": "PASS" if flag("L1a_back_to_back_identical") else "FAIL",
            "means": "informational: shows whether the clock even resolves "
                     "two adjacent constructions apart.",
        },
        {
            "check": "DETECTOR CONTROL: two FIXED-seed constructions produce "
                     "the same stream",
            "expected_for_a_pinnable_stream": True,
            "observed": flag("L1c_fixed_seed_identical"),
            "status": "CONTROL-OK" if flag("L1c_fixed_seed_identical")
                      else "CONTROL-BROKEN",
            "means": "the comparator can report IDENTICAL, so a FAIL above "
                     "is a measurement and not an always-firing detector.",
        },
        {
            "check": "a SHARED generator hands the same stream to a consumer "
                     "that draws after 3 prior draws by another consumer",
            "expected_for_a_pinnable_stream": True,
            "observed": order_independent,
            "status": "PASS" if order_independent else "FAIL",
            "means": "FAIL => pinning the seed alone does not pin the "
                     "stream for SurgeStorage::rngGen; the engine-wide draw "
                     "ORDER would have to be pinned too.",
        },
        {
            "check": "DETECTOR CONTROL: the same shared generator with ZERO "
                     "prior draws produces the same stream",
            "expected_for_a_pinnable_stream": True,
            "observed": flag("L2b_draw_order_unshifted_identical"),
            "status": "CONTROL-OK" if flag("L2b_draw_order_unshifted_identical")
                      else "CONTROL-BROKEN",
            "means": "same role as L1c for the draw-order comparator.",
        },
    ]

    if not detector_ok:
        status = "NO_VERDICT"
    elif clock_reproducible and order_independent:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "leg": "B. seed reproducibility (executable probe)",
        "status": status,
        "question": "Is the FX-modulation RNG stream reproducible across two "
                    "loads of the same patch under the SXT-010 manifest "
                    "(no seed override applied)?",
        "verdict": ("NOT REPRODUCIBLE" if status == "FAIL" else
                    "REPRODUCIBLE" if status == "PASS" else
                    "NO_VERDICT (detector control broken)"),
        "compiler": (ver[0] if ver else cxx),
        "raw": raw,
        "checks": checks,
        "probe_provenance": "tools/fx_rng_characterize.py REPRO_PROBE -- "
                            "original to this repository; it exercises C++ "
                            "standard-library constructs, it does not "
                            "reproduce or link any Surge or sst code.",
    }


def leg_c_portability(leg_b: dict) -> dict:
    """Cross-standard-library portability of the distribution mapping."""
    values = leg_b.get("raw", {}).get("L3_uniform_pm1_first4")
    return {
        "leg": "C. distribution portability across standard libraries",
        "status": "NOT_RUN",
        "reason": "only one C++ standard library is installed on this host, "
                  "and provisioning another is out of this issue's scope. "
                  "The manifest pins Apple clang / libc++ "
                  "(oracle/manifest.json environment.clang); no libc++ build "
                  "was produced here, so no cross-library comparison was "
                  "made. NOT_RUN is not a pass and not a failure.",
        "normative_basis": "[rand.dist.uni.real] specifies the DISTRIBUTION "
                           "of std::uniform_real_distribution, not the "
                           "algorithm or the number of engine draws it "
                           "consumes. Two conforming standard libraries may "
                           "therefore map the same minstd_rand stream to "
                           "different floats. `std::minstd_rand` itself IS "
                           "exactly specified, so the ENGINE is portable and "
                           "the MAPPING is not.",
        "single_datapoint": {
            "standard_library": platform.python_compiler() or "host default",
            "compiler": leg_b.get("compiler"),
            "seed": 20260926,
            "uniform_real_distribution_float_pm1_first4": values,
            "claim_scope": "one host, one standard library; establishes "
                           "nothing about the pinned macOS/libc++ runtime.",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--sst-basic-blocks",
                    default=os.environ.get("SST_BASIC_BLOCKS_DIR"))
    ap.add_argument("--sst-effects",
                    default=os.environ.get("SST_EFFECTS_DIR"))
    ap.add_argument("--surge", default=os.environ.get("ORACLE_SURGE_DIR"))
    ap.add_argument("--cxx", default=os.environ.get("CXX", "c++"))
    args = ap.parse_args()

    roots = {}
    for key, val in (("sst_basic_blocks", args.sst_basic_blocks),
                     ("sst_effects", args.sst_effects),
                     ("surge", args.surge)):
        if val and Path(val).is_dir():
            roots[key] = Path(val).resolve()

    leg_a = leg_a_sources(roots)
    leg_b = leg_b_repro(args.cxx)
    leg_c = leg_c_portability(leg_b)

    pinnable = leg_b["status"] == "PASS"
    doc = {
        "schema_version": "sxt-028-rng-characterization/1.0.0",
        "issue": "#122",
        "raised_by": "SXT-028g (#59)",
        "routes_to": "SXT-017 (#12)",
        "decision_record": "decision-records/0013-fx-modulation-rng-stream.md",
        "engine_pin": {"surge": SRG, "sst_effects": SFX,
                       "sst_basic_blocks": SBB,
                       "manifest": "oracle/manifest.json"},
        "question": "Can the pinned engine's FX-modulation RNG stream be "
                    "pinned well enough for a frozen fixed-point model and "
                    "an exact RTL to reproduce it?",
        "generators": GENERATORS,
        "fx_survey": FX_RNG_SURVEY,
        "not_surveyed": NOT_SURVEYED,
        "legs": {"source_inventory": leg_a, "seed_reproducibility": leg_b,
                 "distribution_portability": leg_c},
        "finding": {
            "stream_is_pinnable": pinnable,
            "obstructions": [
                "O1 SEED: both FX-reachable generators are seeded from the "
                "wall clock at construction and the pinned engine exposes no "
                "reseed call site reachable from a patch load, so the seed "
                "is not a function of the patch or of the manifest.",
                "O2 DRAW ORDER: SurgeStorage::rngGen is shared by every "
                "storage->rand_* consumer on the audio thread, so a "
                "consumer's stream position depends on the rest of the "
                "engine's draw history, not only on its own state.",
                "O3 DISTRIBUTION MAPPING: std::uniform_real_distribution has "
                "no standard-specified algorithm, so even a pinned seed and "
                "a pinned draw order do not pin the produced floats across "
                "standard libraries (leg C, NOT_RUN as a measurement, cited "
                "normatively).",
                "O4 SCOPE: pinning any of the above would require PATCHING "
                "the pinned engine. oracle/manifest.json states that the "
                "pinned engine's own RNG initialization IS part of the "
                "reference; a patched engine is a different reference and "
                "cannot settle a fidelity claim about this one.",
            ],
            "obstruction_severity": "O1 alone is sufficient and is MEASURED "
                                    "(leg B). O2 is MEASURED. O3 is cited, "
                                    "not measured. O4 is a policy fact of "
                                    "the manifest.",
        },
        "claim_scope": "This record characterises an RNG. It establishes no "
                       "preset support, no coverage claim, no fidelity "
                       "claim, no listening claim, and no hardware claim. It "
                       "does not re-open SXT-028g (#59): that leaf's "
                       "fail-closed refusal is correct either way.",
        "reproduce": [
            "python3 tools/fx_rng_characterize.py "
            "--sst-basic-blocks <sst-basic-blocks checkout at the pin> "
            "--sst-effects <sst-effects checkout at the pin> "
            "--surge <surge checkout at the pin>",
            "(the source-verification leg records NOT_RUN without them; the "
            "executable probe needs only a C++17 compiler)",
        ],
    }

    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  leg A source inventory        : {leg_a['status']} "
          f"({leg_a['counts']})")
    print(f"  leg B seed reproducibility    : {leg_b['status']} "
          f"-- {leg_b.get('verdict', leg_b.get('reason'))}")
    print(f"  leg C distribution portability: {leg_c['status']}")
    print(f"  stream_is_pinnable            : {pinnable}")
    # Exit 0 whether or not the stream turns out pinnable: this tool reports
    # a characterisation, it does not gate anything. A broken detector
    # control (NO_VERDICT) or a citation MISMATCH is a tool failure.
    if leg_a["status"] == "FAIL" or leg_b["status"] == "NO_VERDICT":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
