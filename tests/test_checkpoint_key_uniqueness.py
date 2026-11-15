"""Issues #639/#648: every RTL-vs-model exactness harness refuses a
repeated checkpoint key, through the one shared unique-insert primitive.

#455 decided the rule for the two LFO harnesses: in an exactness harness a
contradictory row followed by a correct row for the same checkpoint must be
refused, never resolved last-row-wins (last-row-wins turns a disagreement
into a PASS).  The rule was written twice as private boilerplate and reached
2 of the 13 private `parse_tb` parsers; #639 converted ten more and #648 the
three live-pinned lowpass harnesses.  This module is the live control that
it now reaches all thirteen through `_rtl_compile_common.CheckpointKeys`.

That reach claim is audited live (#667), not merely asserted: the cases
below are parametrised over `CASES`, so on their own they could never
notice a parser missing from it.  `audit_case_inventory` re-derives the
`tools/` parser population from the tree on every run and compares it with
`CASES` in both directions; `ALLOWLIST` is the one place a deliberate
exclusion is recorded, and an exclusion that has gone stale is itself a
finding.  The five effect-family `parse_tb_trace` parsers are allowlisted
pending #666.

Synthetic traces only: no simulator, no oracle, no model.  These are parser
controls, and the audit is an inventory control over the source tree.  They
establish nothing about the RTL, the frozen model, Surge fidelity or any
committed exactness record -- in particular, no committed trace is claimed
here to contain (or to be free of) a repeated key, and the audit says only
which harness parsers exist, never that any of them agrees with anything.
"""
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import tools.compare_classic_rtl_model as classic  # noqa: E402
import tools.compare_control_rtl as control  # noqa: E402
import tools.compare_kt_rtl_model as kt  # noqa: E402
import tools.compare_lfo_rtl_model as lfo  # noqa: E402
import tools.compare_mw_rtl_model as mw  # noqa: E402
import tools.compare_pm_rtl_model as pm  # noqa: E402
import tools.compare_rtl_model as voice  # noqa: E402
import tools.compare_rtl_model_lp12 as lp12  # noqa: E402
import tools.compare_rtl_model_lp24 as lp24  # noqa: E402
import tools.compare_rtl_model_lpmoog as lpmoog  # noqa: E402
import tools.compare_sine_rtl_model as sine  # noqa: E402
import tools.compare_slfo_rtl_model as slfo  # noqa: E402
import tools.compare_vel_rtl_model as vel  # noqa: E402
from _rtl_compile_common import CheckpointKeys, LeafInputError  # noqa: E402


def _row(tag, head, n, start=1):
    """`tag` + the key words in `head` + `n` ascending payload words."""
    return " ".join([tag] + [str(x) for x in head]
                    + [str(start + i) for i in range(n)])


def _flat(tag, head, n, value):
    """Same shape as `_row`, every payload word `value` -- the contradicting
    twin of the `_row` above it, so a last-row-wins store is observable."""
    return " ".join([tag] + [str(x) for x in head] + [str(value)] * n)


# --------------------------------------------------------------- the cases
# good:    a healthy trace -- every keyed record appears exactly once
# dups:    tag -> a row repeating a key already in `good`, with contradictory
#          payload words (so the defect this guards is "the wrong row is
#          silently discarded", not merely "a row was repeated")
# appends: rows that repeat a key on purpose because the store is a sequence,
#          not a keyed checkpoint -- these must keep parsing
CASES = {
    "lfo": dict(
        mod=lfo,
        good=["L 0 0 0 1 1 2 3 4", "S 0 0 5 6"],
        dups={"L": "L 0 0 0 99 1 2 3 4", "S": "S 0 0 50 60"},
        appends=[],
    ),
    "slfo": dict(
        mod=slfo,
        good=["L 0 0 1 4 2 5 3", "S 0 7 9", "O 0 3 3 3 3 3 3"],
        dups={"L": "L 0 0 99 4 2 5 3", "S": "S 0 70 90",
              "O": "O 0 9 9 9 9 9 9"},
        appends=[],
    ),
    "kt": dict(
        mod=kt,
        good=[_row("V", (0, 0), 8)],
        dups={"V": _flat("V", (0, 0), 8, 99)},
        appends=[],
    ),
    "mw": dict(
        mod=mw,
        good=["S 0 0 1 2 3", "M 0 4"],
        dups={"S": "S 0 0 9 9 9", "M": "M 0 7"},
        appends=[],
    ),
    "vel": dict(
        mod=vel,
        good=["S 0 0 1 2 3 4", "V 0 0 5 6"],
        dups={"S": "S 0 0 9 9 9 9", "V": "V 0 0 9 9"},
        appends=[],
    ),
    "pm": dict(
        mod=pm,
        good=[_row("T", (0, 0), 16)],
        dups={"T": _flat("T", (0, 0), 16, 99)},
        appends=[],
    ),
    "classic": dict(
        mod=classic,
        good=[_row("T", (0, 0), 129), _row("O", (0, 0), 64), "M 0 5"],
        dups={"T": _flat("T", (0, 0), 129, 99),
              "O": _flat("O", (0, 0), 64, 99)},
        # `M` is a per-block sample sequence collected with append()
        appends=["M 0 6", "M 0 7"],
    ),
    "sine": dict(
        mod=sine,
        # T carries legacy=0 at word 4, so the modern 4-field unison layout
        # (16*4 words) plus `prior_valid` follows the 8 header words.
        good=["T 0 0 1 0 " + " ".join(["2"] * 3 + ["3"] * 66),
              _row("S", (0, 0), 9), "G 0 0 5", _row("O", (0, 0), 64),
              "M 0 5"],
        dups={"T": "T 0 0 9 0 " + " ".join(["9"] * 69),
              "S": _flat("S", (0, 0), 9, 99), "G": "G 0 0 55",
              "O": _flat("O", (0, 0), 64, 99)},
        appends=["M 0 6", "M 0 7"],
    ),
    "voice": dict(
        mod=voice,
        good=[_row("T", (0, 0), 31), _row("U", (0, 0, 0), 6),
              _row("O", (0, 0), 64), "M 0 5"],
        dups={"T": _flat("T", (0, 0), 31, 99),
              "U": _flat("U", (0, 0, 0), 6, 99),
              "O": _flat("O", (0, 0), 64, 99)},
        appends=["M 0 6", "M 0 7"],
    ),
    "control": dict(
        mod=control,
        good=[_row("T", (0,), 28), "M 0 0 1 2", "E 0 0 1 2 3 4 5 6 7",
              "X 0 0 1 2 3"],
        dups={"T": _flat("T", (0,), 28, 99), "M": "M 0 0 9 9"},
        # E (decisions) and X (drops) are per-block sequences, U is a list
        appends=["E 0 1 1 2 3 4 5 6 7", "X 0 1 1 2 3", "U 0 0", "U 0 0"],
    ),
    # The three live-pinned lowpass harnesses (issue #648).  `Y` keys a
    # single output sample by (block, index) and `T` keys the end-of-block
    # checkpoint by block; neither is a sequence, so both are routed
    # through the primitive.  T width after the block key is T_FIELDS: 12
    # for lp12 (subtype, r0, r1, r_clip, c0..c7), 14 for lp24 and lpmoog
    # (subtype, R[0..4], C[0..7]).
    "lp12": dict(
        mod=lp12,
        good=[_row("Y", (0, 0), 1), _row("T", (0,), 12)],
        dups={"Y": _flat("Y", (0, 0), 1, 99),
              "T": _flat("T", (0,), 12, 99)},
        appends=[],
    ),
    "lp24": dict(
        mod=lp24,
        good=[_row("Y", (0, 0), 1), _row("T", (0,), 14)],
        dups={"Y": _flat("Y", (0, 0), 1, 99),
              "T": _flat("T", (0,), 14, 99)},
        appends=[],
    ),
    "lpmoog": dict(
        mod=lpmoog,
        good=[_row("Y", (0, 0), 1), _row("T", (0,), 14)],
        dups={"Y": _flat("Y", (0, 0), 1, 99),
              "T": _flat("T", (0,), 14, 99)},
        appends=[],
    ),
}

NAMES = sorted(CASES)
TAGGED = sorted((n, t) for n in CASES for t in CASES[n]["dups"])


def _write(tmp_path, rows):
    p = tmp_path / "trace.txt"
    p.write_text("\n".join(rows) + "\n")
    return str(p)


def _parse(name, tmp_path, rows):
    return CASES[name]["mod"].parse_tb(_write(tmp_path, rows))


# ------------------------------------------------- healthy traces still parse
@pytest.mark.parametrize("name", NAMES)
def test_healthy_trace_parses(name, tmp_path):
    """Every key once: the refusal must not fire (non-vacuity for the
    duplicate cases below -- without this they would pass on a parser that
    refused everything)."""
    assert _parse(name, tmp_path, CASES[name]["good"]) is not None


@pytest.mark.parametrize("name", NAMES)
def test_healthy_trace_parses_in_any_order(name, tmp_path):
    """Checkpoint rows are keyed, not positional: reversing a healthy trace
    is still healthy."""
    assert _parse(name, tmp_path, list(reversed(CASES[name]["good"]))) \
        is not None


@pytest.mark.parametrize("name", sorted(n for n in CASES if CASES[n]["appends"]))
def test_repeated_append_style_rows_are_not_refused(name, tmp_path):
    """Append-style rows (`M` sample words, control's `E`/`X`/`U`) repeat a
    block id by design -- they are sequences, not keyed checkpoints.  A
    uniqueness rule that refused them would be over-broad."""
    rows = CASES[name]["good"] + CASES[name]["appends"]
    assert _parse(name, tmp_path, rows) is not None


# ------------------------------------------------------- the #455 refusal
@pytest.mark.parametrize("name,tag", TAGGED)
@pytest.mark.parametrize("wrong_first", [True, False])
def test_duplicate_checkpoint_key_is_refused(name, tag, tmp_path,
                                             wrong_first):
    """FAILURE CONTROL (the #455 shape): a contradictory row and a correct
    row for the same checkpoint key, in either order.  Last-row-wins makes
    the `wrong_first` case compare clean and report PASS; the parser must
    refuse instead of choosing."""
    extra = [CASES[name]["dups"][tag]]
    good = CASES[name]["good"]
    rows = extra + good if wrong_first else good + extra
    with pytest.raises(LeafInputError) as ei:
        _parse(name, tmp_path, rows)
    assert ei.value.which == "rtl_trace"
    assert "duplicate checkpoint key(s)" in ei.value.reason
    assert re.search(r"(?:: |; )%s " % re.escape(tag), ei.value.reason), \
        ei.value.reason


@pytest.mark.parametrize("name,tag", TAGGED)
def test_identical_duplicate_key_is_refused(name, tag, tmp_path):
    """A byte-identical repeat is refused too: the rule is "each checkpoint
    is recorded once", not "the records disagree"."""
    row = next(r for r in CASES[name]["good"] if r.split()[0] == tag)
    with pytest.raises(LeafInputError):
        _parse(name, tmp_path, CASES[name]["good"] + [row])


def test_sine_tags_sharing_one_record_are_unique_per_tag(tmp_path):
    """`compare_sine_rtl_model` merges T, S and G rows into one (block,
    slot) record on purpose.  Uniqueness is per tag+key: one of each is
    healthy (covered above); two S rows for that key are not."""
    good = CASES["sine"]["good"]
    with pytest.raises(LeafInputError) as ei:
        _parse("sine", tmp_path, good + [_flat("S", (0, 0), 9, 7)])
    assert re.search(r": S ", ei.value.reason), ei.value.reason


def test_voice_unison_rows_are_keyed_per_instance(tmp_path):
    """`compare_rtl_model`'s U rows store per-unison records inside the
    (block, slot) checkpoint -- a repeated unison index is a repeated
    checkpoint key, and a different index is not."""
    good = CASES["voice"]["good"]
    assert _parse("voice", tmp_path, good + [_row("U", (0, 0, 1), 6)]) \
        is not None
    with pytest.raises(LeafInputError):
        _parse("voice", tmp_path, good + [_flat("U", (0, 0, 0), 6, 7)])


# ------------------------------------------------------- the shared helper
def test_helper_reports_first_five_duplicates_and_the_total():
    keys = CheckpointKeys()
    store = {}
    for i in range(9):
        keys.put(store, "L", (0, i), i)
    for i in range(7):
        keys.put(store, "L", (0, i), 99)
    with pytest.raises(LeafInputError) as ei:
        keys.raise_if_duplicates("t.txt")
    assert "duplicate checkpoint key(s), 7: " in ei.value.reason
    assert ei.value.reason.count("; ") == 4          # five named, not seven
    assert "(0, 0)" in ei.value.reason and "(0, 6)" not in ei.value.reason


def test_helper_scopes_uniqueness_to_tag_and_key():
    keys = CheckpointKeys()
    keys.claim("T", (0, 0))
    keys.claim("S", (0, 0))       # same key, different tag -- not a repeat
    keys.claim("T", (0, 1))
    keys.raise_if_duplicates("t.txt")      # must not raise
    keys.claim("T", (0, 0))
    with pytest.raises(LeafInputError) as ei:
        keys.raise_if_duplicates("t.txt")
    assert ei.value.reason.endswith("1: T (0, 0)")


def test_helper_put_stores_the_value():
    keys = CheckpointKeys()
    store = {}
    keys.put(store, "V", (0, 0), [1, 2])
    assert store == {(0, 0): [1, 2]}
    keys.raise_if_duplicates("t.txt")


# ------------------------------------------- the CASES completeness audit
# Every test above is parametrised over `CASES`, so the suite can only ever
# check the parsers already listed there -- never that the list is complete
# (#667).  A fourteenth parser added or converted later and omitted from
# `CASES` would leave the docstring's reach claim false with the suite
# green.  The audit below closes that half of the claim: it re-derives the
# parser population from the tree on every run and compares it against
# `CASES`, in both directions.
#
# It is an inventory control over the source tree.  Like the rest of this
# module it establishes nothing about the RTL, the frozen model, Surge
# fidelity or any committed exactness record -- only that the set of
# harness parsers this module parametrises over is the set that exists.
TOOLS_REL = "tools"

# Column-anchored on purpose: `tests/test_rtl_leaf_comparison.py` defines
# two *nested* `parse_tb` fixtures (local to their test, not harness
# parsers), and an unanchored pattern would discover them.
PARSER_DEF = re.compile(r"^def parse_tb(?:_trace)?\(", re.M)

# Deliberate exclusions: a `tools/` parser knowingly absent from `CASES`.
# This dict is the one place an exclusion is recorded -- each entry names
# the issue that retires it, and `audit_case_inventory` reports an entry
# that has gone stale rather than letting it silently widen the audit.
ALLOWLIST = {
    # The five effect-family `parse_tb_trace` parsers.  #666 routes them
    # through `CheckpointKeys` and adds them to `CASES`; delete the five
    # entries in that same change -- leaving one here is a finding.
    "tools/compare_rtl_model_chorus.py": "unconverted, #666",
    "tools/compare_rtl_model_distortion.py": "unconverted, #666",
    "tools/compare_rtl_model_distortion_sse.py": "unconverted, #666",
    "tools/compare_rtl_model_fx.py": "unconverted, #666",
    "tools/compare_rtl_model_phaser.py": "unconverted, #666",
}


def discover_parsers(root=None):
    """`tools/*.py` files defining a module-level trace parser.

    Returned as repo-relative POSIX paths.  Only `tools/` is scanned and
    only column-0 definitions count, so neither a nested `def parse_tb(`
    nor a parser outside `tools/` is discovered.  `root` exists so the
    controls below can point the same scanner at a synthetic directory;
    results keep the `tools/` prefix either way, so a finding always reads
    as a repo path.
    """
    root = os.path.join(REPO, TOOLS_REL) if root is None else str(root)
    found = set()
    for name in sorted(os.listdir(root)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(root, name), encoding="utf-8") as f:
            if PARSER_DEF.search(f.read()):
                found.add("%s/%s" % (TOOLS_REL, name))
    return found


def cased_parsers(cases=None):
    """The files behind `CASES`, read from each case's own module.

    Taken from `mod.__file__` rather than a key->filename convention: the
    convention does not hold (`CASES["voice"]` is `compare_rtl_model.py`,
    and the lowpass keys are `compare_rtl_model_lp12.py` and siblings), and
    every special case a convention needed would be a silent hole of
    exactly the kind this audit closes.
    """
    cases = CASES if cases is None else cases
    return {os.path.relpath(c["mod"].__file__, REPO).replace(os.sep, "/")
            for c in cases.values()}


def audit_case_inventory(discovered, cased, allowlist):
    """Findings for drift between the tree's parsers and `CASES`.

    Returned as a list of strings (empty = clean) rather than asserted
    inline, so the negative controls below can run this same audit over
    doctored inputs.
    """
    findings = []
    for rel in sorted(discovered - cased - set(allowlist)):
        findings.append(
            f"{rel} defines a module-level parse_tb/parse_tb_trace but is "
            f"neither in CASES nor in ALLOWLIST -- this module's reach "
            f"claim does not cover it")
    for rel in sorted(cased - discovered):
        findings.append(
            f"{rel} is behind a CASES entry but defines no module-level "
            f"parse_tb/parse_tb_trace")
    for rel in sorted(set(allowlist) & set(cased)):
        findings.append(
            f"{rel} is allowlisted ({allowlist[rel]}) and also in CASES -- "
            f"the exclusion is stale, delete the ALLOWLIST entry")
    for rel in sorted(set(allowlist) - set(discovered)):
        findings.append(
            f"{rel} is allowlisted ({allowlist[rel]}) but defines no "
            f"module-level parser -- the exclusion names a file the scan "
            f"cannot see")
    return findings


def _audit_now():
    return audit_case_inventory(discover_parsers(), cased_parsers(),
                                ALLOWLIST)


def test_the_case_inventory_matches_the_tree():
    """No silent drift: a new or converted `tools/` parser must land in
    `CASES`, or be recorded as a deliberate exclusion in `ALLOWLIST`."""
    assert _audit_now() == []


def test_the_parser_scan_sees_a_nonempty_tree():
    """Coverage leg: a scan over an empty tree would vacuously 'pass'."""
    discovered = discover_parsers()
    assert len(discovered) >= 13, sorted(discovered)
    assert "tools/compare_rtl_model.py" in discovered, sorted(discovered)
    cased = cased_parsers()
    assert len(cased) == len(CASES), sorted(cased)
    assert "tools/compare_lfo_rtl_model.py" in cased, sorted(cased)


def test_the_parser_scan_is_rooted_and_column_anchored(tmp_path):
    """Discrimination leg: only column-0 definitions in the scanned root
    count.  A nested or commented-out `def parse_tb(` is not a harness
    parser, and an empty root discovers nothing (so the floors above are
    load-bearing, not accidental)."""
    (tmp_path / "nested.py").write_text(
        "def outer():\n    def parse_tb(path):\n        return {}\n")
    (tmp_path / "commented.py").write_text(
        "# def parse_tb(path):\n#     return {}\n")
    (tmp_path / "notpython.txt").write_text("def parse_tb(path):\n")
    assert discover_parsers(tmp_path) == set()
    (tmp_path / "real.py").write_text("def parse_tb(path):\n    return {}\n")
    (tmp_path / "real_trace.py").write_text(
        "def parse_tb_trace(path):\n    return {}\n")
    assert discover_parsers(tmp_path) == {"tools/real.py",
                                          "tools/real_trace.py"}
    # The two nested fixtures in the leaf-comparison tests live outside
    # `tools/`, so the real scan never sees that file at all.
    assert not any(r.startswith("tests/") for r in discover_parsers())


@pytest.mark.parametrize("doctor", ["unlisted_parser", "undiscovered_case",
                                    "stale_allowlist", "phantom_allowlist"])
def test_control_the_inventory_audit_fires_on_drift(doctor):
    """FAILURE CONTROL: each way the inventory can drift must make the
    audit non-empty and name the file responsible."""
    discovered, cased = discover_parsers(), cased_parsers()
    allowlist = dict(ALLOWLIST)
    if doctor == "unlisted_parser":
        # The issue's own "fourteenth parser" case.
        expect = "tools/compare_zz_probe_rtl_model.py"
        discovered = discovered | {expect}
    elif doctor == "undiscovered_case":
        expect = sorted(cased)[0]
        discovered = discovered - {expect}
    elif doctor == "stale_allowlist":
        expect = sorted(cased)[0]
        allowlist[expect] = "stale, #666"
    else:
        expect = "tools/compare_deleted_rtl_model.py"
        allowlist[expect] = "names a file that is gone, #666"
    findings = audit_case_inventory(discovered, cased, allowlist)
    assert findings, f"the {doctor} leg did not fire"
    assert any(expect in f for f in findings), (doctor, findings)


def test_control_the_inventory_audit_is_not_always_firing():
    """The paired positive leg for the controls above: on the tree as
    committed, with the committed allowlist, the audit is silent."""
    assert _audit_now() == []
