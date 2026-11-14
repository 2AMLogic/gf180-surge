#!/usr/bin/env python3
"""Generate the committed copy-style RTL negative-control mutants (#620).

A copy-style mutant is a whole-file copy of the testbench it mutates,
differing from it by a banner plus a few exact lines. This script declares
each one as

    mutant = optional banner prefix + base source with the declared
             `old` -> `new` replacements applied

and `--check` exits non-zero if any committed mutant differs from what this
script would write, so a control cannot silently drift from the base it
mutates. That rule started in tools/make_sxt030_mutants.py, covering the four
rtl/instrumentation/ mutants; #620 applied it to the sixteen mutants that
were hand-maintained copies (or, for the two conditioner mutants,
regenerated in place by their own comparator with no committed-byte check),
and #623 folded the remaining five -- those four plus
rtl/control/control_broken_mutant.sv, which had no committed-byte check at
all -- onto this table, for twenty-one in total.

Each `old` must occur the declared number of times in the base (once unless a
count is given), so a replacement that no longer anchors is an error rather
than a silent no-op. No mutant is weakened or removed here: this script
reproduces the committed bytes of every file it lists.

This is the single definition for every mutant it lists (#623).
tools/compare_rtl_model_conditioner.py, tools/make_control_mutant.py and
tools/make_sxt030_mutants.py no longer carry mutation rules of their own:
they call into this table, so exactly one file decides what each committed
control contains instead of whichever generator ran last.

Two composition shapes are declared:

  plain     optional banner + the mutated base (sixteen entries)
  strip     a banner ending in its own `timescale line + the mutated base
            with that one timescale line removed (the five entries absorbed
            in #623: the four rtl/instrumentation/ mutants and
            rtl/control/control_broken_mutant.sv). This is how those files
            were already composed by their own generators; the fold changes
            no committed mutant byte.

KNOWN DRIFT (bounded finding, #620): rtl/voice/voice_broken_mutant.sv and
rtl/voice/voice_uni_mutant.sv carry, on top of their targeted mutation, three
hunks that revert the SXT-036 constructor gain-anchor logic their base
rtl/voice/tb_voice.sv now has. Those hunks are declared in `"stale"` so the
drift is pinned and reported rather than hidden -- they are NOT the mutation
each control targets, and these two files are not minimal mutants. They are
deliberately not regenerated here: new bytes would require re-deriving the
T1 item 9 attestation (signoff/t1-item9-attestation.json records each
mutant's content hash) and re-running both controls against the current base.
Nothing here claims either control currently fails for the right reason or
the wrong one; no comparator was run to produce this table.

Usage:
    python3 tools/make_rtl_mutants.py            # regenerate (no-op today)
    python3 tools/make_rtl_mutants.py --check     # drift gate, exits non-zero
    python3 tools/make_rtl_mutants.py --list      # print the table

Original to this repository (Apache-2.0).
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The three stale hunks shared by the two drifted rtl/voice/tb_voice.sv
# copies: each reverts SXT-036 constructor gain-anchor logic present in the
# base. Declared, not fixed -- see KNOWN DRIFT above.
SXT036_STALE = [
    ('  //  0 flags(b0 active,b1 ckpt,b2 created,b3 released,\n'
     '  //          b4 ctor gain anchor streamed in word 37 -- SXT-036)\n'
     '  //  1 key  2 gate\n',
     '  //  0 flags(b0 active,b1 ckpt,b2 created,b3 released)  1 key  2 gate\n'),
    ('  //  32 fvel 33 kt_word  34..36 sine omega1..3 (Q3.28)\n'
     '  //  37 ctor gain anchor (iff flags b4; SXT-036)  38..39 reserved\n',
     '  //  32 fvel 33 kt_word  34..36 sine omega1..3 (Q3.28)  37..39 reserved\n'),
    ('    // SXT-036: a per-voice modulation term on VCA Gain at construction\n'
     '    // (velocity -> VCA Gain) makes the SetQFB(0,0) gain anchor per-voice;\n'
     '    // the model streams it (declared control-plane word, slot word 37) and\n'
     '    // flags it with flags bit 4. Legacy stimuli never set bit 4 and keep the\n'
     '    // static cfg[19] anchor below (landed fixtures unchanged).\n'
     "    if (cw[0][4]) prev_gain[s] = 32'(cw[37]);\n"
     "    else          prev_gain[s] = qmul(32'(cfg[19]), aeg_out_r[s]);\n",
     "    prev_gain[s] = qmul(32'(cfg[19]), aeg_out_r[s]);\n"),
]

CONDITIONER_BANNER = (
    '// GENERATED negative-control mutant of tb_conditioner.sv by\n'
    '// tools/compare_rtl_model_conditioner.py -- must FAIL exactness.\n')

TIMESCALE = "`timescale 1ns/1ps\n"

# ---- SXT-021 (#538): rtl/control/control_broken_mutant.sv ---------------
# The banner is kept verbatim from tools/make_control_mutant.py, which wrote
# this file before the fold (#623, Work step 2: keep the banner, gain the
# --check gate). Retargeting the "Regenerate with" line would change an
# attested mutant's bytes for no behavioural gain, so it is deliberately not
# done here; tools/make_control_mutant.py stays as a shim over this entry.
CONTROL_MUTANT = "rtl/control/control_broken_mutant.sv"
CONTROL_BANNER = (
    "// SXT-021 COMMITTED NEGATIVE CONTROL (do not fix in place).\n"
    "//\n"
    "// Deliberately mutated copy of rtl/control/control_top.sv: the event-queue\n"
    "// depth constant is changed from 16 to 15 (one constant). The comparator\n"
    "// (tools/compare_control_rtl.py --dut <this file>) MUST FAIL against the\n"
    "// SXT-021 model: queue-overflow drop records and queue-count checkpoints\n"
    "// diverge (e.g. the 30-event burst fixture drops 14 words in the mutant vs\n"
    "// the model's 16-deep queue). If this file ever PASSES the comparator, the\n"
    "// comparator's divergence detection is broken and must be repaired before\n"
    "// any RTL-vs-model equality claim stands.\n"
    "//\n"
    "// Regenerate with: python3 tools/make_control_mutant.py\n"
    "\n" + TIMESCALE)

# ---- SXT-030 (#316): the four rtl/instrumentation/ mutants --------------
# Mutation sites in the real design. Each must occur exactly once; the
# entries below pin that, so a site that moved is an error, not a no-op.
EXT_MEM_BASE = "rtl/instrumentation/ext_mem_instr.sv"
EXT_MEM_DIR = "rtl/instrumentation"
EXT_MEM_HOLD = "{out_l, out_r} <= miss ? {out_l, out_r} : {smp_l, smp_r};"
EXT_MEM_SILENCE = "{out_l, out_r} <= miss ? 32'd0 : {smp_l, smp_r};"
EXT_MEM_COUNT = "wire stall_count = miss;"
EXT_MEM_NO_COUNT = "wire stall_count = 1'b0;"
EXT_MEM_LATCH = "win_l <= svc_window;"
EXT_MEM_NO_LATCH = "win_l <= SVC_WINDOW_NOMINAL;"
EXT_MEM_RUNS = ("tools/sxt030_stall_bench.py "
                "(tests/test_sxt030_stall_instrumentation.py)")


def _sxt030_banner(spec):
    """The SXT-030 banner, composed from the entry's own fields.

    It quotes the entry's replacements, so a changed mutation rewrites the
    banner too and `--check` reports the committed file as STALE rather than
    letting its header describe a mutation it no longer carries. Reproduces
    the bytes tools/make_sxt030_mutants.py wrote before #623.
    """
    lines = [
        "// SXT-030 (#316) COMMITTED NEGATIVE CONTROL (do not fix in place).",
        "//",
        "// Deliberately mutated copy of %s:" % EXT_MEM_BASE,
    ]
    for old, new in spec["mutation"]:
        lines.append("//   `%s`" % old)
        lines.append("//     -> `%s`" % new)
    lines += [
        "// Effect: %s." % spec["what"],
        "// Under tools/sxt030_stall_bench.py this build MUST %s."
        % spec["must"],
        "// If it ever grades PASS, the bench/gate is broken and must be",
        "// repaired before any SXT-030 instrumentation claim stands.",
        "//",
        "// Regenerate with: python3 tools/make_sxt030_mutants.py",
        "",
    ]
    return "\n".join(lines) + "\n" + TIMESCALE


def _sxt030(mutation, what, must):
    """One rtl/instrumentation/ entry in the `strip` composition shape."""
    spec = {
        "base": EXT_MEM_BASE,
        "strip": [TIMESCALE],
        "mutation": mutation,
        "what": what,
        "must": must,
        "exercised_by": EXT_MEM_RUNS,
    }
    spec["prefix"] = _sxt030_banner(spec)
    return spec

# Entry fields:
#   base        repo-relative source the mutant copies
#   prefix      literal banner prepended ahead of the base text ("" if none)
#   strip       composition shape, not a mutation: literal text removed
#               once from the base because the banner already carries it
#               (the `timescale line, for the five #623 entries). Applied
#               before the mutation, and anchored the same way: text that
#               is no longer there is an error, not a silent no-op.
#   mutation    the replacements that ARE the targeted mutation; each is
#               (old, new) for a single occurrence or (old, new, count)
#   stale       declared drift: replacements present in the committed file
#               that are NOT part of the targeted mutation (default none)
#   what        one line on what the mutation does
#   exercised_by  the comparator / control script that runs this mutant.
#               Presence here is a pointer, not a verdict: whether the
#               control currently FAILS its target is that script's own
#               result, not this table's.
#   must        (strip-shape SXT-030 entries only) the verdict its bench
#               must reach, quoted into the generated banner. Also a
#               pointer, not a verdict.
MUTANTS = {
    "rtl/voice/voice_halfband_order_mutant.sv": {
        "base": "rtl/voice/tb_voice.sv",
        "prefix": ('// SXT-022 #123 NEGATIVE CONTROL MUTANT of tb_voice.sv: the halfband D2\n'
                   '// reconstruction branch order is reverted to the pre-#123 A-even/B-odd\n'
                   '// assignment (a SINGLE-LINE mutation) -- must FAIL RTL-vs-model exactness.\n'
                   '// Everything else is byte-identical to rtl/voice/tb_voice.sv.\n'),
        "mutation": [
            ('      bl = qround1(chainb[2*k] + chaina[2*k+1]);\n',
             '      bl = qround1(chaina[2*k] + chainb[2*k+1]);\n'),
        ],
        "what": "halfband D2 reconstruction branch order reverted (A-even/B-odd)",
        "exercised_by": "tools/compare_rtl_model.py --tb (tests/test_halfband_d2_voice.py)",
    },
    "rtl/voice/voice_wrongparam_mutant.sv": {
        "base": "rtl/voice/tb_voice.sv",
        "prefix": ('// SXT-026a NEGATIVE CONTROL MUTANT of tb_voice.sv (wrong parameterization):\n'
                   '// the filter pole count is forced to 12, ignoring the declared fu_poles init\n'
                   '// word (a SINGLE-LINE mutation) -- must FAIL RTL-vs-model exactness.\n'
                   '// Everything else is byte-identical to rtl/voice/tb_voice.sv (refreshed #145).\n'),
        "mutation": [
            ("    poles = 32'(cfg[41]);                     // SXT-026a: 12 or 24\n",
             "    poles = 32'sd12;                          // WRONG-PARAM MUTANT: ignores declared fu_poles\n"),
        ],
        "what": "filter pole count forced to 12, ignoring the declared fu_poles word",
        "exercised_by": "tests/test_sxt026a_wrongparam_control.py",
    },
    "rtl/voice/lfo_broken_mutant.sv": {
        "base": "rtl/voice/tb_lfo.sv",
        "mutation": [
            ("    output21[s][inst] = (out27 + (32'sd1 <<< (F_WAVE - FQ - 1)))\n",
             "    output21[s][inst] = (out27 + (32'sd1 <<< (F_WAVE - FQ - 2)))\n"),
        ],
        "what": "LFO output rounding bias halved (1/2 LSB -> 1/4 LSB)",
        "exercised_by": "tools/lfo_negative_controls.py",
    },
    "rtl/voice/lp12_broken_mutant.sv": {
        "base": "rtl/voice/tb_lp12.sv",
        "mutation": [
            ("    r = (p + (64'sd1 << 20)) >>> 21;\n",
             "    r = (p + (64'sd1 << 19)) >>> 21;\n"),
        ],
        "what": "qmul() round-half-up bias 2^20 -> 2^19",
        "exercised_by": "tools/lp12_negative_controls.py",
    },
    "rtl/voice/lp24_broken_mutant.sv": {
        "base": "rtl/voice/tb_lp24.sv",
        "prefix": ('// SXT-038 NEGATIVE CONTROL (RTL mutant) — DO NOT USE AS THE LEAF RTL.\n'
                   '//\n'
                   '// This is rtl/voice/tb_lp24.sv with exactly ONE constant mutated: the\n'
                   '// round-half-up bias inside qmul() is 2^19 instead of 2^21/2 = 2^20.  The\n'
                   '// exactness harness (tools/compare_rtl_model_lp24.py) MUST report FAIL on\n'
                   '// this file; if it ever reports PASS, the exactness check is not actually\n'
                   "// checking the arithmetic and the leaf's claim (1) is void.\n"
                   '//\n'),
        "mutation": [
            ('module tb_lp24;\n',
             'module tb_lp24;   // MUTANT BUILD\n'),
            ("    r = (p + (64'sd1 << 20)) >>> 21;\n",
             "    r = (p + (64'sd1 << 19)) >>> 21;   // MUTATION: rounding bias 2^19 (was 2^20)\n"),
        ],
        "what": "qmul() round-half-up bias 2^20 -> 2^19",
        "exercised_by": "tools/lp24_negative_controls.py",
    },
    "rtl/voice/lpmoog_broken_mutant.sv": {
        "base": "rtl/voice/tb_lpmoog.sv",
        "prefix": ('// SXT-039 NEGATIVE CONTROL (committed, must FAIL).\n'
                   '//\n'
                   '// This file is rtl/voice/tb_lpmoog.sv with EXACTLY ONE constant mutated: the\n'
                   '// round-half-up bias of the coefficient product (1 << (CFQ-1) -> 1 << (CFQ-2)),\n'
                   '// i.e. rounding at 1/4 LSB instead of 1/2 LSB.  It must FAIL the\n'
                   '// RTL-vs-model exactness comparison (tools/compare_rtl_model_lpmoog.py) while\n'
                   '// the clean testbench passes on the same stimulus.  A control that stops\n'
                   '// failing is a broken control, not a success.\n'),
        "mutation": [
            ('module tb_lpmoog;\n',
             'module tb_lpmoog;   // MUTANT BUILD (see header)\n'),
            ("    r = (p + (64'sd1 << (CFQ - 1))) >>> CFQ;\n",
             "    r = (p + (64'sd1 << (CFQ - 2))) >>> CFQ;   // MUTATION: round bias 1/2 -> 1/4 LSB\n"),
        ],
        "what": "coefficient-product round bias 1/2 LSB -> 1/4 LSB",
        "exercised_by": "tools/lpmoog_negative_controls.py",
    },
    "rtl/voice/tb_kt_broken_mutant.sv": {
        "base": "rtl/voice/tb_kt.sv",
        "mutation": [
            ("    num = (64'sd1048576 * n) + 64'sd3;\n",
             "    num = (64'sd1048576 * n) + 64'sd0;\n"),
        ],
        "what": "key-tracking word loses its +3 rounding term",
        "exercised_by": "tools/kt_negative_controls.py",
    },
    "rtl/voice/tb_kt_shared_mutant.sv": {
        "base": "rtl/voice/tb_kt.sv",
        "mutation": [
            ('          kt = kt_word_of(key + 12*oct - root);\n',
             "          kt = kt_word_of(32'sd36 + 12*oct - root);\n"),
        ],
        "what": "per-voice key replaced by one shared constant key (36)",
        "exercised_by": "tools/kt_negative_controls.py",
    },
    "rtl/voice/tb_mw_broken_mutant.sv": {
        "base": "rtl/voice/tb_mw.sv",
        "mutation": [
            ('      da    = qmul_sh(tp_sp, INV, FQ);\n',
             '      da    = qmul_sh(tp_sp, INV, FQ-1);\n'),
        ],
        "what": "modwheel smoothing step doubled (shift FQ -> FQ-1)",
        "exercised_by": "tools/mw_negative_controls.py",
    },
    "rtl/effects/tb_fx_mutant.sv": {
        "base": "rtl/effects/tb_fx.sv",
        "mutation": [
            ("    localparam signed [63:0] DLP_r  = 64'sh00000083126E979;    // 0.004 Q24.43\n",
             "    localparam signed [63:0] DLP_r  = 64'sh00000083126E97A;    // 0.004 Q24.43\n"),
        ],
        "what": "Q24.43 lowpass constant off by one LSB",
        "exercised_by": "tools/compare_rtl_model_fx.py",
    },
    "rtl/effects/type-conditioner/tb_conditioner_mutant_nolimiter.sv": {
        "base": "rtl/effects/type-conditioner/tb_conditioner.sv",
        "prefix": CONDITIONER_BANNER,
        "mutation": [
            ('            gain_r[inst] = recip_c(flam2[inst]);\n',
             '            gain_r[inst] = ONE_C;\n'),
        ],
        "what": "compressor gain forced to 1.0 (limiter disabled)",
        "exercised_by": "tools/compare_rtl_model_conditioner.py",
    },
    "rtl/effects/type-conditioner/tb_conditioner_mutant_shared.sv": {
        "base": "rtl/effects/type-conditioner/tb_conditioner.sv",
        "prefix": CONDITIONER_BANNER,
        # Every per-instance look-ahead/envelope site pooled into instance 0
        # (the tb_fx_shared_line pattern). Counts are pinned: a new site in
        # the base changes the count and is reported, not silently pooled.
        "mutation": [
            ('dly_l[inst]', 'dly_l[0]', 3),
            ('dly_r[inst]', 'dly_r[0]', 3),
            ('lamax[inst]', 'lamax[0]', 4),
            ('bufpos[inst]', 'bufpos[0]', 4),
            ('flam[inst]', 'flam[0]', 7),
            ('flam2[inst]', 'flam2[0]', 7),
            ('gain_r[inst]', 'gain_r[0]', 5),
        ],
        "what": "both instances' ring, leaves, bufpos and envelope "
                "pooled into instance 0",
        "exercised_by": "tools/compare_rtl_model_conditioner.py",
    },
    "rtl/oscillators/classic/classic_broken_mutant.sv": {
        "base": "rtl/oscillators/classic/tb_classic.sv",
        "mutation": [
            # This mutant has no prepended banner: it overwrites the base's
            # first header line (committed bytes, reproduced as-is).
            ('// SXT-033 RTL Classic oscillator family: audio-rate schedule for the\n',
             '// SXT-033 NEGATIVE CONTROL MUTANT (single-constant qmul rounding mutation, '
             'SXT-022 pattern) of tb_classic.sv — must FAIL exactness. for the\n'),
            ('module tb_classic;\n',
             'module tb_classic_mut;\n'),
            ("    r = (p + (64'sd1 << 20)) >>> 21;\n",
             "    r = (p + (64'sd1 << 19)) >>> 21;\n"),
        ],
        "what": "qmul() round-half-up bias 2^20 -> 2^19 "
                "(module renamed tb_classic_mut)",
        "exercised_by": "tools/compare_classic_rtl_model.py",
    },
    "rtl/oscillators/sine/sine_broken_mutant.sv": {
        "base": "rtl/oscillators/sine/tb_sine.sv",
        "mutation": [
            ("    r = (p + (64'sd1 << 20)) >>> 21;\n",
             "    r = (p + (64'sd1 << 19)) >>> 21;\n"),
        ],
        "what": "qmul() round-half-up bias 2^20 -> 2^19",
        "exercised_by": "tools/compare_sine_rtl_model.py",
    },
    # ---- absorbed in #623: the `strip` composition shape -----------------
    CONTROL_MUTANT: {
        "base": "rtl/control/control_top.sv",
        "prefix": CONTROL_BANNER,
        "strip": [TIMESCALE],
        "mutation": [
            ("parameter int QUEUE_DEPTH = 16,\n",
             "parameter int QUEUE_DEPTH = 15,\n"),
        ],
        "what": "event-queue depth constant 16 -> 15",
        "exercised_by": "tools/control_negative_controls.py "
                        "(tests/test_sxt021_control.py)",
    },
    EXT_MEM_DIR + "/ext_mem_instr_silence_mutant.sv": _sxt030(
        [(EXT_MEM_HOLD, EXT_MEM_SILENCE)],
        ("on a deadline miss the output is forced to SILENCE "
         "instead of holding the previous frame's sample"),
        ("FAIL the NC-1 gate (over-subscribed output is silent: "
         "the held-sample policy is violated)")),
    EXT_MEM_DIR + "/ext_mem_instr_zero_counters_mutant.sv": _sxt030(
        [(EXT_MEM_COUNT, EXT_MEM_NO_COUNT)],
        ("the stall instrumentation is stubbed to zero: "
         "STALL_FRAMES, STALL_CYCLES_MAX, FIRST_STALL_FRAME, "
         "OUTPUT_FAULT, stall_strobe and stall_led never fire, while "
         "the output still degrades (held samples) on a miss"),
        ("be REFUSED by the NC-1 gate as NO_VERDICT (degraded "
         "output with STALL_FRAMES == 0), never graded PASS")),
    EXT_MEM_DIR + "/ext_mem_instr_silence_zero_counters_mutant.sv": _sxt030(
        [(EXT_MEM_HOLD, EXT_MEM_SILENCE), (EXT_MEM_COUNT, EXT_MEM_NO_COUNT)],
        ("silence on a miss AND the stall instrumentation stubbed "
         "to zero (silence-with-zero-counters)"),
        ("be REFUSED by the NC-1 gate as NO_VERDICT; silence with "
         "zero counters is never reportable as a pass or a stall")),
    EXT_MEM_DIR + "/ext_mem_instr_throttle_never_mutant.sv": _sxt030(
        [(EXT_MEM_LATCH, EXT_MEM_NO_LATCH)],
        ("the M2 service-window throttle never engages: "
         "SVC_WINDOW_LIMIT still reads back the commanded value but "
         "every frame latches the nominal window"),
        ("FAIL the NC-1 gate (the over-subscribed run shows no "
         "witness firing: over-subscription was never achieved)")),
    # ---- the two KNOWN-DRIFT entries (see the module docstring) ----------
    "rtl/voice/voice_broken_mutant.sv": {
        "base": "rtl/voice/tb_voice.sv",
        "mutation": [
            ("    r = (p + (64'sd1 << 20)) >>> 21;\n",
             "    r = (p + (64'sd1 << 19)) >>> 21;\n"),
        ],
        "stale": SXT036_STALE,
        "drift": "three hunks revert the base's SXT-036 constructor "
                 "gain-anchor logic; regenerating needs new bytes, a "
                 "re-derived T1 item 9 attestation and a re-run of "
                 "this control",
        "what": "qmul() round-half-up bias 2^20 -> 2^19",
        "exercised_by": "tools/compare_rtl_model.py --tb",
    },
    "rtl/voice/voice_uni_mutant.sv": {
        "base": "rtl/voice/tb_voice.sv",
        "mutation": [
            ('    // a_cov, accumulating into the SHARED impulse buffer\n'
             '    for (u = 0; u < uni_n; u++) begin\n',
             '    // a_cov, accumulating into the SHARED impulse buffer\n'
             '    for (u = 0; u < 1; u++) begin\n'),
        ],
        "stale": SXT036_STALE,
        "drift": "three hunks revert the base's SXT-036 constructor "
                 "gain-anchor logic; regenerating needs new bytes, a "
                 "re-derived T1 item 9 attestation and a re-run of "
                 "this control",
        "what": "unison fill loop runs one voice instead of uni_n",
        "exercised_by": "tools/compare_rtl_model.py --tb",
    },
}

DRIFTED = tuple(sorted(p for p, s in MUTANTS.items() if s.get("stale")))


def replacements(spec):
    """The full ordered replacement list for an entry.

    Composition strip first (text the banner already carries), then the
    targeted mutation, then any declared drift. Every one of them is
    anchor-checked by apply_replacements(), so a `strip` whose text moved
    out of the base is reported like any other lost anchor.
    """
    return ([(text, "") for text in spec.get("strip", ())]
            + list(spec["mutation"]) + list(spec.get("stale", [])))


def apply_replacements(text, reps, where):
    for rep in reps:
        old, new = rep[0], rep[1]
        want = rep[2] if len(rep) > 2 else 1
        have = text.count(old)
        if have != want:
            raise ValueError("%s: anchor %r occurs %d times, expected %d"
                             % (where, old, have, want))
        text = text.replace(old, new)
    return text


def render(path, base_src=None):
    """The exact bytes the mutant at `path` must have, as text."""
    spec = MUTANTS[path]
    if base_src is None:
        with open(os.path.join(REPO, spec["base"]), encoding="utf-8") as f:
            base_src = f.read()
    body = apply_replacements(base_src, replacements(spec), path)
    return spec.get("prefix", "") + body


def write(path):
    """Regenerate one mutant; returns its absolute path."""
    full = os.path.join(REPO, path)
    want = render(path)
    have = None
    if os.path.exists(full):
        with open(full, encoding="utf-8") as f:
            have = f.read()
    if have != want:
        with open(full, "w", encoding="utf-8") as f:
            f.write(want)
    return full


def stale_mutants():
    """Paths whose committed bytes differ from a fresh render."""
    bad = []
    for path in MUTANTS:
        full = os.path.join(REPO, path)
        have = None
        if os.path.exists(full):
            with open(full, encoding="utf-8") as f:
                have = f.read()
        if have != render(path):
            bad.append(path)
    return bad


def _report_known_drift():
    for path in DRIFTED:
        print("KNOWN-DRIFT: %s -- %s" % (path, MUTANTS[path]["drift"]))


def main(argv):
    if "--list" in argv:
        for path, spec in sorted(MUTANTS.items()):
            print("%s\n    base %s | %d mutation hunk(s)%s"
                  % (path, spec["base"], len(spec["mutation"]),
                     ", %d DECLARED STALE hunk(s)" % len(spec["stale"])
                     if spec.get("stale") else ""))
            print("    %s\n    runs: %s"
                  % (spec["what"], spec["exercised_by"]))
        return 0
    if "--check" in argv:
        bad = stale_mutants()
        for path in bad:
            print("STALE: %s (committed bytes differ from base + declared"
                  " mutations; regenerate with"
                  " python3 tools/make_rtl_mutants.py)" % path)
        _report_known_drift()
        print("%d/%d committed mutants reproduce from their base (%d declared "
              "known-drift)" % (len(MUTANTS) - len(bad), len(MUTANTS),
                                len(DRIFTED)))
        return 1 if bad else 0
    for path in sorted(MUTANTS):
        full = os.path.join(REPO, path)
        before = None
        if os.path.exists(full):
            with open(full, encoding="utf-8") as f:
                before = f.read()
        want = render(path)
        write(path)
        print("%s: %s" % ("unchanged" if before == want else "wrote", path))
    _report_known_drift()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
