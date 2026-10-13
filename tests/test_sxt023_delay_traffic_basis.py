#!/usr/bin/env python3
"""#367 -- Delay external-memory traffic is stated on ONE basis.

What this pins, and what it does NOT:

  * PINS: no live (non-superseded) statement in the tracked tree pairs the
    per-sample read count (24) with the per-block write count (64), i.e. the
    mixed-basis forms "24 reads + 64 writes per frame" / "88 accesses/frame".
    The old wording may survive only (a) inside the two sha256-pinned PR #44
    records that cannot be edited (`reports/sxt-023/EVIDENCE.md` row A6 and
    `reports/sxt-023/artifacts/ext_mem_traffic.json`), whose bytes are checked
    unchanged here, and (b) as explicitly quoted, superseded history in
    `reports/sxt-023/followup.md`, which is the visible superseding record.
  * PINS: the live interface contract `rtl/effects/delay/ext_mem_if.md`
    states 24 reads + 2 writes per sample and 768 reads + 64 writes per
    32-sample block, and both committed PR #44 counters independently imply
    the same block count (8,790) on that basis.
  * DOES NOT: establish RTL exactness, model-vs-Surge fidelity, synthesis,
    or any hardware memory measurement. The counter check is metadata
    consistency over committed numbers only; nothing is re-rendered.
"""

import hashlib
import json
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = os.path.relpath(os.path.abspath(__file__), REPO)

IF_DOC = "rtl/effects/delay/ext_mem_if.md"
FOLLOWUP = "reports/sxt-023/followup.md"
EVIDENCE = "reports/sxt-023/EVIDENCE.md"
TRAFFIC = "reports/sxt-023/artifacts/ext_mem_traffic.json"

# PR #44 records: immutable historical evidence. EVIDENCE.md's digest is the
# one carried by reports/coverage-v1/coverage.json; editing either file would
# turn committed records STALE, so the bad wording in them is superseded by
# followup.md rather than corrected in place.
PINNED_HISTORY = {
    EVIDENCE: "6d8fa5f3cc6f25b087f24add0655bb53cc6725da7f903188394ad32979381763",
    TRAFFIC: "7eb80314823862e2add8df45687ebd4fbaf7d97fb80650d748060d130fe125c6",
}

BLOCK = 32
READS_PER_SAMPLE = 24   # 12-tap sinc x 2 channels
WRITES_PER_SAMPLE = 2   # 1 word x 2 channels
EXPECTED_BLOCKS = 8790

# Mixed-basis forms: per-sample reads paired with per-block writes.
MIXED = [
    re.compile(r"\b24\s+(?:line\s+)?reads?\s*(?:\([^)]*\)\s*)?\+\s*64\s+"
               r"(?:line\s+)?writes?", re.I),
    re.compile(r"\b24\s*r\s*\+\s*64\s*w\b", re.I),
    re.compile(r"\b88\s+accesses\b", re.I),
]

TEXT_EXT = (".md", ".txt", ".py", ".sv", ".v", ".json", ".yml", ".yaml",
            ".toml", ".tex", ".csv", ".sh")


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def _paragraphs(text):
    """Yield (start_line, paragraph_text) for blank-line separated blocks."""
    start, buf = 1, []
    for i, line in enumerate(text.split("\n"), 1):
        if line.strip():
            if not buf:
                start = i
            buf.append(line)
        elif buf:
            yield start, "\n".join(buf)
            buf = []
    if buf:
        yield start, "\n".join(buf)


def _quoted_spans(par):
    return [(m.start(), m.end()) for m in re.finditer(r'"[^"]*"', par)]


def _is_superseded_quote(par, start, end):
    """An old-wording hit is allowed only when it lies inside a double-quoted
    span AND its paragraph says why: it names the issue that supersedes it
    (#367) and that the pinned source is not edited."""
    inside = any(a <= start and end <= b for a, b in _quoted_spans(par))
    marked = "#367" in par and "not edited" in par
    return inside and marked


def mixed_basis_violations(rel, text, allow_quoted=False):
    """Return [(rel, line, match)] for each live mixed-basis statement."""
    out = []
    for line0, par in _paragraphs(text):
        for pat in MIXED:
            for m in pat.finditer(par):
                if allow_quoted and _is_superseded_quote(par, m.start(), m.end()):
                    continue
                line = line0 + par.count("\n", 0, m.start())
                out.append((rel, line, m.group(0)))
    return out


def _tracked_text_files():
    try:
        res = subprocess.run(["git", "-C", REPO, "ls-files", "-z"],
                             capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        pytest.skip(f"git ls-files unavailable: {e}")
    for rel in res.stdout.decode().split("\0"):
        if rel and rel.endswith(TEXT_EXT) and os.path.isfile(
                os.path.join(REPO, rel)):
            yield rel


# --- (a) structural scan ---------------------------------------------------

def test_no_live_mixed_basis_statement_in_tree():
    bad = []
    scanned = 0
    for rel in _tracked_text_files():
        if rel == SELF or rel in PINNED_HISTORY:
            continue
        try:
            text = _read(rel)
        except UnicodeDecodeError:
            continue
        scanned += 1
        bad += mixed_basis_violations(rel, text, allow_quoted=(rel == FOLLOWUP))
    assert scanned > 100, f"scan coverage too small ({scanned} files)"
    assert not bad, f"live mixed-basis Delay traffic statements: {bad}"


def test_pinned_history_bytes_unchanged_and_superseded():
    for rel, digest in PINNED_HISTORY.items():
        with open(os.path.join(REPO, rel), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == digest, rel
    # They still carry the old wording (that is why they need superseding) ...
    assert mixed_basis_violations(EVIDENCE, _read(EVIDENCE))
    t = json.loads(_read(TRAFFIC))
    assert t["per_frame_per_instance"]["total_accesses"] == 88
    assert t["frames_rendered"] == 8550
    # ... and followup.md is the visible superseding record for both.
    fu = _read(FOLLOWUP)
    assert "EVIDENCE.md` A6" in fu and "ext_mem_traffic.json" in fu
    assert "frames_rendered: 8550" in fu and "8,790 blocks" in fu
    assert "#367" in fu


def test_followup_old_wording_allowed_only_as_superseded_quote():
    fu = _read(FOLLOWUP)
    # Superseded-history control: the quoted old wording is present ...
    assert mixed_basis_violations(FOLLOWUP, fu, allow_quoted=False)
    # ... and is tolerated only because it is quoted and marked.
    assert not mixed_basis_violations(FOLLOWUP, fu, allow_quoted=True)
    # Removing the quotes makes the same text a live statement -> fails.
    unquoted = fu.replace('"24 line reads + 64 writes per frame = 88 '
                          'accesses/frame"',
                          "24 line reads + 64 writes per frame = 88 "
                          "accesses/frame")
    assert unquoted != fu
    assert mixed_basis_violations(FOLLOWUP, unquoted, allow_quoted=True)


def test_interface_contract_states_one_basis():
    doc = _read(IF_DOC)
    assert not mixed_basis_violations(IF_DOC, doc)
    row_r = re.search(r"^\| reads \| \*\*(\d+)\*\*[^|]*\| \*\*(\d+)\*\*", doc, re.M)
    row_w = re.search(r"^\| writes \| \*\*(\d+)\*\*[^|]*\| \*\*(\d+)\*\*", doc, re.M)
    assert row_r and row_w, "traffic table rows not found"
    r_s, r_b = map(int, row_r.groups())
    w_s, w_b = map(int, row_w.groups())
    assert (r_s, w_s) == (READS_PER_SAMPLE, WRITES_PER_SAMPLE)
    assert (r_b, w_b) == (r_s * BLOCK, w_s * BLOCK) == (768, 64)
    assert "per sample" in doc and "per 32-sample block" in doc


# --- (c) live negative control --------------------------------------------

OLD_TABLE = """\
| reads | **24** (12-tap sinc × 2 channels) | `Delay.h:365-378` |
| writes | **64** (32 samples × 2 channels) | `Delay.h:434-441` |
| total | 88 accesses/frame/instance | counted by the RTL sim |
"""
OLD_A6 = ("24 line reads (12-tap sinc × 2 ch) + 64 writes (32 × 2 ch) per "
          "frame per instance = 88 accesses")


@pytest.mark.parametrize("injected", [OLD_TABLE, OLD_A6,
                                      "24r + 64w per frame"])
def test_negative_control_mixed_basis_fails(injected):
    doc = _read(IF_DOC) + "\n\n" + injected + "\n"
    assert mixed_basis_violations(IF_DOC, doc), injected
    # Being in followup.md does not help unless it is a marked quote.
    assert mixed_basis_violations(FOLLOWUP, _read(FOLLOWUP) + "\n\n" + injected,
                                  allow_quoted=True)


# --- (b) counter-implied block count --------------------------------------

def _blocks(count, per_block):
    q, r = divmod(count, per_block)
    return q if r == 0 else None


def test_both_counters_imply_8790_blocks():
    c = json.loads(_read(TRAFFIC))["measured_model_counters_at_last_checkpoint"]
    reads, writes = c["ext_reads"], c["ext_writes"]
    assert (reads, writes) == (6_750_720, 562_560)
    br = _blocks(reads, READS_PER_SAMPLE * BLOCK)
    bw = _blocks(writes, WRITES_PER_SAMPLE * BLOCK)
    assert br == bw == EXPECTED_BLOCKS


@pytest.mark.parametrize("r_den,w_den", [
    (24, 64),     # the mixed basis: per-sample reads, per-block writes
    (24, 2),      # per-sample basis: consistent, but counts samples (281,280)
    (768, 2),
    (88, 88),     # "88 accesses/frame" as a total denominator
])
def test_changed_denominator_rejected(r_den, w_den):
    c = json.loads(_read(TRAFFIC))["measured_model_counters_at_last_checkpoint"]
    br = _blocks(c["ext_reads"], r_den)
    bw = _blocks(c["ext_writes"], w_den)
    assert not (br == bw == EXPECTED_BLOCKS)
    if (r_den, w_den) == (88, 88):
        assert _blocks(c["ext_reads"] + c["ext_writes"], 88) is None


def test_basis_matches_model_constants():
    """The 24/2 per-sample basis is the model's own constants, not a copy."""
    from model.effects.delay import delay_model as dm  # noqa: E402
    assert dm.BLOCK == BLOCK
    assert dm.DelayModel.TAP_READS * 2 == READS_PER_SAMPLE
