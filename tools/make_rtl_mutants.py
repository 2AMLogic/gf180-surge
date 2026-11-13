#!/usr/bin/env python3
"""Generate the committed copy-style RTL negative-control mutants (#620).

A copy-style mutant is a whole-file copy of the testbench it mutates,
differing from it by a banner plus a few exact lines. This script declares
each one as

    mutant = optional banner prefix + base source with the declared
             `old` -> `new` replacements applied

and `--check` exits non-zero if any committed mutant differs from what this
script would write, so a control cannot silently drift from the testbench it
mutates. That is the rule tools/make_sxt030_mutants.py already applies to the
four rtl/instrumentation/ mutants; this table applies it to the sixteen
mutants that were hand-maintained copies (or, for the two conditioner
mutants, regenerated in place by their own comparator with no committed-byte
check).

Each `old` must occur the declared number of times in the base (once unless a
count is given), so a replacement that no longer anchors is an error rather
than a silent no-op. No mutant is weakened or removed here: this script
reproduces the committed bytes of every file it lists.

Not yet the single definition for every mutant it lists:
tools/compare_rtl_model_conditioner.py still writes its two mutants from its
own private replacement list, because that file's bytes are attested in
signoff/t1-item9-attestation.json and editing it would make that record
stale. The two definitions are held byte-identical by
tests/test_rtl_mutant_table.py until that fold happens; the same applies to
tools/make_control_mutant.py and tools/make_sxt030_mutants.py, which keep
their own tables.

No entry declares drift (#622). The `"stale"` mechanism below is retained --
`--check` still reports any declared-drift entry by name, and the count in
its summary line is the gate -- but rtl/voice/voice_broken_mutant.sv and
rtl/voice/voice_uni_mutant.sv, the two entries that carried it, were
regenerated in #622 so each is again base + its one targeted replacement.
That regeneration re-derived the T1 item 9 attestation for the new bytes and
re-ran both controls against the current base
(reports/voice-mutant-regeneration/). A declared-drift entry is a bounded
finding, never a resting state: it pins drift so it is reported rather than
hidden, and the entry is expected to be regenerated away.

Nothing here claims any control fails for the right reason or the wrong one;
no comparator is run by this script. Those verdicts live in the evidence
records named in each entry's `exercised_by` tool.

Usage:
    python3 tools/make_rtl_mutants.py            # regenerate
    python3 tools/make_rtl_mutants.py --check     # drift gate, exits non-zero
    python3 tools/make_rtl_mutants.py --list      # print the table

Original to this repository (Apache-2.0).
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONDITIONER_BANNER = (
    '// GENERATED negative-control mutant of tb_conditioner.sv by\n'
    '// tools/compare_rtl_model_conditioner.py -- must FAIL exactness.\n')

# Entry fields:
#   base        repo-relative source the mutant copies
#   prefix      literal banner prepended ahead of the base text ("" if none)
#   mutation    the replacements that ARE the targeted mutation; each is
#               (old, new) for a single occurrence or (old, new, count)
#   stale       declared drift: replacements present in the committed file
#               that are NOT part of the targeted mutation (default none)
#   what        one line on what the mutation does
#   exercised_by  the comparator / control script that runs this mutant.
#               Presence here is a pointer, not a verdict: whether the
#               control currently FAILS its target is that script's own
#               result, not this table's.
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
    "rtl/voice/voice_broken_mutant.sv": {
        "base": "rtl/voice/tb_voice.sv",
        "mutation": [
            ("    r = (p + (64'sd1 << 20)) >>> 21;\n",
             "    r = (p + (64'sd1 << 19)) >>> 21;\n"),
        ],
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
        "what": "unison fill loop runs one voice instead of uni_n",
        "exercised_by": "tools/compare_rtl_model.py --tb",
    },
}

DRIFTED = tuple(sorted(p for p, s in MUTANTS.items() if s.get("stale")))


def replacements(spec):
    """The full ordered replacement list: targeted mutation, then drift."""
    return list(spec["mutation"]) + list(spec.get("stale", []))


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
