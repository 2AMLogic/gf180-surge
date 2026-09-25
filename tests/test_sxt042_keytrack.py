"""SXT-042 keytrack modsource tests (pytest).

Covers: the frozen keytrack word (formula, rounding, the integer-exact RTL
equivalent), the engine-cited initialisation/refresh order, per-instance
state, the fail-closed route pass, the runner's negative-control switches,
the exactness comparator's mismatch detection, the offline reference
projection and the applicability scan — without requiring the oracle or
iverilog.
"""
import json
import os
import subprocess
import sys
import wave

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402
from tools.compare_kt_rtl_model import compare, parse_tb  # noqa: E402

V2_INPUTS = os.path.join(REPO, "model", "voice", "bells_inputs.json")
KT_INPUTS = os.path.join(REPO, "model", "voice", "bells_kt_inputs.json")
SMOKE = os.path.join(REPO, "fixtures", "sequences",
                     "leaf48-smoke-bells-v1.json")
RUNNER = os.path.join(REPO, "model", "voice", "run_kt_model.py")
EXTRACTOR = os.path.join(REPO, "model", "voice", "extract_kt_inputs.py")
REF_TOOL = os.path.join(REPO, "tools", "kt_reference_from_fixture.py")
SCAN = os.path.join(REPO, "tools", "kt_applicability_scan.py")
LANDED_BELLS_WAV = os.path.join(REPO, "reports", "sxt-026a", "artifacts",
                                "model-smoke-bells-dry.wav")


def rtl_kt_word(n):
    """The integer-exact equivalent tb_kt.sv implements: floor((n*2^20+3)/6)."""
    num = (1 << 20) * n + 3
    return num // 6 if num >= 0 else -((-num + 5) // 6)


# --------------------------------------------------------------- the word ---
def test_keytrack_word_matches_the_engine_formula():
    # (pitch - root)/12 quantized round-half-up into Q10.21
    assert vm.keytrack_word(60, 60) == 0
    assert vm.keytrack_word(72, 60) == vm.qint(1.0)
    assert vm.keytrack_word(108, 60) == vm.qint(4.0)
    assert vm.keytrack_word(48, 60) == vm.qint(-1.0)
    assert vm.keytrack_word(79, 60) == vm.qint(19 / 12.0)


def test_keytrack_word_integer_exact_rtl_equivalent():
    for n in range(-128, 129):
        assert vm.keytrack_word(60 + n, 60) == rtl_kt_word(n), n


def test_keytrack_word_is_never_a_rounding_tie():
    # n*2^21/12 has fractional part 0, 1/3 or 2/3 -- the freeze depends on it
    for n in range(-128, 129):
        frac = (n * (1 << 21)) % 12
        assert frac in (0, 4, 8)


# ------------------------------------------------------- init / lag order ---
def _inputs():
    return vm.InputsV2(V2_INPUTS)


def test_ctor_initialises_the_modsource_to_zero_then_refreshes():
    """SurgeVoice.cpp: keytrackSource.set_output(0, 0.f) in the ctor; the
    pitch-derived word is installed at the END of a control pass."""
    inp = _inputs()
    calls = []
    orig = vm.VoiceV2._apply_voice_routes

    def spy(self):
        calls.append(self.kt_word)          # value the pass READ
        orig(self)

    vm.VoiceV2._apply_voice_routes = spy
    try:
        v = vm.VoiceV2(inp, 84, 100)
    finally:
        vm.VoiceV2._apply_voice_routes = orig
    assert calls and calls[0] == 0, "first control pass must read keytrack 0"
    assert v.kt_word == vm.keytrack_word(84 + 12 * int(inp.scene_octave),
                                         inp.keytrack_root)


def test_keytrack_state_is_per_instance():
    inp = _inputs()
    a = vm.VoiceV2(inp, 48, 100)
    b = vm.VoiceV2(inp, 84, 100)
    assert a.kt_word != b.kt_word
    a.kt_word = 12345                       # mutating one must not move the other
    assert b.kt_word == vm.keytrack_word(84 + 12 * int(inp.scene_octave),
                                         inp.keytrack_root)


def test_route_sums_are_per_destination_and_keytrack_only():
    inp = _inputs()
    v = vm.VoiceV2(inp, 84, 100)
    v._apply_voice_routes()                 # steady-state pass (kt installed)
    depth = next(d for s, dst, d in inp.voice_routes
                 if s == vm.KEYTRACK_SRC and dst == vm.DEST_FU1_CUTOFF)
    assert v.kt_route_sums[0] == vm.qmul(vm.qint(depth), v.kt_word)
    assert v.kt_route_sums[1] == 0 and v.kt_route_sums[2] == 0


def test_route_pass_is_fail_closed_on_an_out_of_class_destination():
    inp = _inputs()
    v = vm.VoiceV2(inp, 84, 100)
    inp.voice_routes = list(inp.voice_routes) + [(vm.KEYTRACK_SRC, 265, 12.0)]
    with pytest.raises(vm.Refuse) as e:
        v._apply_voice_routes()
    assert "265" in str(e.value)


def test_inputs_v2_refuses_a_keytrack_route_outside_the_vocabulary(tmp_path):
    d = json.load(open(V2_INPUTS, encoding="utf-8"))
    d["graph_echo"]["md_scene_A"]["v"].append(
        [vm.KEYTRACK_SRC, 0, 0, 265, "A Pan", 1.0, 1.0])
    p = tmp_path / "bad_inputs.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(vm.Refuse):
        vm.InputsV2(str(p))


# ------------------------------------------------------------- the runner ---
def _run(args, tmp_path, tag):
    out = tmp_path / tag
    return subprocess.run(
        [sys.executable, RUNNER, "--sequence", SMOKE, "--out-dir", str(out)]
        + args, capture_output=True, text=True), out


def test_runner_render_is_byte_identical_to_the_landed_model(tmp_path):
    r, out = _run([], tmp_path, "base")
    assert r.returncode == 0, r.stderr
    got = open(out / "model.wav", "rb").read()
    assert got == open(LANDED_BELLS_WAV, "rb").read()


def test_runner_refuses_an_out_of_class_route(tmp_path):
    r, _ = _run(["--out-of-class-route"], tmp_path, "refused")
    assert r.returncode == 2
    assert "outside the declared SXT-042 destination class" in r.stderr


def test_runner_refuses_a_drifted_sidecar(tmp_path):
    d = json.load(open(KT_INPUTS, encoding="utf-8"))
    d["voice_routes"][-1]["depth_raw"] += 1.0
    p = tmp_path / "drift.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    out = tmp_path / "drift-run"
    r = subprocess.run([sys.executable, RUNNER, "--sequence", SMOKE,
                        "--kt-inputs", str(p), "--out-dir", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "sidecar" in r.stderr


def test_lag_inversion_is_inert_on_constant_pitch_voices(tmp_path):
    a, outa = _run([], tmp_path, "a")
    b, outb = _run(["--refresh-before"], tmp_path, "b")
    assert a.returncode == 0 and b.returncode == 0
    assert open(outa / "model.wav", "rb").read() == \
        open(outb / "model.wav", "rb").read()


def test_controls_change_the_render(tmp_path):
    base, outb = _run([], tmp_path, "cbase")
    assert base.returncode == 0
    ref = open(outb / "model.wav", "rb").read()
    for tag, args in (("zero", ["--zero-dest", "cutoff"]),
                      ("root", ["--ignore-root"]),
                      ("swap", ["--source-swap", "velocity"]),
                      ("syn", ["--synthetic-routes"])):
        r, out = _run(args, tmp_path, tag)
        assert r.returncode == 0, r.stderr
        assert open(out / "model.wav", "rb").read() != ref, tag


def test_stimulus_and_trace_agree_on_the_route_table(tmp_path):
    r, out = _run([], tmp_path, "stim")
    assert r.returncode == 0
    trace = json.load(open(out / "model_trace.json"))
    words = [int(x, 16) for x in
             open(out / "rtl" / "kt_routes.hex").read().split()]
    assert len(words) == 3 * len(trace["route_table"])
    init = [int(x, 16) for x in open(out / "rtl" / "kt_init.hex").read().split()]
    assert init[1] == trace["keytrack_root"] and init[7] == len(
        trace["route_table"])


# ------------------------------------------------------- exactness harness ---
def test_comparator_detects_a_single_word_mismatch(tmp_path):
    trace = {"blocks": [{"b": 0, "voices": [
        {"slot": 0, "kt_word": 7, "kt_route_sums": [1, 2, 3],
         "mod_cutoff": 4, "mod_reso": 5, "mod_envmod": 6, "mod_vca_db": 8}]}]}
    good = tmp_path / "good.txt"
    good.write_text("V 0 0 7 1 2 3 4 5 6 8\n")
    checked, fails = compare(trace, parse_tb(str(good)))
    assert not fails and checked["fields"] == 8
    bad = tmp_path / "bad.txt"
    bad.write_text("V 0 0 7 1 2 3 4 5 6 9\n")
    _, fails = compare(trace, parse_tb(str(bad)))
    assert len(fails) == 1 and "mod_vca_db" in fails[0]


def test_comparator_flags_a_missing_and_an_extra_rtl_row(tmp_path):
    trace = {"blocks": [{"b": 0, "voices": [
        {"slot": 0, "kt_word": 0, "kt_route_sums": [0, 0, 0],
         "mod_cutoff": 0, "mod_reso": 0, "mod_envmod": 0, "mod_vca_db": 0}]}]}
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    _, fails = compare(trace, parse_tb(str(empty)))
    assert any("missing V line" in f for f in fails)
    extra = tmp_path / "extra.txt"
    extra.write_text("V 0 0 0 0 0 0 0 0 0 0\nV 1 3 0 0 0 0 0 0 0 0\n")
    _, fails = compare(trace, parse_tb(str(extra)))
    assert any("absent from the model trace" in f for f in fails)


# ------------------------------------------- provenance / reference / scan ---
def test_extractor_is_fail_closed_without_an_oracle(tmp_path):
    r = subprocess.run([sys.executable, EXTRACTOR, "--out",
                        str(tmp_path / "x.json")],
                       capture_output=True, text=True)
    if r.returncode == 0:                    # an oracle host: readback ran
        assert json.load(open(tmp_path / "x.json"))[
            "provenance_mode"] == "engine-readback"
    else:
        assert r.returncode == 2 and "REFUSING" in r.stderr


def test_extractor_offline_reproduces_the_committed_sidecar(tmp_path):
    out = tmp_path / "kt.json"
    r = subprocess.run([sys.executable, EXTRACTOR, "--allow-offline-provenance",
                        "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.load(open(out)) == json.load(open(KT_INPUTS))


def test_reference_projection_reproduces_the_committed_wav(tmp_path):
    out = tmp_path / "ref.wav"
    r = subprocess.run([sys.executable, REF_TOOL, "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    committed = os.path.join(REPO, "reports", "SXT-042", "artifacts",
                             "reference-sxt025-accept-v1-bells-dry.wav")
    assert open(out, "rb").read() == open(committed, "rb").read()
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 48000


def test_applicability_scan_refuses_the_named_carriers(tmp_path):
    out = tmp_path / "scan.json"
    r = subprocess.run([sys.executable, SCAN, "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    scan = json.load(open(out))
    by = {c["path"]: c for c in scan["carriers"]}
    bells = "resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp"
    assert by[bells]["in_class"] is True
    for p, c in by.items():
        if p != bells:
            assert c["in_class"] is False
            assert c["route_class_reasons"] or c["voice_class_reasons"]
    # the leaf adds no NEW in-class preset: its only in-class preset is the
    # carrier the landed SXT-026a leaf already models
    assert scan["voice_class_ok"] == [bells]
    assert scan["recovery_basis_in_class_count"] == 0
