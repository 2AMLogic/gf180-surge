#!/usr/bin/env python3
"""#439 -- non-finite float audio is refused, not graded.

PINS: rms_dbfs rejects NaN/+-inf (exact zero still returns the finite floor);
compare_fx_reference refuses any NaN/+-inf in either stereo bus (either
channel, including a wet-tail sample) with NO_VERDICT and exit 2 before any
metric is computed, leaves no stale report at the requested path, and every
emitted result parses with a strict JSON parser.
DOES NOT: say anything about budgets, fidelity or preset quality.

Failure controls (retained): test_control_direct_nan_does_not_return_floor and
test_control_contaminated_wav_fails_input_validity.
"""

import json
import math
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402
import compare_fx_reference as fx  # noqa: E402

FX = os.path.join(REPO, "tools", "compare_fx_reference.py")
FX_REF = os.path.join(REPO, "reports", "sxt-023", "fixtures",
                      "fm_bass_1__seq-notes-coverage-v1-wet.f32.wav")
FX_MODEL = os.path.join(REPO, "reports", "sxt-023", "artifacts",
                        "model__fm_bass_1__seq-notes-coverage-v1.f32.wav")


def strict(text):
    def bad(tok):
        raise ValueError(tok)
    return json.loads(text, parse_constant=bad)


def data_offset(raw):
    pos = 12
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        sz = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        if cid == b"data":
            return pos + 8, sz // 8
        pos += 8 + sz + (sz & 1)
    raise AssertionError("no data chunk")


def contaminate(src, dst, value, channel, frame):
    raw = bytearray(open(src, "rb").read())
    off, frames = data_offset(raw)
    if frame < 0:
        frame += frames
    at = off + 8 * frame + 4 * channel
    raw[at:at + 4] = struct.pack("<f", value)
    open(dst, "wb").write(bytes(raw))


def run(ref, model, out):
    return subprocess.run([sys.executable, FX, "--ref", str(ref), "--model",
                           str(model), "--json", str(out)],
                          capture_output=True, text=True, cwd=REPO)


# ---- rms_dbfs ---------------------------------------------------------
def test_rms_dbfs_exact_zero_floor_unchanged():
    assert car.rms_dbfs(0.0, 32767.0) == car.RMS_DIFF_DBFS_FLOOR == -300.0
    assert car.rms_dbfs(1.0, 32767.0) == pytest.approx(-90.309, abs=1e-3)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 np.float64("nan"), np.float32("inf")])
def test_control_direct_nan_does_not_return_floor(bad):
    # Failure control: pre-#439 NaN fell through `not rms > 0` to -300.
    with pytest.raises(ValueError):
        car.rms_dbfs(bad, 32767.0)


# ---- the wet comparator ------------------------------------------------
def test_finite_baseline_still_graded(tmp_path):
    out = tmp_path / "ok.json"
    r = run(FX_REF, FX_MODEL, out)
    j = strict(out.read_text())
    assert r.returncode == 0 and j["verdict"].startswith("PASS")
    assert math.isfinite(j["channels"]["mono"]["rms_diff_dbfs"])
    strict(r.stdout)


def test_exact_agreement_keeps_floor(tmp_path):
    out = tmp_path / "same.json"
    r = run(FX_REF, FX_REF, out)
    j = strict(out.read_text())
    assert r.returncode == 0
    assert j["channels"]["mono"]["rms_diff_dbfs"] == car.RMS_DIFF_DBFS_FLOOR


CASES = [(v, ch, fr) for v in (float("nan"), float("inf"), float("-inf"))
         for ch in (0, 1) for fr in (1000, -5)]  # -5: wet tail sample


@pytest.mark.parametrize("bus", ["ref", "model"])
@pytest.mark.parametrize("value,channel,frame", CASES)
def test_control_contaminated_wav_fails_input_validity(
        tmp_path, bus, value, channel, frame):
    ref, model = FX_REF, FX_MODEL
    bad = tmp_path / "bad.f32.wav"
    if bus == "ref":
        # keep the committed name so the sidecar is auto-discovered
        bad = tmp_path / os.path.basename(FX_REF)
        shutil.copy(car.discover_sidecar(FX_REF), tmp_path)
        contaminate(FX_REF, bad, value, channel, frame)
        ref = bad
    else:
        contaminate(FX_MODEL, bad, value, channel, frame)
        model = bad
    out = tmp_path / "report.json"
    out.write_text('{"verdict": "PASS (stale)"}\n')  # stale prior result
    r = run(ref, model, out)
    assert r.returncode == 2
    j = strict(out.read_text())
    assert j["verdict"].startswith("NO_VERDICT")
    assert "input-validity" in j["reason"]
    assert "channel %s" % "LR"[channel] in j["reason"]
    assert "stale" not in out.read_text()
    strict(r.stdout)


def test_first_nonfinite_helper():
    bus = np.zeros((2, 10), dtype=np.float32)
    assert fx.first_nonfinite(bus) is None
    bus[1, 7] = np.inf
    bus[0, 9] = np.nan
    name, idx, _ = fx.first_nonfinite(bus)
    assert (name, idx) == ("L", 9)
