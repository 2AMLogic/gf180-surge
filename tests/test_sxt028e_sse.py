"""SXT-028e-sse Distortion SSE quad-waveshaper leaf tests (pytest).

Covers: the frozen constant inventory and word-length contract, the
generator/ROM consistency guard, the FuzzTable re-derivation claim,
fail-closed refusals in BOTH directions (this leaf refuses FX models 0..2
exactly as SXT-028e refuses 3..7), the proof that the shared Distortion
chain is REUSED unchanged, per-instance `QuadWaveshaperState` independence,
the DC-offset probe, the `/64` drive interpolation and the `wst_digital`
`skipDriveNorm` special case, the ringout tail contract, the
zero-external-memory accounting, and the integrity of the committed evidence
records.

Oracle-dependent legs are not RE-RUN here (no engine is linked into the test
process); they are checked against their committed records. Since #136 the
committed `model/effects/fx_inputs/type-distortion-sse-*.json` records are
`extraction_status = COMPLETE` from the pinned loader's normalized state, and
this suite asserts that plus the live fail-closed control that a record with
any oracle-only field still `null` is REFUSED by `DistortionSSEParams`. The
reference-leg artifacts (`reports/SXT-028e-sse/artifacts/compare-*.json`,
`reference-leg.json`, `settle-boundary.json`) are checked for internal
consistency and for their negative controls having FAILED as required; a
missing iverilog makes the RTL leg NOT_RUN (skipped), never a pass.
"""
import json
import math
import os
import random
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

import quad_shapers as qs  # noqa: E402
import sse_tables as st  # noqa: E402
import distortion_model as dm  # noqa: E402
from distortion_sse_model import (  # noqa: E402
    DistortionSSEModel, DistortionSSEParams, BLOCK, OS_BLOCK, DISTORTION_OS,
    RINGOUT_TIME, RINGOUT_END, SLOWRATE, DRIVE_INTERP_DIVISOR,
    model_revision, table_branch_shaper,
)
from model.effects.qmath import FRAC  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028e-sse")
RTLDIR = os.path.join(REPO, "rtl", "effects", "type-distortion-sse")

SYNTH = dict(preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
             preeq_highcut_f=70.0, drive_f=6.0, feedback_f=0.635445,
             posteq_gain_f=-4.5, posteq_freq_f=24.0, posteq_bw_f=1.1,
             posteq_highcut_f=30.535736, gain_f=0.0, model_i=7,
             preeq_highcut_deactivated=False,
             posteq_highcut_deactivated=False,
             preeq_gain_extend=False, posteq_gain_extend=False,
             drive_extend=False)


def make_model(name="t", **kw):
    p = dict(SYNTH)
    p.update(kw)
    m = DistortionSSEModel(DistortionSSEParams(p), name)
    m.initialize()
    return m


def drive_blocks(m, n, seed=7, amp=1 << 20, ringout=0):
    rs = random.Random(seed)
    out = []
    for _ in range(n):
        il = [rs.randint(-amp, amp) for _ in range(BLOCK)]
        ir = [rs.randint(-amp, amp) for _ in range(BLOCK)]
        ol, orr = m.process_block(il, ir, ringout=ringout)
        out += ol + orr
    return out


# ---------------------------------------------------------------- contract
def test_frozen_constants_and_layout():
    assert DISTORTION_OS == 4 and OS_BLOCK == BLOCK * 4   # dist_OS_bits = 2
    assert SLOWRATE == 8                                   # Effect.h:138
    assert RINGOUT_TIME == 1600 and RINGOUT_END == 320     # DistortionEffect.h
    assert FRAC["Q10.21"] == 21 and FRAC["Q13.18"] == 18
    assert FRAC["Q24.43"] == 43 and FRAC["Q2.29"] == 29
    assert (qs.FA, qs.FG, qs.FC, qs.FS, qs.FW) == (21, 18, 43, 23, 29)
    assert qs.QuadWaveshaperState.N_REGISTERS == 4   # n_waveshaper_registers
    assert qs.QuadWaveshaperState.LANES == 2         # DD-1
    # the /64 quirk: BLOCK_SIZE * dist_OS_bits, NOT BLOCK_SIZE << dist_OS_bits
    assert DRIVE_INTERP_DIVISOR == 64
    assert DRIVE_INTERP_DIVISOR != BLOCK * DISTORTION_OS


def test_fx_model_map_matches_pinned_filter_configuration():
    # src/common/FilterConfiguration.h:235 -- n_fxws = 8
    assert st.FXWS_NAMES == ["wst_soft", "wst_hard", "wst_asym", "wst_sine",
                             "wst_digital", "wst_ojd", "wst_fwrectify",
                             "wst_fuzzsoft"]
    assert st.SSE_MODELS == (3, 4, 5, 6, 7)
    assert st.TABLE_BRANCH_MODELS == (0, 1, 2)
    # the two leaves partition the eight indices with no overlap and no gap
    import ws_tables as wt
    assert set(wt.FROZEN_MODELS) | set(st.SSE_MODELS) == set(range(8))
    assert set(wt.FROZEN_MODELS) & set(st.SSE_MODELS) == set()


def test_quoted_designed_scalars_are_as_written_in_the_pinned_source():
    """DR-0014 clause (a). The float32 spelling is load-bearing."""
    import struct

    def f32(x):
        return struct.unpack("f", struct.pack("f", x))[0]
    assert qs.OJD_M17_C == qs.fq(f32(-1.7), qs.FC)
    assert qs.OJD_P11_C == qs.fq(f32(1.1), qs.FC)
    assert qs.OJD_M03_C == qs.fq(f32(-0.3), qs.FC)
    assert qs.OJD_P09_C == qs.fq(f32(0.9), qs.FC)
    # 1.f / (4 * (1 - 0.9f)) is 2.4999995f, NOT 2.5 -- the float32 spelling
    # of `1 - 0.9f` is 0.100000024f.
    assert abs(qs.OJD_DENHIGH_C / float(1 << qs.FC) - 2.4999995) < 1e-6
    assert qs.OJD_DENHIGH_C != qs.fq(2.5, qs.FC)
    assert qs.TANH_9_C == 9 << qs.FC and qs.TANH_27_C == 27 << qs.FC
    assert qs.ADAA_TOL_C == qs.fq(f32(0.0001), qs.FC)
    assert qs.DCBLOCK_FAC_C == qs.fq(f32(0.9999), qs.FC)
    assert len(qs.SHAPER_INIT_WORDS) == 11 and qs.SHAPER_INIT_BASE == 16


def test_tables_are_rederived_not_quoted():
    import math
    sine = st.TABLES["sine"]
    assert len(sine) == st.SINE_SIZE == 1024
    for i in (0, 256, 512, 600, 1023):
        want = math.sin((float(i) - 512.0) * math.pi / 512.0)
        assert abs(sine[i] / (1 << 29) - want) < 1e-6
    fuzz = st.TABLES["fuzz1"]
    assert len(fuzz) == st.FUZZ_SIZE == 1025          # LUTBase stores N + 1
    # FuzzTable<1>(x) = x*0.9 + U(-0.1, 0.1): bounded, and NOT a smooth curve
    assert all(abs(v / (1 << 29)) <= 1.05 for v in fuzz)
    jumps = [abs(fuzz[i + 1] - fuzz[i]) / (1 << 29) for i in range(1024)]
    assert max(jumps) > 0.1, "the fuzz row must be pseudo-random, not smooth"


def test_portable_minstd_rand_is_the_pinned_engine():
    g = st.PortableMinstdRand(2112)
    assert (st.PortableMinstdRand.A, st.PortableMinstdRand.M) == (48271,
                                                                  2147483647)
    x = 2112
    for _ in range(5):
        x = (48271 * x) % 2147483647
        assert g() == x


def test_ws_rom_matches_generator():
    """The committed RTL ROM must be a build product of sse_tables.py.

    If it ever drifts it would become an independent copy of engine data,
    which DR-0014 clause 2 forbids.
    """
    rom = os.path.join(RTLDIR, "ws_sse_q29.hex")
    with open(rom) as f:
        words = [int(line.strip(), 16) for line in f if line.strip()]
    expect = [w & 0xFFFFFFFF for w in st.rom_words()]
    assert words == expect
    assert len(words) == st.ROM_WORDS == st.SINE_SIZE + st.FUZZ_SIZE


def test_fuzz_table_rederivation_record():
    """DR-0014 clause 3: the re-derivation claim is discharged BY BUILD.

    A MISMATCH would mean the table is quoted data, not a re-derivation --
    a licensing-relevant claim, so this must never silently degrade.
    """
    path = os.path.join(SXT, "artifacts", "fuzz-table-rederivation.json")
    rec = json.load(open(path))
    if rec["status"] in ("NOT_RUN", "BLOCKED"):
        pytest.skip(f"{rec['status']}: {rec.get('reason')}")
    assert rec["status"] == "MATCH", rec
    assert rec["mismatches"] == 0
    assert rec["entries"] == st.FUZZ_SIZE == rec["cpp_entries"]
    assert rec["table_digest"] == st.table_digest(), \
        "fuzz-table-rederivation.json is STALE against the generator"
    assert rec["probe_source_committed"] is False
    # The build must have gone against the PINNED headers, at the pinned
    # SHAs -- a build against some other revision would validate nothing.
    assert rec["probe_kind"] == "external-header-build"
    man = json.load(open(os.path.join(REPO, "oracle", "manifest.json")))
    pins = {s["path"]: s["commit"] for s in man["submodules"]}
    ext = rec["external_headers"]
    for key, sub in (("sst-waveshapers", "libs/sst/sst-waveshapers"),
                     ("sst-basic-blocks", "libs/sst/sst-basic-blocks")):
        assert ext[key]["pinned_commit"] == pins[sub]
        assert ext[key]["commit"] == pins[sub], \
            f"{key} build was not against the pinned SHA"
        assert not ext[key]["checkout"].startswith(REPO + os.sep), \
            "the pinned GPL-3.0-or-later checkout must stay outside this repo"


# The engine expressions this repository must NOT carry a copy of. The
# FuzzTable re-derivation is validated by INCLUDING the pinned header from an
# external checkout, never by transcribing it here (DR-0014 clauses 3 and 5,
# EVIDENCE.md §13). This guard is live: re-introducing the transcription --
# the exact defect that blocked PR #137 -- fails this test.
FORBIDDEN_ENGINE_SOURCE_TOKENS = (
    "linear_congruential_engine",   # the pinned LCG typedef
    "uniform_real_distribution",    # the pinned draw
    "48271", "2147483647", "2112",  # the pinned LCG/seed constants
    "dx - 1.0", "1 - range",        # the LUTBase / FuzzTable expressions
)


def test_rederivation_checker_carries_no_engine_source_text():
    """No GPL-3.0-or-later source text is committed in the checker."""
    tool = os.path.join(REPO, "tools", "check_fuzz_table_rederivation.py")
    src = open(tool).read()
    for tok in FORBIDDEN_ENGINE_SOURCE_TOKENS:
        assert tok not in src, \
            (f"{tool} contains engine source text {tok!r}: the pinned "
             "GPL-3.0-or-later expressions must be INCLUDED from an external "
             "checkout, not transcribed into this Apache-2.0 repository")
    # ... and specifically not inside the C++ the tool compiles.
    import importlib.util
    spec = importlib.util.spec_from_file_location("_fuzzchk", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    driver = mod.DRIVER_CPP
    assert "#include <sst/waveshapers.h>" in driver, \
        "the driver must build against the pinned header, not a copy of it"
    for tok in FORBIDDEN_ENGINE_SOURCE_TOKENS:
        assert tok not in driver


def _load_rederivation_checker():
    import importlib.util
    tool = os.path.join(REPO, "tools", "check_fuzz_table_rederivation.py")
    spec = importlib.util.spec_from_file_location("_fuzzchk_det", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeRun:
    """Stands in for subprocess.run: answers the macro dump according to the
    -stdlib= flag it is GIVEN, so a detection that drops the driver's flags
    would report the wrong library and fail the test."""

    def __init__(self, returncode=0, stderr=""):
        self.calls, self.returncode, self.stderr = [], returncode, stderr

    def __call__(self, cmd, capture_output=True, text=True):
        self.calls.append(list(cmd))
        if "-stdlib=libstdc++" in cmd:
            out = "#define __GLIBCXX__ 20260101\n#define __cplusplus 202002L\n"
        elif "-stdlib=libc++" in cmd:
            out = "#define _LIBCPP_VERSION 220106\n#define __cplusplus 202002L\n"
        else:
            out = "#define __cplusplus 202002L\n"
        return subprocess.CompletedProcess(cmd, self.returncode, out,
                                           self.stderr)


def test_stdlib_detection_uses_the_driver_flags_and_includes():
    """Review finding (#383): the recorded standard library must describe
    the compilation actually performed, so the macro probe carries every
    driver flag (incl. --cxxflag values) and include directory."""
    mod = _load_rederivation_checker()
    flags = ["-O2", "-std=c++20", "-DX=1", "-stdlib=libc++",
             "-ffp-contract=off"]
    incs = ["/ext/a/include", "/ext/b"]
    cmd = mod.stdlib_detection_cmd("clang++", flags, incs)
    assert cmd[0] == "clang++"
    for f in flags:
        assert f in cmd, f
    for d in incs:
        assert f"-I{d}" in cmd, d
    assert {"-dM", "-E"} <= set(cmd)
    # The recorded library follows the flags passed, in both directions.
    for flag, want in (("-stdlib=libc++", "libc++ (_LIBCPP_VERSION 220106)"),
                       ("-stdlib=libstdc++",
                        "libstdc++ (__GLIBCXX__ 20260101)")):
        fake = _FakeRun()
        lib, det = mod.detect_stdlib("clang++", ["-O2", flag], incs, run=fake)
        assert lib == want
        assert len(fake.calls) == 1 and flag in fake.calls[0]
        assert det["returncode"] == 0 and flag in det["command"]


def test_stdlib_detection_failures_are_recorded_unknown_never_guessed():
    mod = _load_rederivation_checker()
    lib, det = mod.detect_stdlib(
        "g++", ["-stdlib=bogus"], [],
        run=_FakeRun(returncode=1, stderr="error: invalid library name"))
    assert lib.startswith("UNKNOWN") and "exit 1" in lib
    assert det["returncode"] == 1 and "invalid library" in det["error"]
    # A compile that defines neither library macro is UNKNOWN too ...
    lib, det = mod.detect_stdlib("g++", ["-O2"], [], run=_FakeRun())
    assert lib.startswith("UNKNOWN") and "neither" in lib
    # ... and so is a compiler that cannot be executed at all.

    def boom(cmd, **kw):
        raise FileNotFoundError(2, "No such file", cmd[0])
    lib, det = mod.detect_stdlib("nope++", [], [], run=boom)
    assert lib.startswith("UNKNOWN") and det["returncode"] is None
    # The name of the compiler is never used as a fallback guess.
    lib, _ = mod.detect_stdlib("g++", [], [], run=_FakeRun())
    assert "libstdc++" not in lib


def test_environment_scope_separates_pinned_host_from_alternate_hosts():
    """A run off the manifest's frozen environment is an alternate-environment
    observation and leaves the pinned-host leg NOT_RUN (review of #383)."""
    mod = _load_rederivation_checker()
    man = json.load(open(os.path.join(REPO, "oracle", "manifest.json")))
    pin_clang = man["environment"]["clang"]
    clang_id = pin_clang.split("(", 1)[1].split(")", 1)[0]
    pin_os_ver = man["environment"]["os"].split()[1]
    pinned_ver = f"Apple clang version 21.0.0 ({clang_id})\nTarget: x\n"
    env = mod.environment_scope(pinned_ver, mac_ver=pin_os_ver)
    assert env["os_matches_pin"] and env["clang_matches_pin"]
    assert env["pinned_host_acceptance"] != "NOT_RUN"
    for ver, osv in (("Apple clang version 21.0.0 (clang-2100.3.34.2)",
                      "27.0.1"),
                     ("Apple clang version 21.0.0 (clang-2100.3.34.2)",
                      pin_os_ver),
                     (pinned_ver, "27.0.1"),
                     ("g++ (GCC) 14.2.0", "")):
        env = mod.environment_scope(ver, mac_ver=osv)
        assert env["pinned_host_acceptance"] == "NOT_RUN", (ver, osv)
        assert env["scope"].startswith("ALTERNATE-ENVIRONMENT OBSERVATION")


LIBCXX_TRANSCRIPTS = ("fuzz-table-rederivation-libcxx-arm64.json",
                      "fuzz-table-rederivation-libcxx-arm64-fpcontract-off.json")


@pytest.mark.parametrize("name", LIBCXX_TRANSCRIPTS)
def test_libcxx_transcripts_are_scoped_to_the_environment_they_ran_in(name):
    """The #135 libc++ transcripts must state, against the CURRENT manifest
    pin, whether they ran in the frozen environment -- and must not claim the
    pinned-host leg unless both OS and clang matched."""
    rec = json.load(open(os.path.join(SXT, "artifacts", name)))
    man = json.load(open(os.path.join(REPO, "oracle", "manifest.json")))
    env = rec["environment"]
    assert env["pinned_environment"] == {
        "os": man["environment"]["os"], "clang": man["environment"]["clang"]}, \
        f"{name} is STALE against oracle/manifest.json environment"
    pinned = env["os_matches_pin"] and env["clang_matches_pin"]
    if not pinned:
        assert env["pinned_host_acceptance"] == "NOT_RUN"
        assert env["scope"].startswith("ALTERNATE-ENVIRONMENT OBSERVATION")
    # The recorded stdlib came from a probe that used the driver's flags.
    det = rec["stdlib_detection"]
    assert det["returncode"] == 0
    for flag in rec["compile_flags"].split():
        assert flag in det["command"].split(), flag
    assert rec["stdlib_validated"].startswith("libc++ ")
    assert rec["entries"] == st.FUZZ_SIZE == rec["cpp_entries"]
    assert rec["table_digest"] == st.table_digest(), \
        f"{name} is STALE against the generator"


def test_rederivation_checker_reports_not_run_without_the_pinned_headers(
        tmp_path):
    """Absent the external checkout the claim is NOT_RUN, never a pass."""
    env = dict(os.environ)
    env["SXT_ORACLE_HEADERS_DIR"] = str(tmp_path / "absent")
    env.pop("ORACLE_SURGE_DIR", None)
    out = tmp_path / "rec.json"
    r = subprocess.run(
        [sys.executable,
         os.path.join(REPO, "tools", "check_fuzz_table_rederivation.py"),
         "--out", str(out)],
        capture_output=True, text=True, env=env)
    if r.returncode == 77 and "no C++ toolchain" in r.stdout:
        pytest.skip("no C++ toolchain on this host")
    assert r.returncode == 77, r.stdout + r.stderr
    rec = json.load(open(out))
    assert rec["status"] == "NOT_RUN"
    assert rec["mismatches"] is None


# ------------------------------------------------------------- fail-closed
def test_table_branch_models_refused_here():
    """This leaf refuses 0..2 exactly as SXT-028e (#57) refuses 3..7."""
    for mi in (0, 1, 2):
        with pytest.raises(RuntimeError) as e:
            DistortionSSEParams(dict(SYNTH, model_i=mi))
        assert "table branch" in str(e.value)
        with pytest.raises(RuntimeError):
            st.build_table(mi)
        with pytest.raises(RuntimeError):
            qs.get_quad_waveshaper(mi)
    # and the complementary refusal still holds on the #57 side
    for mi in (3, 4, 5, 6, 7):
        with pytest.raises(RuntimeError):
            dm.DistortionParams(dict(SYNTH, model_i=mi))


def test_all_sse_models_are_accepted_and_dispatch():
    for mi in st.SSE_MODELS:
        p = DistortionSSEParams(dict(SYNTH, model_i=mi))
        assert p.model_i == mi
        assert qs.get_quad_waveshaper(mi) is qs.SHAPERS[mi]
        assert st.SSE_SHAPER_OF[mi]


def test_out_of_range_model_refused():
    for mi in (-1, 8, 42):
        with pytest.raises(RuntimeError):
            DistortionSSEParams(dict(SYNTH, model_i=mi))


def test_closed_form_shapers_have_no_table():
    for mi in (4, 5, 6):
        with pytest.raises(RuntimeError) as e:
            st.build_table(mi)
        assert "closed form" in str(e.value)


def test_unresolved_control_plane_inputs_refused():
    for k in ("preeq_highcut_deactivated", "drive_extend", "model_i"):
        bad = dict(SYNTH)
        bad[k] = None
        with pytest.raises(RuntimeError) as e:
            DistortionSSEParams(bad)
        assert "fail-closed" in str(e.value)


ORACLE_ONLY_FIELDS = ("preeq_highcut_deactivated", "posteq_highcut_deactivated",
                      "preeq_gain_extend", "posteq_gain_extend", "drive_extend")


def test_committed_fx_inputs_are_complete_from_the_pinned_loader():
    """#136: the oracle extraction ran, so the records are COMPLETE.

    What is asserted is the *shape and provenance* of the record, never that
    any render agreed with anything: a COMPLETE record permits a model run,
    it is not a fidelity result.
    """
    found = 0
    d = os.path.join(REPO, "model", "effects", "fx_inputs")
    for name in sorted(os.listdir(d)):
        if not name.startswith("type-distortion-sse-"):
            continue
        found += 1
        rec = json.load(open(os.path.join(d, name)))
        assert rec["leaf"] == "SXT-028e-sse"
        assert rec["extraction_status"] == "COMPLETE"
        assert rec["extraction_mode"] == "oracle"
        assert rec["unresolved_fields"] == []
        assert rec["census_blob_sha1"]
        assert "58914e59c608ed4384ba6002e44c3465c58b2e71" in rec["source"]
        assert rec["oracle_extraction"]["flags_source"].startswith(
            "savePatch round-trip")
        for slot in rec["distortion_slots"]:
            assert slot["fx_model_index"] in st.SSE_MODELS
            for k in ORACLE_ONLY_FIELDS:
                assert isinstance(slot["params"][k], bool)
            # a COMPLETE record is runnable; an incomplete one is not
            DistortionSSEParams(slot["params"])
            for k in ORACLE_ONLY_FIELDS:
                blanked = dict(slot["params"])
                blanked[k] = None
                with pytest.raises(RuntimeError):
                    DistortionSSEParams(blanked)
    assert found == 3, "one carrier each for FX models 3, 4 and 5"


def test_census_blob_shas_match_manifest():
    man = json.load(open(os.path.join(REPO, "corpus", "census-v0.1",
                                      "corpus-manifest.json")))
    by_path = {e["path"]: e["git_blob_sha1"] for e in man["entries"]}
    d = os.path.join(REPO, "model", "effects", "fx_inputs")
    for name in sorted(os.listdir(d)):
        if not name.startswith("type-distortion-sse-"):
            continue
        rec = json.load(open(os.path.join(d, name)))
        assert by_path[rec["preset_path"]] == rec["census_blob_sha1"]


def test_corpus_reach_is_inventory_not_a_support_claim():
    """Re-derive the histogram the issue quotes, from the committed export.

    Inventory only. This asserts the SCOPE SPLIT between the two leaves is
    what the record says it is; it establishes no support claim.
    """
    import collections
    hist = collections.Counter()
    path = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
    with open(path) as f:
        for line in f:
            d = json.loads(line)
            if d.get("st") != "normalized":
                continue
            for fx in d["g"]["fx"]:
                if fx.get("on") and fx.get("tn") == "Distortion":
                    hist[int(fx["p"][11])] += 1
    total = sum(hist.values())
    in_scope = sum(hist[m] for m in st.SSE_MODELS)
    assert total == 475
    assert in_scope == 28
    assert hist[7] == 0, "wst_fuzzsoft has zero corpus reach (recorded)"


# --------------------------------------------- the shared chain is REUSED
def test_shared_chain_is_bit_identical_to_sxt028e():
    """The #57 chain must be REUSED, not re-derived.

    Running this leaf's block schedule with the #57 table shaper substituted
    for the quad shaper must reproduce `DistortionModel` bit for bit -- every
    output sample AND every checkpoint field the two models share. If a
    future edit disturbs the shared chain (an extra rounding step, a
    reordered stage, a different lipol update), this test fails.
    """
    base = dict(SYNTH)
    ref_p = dict(base, model_i=0)
    ref = dm.DistortionModel(dm.DistortionParams(ref_p), "ref")
    ref.initialize()
    probe = DistortionSSEModel(DistortionSSEParams(dict(base, model_i=3)),
                               "ref", chain_probe_shaper=table_branch_shaper(0))
    probe.initialize()
    assert probe.chain_probe_mode is True
    rs = random.Random(3)
    for b in range(24):
        il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        a = ref.process_block(il, ir)
        c = probe.process_block(il, ir)
        assert a == c, f"shared chain diverged at block {b}"
    ra = ref.st.checkpoint()
    rb = probe.st.checkpoint()
    for k, v in ra.items():
        if k == "name":
            continue
        assert rb[k] == v, f"shared chain state field {k} diverged"


def test_chain_probe_hook_is_off_by_default():
    m = make_model("default")
    assert m.chain_probe_mode is False
    assert m.chain_probe_shaper is None


# ------------------------------------------------------------------- model
def test_model_determinism():
    a = drive_blocks(make_model("a"), 24)
    b = drive_blocks(make_model("b"), 24)
    assert a == b


def test_every_sse_model_produces_signal():
    for mi in st.SSE_MODELS:
        out = drive_blocks(make_model(f"m{mi}", model_i=mi), 8)
        assert max(abs(v) for v in out) > 0, f"model {mi} produced silence"


def test_per_instance_independence():
    """Two concurrent instances must keep independent histories, INCLUDING
    independent QuadWaveshaperState registers."""
    m1 = make_model("i0", model_i=6)
    m2 = make_model("i1", model_i=7, drive_f=-3.0, feedback_f=0.2)
    rs = random.Random(3)
    stim = []
    for _ in range(24):
        stim.append(([rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)],
                     [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]))
    solo1, solo2 = [], []
    for il, ir in stim:
        o = m1.process_block(il, ir)
        solo1 += list(o[0]) + list(o[1])
    for il, ir in stim:
        o = m2.process_block(il, ir)
        solo2 += list(o[0]) + list(o[1])
    n1 = make_model("j0", model_i=6)
    n2 = make_model("j1", model_i=7, drive_f=-3.0, feedback_f=0.2)
    inter1, inter2 = [], []
    for il, ir in stim:
        o = n1.process_block(il, ir)
        inter1 += list(o[0]) + list(o[1])
        o = n2.process_block(il, ir)
        inter2 += list(o[0]) + list(o[1])
    assert inter1 == solo1
    assert inter2 == solo2
    assert solo1 != solo2
    assert n1.st is not n2.st
    assert n1.st.ws is not n2.st.ws
    assert n1.st.chain.hr_a is not n2.st.chain.hr_a
    # both register-owning shapers actually advanced their registers
    assert any(v != 0 for r in n1.st.ws.R for v in r)
    assert any(v != 0 for r in n2.st.ws.R for v in r)


def test_shared_quad_waveshaper_state_is_detectable():
    """The per-instance acceptance needs a control that fires on exactly the
    state THIS leaf adds (the chain state stays per-instance)."""
    a = make_model("k0", model_i=6)
    ref_a = drive_blocks(a, 16, seed=9)
    a2 = make_model("l0", model_i=6)
    b2 = make_model("l1", model_i=7, drive_f=-3.0, feedback_f=0.2)
    b2.st.ws = a2.st.ws                 # THE DEFECT: pooled ws registers only
    assert b2.st.chain is not a2.st.chain
    rs = random.Random(9)
    pooled_a = []
    for _ in range(16):
        il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        o = a2.process_block(il, ir)
        pooled_a += list(o[0]) + list(o[1])
        b2.process_block(il, ir)
    assert pooled_a != ref_a


def test_register_use_inventory_is_measured_not_asserted():
    """`REGISTER_USE` must agree with what the shapers actually touch."""
    sentinel = 12345
    for mi in st.SSE_MODELS:
        state = qs.QuadWaveshaperState()
        for i in range(state.N_REGISTERS):
            for lane in range(state.LANES):
                state.R[i][lane] = sentinel
        shaper = qs.get_quad_waveshaper(mi)
        drive = qs.fq(2.0, qs.FC)
        for x in (0.3, -0.7, 0.9):
            shaper(state, 0, qs.fq(x, qs.FC), drive)
        touched = tuple(i for i in range(state.N_REGISTERS)
                        if state.R[i][0] != sentinel)
        assert touched == qs.REGISTER_USE[mi], f"model {mi}: {touched}"
        # lane 1 is untouched because only lane 0 was driven
        assert all(state.R[i][1] == sentinel for i in range(4))


# ------------------------------------------------- the SSE-branch specifics
def test_dc_offset_probe_is_nonzero_exactly_where_the_source_says():
    """DIGITAL maps zero input to a non-zero value -- that is why the probe
    exists. FuzzTable is non-zero at x = 0 too; the other three are odd."""
    d_s_c = qs.fq(2.0, qs.FC)
    nonzero = {}
    for mi in st.SSE_MODELS:
        m = make_model(f"dc{mi}", model_i=mi)
        nonzero[mi] = m.dc_offset(d_s_c) != 0
    assert nonzero[4] is True, "wst_digital must have a non-zero DC offset"
    assert nonzero[7] is True, "wst_fuzzsoft's LUT is non-zero at x = 0"
    assert nonzero[3] is False and nonzero[5] is False and nonzero[6] is False


def test_dc_offset_probe_does_not_touch_the_live_state():
    """`DistortionEffect::process` probes a THROW-AWAY QuadWaveshaperState."""
    m = make_model("probe", model_i=7)
    drive_blocks(m, 4)
    before = [list(r) for r in m.st.ws.R]
    before_init = list(m.st.ws.init)
    m.dc_offset(qs.fq(2.0, qs.FC))
    assert [list(r) for r in m.st.ws.R] == before
    assert list(m.st.ws.init) == before_init


def test_probe_state_zeroes_init_unlike_engine_init():
    """The probe zeroes BOTH R[i] and `init` (specified); the live init()
    zeroes only R[i] and leaves `init` indeterminate (DD-3)."""
    live = qs.QuadWaveshaperState()
    assert live.init == [True, True]
    live.engine_init()
    assert live.init == [True, True]          # DD-3: frozen to "first sample"
    probe = live.probe_state()
    assert probe.init == [False, False]
    assert all(v == 0 for r in probe.R for v in r)


def test_drive_interpolation_uses_the_pinned_divisor_and_overshoots():
    """dD = (dE - dS)/(BLOCK_SIZE * dist_OS_bits) = /64, NOT /128.

    128 oversampled steps x (dE - dS)/64 lands dNow on 2*dE - dS. The
    overshoot is the pinned behaviour and is reproduced as written.
    """
    m = make_model("dn", model_i=4)
    rs = random.Random(11)
    for _ in range(3):
        il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        m.process_block(il, ir)
        c = m.ctrl
        # the Q13.18 -> Q24.43 /64 is exact (a left shift of 19)
        assert c["d_d"] == (c["d_e"] - c["d_s"]) << 19
        assert c["d_now_end"] == c["d_s_c"] + OS_BLOCK * c["d_d"]
        # ... which is 2*dE - dS, not dE
        assert c["d_now_end"] == (2 * c["d_e"] - c["d_s"]) << 25
        if c["d_e"] != c["d_s"]:
            assert c["d_now_end"] != c["d_e_c"]


def test_skip_drive_norm_is_digital_only():
    assert qs.SKIP_DRIVE_NORM == {3: False, 4: True, 5: False, 6: False,
                                  7: False}
    for mi in st.SSE_MODELS:
        m = make_model(f"s{mi}", model_i=mi)
        assert m.skip_drive_norm == (mi == 4)


def test_drive_normalization_cancels_for_the_non_digital_models():
    """Structural claim recorded in the README, asserted here.

    For models 3/5/6/7 the 1/dNow pre-scale and the shaper's leading
    `x * drive` cancel, so a DIFFERENT drive ramp leaves the shaper stage
    (and therefore the whole output, once the drive ramp itself is held
    equal) essentially unchanged -- which is why the drive-interpolation
    controls must be graded on the DIGITAL bed.
    """
    x_a = 1 << 19
    for mi in (3, 5, 6, 7):
        shaper = qs.get_quad_waveshaper(mi)
        outs = []
        for drive in (0.5, 2.0, 8.0):
            state = qs.QuadWaveshaperState()
            d_c = qs.fq(drive, qs.FC)
            d_inv = qs.frecip(d_c, qs.FC, qs.FC, qs.W64)
            sb = qs.fmul(x_a << 22, d_inv, qs.FC, qs.FC, qs.FC, qs.W64)
            outs.append(shaper(state, 0, sb, d_c))
        spread = max(outs) - min(outs)
        assert spread < (1 << (qs.FC - 21)) * 8, \
            f"model {mi}: drive did not cancel (spread {spread})"
    # ... and for DIGITAL (no pre-scale) it emphatically does NOT cancel
    outs = []
    for drive in (0.5, 2.0, 8.0):
        state = qs.QuadWaveshaperState()
        d_c = qs.fq(drive, qs.FC)
        outs.append(qs.SHAPERS[4](state, 0, x_a << 22, d_c))
    assert max(outs) - min(outs) > (1 << (qs.FC - 21)) * 1000


def test_cvt_is_round_half_to_even_not_truncation():
    """The SSE index convention differs from `lookup_waveshape`'s."""
    one = 1 << qs.FC
    half = one >> 1
    assert qs.cvt_i32(3 * one + half, qs.FC) == 4      # 3.5 -> 4 (even)
    assert qs.cvt_i32(4 * one + half, qs.FC) == 4      # 4.5 -> 4 (even)
    assert qs.cvt_i32(-(3 * one + half), qs.FC) == -4
    assert qs.cvt_i32(one + 1, qs.FC) == 1
    assert qs.cvt_i32(2 * one - 1, qs.FC) == 2         # NOT truncation


def test_ringout_fade_contract():
    f = DistortionSSEModel.ringout_mul
    assert f(0) == 1.0
    assert f(RINGOUT_TIME - RINGOUT_END) == 1.0
    assert f(RINGOUT_TIME - 1) == 0.0
    assert 0.0 < f(RINGOUT_TIME - RINGOUT_END // 2) < 1.0
    assert RINGOUT_TIME * BLOCK / 48000.0 == pytest.approx(1.0666666, rel=1e-6)


def test_tail_is_produced_and_droppable():
    m = make_model("tail", model_i=6, feedback_f=0.99, drive_f=9.0,
                   drive_extend=True)
    drive_blocks(m, 32, seed=21)
    tail = []
    for b in range(64):
        o = m.process_block([0] * BLOCK, [0] * BLOCK, ringout=b + 1)
        tail += list(o[0]) + list(o[1])
    assert max(abs(v) for v in tail) > 0, "no tail produced at all"


def test_zero_external_memory():
    m = make_model("mem")
    drive_blocks(m, 16)
    assert m.st.chain.ext_reads == 0
    assert m.st.chain.ext_writes == 0


def test_checkpoint_includes_the_quad_waveshaper_registers():
    """Issue #121 acceptance: the ws registers must be DECLARED checkpoints."""
    m = make_model("cp", model_i=7)
    drive_blocks(m, 4)
    cp = m.st.checkpoint()
    for i in range(4):
        for lane in range(2):
            assert f"wsR{i}{lane}" in cp
    assert "wsI0" in cp and "wsI1" in cp
    # and the whole #57 chain checkpoint is still there, verbatim
    chain_keys = set(dm.DistortionState("x").checkpoint())
    assert chain_keys <= set(cp), sorted(chain_keys - set(cp))
    for k in ("fb_l", "fb_r", "b1_lag", "hrax000", "lp1_reg0", "ext_reads"):
        assert k in cp


def test_slowrate_coefficient_refresh():
    m = make_model("slow")
    seen = []
    rs = random.Random(1)
    for b in range(SLOWRATE * 3):
        seen.append(m.st.chain.bi)
        m.process_block([rs.randint(-1000, 1000) for _ in range(BLOCK)],
                        [rs.randint(-1000, 1000) for _ in range(BLOCK)])
    assert seen == [b % SLOWRATE for b in range(SLOWRATE * 3)]


# -------------------------------------------------------- evidence records
def test_negative_controls_record():
    path = os.path.join(SXT, "negative-controls", "negative-controls.json")
    rec = json.load(open(path))
    assert rec["status"] == "ALL-CONTROLS-OK"
    assert rec["model_revision"] == model_revision(), \
        "negative-control record is STALE against the frozen model"
    ids = {c["id"] for c in rec["controls"]}
    # the five controls the issue requires, plus this leaf's own four
    assert {"NC-0", "NC-0b", "NC-A", "NC-A2", "NC-B", "NC-C", "NC-D", "NC-E",
            "NC-F", "NC-G", "NC-H"} <= ids
    for c in rec["controls"]:
        assert c["ok"], f"{c['id']} is a BROKEN control"
    base = next(c for c in rec["controls"] if c["id"] == "NC-0")
    assert base["verdict"] == "PASS", "open-loop baseline sanity must pass"
    for mi, leg in base["per_model"].items():
        assert leg["within_tolerance"], f"open-loop leg {mi} out of tolerance"
    for cid in ("NC-A", "NC-A2", "NC-C", "NC-D", "NC-F", "NC-G", "NC-H",
                "NC-B"):
        c = next(x for x in rec["controls"] if x["id"] == cid)
        assert c["verdict"] == "FAIL", f"{cid} must FAIL the check it targets"


def _load_sse_nc_tool():
    """Import tools/distortion_sse_negative_controls.py as a module."""
    import importlib.util
    tool = os.path.join(REPO, "tools", "distortion_sse_negative_controls.py")
    spec = importlib.util.spec_from_file_location("_ncsse", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_negative_control_record_declares_the_environment_it_measured_under():
    """The metric fields are exact under a declared environment ONLY (#243).

    `model_revision` pins the frozen model, and nothing else in this record
    was pinned to anything. But the *metric* fields are not a property of
    the frozen model alone — they are a property of the frozen model AND the
    host. Measured across two libm implementations (#243), regenerating from
    a byte-for-byte **unmodified** tree, with every verdict, every `ok`,
    `status: ALL-CONTROLS-OK`, `rtl-exactness.json` and
    `artifacts/buffer-requirement.json` byte-identical throughout:

    * glibc 2.41 / CPython 3.14.7 / numpy 2.5.3 reproduces every
      `max_abs_diff_lsb` and `rms_diff_*` field byte-for-byte; only 12
      `spectral_corr` fields move, by <= 8.1e-16 relative.
    * Apple libm, same architecture and interpreter, moves 43 max/rms
      fields — the FX-model-7 legs by up to 12 % relative.

    Two mechanisms, both outside the frozen model:

    1. INPUT. `stimulus()` calls libm `sin` at phases running to ~118 rad,
       where libm is not correctly rounded (252 of the harness's 6144
       evaluations are 1 ULP off under Apple libm), so a different libm is a
       different input, which the F-028e-sse-4 chaos amplifies. Substituting
       a correctly rounded `sin` reproduces the same signature: FX-model-7
       legs up to 14 %, FX 3/5/6 <= 4.2e-9, model-independent controls
       <= 1e-13.
    2. `spectral_corr` is numpy, so its last 1-2 bits follow the numpy
       build's reduction order (<= 8.1e-16 relative, on bit-identical
       signals, under a matching digest). Bounded by the recorded numpy
       version, not by the digest.

    So the record must say which input it was measured on, and this test
    RE-DERIVES that fingerprint rather than trusting the record's word for
    it. Fails closed if the environment block is missing or its stimulus
    beds are not the ones the generator renders. On a host whose libm
    differs from the record's, the digest cannot match: that is reported as
    NOT_RUN (skip), never as a pass and never by widening a tolerance — the
    verdict assertions in `test_negative_controls_record` are unconditional
    and carry the controls' actual weight. The committed record is
    glibc-taken, so this check is live in CI and NOT_RUN on an Apple-libm
    workstation.
    """
    rec = json.load(open(os.path.join(SXT, "negative-controls",
                                      "negative-controls.json")))
    env = rec.get("environment")
    assert env, \
        ("negative-control record declares no environment: its metric "
         "fields are libm-dependent and are meaningless without one (#243)")
    for key in ("reproducibility", "python", "python_implementation",
                "platform", "machine", "stimulus_digest", "stimulus_beds",
                "stimulus_digest_note", "spectral_corr_note"):
        assert env.get(key), f"environment record is missing {key!r}"
    # numpy may legitimately be null (spectral_corr degrades to NaN), but the
    # key must be present: it is what bounds mechanism 2 above.
    assert "numpy" in env, "environment record does not declare numpy"

    mod = _load_sse_nc_tool()
    assert [(b["n_blocks"], b["seed"]) for b in env["stimulus_beds"]] == \
        [tuple(b) for b in mod.STIMULUS_BEDS], \
        "the record's stimulus beds are not the ones the generator renders"

    live = mod.stimulus_digest()
    if live != env["stimulus_digest"]:
        pytest.skip(
            "NOT_RUN: this host's stimulus digest %s differs from the "
            "record's %s (libm-dependent input, see EVIDENCE.md §0). The "
            "committed metric fields are exact only under the recorded "
            "environment; no metric comparison is made here and none is "
            "reported as a pass." % (live[:16], env["stimulus_digest"][:16]))
    assert live == env["stimulus_digest"]


def test_stimulus_digest_detects_a_one_ulp_input_change():
    """Live negative control for the digest above (#243).

    The digest's whole claim is "a 1-ULP difference in the harness input
    shows up here". A digest that could not detect the perturbation class it
    exists to detect would be decorative — it would let a genuinely
    different input be reported as the recorded one. So perturb exactly one
    stimulus sample by one ULP and require the digest to move.
    """
    mod = _load_sse_nc_tool()
    base = mod.stimulus_digest()

    real = mod.stimulus

    def one_ulp_off(n_blocks, **kw):
        blocks = real(n_blocks, **kw)
        il, ir, ring = blocks[0]
        il = list(il)
        il[7] = math.nextafter(il[7], math.inf)     # exactly 1 ULP
        blocks[0] = (il, ir, ring)
        return blocks

    mod.stimulus = one_ulp_off
    try:
        perturbed = mod.stimulus_digest()
    finally:
        mod.stimulus = real

    assert perturbed != base, \
        ("the stimulus digest did not move under a 1-ULP change to one "
         "input sample: it cannot detect the libm-class input difference "
         "it is recorded to detect (#243)")
    assert mod.stimulus_digest() == base, "digest is not restored/stable"


def test_closed_loop_sensitivity_finding_is_recorded_not_hidden():
    """F-028e-sse-4 must be reported as a finding, never as a pass.

    FX models 4 and 7 do NOT meet the [PROPOSED] sample-domain budgets at
    the model boundary. The record must say so in those words and must
    carry the measured sensitivity floor that justifies the classification.
    """
    rec = json.load(open(os.path.join(SXT, "negative-controls",
                                      "negative-controls.json")))
    nc0b = next(c for c in rec["controls"] if c["id"] == "NC-0b")
    assert nc0b["proposed_budgets_met_for_all_models"] is False
    assert "F-028e-sse-4" in json.dumps(nc0b)
    assert nc0b["finding"]["routed_to"].startswith("#12")
    legs = nc0b["per_model_legs"]
    for mi in ("3", "5", "6"):
        assert legs[mi]["verdict_vs_proposed_budgets"] == "PASS"
    for mi in ("4", "7"):
        assert legs[mi]["verdict_vs_proposed_budgets"] == "FAIL"
        assert legs[mi]["at_or_below_sensitivity_floor"] is True
        assert "AT-SENSITIVITY-FLOOR" in legs[mi]["status"]


def test_rtl_exactness_record():
    path = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(path):
        pytest.skip("NOT_RUN: no committed RTL exactness record")
    rec = json.load(open(path))
    assert rec["model_revision"] == model_revision(), \
        "rtl-exactness.json is STALE against the frozen model"
    assert rec["status"] == "PASS"
    assert rec["cases"], "no RTL cases recorded"
    for c in rec["cases"]:
        assert c["exact"], f"{c['case']} is not exact"
        assert c["revision_pin"]["ok"]
        assert c["checked"]["outputs"] > 0
    names = {c["case"] for c in rec["cases"]}
    assert any(n.startswith("prs-dual") for n in names)
    assert any("reset" in n for n in names)
    assert any(n.startswith("ringout-tail") for n in names), \
        "the declared tail span must be covered by an exactness case"
    # one exactness case per reachable FX model
    for mi in st.SSE_MODELS:
        assert any(n.startswith(f"model-{mi}-") for n in names), \
            f"no exactness case for FX model {mi}"
    assert rec["mutant_controls"], "no RTL negative controls recorded"
    for m in rec["mutant_controls"]:
        assert m["ok"], f"{m['case']} is a BROKEN control"
    mnames = {m["case"] for m in rec["mutant_controls"]}
    for required in ("mutant-wsshared", "mutant-nodcoffset",
                     "mutant-dcprobe-live", "mutant-drivestep128",
                     "mutant-diginorm", "mutant-order",
                     "stale-revision-pin"):
        assert required in mnames, f"missing RTL control {required}"


def test_buffer_report_record():
    path = os.path.join(SXT, "artifacts", "buffer-requirement.json")
    rec = json.load(open(path))
    assert rec["model_revision"] == model_revision()
    ext = rec["external_memory"]
    assert ext["per_instance_state_bytes"] == 0
    assert ext["reads_per_sample"] == 0 and ext["writes_per_sample"] == 0
    assert ext["delay_line_class_buffers"] == 0
    assert rec["cost_fit_verdict"] == "[PENDING-SXT-016]"
    assert rec["frozen_rom"]["waveshaper_table_digest"] == st.table_digest()
    ws = rec["quad_waveshaper_state"]
    assert ws["n_waveshaper_registers"] == 4
    assert ws["bounded"] is True, \
        "the issue's stop/escalate clause turns on this being bounded"
    assert ws["registers_actually_touched_by_reachable_shapers"] == [0, 1]


def test_settle_boundary_was_measured_not_assumed():
    """#136: the model's silent pre-roll is a MEASURED boundary.

    The two candidate boundaries differ by ~73 dB on the harness anchor, so
    a guessed one would dominate every number in the leg. The record must
    show the two engine-side invariances that settle it, and the declared
    pre-roll must be the one those invariances imply.
    """
    rec = json.load(open(os.path.join(SXT, "artifacts",
                                      "settle-boundary.json")))
    assert rec["A_settle_length_invariance"]["byte_identical"] is True
    assert rec["B_construction_invariance"]["byte_identical"] is True
    assert rec["declared_silent_preroll_blocks"] == 0
    assert rec["status"] == "RESOLVED"
    legs = rec["C_model_boundary_vs_engine"]["silent_preroll_blocks"]
    # the declared boundary must be the better-agreeing one BY MEASUREMENT,
    # and the wrong one must be far outside the proposed budget
    assert legs["0"]["rms_diff_dbfs"] < -46.0
    assert legs["375"]["rms_diff_dbfs"] > -46.0


def test_reference_leg_controls_all_failed_as_required():
    """A reference leg whose negative controls PASS measured nothing."""
    path = os.path.join(SXT, "artifacts", "reference-leg.json")
    rec = json.load(open(path))
    assert rec["controls_ok"] is True, rec.get("warning")
    for cid in ("NC-A", "NC-A2", "NC-SHARED", "NC-B", "NC-C"):
        c = rec["controls"][cid]
        assert c["status"] == "CONTROL-OK", f"{cid}: {c}"
        assert c["must"] == "FAIL"
        if c["gate"] == "tail":
            assert c["tail_gate_ok"] is False
        else:
            assert c["verdict"].startswith("FAIL")
    assert rec["primary"], "no primary comparison was recorded"


def test_reference_leg_carriers_are_declared_synthetic_everywhere():
    """No synthetic number may be presented as corpus reach."""
    import glob
    seen = 0
    for p in sorted(glob.glob(os.path.join(SXT, "artifacts",
                                           "compare-*.json"))):
        rec = json.load(open(p))
        seen += 1
        assert rec["carrier_kind"] == "DECLARED-SYNTHETIC", p
        assert rec["corpus_reach"].startswith("NONE"), p
        assert "no corpus reach" in rec["claim_scope"], p
        assert rec["fx_model_index"] in st.SSE_MODELS, p
    assert seen, "no compare-*.json committed"


def test_corpus_carrier_renders_are_not_run_with_measured_reasons():
    """The three corpus carriers are NOT_RUN, and say why, and have no
    compare record standing in for one."""
    import glob
    text = open(os.path.join(SXT, "artifacts", "render-refusals.txt")).read()
    for slug in ("reversecrash", "trancepluck", "mutantlofiacoustic"):
        assert f"NOT_RUN {slug}__" in text, slug
        assert not glob.glob(os.path.join(SXT, "artifacts",
                                          f"compare-{slug}__*.json")), slug
    # the refusals must be statements about the presets, not about this host
    ctrl = json.load(open(os.path.join(SXT, "artifacts",
                                       "harness-host-control.json")))
    assert ctrl["status"] == "PASS"
    assert ctrl["committed_sha256"] == ctrl["rerendered_sha256"]


def test_evidence_record_exists_and_is_honest():
    path = os.path.join(SXT, "EVIDENCE.md")
    text = open(path).read()
    assert "NOT_RUN" in text
    assert "[PENDING-SXT-016]" in text
    assert "[PROPOSED" in text
    # Heading matched WITHOUT its section number: the numbering shifts
    # whenever a section is inserted, and the guard is about the section
    # being present, not about where it sits.
    assert "What this record does NOT establish" in text
    assert "Follow-ups filed" in text
    # the measured state figures must agree with the buffer report
    rec = json.load(open(os.path.join(SXT, "artifacts",
                                      "buffer-requirement.json")))
    onchip = rec["on_chip_state"]
    assert f"{onchip['q24_43_words']} × Q24.43" in text
    assert f"{onchip['bytes_per_instance']:,} B" in text
    # the sensitivity finding must be visible in the prose, not only the JSON
    assert "F-028e-sse-4" in text


def test_evidence_record_has_no_unfilled_placeholders():
    text = open(os.path.join(SXT, "EVIDENCE.md")).read()
    for token in ("RTL-CASE-TABLE", "RTL-CASES", "RTL-MUTANTS", "TODO",
                  "TBD", "XXX", "FIXME"):
        assert token not in text, f"unfilled placeholder {token} in EVIDENCE.md"
    rec = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    for c in rec["cases"]:
        assert c["case"] in text, f"case {c['case']} missing from EVIDENCE.md"
    for m in rec["mutant_controls"]:
        assert m["case"] in text, f"control {m['case']} missing from EVIDENCE.md"
    assert rec["sim_version"] in text, "simulator version not recorded in prose"


def test_decision_record_registered():
    idx = open(os.path.join(REPO, "decision-records", "README.md")).read()
    name = "0014-distortion-sse-quad-waveshaper-constants.md"
    assert name in idx
    dr = open(os.path.join(REPO, "decision-records", name)).read()
    # every quoted designed scalar must appear in the record
    for token in ("-1.7f", "1.1f", "-0.3f", "0.9f", "0.0001", "0.9999f",
                  "2.4999995", "1.f / (4 * (1 - 0.3f))"):
        assert token in dr, f"designed scalar {token} missing from DR-0014"
    assert "0012" in dr, "DR-0014 must cite the DR-0012 reservation it closes"
    # and DR-0012's reservation must still be the thing being discharged
    dr12 = open(os.path.join(REPO, "decision-records",
                             "0012-distortion-halfband-and-waveshaper-tables.md")
                ).read()
    assert "SSE quad-waveshaper branch" in dr12


# ------------------------------------------------------------- RTL harness
@pytest.mark.skipif(shutil.which(os.environ.get("IVERILOG", "iverilog")) is None,
                    reason="NOT_RUN: iverilog unavailable")
def test_rtl_harness_smoke(tmp_path):
    """Elaborate the committed testbench (exactness itself is the
    comparator's job; this guards against a stale/broken harness)."""
    tb = os.path.join(RTLDIR, "tb_distortion_sse.sv")
    vvp = str(tmp_path / "tb.vvp")
    subprocess.run([os.environ.get("IVERILOG", "iverilog"), "-g2012",
                    "-o", vvp, tb], check=True, cwd=str(tmp_path))
    assert os.path.exists(vvp)


def test_rtl_owns_no_copy_of_the_quoted_engine_constants():
    """DR-0002 clause 1 / DR-0014 clause 1: the RTL streams engine data.

    The eleven designed shaper scalars must reach the testbench through
    INITFILE, never as literals in the source.
    """
    tb = open(os.path.join(RTLDIR, "tb_distortion_sse.sv")).read()
    for w in qs.SHAPER_INIT_WORDS:
        assert str(w) not in tb, \
            f"quoted engine constant {w} is duplicated in the RTL"
        assert f"{w & 0xFFFFFFFFFFFFFFFF:x}" not in tb.lower()
    assert "INITFILE" in tb and "KC(" in tb
