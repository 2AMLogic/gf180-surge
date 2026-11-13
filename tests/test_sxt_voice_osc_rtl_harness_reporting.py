"""Voice- and oscillator-leaf RTL harness reporting controls (#634).

One table-parametrized battery for the five leaves whose harness-reporting
controls were previously five separately-typed copies of the same seven
tests (issue #634):

  * `tools/compare_classic_rtl_model.py` (SXT-033, #208, decomposing #201)
  * `tools/compare_sine_rtl_model.py`    (SXT-040, #208, decomposing #201)
  * `tools/compare_kt_rtl_model.py`      (SXT-042, #193/#207)
  * `tools/compare_mw_rtl_model.py`      (SXT-035, #193/#207)
  * `tools/compare_lfo_rtl_model.py`     (SXT-032, #193/#207)

All five were migrated to the shared
`tools/_rtl_compile_common.compile_and_run` helper's opt-in
`report_sim_fails=True` / `stimulus_files=...` mode (issue #193's
re-enumeration of the #188 blind spot: a `$readmemh` target that fails to
open is reported by Icarus on the simulation's STDOUT -- on three of these
five leaves while `vvp` still exits 0 -- so `check=True` alone never sees
it, and the harness's own comparison goes on to read an empty/partial trace
as though it were a genuine RTL-vs-model disagreement).

Because they share one reporting contract, the battery is parametrized over
the leaf rather than copied five times, the layout
`tests/test_lowpass_rtl_harness_reporting.py` already uses for lp12/lp24/
lpmoog. Everything that differs per leaf -- module, stimulus file to remove,
measured stdout strings, model trace, trace shape, and the exact
`checked[...]` / verdict-field assertions each leaf's own control made --
lives in `LEAVES` below, next to that leaf's provenance note. This is a
test-layout change only: it removes no case and loosens no assertion.

The simulator is STUBBED here (no iverilog, no vvp) -- these are
reporting-path controls only, **not** evidence about the RTL, the frozen
model, or their agreement. The model traces are synthesized to agree (or to
disagree by exactly one field) with whatever trace the stub produced; they
establish only that a simulator-level failure is reported as one, and that a
real comparison disagreement is still reported as a disagreement. Claim (1),
RTL-vs-frozen-model exactness, is decided by each leaf's own SXT exactness
run against real oracle-derived stimulus, untouched here.

The per-leaf `READMEMH_STDOUT` / `HEALTHY_STDOUT` strings below are real
Icarus 13.0 measurements retained from the issues that migrated each leaf
(#207 for kt/mw/lfo, #208 for classic/sine); see each row's note. They are
frozen inputs to the stubbed false-positive control, not live measurements:
`tests/test_lowpass_rtl_harness_reporting.py` re-measures the equivalent
strings against the real testbenches when `iverilog`/`vvp` are present.

The sine leaf additionally has a `--trace` reuse path that skips the
simulator entirely; its two controls are not parametrized and sit at the end
of this file.
"""

import importlib
import json
import os
import subprocess
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import _rtl_compile_common as rcc  # noqa: E402


# ----------------------------------------------------------------- classic
# SXT-033, issue #208 evidence. Both strings measured against this repo's
# Icarus 13.0: with `rtl/ctrl.hex` removed from an otherwise-complete run
# dir, rc=0, one ERROR line, and the testbench's own DONE/$finish sequence
# runs anyway; with the committed fixtures present, only Icarus's
# `$readmemh(...): Not enough words...` WARNING (the committed `ctrl.hex`
# fixture is deliberately shorter than the testbench's declared memory
# range) plus DONE/$finish -- never the `$readmem`+`Unable to open`
# conjunction this matcher looks for.
CLASSIC_TB_REL = "rtl/oscillators/classic/tb_classic.sv"

CLASSIC_SIM_STDERR = \
    "vvp: tb.vvp: simulated simulator failure (no rtl/ctrl.hex)"

CLASSIC_READMEMH_STDOUT = (
    "ERROR: %s/%s:153: $readmemh: Unable to open rtl/ctrl.hex for "
    "reading.\nDONE qmuls=76800 blocks=96\n%s/%s:162: $finish called at 0 "
    "(1ps)\n" % (REPO, CLASSIC_TB_REL, REPO, CLASSIC_TB_REL))

CLASSIC_HEALTHY_STDOUT = (
    "WARNING: %s/%s:153: $readmemh(rtl/ctrl.hex): Not enough words in the "
    "file for the requested range [0:4200000].\nDONE qmuls=135110 "
    "blocks=96\n%s/%s:162: $finish called at 0 (1ps)\n"
    % (REPO, CLASSIC_TB_REL, REPO, CLASSIC_TB_REL))


def _classic_model(mod):
    return {
        "n_unison": 1,
        "blocks": [{
            "b": 0,
            "mono_block": [100, -200, 300],
            "voices": [{
                "slot": 0, "oscout_block": [1, 2, 3],
                "after": {
                    "aeg": {"state": 1, "phase": 4, "output": 5},
                    "l_shape": 6, "l_pw": 7, "l_pw2": 8, "l_sub": 9,
                    "l_sync": 10, "dc": 11, "osc_out": 12, "osc_out2": 13,
                    "bufpos": 0, "hpf_prev": 14, "gain_end": 15,
                    "oscstate": [16], "syncstate": [17], "state": [18],
                    "last_level": [19], "pwidth": [20], "pwidth2": [21],
                    "dc_uni": [22],
                },
            }],
        }],
    }


def _classic_t_line(mod, overrides):
    """Build a `T` line in `mod.T_FIELDS` order -- shields this fixture from
    a field-order/count change in the harness (which would otherwise need a
    parallel hand-counted edit here)."""
    d = {f: 0 for f in mod.T_FIELDS}
    d.update(overrides)
    vals = [d[f] for f in mod.T_FIELDS]
    return "T " + " ".join(str(v) for v in vals)


def _classic_matching(mod):
    return (
        _classic_t_line(mod, {
            "b": 0, "slot": 0, "key": 60, "aeg_state": 1, "aeg_phase": 4,
            "aeg_out": 5, "n_unison": 1,
            "u0_oscstate": 16, "u0_syncstate": 17, "u0_state": 18,
            "u0_last_level": 19, "u0_pwidth": 20, "u0_pwidth2": 21,
            "u0_dc_uni": 22,
            "l_shape": 6, "l_pw": 7, "l_pw2": 8, "l_sub": 9, "l_sync": 10,
            "dc": 11, "osc_out": 12, "osc_out2": 13, "bufpos": 0,
            "hpf_prev": 14, "gain_end": 15,
        }) + "\n"
        "O 0 0 1 2 3\n"
        "M 0 100\nM 0 -200\nM 0 300\n")


def _classic_mismatching(mod):
    return _classic_matching(mod).replace("M 0 100", "M 0 101", 1)


# -------------------------------------------------------------------- sine
# SXT-040, issue #208 evidence. Measured against this repo's Icarus 13.0,
# same two conditions and the same reading as the classic rows above: the
# missing-`rtl/ctrl.hex` repro exits 0 with one ERROR line on stdout, and a
# healthy run emits only the size-mismatch WARNING plus DONE/$finish.
SINE_TB_REL = "rtl/oscillators/sine/tb_sine.sv"

SINE_SIM_STDERR = "vvp: tb.vvp: simulated simulator failure (no rtl/ctrl.hex)"

SINE_READMEMH_STDOUT = (
    "ERROR: %s/%s:172: $readmemh: Unable to open rtl/ctrl.hex for "
    "reading.\nDONE qmuls=76800 blocks=2017659\n%s/%s:181: $finish called "
    "at 0 (1ps)\n" % (REPO, SINE_TB_REL, REPO, SINE_TB_REL))

SINE_HEALTHY_STDOUT = (
    "WARNING: %s/%s:172: $readmemh(rtl/ctrl.hex): Not enough words in the "
    "file for the requested range [0:4200000].\nDONE qmuls=279570 "
    "blocks=2017659\n%s/%s:181: $finish called at 0 (1ps)\n"
    % (REPO, SINE_TB_REL, REPO, SINE_TB_REL))


def _sine_model(mod):
    return {
        "n_unison": 1,
        "legacy": False,
        "blocks": [{
            "b": 0,
            "mono_block": [100, -200, 300],
            "voices": [{
                "slot": 0, "oscout_block": [1, 2, 3],
                "after": {
                    "aeg": {"state": 1, "phase": 4, "output": 5},
                    "fb_v": 6, "fm_v": 7, "firstblock": 1,
                    "hp_r0": 8, "hp_r1": 9, "lp_r0": 10, "lp_r1": 11,
                    "char_py": 12, "char_px": 13, "gain_end": 14,
                    "prior_valid": 1,
                    "phase": [15], "lv0": [16], "lv1": [17],
                    "om_prior": [18],
                },
            }],
        }],
    }


def _sine_t_line(mod, b, s, key, legacy, nuni, aeg_state, aeg_phase, aeg_out,
                 u_values, prior_valid=None):
    """Modern (non-legacy) `T` line: b s key legacy nuni aeg_state aeg_phase
    aeg_out, then MAXUNI groups of MODERN_U_FIELDS (phase lv0 lv1 om_prior),
    then prior_valid -- mirrors `parse_tb`'s modern-branch layout exactly."""
    vals = [b, s, key, int(legacy), nuni, aeg_state, aeg_phase, aeg_out]
    for u in range(mod.MAXUNI):
        vals += list(u_values.get(u, (0, 0, 0, 0)))
    vals.append(0 if prior_valid is None else prior_valid)
    return "T " + " ".join(str(v) for v in vals)


def _sine_s_line(b, s, fb_v, fm_v, firstblock, hp_r0, hp_r1, lp_r0, lp_r1,
                 char_py, char_px):
    vals = [b, s, fb_v, fm_v, firstblock, hp_r0, hp_r1, lp_r0, lp_r1,
            char_py, char_px]
    return "S " + " ".join(str(v) for v in vals)


def _sine_g_line(b, s, gain):
    return "G %d %d %d" % (b, s, gain)


def _sine_matching(mod):
    return (
        _sine_t_line(mod, 0, 0, 60, False, 1, 1, 4, 5, {0: (15, 16, 17, 18)},
                     prior_valid=1) + "\n"
        + _sine_s_line(0, 0, 6, 7, 1, 8, 9, 10, 11, 12, 13) + "\n"
        + _sine_g_line(0, 0, 14) + "\n"
        "O 0 0 1 2 3\n"
        "M 0 100\nM 0 -200\nM 0 300\n")


def _sine_mismatching(mod):
    return _sine_matching(mod).replace("M 0 100", "M 0 101", 1)


# ---------------------------------------------------------------------- kt
# SXT-042, issue #207 evidence, from a real Icarus 13.0 run against a
# genuine run dir built by
# `model/voice/run_kt_model.py --sequence sxt025-accept-v1`:
#   * healthy run: two `$readmemh(...): Not enough words...` WARNINGs (this
#     repo's committed hex fixtures are deliberately shorter than the
#     testbench's declared memory ranges), the `DONE kt-qmuls=...` marker
#     and `$finish` -- never the `$readmem`+`Unable to open` conjunction.
#   * `rtl/kt_ctrl.hex` removed: Icarus prints the ERROR on stdout, then
#     this leaf's testbench also FATALs on the exhausted ctrl stream and
#     `vvp` exits 1 (unlike `lfo`, this one does not race ahead with rc=0 --
#     but the missing-input pre-flight check fires before the simulator is
#     ever invoked either way, so that distinction does not matter to the
#     harness). Hence `readmemh_rc=1` and two reported `sim_fails` entries
#     (the non-zero exit and the stdout scan), which is why this leaf's own
#     control asserted "at least one" rather than exactly one.
KT_SIM_STDERR = \
    "vvp: tb_kt.vvp: simulated simulator failure (no rtl/kt_ctrl.hex)"

KT_READMEMH_STDOUT = (
    "WARNING: %s/rtl/voice/tb_kt.sv:92: $readmemh(rtl/kt_routes.hex): Not "
    "enough words in the file for the requested range [0:191].\n"
    "ERROR: %s/rtl/voice/tb_kt.sv:93: $readmemh: Unable to open "
    "rtl/kt_ctrl.hex for reading.\n"
    "FATAL: %s/rtl/voice/tb_kt.sv:119: kt ctrl stream exhausted at block 0\n"
    "       Time: 0  Scope: tb_kt.run\n" % (REPO, REPO, REPO))

KT_HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_kt.sv:92: $readmemh(rtl/kt_routes.hex): Not "
    "enough words in the file for the requested range [0:191].\n"
    "WARNING: %s/rtl/voice/tb_kt.sv:93: $readmemh(rtl/kt_ctrl.hex): Not "
    "enough words in the file for the requested range [0:1999999].\n"
    "DONE kt-qmuls=180126\n"
    "%s/rtl/voice/tb_kt.sv:112: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO))


def _kt_model(mod):
    return {
        "sequence": "test-seq",
        "control_mode": "normal",
        "blocks": [{
            "b": 0,
            "voices": [{
                "slot": 0,
                "kt_word": 100,
                "kt_route_sums": [10, 20, 30],
                "mod_cutoff": 1, "mod_reso": 2, "mod_envmod": 3,
                "mod_vca_db": 4,
            }],
        }],
    }


def _kt_matching(mod):
    return "V 0 0 100 10 20 30 1 2 3 4\n"


def _kt_mismatching(mod):
    return "V 0 0 101 10 20 30 1 2 3 4\n"


# ---------------------------------------------------------------------- mw
# SXT-035, issue #207 evidence, from a real Icarus 13.0 run against a
# genuine run dir built by
# `model/voice/run_mw_model.py --sequence seq-modwheel-v1`. Same two
# conditions and the same rc=1 FATAL-on-exhausted-ctrl-stream reading as the
# kt rows above.
MW_SIM_STDERR = \
    "vvp: tb_mw.vvp: simulated simulator failure (no rtl/mw_ctrl.hex)"

MW_READMEMH_STDOUT = (
    "WARNING: %s/rtl/voice/tb_mw.sv:85: $readmemh(rtl/mw_routes.hex): Not "
    "enough words in the file for the requested range [0:63].\n"
    "ERROR: %s/rtl/voice/tb_mw.sv:86: $readmemh: Unable to open "
    "rtl/mw_ctrl.hex for reading.\n"
    "FATAL: %s/rtl/voice/tb_mw.sv:105: mw ctrl stream exhausted at block 0\n"
    "       Time: 0  Scope: tb_mw.run\n" % (REPO, REPO, REPO))

MW_HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_mw.sv:85: $readmemh(rtl/mw_routes.hex): Not "
    "enough words in the file for the requested range [0:63].\n"
    "WARNING: %s/rtl/voice/tb_mw.sv:86: $readmemh(rtl/mw_ctrl.hex): Not "
    "enough words in the file for the requested range [0:1200000].\n"
    "DONE mw-qmuls=11244\n"
    "%s/rtl/voice/tb_mw.sv:95: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO))


def _mw_model(mod):
    return {
        "blocks": [{
            "b": 0,
            "mw_value": 500,
            "voices": [{"slot": 0, "mw_route_sums": [1, 2, 3]}],
        }],
    }


def _mw_matching(mod):
    return "S 0 0 1 2 3\nM 0 500\n"


def _mw_mismatching(mod):
    return "S 0 0 1 2 3\nM 0 501\n"


# --------------------------------------------------------------------- lfo
# SXT-032, issue #207 evidence, from a real Icarus 13.0 run against a
# genuine run dir built by
# `model/voice/run_lfo_model.py --sequence seq-notes-repeated-v1`:
#   * healthy run: `$readmemh(...): Too many/Not enough words...` WARNINGs
#     (this repo's committed hex fixtures deliberately differ in size from
#     the testbench's declared memory ranges), the `DONE lfo-qmuls=...`
#     marker and `$finish` -- never the `$readmem`+`Unable to open`
#     conjunction.
#   * `rtl/lfo_ctrl.hex` removed: Icarus prints the ERROR on stdout and
#     `vvp` still **exits 0**, `$finish`-ing normally -- the exact #188/#193
#     blind spot, genuinely reproduced on this leaf (unlike `kt`/`mw`, this
#     testbench does not FATAL on the empty control memory, so `check=True`
#     alone truly cannot see the failure without the pre-flight
#     `stimulus_files` check or the stdout scan). Hence `readmemh_rc=0` and
#     the `rc=0` substring this leaf's control requires.
LFO_SIM_STDERR = ("vvp: tb_lfo.vvp: simulated simulator failure "
                  "(no rtl/lfo_ctrl.hex)")

LFO_READMEMH_STDOUT = (
    "WARNING: %s/rtl/voice/tb_lfo.sv:88: $readmemh(rtl/init.hex): Too many "
    "words in the file for the requested range [0:39].\n"
    "WARNING: %s/rtl/voice/tb_lfo.sv:90: $readmemh(rtl/lfo_routes.hex): Not "
    "enough words in the file for the requested range [0:63].\n"
    "ERROR: %s/rtl/voice/tb_lfo.sv:92: $readmemh: Unable to open "
    "rtl/lfo_ctrl.hex for reading.\n"
    "DONE lfo-qmuls=98400\n"
    "%s/rtl/voice/tb_lfo.sv:98: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO, REPO))

LFO_HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_lfo.sv:88: $readmemh(rtl/init.hex): Too many "
    "words in the file for the requested range [0:39].\n"
    "WARNING: %s/rtl/voice/tb_lfo.sv:90: $readmemh(rtl/lfo_routes.hex): Not "
    "enough words in the file for the requested range [0:63].\n"
    "WARNING: %s/rtl/voice/tb_lfo.sv:92: $readmemh(rtl/lfo_ctrl.hex): Not "
    "enough words in the file for the requested range [0:4200000].\n"
    "DONE lfo-qmuls=13592\n"
    "%s/rtl/voice/tb_lfo.sv:98: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO, REPO))


def _lfo_model(mod):
    return {
        "blocks": [{
            "b": 0,
            "voices": [{
                "slot": 0,
                "lfo": [{"index": 0, "phase": 10, "env_state": 1,
                         "env_phase": 2, "env_val": 3, "output": 4}],
                "lfo_route_sums": [5, 6],
            }],
        }],
    }


def _lfo_matching(mod):
    return "L 0 0 0 10 1 2 3 4\nS 0 0 5 6\n"


def _lfo_mismatching(mod):
    return "L 0 0 0 11 1 2 3 4\nS 0 0 5 6\n"


# ------------------------------------------------------------------- table
class Leaf:
    """One leaf's data for the shared battery below.

    Every field is data consumed identically by every parametrized case --
    no test body branches on the leaf (issue #634's stop/escalate
    condition). The assertion-shaped fields carry exactly what that leaf's
    own control file asserted:

      pass_checked / pass_checked_positive
          `checked[...]` keys the agreeing-trace control pinned to an exact
          value, and those it only required to be > 0.
      pass_fields / missing_fields
          top-level verdict keys that control pinned (kt's `rtl_qmuls`).
      zero_checked
          the `checked[...]` keys both no-comparison controls pinned to 0.
      readmemh_fail_count
          exact `sim_fails` length where the leaf's control pinned one
          (classic/sine/lfo), or None where it only required a non-empty
          list because the leaf reports two entries (kt/mw, see their notes).
      readmemh_fail_substrings
          substrings that control required in the reported `sim_fails`.
    """

    def __init__(self, name, module, script, trace_name, sim_stderr,
                 readmemh_stdout, healthy_stdout, model, matching,
                 mismatching, missing_rel, absent_first_failure,
                 mismatch_field, pass_checked, zero_checked,
                 readmemh_rc, readmemh_fail_count, readmemh_fail_substrings,
                 pass_checked_positive=(), pass_fields=None,
                 missing_fields=None, pass_shows_healthy_stdout=False):
        self.name = name
        self.module = module
        self.script = script                 # argv[0] the harness sees
        self.trace_name = trace_name         # trace file the stub writes
        self.sim_stderr = sim_stderr
        self.readmemh_stdout = readmemh_stdout
        self.healthy_stdout = healthy_stdout
        self.model = model                   # (mod) -> model_trace dict
        self.matching = matching             # (mod) -> agreeing trace text
        self.mismatching = mismatching       # (mod) -> disagreeing trace
        self.missing_rel = missing_rel       # stimulus file to remove
        self.absent_first_failure = absent_first_failure
        self.mismatch_field = mismatch_field
        self.pass_checked = pass_checked
        self.pass_checked_positive = pass_checked_positive
        self.pass_fields = pass_fields or {}
        self.missing_fields = missing_fields or {}
        self.zero_checked = zero_checked
        self.readmemh_rc = readmemh_rc
        self.readmemh_fail_count = readmemh_fail_count
        self.readmemh_fail_substrings = readmemh_fail_substrings
        self.pass_shows_healthy_stdout = pass_shows_healthy_stdout

    @property
    def pass_stdout(self):
        """Stub stdout for the agreeing-trace control.

        kt/mw/lfo's own control fed the healthy string there (which is how
        kt observed its `rtl_qmuls`); classic/sine's fed nothing. The
        dedicated false-positive control below feeds the healthy string for
        every leaf regardless.
        """
        return self.healthy_stdout if self.pass_shows_healthy_stdout else ""

    def __repr__(self):
        return self.name


LEAVES = [
    Leaf("classic", "tools.compare_classic_rtl_model",
         "compare_classic_rtl_model.py", "tb_trace.txt",
         CLASSIC_SIM_STDERR, CLASSIC_READMEMH_STDOUT, CLASSIC_HEALTHY_STDOUT,
         _classic_model, _classic_matching, _classic_mismatching,
         "rtl/ctrl.hex", "missing T line", "sample",
         pass_checked={"mono": 3}, pass_checked_positive=("fields",),
         zero_checked={"fields": 0},
         readmemh_rc=0, readmemh_fail_count=1,
         readmemh_fail_substrings=("rtl/ctrl.hex", "rc=0")),
    Leaf("sine", "tools.compare_sine_rtl_model",
         "compare_sine_rtl_model.py", "tb_trace.txt",
         SINE_SIM_STDERR, SINE_READMEMH_STDOUT, SINE_HEALTHY_STDOUT,
         _sine_model, _sine_matching, _sine_mismatching,
         "rtl/ctrl.hex", "missing T line", "sample",
         pass_checked={"mono": 3}, pass_checked_positive=("fields",),
         zero_checked={"fields": 0},
         readmemh_rc=0, readmemh_fail_count=1,
         readmemh_fail_substrings=("rtl/ctrl.hex", "rc=0")),
    Leaf("kt", "tools.compare_kt_rtl_model",
         "compare_kt_rtl_model.py", "tb_kt_trace.txt",
         KT_SIM_STDERR, KT_READMEMH_STDOUT, KT_HEALTHY_STDOUT,
         _kt_model, _kt_matching, _kt_mismatching,
         "rtl/kt_ctrl.hex", "missing V line", "kt_word",
         pass_checked={"voice_checkpoints": 1, "fields": 8},
         pass_fields={"rtl_qmuls": 180126},
         missing_fields={"rtl_qmuls": None},
         zero_checked={"fields": 0},
         readmemh_rc=1, readmemh_fail_count=None,
         readmemh_fail_substrings=("rtl/kt_ctrl.hex",),
         pass_shows_healthy_stdout=True),
    Leaf("mw", "tools.compare_mw_rtl_model",
         "compare_mw_rtl_model.py", "tb_mw_trace.txt",
         MW_SIM_STDERR, MW_READMEMH_STDOUT, MW_HEALTHY_STDOUT,
         _mw_model, _mw_matching, _mw_mismatching,
         "rtl/mw_ctrl.hex", "missing M line", "mw_value",
         pass_checked={"mw_values": 1, "route_sum_checkpoints": 1,
                       "route_sums": 3},
         zero_checked={"route_sums": 0},
         readmemh_rc=1, readmemh_fail_count=None,
         readmemh_fail_substrings=("rtl/mw_ctrl.hex",),
         pass_shows_healthy_stdout=True),
    Leaf("lfo", "tools.compare_lfo_rtl_model",
         "compare_lfo_rtl_model.py", "tb_lfo_trace.txt",
         LFO_SIM_STDERR, LFO_READMEMH_STDOUT, LFO_HEALTHY_STDOUT,
         _lfo_model, _lfo_matching, _lfo_mismatching,
         "rtl/lfo_ctrl.hex", "missing L line", "phase",
         pass_checked={"lfo_checkpoints": 1, "lfo_fields": 5,
                       "route_sums": 1},
         zero_checked={"lfo_fields": 0},
         readmemh_rc=0, readmemh_fail_count=1,
         readmemh_fail_substrings=("rtl/lfo_ctrl.hex", "rc=0"),
         pass_shows_healthy_stdout=True),
]

LEAF_IDS = [leaf.name for leaf in LEAVES]


@pytest.fixture(params=LEAVES, ids=LEAF_IDS)
def leaf(request):
    return request.param


def _leaf(name):
    """The one row named `name` -- for a leaf-specific control below."""
    found = [lf for lf in LEAVES if lf.name == name]
    assert len(found) == 1, name
    return found[0]


# --------------------------------------------------------------- machinery
def _mod(leaf):
    mod = importlib.import_module(leaf.module)
    return importlib.reload(mod)  # a clean module object per test


def _write_run_dir(leaf, mod, tmp_path):
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(leaf.model(mod), f)
    os.makedirs(os.path.join(run_dir, "rtl"), exist_ok=True)
    for rel in mod.STIMULUS_RELPATHS:
        open(os.path.join(run_dir, rel), "w").close()
    return run_dir


def _stub_simulator(leaf, monkeypatch, run_dir, sim_rc, trace_text,
                    sim_stdout="", calls=None):
    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd[0])
        if cmd[0] == "iverilog":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if trace_text is not None:
            with open(os.path.join(run_dir, leaf.trace_name), "w") as f:
                f.write(trace_text)
        return types.SimpleNamespace(
            returncode=sim_rc, stdout=sim_stdout,
            stderr=(leaf.sim_stderr if sim_rc else ""))

    monkeypatch.setattr(rcc, "subprocess", types.SimpleNamespace(
        run=fake_run, DEVNULL=subprocess.DEVNULL,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired))


def _delegating_simulator(monkeypatch, substitutions, calls):
    def real_run(cmd, **kwargs):
        calls.append(cmd[0])
        return subprocess.run(substitutions.get(cmd[0], cmd), **kwargs)

    monkeypatch.setattr(rcc, "subprocess", types.SimpleNamespace(
        run=real_run, DEVNULL=subprocess.DEVNULL,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired))


def _run_harness(leaf, mod, monkeypatch, run_dir, extra=()):
    out = os.path.join(run_dir, "verdict.json")
    if os.path.exists(out):
        os.remove(out)
    monkeypatch.setattr(sys, "argv",
                        [leaf.script, "--run-dir", run_dir, "--out", out]
                        + list(extra))
    rc = mod.main()
    with open(out) as f:
        return rc, json.load(f)


def _assert_checked(d, exact, positive=()):
    for key, value in exact.items():
        assert d["checked"][key] == value, (key, d["checked"])
    for key in positive:
        assert d["checked"][key] > 0, (key, d["checked"])


def _assert_fields(d, expected):
    for key, value in expected.items():
        assert d[key] == value, (key, d)


def _assert_sim_fails(sim_fails, count):
    """`count` is an exact length, or None for "at least one".

    None is used only where the leaf's own control asserted a non-empty list
    rather than a length, because that leaf reports more than one entry --
    see the kt/mw notes above. It never relaxes a length a leaf did pin.
    """
    assert sim_fails, sim_fails
    if count is not None:
        assert len(sim_fails) == count, sim_fails


# ---------------------------------------------------------------- regression
def test_agreeing_trace_still_passes(leaf, tmp_path, monkeypatch):
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    _stub_simulator(leaf, monkeypatch, run_dir, 0, leaf.matching(mod),
                    sim_stdout=leaf.pass_stdout)

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 0
    _assert_checked(d, leaf.pass_checked, leaf.pass_checked_positive)
    _assert_fields(d, leaf.pass_fields)


def test_comparison_mismatch_still_reported(leaf, tmp_path, monkeypatch):
    """A genuine RTL-vs-model disagreement must NOT be swallowed."""
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    _stub_simulator(leaf, monkeypatch, run_dir, 0, leaf.mismatching(mod))

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1
    assert leaf.mismatch_field in d["first_failures"][0]


# ------------------------------------------------------- the four mechanisms
def test_missing_stimulus_file_is_named_and_not_a_comparison_disagreement(
        leaf, tmp_path, monkeypatch):
    """issue #193/#208's failure control: delete exactly one declared hex
    file. The pre-flight check must name it and leave the comparison
    NOT_RUN, never report it as a disagreement."""
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    os.remove(os.path.join(run_dir, leaf.missing_rel))
    calls = []
    _stub_simulator(leaf, monkeypatch, run_dir, 0, leaf.matching(mod),
                    calls=calls)

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    _assert_sim_fails(d["sim_fails"], 1)
    assert leaf.missing_rel in d["sim_fails"][0]
    joined = "\n".join(d["first_failures"])
    assert leaf.absent_first_failure not in joined, joined
    _assert_checked(d, leaf.zero_checked)
    _assert_fields(d, leaf.missing_fields)
    assert calls == [], calls  # the simulator is never even invoked


def test_readmemh_open_failure_on_stdout_is_a_sim_failure(
        leaf, tmp_path, monkeypatch):
    """The #188 mechanism: Icarus reports the failed `$readmemh` open on
    STDOUT. On classic/sine/lfo `vvp` still exits 0, so `check=True` alone
    would never have caught it; on kt/mw the testbench also FATALs and `vvp`
    exits 1. Either way the harness must report a simulator-level failure
    and leave the comparison NOT_RUN."""
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    _stub_simulator(leaf, monkeypatch, run_dir, leaf.readmemh_rc, None,
                    sim_stdout=leaf.readmemh_stdout)

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    _assert_sim_fails(d["sim_fails"], leaf.readmemh_fail_count)
    joined = "\n".join(d["sim_fails"])
    for needle in leaf.readmemh_fail_substrings:
        assert needle in joined, (needle, joined)
    assert "$readmemh" in d["sim_stdout_tail"]
    _assert_checked(d, leaf.zero_checked)


def test_simulator_failure_is_reported_with_its_stderr(
        leaf, tmp_path, monkeypatch):
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    _stub_simulator(leaf, monkeypatch, run_dir, 4, leaf.matching(mod))

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    joined = "\n".join(d["sim_fails"])
    assert "vvp exited rc=4" in joined, joined
    assert leaf.sim_stderr in joined, joined


def test_compile_failure_is_recorded_instead_of_raising(
        leaf, tmp_path, monkeypatch):
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    calls = []
    _delegating_simulator(
        monkeypatch,
        {"iverilog": ["sh", "-c", "echo 'syntax error' >&2; exit 3"]}, calls)

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir)

    assert calls == ["iverilog"], calls
    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    _assert_sim_fails(d["sim_fails"], 1)
    assert "iverilog compile failed rc=3" in d["sim_fails"][0]


# -------------------------------------------------- false-positive guardrail
def test_healthy_stdout_diagnostics_do_not_flip_a_pass(
        leaf, tmp_path, monkeypatch):
    """FALSE-POSITIVE control (issue #188's guardrail, per leaf).

    A matcher that turns a genuinely passing exactness run into a FAIL is
    worse than the lost reason it recovers, so the benign size-mismatch
    WARNINGs each of these testbenches emits on a healthy run (measured per
    leaf -- see the rows above) must not trip it.
    """
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    _stub_simulator(leaf, monkeypatch, run_dir, 0, leaf.matching(mod),
                    sim_stdout=leaf.healthy_stdout)

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""


# --------------------------------------------------------- --trace reuse ---
# sine only. The `--trace` path skips `compile_and_run` entirely (it reuses
# an already-captured trace file), so it can never observe a simulator-level
# failure; these controls confirm the migration left that branch reporting
# `sim_fails: []` / a comparison-driven verdict, not a stale/missing field.

def test_trace_reuse_path_never_touches_the_simulator(tmp_path, monkeypatch):
    leaf = _leaf("sine")
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    trace_path = os.path.join(run_dir, "reused_trace.txt")
    with open(trace_path, "w") as f:
        f.write(leaf.matching(mod))
    calls = []
    _stub_simulator(leaf, monkeypatch, run_dir, 0, None, calls=calls)

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir,
                         extra=["--trace", trace_path])

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""
    assert calls == [], calls  # never invokes iverilog/vvp


def test_trace_reuse_path_still_reports_a_mismatch(tmp_path, monkeypatch):
    leaf = _leaf("sine")
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, mod, tmp_path)
    trace_path = os.path.join(run_dir, "reused_trace.txt")
    with open(trace_path, "w") as f:
        f.write(leaf.mismatching(mod))
    calls = []
    _stub_simulator(leaf, monkeypatch, run_dir, 0, None, calls=calls)

    rc, d = _run_harness(leaf, mod, monkeypatch, run_dir,
                         extra=["--trace", trace_path])

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert calls == [], calls
