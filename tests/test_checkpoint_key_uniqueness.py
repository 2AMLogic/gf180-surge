"""Issue #639: every RTL-vs-model exactness harness refuses a repeated
checkpoint key, through the one shared unique-insert primitive.

#455 decided the rule for the two LFO harnesses: in an exactness harness a
contradictory row followed by a correct row for the same checkpoint must be
refused, never resolved last-row-wins (last-row-wins turns a disagreement
into a PASS).  The rule was written twice as private boilerplate and reached
2 of the 13 private `parse_tb` parsers; this module is the live control that
it now reaches every converted one through
`_rtl_compile_common.CheckpointKeys`.

Synthetic traces only: no simulator, no oracle, no model.  These are parser
controls.  They establish nothing about the RTL, the frozen model or any
committed exactness record -- in particular, no committed trace is claimed
here to contain (or to be free of) a repeated key.

NOT_RUN for this rule: `tools/compare_rtl_model_lp12.py`,
`tools/compare_rtl_model_lp24.py` and `tools/compare_rtl_model_lpmoog.py`.
They are live-pinned in `docs/byte-frozen-sources.json`, were deliberately
left unconverted, and still resolve a repeated key last-row-wins.  Their
absence from `CASES` is not a pass for them.
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
