"""Packet lint for docs/decision-record-review-packets/ (issue #371).

A review packet is input to the owner's two-key ceremony. It ratifies nothing.
This lint checks the *shape* of the 15 packets and nothing else: it does not
establish that any record is ratified, faithful, or correct, and a PASS here is
bookkeeping about the packets only.

Checks (see ``lint``):
  * exactly the 15 expected packets exist, no more, no fewer;
  * every required heading is present (GPL-boundary and product-question
    sections where the issue requires them);
  * the Status quoted in the packet equals the live Status entry of the record
    file (whitespace-normalised, label stripped) -- so a record whose Status
    later flips turns its packet STALE (this lint FAILs) rather than silently
    describing a state that no longer holds;
  * the reviewer's choice set lists options with unchecked boxes and no option
    is marked chosen/selected/recommended;
  * no packet states a disposition as a result, and each says the disposition
    is pending the owner's two-key ceremony.

Failure controls (run live by the tests below and by ``python3 <this file>
--controls``, which prints the failing lint output for each):
  (a) a packet whose quoted Status differs from the record,
  (b) a missing packet,
  (c) a packet that marks a disposition chosen.
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKETS = REPO / "docs" / "decision-record-review-packets"
RECORDS = REPO / "decision-records"

IDS = ("0003", "0004", "0006", "0007", "0008", "0009", "0010", "0011", "0012",
       "0013", "0014", "0015", "0016", "0017", "0018")
GPL_BOUNDARY = ("0003", "0004", "0012", "0014", "0015")

COMMON_HEADINGS = (
    "## Review basis",
    "## Status as quoted from the record",
    "## README index row",
    "## Decision in two sentences",
    "## Affected contracts and files",
    "## Provenance rows citing this record",
    "## Evidence and what it does not show",
    "## Reviewer's choice set",
    "## Cross-references",
    "## Prerequisite status",
)
PENDING_SENTENCE = "pending the owner's two-key ceremony"

# A packet may not mark any option chosen, and may not state a disposition as
# a result. Quoted record text (lines starting with ">") is exempt: the records
# themselves say "pending owner ratification" and the like.
CHOSEN_MARKS = (
    re.compile(r"\[[xX✓✔]\]"),
    re.compile(r"[✅✔☑]"),
    re.compile(r"\((?:chosen|selected|recommended|taken)\)", re.I),
    re.compile(r"\*\*(?:chosen|selected|recommended)\*\*", re.I),
    re.compile(r"(?:->|=>|←|→)\s*(?:chosen|selected|recommended)", re.I),
    re.compile(r"^\s*(?:chosen|selected) (?:option|disposition)\s*:", re.I | re.M),
)
RESULT_PHRASES = re.compile(
    r"\b(?:is|was|been|now|hereby|are|as)\s+(?:ratified|accepted)\b",
    re.I,
)


def status_entry(lines: list[str]) -> str | None:
    """Return the normalised text of the Status bullet (label stripped)."""
    out: list[str] = []
    on = False
    for line in lines:
        if not on:
            m = re.match(r"- \*\*Status(?::\*\*|\*\*:)\s*(.*)$", line)
            if m:
                on = True
                out.append(m.group(1))
        elif line.startswith("  "):
            out.append(line.strip())
        else:
            break
    if not on:
        return None
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def record_path(rec_dir: Path, rid: str) -> Path | None:
    hits = sorted(rec_dir.glob(f"{rid}-*.md"))
    return hits[0] if len(hits) == 1 else None


def quoted_status(packet_text: str) -> str | None:
    lines = packet_text.splitlines()
    try:
        i = lines.index("## Status as quoted from the record")
    except ValueError:
        return None
    quoted: list[str] = []
    for line in lines[i + 1:]:
        if line.startswith("## "):
            break
        if line.startswith(">"):
            quoted.append(line[1:][1:] if line.startswith("> ") else line[1:])
    return status_entry(quoted)


def lint(packet_dir: Path = PACKETS, rec_dir: Path = RECORDS) -> list[str]:
    errs: list[str] = []
    expected = {f"{rid}.md" for rid in IDS}
    present = {p.name for p in packet_dir.glob("*")} if packet_dir.is_dir() else set()
    for name in sorted(expected - present):
        errs.append(f"{name}: packet missing")
    for name in sorted(present - expected):
        errs.append(f"{name}: unexpected file (exactly 15 packets are in scope)")

    for rid in IDS:
        p = packet_dir / f"{rid}.md"
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        rec = record_path(rec_dir, rid)
        if rec is None:
            errs.append(f"{rid}: record file not found / ambiguous in {rec_dir}")
            continue
        live = status_entry(rec.read_text(encoding="utf-8").splitlines())
        if live is None:
            errs.append(f"{rid}: record has no Status entry")
        else:
            got = quoted_status(text)
            if got is None:
                errs.append(f"{rid}: no quoted Status block in packet")
            elif got != live:
                errs.append(
                    f"{rid}: quoted Status differs from the live record Status\n"
                    f"      packet: {got[:120]}\n      record: {live[:120]}"
                )

        headings = set(COMMON_HEADINGS)
        if rid in GPL_BOUNDARY:
            headings.add("## GPL-boundary context")
        if rid == "0011":
            headings.add("## Product question (this record is not a ratification candidate)")
        for h in sorted(headings):
            if not re.search(rf"^{re.escape(h)}$", text, re.M):
                errs.append(f"{rid}: missing heading {h!r}")

        for label, pat in (
            ("record git blob", r"- Record git blob: `[0-9a-f]{40}`"),
            ("record sha256", r"- Record sha256: `[0-9a-f]{64}`"),
            ("base SHA", r"- Base SHA reviewed: `[0-9a-f]{40}`"),
        ):
            if not re.search(pat, text):
                errs.append(f"{rid}: missing/ill-formed {label}")
        if not re.search(r"^```text\n\| \[" + rid + r"\]\(", text, re.M):
            errs.append(f"{rid}: README index row not quoted")

        if PENDING_SENTENCE not in text:
            errs.append(f"{rid}: does not say the disposition is {PENDING_SENTENCE}")

        body = "\n".join(l for l in text.splitlines() if not l.startswith(">"))
        for rx in CHOSEN_MARKS:
            m = rx.search(body)
            if m:
                errs.append(f"{rid}: an option is marked chosen: {m.group(0)!r}")
        m = RESULT_PHRASES.search(body)
        if m:
            errs.append(f"{rid}: states a disposition as a result: {m.group(0)!r}")

        if rid == "0011":
            if "#25" not in text or "not in #371" not in text:
                errs.append("0011: must send the decision to #25, not #371")
            if "Product owner takes" not in text:
                errs.append("0011: product-owner option list missing")
        else:
            for opt in ("**Ratify.**", "**Amend.**", "**Reject.**"):
                if f"- [ ] {opt}" not in text:
                    errs.append(f"{rid}: choice-set option {opt} missing or not an unchecked box")
        if rid in GPL_BOUNDARY:
            for needle in ("option (a)", "0002", "cite with provenance"):
                if needle not in text:
                    errs.append(f"{rid}: GPL-boundary section lacks {needle!r}")
        if rid == "0016" and "0017" not in text:
            errs.append("0016: must cross-reference 0017")
        if rid == "0017" and "0016" not in text:
            errs.append("0017: must cross-reference 0016")
    return errs


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------
def _copy_packets(tmp: Path) -> Path:
    dst = tmp / "packets"
    shutil.copytree(PACKETS, dst)
    return dst


def control_a_status_differs(tmp: Path) -> list[str]:
    d = _copy_packets(tmp)
    p = d / "0003.md"
    t = p.read_text(encoding="utf-8")
    assert "PROPOSED — pending owner ratification" in t
    p.write_text(t.replace("PROPOSED — pending owner ratification",
                           "PROPOSED — pending owner review", 1), encoding="utf-8")
    return lint(d)


def control_b_missing_packet(tmp: Path) -> list[str]:
    d = _copy_packets(tmp)
    (d / "0009.md").unlink()
    return lint(d)


def control_c_marks_chosen(tmp: Path) -> list[str]:
    d = _copy_packets(tmp)
    p = d / "0006.md"
    t = p.read_text(encoding="utf-8")
    assert "- [ ] **Ratify.**" in t
    p.write_text(t.replace("- [ ] **Ratify.**", "- [x] **Ratify.**", 1), encoding="utf-8")
    return lint(d)


def control_c2_states_result(tmp: Path) -> list[str]:
    d = _copy_packets(tmp)
    p = d / "0012.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nThis record is ratified.\n", encoding="utf-8")
    return lint(d)


def test_live_packets_lint_clean():
    errs = lint()
    assert not errs, "\n".join(errs)


def test_exactly_15_packets_one_per_record():
    assert len(IDS) == 15
    assert sorted(p.name for p in PACKETS.glob("*")) == sorted(f"{r}.md" for r in IDS)


def test_control_a_quoted_status_differs_fails(tmp_path):
    errs = control_a_status_differs(tmp_path)
    assert any("0003" in e and "quoted Status differs" in e for e in errs), errs


def test_control_b_missing_packet_fails(tmp_path):
    errs = control_b_missing_packet(tmp_path)
    assert any(e.startswith("0009.md: packet missing") for e in errs), errs


def test_control_c_marked_chosen_fails(tmp_path):
    errs = control_c_marks_chosen(tmp_path)
    assert any("0006" in e and "marked chosen" in e for e in errs), errs
    errs = control_c2_states_result(tmp_path / "2") if (tmp_path / "2").mkdir() is None else []
    assert any("0012" in e and "disposition as a result" in e for e in errs), errs


def test_status_extractor_handles_wrapped_and_qualified_statuses():
    wrapped = status_entry(RECORDS.joinpath(
        "0016-int16-tail-shape-leg-floor.md").read_text(encoding="utf-8").splitlines())
    assert wrapped and wrapped.startswith("RECORDED") and "AMENDED 2026-09-27" in wrapped
    qualified = status_entry(RECORDS.joinpath(
        "0010-lp24-pinned-kernel-harness.md").read_text(encoding="utf-8").splitlines())
    assert qualified == "PROPOSED — pending owner ratification (leaf-scoped)"


def main(argv: list[str]) -> int:
    if "--controls" not in argv:
        errs = lint()
        print("\n".join(errs) if errs else "PASS: 15 packets lint clean")
        return 1 if errs else 0
    rc = 0
    for name, fn in (("(a) quoted Status differs from record", control_a_status_differs),
                     ("(b) missing packet", control_b_missing_packet),
                     ("(c) option marked chosen", control_c_marks_chosen),
                     ("(c') disposition stated as a result", control_c2_states_result)):
        with tempfile.TemporaryDirectory() as t:
            errs = fn(Path(t))
        print(f"--- control {name}: lint {'FAILED as required' if errs else 'DID NOT FAIL (control broken)'}")
        for e in errs:
            print("   ", e)
        rc |= 0 if errs else 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
