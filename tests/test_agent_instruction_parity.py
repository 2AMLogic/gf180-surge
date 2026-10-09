"""AGENTS.md / CLAUDE.md must be identical outside Loom-managed marker blocks.

Enforces the CLAUDE.md rule "Keep AGENTS.md and CLAUDE.md substantively
identical outside their Loom-managed marker blocks". Stdlib only.

How the pair is linked today: in git, CLAUDE.md is a symlink (mode 120000) to
AGENTS.md, so the two names are one file and cannot drift. While that holds,
parity is enforced *structurally* (``test_live_pair_structural_parity``) and
the text comparison of the live files is NOT_APPLICABLE: comparing a file with
itself would pass by construction, so ``test_live_pair_text_parity`` skips
with that reason instead of reporting a vacuous pass.

If CLAUDE.md is ever replaced by a regular file (e.g. an installer writing a
real copy), the strip-and-compare becomes the live check. The controls below
exercise it on regular-file copies in a tmp dir so it is proven to fail on
drift outside the marker blocks even while the live pair is a symlink.

Marker grammar (as used in AGENTS.md): a line ``<!-- BEGIN NAME -->`` opens a
block and ``<!-- END NAME -->`` closes it; NAME may contain spaces and
parentheses (e.g. ``LOOM ORCHESTRATION (AGENTS)``). Blocks are exempt from
comparison.
"""

import difflib
import os
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
                    raise MarkerError(
                        f"line {n}: BEGIN {name!r} inside open {open_name!r}"
                    )
                open_name = name
            else:
                if open_name is None:
                    raise MarkerError(f"line {n}: END {name!r} without BEGIN")
                if name != open_name:
                    raise MarkerError(
                        f"line {n}: END {name!r} does not match BEGIN {open_name!r}"
                    )
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
    return "".join(
        difflib.unified_diff(sa.splitlines(True), sb.splitlines(True), a_name, b_name)
    )


def _read(name: str, root: Path | None = None) -> str:
    p = (ROOT if root is None else root) / name
    assert p.is_file(), f"{name} missing"
    return p.read_text(encoding="utf-8")


NOT_APPLICABLE = (
    "NOT_APPLICABLE: CLAUDE.md is a symlink resolving to AGENTS.md, so a text "
    "comparison would compare one file with itself and pass by construction; "
    "parity is enforced structurally by test_live_pair_structural_parity"
)


def is_linked_pair(root: Path) -> bool:
    """True when CLAUDE.md and AGENTS.md under ``root`` are the same file."""
    a, c = root / "AGENTS.md", root / "CLAUDE.md"
    assert a.is_file(), "AGENTS.md missing"
    assert c.is_file(), "CLAUDE.md missing (or a dangling symlink)"
    return os.path.samefile(a, c)


def text_parity_diff(root: Path) -> str:
    """Strip-and-compare of two *distinct* files; '' when equal outside blocks."""
    assert not is_linked_pair(root), NOT_APPLICABLE
    return compare(_read("AGENTS.md", root), _read("CLAUDE.md", root))


def test_live_pair_structural_parity():
    """Today: CLAUDE.md must be a symlink to AGENTS.md (one file, no drift)."""
    claude = ROOT / "CLAUDE.md"
    if not claude.is_symlink():
        pytest.skip(
            "CLAUDE.md is a regular file; parity is checked by "
            "test_live_pair_text_parity instead"
        )
    assert is_linked_pair(ROOT), (
        f"CLAUDE.md is a symlink to {os.readlink(claude)!r}, which does not "
        "resolve to AGENTS.md"
    )


def test_live_pair_text_parity():
    """Live text check; NOT_APPLICABLE (skip) while the pair is one file."""
    if is_linked_pair(ROOT):
        pytest.skip(NOT_APPLICABLE)
    diff = text_parity_diff(ROOT)
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


@pytest.mark.parametrize(
    "bad",
    [
        "a\n<!-- BEGIN X -->\nb\n",  # unterminated
        "a\n<!-- END X -->\n",  # END without BEGIN
        "<!-- BEGIN X -->\n<!-- END Y -->\n",  # mismatched names
        "<!-- BEGIN X -->\n<!-- BEGIN Y -->\n<!-- END Y -->\n<!-- END X -->\n",  # nested
    ],
)
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


# ---- regular-file controls: the path the live check takes once CLAUDE.md
# stops being a symlink (run on tmp copies of the real AGENTS.md text) ----


def _regular_pair(tmp_path: Path, claude_text: str | None = None) -> Path:
    text = _read("AGENTS.md")
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(
        text if claude_text is None else claude_text, encoding="utf-8"
    )
    assert not (tmp_path / "CLAUDE.md").is_symlink()
    return tmp_path


def test_control_e_regular_copies_identical_pass(tmp_path):
    root = _regular_pair(tmp_path)
    assert not is_linked_pair(root)
    assert text_parity_diff(root) == ""


def test_control_e_regular_copy_drift_outside_blocks_fails(tmp_path):
    text = _read("AGENTS.md")
    root = _regular_pair(tmp_path, text + "\nextra drift sentence\n")
    diff = text_parity_diff(root)
    assert "+extra drift sentence" in diff


def test_control_e_regular_copy_drift_inside_block_passes(tmp_path):
    text = _read("AGENTS.md")
    m = re.search(r"^<!-- BEGIN .+? -->$", text, re.MULTILINE)
    assert m, "expected at least one marker block in AGENTS.md"
    drifted = text[: m.end()] + "\nin-block only change" + text[m.end() :]
    root = _regular_pair(tmp_path, drifted)
    assert text_parity_diff(root) == ""


def test_control_f_symlinked_pair_is_not_applicable(tmp_path):
    """A symlinked pair must be reported NOT_APPLICABLE, never compared."""
    (tmp_path / "AGENTS.md").write_text(_read("AGENTS.md"), encoding="utf-8")
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    assert is_linked_pair(tmp_path)
    with pytest.raises(AssertionError, match="NOT_APPLICABLE"):
        text_parity_diff(tmp_path)
