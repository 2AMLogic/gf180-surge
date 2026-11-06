#!/usr/bin/env python3
"""SXT-019 provenance audit — negative-control (self-test) scaffolding.

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or control was changed, reordered or reflowed). This module holds the
synthetic-tree fixture builders and the `_*_controls` self-tests that prove
every audit rule still fires on a deliberate violation. The audit rules, the
declared limits and the CLI (including the `--negative-control` flag, which
calls `run_negative_control` here) stay in `check_provenance.py`; this module
imports the audit from there and never the other way round at import time.
"""

from __future__ import annotations

import base64
import bz2
import gzip
import io
import json
import lzma
import struct
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

from check_provenance import (
    AuditError,
    BY_REFERENCE_CLASS,
    CAVEAT,
    COPYRIGHT_SIGN_CHAR,
    INDEX_REL,
    MANIFEST_REL,
    RECORD_DIR_REL,
    REGISTER_EXCEPTION_COLUMNS,
    REGISTER_EXCEPTION_SECTION,
    REGISTER_EXCLUSION_COLUMNS,
    REGISTER_EXCLUSION_SECTION,
    REGISTER_GPL_SECTION,
    REGISTER_MIT_SECTION,
    REGISTER_REL,
    REGISTER_ROW_COLUMNS,
    RULES,
    SCHEMA_VERSION,
    TIP_ABSENT,
    TIP_ANSWERED,
    TRIPWIRE_RULES,
    audit,
    audit_history,
)


# --- negative control (self-test) --------------------------------------------


SKELETON_RECORD = """# 0001: Example quoted constants (synthetic)

- **Status**: ratified
- **Date**: 2026-01-01

## Decision

Synthetic record used only by the provenance audit's negative control.
"""

SKELETON_INDEX = """# Decision records

## Index

| Number | Title | Status | Date |
|---|---|---|---|
| [0001](0001-example.md) | Example quoted constants (synthetic) | ratified | 2026-01-01 |
"""

SKELETON_CARRIER = '''"""Synthetic carrier.

Constants below are QUOTED as data from
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71;
licensing decision: decision-records/0001-example.md.
"""

TABLE = [1, 2, 3]
'''


def _write(root: Path, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _register_table(columns, rows):
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "---|" * len(columns),
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


SKELETON_REGISTER_ROW = [
    "G-1",
    "model/carrier.py",
    "TABLE",
    "synthetic/upstream.h",
    "58914e59c608ed4384ba6002e44c3465c58b2e71",
    "GPL-3.0-or-later",
    "0001",
    "manifest:model/carrier.py",
    "registered",
    "synthetic",
]


def skeleton_register(gpl_rows=(SKELETON_REGISTER_ROW,), exceptions=(), exclusions=()):
    """The register that matches `build_skeleton`'s one quoted-constants row."""
    text = "# GPL-boundary register (synthetic)\n\n"
    for name, columns, rows in (
        (REGISTER_GPL_SECTION, REGISTER_ROW_COLUMNS, gpl_rows),
        (REGISTER_MIT_SECTION, REGISTER_ROW_COLUMNS, ()),
        (REGISTER_EXCEPTION_SECTION, REGISTER_EXCEPTION_COLUMNS, exceptions),
        (REGISTER_EXCLUSION_SECTION, REGISTER_EXCLUSION_COLUMNS, exclusions),
    ):
        text += f"## {name}\n\n" + _register_table(columns, rows) + "\n"
    return text


def build_skeleton(root: Path):
    """A minimal tree that must audit clean."""
    _write(root, REGISTER_REL, skeleton_register())
    _write(root, f"{RECORD_DIR_REL}/0001-example.md", SKELETON_RECORD)
    _write(root, INDEX_REL, SKELETON_INDEX)
    _write(root, "model/carrier.py", SKELETON_CARRIER)
    _write(root, "docs/plain.md", "A document with no third-party content.\n")
    _write(
        root,
        MANIFEST_REL,
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "scan_floor": 1,
                "scope_exclusions": [],
                "entries": [
                    {
                        "path": "model/carrier.py",
                        "class": "quoted-constants",
                        "content": "synthetic TABLE",
                        "upstream": "synthetic upstream",
                        "pinned_commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
                        "upstream_license": "GPL-3.0-or-later",
                        "decision_record": "0001",
                        "covers": ["self-declared-quotation"],
                    }
                ],
                "exemptions": [],
            },
            indent=2,
        )
        + "\n",
    )


# NOTE — the fixture strings below are deliberately assembled from fragments.
# If this file contained a contiguous foreign license body, copyright line or
# decision-record citation, the audit would (correctly) flag its own source as
# unattributed carriage — and the only ways out would be to exempt a
# non-exemptible rule or to special-case the audit's own path, both of which
# would punch a hole in the rule set. Assembling at runtime keeps the rules
# intact and the synthetic violations byte-identical to the real thing. Do not
# "tidy" these into single literals.
FIXTURE_GPL_BODY = (
    '"""Helper.\n\n'
    + "GNU GENERAL "
    + "PUBLIC LICENSE Version 3\n"
    + "Copy"
    + "right (C) 20"
    + "16 Somebody Else\n"
    + "This program is "
    + 'free software.\n"""\n'
)
FIXTURE_RECORD_CITATION = "Licensing: see " + "decision-records/" + "0099.\n"
FIXTURE_TRANSCRIBED = (
    '"""Table '
    + "transcribed from "
    + "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71.\n"
    + '"""\n\nT = [4, 5, 6]\n'
)


# An in-repo document that cites the pinned upstream AND says it carries a
# verbatim copy of this project's OWN model (the model/oscillators/classic
# README shape that landed with #181). Plus a genuinely foreign quotation, in
# the SAME marker wording, that an occurrence-scoped exemption must not hide.
FIXTURE_OWN_COPY_DOC = (
    "Pinned structure (read and cited, never copied): "
    + "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71.\n\n"
    + "`run_model.py` instantiates the shared `voice_model.HalfbandD2`, and\n"
    + "`tb_own.sv` carries a\nverbatim copy of it.\n"
)
FIXTURE_OWN_COPY_OCCURRENCE = "`tb_own.sv` carries a verbatim copy of it"
FIXTURE_FOREIGN_COPY_LINE = (
    "\nThe table below is copied verbatim from the pinned upstream wavetable.\n"
)
# The adversarial shape the occurrence scoping did NOT catch before #260: the
# named sentence repeated WORD FOR WORD with a foreign referent. Wording alone
# cannot separate it from the legitimate self-copy, so a duplicated occurrence
# is reported as ambiguous instead of being exempted twice.
FIXTURE_DUPLICATE_OCCURRENCE_LINE = (
    "\nThe upstream Surge oscillator: `tb_own.sv` carries a verbatim copy of it.\n"
)


# --- masking fixtures ---------------------------------------------------------
#
# Our OWN attribution above a pasted upstream one. This is how the
# non-exemptible `foreign-license-text` rule was disarmed before: the signal
# read only the FIRST copyright line / SPDX tag in a file, and judged that
# line's holder from a ±120-char window that any nearby mention of this
# project satisfied. Both shapes below audited clean until the fix; both must
# fail now, and our own attribution alone must still audit clean (a rule that
# fires on our own header would just be turned off again).
# Assembled from fragments, like the fixtures above — see the fixture note.
FIXTURE_OWN_COPYRIGHT = "# Copy" + "right 20" + "26 2AM" + "Logic\n"
FIXTURE_OWN_SPDX_TAG = "# SPDX-License" + "-Identifier" + ": Apache-2.0\n"
FIXTURE_OWN_PROJECT_LINE = "# This module belongs to the gf180-surge model.\n"
FIXTURE_FOREIGN_COPYRIGHT_LINE = "# Copy" + "right (C) 20" + "19 Some Upstream Author\n"
FIXTURE_FOREIGN_SPDX_TAG = "# SPDX-License" + "-Identifier" + ": GPL-3.0-or-later\n"

# Increment 3 — the same masking one level in. Each of these audited clean on
# the non-exemptible rule while every rule still "fired" in the self-test:
#
#   * our project named in the foreign notice's own HOLDER line (a
#     parenthetical, or after a spaced hyphen) — the line-scoped holder test
#     from increment 2 read the whole line, so the mention suppressed it;
#   * an SPDX *expression* whose leading operand is our own licence — only the
#     first whitespace-delimited word was compared, so every other operand was
#     invisible (and `Apache-2.0 OR <foreign>` is the standard dual-licence
#     spelling, not an exotic one);
#   * a license body wrapped mid-phrase across a comment leader — the plain
#     `\s+` between words does not span `"\n# "`, and the multi-word prefilter
#     did not survive the wrap either.
FIXTURE_FOREIGN_COPYRIGHT_PARENTHETICAL = (
    "# Copy" + "right (C) 20" + "19 Some Upstream Author (adapted for gf180-surge)\n"
)
FIXTURE_FOREIGN_COPYRIGHT_AFTER_DASH = (
    "# Copy" + "right 20" + "19 Chris Johnson - reworked for gf180-surge\n"
)
FIXTURE_COMPOUND_SPDX_OWN_FIRST = (
    "# SPDX-License" + "-Identifier" + ": Apache-2.0 OR GPL-3.0-or-later\n"
)
FIXTURE_WRAPPED_FSF_BODY = (
    "#  This program is " + "free\n#  software; you can redistribute it.\n"
)
FIXTURE_WRAPPED_GPL_TITLE = "/*\n * GNU " + "GENERAL\n * PUBLIC " + "LICENSE Version 3\n */\n"
# Positive controls: own-attribution layouts that ALSO put a name-like aside or
# a spaced hyphen on the notice line, plus an SPDX tag quoted inside prose.
# A fix that flagged these would be reverted, and the rule with it.
FIXTURE_OWN_COPYRIGHT_WITH_ASIDE = (
    "# Copy" + "right 20" + "26 2AM" + "Logic (gf180-surge model sources)\n"
)
FIXTURE_OWN_COPYRIGHT_AUTHORS = "# Copy" + "right (c) 20" + "26 The gf180-surge Authors\n"
FIXTURE_OWN_COPYRIGHT_AFTER_DASH = "# Copy" + "right 20" + "26 - 2AM " + "Logic\n"
FIXTURE_OWN_SPDX_IN_PROSE = (
    "# The SPDX-License" + "-Identifier" + ": Apache-2.0 tags below are ours.\n"
)
# The deliberate scope boundary (declared, not an oversight): a LEADERLESS
# prose wrap of a license NAME is not a comment-block paste, and is not
# treated as carriage — otherwise ordinary text that names a license would
# become a finding that no exemption could answer (the rule is non-exemptible).
FIXTURE_PROSE_WRAP_LICENSE_NAME = (
    "The record cites the GNU " + "General Public\n" + "License as the upstream terms.\n"
)

# Increment 4 — four more families that audited clean while --negative-control
# still reported every rule firing. All four are the SAME failure shape as
# increments 2 and 3: a signal that stops reading as soon as it has seen enough
# to recognise OUR OWN attribution.
#
#   * the holder field opens with a delimiter, so it held no name and the holder
#     test fell back to searching the WHOLE LINE — the very thing increment 3
#     removed, reinstated for every bracket/semicolon/dash layout;
#   * an SPDX expression whose foreign operand sits past the end of the
#     parseable expression (a comma list, a parenthetical);
#   * a notice with a holder but NO year, which carried no signal at all;
#   * a holder list WRAPPED onto a continuation line that carries no keyword.
FIXTURE_FOREIGN_HOLDER_BEHIND_BRACKETS = (
    "# Copy" + "right (C) 20" + "19 [gf180-surge] Some Upstream Author\n"
)
FIXTURE_FOREIGN_HOLDER_BEHIND_PARENS = (
    "# Copy" + "right (C) 20" + "19 (gf180-surge port) Some Upstream Author\n"
)
FIXTURE_FOREIGN_HOLDER_AFTER_SEMICOLON = (
    "# Copy" + "right 20" + "19; gf180-surge adaptation of Chris Johnson's filter\n"
)
FIXTURE_FOREIGN_HOLDER_AFTER_EM_DASH = (
    "# Copy" + "right 20" + "19 — gf180-surge vendoring of Chris Johnson\n"
)
FIXTURE_SPDX_FOREIGN_AFTER_COMMA = (
    "# SPDX-License" + "-Identifier" + ": Apache-2.0, GPL-3.0-or-later\n"
)
FIXTURE_SPDX_FOREIGN_IN_PARENTHETICAL = (
    "# SPDX-License" + "-Identifier" + ": Apache-2.0 (upstream GPL-3.0-or-later)\n"
)
FIXTURE_YEARLESS_FOREIGN_COPYRIGHT = (
    "# Copy" + "right (C) " + "Chris Johnson / Airwindows\n"
)
FIXTURE_WRAPPED_HOLDER_LIST = (
    FIXTURE_OWN_COPYRIGHT + "#     and " + "Chris Johnson / Airwindows\n"
)
# Positive controls for increment 4: own-attribution and ordinary prose layouts
# that the four fixes above could plausibly have started flagging. Each one is a
# shape that really occurs in this repository (lettered list markers are used
# throughout the decision records and evidence reports), and a false positive
# here would be UNANSWERABLE — `foreign-license-text` cannot be exempted — so
# the rule would be switched off rather than answered.
FIXTURE_OWN_COPYRIGHT_RIGHTS_RESERVED = (
    "# Copy" + "right (c) 20" + "26 2AM " + "Logic, All Rights Reserved.\n"
)
FIXTURE_OWN_COPYRIGHT_CROSS_REFERENCE = (
    "# Copy" + "right 20" + "26 2AM " + "Logic. See LICENSE for terms.\n"
)
FIXTURE_OWN_COPYRIGHT_QUOTED_IN_PROSE = (
    "The header reads \"Copy" + "right (c) 20" + "26 The gf180-surge Authors\". "
    "Anything else names someone else.\n"
)
FIXTURE_OWN_DASH_HOLDER_WITH_ASIDE = (
    "# Copy" + "right 20" + "26 - 2AM " + "Logic (SXT-019 governance)\n"
)
FIXTURE_OWN_COPYRIGHT_THEN_PROSE = (
    FIXTURE_OWN_COPYRIGHT + "# Implements the halfband decimator.\n"
)
FIXTURE_LETTERED_LIST_MARKERS = (
    "## (c) Unknown status string\n\n"
    "| leg | control |\n| --- | --- |\n| (c) | status `DONE` rejected |\n"
)
# Increment 5 — the holder list continues past the NEXT delimiter on the SAME
# line. The segment walk from increment 4 judged the first segment holding a
# name and returned, so a second holder standing after that segment's closing
# delimiter was never read: the same "stop as soon as our own name is
# recognised" shape, one segment to the right. All four audited clean while
# --negative-control reported every rule firing, and all four are how a
# part-vendored file actually gets attributed.
FIXTURE_SECOND_HOLDER_AFTER_SEMICOLON = (
    "# Copy" + "right 20" + "26 2AM " + "Logic; Some Upstream Author\n"
)
FIXTURE_SECOND_HOLDER_IN_PARENTHETICAL = (
    "# Copy" + "right (c) 20" + "26 2AM " + "Logic (from Chris Johnson)\n"
)
FIXTURE_SECOND_HOLDER_AFTER_EM_DASH = (
    "# Copy" + "right 20" + "26 2AM " + "Logic — Chris Johnson\n"
)
FIXTURE_SECOND_HOLDER_AFTER_DASH = (
    "# Copy" + "right 20" + "26 2AM " + "Logic - Some Upstream Author\n"
)
# Positive controls for increment 5, and the two residual limits it declares
# rather than closes (see DECLARED LIMITS at the top of this file): a later
# segment is read as a holder only on a TWO-WORD name shape, and only before the
# segment's first sentence break. Both bounds exist because an own notice that
# became a finding on this non-exemptible rule would be unanswerable.
FIXTURE_OWN_SINGLE_NAME_ASIDE = (
    "# Copy" + "right 20" + "26 2AM " + "Logic (generated from Verilog)\n"
)
FIXTURE_OWN_NOTICE_THEN_SENTENCE = (
    "# Copy" + "right 20" + "26 2AM " + "Logic; see NOTICE. "
    "Chris Johnson's filter is discussed in the record, not carried here.\n"
)
FIXTURE_COPYRIGHT_PROSE_NOT_A_NOTICE = (
    "2. Grant of Copy" + "right License. Subject to the terms and conditions of\n"
    "this record, the Copy" + "right Notice is retained verbatim.\n"
)
# Long enough that the foreign notice is well outside the old ±120-char
# proximity window, so this control isolates the first-match-only bug.
FIXTURE_FILLER = "\n" + "".join(f"ROW_{n} = [{n}, {n}, {n}]\n" for n in range(12)) + "\n"

# Increment 6 — masking one level BELOW the signal layer. Increments 1-5 all
# assumed the file had become text; these never do. A head carrying a NUL was
# classified "binary", and `tripwire_hits` returns before every content rule
# for such a file — so an ordinary source file saved in UTF-16, or an ASCII one
# carrying a single stray NUL, took a complete GPL body, a GPL SPDX tag and a
# foreign copyright notice straight past the non-exemptible rule. Neither needs
# an exotic tool: "Unicode" is a standard editor save, and `.py`/`.sv` are not
# in FOREIGN_SOURCE_EXTS, so no extension tripwire covered them either.
FIXTURE_WIDE_NOTICE_TEXT = (
    "# Copy" + "right (C) 20" + "19 Some Upstream Author\n"
    "# This program is free " + "software; you can redistribute it\n"
    "# under the terms of the GNU " + "General Public License as published\n"
    "# by the Free " + "Software Foundation.\n"
)
# The locator each wide-encoding control requires in its finding's evidence,
# assembled from fragments for the same reason as the fixtures above.
WIDE_NOTICE_LOCATOR = "GNU " + "General Public License"
FIXTURE_UTF16_BOM_NOTICE = FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16")
FIXTURE_UTF16LE_BOMLESS_NOTICE = FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-le")
FIXTURE_UTF16BE_BOMLESS_NOTICE = FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-be")
FIXTURE_STRAY_NUL_NOTICE = (
    b"# \x00 vim: set fileencoding=utf-8 :\n" + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8")
)
# Increment 8 — the PAYLOAD layer, below the decode layer of increment 6. A
# payload the sniff refuses is not evidence-free: it is either a WRAPPER (one
# `read()` from text) or binary data with ASCII runs in it. Until this
# increment all of the fixtures below audited **clean** while
# `--negative-control` reported all 31 rules and all 41 masking controls
# behaving — demonstrated on the real tree in `reports/sxt-019/EVIDENCE.md` §14.
# Assembled from fragments like every other fixture here (see the fixture note).
FIXTURE_PAYLOAD_COPYRIGHT = "Copy" + "right (C) 20" + "19 Some Upstream Author"
PAYLOAD_COPYRIGHT_LOCATOR = "Some Upstream Author"


def _lcg_samples(count, seed=12345):
    """Deterministic pseudo-random 16-bit samples — stand-in render data.

    Noise is the worst case for the string harvest (it maximises the chance of
    an accidental printable run), which is what a positive control wants.
    """
    value = seed
    out = []
    for _ in range(count):
        value = (1103515245 * value + 12345) & 0x7FFFFFFF
        out.append((value >> 8) % 65536 - 32768)
    return out


def _riff_chunk(chunk_id: bytes, payload: bytes):
    if len(payload) % 2:
        payload += b"\x00"
    return chunk_id + struct.pack("<I", len(payload)) + payload


def _wav_payload(info_fields=(), spliced=b"", quiet=False):
    """A real 16-bit PCM WAV, optionally carrying LIST/INFO metadata.

    `ICOP` is the RIFF copyright field — exactly where an upstream sample pack
    or an exported preset render states its holder. None of this repository's
    own renders carries one.

    `spliced` is inserted into the middle of the data chunk, which is how a
    notice rides along inside a real render. `quiet` scales the samples into the
    low-amplitude range this repository's own renders mostly occupy, where the
    high byte of every sample is NUL — the shape a UTF-16-LE string also has
    (increment 10's false-positive hazard).
    """
    fmt = _riff_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16))
    samples = _lcg_samples(2400)
    if quiet:
        samples = [sample // 256 for sample in samples]
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    if spliced:
        middle = len(pcm) // 2
        pcm = pcm[:middle] + spliced + pcm[middle:]
    data = _riff_chunk(b"data", pcm)
    body = b"WAVE" + fmt
    if info_fields:
        info = b"".join(
            _riff_chunk(field, text.encode("ascii") + b"\x00")
            for field, text in info_fields
        )
        body += _riff_chunk(b"LIST", b"INFO" + info)
    body += data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _float_dump(notice=None, spliced=b"", seed=777):
    """A raw float32 dump (the `.f32` shape), optionally with a notice spliced in.

    `notice` is spliced as ASCII (increment 8); `spliced` takes raw bytes, which
    is how a re-encoded notice arrives (increment 10).
    """
    values = [sample / 32768.0 for sample in _lcg_samples(1200, seed=seed)]
    payload = struct.pack(f"<{len(values)}f", *values)
    if notice is not None:
        spliced = notice.encode("ascii")
    if not spliced:
        return payload
    middle = len(payload) // 2
    return payload[:middle] + spliced + payload[middle:]


def _tensor_payload():
    """An `.npy`-shaped payload: a short ASCII header over float data."""
    header = b"\x93NUMPY\x01\x00v\x00{'descr': '<f4', 'fortran_order': False, }"
    return header + b" " * (64 - len(header) % 64) + _float_dump()


def _zip_payload(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return buf.getvalue()


def _tar_gz_payload(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        for name, content in members:
            raw = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return gzip.compress(buf.getvalue())


FIXTURE_WAV_WITH_COPYRIGHT_CHUNK = _wav_payload(
    (
        (b"ICOP", FIXTURE_PAYLOAD_COPYRIGHT),
        (b"IART", "Some Upstream Author"),
    )
)
FIXTURE_PLAIN_PCM_WAV = _wav_payload()
FIXTURE_FLOAT_DUMP_WITH_NOTICE = _float_dump(FIXTURE_WIDE_NOTICE_TEXT)
FIXTURE_PLAIN_FLOAT_DUMP = _float_dump()
FIXTURE_TENSOR_PAYLOAD = _tensor_payload()
FIXTURE_GZIPPED_NOTICE = gzip.compress(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
FIXTURE_XZ_NOTICE = lzma.compress(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
FIXTURE_BZIP2_NOTICE = bz2.compress(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
FIXTURE_ZIP_WITH_NOTICE = _zip_payload(
    (("dsp/Reverb1.h", "/*\n" + FIXTURE_WIDE_NOTICE_TEXT + "*/\n"),)
)
FIXTURE_NPZ_WITH_NOTICE = _zip_payload(
    (("taps.npy", "x"), ("header.txt", FIXTURE_WIDE_NOTICE_TEXT))
)
FIXTURE_TAR_GZ_WITH_NOTICE = _tar_gz_payload(
    (("vendor/filter.cpp", "// " + FIXTURE_WIDE_NOTICE_TEXT),)
)
# Wrapper inside wrapper, one for each recursion site. Neither is reachable by
# the string harvest: the inner layer is itself compressed, so the notice is not
# ASCII anywhere in the outer payload's bytes. (A `.tar.gz` is NOT such a case —
# a tar stores its members uncompressed, so the harvest alone would find it.)
FIXTURE_GZIPPED_ZIP_WITH_NOTICE = gzip.compress(FIXTURE_ZIP_WITH_NOTICE)
FIXTURE_ZIP_WITH_GZIPPED_MEMBER = _zip_payload(
    (("dsp/Reverb1.h.gz", FIXTURE_GZIPPED_NOTICE),)
)
# This repository's own evidence-trace shape: a gzipped JSON trace. 18 are
# tracked, all now inflated and content-scanned, and none may become a finding.
FIXTURE_OWN_GZIPPED_TRACE = gzip.compress(
    json.dumps(
        {
            "fixture": "seq-notes-coverage-v1",
            "tool": "tools/run_fx_model.py",
            "taps": [sample / 32768.0 for sample in _lcg_samples(64, seed=31)],
        },
        indent=1,
    ).encode("utf-8")
)
# The exact payload increment 6 declared out of reach ("a notice sealed inside
# an opaque payload"), kept byte-for-byte so this increment's control is a
# direct inversion of that one: it was `masking/notice-sealed-in-an-opaque-
# payload-stays-out-of-scope`, a POSITIVE control, and is now
# `payload/notice-embedded-in-an-opaque-payload`, which must FIRE.
FIXTURE_NOTICE_IN_AN_OPAQUE_PAYLOAD = (
    bytes(range(256)) * 4
    + (FIXTURE_PAYLOAD_COPYRIGHT + "\n").encode("ascii")
    + bytes(range(256)) * 4
)
# A notice written with the sign spelling (U+00A9) rather than the word, inside
# a payload. The UTF-8 sign is not printable ASCII, so without normalisation it
# ENDS the run and takes the keyword with it: the surviving run reads
# " 2019 Some Upstream Author", which matches no prefilter at all. The sign is
# written as an ESCAPE here, like every other fixture fragment, so this file does
# not itself carry a notice (see the fixture note above).
FIXTURE_COPYRIGHT_SIGN_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=41))
    + ("\u00a9 20" + "19 Some Upstream Author\n").encode("utf-8")
    + struct.pack("<600h", *_lcg_samples(600, seed=42))
)
# Increment 10 — the WIDE-ENCODED run inside a payload. Increment 8 declared
# this out of reach ("the harvest reads ASCII"); the fixture below is kept
# BYTE-FOR-BYTE from that declaration so this increment's control is a direct
# inversion of it, exactly as increment 8 inverted increment 6's
# `masking/notice-sealed-in-an-opaque-payload-stays-out-of-scope`. It was
# `payload/wide-encoded-notice-in-a-payload-stays-out-of-scope`, a POSITIVE
# control, and is now `payload/wide-encoded-notice-in-a-payload`, which must FIRE.
FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=99))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=100))
)
# The same mask in the other byte order, in UTF-32 (both orders), and with a BOM
# in front of it — the four shapes `BOMLESS_WIDE_ENCODINGS` and `BOM_ENCODINGS`
# already name at the decode layer, which a payload-embedded notice reached none
# of. A `.wav`/`.f32` carriage is used rather than a source name so no extension
# tripwire can answer them instead.
FIXTURE_UTF16BE_NOTICE_IN_A_PAYLOAD = _float_dump(
    spliced=FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-be"), seed=101
)
# The same notice spliced at an ODD byte offset. A notice lands on an odd offset
# as often as an even one, and at an odd offset the data byte of each code unit
# sits on the OTHER side of its padding — the reading that was missed first, and
# the reason both windows are read.
FIXTURE_WIDE_NOTICE_AT_AN_ODD_OFFSET = (
    b"\x81" + struct.pack("<600h", *_lcg_samples(600, seed=110))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=111))
)
# The odd-offset case where the FIRST character of the run is load-bearing: a
# bare holder line, with no "(c)" marker and no license body behind it, so
# "opyright 2019 …" — the reading one unit late — matches no prefilter at all and
# the audit comes back clean. This is what makes reading both windows a coverage
# fix rather than a tidiness one.
FIXTURE_WIDE_HOLDER_LINE_AT_AN_ODD_OFFSET = (
    b"\x81" + struct.pack("<600h", *_lcg_samples(600, seed=112))
    + ("Copy" + "right 20" + "19 Some Upstream Author\n").encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=113))
)
FIXTURE_UTF32LE_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=102))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-32-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=103))
)
FIXTURE_UTF32BE_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=104))
    + FIXTURE_WIDE_NOTICE_TEXT.encode("utf-32-be")
    + struct.pack("<600h", *_lcg_samples(600, seed=105))
)
# A real PCM render whose data chunk carries the notice in UTF-16-LE: the
# carriage an exported render actually has, and the shape whose own quiet samples
# are the false-positive hazard this layer had to be measured against.
FIXTURE_WAV_WITH_WIDE_NOTICE = _wav_payload(
    spliced=FIXTURE_WIDE_NOTICE_TEXT.encode("utf-16")
)
# One wrapper deep: a gzip whose member is an opaque payload with a UTF-16-LE
# notice in it. The unwrap resolves the member, the member is still refused by
# the sniff, and only the wide harvest reads it — so this case fails if the
# member path does not harvest wide runs, even when the top-level path does.
FIXTURE_GZIPPED_WIDE_NOTICE_PAYLOAD = gzip.compress(
    FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD
)
# A notice whose holder is written with the sign spelling (U+00A9), wide-encoded
# inside a payload: 0xA9 arrives NUL-padded inside an otherwise printable
# NUL-padded run, so it is admitted and normalised, where the bare Latin-1 byte
# in the NARROW harvest deliberately is not. The sign is built from the byte
# constant rather than written as a character, like every other fixture fragment
# here, so this file carries no notice of its own.
FIXTURE_WIDE_COPYRIGHT_SIGN_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=106))
    + (COPYRIGHT_SIGN_CHAR + " 20" + "19 Some Upstream Author\n").encode("utf-16-le")
    + struct.pack("<600h", *_lcg_samples(600, seed=107))
)
# This repository's own renders are mostly QUIET, and a quiet 16-bit PCM sample
# is a low byte beside a NUL high byte — byte-for-byte the shape a UTF-16-LE
# string has. That makes a quiet render, not a full-scale one, the real
# false-positive hazard for this layer, and `foreign-license-text` cannot be
# exempted: a finding on one of this repository's 264 renders would be
# unanswerable. Kept as a positive control with real PCM data.
FIXTURE_QUIET_PCM_WAV = _wav_payload(quiet=True)
# The residual this increment declares rather than closes: a notice carried in a
# TRANSFORMED encoding (base64 here) is not text in any stride, so no run-shaped
# harvest reaches it. Non-vacuous in both directions — it is clean today and
# fails the moment a decoding layer is added.
FIXTURE_BASE64_NOTICE_IN_A_PAYLOAD = (
    struct.pack("<600h", *_lcg_samples(600, seed=108))
    + base64.b64encode(FIXTURE_WIDE_NOTICE_TEXT.encode("utf-8"))
    + struct.pack("<600h", *_lcg_samples(600, seed=109))
)
# Positive control for the PRECISION residual the increment-8 review found
# (#283): harvested runs are fed to every rule, not only to the four carriage
# signals, and a BOOKKEEPING rule is cheap enough for noise to satisfy by
# accident. A license body cannot plausibly appear in a render; a four-digit
# record citation can — `reports/sxt-024/traces/reset-midpatch-wet.npy` on the
# real tree carries a printable `dR` + `90459` run, which `RECORD_CITATION_RE`
# reads as a citation of a decision record that does not exist. The word filter
# is what keeps it out: that run holds no three consecutive letters, so the
# harvest drops it. Before this control nothing but the real tree pinned the
# filter.
#
# Shaped like the real hit rather than like a citation anyone would write: it
# needs the `dr0` prefilter token to reach the rule at all, a non-letter before
# the `d` for the regex's `\b`, and no word anywhere in the run. Assembled from
# fragments like every other fixture here (see the fixture note): spelled out,
# the literal would make THIS file a dangling citation — the rule reads the
# tool's own source. Non-vacuous in both directions — the control is clean
# today and fires `dangling-record-citation` the moment the filter is dropped.
FIXTURE_CITATION_SHAPED_NOISE_RUN = b';9$dR' + b'09' + b'45"4-7;'
FIXTURE_CITATION_SHAPED_NOISE = (
    struct.pack("<600h", *_lcg_samples(600, seed=101))
    + FIXTURE_CITATION_SHAPED_NOISE_RUN
    + struct.pack("<600h", *_lcg_samples(600, seed=102))
)

# Increment 9 — the NAMES a wrapper carries. Increment 8 unwrapped wrappers and
# content-scanned their members, then DECLARED the remainder: "a wrapper whose
# members carry no marker at all is covered only by the extension tripwires …
# unwrapping reads member CONTENT, and member NAMES are not themselves
# tripwired". Every must-fail fixture below audited **clean** under increment 8
# — no license text anywhere in it to find, and the outer `.dat`/`.bin` name
# evades both extension sets — which is precisely the shape upstream assets
# arrive in: a wavetable payload states no copyright, and a stripped source file
# states nothing either.
#
# Marker-free ON PURPOSE. A fixture carrying a notice would be caught by
# `foreign-license-text` and prove nothing about this rule, so each payload
# below is deterministic noise or plain code: the member NAME is the only signal
# in the file.
# NUL-interleaved high bytes: the encoding sniff refuses it (no BOM, NUL-dense,
# no wide decode that is mostly ASCII) and no six consecutive printable bytes
# exist, so the harvest is empty and `text()` is None. The member NAME is then
# the only thing in the file any rule can read — which is both the point of this
# control and the real shape of a wavetable payload. (Ordinary int16 noise fires
# the rule just as well, but an accidental printable run in it makes
# `manifest-uncorroborated` demand a citation a binary cannot carry — a
# confound, not the rule under test.)
FIXTURE_MARKER_FREE_ASSET_PAYLOAD = bytes(
    value for i in range(512) for value in (0x00, 0x80 | (i * 37) % 0x80)
)
FIXTURE_MARKER_FREE_SOURCE = (
    "float run(float x, float k) { return x - k * x * x * x; }\n"
)


def _gzip_with_name(name, payload: bytes):
    """A gzip stream whose header carries `name` in its FNAME field.

    `mtime=0` keeps the bytes deterministic. This is the shape `gzip <file>`
    produces by default, and the shape 15 of this repository's own evidence
    traces are in — so the positive control below is this repository's real
    data, not a hypothetical.
    """
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", filename=name, mtime=0) as handle:
        handle.write(payload)
    return buf.getvalue()


FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME = _zip_payload(
    (("wavetables/Bank Sine.wt", FIXTURE_MARKER_FREE_ASSET_PAYLOAD),)
)
FIXTURE_TAR_GZ_WITH_SOURCE_MEMBER_NAME = _tar_gz_payload(
    (("vendor/Reverb1.cpp", FIXTURE_MARKER_FREE_SOURCE),)
)
FIXTURE_GZIP_WITH_ASSET_FNAME = _gzip_with_name(
    "Bank Sine.wt", FIXTURE_MARKER_FREE_ASSET_PAYLOAD
)
FIXTURE_GZIPPED_ZIP_WITH_ASSET_MEMBER = gzip.compress(
    FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME
)
# The masking shape `member_name_signals` splits for: the offending name is the
# OUTER member, and what it wraps is innocuous. Judging only the last component
# of the joined label would read this as a `.json`.
FIXTURE_ZIP_WITH_WRAPPED_ASSET_MEMBER = _zip_payload(
    (("Bank Sine.wt", _gzip_with_name("meta.json", b'{"frames": 16}')),)
)
# The masking shape increment 12 closes: a CONCATENATED gzip (`cat a.gz b.gz`
# is a valid gzip file) whose offending name is on the SECOND member. Increment
# 9 read the FNAME once per stream, so this audited clean while the same two
# members in the other order fired — the order-dependence is the tell. The
# first member's payload is ordinary JSON so the file still yields text, which
# is what the pre-change tool saw and found nothing in.
FIXTURE_MULTI_MEMBER_GZIP_SECOND_NAMES_AN_ASSET = _gzip_with_name(
    "notes.json", b'{"frames": 16}'
) + _gzip_with_name("Bank Sine.wt", FIXTURE_MARKER_FREE_ASSET_PAYLOAD)
# Its mirror, for the same stream read in the other order — kept beside it so a
# test can assert the two now agree rather than asserting one of them alone.
FIXTURE_MULTI_MEMBER_GZIP_FIRST_NAMES_AN_ASSET = _gzip_with_name(
    "Bank Sine.wt", FIXTURE_MARKER_FREE_ASSET_PAYLOAD
) + _gzip_with_name("notes.json", b'{"frames": 16}')
# Positive controls — this repository's own wrapper shapes, which must stay
# clean. `wrapper-member-name` cannot be exempted, so a false positive here
# would be answered by switching the rule off. Both are measured shapes: of the
# 18 tracked `*.json.gz`/`*.hex.gz` traces, 15 carry an FNAME (9 `.json`,
# 6 `.hex`; the other 3 carry none), and the `.npz` tap fixture is a zip of 11
# `.npy` members — 26 real member names, 0 hits, re-derived by
# `test_real_tree_member_names_are_read_and_none_offend` on every run.
FIXTURE_OWN_GZIPPED_TRACE_WITH_FNAME = _gzip_with_name(
    "trace_seq-notes-coverage-v1.json",
    json.dumps({"fixture": "seq-notes-coverage-v1", "taps": [0.0, 0.25]}).encode("utf-8"),
)
FIXTURE_OWN_NPZ_MEMBERS = _zip_payload(
    (("gal_in.npy", "x"), ("gal_out.npy", "y"), ("__trimmed__.npy", "z"))
)
# The false-positive direction for increment 12: two of this repository's own
# trace members concatenated into one stream must read as TWO `.json` names and
# stay clean. A member walk that mis-parsed a boundary would surface here.
FIXTURE_OWN_MULTI_MEMBER_GZIPPED_TRACE = _gzip_with_name(
    "trace_seq-notes-coverage-v1.json",
    json.dumps({"fixture": "seq-notes-coverage-v1", "taps": [0.0, 0.25]}).encode("utf-8"),
) + _gzip_with_name(
    "trace_seq-notes-coverage-v2.json",
    json.dumps({"fixture": "seq-notes-coverage-v2", "taps": [0.5, 0.75]}).encode("utf-8"),
)


def _scoped_exemption(root: Path, occurrences, path="docs/own_copy.md"):
    item = {
        "rules": ["self-declared-quotation"],
        "occurrences": occurrences,
        "reason": "synthetic: the named occurrence copies this project's own model",
    }
    item["path" if "*" not in path else "pattern"] = path
    # Naming the occurrence puts the marker wording into the manifest itself,
    # so the skeleton exempts the manifest exactly as the real repository does.
    manifest_exemption = {
        "path": MANIFEST_REL,
        "rules": ["self-declared-quotation"],
        "reason": "synthetic: the manifest quotes the occurrence it exempts",
    }
    _patch_manifest(root, lambda d: d["exemptions"].extend([manifest_exemption, item]))


def _patch_manifest(root: Path, mutate, stage=True):
    """Rewrite the manifest, re-staging it when the control tree is a checkout.

    `stage` matters because of increment 15: an ANSWER present only on disk is
    now a finding of its own, so a fixture that patches the manifest AFTER
    staging would be asserting two things at once. Re-staging keeps a control
    about some other layer (a gitlink declared by a row) a control about that
    layer alone. The committed-answer-set controls pass `stage=False` on
    purpose — there, the unstaged answer IS the subject.
    """
    path = root / MANIFEST_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    # Keep the synthetic GPL-boundary register in step with the quoted-constants
    # rows this fixture adds, so a control about some OTHER layer stays a control
    # about that layer alone. (The register controls write the register directly.)
    register = root / REGISTER_REL
    if register.exists():
        rows = []
        for number, entry in enumerate(data.get("entries", []), start=1):
            if entry.get("class") == "quoted-constants" and entry.get("path"):
                rows.append(
                    [
                        f"G-{number}",
                        entry["path"],
                        "TABLE",
                        "synthetic/upstream.h",
                        entry.get("pinned_commit") or SKELETON_REGISTER_ROW[4],
                        "GPL-3.0-or-later",
                        str(entry["decision_record"]),
                        f"manifest:{entry['path']}",
                        "registered",
                        "synthetic",
                    ]
                )
        register.write_text(skeleton_register(gpl_rows=rows), encoding="utf-8")
    if stage and (root / ".git").exists():
        _git(root, "add", "-f", MANIFEST_REL)
        if register.exists():
            _git(root, "add", "-f", REGISTER_REL)


# --- discovery-layer fixtures -------------------------------------------------
#
# A by-reference entry cannot be written as a string, so these controls build
# real symlinks and a real mode-160000 index entry. The gitlink ones turn the
# control tree into a git checkout on purpose: that is the path `list_entries`
# takes on this repository, so the control exercises the actual `ls-files -s`
# mode parsing rather than a stand-in for it.
FIXTURE_SUBMODULE_REL = "libs/surge"
FIXTURE_SUBMODULE_COMMIT = "58914e59c608ed4384ba6002e44c3465c58b2e71"
FIXTURE_SUBMODULE_URL = "https://github.com/surge-synthesizer/surge.git"
FIXTURE_NESTED_REPO_REL = "libs/vendored-engine"
FIXTURE_ESCAPING_LINK_REL = "model/oracle_tables.py"
FIXTURE_ESCAPING_LINK_TARGET = "../../surge-oracle/include/sst/effects/Reverb1.h"
# A gitlink INSIDE a declared scope exclusion (increment 13): the shape an
# exclusion used to swallow whole, while a symlink INTO the same prefix was
# already a reportable escape.
FIXTURE_EXCLUDED_SUBMODULE_REL = ".loom/surge"
FIXTURE_DECLARED_HOLE_PREFIX = ".loom/"


def _git(root: Path, *args):
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True
    )
    if proc.returncode != 0:
        raise AuditError(
            "git " + " ".join(args) + " failed: "
            + proc.stderr.decode("utf-8", "replace").strip()
        )


def _symlink(root: Path, rel, target):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def _git_submodule_entry(root: Path, rel=FIXTURE_SUBMODULE_REL,
                         commit=FIXTURE_SUBMODULE_COMMIT, url=FIXTURE_SUBMODULE_URL):
    """Record a submodule GITLINK in a synthetic tree — no clone, no network.

    `git update-index --cacheinfo 160000,…` writes exactly the index entry
    `git submodule add` would, so the audit sees a real mode-160000 row.
    """
    _git(root, "init", "-q")
    # -f: a host-level core.excludesFile must not silently drop skeleton files
    # (an untracked file is invisible to `ls-files`, which would change what
    # the control is actually testing).
    _git(root, "add", "-A", "-f")
    if url:
        _write(root, ".gitmodules", f'[submodule "{rel}"]\n\tpath = {rel}\n\turl = {url}\n')
        _git(root, "add", "-f", ".gitmodules")
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{commit},{rel}")


def _nested_repo(root: Path, rel=FIXTURE_NESTED_REPO_REL):
    """A nested repository checkout in a NON-git tree (the tarball shape)."""
    _write(root, f"{rel}/.git/config", "[core]\n\tbare = false\n")
    _write(root, f"{rel}/dsp/Reverb1.h", "float run(float x) { return x; }\n")


def _submodule_row(
    commit=FIXTURE_SUBMODULE_COMMIT,
    rel=FIXTURE_SUBMODULE_REL,
    row_class=BY_REFERENCE_CLASS,
):
    """A row answering a gitlink. `commit=None` OMITS the field entirely.

    Omission is a distinct case from a wrong value, and the one the pin rule
    missed: `pinned_commit` is not in `REQUIRED_ENTRY_FIELDS` (it is optional
    for the content classes), so deleting it used to defeat the wrong-commit
    control instead of tripping a field rule. `row_class` is a parameter for
    the same reason — a row of the wrong class used to cover the rule anyway.
    """
    row = {
        "path": rel,
        "class": row_class,
        "content": "synthetic: the pinned upstream engine, referenced as a submodule",
        "upstream": FIXTURE_SUBMODULE_URL,
        "upstream_license": "GPL-3.0-or-later",
        "decision_record": "0001",
    }
    if commit is not None:
        row["pinned_commit"] = commit
    return row


def _escaping_link_row(rel=FIXTURE_ESCAPING_LINK_REL, row_class=BY_REFERENCE_CLASS):
    """A correct row answering an escaping symlink."""
    return {
        "path": rel,
        "class": row_class,
        "content": "synthetic: a link into the external oracle tree",
        "upstream": "surge-synthesizer/surge",
        "pinned_commit": FIXTURE_SUBMODULE_COMMIT,
        "upstream_license": "GPL-3.0-or-later",
        "decision_record": "0001",
    }


def _declared_hole(root: Path, rel=f"{FIXTURE_DECLARED_HOLE_PREFIX}notes.md"):
    """Declare `FIXTURE_DECLARED_HOLE_PREFIX` as a scope exclusion, with a member."""
    _write(root, rel, "A surface installed from elsewhere, not product content.\n")
    _patch_manifest(
        root,
        lambda d: d["scope_exclusions"].append(
            {
                "prefix": FIXTURE_DECLARED_HOLE_PREFIX,
                "reason": "synthetic declared hole",
            }
        ),
    )


def _controls():
    """{rule: (description, mutator)} — one deliberate violation per rule."""

    def add_second_record(root, indexed):
        _write(
            root,
            f"{RECORD_DIR_REL}/0002-second.md",
            "# 0002: Second (synthetic)\n\n- **Status**: proposed\n"
            "- **Date**: 2026-01-02\n",
        )
        if indexed:
            path = root / INDEX_REL
            path.write_text(
                path.read_text(encoding="utf-8")
                + "| [0002](0002-second.md) | Second (synthetic) | proposed | 2026-01-02 |\n",
                encoding="utf-8",
            )

    controls = {
        "foreign-license-text": (
            "an unattributed file carrying a foreign license body",
            lambda root: _write(root, "model/pasted_helper.py", FIXTURE_GPL_BODY),
        ),
        "upstream-asset-extension": (
            "an undeclared upstream asset payload",
            lambda root: _write(root, "assets/Bank Sine.wt", b"\x00\x01wt payload"),
        ),
        "foreign-source-language": (
            "an undeclared foreign-language source file",
            lambda root: _write(
                root, "src/copied_filter.cpp", "float run(float x) { return x; }\n"
            ),
        ),
        "wrapper-member-name": (
            "an archive renamed '.dat' carrying an upstream asset member name",
            lambda root: _write(
                root, PAYLOAD_BUNDLE_REL, FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME
            ),
        ),
        "self-declared-quotation": (
            "a file admitting quotation with no provenance row",
            lambda root: _write(root, "model/undeclared_table.py", FIXTURE_TRANSCRIBED),
        ),
        "submodule-reference": (
            "a committed submodule gitlink pinning the upstream engine",
            _git_submodule_entry,
        ),
        "external-symlink-target": (
            "a tracked symlink whose target leaves the audited tree",
            lambda root: _symlink(
                root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET
            ),
        ),
        "dangling-record-citation": (
            "a citation of a decision record that does not exist",
            lambda root: _write(root, "docs/claim.md", FIXTURE_RECORD_CITATION),
        ),
        "unindexed-record-citation": (
            "a citation of a record missing from the index",
            lambda root: (
                add_second_record(root, indexed=False),
                _write(root, "docs/claim2.md", "See DR-0002 for the decision.\n"),
            ),
        ),
        "index-missing-row": (
            "a decision record on disk with no index row",
            lambda root: add_second_record(root, indexed=False),
        ),
        "index-unknown-record": (
            "an index row with no record file",
            lambda root: _write(
                root,
                INDEX_REL,
                SKELETON_INDEX
                + "| [0002](0002-ghost.md) | Ghost | proposed | 2026-01-02 |\n",
            ),
        ),
        "index-duplicate-row": (
            "the same record listed twice in the index",
            lambda root: _write(
                root,
                INDEX_REL,
                SKELETON_INDEX
                + "| [0001](0001-example.md) | Example | ratified | 2026-01-01 |\n",
            ),
        ),
        "index-status-mismatch": (
            "an index status keyword that no longer matches the record",
            lambda root: _write(
                root, INDEX_REL, SKELETON_INDEX.replace("| ratified |", "| PROPOSED |")
            ),
        ),
        "index-date-mismatch": (
            "an index date that no longer matches the record",
            lambda root: _write(
                root, INDEX_REL, SKELETON_INDEX.replace("2026-01-01 |", "2026-02-02 |")
            ),
        ),
        "index-number-gap": (
            "a gap in the decision-record numbering (a deleted record)",
            lambda root: (
                _write(
                    root,
                    f"{RECORD_DIR_REL}/0003-third.md",
                    "# 0003: Third (synthetic)\n\n- **Status**: proposed\n"
                    "- **Date**: 2026-01-03\n",
                ),
                _write(
                    root,
                    INDEX_REL,
                    SKELETON_INDEX
                    + "| [0003](0003-third.md) | Third | proposed | 2026-01-03 |\n",
                ),
            ),
        ),
        "record-status-unrecognized": (
            "a record whose status keyword is outside the vocabulary",
            lambda root: _write(
                root,
                f"{RECORD_DIR_REL}/0001-example.md",
                SKELETON_RECORD.replace("ratified", "maybe-someday"),
            ),
        ),
        "record-header-missing": (
            "a record with no parseable Status/Date header",
            lambda root: _write(
                root, f"{RECORD_DIR_REL}/0001-example.md", "# 0001: no header\n"
            ),
        ),
        "manifest-missing": (
            "a missing provenance manifest",
            lambda root: (root / MANIFEST_REL).unlink(),
        ),
        "manifest-schema": (
            "a manifest with an unknown schema_version",
            lambda root: _patch_manifest(root, lambda d: d.update(schema_version=99)),
        ),
        "manifest-field-missing": (
            "a provenance row missing required provenance fields",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].pop("upstream_license")
            ),
        ),
        "manifest-unknown-class": (
            "a provenance row with an unknown class",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"class": "vibes"})
            ),
        ),
        "manifest-stale-path": (
            "a provenance row whose file is gone",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"path": "model/deleted.py"})
            ),
        ),
        "manifest-bad-pattern": (
            "a blanket provenance pattern",
            lambda root: _patch_manifest(
                root,
                lambda d: d["entries"].append(
                    {
                        "pattern": "model/**",
                        "class": "quoted-constants",
                        "content": "everything",
                        "upstream": "x",
                        "upstream_license": "GPL-3.0-or-later",
                        "decision_record": "0001",
                    }
                ),
            ),
        ),
        "manifest-missing-record": (
            "a provenance row citing a nonexistent decision record",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"decision_record": "0099"})
            ),
        ),
        "manifest-unindexed-record": (
            "a provenance row citing an unindexed decision record",
            lambda root: (
                add_second_record(root, indexed=False),
                _patch_manifest(
                    root, lambda d: d["entries"][0].update({"decision_record": "0002"})
                ),
            ),
        ),
        "manifest-uncorroborated": (
            "a provenance row the file itself does not corroborate",
            lambda root: _write(
                root, "model/carrier.py", "TABLE = [1, 2, 3]  # no provenance stated\n"
            ),
        ),
        "exemption-field-missing": (
            "an exemption with no reason",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {"path": "docs/plain.md", "rules": ["self-declared-quotation"]}
                ),
            ),
        ),
        "exemption-non-exemptible-rule": (
            "an exemption of a non-exemptible rule",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "path": "docs/plain.md",
                        "rules": ["foreign-license-text"],
                        "reason": "trying to wave away a GPL header",
                    }
                ),
            ),
        ),
        "exemption-stale": (
            "an exemption matching no file",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "path": "docs/gone.md",
                        "rules": ["self-declared-quotation"],
                        "reason": "stale",
                    }
                ),
            ),
        ),
        "exemption-ambiguous": (
            "an occurrence-scoped exemption whose named sentence appears twice",
            lambda root: (
                _write(
                    root,
                    "docs/own_copy.md",
                    FIXTURE_OWN_COPY_DOC + FIXTURE_DUPLICATE_OCCURRENCE_LINE,
                ),
                _scoped_exemption(root, [FIXTURE_OWN_COPY_OCCURRENCE]),
            ),
        ),
        "exemption-bad-pattern": (
            "a blanket exemption pattern",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "pattern": "docs/**",
                        "rules": ["self-declared-quotation"],
                        "reason": "blanket",
                    }
                ),
            ),
        ),
        "scope-exclusion-stale": (
            "a scope exclusion that excludes nothing",
            lambda root: _patch_manifest(
                root,
                lambda d: d["scope_exclusions"].append(
                    {"prefix": "vendor-nothing/", "reason": "stale"}
                ),
            ),
        ),
        "scan-underflow": (
            "a scan that saw fewer files than the declared floor",
            lambda root: _patch_manifest(root, lambda d: d.update(scan_floor=10_000)),
        ),
        "register-missing": (
            "a deleted GPL-boundary register",
            lambda root: (root / REGISTER_REL).unlink(),
        ),
        "register-malformed-row": (
            "a register row with an empty required field",
            lambda root: _write(
                root,
                REGISTER_REL,
                skeleton_register(
                    gpl_rows=[SKELETON_REGISTER_ROW[:-1] + [""]],
                ),
            ),
        ),
        "register-missing-row": (
            "a quoted-constants manifest row whose register row was removed",
            lambda root: _write(
                root,
                REGISTER_REL,
                skeleton_register(
                    gpl_rows=[],
                    exclusions=[
                        [
                            "X-1",
                            "0001",
                            "model/carrier.py",
                            "TABLE",
                            "structural",
                            "synthetic",
                        ]
                    ],
                ),
            ),
        ),
        "register-unmapped-row": (
            "a register row citing a provenance row that does not exist",
            lambda root: _write(
                root,
                REGISTER_REL,
                skeleton_register(
                    gpl_rows=[
                        SKELETON_REGISTER_ROW[:7]
                        + ["manifest:model/other.py"]
                        + SKELETON_REGISTER_ROW[8:]
                    ],
                ),
            ),
        ),
        "register-licence-mismatch": (
            "an MIT-licensed row filed in the GPL-derived table",
            lambda root: _write(
                root,
                REGISTER_REL,
                skeleton_register(
                    gpl_rows=[
                        SKELETON_REGISTER_ROW[:5] + ["MIT"] + SKELETON_REGISTER_ROW[6:]
                    ],
                ),
            ),
        ),
        "register-exception-stale": (
            "a register exception for a file that a manifest row now covers",
            lambda root: _write(
                root,
                REGISTER_REL,
                skeleton_register(
                    exceptions=[
                        [
                            "E-1",
                            "model/carrier.py",
                            "0001",
                            "synthetic gap",
                            "synthetic closing action",
                        ]
                    ],
                ),
            ),
        ),
        "register-record-unaccounted": (
            "a record declaring quoted data that the register neither lists nor excludes",
            lambda root: (
                _write(
                    root,
                    f"{RECORD_DIR_REL}/0002-second.md",
                    "# 0002: Second (synthetic)\n\n- **Status**: proposed\n"
                    "- **Date**: 2026-01-02\n\nThe table is quoted as data.\n",
                ),
                _write(
                    root,
                    INDEX_REL,
                    SKELETON_INDEX
                    + "| [0002](0002-second.md) | Second (synthetic) | proposed | 2026-01-02 |\n",
                ),
            ),
        ),
    }
    return controls


def _scoped_exemption_controls():
    """[(label, expected rule or None, description, mutator)].

    The occurrence-scoped exemption is a weakening of the one exemptible rule,
    so it gets its own controls: the case it exists for must pass (a positive
    control — otherwise it is dead), and each way it could launder real
    carriage must still fail.
    """
    own = FIXTURE_OWN_COPY_DOC
    occ = [FIXTURE_OWN_COPY_OCCURRENCE]
    return [
        (
            "scoped-exemption/own-copy-passes",
            None,
            "a file whose only quotation marker is the named own-model occurrence",
            lambda root: (_write(root, "docs/own_copy.md", own), _scoped_exemption(root, occ)),
        ),
        (
            "scoped-exemption/foreign-copy-still-fails",
            "self-declared-quotation",
            "the same exempted file plus a foreign 'copied verbatim' line",
            lambda root: (
                _write(root, "docs/own_copy.md", own + FIXTURE_FOREIGN_COPY_LINE),
                _scoped_exemption(root, occ),
            ),
        ),
        (
            "scoped-exemption/other-marker-still-fails",
            "self-declared-quotation",
            "the same exempted file plus a foreign 'transcribed from' table",
            lambda root: (
                _write(root, "docs/own_copy.md", own + FIXTURE_TRANSCRIBED),
                _scoped_exemption(root, occ),
            ),
        ),
        (
            "scoped-exemption/occurrence-gone",
            "exemption-stale",
            "a named occurrence that no longer appears in the file",
            lambda root: (
                _write(root, "docs/own_copy.md", own),
                _scoped_exemption(root, occ + ["a sentence that is not there"]),
            ),
        ),
        (
            "scoped-exemption/occurrence-without-marker",
            "exemption-stale",
            "a named occurrence that contains no quotation marker",
            lambda root: (
                _write(root, "docs/own_copy.md", own),
                _scoped_exemption(root, occ + ["instantiates the shared"]),
            ),
        ),
        (
            "scoped-exemption/duplicate-occurrence",
            "exemption-ambiguous",
            "the named occurrence repeated verbatim with a foreign referent",
            lambda root: (
                _write(
                    root,
                    "docs/own_copy.md",
                    own + FIXTURE_DUPLICATE_OCCURRENCE_LINE,
                ),
                _scoped_exemption(root, occ),
            ),
        ),
        (
            "scoped-exemption/on-a-pattern",
            "exemption-bad-pattern",
            "occurrences attached to a glob instead of one exact path",
            lambda root: (
                _write(root, "docs/own_copy.md", own),
                _scoped_exemption(root, occ, path="docs/*.md"),
            ),
        ),
    ]


MASKED_REL = "model/pasted_below_our_header.py"
OWN_ONLY_REL = "model/own_header_only.py"


def _masking_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    `foreign-license-text` cannot be exempted, so the only way to disarm it is
    to make it stop firing. These controls pin the two ways that happened —
    reading only a file's FIRST notice, and judging a notice's holder from a
    proximity window rather than from the notice itself — plus the positive
    cases that keep the fix from degenerating into "flag our own headers too".
    """
    below = FIXTURE_OWN_COPYRIGHT + FIXTURE_FILLER + FIXTURE_FOREIGN_COPYRIGHT_LINE
    adjacent = FIXTURE_OWN_PROJECT_LINE + FIXTURE_FOREIGN_COPYRIGHT_LINE
    spdx_below = FIXTURE_OWN_SPDX_TAG + FIXTURE_FILLER + FIXTURE_FOREIGN_SPDX_TAG
    return [
        (
            "masking/foreign-copyright-under-our-own",
            "foreign-license-text",
            MASKED_REL,
            "a pasted foreign copyright line below our own copyright header",
            lambda root: _write(root, MASKED_REL, below),
        ),
        (
            "masking/foreign-copyright-beside-a-project-mention",
            "foreign-license-text",
            MASKED_REL,
            "a foreign copyright line one line under a 'gf180-surge' mention",
            lambda root: _write(root, MASKED_REL, adjacent),
        ),
        (
            "masking/foreign-spdx-under-our-own",
            "foreign-license-text",
            MASKED_REL,
            "a pasted foreign SPDX tag below our own Apache tag",
            lambda root: _write(root, MASKED_REL, spdx_below),
        ),
        (
            "masking/our-own-copyright-alone-passes",
            None,
            None,
            "a file carrying only our own copyright header",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-spdx-alone-passes",
            None,
            None,
            "a file carrying only our own Apache SPDX tag",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_SPDX_TAG + FIXTURE_FILLER
            ),
        ),
        # --- increment 3: the same masking inside the notice itself ---------
        (
            "masking/foreign-holder-with-our-name-in-a-parenthetical",
            "foreign-license-text",
            MASKED_REL,
            "a foreign copyright line that names this project in a parenthetical",
            lambda root: _write(
                root, MASKED_REL, FIXTURE_FOREIGN_COPYRIGHT_PARENTHETICAL
            ),
        ),
        (
            "masking/foreign-holder-with-our-name-after-a-dash",
            "foreign-license-text",
            MASKED_REL,
            "a foreign copyright line that names this project after a spaced hyphen",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_COPYRIGHT_AFTER_DASH),
        ),
        (
            "masking/compound-spdx-behind-our-own-operand",
            "foreign-license-text",
            MASKED_REL,
            "an SPDX expression whose leading operand is our own licence",
            lambda root: _write(root, MASKED_REL, FIXTURE_COMPOUND_SPDX_OWN_FIRST),
        ),
        (
            "masking/license-body-wrapped-across-a-comment-leader",
            "foreign-license-text",
            MASKED_REL,
            "an FSF license body wrapped mid-phrase across a '#' comment leader",
            lambda root: _write(root, MASKED_REL, FIXTURE_WRAPPED_FSF_BODY),
        ),
        (
            "masking/license-title-wrapped-across-a-comment-leader",
            "foreign-license-text",
            MASKED_REL,
            "a GPL license title wrapped mid-phrase across a '*' comment leader",
            lambda root: _write(root, MASKED_REL, FIXTURE_WRAPPED_GPL_TITLE),
        ),
        (
            "masking/our-own-copyright-with-an-aside-passes",
            None,
            None,
            "our own copyright line trailed by a parenthetical aside",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_WITH_ASIDE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-authors-line-passes",
            None,
            None,
            "our own copyright line spelled 'The gf180-surge Authors'",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_AUTHORS + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-copyright-after-a-dash-passes",
            None,
            None,
            "our own copyright line whose holder follows a spaced hyphen",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_AFTER_DASH + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-spdx-quoted-in-prose-passes",
            None,
            None,
            "our own SPDX tag quoted mid-sentence, with prose after the operand",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_SPDX_IN_PROSE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/leaderless-prose-wrap-stays-out-of-scope",
            None,
            None,
            "a declared boundary: a license NAME wrapped in leaderless prose",
            lambda root: _write(
                root, "docs/mentions.md", FIXTURE_PROSE_WRAP_LICENSE_NAME
            ),
        ),
        # --- increment 4: delimiter-led holder fields, SPDX operands past the
        # --- expression, yearless notices, wrapped holder lists -------------
        (
            "masking/foreign-holder-behind-a-bracketed-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder behind a bracketed mention of this project",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_BEHIND_BRACKETS),
        ),
        (
            "masking/foreign-holder-behind-a-parenthesised-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder behind a parenthesised mention of this project",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_BEHIND_PARENS),
        ),
        (
            "masking/foreign-holder-after-a-semicolon-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder in a notice whose year is followed by '; gf180-surge …'",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_AFTER_SEMICOLON),
        ),
        (
            "masking/foreign-holder-after-an-em-dash-project-name",
            "foreign-license-text",
            MASKED_REL,
            "a foreign holder in a notice whose year is followed by '— gf180-surge …'",
            lambda root: _write(root, MASKED_REL, FIXTURE_FOREIGN_HOLDER_AFTER_EM_DASH),
        ),
        (
            "masking/spdx-foreign-operand-after-a-comma",
            "foreign-license-text",
            MASKED_REL,
            "an SPDX tag listing a foreign licence after a comma",
            lambda root: _write(root, MASKED_REL, FIXTURE_SPDX_FOREIGN_AFTER_COMMA),
        ),
        (
            "masking/spdx-foreign-operand-in-a-parenthetical",
            "foreign-license-text",
            MASKED_REL,
            "an SPDX tag naming a foreign licence inside a parenthetical",
            lambda root: _write(root, MASKED_REL, FIXTURE_SPDX_FOREIGN_IN_PARENTHETICAL),
        ),
        (
            "masking/yearless-foreign-copyright-notice",
            "foreign-license-text",
            MASKED_REL,
            "a pasted foreign notice that carries a holder but no year",
            lambda root: _write(root, MASKED_REL, FIXTURE_YEARLESS_FOREIGN_COPYRIGHT),
        ),
        (
            # The notice is written BELOW a filler pad on purpose. `Finding`
            # carries no line number, so the finding's `detail` snippet is its
            # only locator -- and a wrapped-holder match computed at
            # line-relative offsets quotes the right bytes only while the notice
            # sits at the top of the file. The pad makes the offsets diverge, and
            # the expected-detail substring below is what fails on a regression.
            "masking/foreign-holder-on-a-wrapped-continuation-line",
            "foreign-license-text",
            MASKED_REL,
            "a holder list wrapped onto a continuation line with no keyword",
            lambda root: _write(
                root, MASKED_REL, FIXTURE_FILLER + FIXTURE_WRAPPED_HOLDER_LIST
            ),
            "Chris Johnson / Airwindows",
        ),
        (
            "masking/our-own-notice-with-rights-reserved-passes",
            None,
            None,
            "our own notice trailed by 'All Rights Reserved.'",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_RIGHTS_RESERVED + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-notice-with-a-cross-reference-passes",
            None,
            None,
            "our own notice trailed by a sentence pointing at LICENSE",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_CROSS_REFERENCE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/our-own-notice-quoted-inside-prose-passes",
            None,
            None,
            "our own notice quoted mid-sentence, with prose after the closing quote",
            lambda root: _write(
                root, "docs/mentions.md", FIXTURE_OWN_COPYRIGHT_QUOTED_IN_PROSE
            ),
        ),
        (
            # Pins the segment walk itself: with the old fallback to the WHOLE
            # LINE, the aside's own capitalised token reads as a second holder
            # and our own notice becomes an unanswerable finding.
            "masking/our-own-dash-holder-with-an-aside-passes",
            None,
            None,
            "our own notice after a spaced hyphen, trailed by a capitalised aside",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_DASH_HOLDER_WITH_ASIDE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/ordinary-comment-under-an-own-notice-passes",
            None,
            None,
            "a capitalised comment sentence directly under our own notice",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_COPYRIGHT_THEN_PROSE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/lettered-list-markers-stay-out-of-scope",
            None,
            None,
            "a declared boundary: '(c)' list markers are not yearless notices",
            lambda root: _write(root, "docs/legs.md", FIXTURE_LETTERED_LIST_MARKERS),
        ),
        # --- increment 5: the holder list continues past the next delimiter on
        # --- the SAME line --------------------------------------------------
        (
            "masking/second-holder-after-a-semicolon",
            "foreign-license-text",
            MASKED_REL,
            "a second holder after a semicolon on a notice line that names us first",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_AFTER_SEMICOLON),
            "Some Upstream Author",
        ),
        (
            "masking/second-holder-in-a-parenthetical",
            "foreign-license-text",
            MASKED_REL,
            "an upstream holder credited in a parenthetical after our own holder",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_IN_PARENTHETICAL),
            "Chris Johnson",
        ),
        (
            "masking/second-holder-after-an-em-dash",
            "foreign-license-text",
            MASKED_REL,
            "a second holder after an em dash, our own holder standing first",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_AFTER_EM_DASH),
            "Chris Johnson",
        ),
        (
            "masking/second-holder-after-a-spaced-hyphen",
            "foreign-license-text",
            MASKED_REL,
            "a second holder after a spaced hyphen, our own holder standing first",
            lambda root: _write(root, MASKED_REL, FIXTURE_SECOND_HOLDER_AFTER_DASH),
            "Some Upstream Author",
        ),
        (
            "masking/single-name-aside-stays-out-of-scope",
            None,
            None,
            "a declared boundary: ONE capitalised token in an aside is not a holder",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_SINGLE_NAME_ASIDE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/prose-after-a-sentence-break-stays-out-of-scope",
            None,
            None,
            "a declared boundary: a name after a full stop is prose, not a holder list",
            lambda root: _write(
                root, OWN_ONLY_REL, FIXTURE_OWN_NOTICE_THEN_SENTENCE + FIXTURE_FILLER
            ),
        ),
        (
            "masking/copyright-prose-is-not-a-notice-passes",
            None,
            None,
            "prose ABOUT copyright, whose holder position holds 'License'/'Notice'",
            lambda root: _write(
                root, "docs/mentions.md", FIXTURE_COPYRIGHT_PROSE_NOT_A_NOTICE
            ),
        ),
        # --- increment 6: masking the DECODE layer, below every signal ------
        (
            "masking/utf16-bom-encoded-license-body",
            "foreign-license-text",
            MASKED_REL,
            "a GPL body in a UTF-16 (BOM) source file the sniff called binary",
            lambda root: _write(root, MASKED_REL, FIXTURE_UTF16_BOM_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "masking/utf16-le-bomless-encoded-license-body",
            "foreign-license-text",
            MASKED_REL,
            "the same body in BOM-less UTF-16-LE (a plain 'Unicode' editor save)",
            lambda root: _write(root, MASKED_REL, FIXTURE_UTF16LE_BOMLESS_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "masking/utf16-be-bomless-encoded-license-body",
            "foreign-license-text",
            MASKED_REL,
            "the same body in BOM-less UTF-16-BE",
            lambda root: _write(root, MASKED_REL, FIXTURE_UTF16BE_BOMLESS_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "masking/stray-nul-byte-above-a-license-body",
            "foreign-license-text",
            MASKED_REL,
            "one stray NUL byte in the head of an otherwise ASCII GPL-headed file",
            lambda root: _write(root, MASKED_REL, FIXTURE_STRAY_NUL_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
    ]


PAYLOAD_WRAPPED_REL = "model/pasted_helper.py.gz"
PAYLOAD_RENDER_REL = "fixtures/audio/render.wav"
PAYLOAD_DUMP_REL = "reports/artifacts/ref-hot.f32"
PAYLOAD_BUNDLE_REL = "compiler/golden/bundle.dat"


def _payload_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    Increment 8 — the PAYLOAD layer. Increment 6 made the decode layer honest
    about ENCODINGS; a payload it still refused reached no content rule, and
    `files_not_content_scanned` counted 335 such files on this tree. Every
    must-fail case below audited **clean** before this increment while
    `--negative-control` reported all 31 rules and all 41 masking controls
    behaving — a gzipped source file, a zip/tar renamed `.dat`, a WAV copyright
    chunk, a notice spliced into a float dump.

    Increment 10 then inverted this increment's own declared residual, on the
    same fixture bytes: a notice re-saved in a WIDE encoding and spliced into the
    same payloads went past the non-exemptible rule just as the ASCII one had,
    and a "Unicode" save is an ordinary editor default rather than an exotic
    carriage.

    The positive controls carry at least as much weight. `foreign-license-text`
    cannot be exempted, so a false positive on this repository's own 264
    renders, 22 float dumps, 8 tensors or 18 gzipped traces would be
    unanswerable — the rule would be switched off rather than answered. Hence a
    real PCM render, a float dump, an `.npy`-shaped tensor and an own gzipped
    JSON trace must all stay clean; so must a QUIET render, which is the shape
    increment 10 had to be measured against (a quiet 16-bit sample is a low byte
    beside a NUL high byte — byte-for-byte what a UTF-16-LE string looks like);
    a base64-carried notice pins the residual limit increment 10 declares
    rather than closes; and (added by the increment-8 review, #283) a
    citation-shaped wordless noise run, which is what keeps the word filter
    honest about being load-bearing rather than cosmetic.
    """
    return [
        (
            "payload/gzipped-source-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_WRAPPED_REL,
            "a gzipped source file whose stripped extension matches no tripwire",
            lambda root: _write(root, PAYLOAD_WRAPPED_REL, FIXTURE_GZIPPED_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/xz-compressed-source-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_WRAPPED_REL,
            "the same body in an xz stream (the wrapper is found by magic, not name)",
            lambda root: _write(root, PAYLOAD_WRAPPED_REL, FIXTURE_XZ_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/bzip2-compressed-source-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_WRAPPED_REL,
            "the same body in a bzip2 stream",
            lambda root: _write(root, PAYLOAD_WRAPPED_REL, FIXTURE_BZIP2_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/zip-member-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a zip renamed '.dat' — the archive extension tripwire evaded outright",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_ZIP_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/tar-gz-member-with-a-license-body",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a tar inside a gzip inside a '.dat' name — two wrappers deep",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_TAR_GZ_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/zip-inside-a-gzip-stream",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a zip inside a gzip — the inner layer is compressed, not ASCII",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_GZIPPED_ZIP_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/gzipped-member-inside-a-zip",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a gzipped member inside a zip — the other recursion site",
            lambda root: _write(root, PAYLOAD_BUNDLE_REL, FIXTURE_ZIP_WITH_GZIPPED_MEMBER),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/npz-member-with-a-license-body",
            "foreign-license-text",
            "reports/fixtures/taps.npz",
            "a notice riding along in an '.npz' tensor archive (a zip)",
            lambda root: _write(
                root, "reports/fixtures/taps.npz", FIXTURE_NPZ_WITH_NOTICE
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wav-copyright-chunk",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a render whose RIFF LIST/INFO 'ICOP' chunk states an upstream holder",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WAV_WITH_COPYRIGHT_CHUNK
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/notice-spliced-into-a-float-dump",
            "foreign-license-text",
            PAYLOAD_DUMP_REL,
            "a GPL body spliced into the middle of a raw float32 dump",
            lambda root: _write(root, PAYLOAD_DUMP_REL, FIXTURE_FLOAT_DUMP_WITH_NOTICE),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/notice-embedded-in-an-opaque-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "increment 6's declared limit, now closed: an ASCII notice in binary data",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_NOTICE_IN_AN_OPAQUE_PAYLOAD
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/copyright-sign-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a notice written with the © sign, which ends the printable run",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_COPYRIGHT_SIGN_IN_A_PAYLOAD
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/pcm-render-stays-clean",
            None,
            None,
            "a real 16-bit PCM render with no metadata chunk",
            lambda root: _write(root, PAYLOAD_RENDER_REL, FIXTURE_PLAIN_PCM_WAV),
        ),
        (
            "payload/float-dump-stays-clean",
            None,
            None,
            "a raw float32 dump of this repository's own shape",
            lambda root: _write(root, PAYLOAD_DUMP_REL, FIXTURE_PLAIN_FLOAT_DUMP),
        ),
        (
            "payload/tensor-payload-stays-clean",
            None,
            None,
            "an '.npy'-shaped tensor payload (ASCII header over float data)",
            lambda root: _write(root, "reports/traces/click-dry.npy", FIXTURE_TENSOR_PAYLOAD),
        ),
        (
            "payload/our-own-gzipped-trace-stays-clean",
            None,
            None,
            "this repository's own evidence shape: a gzipped JSON trace, now inflated",
            lambda root: _write(
                root, "reports/artifacts/trace.json.gz", FIXTURE_OWN_GZIPPED_TRACE
            ),
        ),
        # Increment 10 — the inversion of increment 8's own declared residual,
        # on the same fixture bytes, plus the other byte orders, strides and
        # carriages that declaration also covered.
        (
            "payload/wide-encoded-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "increment 8's declared limit, now closed: a UTF-16-LE notice in a payload",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-encoded-notice-in-the-other-byte-order",
            "foreign-license-text",
            PAYLOAD_DUMP_REL,
            "the same notice in UTF-16-BE, spliced into a float dump",
            lambda root: _write(
                root, PAYLOAD_DUMP_REL, FIXTURE_UTF16BE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-notice-spliced-at-an-odd-offset",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "the same notice at an ODD offset: its data bytes sit on the other "
            "side of their padding",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_NOTICE_AT_AN_ODD_OFFSET
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-holder-line-at-an-odd-offset",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "the same, where the run's FIRST character is the whole prefilter: a "
            "bare holder line read one unit late matches nothing",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_HOLDER_LINE_AT_AN_ODD_OFFSET
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/utf32-le-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a 32-bit code unit: three padding bytes per character, not one",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_UTF32LE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/utf32-be-notice-in-a-payload",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "the same, big-endian — the other half of the second halving step",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_UTF32BE_NOTICE_IN_A_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/bom-led-wide-notice-inside-a-real-render",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a BOM-led UTF-16 notice inside a real PCM render's data chunk",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WAV_WITH_WIDE_NOTICE
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-notice-inside-a-wrapper-member",
            "foreign-license-text",
            PAYLOAD_BUNDLE_REL,
            "a gzip whose member is an opaque payload with a UTF-16 notice in it",
            lambda root: _write(
                root, PAYLOAD_BUNDLE_REL, FIXTURE_GZIPPED_WIDE_NOTICE_PAYLOAD
            ),
            WIDE_NOTICE_LOCATOR,
        ),
        (
            "payload/wide-encoded-copyright-sign-notice",
            "foreign-license-text",
            PAYLOAD_RENDER_REL,
            "a wide-encoded notice whose holder is written with the sign spelling",
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_WIDE_COPYRIGHT_SIGN_IN_A_PAYLOAD
            ),
            PAYLOAD_COPYRIGHT_LOCATOR,
        ),
        (
            "payload/quiet-pcm-render-stays-clean",
            None,
            None,
            (
                "the real false-positive hazard: a QUIET 16-bit PCM render, whose "
                "every sample is a low byte beside a NUL — a UTF-16-LE string's "
                "own byte shape"
            ),
            lambda root: _write(root, PAYLOAD_RENDER_REL, FIXTURE_QUIET_PCM_WAV),
        ),
        (
            "payload/base64-encoded-notice-stays-out-of-scope",
            None,
            None,
            (
                "a declared limit: a notice carried in a TRANSFORMED encoding "
                "(base64) is not text at any stride, so no run harvest reaches it"
            ),
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_BASE64_NOTICE_IN_A_PAYLOAD
            ),
        ),
        (
            "payload/citation-shaped-noise-run-stays-clean",
            None,
            None,
            (
                "the precision residual (#283): a wordless printable run in a "
                "render that reads as a citation of record 0945 — the word "
                "filter is the only thing keeping a bookkeeping rule off noise"
            ),
            lambda root: _write(
                root, PAYLOAD_RENDER_REL, FIXTURE_CITATION_SHAPED_NOISE
            ),
        ),
    ]


PAYLOAD_ASSET_BUNDLE_REL = "compiler/golden/wavetables.dat"


def _asset_bundle_row(covers=None):
    """A provenance row for the synthetic wavetable bundle, plus the manifest's
    own `self-declared-quotation` exemption.

    The row's class is `vendored-copy`, so the manifest itself then carries the
    quotation vocabulary beside an upstream citation — exactly as the real
    `decision-records/provenance.json` does, and exempted the same way (that
    file's own exemption, not a special case in the tool). Without it the
    control would fail on a confound rather than on the rule under test.
    """
    row = {
        "path": PAYLOAD_ASSET_BUNDLE_REL,
        "class": "vendored-copy",
        "content": "synthetic: an archive of upstream wavetable assets",
        "upstream": "surge-synthesizer/surge",
        "pinned_commit": FIXTURE_SUBMODULE_COMMIT,
        "upstream_license": "GPL-3.0-or-later",
        "decision_record": "0001",
    }
    if covers is not None:
        row["covers"] = list(covers)
    exemption = {
        "path": MANIFEST_REL,
        "rules": ["self-declared-quotation"],
        "reason": "synthetic: the manifest's own rows use the quotation vocabulary",
    }

    def mutate(root):
        _write(root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME)
        _patch_manifest(
            root,
            lambda d: (d["entries"].append(row), d["exemptions"].append(exemption)),
        )

    return mutate


def _wrapper_name_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    Increment 9 — the NAMES inside a wrapper, which increment 8 declared rather
    than closed. Every must-fail case below audited **clean** on increment 8's
    tool while `--negative-control` reported all 31 rules, all 40 masking
    controls, all 11 discovery controls and all 17 payload controls behaving:
    the files carry no license text to find, and their outer name is in neither
    extension set.

    The positive controls carry at least as much weight as on every earlier
    increment. `wrapper-member-name` is non-exemptible, so a false positive on
    this repository's own 19 wrappers — 15 gzipped traces that really do carry
    an FNAME, and the `.npz` tap fixture whose 11 members are all `.npy` — could
    only be answered by switching the rule off. Both were measured over the
    real tree before this was written: 0 hits across its 26 member names
    (9 `.json`, 6 `.hex`, 11 `.npy`; 3 gzip streams carry no FNAME at all).

    Increment 12 adds one more must-fail case to the same set:
    `second-member-of-a-concatenated-gzip-names-an-asset`, which audited
    **clean** on increment 11's tool (the FNAME was read once per stream, from
    the first member) and fires now. The real tree is unaffected either way —
    all 18 of its tracked gzip streams are single-member, re-derived by
    `test_real_tree_gzip_streams_are_all_single_member`.
    """
    return [
        (
            "wrapper/zip-member-named-as-an-upstream-asset",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a zip renamed '.dat' whose member is a '.wt' wavetable with no marker",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/tar-member-named-as-foreign-source",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a tar.gz renamed '.dat' carrying a stripped '.cpp' — no notice in it",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_TAR_GZ_WITH_SOURCE_MEMBER_NAME
            ),
            "Reverb1.cpp",
        ),
        (
            "wrapper/gzip-fname-header-names-an-asset",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a gzip whose FNAME header is the only name it has ('Bank Sine.wt')",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_GZIP_WITH_ASSET_FNAME
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/second-member-of-a-concatenated-gzip-names-an-asset",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "increment 12: a CONCATENATED gzip whose SECOND member's FNAME "
            "names a '.wt' — increment 9 read the first member's name only, so "
            "this audited clean while the same two members in the other order "
            "fired",
            lambda root: _write(
                root,
                PAYLOAD_ASSET_BUNDLE_REL,
                FIXTURE_MULTI_MEMBER_GZIP_SECOND_NAMES_AN_ASSET,
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/asset-member-inside-a-gzipped-zip",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "the recursion site: a zip inside a gzip, '.wt' member two deep",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_GZIPPED_ZIP_WITH_ASSET_MEMBER
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/outer-member-name-not-masked-by-the-inner-one",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "a '.wt' member that is itself a gzip of 'meta.json' — the outer "
            "name must still be judged",
            lambda root: _write(
                root, PAYLOAD_ASSET_BUNDLE_REL, FIXTURE_ZIP_WITH_WRAPPED_ASSET_MEMBER
            ),
            "Bank Sine.wt",
        ),
        (
            "wrapper/own-gzipped-trace-with-an-fname-stays-clean",
            None,
            None,
            "this repository's real shape: a gzipped JSON trace whose gzip "
            "header carries its original '.json' filename",
            lambda root: _write(
                root,
                "reports/artifacts/trace.json.gz",
                FIXTURE_OWN_GZIPPED_TRACE_WITH_FNAME,
            ),
        ),
        (
            "wrapper/own-npz-members-stay-clean",
            None,
            None,
            "an '.npz' tap fixture: a zip of this project's own '.npy' members",
            lambda root: _write(
                root, "reports/fixtures/taps.npz", FIXTURE_OWN_NPZ_MEMBERS
            ),
        ),
        (
            "wrapper/asset-member-answered-by-a-row-passes",
            None,
            None,
            "the rule is ANSWERABLE: a row citing its record and declaring "
            "'covers' clears the same bundle",
            _asset_bundle_row(covers=["wrapper-member-name"]),
        ),
        (
            "wrapper/a-row-without-covers-does-not-clear-it",
            "wrapper-member-name",
            PAYLOAD_ASSET_BUNDLE_REL,
            "and coverage is not implicit: the SAME row without 'covers' still "
            "fails, so a row filed for another reason cannot absorb a member "
            "name added later",
            _asset_bundle_row(),
            "Bank Sine.wt",
        ),
    ]


# --- index-boundary (coverage) controls, increment 11 -------------------------
#
# These assert on COVERAGE, not on findings, which is why they need their own
# runner: the default behaviour under test is deliberately "this file produces
# no finding", and a control that only checked findings would be satisfied by
# the very silence the increment exists to remove. Each one therefore checks
# what the run SAID about the entry it did not audit.
FIXTURE_UNTRACKED_REL = "model/pasted_unstaged.py"


def _git_init_with_untracked(root: Path, rel=FIXTURE_UNTRACKED_REL,
                             content=None, ignored=False):
    """Commit the skeleton, then leave `rel` on disk and OUT of the index."""
    if ignored:
        _write(root, ".gitignore", rel + "\n")
    _git(root, "init", "-q")
    # -f for the same reason _git_submodule_entry uses it: a host-level
    # core.excludesFile must not silently drop skeleton files.
    _git(root, "add", "-A", "-f")
    _write(root, rel, FIXTURE_GPL_BODY if content is None else content)


def _coverage_controls():
    """[(label, description, mutate, check(findings, stats) -> (ok, detail))].

    Increment 11 — the ENUMERATION layer, below the by-reference discovery
    layer increment 7 closed. The negative case audited **clean** with a file
    count identical to the clean tree's, while `--negative-control` reported
    all 31 rules firing: `list_entries` reads the git index, so an unstaged
    file is in no rule's input at all.
    """

    def unindexed(stats):
        return stats["entries_present_but_not_in_the_index"]

    def check_counted_and_disclosed(findings, stats):
        paths = unindexed(stats)
        if FIXTURE_UNTRACKED_REL not in paths:
            return False, (
                "the unstaged carrier was NOT disclosed as un-audited "
                f"(entries_present_but_not_in_the_index={paths})"
            )
        if any(f.path == FIXTURE_UNTRACKED_REL for f in findings):
            return False, "default run flagged an unstaged file (it must only disclose it)"
        return True, f"disclosed as not audited: {paths}"

    def check_clean_tree_reports_zero(findings, stats):
        paths = unindexed(stats)
        if paths:
            return False, f"a fully staged tree reported un-indexed entries: {paths}"
        if findings:
            return False, "false alarm on a clean, fully staged tree"
        return True, "reports 0 un-indexed entries (printed, not omitted)"

    def check_not_counted(findings, stats):
        paths = unindexed(stats)
        if paths:
            return False, f"counted a path it must not: {paths}"
        if findings:
            return False, (
                "produced a finding: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings)
            )
        return True, "neither counted nor audited"

    return [
        (
            "coverage/unstaged-carrier-is-disclosed-not-silently-skipped",
            "an unattributed GPL-bodied file on disk but not in the index",
            _git_init_with_untracked,
            check_counted_and_disclosed,
        ),
        (
            "coverage/fully-staged-tree-reports-zero",
            "a tree with nothing unstaged still reports the count, as zero",
            lambda root: (_git(root, "init", "-q"), _git(root, "add", "-A", "-f")),
            check_clean_tree_reports_zero,
        ),
        (
            "coverage/gitignored-scratch-is-neither-counted-nor-audited",
            "the declared sub-boundary: an ignored path is this repo's own "
            "statement that it is not part of it",
            lambda root: _git_init_with_untracked(root, ignored=True),
            check_not_counted,
        ),
        (
            "coverage/unstaged-path-inside-a-declared-scope-exclusion",
            "an unstaged file in an already-disclosed hole is not re-counted",
            lambda root: (
                _patch_manifest(
                    root,
                    lambda d: d["scope_exclusions"].append(
                        {"prefix": ".loom/", "reason": "synthetic declared hole"}
                    ),
                ),
                # A tracked file inside the hole, so the exclusion is not stale.
                _write(root, ".loom/notes.md", "declared, unaudited.\n"),
                _git_init_with_untracked(root, rel=".loom/pasted_unstaged.py"),
            ),
            check_not_counted,
        ),
        (
            "coverage/non-git-tree-reports-zero-and-still-audits-everything",
            "a synthetic (non-checkout) tree: every file is walked, so nothing "
            "is un-indexed and the carrier still fires",
            lambda root: _write(root, FIXTURE_UNTRACKED_REL, FIXTURE_GPL_BODY),
            lambda findings, stats: (
                (False, f"reported un-indexed entries in a non-git tree: {unindexed(stats)}")
                if unindexed(stats)
                else (
                    (True, "0 un-indexed, and foreign-license-text fired on the carrier")
                    if any(
                        f.rule == "foreign-license-text"
                        and f.path == FIXTURE_UNTRACKED_REL
                        for f in findings
                    )
                    else (False, "the walked carrier did not produce a finding")
                )
            ),
        ),
    ]


def _coverage_include_untracked_controls():
    """The same fixtures, run with `--include-untracked`: the boundary crossed.

    Separated from `_coverage_controls` because they need a different audit
    call, not a different assertion — which is exactly the thing a control
    must pin: reverting the `--include-untracked` wiring leaves the default
    controls above passing and only these failing.
    """

    def check_audited(findings, stats):
        if stats["entries_present_but_not_in_the_index"]:
            return False, (
                "entries were audited but still reported as not audited: "
                f"{stats['entries_present_but_not_in_the_index']}"
            )
        fired = [
            f
            for f in findings
            if f.rule == "foreign-license-text" and f.path == FIXTURE_UNTRACKED_REL
        ]
        if not fired:
            return False, (
                "foreign-license-text did NOT fire on the unstaged carrier "
                "(found "
                + (", ".join(sorted({f"{f.rule}@{f.path}" for f in findings})) or "nothing")
                + ")"
            )
        return True, f"foreign-license-text fired on {FIXTURE_UNTRACKED_REL}"

    def check_ignored_still_out(findings, stats):
        if any(f.path == FIXTURE_UNTRACKED_REL for f in findings):
            return False, "an ignored path was audited; the sub-boundary is declared"
        return True, "an ignored path stays out even with --include-untracked"

    return [
        (
            "coverage/unstaged-carrier-is-audited-when-included",
            "acceptance item 4's demonstration, run without staging the fixture",
            _git_init_with_untracked,
            check_audited,
        ),
        (
            "coverage/ignored-path-stays-out-even-when-included",
            "the declared sub-boundary holds on the opt-in path too",
            lambda root: _git_init_with_untracked(root, ignored=True),
            check_ignored_still_out,
        ),
    ]


# --- staged-content controls, increment 14 ------------------------------------
#
# These use the coverage runner (findings AND stats), because the increment has
# two halves that must both hold: the staged view must FIRE on a carrier the
# working-tree copy hides, and the divergence must be DISCLOSED even when the
# staged bytes are clean. A control that only checked findings would pass on a
# tool that read the index blob and said nothing about having done so; one that
# only checked coverage would pass on a tool that counted the divergence and
# never read it.
FIXTURE_STAGED_REL = "model/pasted_staged.py"
FIXTURE_STAGED_BUNDLE_REL = "compiler/golden/staged_bundle.dat"
FIXTURE_INNOCUOUS = "# nothing third-party here\n"


def _stage_all(root: Path):
    """Make `root` a git checkout with every file in it staged (no commit).

    No commit is needed — and none is made, so no committer identity is
    required: `git commit` publishes the INDEX, which is exactly the content
    under test here.
    """
    _git(root, "init", "-q")
    # -f for the same reason the other git fixtures use it: a host-level
    # core.excludesFile must not silently drop skeleton files.
    _git(root, "add", "-A", "-f")


def _stage_then_replace(root: Path, rel=FIXTURE_STAGED_REL, staged=None,
                        working=FIXTURE_INNOCUOUS, assume_unchanged=False):
    """Stage `staged` at `rel`, then put `working` (or nothing) on disk.

    `working=None` deletes the working-tree copy. `assume_unchanged` sets the
    index bit that makes `git diff-files` report the entry clean no matter what
    the working copy holds — the "stop looking" switch that sits directly under
    this rule.
    """
    _write(root, rel, FIXTURE_GPL_BODY if staged is None else staged)
    _stage_all(root)
    if assume_unchanged:
        _git(root, "update-index", "--assume-unchanged", rel)
    if working is None:
        (root / rel).unlink()
    else:
        _write(root, rel, working)


def _staged_controls():
    """[(label, description, mutate, check(findings, stats) -> (ok, detail))].

    Increment 14 — the BYTE SOURCE, below the enumeration layer increment 11
    disclosed. Increment 7 moved the discovery rules onto the index; the content
    rules kept reading `root / rel`. Every must-fire case below audited **PASS**
    on increment 12's tool, with `--negative-control` reporting all 32 rules,
    40 masking, 11 discovery, 27 payload, 10 wrapper-name and 7 coverage
    controls behaving, and with coverage identical to a clean tree's — while the
    staged blob held a complete GPL body that `git commit` would publish.

    The must-NOT-fire cases carry equal weight, in two directions. An unstaged
    paste into a tracked file must keep firing: the point is a SECOND view, not
    a different one, and replacing the working-tree read with an index read
    would close this masking path by opening the one the audit is most used
    for (a local run before `git add`). And a divergent entry whose staged bytes
    are clean must be counted, not flagged — a working copy differing from the
    index is the normal state of a tree being edited, and a finding there would
    be noise on a non-exemptible rule.
    """

    def divergent(stats):
        return stats["entries_whose_staged_content_differs_from_the_working_tree"]

    def fired(findings, rule, rel):
        return [f for f in findings if f.rule == rule and f.path == rel]

    def check_staged_carrier(rule=("foreign-license-text"), rel=FIXTURE_STAGED_REL,
                             absent=False):
        def check(findings, stats):
            if rel not in divergent(stats):
                return False, (
                    "the divergent entry was not disclosed "
                    f"(entries_whose_staged_content_differs…={divergent(stats)})"
                )
            if absent and rel not in stats["staged_entries_absent_from_the_working_tree"]:
                return False, (
                    "an entry with no working-tree copy was not reported as absent "
                    f"({stats['staged_entries_absent_from_the_working_tree']})"
                )
            hits = fired(findings, rule, rel)
            if not hits:
                return False, (
                    f"{rule} did NOT fire on the staged content of {rel} (found "
                    + (", ".join(sorted({f"{f.rule}@{f.path}" for f in findings})) or "nothing")
                    + ")"
                )
            # The finding must SAY which bytes offended: "the working-tree copy
            # is clean" changes what the author has to do about it.
            if not any("STAGED" in f.detail for f in hits):
                return False, (
                    "the finding does not name the staged content as its source: "
                    + "; ".join(repr(f.detail) for f in hits)
                )
            return True, f"{rule} fired on the staged content of {rel}, and said so"

        return check

    def check_worktree_carrier_still_fires(findings, stats):
        hits = fired(findings, "foreign-license-text", FIXTURE_STAGED_REL)
        if not hits:
            return False, (
                "an UNSTAGED paste into a tracked file stopped firing — the "
                "working-tree view was replaced instead of joined"
            )
        if any("STAGED" in f.detail for f in hits):
            return False, (
                "the working-tree paste was reported as staged content: "
                + "; ".join(repr(f.detail) for f in hits)
            )
        return True, "the working-tree view still fires, and is not mislabelled"

    def check_clean_tree_reports_zero(findings, stats):
        if divergent(stats):
            return False, (
                f"a fully staged tree reported divergence: {divergent(stats)}"
            )
        if findings:
            return False, "false alarm on a clean, fully staged tree"
        return True, "reports 0 divergent entries (printed, not omitted)"

    def check_counted_not_flagged(findings, stats):
        if FIXTURE_STAGED_REL not in divergent(stats):
            return False, (
                "an innocuous modification was not disclosed as divergent "
                f"({divergent(stats)})"
            )
        if stats["staged_payloads_content_scanned"] < 1:
            return False, "the divergence was counted but its staged bytes were not read"
        if findings:
            return False, (
                "flagged a divergent entry whose staged bytes are clean: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings)
            )
        return True, "counted and read, not flagged"

    def check_not_counted(findings, stats):
        if divergent(stats):
            return False, f"counted a path it must not: {divergent(stats)}"
        if findings:
            return False, (
                "produced a finding: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings)
            )
        return True, "neither counted nor read as a second view"

    return [
        (
            "staged/staged-carrier-whose-working-tree-copy-was-cleaned",
            "a GPL body `git add`ed and then overwritten on disk — the commit "
            "would publish the body the audit read past",
            _stage_then_replace,
            check_staged_carrier(),
        ),
        (
            "staged/staged-carrier-whose-working-tree-copy-was-deleted",
            "the same carrier staged and then deleted: `open()` failed and the "
            "entry was counted among the opaque payloads",
            lambda root: _stage_then_replace(root, working=None),
            check_staged_carrier(absent=True),
        ),
        (
            "staged/assume-unchanged-does-not-stop-the-staged-read",
            "the index bit that makes `git diff-files` call the entry clean "
            "however the working copy differs",
            lambda root: _stage_then_replace(root, assume_unchanged=True),
            check_staged_carrier(),
        ),
        (
            "staged/staged-wrapper-member-name-is-judged",
            "a zip of upstream `.wt` members renamed '.dat', staged and then "
            "replaced on disk — no content signal exists in it to find",
            lambda root: _stage_then_replace(
                root,
                rel=FIXTURE_STAGED_BUNDLE_REL,
                staged=FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME,
                working=b"not an archive at all\n",
            ),
            check_staged_carrier(
                rule="wrapper-member-name", rel=FIXTURE_STAGED_BUNDLE_REL
            ),
        ),
        (
            "staged/an-unstaged-working-tree-carrier-still-fires",
            "the regression direction: a paste into a tracked file that has NOT "
            "been staged is what a pre-commit run is for",
            lambda root: _stage_then_replace(
                root, staged=FIXTURE_INNOCUOUS, working=FIXTURE_GPL_BODY
            ),
            check_worktree_carrier_still_fires,
        ),
        (
            "staged/fully-staged-tree-reports-zero",
            "a tree whose index matches its working copy still reports the "
            "count, as zero",
            _stage_all,
            check_clean_tree_reports_zero,
        ),
        (
            "staged/innocuous-divergence-is-counted-and-read-not-flagged",
            "an ordinary unstaged edit: disclosed and scanned, never a finding",
            lambda root: _stage_then_replace(
                root,
                staged=FIXTURE_INNOCUOUS,
                working=FIXTURE_INNOCUOUS + "# one more line, still nothing\n",
            ),
            check_counted_not_flagged,
        ),
        (
            "staged/divergent-path-inside-a-declared-scope-exclusion",
            "a divergence in an already-disclosed hole is not re-counted, for "
            "the same reason increment 11 does not re-count one",
            lambda root: (
                _patch_manifest(
                    root,
                    lambda d: d["scope_exclusions"].append(
                        {"prefix": ".loom/", "reason": "synthetic declared hole"}
                    ),
                ),
                _stage_then_replace(root, rel=".loom/pasted_staged.py"),
            ),
            check_not_counted,
        ),
        (
            "staged/a-gitlink-is-not-read-as-a-staged-blob",
            "a committed submodule's object is a commit in another repository, "
            "not a blob here: it must not become a staged view",
            lambda root: (_git_submodule_entry(root), None),
            lambda findings, stats: (
                (False, f"read a gitlink as a staged view: {divergent(stats)}")
                if FIXTURE_SUBMODULE_REL in divergent(stats)
                else (
                    (True, "the gitlink stays a by-reference entry, judged at discovery")
                    if any(
                        f.rule == "submodule-reference"
                        and f.path == FIXTURE_SUBMODULE_REL
                        for f in findings
                    )
                    else (False, "the gitlink stopped producing its discovery finding")
                )
            ),
        ),
    ]


# --- committed-answer-set fixtures (increment 15) -----------------------------
#
# Every case here turns on the SAME one-line difference: whether the answer a
# carriage finding needs is in the index as well as on disk. The carrier itself
# is identical in both views throughout — that is the point. Increment 14 reads
# the committable BYTES of an entry; these fixtures move the committable ANSWER.
FIXTURE_COMMITTED_CARRIER_REL = "model/pasted_committed.py"
FIXTURE_SKELETON_CARRIER_REL = "model/carrier.py"
FIXTURE_SECOND_RECORD_NUMBER = "0002"
FIXTURE_SECOND_RECORD_REL = "decision-records/0002-second.md"


def _committed_row(path=FIXTURE_COMMITTED_CARRIER_REL, covers=None):
    """A well-formed provenance row for a GPL-bodied carrier.

    Corroborated by the pinned commit, which the carrier cites, so the row is
    rejected for being unstaged and for nothing else.
    """
    row = {
        "path": path,
        "class": "quoted-constants",
        "content": "synthetic TABLE",
        "upstream": "synthetic upstream",
        "pinned_commit": FIXTURE_SUBMODULE_COMMIT,
        "upstream_license": "GPL-3.0-or-later",
        "decision_record": "0001",
        "covers": list(covers or ["foreign-license-text"]),
    }
    return row


FIXTURE_COMMITTED_CARRIER = (
    FIXTURE_GPL_BODY
    + f"# pinned at {FIXTURE_SUBMODULE_COMMIT}\n"
    + "TABLE = [1, 2, 3]\n"
)


def _stage_carrier_then_answer_on_disk(root: Path, answer, rel=None,
                                       body=FIXTURE_COMMITTED_CARRIER):
    """Stage a carrier (and the whole skeleton), then write `answer` to DISK only.

    `answer(root)` patches `decision-records/` without staging it, which is the
    entire mask: `git commit` publishes the carrier and a bookkeeping set that
    does not answer it.
    """
    if rel is not None:
        _write(root, rel, body)
    _stage_all(root)
    answer(root)


def _committed_bookkeeping_controls():
    """[(label, description, mutate, check(findings, stats) -> (ok, detail))].

    Increment 15 — the ANSWER SET, the other half of the layer increment 14
    opened. Increment 14 asked each carriage question of both byte views an
    entry can have; the four groups' ANSWERS (a provenance row, an exemption, a
    scope exclusion, the record index, a record's own header) kept coming from
    the working-tree copy of `decision-records/` alone. So every must-fire case
    below audited **PASS** on increment 14's tool — with all 32 rules, 40
    masking, 17 discovery, 27 payload, 10 wrapper-name, 7 coverage and 9 staged
    controls reported as behaving, and with the carrier's own bytes identical in
    both views — while the commit published the carrier and a manifest, index or
    record that does not answer it.

    Two of these are not hypothetical constructions: `_patch_manifest` wrote the
    manifest to disk without staging it, so TWO pre-existing discovery controls
    (a gitlink answered by a row, and an excluded gitlink answered by a row)
    were passing on an answer no commit published. They are fixed in the same
    change, by staging the fixture's answer — not by exempting them.

    The must-NOT-fire cases carry equal weight and in the same two directions as
    increment 14's. The second pass must not fire when the bookkeeping agrees in
    both views — including when some ORDINARY file diverges, which is the normal
    state of a tree being edited and must not drag the answer set into a second
    judgement. And a bookkeeping edit that changes no answer must be disclosed
    and produce nothing, because a developer editing a `note` field is not
    committing a license violation.
    """

    def bookkeeping(stats):
        return stats["divergent_bookkeeping_files"]

    def check_committable_finding(rule, rel):
        def check(findings, stats):
            if MANIFEST_REL not in bookkeeping(stats) and INDEX_REL not in bookkeeping(
                stats
            ) and not bookkeeping(stats):
                return False, (
                    "the divergent bookkeeping was not disclosed "
                    f"(divergent_bookkeeping_files={bookkeeping(stats)})"
                )
            hits = [f for f in findings if f.rule == rule and f.path == rel]
            if not hits:
                return False, (
                    f"{rule} did NOT fire against the committable answer set for "
                    f"{rel} (found "
                    + (
                        ", ".join(sorted({f"{f.rule}@{f.path}" for f in findings}))
                        or "nothing"
                    )
                    + ")"
                )
            # The finding must SAY the answer set is what differs. "Your file is
            # undeclared" is wrong and unactionable here: the file IS declared,
            # on disk, and the remedy is `git add decision-records/`.
            if not any("ANSWER SET" in f.detail for f in hits):
                return False, (
                    "the finding does not name the committable answer set as its "
                    "source: " + "; ".join(repr(f.detail) for f in hits)
                )
            if stats["committed_answer_set_findings"] < 1:
                return False, "the finding was not counted in the coverage line"
            return True, (
                f"{rule} fired against the committable answer set for {rel}, and "
                "said so"
            )

        return check

    def check_no_second_answer_set(findings, stats):
        if bookkeeping(stats):
            return False, (
                "reported a divergent answer set where the bookkeeping agrees: "
                f"{bookkeeping(stats)}"
            )
        if stats["committed_answer_set_findings"]:
            return False, "ran the committable pass on an undiverged answer set"
        if findings:
            return False, (
                "false alarm: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings)
            )
        return True, "no second answer set, and the list is printed as empty"

    def check_disclosed_not_flagged(findings, stats):
        if MANIFEST_REL not in bookkeeping(stats):
            return False, (
                "a bookkeeping divergence was not disclosed "
                f"({bookkeeping(stats)})"
            )
        if findings:
            return False, (
                "flagged a bookkeeping edit that changes no answer: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings)
            )
        return True, "disclosed as a second answer set, and produced nothing"

    def answer_row_on_disk(root):
        _patch_manifest(
            root, lambda d: d["entries"].append(_committed_row()), stage=False
        )

    def strip_skeleton_row_from_the_index(root):
        """The converse shape: the row is REMOVED from the index, kept on disk."""
        full = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))
        stripped = dict(full)
        stripped["entries"] = [
            e for e in full["entries"] if e.get("path") != FIXTURE_SKELETON_CARRIER_REL
        ]
        _write(root, MANIFEST_REL, json.dumps(stripped, indent=2) + "\n")
        _stage_all(root)
        _write(root, MANIFEST_REL, json.dumps(full, indent=2) + "\n")

    def exemption_on_disk(root):
        _patch_manifest(
            root,
            lambda d: d["exemptions"].append(
                {
                    "path": FIXTURE_SKELETON_CARRIER_REL,
                    "rules": ["self-declared-quotation"],
                    "reason": "synthetic: unstaged exemption",
                }
            ),
            stage=False,
        )

    def strip_skeleton_row_and_exempt_on_disk(root):
        strip_skeleton_row_from_the_index(root)
        exemption_on_disk(root)

    def exclusion_on_disk(root):
        _patch_manifest(
            root,
            lambda d: d["scope_exclusions"].append(
                {"prefix": "model/", "reason": "synthetic: unstaged hole"}
            ),
            stage=False,
        )

    def index_row_on_disk(root):
        """A second record, cited by a staged file, indexed on DISK only."""
        _write(
            root,
            FIXTURE_SECOND_RECORD_REL,
            "# 0002 second\n\n- **Status**: PROPOSED\n- **Date**: 2026-10-01\n",
        )
        _write(
            root,
            "docs/cites_0002.md",
            "This follows decision-records/0002-second.md.\n",
        )
        _stage_all(root)
        row = (
            f"| [{FIXTURE_SECOND_RECORD_NUMBER}]"
            f"({FIXTURE_SECOND_RECORD_REL.split('/')[-1]}) | Second record "
            "(synthetic) | PROPOSED | 2026-10-01 |\n"
        )
        _write(
            root,
            INDEX_REL,
            (root / INDEX_REL).read_text(encoding="utf-8").rstrip("\n") + "\n" + row,
        )

    def covers_broadened_on_disk(root):
        """The skeleton carrier gains a GPL body; its row's `covers` grows on disk."""
        _write(
            root,
            FIXTURE_SKELETON_CARRIER_REL,
            (root / FIXTURE_SKELETON_CARRIER_REL).read_text(encoding="utf-8")
            + FIXTURE_GPL_BODY,
        )
        _stage_all(root)
        def widen(data):
            for entry in data["entries"]:
                if entry.get("path") == FIXTURE_SKELETON_CARRIER_REL:
                    entry["covers"] = sorted(
                        set(entry.get("covers") or []) | {"foreign-license-text"}
                    )
        _patch_manifest(root, widen, stage=False)

    def answer_row_staged_too(root):
        _write(root, FIXTURE_COMMITTED_CARRIER_REL, FIXTURE_COMMITTED_CARRIER)
        _patch_manifest(root, lambda d: d["entries"].append(_committed_row()))
        _stage_all(root)

    def innocuous_bookkeeping_edit(root):
        _stage_all(root)
        _patch_manifest(
            root,
            lambda d: d["entries"][0].update({"content": "synthetic TABLE (reworded)"}),
            stage=False,
        )

    def ordinary_file_diverges_only(root):
        _stage_then_replace(root, staged=FIXTURE_INNOCUOUS, working=FIXTURE_INNOCUOUS + "#\n")

    def manifest_removed_from_the_index_only(root):
        """`git rm --cached` the manifest: a commit publishes NO manifest.

        The sentinel case. A view that yields no text must not be spelled the
        same as "read the copy on disk", or the committable pass answers from
        the exact bytes it exists to stop answering from.
        """
        _stage_all(root)
        _git(root, "rm", "--cached", "-q", MANIFEST_REL)

    def check_absent_manifest_answers_nothing(findings, stats):
        if not any(f.rule == "manifest-missing" for f in findings):
            return False, (
                "a tree whose commit publishes no manifest audited without a "
                "manifest-missing finding (found "
                + (", ".join(sorted({f"{f.rule}@{f.path}" for f in findings})) or "nothing")
                + ")"
            )
        if not any(
            f.rule in ("foreign-license-text", "self-declared-quotation")
            for f in findings
        ):
            return False, (
                "the absent manifest still answered the skeleton's carrier — the "
                "copy on disk was read as a fallback"
            )
        return True, "an unpublished manifest answers nothing, and says so"

    return [
        (
            "committed/provenance-row-added-on-disk-only",
            "a staged GPL-bodied carrier whose row was written to "
            "provenance.json without being staged — the commit publishes the "
            "carrier and a manifest that does not mention it",
            lambda root: _stage_carrier_then_answer_on_disk(
                root, answer_row_on_disk, rel=FIXTURE_COMMITTED_CARRIER_REL
            ),
            check_committable_finding(
                "foreign-license-text", FIXTURE_COMMITTED_CARRIER_REL
            ),
        ),
        (
            "committed/provenance-row-removed-from-the-index-only",
            "the converse: an existing row deleted from the staged manifest and "
            "kept on disk, which no working-tree read can tell from a declared "
            "file",
            strip_skeleton_row_from_the_index,
            check_committable_finding(
                "self-declared-quotation", FIXTURE_SKELETON_CARRIER_REL
            ),
        ),
        (
            "committed/exemption-added-on-disk-only",
            "the one exemptible rule answered by an exemption that is on disk "
            "and in no commit",
            strip_skeleton_row_and_exempt_on_disk,
            check_committable_finding(
                "self-declared-quotation", FIXTURE_SKELETON_CARRIER_REL
            ),
        ),
        (
            "committed/scope-exclusion-added-on-disk-only",
            "a declared hole is a statement this repository publishes: one that "
            "exists only on disk hides the carrier from no commit",
            lambda root: _stage_carrier_then_answer_on_disk(
                root, exclusion_on_disk, rel=FIXTURE_COMMITTED_CARRIER_REL
            ),
            check_committable_finding(
                "foreign-license-text", FIXTURE_COMMITTED_CARRIER_REL
            ),
        ),
        (
            "committed/index-row-added-on-disk-only",
            "a staged citation of a staged record whose index row is on disk "
            "only: the published README indexes no such record",
            index_row_on_disk,
            check_committable_finding("unindexed-record-citation", "docs/cites_0002.md"),
        ),
        (
            "committed/row-covers-broadened-on-disk-only",
            "a staged GPL body over an already-declared file, with the row's "
            "'covers' widened to admit it on disk only",
            covers_broadened_on_disk,
            check_committable_finding(
                "foreign-license-text", FIXTURE_SKELETON_CARRIER_REL
            ),
        ),
        (
            "committed/the-same-answer-staged-too-passes",
            "the positive control: carrier and row staged together is the "
            "legitimate shape and must stay silent",
            answer_row_staged_too,
            check_no_second_answer_set,
        ),
        (
            "committed/fully-staged-bookkeeping-reports-zero",
            "a tree whose decision-records match the index still reports the "
            "list, as empty",
            _stage_all,
            check_no_second_answer_set,
        ),
        (
            "committed/an-ordinary-divergence-does-not-open-a-second-answer-set",
            "an unstaged edit to a file that answers nothing must not drag the "
            "bookkeeping into a second judgement",
            ordinary_file_diverges_only,
            check_no_second_answer_set,
        ),
        (
            "committed/a-manifest-absent-from-the-index-answers-nothing",
            "`git rm --cached` on the manifest: a view that yields no text must "
            "not fall back to the copy on disk",
            manifest_removed_from_the_index_only,
            check_absent_manifest_answers_nothing,
        ),
        (
            "committed/an-innocuous-bookkeeping-edit-is-disclosed-not-flagged",
            "a reworded 'content' field: two answer sets that answer the same "
            "things must be disclosed and produce nothing",
            innocuous_bookkeeping_edit,
            check_disclosed_not_flagged,
        ),
    ]


# --- committable-evidence fixtures (increment 16) -----------------------------
#
# The two checks OUTSIDE group 4 that read an entry's own content as evidence
# for a bookkeeping judgement. The bookkeeping itself is identical in both
# views in every case here — that is what separates these from increment 15's:
# the divergent entry is the CARRIER, so `divergent_bookkeeping()` is empty and
# the committable pass never runs.
FIXTURE_EVIDENCE_DOC_REL = "docs/plain.md"
FIXTURE_EVIDENCE_INNOCUOUS_DOC = "A document with no third-party content.\n"
FIXTURE_DANGLING_CITATION = "Licensing: see " + "decision-records/" + "0099.\n"
# The skeleton's declared carrier with its provenance statement removed: the
# row still names it, and these bytes corroborate neither its decision record
# nor its pinned commit.
FIXTURE_UNCITED_CARRIER = "TABLE = [1, 2, 3]\n"
FIXTURE_OPAQUE_ROW_REL = PAYLOAD_DUMP_REL


def _stage_then_restage(root: Path, rel, staged, working):
    """Stage the whole skeleton, then put `staged` in the index and `working` on disk.

    `working=None` deletes the working-tree copy, which is the shape whose
    working-tree view yields no text at all — the one that used to answer for
    the staged bytes as well.
    """
    _stage_all(root)
    _write(root, rel, staged)
    _git(root, "add", "-f", rel)
    if working is None:
        (root / rel).unlink()
    else:
        _write(root, rel, working)


def _committable_evidence_controls():
    """[(label, description, mutate, check(findings, stats) -> (ok, detail))].

    Increment 16 — the EVIDENCE a bookkeeping judgement rests on. Increment 14
    moved the carriage rules (group 4) onto both byte views of an entry;
    increment 15 moved the four groups' ANSWER SET onto the committable
    bookkeeping bytes. Neither reached the two places where a bookkeeping group
    reads an ENTRY's content: `check_citations` (group 2) and `_corroborate`
    (group 3). Both read the tree's default view alone, and neither pass two's
    trigger (`decision-records/` divergence) nor group 4's enumeration covers
    them — so all three must-fire cases below audited **PASS** on increment 15's
    tool, with the divergent carrier disclosed, read by group 4, and found clean
    there because the staged bytes carry no carriage signal at all. They do not
    need to: the defect is that a row or a citation the commit publishes is
    answered by bytes it does not.

    The must-NOT-fire cases carry equal weight in the same two directions as
    increment 14's. A citation or a stripped provenance statement in the
    WORKING TREE must keep firing, unlabelled — the point is a second view, not
    a different one, and a local run before `git add` is what the audit is most
    used for. A divergent carrier that corroborates its row in both views must
    be READ and stay silent, which is the normal state of a tree being edited.
    And the "no text in this view, so the row is the record" boundary must stay
    a boundary: a binary payload's row is corroborated by nothing in either
    view, exactly as before, or every opaque declared asset becomes a finding
    the moment its bytes are touched.
    """

    def evidence(stats):
        return stats["staged_views_read_as_bookkeeping_evidence"]

    def divergent(stats):
        return stats["entries_whose_staged_content_differs_from_the_working_tree"]

    def fired(findings, rule, rel):
        return [f for f in findings if f.rule == rule and f.path == rel]

    def check_staged_evidence(rule, rel):
        def check(findings, stats):
            if rel not in divergent(stats):
                return False, (
                    "the divergent carrier was not disclosed "
                    f"(entries_whose_staged_content_differs…={divergent(stats)})"
                )
            if stats["divergent_bookkeeping_files"]:
                return False, (
                    "the bookkeeping diverged too, so this control is not "
                    "testing increment 16's layer: "
                    f"{stats['divergent_bookkeeping_files']}"
                )
            hits = fired(findings, rule, rel)
            if not hits:
                return False, (
                    f"{rule} did NOT fire on the staged content of {rel} (found "
                    + (
                        ", ".join(sorted({f"{f.rule}@{f.path}" for f in findings}))
                        or "nothing"
                    )
                    + ")"
                )
            if rel not in evidence(stats):
                return False, (
                    "the staged view was not reported as read by a bookkeeping "
                    f"check (staged_views_read_as_bookkeeping_evidence={evidence(stats)})"
                )
            # The finding must SAY which bytes it read. "Your file does not cite
            # its record" is wrong and unactionable when the copy the author is
            # looking at does: the remedy is `git add`, not an edit.
            if not any("STAGED" in f.detail for f in hits):
                return False, (
                    "the finding does not name the staged content as its source: "
                    + "; ".join(repr(f.detail) for f in hits)
                )
            return True, f"{rule} fired on the staged content of {rel}, and said so"

        return check

    def check_worktree_evidence_still_fires(rule, rel):
        def check(findings, stats):
            hits = fired(findings, rule, rel)
            if not hits:
                return False, (
                    f"{rule} stopped firing on the WORKING-TREE copy — the "
                    "working-tree read was replaced instead of joined"
                )
            if any("STAGED" in f.detail for f in hits):
                return False, (
                    "a working-tree finding was reported as staged content: "
                    + "; ".join(repr(f.detail) for f in hits)
                )
            return True, f"{rule} still fires on the working-tree copy, unmislabelled"

        return check

    def check_read_and_silent(rel):
        def check(findings, stats):
            if rel not in divergent(stats):
                return False, (
                    f"the divergence was not disclosed ({divergent(stats)})"
                )
            if rel not in evidence(stats):
                return False, (
                    "the staged view was counted as divergent but no bookkeeping "
                    f"check read it ({evidence(stats)})"
                )
            if findings:
                return False, (
                    "flagged a carrier that corroborates its row in both views: "
                    + "; ".join(f"{f.rule}@{f.path}" for f in findings)
                )
            return True, "both views read as evidence, neither flagged"

        return check

    def check_opaque_row_untouched(rel):
        def check(findings, stats):
            if rel not in divergent(stats):
                return False, (
                    f"the divergence was not disclosed ({divergent(stats)})"
                )
            if rel in evidence(stats):
                return False, (
                    "reported a read a payload with no text cannot have given: "
                    f"{evidence(stats)}"
                )
            if findings:
                return False, (
                    "a declared binary payload's row became a finding: "
                    + "; ".join(f"{f.rule}@{f.path}" for f in findings)
                )
            return True, (
                "no text in either view, so the row is the record — disclosed, "
                "not read, not flagged"
            )

        return check

    def opaque_declared_payload(root):
        _patch_manifest(
            root,
            lambda d: d["entries"].append(
                {
                    "path": FIXTURE_OPAQUE_ROW_REL,
                    "class": "quoted-constants",
                    "content": "synthetic opaque dump",
                    "upstream": "synthetic upstream",
                    "pinned_commit": FIXTURE_SUBMODULE_COMMIT,
                    "upstream_license": "GPL-3.0-or-later",
                    "decision_record": "0001",
                }
            ),
        )
        _write(root, FIXTURE_OPAQUE_ROW_REL, _float_dump(seed=11))
        _stage_then_restage(
            root,
            FIXTURE_OPAQUE_ROW_REL,
            _float_dump(seed=22),
            _float_dump(seed=33),
        )

    return [
        (
            "evidence/a-row-corroborated-only-by-the-copy-on-disk",
            "the declared carrier `git add`ed with its provenance statement "
            "stripped, the citing copy left on disk — the commit publishes a "
            "row describing a file that states nothing",
            lambda root: _stage_then_restage(
                root,
                FIXTURE_SKELETON_CARRIER_REL,
                FIXTURE_UNCITED_CARRIER,
                SKELETON_CARRIER,
            ),
            check_staged_evidence(
                "manifest-uncorroborated", FIXTURE_SKELETON_CARRIER_REL
            ),
        ),
        (
            "evidence/a-row-whose-only-published-carrier-was-deleted-from-disk",
            "the same carrier staged uncited and then deleted: its working-tree "
            "view yields no text, which used to answer for the staged bytes too",
            lambda root: _stage_then_restage(
                root, FIXTURE_SKELETON_CARRIER_REL, FIXTURE_UNCITED_CARRIER, None
            ),
            check_staged_evidence(
                "manifest-uncorroborated", FIXTURE_SKELETON_CARRIER_REL
            ),
        ),
        (
            "evidence/a-record-citation-that-exists-only-in-the-staged-bytes",
            "a citation of a record that does not exist, staged and then "
            "removed from the working copy — the commit publishes the claim",
            lambda root: _stage_then_restage(
                root,
                FIXTURE_EVIDENCE_DOC_REL,
                FIXTURE_DANGLING_CITATION,
                FIXTURE_EVIDENCE_INNOCUOUS_DOC,
            ),
            check_staged_evidence(
                "dangling-record-citation", FIXTURE_EVIDENCE_DOC_REL
            ),
        ),
        (
            "evidence/a-dangling-citation-on-disk-only-still-fires",
            "the regression direction: an unstaged paste of a citation is what "
            "a pre-commit run is for",
            lambda root: _stage_then_restage(
                root,
                FIXTURE_EVIDENCE_DOC_REL,
                FIXTURE_EVIDENCE_INNOCUOUS_DOC,
                FIXTURE_DANGLING_CITATION,
            ),
            check_worktree_evidence_still_fires(
                "dangling-record-citation", FIXTURE_EVIDENCE_DOC_REL
            ),
        ),
        (
            "evidence/a-stripped-provenance-statement-on-disk-only-still-fires",
            "the same direction for corroboration: the row stands and the copy "
            "the author is editing no longer states its provenance",
            lambda root: _stage_then_restage(
                root,
                FIXTURE_SKELETON_CARRIER_REL,
                SKELETON_CARRIER,
                FIXTURE_UNCITED_CARRIER,
            ),
            check_worktree_evidence_still_fires(
                "manifest-uncorroborated", FIXTURE_SKELETON_CARRIER_REL
            ),
        ),
        (
            "evidence/a-carrier-citing-its-record-in-both-views-is-read-not-flagged",
            "an ordinary unstaged edit to a declared carrier that still states "
            "its provenance: read as evidence in both views, never a finding",
            lambda root: _stage_then_restage(
                root,
                FIXTURE_SKELETON_CARRIER_REL,
                SKELETON_CARRIER,
                SKELETON_CARRIER + "\nEXTRA = [7]\n",
            ),
            check_read_and_silent(FIXTURE_SKELETON_CARRIER_REL),
        ),
        (
            "evidence/a-declared-binary-payloads-row-is-corroborated-in-neither-view",
            "the boundary stays a boundary: a payload with no text in it states "
            "no provenance in either view, and its row is still the record",
            opaque_declared_payload,
            check_opaque_row_untouched(FIXTURE_OPAQUE_ROW_REL),
        ),
    ]


# --- history-layer fixtures (increment 17) ------------------------------------
#
# These controls build real COMMITS, because that is the layer under test: every
# earlier control family can make its point with a working tree or an index,
# while "a carrier published by a commit and deleted by the next one" has no
# representation outside a commit graph. Each case is audited twice — the
# ordinary tree audit of the final checkout AND the history audit — and the
# must-fire cases assert that the TREE audit is clean, which is what makes them
# controls for this increment rather than re-runs of increment 14's.

FIXTURE_HISTORY_CARRIER_REL = "model/pasted_history.py"
FIXTURE_HISTORY_ASSET_REL = "fixtures/wavetables/history.wt"
FIXTURE_HISTORY_ALIAS_REL = "docs/alias.md"
# Every commit reachable from the branch tip: the control trees are small, and a
# range that selects a subset would make each case's reach a second variable.
HISTORY_CONTROL_RANGE = "HEAD"


def _commit(root: Path, message):
    """Commit the index of a synthetic tree, with an identity of its own.

    `--no-verify` and the inline identity keep the control independent of the
    host's git configuration: a global hooksPath or a missing user.email must not
    turn a control into a setup failure.
    """
    _git(
        root,
        "-c",
        "user.name=Provenance Control",
        "-c",
        "user.email=control@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--no-verify",
        "-q",
        "-m",
        message,
    )


def _commit_all(root: Path, message):
    """Stage everything in the tree (including deletions) and commit it."""
    _git(root, "add", "-A", "-f")
    _commit(root, message)


def _history_repo(root: Path):
    """Turn the skeleton into a git checkout with one clean commit."""
    _git(root, "init", "-q")
    _commit_all(root, "skeleton: a tree that audits clean")


def _history_row(path, covers=None):
    """A provenance row answering a synthetic history carrier."""
    return {
        "path": path,
        "class": "quoted-constants",
        "content": "synthetic: a carrier published by one commit in the range",
        "upstream": "synthetic upstream",
        "pinned_commit": FIXTURE_SUBMODULE_COMMIT,
        "upstream_license": "GPL-3.0-or-later",
        "decision_record": "0001",
        "covers": list(covers or ["foreign-license-text"]),
    }


def _history_controls():
    """[(label, description, revrange, mutate, check)] for the history pass.

    `check(findings, stats, tree_findings)` -> (ok, detail). `findings` is None
    and `stats` is the exception when the history audit deliberately refuses to
    run, which is itself one of the behaviours under test: a range that resolves
    to no commits must be an error, not an empty PASS.
    """

    def fired(findings, rule, rel, standing=None, in_detail=None):
        """(ok, detail) for "this rule fired on this path in published history"."""
        hits = [
            f
            for f in findings
            if f.rule == rule and f.path.startswith(rel + " [commit ")
        ]
        if not hits:
            found = ", ".join(sorted({f"{f.rule}@{f.path}" for f in findings})) or "nothing"
            return False, f"{rule} did NOT fire on {rel} in history (found {found})"
        if standing is not None and not any(standing in f.detail for f in hits):
            return False, (
                f"{rule} fired on {rel} but not with standing {standing!r} "
                "(details: " + "; ".join(repr(f.detail) for f in hits) + ")"
            )
        if in_detail is not None and not any(in_detail in f.detail for f in hits):
            return False, (
                f"{rule} fired on {rel} but no finding quoted {in_detail!r} "
                "(details: " + "; ".join(repr(f.detail) for f in hits) + ")"
            )
        return True, f"{rule} fired on {rel} in published history"

    def must_fire(rule, rel, standing=None, in_detail=None):
        def check(findings, stats, tree_findings):
            if findings is None:
                return False, f"the history audit did not run: {stats}"
            if tree_findings:
                # The point of this family: the bytes are gone from the final
                # tree. A control whose TREE audit also fails proves nothing
                # about history.
                return False, (
                    "the tree audit of the final checkout is NOT clean, so this "
                    "case does not isolate the history layer: "
                    + ", ".join(sorted({f.rule for f in tree_findings}))
                )
            return fired(findings, rule, rel, standing, in_detail)

        return check

    def must_be_clean(findings, stats, tree_findings):
        if findings is None:
            return False, f"the history audit did not run: {stats}"
        if findings:
            return False, "history findings on a correctly declared tree: " + ", ".join(
                sorted({f"{f.rule}@{f.path}" for f in findings})
            )
        if not stats["commits_judged"]:
            return False, "no commit was judged at all, so 'clean' means nothing"
        return True, f"{stats['commits_judged']} commit(s) judged, no finding"

    def add_then_delete(root, rel=FIXTURE_HISTORY_CARRIER_REL, payload=None):
        _history_repo(root)
        _write(root, rel, FIXTURE_GPL_BODY if payload is None else payload)
        _commit_all(root, "add an undeclared carrier")
        (root / rel).unlink()
        _commit_all(root, "delete it again")

    def declared_in_the_same_commit(root):
        _history_repo(root)
        _write(root, FIXTURE_HISTORY_CARRIER_REL, FIXTURE_GPL_BODY)
        _patch_manifest(
            root,
            lambda d: d["entries"].append(_history_row(FIXTURE_HISTORY_CARRIER_REL)),
            stage=False,
        )
        _commit_all(root, "add a carrier AND its row, together")
        (root / FIXTURE_HISTORY_CARRIER_REL).unlink()
        _patch_manifest(
            root,
            lambda d: d.__setitem__(
                "entries",
                [e for e in d["entries"] if e.get("path") != FIXTURE_HISTORY_CARRIER_REL],
            ),
            stage=False,
        )
        _commit_all(root, "remove both")

    def declared_one_commit_late(root):
        _history_repo(root)
        _write(root, FIXTURE_HISTORY_CARRIER_REL, FIXTURE_GPL_BODY)
        _commit_all(root, "add the carrier")
        # The second commit does what an author would do once reminded: adds the
        # row AND states the provenance in the file, so the FINAL tree audits
        # clean. What the first commit published is unchanged by that, which is
        # the whole point of the case.
        _write(
            root,
            FIXTURE_HISTORY_CARRIER_REL,
            FIXTURE_GPL_BODY + "\n# Provenance: " + "DR-" + "0001.\n",
        )
        _patch_manifest(
            root,
            lambda d: d["entries"].append(_history_row(FIXTURE_HISTORY_CARRIER_REL)),
            stage=False,
        )
        _commit_all(root, "declare it, one commit late")

    def manifest_deleted_with_the_carrier(root):
        _history_repo(root)
        _write(root, FIXTURE_HISTORY_CARRIER_REL, FIXTURE_GPL_BODY)
        (root / MANIFEST_REL).unlink()
        _commit_all(root, "delete the answer set and add a carrier in one commit")

    def no_manifest_before_the_first_one(root):
        # The pre-bookkeeping era: a first commit with a carrier and NO manifest
        # at all, then the manifest arrives (without a row for it).
        (root / MANIFEST_REL).unlink()
        _write(root, FIXTURE_HISTORY_CARRIER_REL, FIXTURE_GPL_BODY)
        _git(root, "init", "-q")
        _commit_all(root, "a tree from before the provenance manifest existed")
        (root / FIXTURE_HISTORY_CARRIER_REL).unlink()
        build_skeleton(root)
        _commit_all(root, "introduce the provenance manifest")

    def check_pre_manifest_disclosure(findings, stats, tree_findings):
        if findings is None:
            return False, f"the history audit did not run: {stats}"
        if findings:
            return False, (
                "a commit with no answer set must not be judged: "
                + ", ".join(sorted({f"{f.rule}@{f.path}" for f in findings}))
            )
        unjudged = stats["commits_not_judged_no_answer_set_yet"]
        if len(unjudged) != 1:
            return False, (
                f"expected exactly 1 commit disclosed as not judged, got "
                f"{len(unjudged)}"
            )
        if stats["commits_judged"] != 1:
            return False, f"expected 1 judged commit, got {stats['commits_judged']}"
        return True, (
            "the pre-manifest commit is disclosed as NOT judged (1) and the "
            "commit that introduced the manifest is judged (1)"
        )

    def check_dropped_manifest(findings, stats, tree_findings):
        ok, detail = fired(
            findings or [], "foreign-license-text", FIXTURE_HISTORY_CARRIER_REL
        )
        if not ok:
            return False, detail
        if not stats["commits_that_published_no_manifest_after_one_existed"]:
            return False, (
                "the finding fired but the deletion of the answer set was not "
                "disclosed, so a reader cannot tell why nothing answered"
            )
        return True, detail + ", with the deleted answer set disclosed"

    def same_bytes_at_two_paths(root):
        # The second path deliberately carries an UPSTREAM-ASSET extension while
        # the first does not: identical bytes, different structural signals. A
        # signal cache keyed on the blob alone would answer the `.wt` read from
        # the `.py` scan and lose the extension rule entirely.
        _history_repo(root)
        _write(root, FIXTURE_HISTORY_CARRIER_REL, FIXTURE_GPL_BODY)
        _commit_all(root, "add the carrier")
        (root / FIXTURE_HISTORY_CARRIER_REL).unlink()
        _write(root, FIXTURE_HISTORY_ASSET_REL, FIXTURE_GPL_BODY)
        _commit_all(root, "move the same bytes to a path with an asset extension")
        (root / FIXTURE_HISTORY_ASSET_REL).unlink()
        _commit_all(root, "delete that too")

    def check_both_paths(findings, stats, tree_findings):
        if findings is None:
            return False, f"the history audit did not run: {stats}"
        if tree_findings:
            return False, "the tree audit of the final checkout is NOT clean"
        for rule, rel in (
            ("foreign-license-text", FIXTURE_HISTORY_CARRIER_REL),
            ("foreign-license-text", FIXTURE_HISTORY_ASSET_REL),
            ("upstream-asset-extension", FIXTURE_HISTORY_ASSET_REL),
        ):
            ok, detail = fired(findings, rule, rel)
            if not ok:
                return False, detail
        return True, (
            "both paths that published the same bytes are named, and the second "
            "path's own extension rule fired on it"
        )

    def escaping_link_then_deleted(root):
        _history_repo(root)
        _symlink(root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET)
        _commit_all(root, "add a link into an external tree")
        (root / FIXTURE_ESCAPING_LINK_REL).unlink()
        _commit_all(root, "delete the link")

    def in_repo_link_then_deleted(root):
        _history_repo(root)
        _symlink(root, FIXTURE_HISTORY_ALIAS_REL, "plain.md")
        _commit_all(root, "add an in-repo alias link")
        (root / FIXTURE_HISTORY_ALIAS_REL).unlink()
        _commit_all(root, "delete the alias")

    def empty_range(root):
        _history_repo(root)

    def check_refuses_empty_range(findings, stats, tree_findings):
        if findings is not None:
            return False, (
                "a range that resolves to no commits was reported as a result "
                "instead of an error"
            )
        if "no commits" not in str(stats):
            return False, f"the refusal does not say the range is empty: {stats}"
        return True, f"refused to report a verdict: {stats}"

    return [
        (
            "history/a-carrier-published-and-then-deleted-is-judged",
            "the shape no tree audit can see: a GPL body added by one commit and "
            "deleted by the next, in a repository that merges with merge commits",
            HISTORY_CONTROL_RANGE,
            add_then_delete,
            must_fire(
                "foreign-license-text",
                FIXTURE_HISTORY_CARRIER_REL,
                standing=TIP_ABSENT,
            ),
        ),
        (
            "history/an-upstream-asset-published-and-then-deleted-is-judged",
            "the same for a STRUCTURAL signal (an extension rule), which a "
            "view-gated primary check would have made unreachable in a commit tree",
            HISTORY_CONTROL_RANGE,
            lambda root: add_then_delete(
                root, FIXTURE_HISTORY_ASSET_REL, FIXTURE_MARKER_FREE_ASSET_PAYLOAD
            ),
            must_fire(
                "upstream-asset-extension",
                FIXTURE_HISTORY_ASSET_REL,
                standing=TIP_ABSENT,
            ),
        ),
        (
            "history/an-escaping-symlink-published-and-then-deleted-is-judged",
            "a by-reference entry whose target is read from the COMMIT's blob, "
            "not from a working-tree link that no longer exists",
            HISTORY_CONTROL_RANGE,
            escaping_link_then_deleted,
            must_fire(
                "external-symlink-target",
                FIXTURE_ESCAPING_LINK_REL,
                in_detail="escapes the audited tree",
            ),
        ),
        (
            "history/an-in-repo-symlink-in-history-is-not-a-signal",
            "the must-NOT-fire direction of the same read: a link to in-scope "
            "content is this repository's own shape, and resolving it against "
            "the checkout rather than the commit would invent a finding on a "
            "rule that cannot be exempted",
            HISTORY_CONTROL_RANGE,
            in_repo_link_then_deleted,
            must_be_clean,
        ),
        (
            "history/a-carrier-declared-in-the-same-commit-passes",
            "the positive control: a commit that publishes a carrier AND its row "
            "answers for itself, so the mode is not a blanket alarm on history",
            HISTORY_CONTROL_RANGE,
            declared_in_the_same_commit,
            must_be_clean,
        ),
        (
            "history/a-carrier-declared-one-commit-late-is-judged",
            "the answer must come from the commit's OWN bookkeeping: a row added "
            "by the next commit does not retroactively declare published bytes",
            HISTORY_CONTROL_RANGE,
            declared_one_commit_late,
            must_fire(
                "foreign-license-text",
                FIXTURE_HISTORY_CARRIER_REL,
                standing=TIP_ANSWERED,
            ),
        ),
        (
            "history/deleting-the-answer-set-does-not-silence-a-commit",
            "the escape hatch the 'not judged' disclosure could have become: "
            "removing the manifest in the same commit as the carrier",
            HISTORY_CONTROL_RANGE,
            manifest_deleted_with_the_carrier,
            check_dropped_manifest,
        ),
        (
            "history/a-commit-older-than-the-manifest-is-disclosed-not-judged",
            "the pre-bookkeeping era is NOT_RUN and says so, rather than one "
            "finding per carrier per commit against an answer set that did not "
            "exist yet",
            HISTORY_CONTROL_RANGE,
            no_manifest_before_the_first_one,
            check_pre_manifest_disclosure,
        ),
        (
            "history/the-same-bytes-at-two-paths-are-judged-at-both",
            "the signal cache is keyed by (path, blob): a blob reintroduced "
            "under a new name must not be answered from the first path's scan",
            HISTORY_CONTROL_RANGE,
            same_bytes_at_two_paths,
            check_both_paths,
        ),
        (
            "history/an-empty-range-is-an-error-not-a-pass",
            "a range that selects no commit audits nothing, and nothing audited "
            "must never print a verdict",
            "HEAD..HEAD",
            empty_range,
            check_refuses_empty_range,
        ),
    ]


def _run_history_controls(tmp_root: Path, prefix, cases):
    """Run (label, description, revrange, mutate, check) history cases."""
    results = []
    for index, (label, description, revrange, mutate, check) in enumerate(cases):
        case_root = Path(tmp_root) / f"{prefix}-{index}"
        case_root.mkdir()
        build_skeleton(case_root)
        try:
            mutate(case_root)
        except Exception as exc:  # a control that cannot be SET UP is a FAIL
            results.append(
                (label, False, f"{description} -> control setup failed: {exc}")
            )
            continue
        try:
            tree_findings, _ = audit(case_root)
        except AuditError as exc:
            results.append(
                (label, False, f"{description} -> the tree audit did not run: {exc}")
            )
            continue
        try:
            findings, stats = audit_history(case_root, revrange)
        except AuditError as exc:
            findings, stats = None, exc
        passed, detail = check(findings, stats, tree_findings)
        results.append((label, passed, f"{description} -> {detail}"))
    return results


def _run_coverage_controls(tmp_root: Path, prefix, cases, include_untracked=False):
    """Run (label, description, mutate, check) cases that assert on COVERAGE."""
    results = []
    for index, (label, description, mutate, check) in enumerate(cases):
        case_root = Path(tmp_root) / f"{prefix}-{index}"
        case_root.mkdir()
        build_skeleton(case_root)
        try:
            mutate(case_root)
        except Exception as exc:  # a control that cannot be SET UP is a FAIL
            results.append(
                (label, False, f"{description} -> control setup failed: {exc}")
            )
            continue
        try:
            findings, stats = audit(case_root, include_untracked=include_untracked)
        except AuditError as exc:
            results.append((label, False, f"{description} -> audit did not run: {exc}"))
            continue
        passed, detail = check(findings, stats)
        results.append((label, passed, f"{description} -> {detail}"))
    return results


def _discovery_controls():
    """[(label, expected rule or None, expected path, description, mutator[, in_detail])].

    Increment 7 — the DISCOVERY layer, below the decode layer increment 6
    closed. Both negative cases below audited **clean** while
    `--negative-control` reported all 29 earlier rules firing: a by-reference
    entry has no bytes of its own, so `open()` failed and the file was counted
    as an undecodable payload among the renders.

    The positive controls matter as much: a repository that symlinks
    `CLAUDE.md -> AGENTS.md` (this one does) must not acquire a finding on a
    non-exemptible rule, or the rule would be switched off rather than answered.

    Increment 13 went back INSIDE increment 7's own fix rather than below it.
    Four ways a declared by-reference entry was described by nothing, each
    probed clean on the tree that reported every other rule firing: a row with
    no `pinned_commit` at all (the field is optional, and its absence
    short-circuited the gitlink comparison); a gitlink UNDER a declared scope
    exclusion (swallowed before any rule saw it, while a symlink INTO the same
    prefix was already an escape); and a row of any class whatsoever covering
    either by-reference rule. The fourth was not a mask but an
    environment-dependent verdict — the same committed tree passed in CI and
    failed where the external target happened to be checked out — which is now
    decided from the committed link target alone.
    """
    return [
        (
            "discovery/committed-submodule-gitlink",
            "submodule-reference",
            FIXTURE_SUBMODULE_REL,
            "a committed mode-160000 gitlink pinning the upstream GPL engine",
            _git_submodule_entry,
            "surge-synthesizer/surge",
        ),
        (
            "discovery/submodule-gitlink-answered-by-a-row",
            None,
            None,
            "the same gitlink, declared by a provenance row at its exact commit",
            lambda root: (
                _git_submodule_entry(root),
                _patch_manifest(root, lambda d: d["entries"].append(_submodule_row())),
            ),
        ),
        (
            "discovery/submodule-row-naming-the-wrong-commit",
            "manifest-uncorroborated",
            FIXTURE_SUBMODULE_REL,
            "a submodule row whose pinned_commit is not the committed gitlink",
            lambda root: (
                _git_submodule_entry(root),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(
                        _submodule_row(commit="0" * 40)
                    ),
                ),
            ),
        ),
        (
            # R1 (increment 13): the wrong-commit control above is defeated by
            # DELETING the field rather than changing it — `pinned_commit` is
            # optional, and an empty one short-circuited the comparison, so the
            # gitlink was declared by a row that recorded no pin anywhere.
            "discovery/submodule-row-with-no-pinned-commit",
            "manifest-field-missing",
            MANIFEST_REL,
            "a submodule row that omits pinned_commit entirely",
            lambda root: (
                _git_submodule_entry(root),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(_submodule_row(commit=None)),
                ),
            ),
            "pinned_commit",
        ),
        (
            # R4 (increment 13): `external-reference` is the class that
            # describes a by-reference entry, and was advertised as required —
            # but any row at the path used to cover the rule, whatever it said.
            "discovery/gitlink-answered-by-a-row-of-the-wrong-class",
            "submodule-reference",
            FIXTURE_SUBMODULE_REL,
            "a gitlink 'answered' by an attribution-statement row",
            lambda root: (
                _git_submodule_entry(root),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(
                        _submodule_row(row_class="attribution-statement")
                    ),
                ),
            ),
        ),
        (
            # The same hole on the other by-reference rule.
            "discovery/escaping-symlink-answered-by-a-row-of-the-wrong-class",
            "external-symlink-target",
            FIXTURE_ESCAPING_LINK_REL,
            "an escaping symlink 'answered' by a quoted-constants row",
            lambda root: (
                _symlink(
                    root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET
                ),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(
                        _escaping_link_row(row_class="quoted-constants")
                    ),
                ),
            ),
        ),
        (
            # R3 (increment 13): a declared exclusion withholds CONTENT from the
            # content rules; a gitlink has none of its own, and the entry used
            # to be dropped before any rule saw it.
            "discovery/gitlink-under-a-declared-scope-exclusion",
            "submodule-reference",
            FIXTURE_EXCLUDED_SUBMODULE_REL,
            "a committed gitlink inside a declared, unaudited hole",
            lambda root: (
                _declared_hole(root),
                _git_submodule_entry(root, rel=FIXTURE_EXCLUDED_SUBMODULE_REL),
            ),
            "scope exclusion",
        ),
        (
            # …and it must be ANSWERABLE where it fires, or the disclosure is a
            # trap: a row naming an excluded path used to be read as stale.
            "discovery/gitlink-under-an-exclusion-answered-by-a-row-passes",
            None,
            None,
            "the same excluded gitlink, declared by a row at its exact commit",
            lambda root: (
                _declared_hole(root),
                _git_submodule_entry(root, rel=FIXTURE_EXCLUDED_SUBMODULE_REL),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(
                        _submodule_row(rel=FIXTURE_EXCLUDED_SUBMODULE_REL)
                    ),
                ),
            ),
        ),
        (
            "discovery/nested-repository-in-a-non-git-tree",
            "submodule-reference",
            FIXTURE_NESTED_REPO_REL,
            "a nested repository checkout in a tree that is not itself a checkout",
            _nested_repo,
        ),
        (
            "discovery/symlink-to-an-absent-external-target",
            "external-symlink-target",
            FIXTURE_ESCAPING_LINK_REL,
            "a symlink into an external oracle tree that is not checked out here",
            lambda root: _symlink(
                root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET
            ),
            "escapes the audited tree",
        ),
        (
            "discovery/symlink-with-an-absolute-target",
            "external-symlink-target",
            FIXTURE_ESCAPING_LINK_REL,
            "a symlink whose target is an absolute path on the author's machine",
            lambda root: _symlink(
                root, FIXTURE_ESCAPING_LINK_REL, "/opt/surge/include/Reverb1.h"
            ),
            "absolute target",
        ),
        (
            # The structural rule is not the only one that must fire here: a
            # link that DOES resolve is read by every content rule, and a fix
            # that short-circuited on the symlink kind would silently drop them.
            "discovery/resolvable-escaping-symlink-is-still-content-scanned",
            "foreign-license-text",
            FIXTURE_ESCAPING_LINK_REL,
            "an escaping symlink that resolves, whose target carries a GPL body",
            lambda root: (
                _write(root.parent / f"{root.name}-oracle", "Reverb1.h", FIXTURE_GPL_BODY),
                _symlink(
                    root,
                    FIXTURE_ESCAPING_LINK_REL,
                    f"../../{root.name}-oracle/Reverb1.h",
                ),
            ),
        ),
        (
            "discovery/symlink-into-a-declared-scope-exclusion",
            "external-symlink-target",
            FIXTURE_ESCAPING_LINK_REL,
            "a symlink from product space into a declared, unaudited hole",
            lambda root: (
                _write(root, ".loom/vendored_table.py", "TABLE = [7, 8, 9]\n"),
                _patch_manifest(
                    root,
                    lambda d: d["scope_exclusions"].append(
                        {"prefix": ".loom/", "reason": "synthetic declared hole"}
                    ),
                ),
                _symlink(root, FIXTURE_ESCAPING_LINK_REL, "../.loom/vendored_table.py"),
            ),
            "scope exclusion",
        ),
        (
            "discovery/in-repo-symlink-to-a-regular-file-passes",
            None,
            None,
            "this repository's own shape: a symlink to an audited in-tree file",
            lambda root: _symlink(root, "CLAUDE.md", "docs/plain.md"),
        ),
        (
            "discovery/in-repo-symlink-to-a-directory-passes",
            None,
            None,
            "a symlink to an in-tree directory, whose files are audited at their own paths",
            lambda root: _symlink(root, "docs/model", "../model"),
        ),
        (
            "discovery/escaping-symlink-answered-by-a-row-passes",
            None,
            None,
            "an escaping symlink declared by a provenance row citing its record",
            lambda root: (
                _symlink(
                    root, FIXTURE_ESCAPING_LINK_REL, FIXTURE_ESCAPING_LINK_TARGET
                ),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(_escaping_link_row()),
                ),
            ),
        ),
        (
            # R2 (increment 13): the SAME tree and the SAME row as the control
            # above, with the external target checked out here. Both must audit
            # clean, or one committed tree has two governance verdicts depending
            # on whose machine ran the audit — which is what this one pins. The
            # alternative (requiring the resolved UPSTREAM bytes to cite one of
            # our decision records) is not a tooling change; see `_corroborate`.
            "discovery/declared-escaping-symlink-passes-whether-its-target-resolves-or-not",
            None,
            None,
            "the same declared escaping link, with its external target present",
            lambda root: (
                _write(
                    root.parent / f"{root.name}-oracle",
                    "oracle_tables.py",
                    "TABLE = [7, 8, 9]\n",
                ),
                _symlink(
                    root,
                    FIXTURE_ESCAPING_LINK_REL,
                    f"../../{root.name}-oracle/oracle_tables.py",
                ),
                _patch_manifest(
                    root,
                    lambda d: d["entries"].append(_escaping_link_row()),
                ),
            ),
        ),
    ]


def _run_case_controls(tmp_root: Path, prefix, cases):
    """Run (label, expected, path, description, mutate[, in_detail]) cases.

    Returns [(label, ok, detail)]. The optional sixth element `in_detail` is a
    substring the firing finding's own `detail` must contain. It exists because
    `Finding` carries no line number: the `detail` snippet is the only locator a
    human has for answering a finding, and `foreign-license-text` cannot be
    exempted -- so a control that checks only `rule`/`path` would pass on a
    finding whose evidence points at the wrong bytes.
    """
    results = []
    for index, case in enumerate(cases):
        label, expected, where, description, mutate = case[:5]
        in_detail = case[5] if len(case) > 5 else None
        case_root = Path(tmp_root) / f"{prefix}-{index}"
        case_root.mkdir()
        build_skeleton(case_root)
        try:
            mutate(case_root)
        except Exception as exc:  # a control that cannot be SET UP is a FAIL
            results.append(
                (label, False, f"{description} -> control setup failed: {exc}")
            )
            continue
        findings, _ = audit(case_root)
        found = ", ".join(sorted({f"{f.rule}@{f.path}" for f in findings})) or "nothing"
        if expected is None:
            passed = not findings
            detail = f"{description} -> " + ("audits clean" if passed else f"found {found}")
        else:
            matched = [
                f
                for f in findings
                if f.rule == expected and (where is None or f.path == where)
            ]
            passed = bool(matched)
            detail = f"{description} -> " + (
                f"{expected} fired on {where}"
                if passed
                else f"{expected} did NOT fire on {where} (found {found})"
            )
            if passed and in_detail is not None:
                quoting = [f for f in matched if in_detail in f.detail]
                passed = bool(quoting)
                if not passed:
                    detail = (
                        f"{description} -> {expected} fired on {where} but no "
                        f"finding quoted {in_detail!r} (details: "
                        + "; ".join(repr(f.detail) for f in matched)
                        + ")"
                    )
                else:
                    detail += f", quoting {in_detail!r}"
        results.append((label, passed, detail))
    return results


def run_negative_control(verbose=True):
    """Every rule must fire on a deliberate violation. Returns exit code."""
    controls = _controls()
    missing = sorted(set(RULES) - set(controls))
    results = []
    ok = True

    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean"
        clean.mkdir()
        build_skeleton(clean)
        findings, _ = audit(clean)
        clean_ok = not findings
        ok = ok and clean_ok
        results.append(
            (
                "(clean skeleton)",
                "PASS" if clean_ok else "FAIL",
                "audits clean"
                if clean_ok
                else "false alarm on a clean tree: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings),
            )
        )

        for rule in sorted(controls):
            description, mutate = controls[rule]
            case = Path(tmp) / f"case-{rule}"
            case.mkdir()
            build_skeleton(case)
            try:
                mutate(case)
            except Exception as exc:  # a control that cannot be SET UP is a FAIL
                ok = False
                results.append(
                    (rule, "FAIL", f"{description} -> control setup failed: {exc}")
                )
                continue
            findings, _ = audit(case)
            fired = [f for f in findings if f.rule == rule]
            if fired:
                results.append((rule, "PASS", f"{description} -> {fired[0].path}"))
            else:
                ok = False
                results.append(
                    (
                        rule,
                        "FAIL",
                        f"{description} -> rule did NOT fire (found: "
                        + (", ".join(sorted({f.rule for f in findings})) or "nothing")
                        + ")",
                    )
                )

        # A scoped-exemption tripwire must fire on the exempted file itself,
        # not on the manifest; a manifest rule fires on the manifest.
        scoped = [
            (
                label,
                expected,
                None
                if expected is None
                else ("docs/own_copy.md" if expected in TRIPWIRE_RULES else MANIFEST_REL),
                description,
                mutate,
            )
            for label, expected, description, mutate in _scoped_exemption_controls()
        ]
        for prefix, cases in (
            ("scoped", scoped),
            ("masking", _masking_controls()),
            ("discovery", _discovery_controls()),
            ("payload", _payload_controls()),
            ("wrapper", _wrapper_name_controls()),
        ):
            for label, passed, detail in _run_case_controls(Path(tmp), prefix, cases):
                ok = ok and passed
                results.append((label, "PASS" if passed else "FAIL", detail))

        # Increment 11: coverage-asserting controls. These check what the run
        # SAID about an entry it did not audit, which no findings-based control
        # can do — the behaviour under test is deliberately "no finding".
        # Increment 14 joins them: the staged-content controls assert on BOTH
        # findings and coverage (a staged carrier must fire, an innocuous
        # divergence must only be disclosed), so they share this runner.
        for prefix, cases, included in (
            ("coverage", _coverage_controls(), False),
            ("coverage-included", _coverage_include_untracked_controls(), True),
            ("staged", _staged_controls(), False),
            # Increment 15 shares it for the same reason: the committed-answer-set
            # controls assert on findings AND on the coverage line that discloses
            # the second answer set, and the must-not-fire half is defined
            # entirely by coverage (no second pass at all).
            ("committed", _committed_bookkeeping_controls(), False),
            # Increment 16 shares it for the third time, and needs it: its
            # must-fire half asserts on a finding AND on the coverage line that
            # says a bookkeeping check read the staged view, while its
            # must-not-fire half is defined entirely by coverage (a view read
            # and not flagged; a view with no text, not read at all).
            ("evidence", _committable_evidence_controls(), False),
        ):
            for label, passed, detail in _run_coverage_controls(
                Path(tmp), prefix, cases, include_untracked=included
            ):
                ok = ok and passed
                results.append((label, "PASS" if passed else "FAIL", detail))

        # Increment 17: the HISTORY layer. Its own runner, because every case
        # needs a real commit graph, and because each one asserts on BOTH audits
        # — the tree audit of the final checkout must be clean (otherwise the
        # case proves nothing about history) and the history audit must fire.
        for label, passed, detail in _run_history_controls(
            Path(tmp), "history", _history_controls()
        ):
            ok = ok and passed
            results.append((label, "PASS" if passed else "FAIL", detail))

    if verbose:
        print("negative control: one deliberate violation per rule\n")
        for name, verdict, detail in results:
            print(f"  {verdict:4}  {name}")
            print(f"        {detail}")
        if missing:
            print(
                "\nFAIL: rules with no negative control (add one before merging): "
                + ", ".join(missing)
            )
        print()
        if ok and not missing:
            print(
                f"PASS: all {len(controls)} rules fired on their deliberate "
                "violation, the clean control tree produced no findings, "
                f"all {len(_scoped_exemption_controls())} occurrence-scoped "
                f"exemption controls behaved, all {len(_masking_controls())} "
                "own-attribution masking controls behaved, all "
                f"{len(_discovery_controls())} discovery-layer controls behaved, "
                f"all {len(_payload_controls())} payload-layer controls behaved, "
                f"all {len(_wrapper_name_controls())} wrapper-member-name "
                "controls behaved, and all "
                f"{len(_coverage_controls()) + len(_coverage_include_untracked_controls())}"
                " index-boundary coverage controls and all "
                f"{len(_staged_controls())} staged-content controls and all "
                f"{len(_committed_bookkeeping_controls())} committed-answer-set "
                f"controls and all {len(_committable_evidence_controls())} "
                "committable-evidence controls and all "
                f"{len(_history_controls())} published-history controls behaved."
            )
        else:
            print("FAIL: the audit's own failure detection is not intact.")
        print(CAVEAT)
    return 0 if (ok and not missing) else 2
