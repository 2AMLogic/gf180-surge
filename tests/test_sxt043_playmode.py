"""SXT-043 (#77) playmode submode pm_mono_st_fp tests (pytest).

Covers the oracle-independent and iverilog-independent machinery: the
pure portamento/glide arithmetic, the allocation state machine
(create/legato/legato_down/reclaim/suppression, priority-mode scans), the
declared negative controls (anchor-last-key, shared-portamento-state,
reset-osc-on-reclaim), the model runner's stimulus/trace consistency, and
the RTL-vs-model comparator's own mismatch detection (against hand-written
trace text -- no iverilog invoked here).

These are claim-(1)-side tests (RTL-vs-frozen-model exactness machinery).
They establish nothing about model-vs-pinned-engine agreement (claim 2) or
sound quality (claim 3); those are reported, with measured numbers, in
reports/SXT-043/EVIDENCE.md from a host with the pinned oracle.

The harness-reporting section at the end (issue #645) pins the migrated
harness's reporting boundary with a STUBBED simulator (rcc.subprocess is
replaced; no iverilog, no vvp): a simulator-level failure must be published
as `comparison: NOT_RUN` with a named reason, never as an RTL-vs-model
disagreement, and never as a surviving stale verdict.  The real-toolchain
measurements behind those stubs, taken on Icarus 13.0 against a bass2
`seq-notes-holds-v1` run dir: with `rtl/ev.hex` removed the UNMIGRATED
harness published a numeric `"FAIL", "mismatches": 42` (Icarus reports the
open failure on stdout and still exits 0, so `check=True` saw nothing --
`DONE pm-qmuls=0 voice-blocks=0`); an uncompilable `--tb` over an `--out`
holding the committed PASS left that stale PASS in place after a
CalledProcessError traceback.  A healthy run prints only the two
"Not enough words" WARNINGs, `DONE pm-qmuls=5148 voice-blocks=4392` and
`$finish` -- never the `$readmem` + `Unable to open` conjunction (#193's
per-harness false-positive baseline).
"""
import hashlib
import importlib
import json
import os
import subprocess
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "sine"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "playmode"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import voice_model as vm                                      # noqa: E402
import sine_model as sm                                       # noqa: E402
import pm_mono_st_fp as pm                                     # noqa: E402
import _rtl_compile_common as rcc                             # noqa: E402
from refusal import Refuse                                    # noqa: E402
import tools.compare_pm_rtl_model as pm_harness               # noqa: E402
importlib.reload(pm_harness)   # clean module object per test session
from tools.compare_pm_rtl_model import compare, parse_tb, FIELD_NAMES  # noqa: E402

RUNNER = os.path.join(REPO, "model", "voice", "playmode", "run_model.py")
INPUTS = os.path.join(REPO, "model", "voice", "playmode", "inputs", "bass2.json")


def _run(extra_args, out_dir, sequence="seq-mono-fingered-v1"):
    cmd = [sys.executable, RUNNER, "--inputs", INPUTS, "--sequence", sequence,
           "--out-dir", str(out_dir)] + list(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


# ------------------------------------------------------------- pure arithmetic
def test_glide_phase_linear_is_a_pure_format_shift():
    # cfg.curve PORTA_LIN: phase = qround(portaphase, F_PHASE - FQ) -- no table
    assert pm.glide_phase(pm.PORTA_LIN, 0) == 0
    one_q29 = 1 << pm.F_PHASE
    assert pm.glide_phase(pm.PORTA_LIN, one_q29) == pm.ONE


def test_glide_log_and_exp_are_complementary_at_the_table_ends():
    # table_glide_log[0] == log2(1)/log2(11) == 0 exactly; table_glide_exp
    # is defined as 1 - table_glide_log[511 - i], so it is 1.0 at i=511.
    assert pm._tbl_glide_log(0) == 0.0
    assert pm._tbl_glide_exp(511) == 1.0
    # and the complementary relationship holds by construction at every i
    for i in (0, 1, 255, 510, 511):
        assert pm._tbl_glide_exp(i) == 1.0 - pm._tbl_glide_log(511 - i)


def test_floor_half_matches_python_floor_for_nonnegative_pitches():
    # every pitch value in this leaf derives from a MIDI key (>= 0), so
    # floor_half only ever needs to behave like floor() on nonnegative input
    for key in (0, 1, 36, 60, 61, 127):
        q = vm.qint(float(key)) + (vm.ONE // 3)   # a non-multiple-of-ONE value
        assert pm.floor_half(q) == (q // vm.ONE) * vm.ONE


def test_porta_rate_refuses_outside_declared_range():
    try:
        pm.porta_rate_q29(2.01)
        assert False, "expected Refuse"
    except Refuse:
        pass
    try:
        pm.porta_rate_q29(-8.01)
        assert False, "expected Refuse"
    except Refuse:
        pass


# --------------------------------------------------------- allocation machine
def _inputs():
    """The real, committed bass2.json sidecar, loaded through the base
    sine-oscillator Inputs class (everything MonoVoice/SineOsc read) plus
    the two extra fields PmInputs adds -- avoids hand-rolling a stub whose
    attribute set can silently drift from what the frozen classes need."""
    inp = sm.Inputs(INPUTS)
    with open(INPUTS, encoding="utf-8") as f:
        d = json.load(f)
    inp.cut_activation = d["osc_cut_activation_probe"]
    inp.vca_gain_routes = []
    return inp


def _scene(priority_mode=pm.NOTE_ON_LATEST_RETRIGGER_HIGHEST,
          envelope_mode=pm.RESTART_FROM_LATEST, fingered=True,
          porta_val=-5.96, porta_val_min=-8.0):
    cfg = pm.PortamentoConfig(porta_val=porta_val, curve=pm.PORTA_LIN,
                              gliss=False, constrate=False,
                              porta_retrigger=False, fingered=fingered,
                              porta_val_min=porta_val_min)
    return pm.MonoStFpScene(_inputs(), cfg, priority_mode, envelope_mode)


def test_create_then_legato_single_trigger_keeps_the_envelope():
    sc = _scene()
    sc.note_on(0, 36, 100)
    v = sc.voices[0]
    aeg_state_before = v.aeg.state
    aeg_phase_before = v.aeg.phase
    sc.note_on(1, 48, 90)
    assert len(sc.voices) == 1, "single trigger: still exactly one voice"
    assert sc.voices[0] is v, "the SAME voice object, legato'd onto the new key"
    assert v.key == 48
    assert v.aeg.state == aeg_state_before and v.aeg.phase == aeg_phase_before, \
        "legato (single trigger) must not touch the envelope"
    assert [e["event"] for e in sc.events] == ["create", "legato"]


def test_note_off_hands_down_to_a_still_held_key_instead_of_releasing():
    sc = _scene()
    sc.note_on(0, 36, 100)
    sc.note_on(1, 60, 100)          # legato onto 60 (36 still "down" in keystate)
    sc.note_off(2, 60, 0)           # release 60: key 36 is still held -> legato_down
    assert sc.voices[0].key == 36
    assert sc.voices[0].gate is True
    assert [e["event"] for e in sc.events] == ["create", "legato", "legato_down"]


def test_note_off_with_nothing_else_held_releases():
    sc = _scene()
    sc.note_on(0, 36, 100)
    sc.note_off(1, 36, 0)
    assert sc.voices[0].gate is False
    assert sc.voices[0].aeg.state == vm.Adsr.S_RELEASE


def test_reclaim_reuses_the_voice_and_restarts_the_attack():
    # bass2's own ADSR has an instant attack (a == -8.0, the fixture's own
    # minimum): attackFrom(level) is defined but its "start" argument is
    # INERT whenever the instant-attack condition holds (the ctor/attackFrom
    # tail forces output=ONE, phase=PHASE_ONE regardless of start) -- see
    # test_aeg_mono_attack_from_restarts_at_the_captured_level below for the
    # non-instant-attack path this carrier can never reach.
    sc = _scene()
    sc.note_on(0, 36, 100)
    sc.note_off(1, 36, 0)           # -> release, decaying
    for b in range(2, 10):
        sc.process_block(b, [0] * pm.BLOCK_SIZE_OS)
    assert sc.voices[0].aeg.state == vm.Adsr.S_RELEASE
    sc.note_on(10, 60, 100)
    assert len(sc.voices) == 1, "reclaim reuses the slot, does not create a second voice"
    v = sc.voices[0]
    assert v.key == 60 and v.gate is True
    assert v.aeg.state == vm.Adsr.S_DECAY        # instant-attack: straight to DECAY
    assert v.aeg.output == vm.ONE
    assert [e["event"] for e in sc.events] == ["create", "release", "reclaim"]


def test_aeg_mono_attack_from_restarts_at_the_captured_level():
    """AegMono.attack_from(start), start > 0, NOT an instant attack: the
    general `restartAEGFEGAttack(level)` mechanism reclaim() relies on,
    isolated from bass2's instant-attack fixture (which can never reach
    this branch -- see the test above)."""
    prm = {"a": -2.0, "d": 0.0, "s": 1.0, "r": -5.0,
          "a_s": 1, "d_s": 0, "r_s": 0, "mode": 0}
    aeg = pm.AegMono(prm, "aeg")
    start = vm.qint(0.4)
    aeg.attack_from(start)
    assert aeg.state == vm.Adsr.S_ATTACK
    assert aeg.output == start
    assert aeg.scalestage == vm.ONE and aeg.idlecount == 0
    # a_s == 1 (linear): phase = qround(start, FQ - F_PHASE) (a left shift,
    # since FQ - F_PHASE < 0)
    assert aeg.phase == vm.qround(start, pm.FQ - pm.F_PHASE)


def test_aeg_mono_uber_release_uses_the_fixed_rate_not_the_release_param():
    prm = {"a": -8.0, "d": 0.0, "s": 1.0, "r": -5.0,
          "a_s": 1, "d_s": 0, "r_s": 0, "mode": 0}
    aeg = pm.AegMono(prm, "aeg")
    aeg.attack_from(0)
    aeg.output = vm.qint(0.8)
    aeg.uber_release()
    assert aeg.state == vm.Adsr.S_UBER
    assert aeg.scalestage == vm.qint(0.8)
    # the uber-release rate is the FIXED envelope_rate_linear_nowrap(-6.5),
    # independent of this fixture's own release rate (r == -5.0)
    assert aeg.uber_rate == vm.envelope_rate_linear_nowrap(vm.qint(-6.5))
    assert aeg.uber_rate != vm.envelope_rate_linear_nowrap(vm.qint(-5.0))


def test_pm_mono_st_fp_anchors_a_new_voice_at_its_own_pitch_not_last_key():
    sc = _scene(fingered=True)
    sc.note_on(0, 72, 100)
    sc.note_off(1, 72, 0)
    sc.note_on(2, 36, 100)           # far from 72; fingered -> anchor at OWN pitch
    v = sc.voices[0]
    assert v.porta.portasrc_key == vm.qint(36.0), \
        "pm_mono_st_fp never glides a fresh note-on, however recently another key sounded"


def test_dropping_the_fingered_anchor_glides_from_the_prior_key_instead():
    # the SAME scenario, with `fingered` off (simulating a different submode):
    # the glide source becomes last_key, demonstrating the branch is load-bearing.
    sc = _scene(fingered=False)
    sc.note_on(0, 72, 100)
    sc.note_off(1, 72, 0)
    sc.note_on(2, 36, 100)
    v = sc.voices[0]
    assert v.porta.portasrc_key == vm.qint(72.0)


def test_always_highest_suppresses_a_lower_note_on():
    sc = _scene(priority_mode=pm.ALWAYS_HIGHEST)
    sc.note_on(0, 60, 100)
    sc.note_on(1, 48, 100)           # lower than the held 60 -> suppressed
    assert len(sc.voices) == 1 and sc.voices[0].key == 60
    assert [e["event"] for e in sc.events] == ["create", "suppressed"]


def test_always_lowest_hands_down_to_the_lowest_held_key():
    sc = _scene(priority_mode=pm.ALWAYS_LOWEST)
    sc.note_on(0, 60, 100)
    sc.note_on(1, 48, 100)           # lower: legato down to 48 allowed through
    sc.note_off(2, 48, 0)            # release 48: 60 still held -> legato to 60? no:
    # ALWAYS_LOWEST picks the LOWEST held key on release too; only 60 remains held
    assert sc.voices[0].key == 60


def test_voice_pool_exhaustion_is_fail_closed():
    # RESTART_FROM_ZERO: a note-on never reclaims, only uber-releases the
    # previously-released (non-gated, non-uberreleased) voice and creates a
    # FRESH one. Immediately releasing each note before the next note-on
    # (no time to decay to idle) means every cycle adds one more live voice
    # to the pool instead of reusing a slot -- POOL+1 such cycles must
    # exhaust the declared 8-slot pool and fail closed, never silently steal
    # a slot.
    sc = _scene(envelope_mode=pm.RESTART_FROM_ZERO)
    b = 0
    try:
        for i in range(pm.MonoStFpScene.POOL + 1):
            key = 40 + i
            sc.note_on(b, key, 100)
            b += 1
            sc.note_off(b, key, 0)
            b += 1
        assert False, "expected the pool to be exhausted by now"
    except Refuse as e:
        assert "exhausted" in str(e)
    assert len(sc.voices) <= pm.MonoStFpScene.POOL, \
        "the pool invariant must hold even while failing closed"


# -------------------------------------------- model runner / stimulus checks
def test_model_run_is_deterministic(tmp_path):
    r1 = _run([], tmp_path / "a")
    r2 = _run([], tmp_path / "b")
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    wav1 = (tmp_path / "a" / "model.wav").read_bytes()
    wav2 = (tmp_path / "b" / "model.wav").read_bytes()
    assert hashlib.sha256(wav1).hexdigest() == hashlib.sha256(wav2).hexdigest()


def test_model_run_emits_the_declared_hex_and_trace_shape(tmp_path):
    r = _run([], tmp_path)
    assert r.returncode == 0, r.stderr
    trace = json.load(open(tmp_path / "model_trace.json"))
    assert trace["format"] == "sxt-043-playmode-trace/1"
    assert trace["leaf"] == "SXT-043" and trace["issue"] == 77
    assert trace["state_word_order"][0] == "active"
    assert trace["state_word_order"][1:] == pm.STATE_WORD_ORDER
    assert trace["pool"] == pm.MonoStFpScene.POOL
    for blk in trace["blocks"]:
        assert len(blk["slots"]) == pm.MonoStFpScene.POOL
        for slot_rec in blk["slots"]:
            assert len(slot_rec) == 1 + pm.N_STATE_WORDS
    init_words = [int(x, 16) for x in
                  open(tmp_path / "rtl" / "init.hex").read().split()]
    assert len(init_words) == 25
    assert init_words[-1] == pm.MonoStFpScene.POOL
    ev_words = [int(x, 16) for x in
               open(tmp_path / "rtl" / "ev.hex").read().split()]
    assert len(ev_words) % 4 == 0


# ------------------------------------------------- declared negative controls
def test_nc_anchor_last_key_refuses_on_the_fingered_sequence(tmp_path):
    r = _run(["--nc-anchor-last-key"], tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "outside declared" in r.stderr


def test_nc_reset_osc_on_reclaim_changes_the_render(tmp_path):
    base = _run([], tmp_path / "base", sequence="seq-mono-reclaim-v1")
    nc = _run(["--nc-reset-osc-on-reclaim"], tmp_path / "nc",
             sequence="seq-mono-reclaim-v1")
    assert base.returncode == 0 and nc.returncode == 0
    a = hashlib.sha256((tmp_path / "base" / "model.wav").read_bytes()).hexdigest()
    b = hashlib.sha256((tmp_path / "nc" / "model.wav").read_bytes()).hexdigest()
    assert a != b, "resetting the oscillator on a mono reclaim must be audible"


def test_nc_share_portamento_state_is_a_recorded_coverage_gap(tmp_path):
    """None of this leaf's 3 declared carriers' fixtures ever hold two
    concurrently-alive voices (monoVoiceEnvelopeMode == RESTART_FROM_LATEST
    always reclaims before creating a second one) -- so sharing the
    portamento object across voices is indistinguishable from per-instance
    state on THESE carriers. This test pins that fact down (not a false
    PASS of the control) rather than silently losing track of it."""
    for seq in ("seq-notes-coverage-v1", "seq-notes-repeated-v1",
               "seq-notes-holds-v1", "seq-mono-fingered-v1",
               "seq-mono-reclaim-v1"):
        r = _run([], tmp_path / seq, sequence=seq)
        assert r.returncode == 0, r.stderr
        trace = json.load(open(tmp_path / seq / "model_trace.json"))
        max_concurrent = max(
            sum(1 for sl in blk["slots"] if sl[0]) for blk in trace["blocks"])
        assert max_concurrent == 1, (
            f"{seq}: max_concurrent_voices={max_concurrent} -- if this ever "
            "becomes > 1, the shared-portamento-state negative control "
            "should now DISCRIMINATE and reports/SXT-043/EVIDENCE.md's "
            "'recorded coverage gap' note needs updating, not just this test")


# --------------------------------------------------- RTL comparator (no iverilog)
def _slot_line(b, slot, fields):
    return f"T {b} {slot} " + " ".join(str(int(x)) for x in fields)


def test_comparator_detects_a_single_field_mismatch():
    active_slot = [1] + [0] * len(pm.STATE_WORD_ORDER)
    inactive_slot = [0] * (1 + len(pm.STATE_WORD_ORDER))
    trace = {"pool": pm.MonoStFpScene.POOL, "blocks": [{"b": 0, "slots":
                        [active_slot] + [inactive_slot] * (pm.MonoStFpScene.POOL - 1)}]}
    lines = [_slot_line(0, 0, active_slot)] + [
        _slot_line(0, s, inactive_slot) for s in range(1, pm.MonoStFpScene.POOL)]
    good = "\n".join(lines) + "\n"
    checked, fails, pool = compare(trace, parse_tb_text(good))
    assert not fails
    assert checked["block_slot_checkpoints"] == pm.MonoStFpScene.POOL
    assert pool == pm.MonoStFpScene.POOL

    bad_lines = list(lines)
    bad_lines[0] = bad_lines[0][:-1] + "1"   # flip the last field (doretrigger) 0 -> 1
    bad = "\n".join(bad_lines) + "\n"
    _, fails, _ = compare(trace, parse_tb_text(bad))
    assert len(fails) == 1
    assert FIELD_NAMES[-1] in fails[0]


def parse_tb_text(text):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return parse_tb(path)
    finally:
        os.unlink(path)


def test_comparator_flags_a_missing_rtl_line():
    active_slot = [1] + [0] * len(pm.STATE_WORD_ORDER)
    inactive_slot = [0] * (1 + len(pm.STATE_WORD_ORDER))
    trace = {"pool": pm.MonoStFpScene.POOL, "blocks": [{"b": 0, "slots":
                        [active_slot] + [inactive_slot] * (pm.MonoStFpScene.POOL - 1)}]}
    _, fails, _ = compare(trace, {})
    assert any("missing T line" in f for f in fails)


# ------------------------------------------- harness reporting boundary (#645)
#
# The simulator is STUBBED (rcc.subprocess replaced) -- what is under test is
# the report assembly the leaf now shares, not the compile/run step (owned by
# tests/test_rtl_compile_common.py) and not the RTL.  The real-toolchain
# measurements behind these controls are in the module docstring.

REPORT_KEY_ORDER = ["tb", "carrier", "sequence", "pool", "verdict",
                    "comparison", "checked", "mismatches", "first_failures",
                    "rtl_done_line", "sim_fails", "sim_stdout_tail"]
COMMITTED_KEY_ORDER = [k for k in REPORT_KEY_ORDER
                       if k not in ("comparison", "sim_fails",
                                    "sim_stdout_tail")]

HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_pm_mono_st_fp.sv:249: $readmemh(rtl/init.hex):"
    " Not enough words in the file for the requested range [0:31].\n"
    "WARNING: %s/rtl/voice/tb_pm_mono_st_fp.sv:250: $readmemh(rtl/ev.hex):"
    " Not enough words in the file for the requested range [0:32767].\n"
    "DONE pm-qmuls=5148 voice-blocks=4392\n"
    "%s/rtl/voice/tb_pm_mono_st_fp.sv:290: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO))

FIXTURE_TRACE = {"carrier": "fixture", "sequence": "fixture-seq", "pool": 1,
                 "blocks": [{"b": 0, "slots": [[0] * len(FIELD_NAMES)]}]}
MATCHING_TRACE = "T 0 0 " + " ".join(["0"] * len(FIELD_NAMES)) + "\n"
MISMATCHING_TRACE = "T 0 0 " + " ".join(["1"] + ["0"] * (len(FIELD_NAMES) - 1)) + "\n"


def _write_run_dir(tmp_path):
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(FIXTURE_TRACE, f)
    os.makedirs(os.path.join(run_dir, "rtl"), exist_ok=True)
    for rel in pm_harness.STIMULUS_RELPATHS:
        open(os.path.join(run_dir, rel), "w").close()
    return run_dir


def _stub_simulator(monkeypatch, run_dir, sim_rc, trace_text, sim_stdout="",
                    calls=None):
    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd[0])
        if cmd[0] == "iverilog":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if trace_text is not None:
            with open(os.path.join(run_dir, "tb_pm_trace.txt"), "w") as f:
                f.write(trace_text)
        rc, err = sim_rc, ("vvp: simulated failure" if sim_rc else "")
        return types.SimpleNamespace(returncode=rc, stdout=sim_stdout,
                                     stderr=err)

    monkeypatch.setattr(rcc, "subprocess",
                        types.SimpleNamespace(
                            run=fake_run, DEVNULL=subprocess.DEVNULL,
                            CalledProcessError=subprocess.CalledProcessError,
                            TimeoutExpired=subprocess.TimeoutExpired))


def _delegating_simulator(monkeypatch, substitutions, calls):
    def real_run(cmd, **kwargs):
        calls.append(cmd[0])
        return subprocess.run(substitutions.get(cmd[0], cmd), **kwargs)

    monkeypatch.setattr(rcc, "subprocess",
                        types.SimpleNamespace(
                            run=real_run, DEVNULL=subprocess.DEVNULL,
                            CalledProcessError=subprocess.CalledProcessError,
                            TimeoutExpired=subprocess.TimeoutExpired))


def _run_harness(monkeypatch, run_dir, out=None, extra=()):
    out = out or os.path.join(run_dir, "verdict.json")
    monkeypatch.setattr(sys, "argv",
                        ["compare_pm_rtl_model.py", "--run-dir", run_dir,
                         "--out", out] + list(extra))
    rc = pm_harness.main()
    with open(out) as f:
        return rc, json.load(f)


def test_committed_report_keys_keep_their_order_with_additive_keys(
        tmp_path, monkeypatch):
    """`reports/SXT-043/artifacts/exactness-*.json` reports `carrier` /
    `sequence` / `pool` after `tb` and `rtl_done_line` after
    `first_failures`.  The shared skeleton must not re-order or drop any of
    them, and the three keys it adds must be additive."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)
    out = os.path.join(run_dir, "verdict.json")

    rc, d = _run_harness(monkeypatch, run_dir, out=out)

    assert rc == 0
    with open(out) as f:
        order = [k for k, _ in json.loads(
            f.read(), object_pairs_hook=lambda ps: ps)]
    assert order == REPORT_KEY_ORDER
    assert [k for k in order if k in COMMITTED_KEY_ORDER] \
        == COMMITTED_KEY_ORDER
    assert d["tb"] == "rtl/voice/tb_pm_mono_st_fp.sv"
    assert d["carrier"] == "fixture"
    assert d["sequence"] == "fixture-seq"
    assert d["pool"] == 1
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 0
    assert d["checked"] == {"block_slot_checkpoints": 1,
                            "fields": len(FIELD_NAMES)}


def test_rtl_done_line_is_the_full_string_not_a_count(tmp_path, monkeypatch):
    """`rtl_done_line` is the whole `DONE ...` line in committed evidence
    ("DONE pm-qmuls=5148 voice-blocks=4392").  Routing it through
    `compile_and_run`'s `done_prefix` would publish `int(...)` instead and
    silently change the field's type."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    _, d = _run_harness(monkeypatch, run_dir)

    assert d["rtl_done_line"] == "DONE pm-qmuls=5148 voice-blocks=4392"


def test_missing_stimulus_is_not_run_not_a_disagreement(tmp_path,
                                                        monkeypatch):
    """#188's blind-spot row, measured live before #645 (module docstring):
    removing `rtl/ev.hex` still yielded a trace of 74,400 `T` rows from the
    stimulus-less run; the old harness graded that output as a real render
    -- 24 checkpoints, 384 fields and 42 mismatches counted before the
    comparator stopped -- and published a numeric FAIL.  Zero coverage is
    what the migrated harness's refusal reports: it must reject the input
    before the simulator is even invoked."""
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "rtl/ev.hex"))
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/ev.hex" in d["sim_fails"][0]
    assert d["checked"] == {"block_slot_checkpoints": 0, "fields": 0}
    assert calls == [], calls
    assert d["rtl_done_line"] == ""


def test_compile_failure_replaces_a_stale_pass(tmp_path, monkeypatch):
    """The second live-measured row: before #645 an uncompilable `--tb`
    over an `--out` holding a PASS left that stale PASS in place after a
    traceback.  The stale verdict must be invalidated and a current NOT_RUN
    refusal published in its place."""
    run_dir = _write_run_dir(tmp_path)
    out = os.path.join(run_dir, "verdict.json")
    with open(out, "w") as f:
        json.dump({"verdict": "PASS", "mismatches": 0}, f)
    calls = []
    _delegating_simulator(
        monkeypatch,
        {"iverilog": ["sh", "-c", "echo 'syntax error' >&2; exit 2"]}, calls)

    rc, d = _run_harness(monkeypatch, run_dir, out=out)

    assert calls == ["iverilog"], calls
    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "iverilog compile failed rc=2" in d["sim_fails"][0]
    with open(out) as f:
        assert json.load(f) == d          # stale PASS is gone


def test_healthy_stdout_diagnostics_do_not_flip_a_pass(tmp_path, monkeypatch):
    """FALSE-POSITIVE control (issue #188's guardrail), measured for THIS
    testbench's own diagnostics -- see the module docstring.  A matcher that
    turns a genuinely passing exactness run into a FAIL is worse than the
    lost reason it recovers."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""


def test_slots_shape_refusal_before_the_simulator(tmp_path, monkeypatch):
    """A `voices`-shaped model trace must be refused by THIS leaf (the
    reciprocal of the six `voices` leaves refusing `slots`), before the
    simulator is launched."""
    run_dir = _write_run_dir(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump({"blocks": [{"b": 0, "voices": [{"slot": 0}]}]}, f)
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert calls == [], calls
    assert d["comparison"] == "NOT_RUN"
    assert d["input_error"] == {
        "input": "model",
        "path": os.path.join(run_dir, "model_trace.json"),
        "reason": "blocks[0].slots is not a list of per-slot field lists",
    }
    assert d["carrier"] is None and d["rtl_done_line"] is None, d
