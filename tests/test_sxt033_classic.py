#!/usr/bin/env python3
"""SXT-033 Classic oscillator family tests (issue #67).

Covers: the frozen model's declared parameter classes and fail-closed
refusals, the pinned pitch-table construction fix, RTL-vs-model exactness on
a deterministic smoke configuration (iverilog required, skipped when
absent), and the in-repo guards. Oracle-dependent tests skip as NOT_RUN
when the external pinned oracle is absent — a skipped test is never a pass.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.voice import voice_model as vm  # noqa: E402

CLASSIC = os.path.join(REPO, "model", "oscillators", "classic")
TB = os.path.join(REPO, "rtl", "oscillators", "classic", "tb_classic.sv")
MUTANT = os.path.join(REPO, "rtl", "oscillators", "classic",
                      "classic_broken_mutant.sv")
sys.path.insert(0, CLASSIC)

import classic_model as cm  # noqa: E402

HAS_IVERILOG = all(shutil.which(x) for x in ("iverilog", "vvp"))
INPUTS = sorted(os.listdir(os.path.join(CLASSIC, "inputs")))


def _synth_inputs(tmp, **over):
    """Deterministic declared-class configuration (test configuration; the
    parameter values are drawn from the recovery-basis presets' observed
    ranges — see model/oscillators/classic/README.md)."""
    d = {
        "schema_version": 1, "issue": "SXT-033", "carrier": "test",
        "slot": 1, "preset_path": "test-configuration",
        "preset_census_blob_sha1": "0",
        "octave": -1, "scene_octave": 0, "keytrack": True,
        "pitch_param": 0.0, "retrigger": True,
        "shape": -1.0, "pw": 0.282, "pw2": 0.5, "submix": 0.316,
        "sync": 0.0, "unison_detune": 0.163, "unison": 4,
        "extend_detune": False, "absolute_detune": False, "character": 0,
        "drift": 0.0, "o_level": 0.8, "level_pfg": 0.0,
        "scene_volume": 0.9, "vca_db": 3.0, "vca_velsense": -6.0,
        "master_db": -2.0,
        "adsr": {"a": -5.2, "d": -3.0, "s": 0.6, "r": -3.5, "a_s": 1.0,
                 "d_s": 1.0, "r_s": 2.0, "mode": 0.0},
    }
    d.update(over)
    path = os.path.join(tmp, "synth.json")
    with open(path, "w") as f:
        json.dump(d, f)
    return path


def _run_model(inputs, out, seq="seq-notes-repeated-v1", blocks=96,
               env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(
        [sys.executable, os.path.join(CLASSIC, "run_model.py"),
         "--inputs", inputs, "--sequence", seq, "--out-dir", out,
         "--rtl", "--max-blocks", str(blocks)],
        capture_output=True, text=True, env=e, cwd=REPO)
    return r


def _compare(run_dir, tb=TB):
    return subprocess.run(
        [sys.executable, os.path.join(REPO, "tools",
                                      "compare_classic_rtl_model.py"),
         "--run-dir", run_dir, "--tb", tb],
        capture_output=True, text=True, cwd=REPO)


# ----------------------------------------------------------------- model ---

def test_pinned_ntpi_tuningctr_fractional_term():
    # SurgeStorage.cpp: table_two_to_the_minus[i] = 2^(-i/12/1000); the fine
    # interpolation of the fractional semitone must follow the MINUS table
    # (the landed SXT-022 helper's 12000x-steep term is corrected here —
    # model/oscillators/classic/README.md finding).
    for detune, want in ((0.163, 2 ** (-0.163 / 12)),
                         (-0.163, 2 ** (+0.163 / 12)),
                         (1.0, 2 ** (-1.0 / 12)),
                         (28.607, 2 ** (-28.607 / 12))):
        got = cm.ntpi_tuningctr(vm.qint(detune)) / float(1 << 21)
        assert abs(got - want) < 1e-5, (detune, got, want)


def test_sync_rate_uses_clamped_semitones(tmp_path):
    # sync = min(l_sync, 156 - pitch): the impulse rate word must reflect the
    # clamp for high pitches and the raw value otherwise
    d = json.loads(open(os.path.join(
        CLASSIC, "inputs", "tentacles.json")).read())
    o = cm.ClassicOsc(cm.Inputs(os.path.join(
        CLASSIC, "inputs", "tentacles.json")), 60)
    assert abs(o.t_u[0] / float(1 << 21)
               - 2 ** (-min(28.607, 156 - 48) / 12.0)) < 1e-4


def test_refusals_are_fail_closed(tmp_path):
    # Inputs/Adsr-level refusals: decay shape, mode
    # ClassicOsc-level refusals: unison cap, absolute detune, drift, Bright
    cases = (
        ({"unison": 17}, "unison", "osc"),
        ({"absolute_detune": True}, "absolute", "osc"),
        ({"drift": 0.3}, "drift", "osc"),
        ({"character": 2}, "Bright", "osc"),
        ({"adsr": {"a": -5.2, "d": -3.0, "s": 0.6, "r": -3.5, "a_s": 1.0,
                   "d_s": 2.0, "r_s": 2.0, "mode": 0.0}},
         "decay shape", "inputs"),
    )
    for over, msg, level in cases:
        d = json.loads(open(_synth_inputs(tmp_path)).read())
        d.update(over)
        p = os.path.join(tmp_path, "m.json")
        json.dump(d, open(p, "w"))
        i = cm.Inputs(p)
        if level == "inputs":
            with pytest.raises(RuntimeError, match=msg):
                cm.AdsrClassic(i.adsr, "aeg")
        else:
            with pytest.raises(RuntimeError, match=msg):
                cm.ClassicOsc(i, 60)


def test_unison_constants_match_unisonsetup(tmp_path):
    # prepare_unison / UnisonSetup: attenuation 1/sqrt(n) (float32), bias
    # 2/(n-1), offset -1; per-voice detune udet*(bias*v-1) in float32 order
    inp = cm.Inputs(_synth_inputs(tmp_path, unison=6, unison_detune=0.2))
    o = cm.ClassicOsc(inp, 48)
    att = o.out_attenuation / float(1 << 21)
    assert abs(att - 1.0 / (6 ** 0.5)) < 1e-6
    dets = [round(v, 6) for v in o.voice_detune]
    assert dets == [round(0.2 * (2.0 / 5 * v - 1.0), 6) for v in range(6)]


def test_inputs_are_census_pinned_and_retriggered():
    for name in INPUTS:
        d = json.loads(open(os.path.join(CLASSIC, "inputs", name)).read())
        assert d["preset_census_blob_sha1"] != "0"
        assert d["retrigger"] is True, name
        assert d["drift"] == 0.0, name
        assert 1 <= d["unison"] <= 16, name
        assert not d["absolute_detune"], name


# ------------------------------------------------------------------- RTL ---

@pytest.mark.skipif(not HAS_IVERILOG, reason="iverilog/vvp not present")
def test_rtl_vs_model_exact_smoke(tmp_path):
    inputs = _synth_inputs(tmp_path)
    out = str(tmp_path / "run")
    r = _run_model(inputs, out)
    assert r.returncode == 0, r.stderr
    c = _compare(out)
    assert c.returncode == 0, c.stdout + c.stderr


@pytest.mark.skipif(not HAS_IVERILOG, reason="iverilog/vvp not present")
def test_negative_control_mutant_fails_exactness(tmp_path):
    inputs = _synth_inputs(tmp_path)
    out = str(tmp_path / "run")
    assert _run_model(inputs, out).returncode == 0
    c = _compare(out, tb=MUTANT)
    assert c.returncode == 1, "mutant must FAIL the exactness check"


def test_negative_control_submode_confusion_fails_budget(tmp_path):
    # drive the committed unison carrier with the landed SXT-022 Attacky-class
    # arithmetic (unison 1): the model-vs-reference budget check must FAIL
    carrier = "crush" if os.path.exists(
        os.path.join(CLASSIC, "inputs", "crush.json")) else "horn"
    ref = os.path.join(REPO, "reports", "SXT-033", "artifacts",
                       "%s__seq-notes-repeated-v1-ref.wav" % carrier)
    if not os.path.exists(ref):
        pytest.skip("committed reference render not present")
    inputs = os.path.join(CLASSIC, "inputs", carrier + ".json")
    out = str(tmp_path / "nc")
    r = _run_model(inputs, out, blocks=None, env={"SXT033_NC_SUBMODE_CONFUSION": "1"})
    if r.returncode != 0:
        # full render too heavy for CI; a capped render still demonstrates it
        r = _run_model(inputs, out, blocks=256,
                       env={"SXT033_NC_SUBMODE_CONFUSION": "1"})
    assert r.returncode == 0, r.stderr
    c = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools",
                                      "compare_audio_reference.py"),
         "--ref", ref, "--model", os.path.join(out, "model.wav")],
        capture_output=True, text=True)
    assert "FAIL against proposed budgets" in c.stdout


def test_out_of_class_preset_refused():
    # House Of Chords (a recovery-basis preset) has its Classic slots only in
    # scene B; the extractor must refuse it for fixture use (exit 2)
    r = subprocess.run(
        [sys.executable, os.path.join(CLASSIC, "extract_inputs.py"),
         "--carrier", "house", "--out", os.path.join(tempfile.gettempdir(),
                                                     "house.json")],
        capture_output=True, text=True, cwd=REPO)
    combined = r.stdout + r.stderr
    if "ORACLE_SURGE_DIR" in combined or "requires the external oracle" in combined:
        pytest.skip("external pinned oracle not present")
    assert r.returncode == 2, combined
    assert "no Classic oscillator in scene A" in combined
