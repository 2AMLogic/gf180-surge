"""SXT-022 / #123 — `voice_model.HalfbandD2` branch-assignment regression.

The shared scene decimator reconstructs its output from two 6-stage allpass
cascades (coefficient sets A and B). Before #123 it sampled the A cascade at
the even index and B at the odd one; the pinned
`sst::filters::HalfRate::HalfRateFilter::process_block_D2`
(`libs/sst/sst-filters@e92d93a9…`, `include/sst/filters/HalfRateFilter.h`)
does the opposite, and the A-even ordering destroys the decimator's stopband
rejection entirely (-0.4 dB instead of -110 dB at 0.30 of the input rate).

Claim discipline (AGENTS.md): these tests establish (1) the frozen model's
internal agreement with the pinned kernel's branch assignment, and (2)
RTL == frozen model at integer equality on a smoke fixture. They establish
NO model-vs-Surge fidelity verdict, no preset-support claim, and no musical
claim. Evidence record: `reports/halfband-branch-order/`.

Every response assertion carries its live negative control: the same check
run against the PRE-FIX ordering must FAIL.
"""
import json
import math
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402

HAS_IVERILOG = all(shutil.which(x) for x in ("iverilog", "vvp"))

BLOCK_OS = vm.BLOCK_SIZE_OS          # oversampled words handed to the decimator
# Steady-state measurement window: the 6-stage allpass cascade (largest
# coefficient 0.9878) needs a long warm-up before the stopband floor settles.
N_IN = 16384
WARMUP_IN = 2048
AMPLITUDE = 0.5                       # Q10.21, comfortably inside the word


# --------------------------------------------------------------- helpers
def _cascades(inp, state):
    """Run both allpass cascades over `inp`, advancing `state` in place."""
    chain_b, chain_a = [], []
    for x_in in inp:
        xb, xa = x_in, x_in
        for j in range(6):
            y = state.bx[j][1] + vm.qmul(vm.HALFBAND_B_Q[j], xb - state.by[j][1])
            state.bx[j] = [xb, state.bx[j][0], state.bx[j][1]]
            state.by[j] = [y, state.by[j][0], state.by[j][1]]
            xb = y
            y = state.ax[j][1] + vm.qmul(vm.HALFBAND_A_Q[j], xa - state.ay[j][1])
            state.ax[j] = [xa, state.ax[j][0], state.ax[j][1]]
            state.ay[j] = [y, state.ay[j][0], state.ay[j][1]]
            xa = y
        chain_b.append(xb)
        chain_a.append(xa)
    return chain_a, chain_b


def _run(order, xs):
    """Decimate `xs` (Q10.21 ints) block-by-block under a given ordering.

    order == "b_even" is the shipped/pinned reconstruction; "a_even" is the
    PRE-#123 reconstruction, kept here only as a live negative control.
    """
    h = vm.HalfbandD2()
    out = []
    for i in range(0, len(xs) - BLOCK_OS + 1, BLOCK_OS):
        blk = xs[i:i + BLOCK_OS]
        if order is None:                       # the real, shipped class
            out += h.process(blk)
            continue
        chain_a, chain_b = _cascades(blk, h)
        if order == "a_even":
            out += [vm.qround(chain_a[2 * n] + chain_b[2 * n + 1], 1)
                    for n in range(len(blk) // 2)]
        else:
            out += [vm.qround(chain_b[2 * n] + chain_a[2 * n + 1], 1)
                    for n in range(len(blk) // 2)]
    return out


def _sine_q(f, n=N_IN, amp=AMPLITUDE):
    return [int(round(amp * vm.ONE * math.sin(2.0 * math.pi * f * i)))
            for i in range(n)]


def _rms_db(words):
    if not words:
        return -300.0
    r = math.sqrt(sum((w / vm.ONE) ** 2 for w in words) / len(words))
    return -300.0 if r <= 0 else 20.0 * math.log10(r)


def _rejection_db(order, f):
    """Input RMS minus output RMS, in dB (positive = attenuation)."""
    xs = _sine_q(f)
    out = _run(order, xs)
    return _rms_db(xs) - _rms_db(out[WARMUP_IN // 2:])


# --------------------------------------------- 1. the pinned branch order
def test_process_samples_b_branch_at_even_index():
    """The shipped class reconstructs out[n] = (B[2n] + A[2n+1]) * 0.5.

    Checked structurally against independently-run cascades, so this pins
    the branch assignment itself, not merely a response shape.
    """
    xs = _sine_q(0.17, n=BLOCK_OS)
    shipped = vm.HalfbandD2().process(list(xs))
    chain_a, chain_b = _cascades(xs, vm.HalfbandD2())
    b_even = [vm.qround(chain_b[2 * n] + chain_a[2 * n + 1], 1)
              for n in range(len(xs) // 2)]
    a_even = [vm.qround(chain_a[2 * n] + chain_b[2 * n + 1], 1)
              for n in range(len(xs) // 2)]
    assert shipped == b_even
    assert shipped != a_even            # the orderings are distinguishable here


# ------------------------------------------------ 2. passband / stopband
@pytest.mark.parametrize("f", [0.05, 0.15, 0.20])
def test_passband_is_flat_within_a_quarter_db(f):
    """Below the output Nyquist the decimator is (near) unity gain."""
    assert abs(_rejection_db(None, f)) <= 0.25


@pytest.mark.parametrize("f", [0.30, 0.45])
def test_stopband_rejection_above_output_nyquist(f):
    """Past the output Nyquist (0.25 of the input rate) the decimator must
    reject. The pinned kernel's declared figure for M=6/steep is ~104 dB;
    the Q10.21 model measures 99-103 dB here. The 80 dB threshold is a
    declared regression floor with ~20 dB of headroom, not a fidelity
    budget.
    """
    assert _rejection_db(None, f) >= 80.0


def test_output_nyquist_boundary_is_the_half_power_crossover():
    """At exactly the output Nyquist (0.25 of the input rate) the halfband
    sits on its -3 dB crossover — measured 3.01 dB. Recorded as the
    transition-band anchor between the passband and stopband rows above;
    it is a characterization, not a budget."""
    r = _rejection_db(None, 0.25)
    assert 2.5 <= r <= 3.5


# ------------------------- 3. NEGATIVE CONTROL: the pre-#123 branch order
@pytest.mark.parametrize("f", [0.30, 0.45])
def test_negative_control_pre_fix_order_fails_the_stopband_check(f):
    """Live control: the A-even ordering this class carried before #123 must
    FAIL the very assertion above, or that assertion proves nothing."""
    assert _rejection_db("a_even", f) < 80.0


def test_negative_control_pre_fix_order_also_sags_the_passband():
    """Second control face: A-even is not merely 'aliasing', it also loses
    passband flatness (this is what the SXT-022 fixtures partly absorbed)."""
    assert abs(_rejection_db("a_even", 0.15)) > 1.0


# ----------------------------------- 4. model <-> RTL lockstep (textual)
RTL_SITES = [
    ("rtl/voice/tb_voice.sv", "qround1(chainb[2*k] + chaina[2*k+1])"),
    ("rtl/voice/voice_broken_mutant.sv", "qround1(chainb[2*k] + chaina[2*k+1])"),
    ("rtl/voice/voice_uni_mutant.sv", "qround1(chainb[2*k] + chaina[2*k+1])"),
    ("rtl/oscillators/classic/tb_classic.sv",
     "clamp8(qround1(chainb[2*k] + chaina[2*k+1]))"),
    ("rtl/oscillators/classic/classic_broken_mutant.sv",
     "clamp8(qround1(chainb[2*k] + chaina[2*k+1]))"),
    ("rtl/oscillators/sine/tb_sine.sv",
     "clamp8((chainb[2*k] + chaina[2*k+1] + 32'sd1) >>> 1)"),
    ("rtl/oscillators/sine/sine_broken_mutant.sv",
     "clamp8((chainb[2*k] + chaina[2*k+1] + 32'sd1) >>> 1)"),
]


@pytest.mark.parametrize("rel,expected", RTL_SITES)
def test_every_rtl_decimator_carries_the_pinned_branch_order(rel, expected):
    """Every RTL copy of the decimator is independently coded, so nothing but
    a check like this keeps them in lockstep with the shared Python class.
    (`voice_halfband_order_mutant.sv` is deliberately excluded: it IS the
    reverted order.)"""
    text = open(os.path.join(REPO, rel), encoding="utf-8").read()
    assert expected in text, "%s lost the pinned branch order" % rel
    assert "chaina[2*k] + chainb[2*k+1]" not in text, (
        "%s still carries the pre-#123 A-even/B-odd order" % rel)


def test_halfband_order_mutant_is_a_single_line_revert_of_tb_voice():
    """The RTL negative control must differ from tb_voice.sv only in the
    branch order (plus its own header banner) — a control that changed two
    things would not isolate the thing it targets."""
    tb = open(os.path.join(REPO, "rtl/voice/tb_voice.sv"),
              encoding="utf-8").read().splitlines()
    mut = open(os.path.join(REPO, "rtl/voice/voice_halfband_order_mutant.sv"),
               encoding="utf-8").read().splitlines()
    banner = 4
    assert mut[:banner] != tb[:banner]
    body = mut[banner:]
    assert len(body) == len(tb)
    diff = [(a, b) for a, b in zip(tb, body) if a != b]
    assert diff == [("      bl = qround1(chainb[2*k] + chaina[2*k+1]);",
                     "      bl = qround1(chaina[2*k] + chainb[2*k+1]);")]


# ------------------------------- 5. RTL-vs-model exactness (needs iverilog)
def _smoke_run(tmp_path):
    run_dir = str(tmp_path / "run")
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "model", "voice", "run_model.py"),
         "--sequence", "leaf48-smoke-bells-v1",
         "--inputs", os.path.join(REPO, "model", "voice", "bells_inputs.json"),
         "--out-dir", run_dir],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return run_dir


def _compare(run_dir, tb, out_json):
    cmd = [sys.executable, os.path.join(REPO, "tools", "compare_rtl_model.py"),
           "--run-dir", run_dir, "--out", out_json]
    if tb:
        cmd += ["--tb", os.path.join(REPO, tb)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    with open(out_json, encoding="utf-8") as f:
        return r.returncode, json.load(f)


@pytest.mark.skipif(not HAS_IVERILOG, reason="iverilog/vvp not present")
def test_rtl_vs_model_exact_after_the_coordinated_fix(tmp_path):
    """Integer equality on the voice smoke fixture with the model and the
    RTL both carrying the pinned branch order."""
    run_dir = _smoke_run(tmp_path)
    rc, summary = _compare(run_dir, None, str(tmp_path / "exactness.json"))
    assert summary["verdict"] == "PASS", summary["first_failures"][:5]
    assert summary["mismatches"] == 0
    assert summary["checked"]["mono"] > 0
    assert rc == 0


@pytest.mark.skipif(not HAS_IVERILOG, reason="iverilog/vvp not present")
def test_negative_control_rtl_branch_order_mutant_fails_exactness(tmp_path):
    """Live control for the test above: an RTL testbench identical to
    tb_voice.sv except for the reverted branch order must FAIL integer
    equality against the same model trace."""
    run_dir = _smoke_run(tmp_path)
    rc, summary = _compare(run_dir, "rtl/voice/voice_halfband_order_mutant.sv",
                           str(tmp_path / "nc.json"))
    assert summary["verdict"] == "FAIL"
    assert summary["mismatches"] > 0
    assert rc != 0
