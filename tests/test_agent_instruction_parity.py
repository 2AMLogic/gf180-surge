"""AGENTS.md / CLAUDE.md must be identical outside Loom-managed marker blocks.

Enforces the CLAUDE.md rule "Keep AGENTS.md and CLAUDE.md substantively
identical outside their Loom-managed marker blocks". Stdlib only. Marker
grammar (verified in both files): a line ``<!-- BEGIN NAME -->`` opens a block
and ``<!-- END NAME -->`` closes it; NAME may contain spaces and parentheses
(e.g. ``LOOM ORCHESTRATION (AGENTS)``). Blocks are exempt from comparison.
"""
import difflib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MARKER = re.compile(r"^\s*<!--\s*(BEGIN|END)\s+(.+?)\s*-->\s*$")


class MarkerError(ValueError):
    pass


def strip_blocks(text: str) -> str:
    """Remove BEGIN/END blocks (inclusive); raise MarkerError if malformed."""
    out, open_name = [], None
    for n, line in enumerate(text.splitlines(), 1):
        m = MARKER.match(line)
        if m:
            kind, name = m.group(1), m.group(2)
            if kind == "BEGIN":
                if open_name is not None:
                    raise MarkerError(f"line {n}: BEGIN {name!r} inside open {open_name!r}")
                open_name = name
            else:
                if open_name is None:
                    raise MarkerError(f"line {n}: END {name!r} without BEGIN")
                if name != open_name:
                    raise MarkerError(f"line {n}: END {name!r} does not match BEGIN {open_name!r}")
                open_name = None
            continue
        if open_name is None:
            out.append(line.rstrip())
    if open_name is not None:
        raise MarkerError(f"unterminated BEGIN {open_name!r}")
    return "\n".join(out).rstrip("\n") + "\n"


def compare(a: str, b: str, a_name="AGENTS.md", b_name="CLAUDE.md") -> str:
    """Return '' when equal outside blocks, else a unified diff. Refuses on empty."""
    sa, sb = strip_blocks(a), strip_blocks(b)
    if not sa.strip() and not sb.strip():
        raise AssertionError("both files empty after stripping; refusing vacuous pass")
    return "".join(difflib.unified_diff(
        sa.splitlines(True), sb.splitlines(True), a_name, b_name))


def _read(name: str) -> str:
    p = ROOT / name
    assert p.is_file(), f"{name} missing"
    return p.read_text(encoding="utf-8")


def test_committed_pair_matches_outside_blocks():
    diff = compare(_read("AGENTS.md"), _read("CLAUDE.md"))
    assert diff == "", "AGENTS.md and CLAUDE.md differ outside marker blocks:\n" + diff


# ---- negative controls (run on in-memory / temp copies) ----

BASE = "intro\n<!-- BEGIN X Y (Z) -->\nblock\n<!-- END X Y (Z) -->\ntail\n"


def test_control_a_added_sentence_outside_block_fails():
    assert compare(BASE, BASE + "extra sentence\n") != ""


def test_control_b_differing_block_content_passes():
    other = BASE.replace("block", "different block content")
    assert compare(BASE, other) == ""


def test_control_b2_trailing_whitespace_normalised():
    assert compare(BASE, BASE.replace("intro", "intro   ")) == ""


@pytest.mark.parametrize("bad", [
    "a\n<!-- BEGIN X -->\nb\n",                       # unterminated
    "a\n<!-- END X -->\n",                            # END without BEGIN
    "<!-- BEGIN X -->\n<!-- END Y -->\n",             # mismatched names
    "<!-- BEGIN X -->\n<!-- BEGIN Y -->\n<!-- END Y -->\n<!-- END X -->\n",  # nested
])
def test_control_c_bad_markers_refuse(bad):
    with pytest.raises(MarkerError):
        compare(bad, BASE)
    with pytest.raises(MarkerError):
        compare(BASE, bad)


def test_control_d_empty_fails():
    with pytest.raises(AssertionError):
        compare("", "")
    with pytest.raises(AssertionError):
        compare("<!-- BEGIN X -->\nonly block\n<!-- END X -->\n", "")


def test_control_d_missing_file_fails(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    with pytest.raises(AssertionError):
        _read("AGENTS.md")
