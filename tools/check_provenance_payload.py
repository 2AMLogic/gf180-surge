#!/usr/bin/env python3
"""SXT-019 provenance audit — the payload layer (encodings and wrappers).

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or message was changed, reordered or reflowed). This module turns BYTES into
the text the signal layer can read: it sniffs the encoding, decodes wide
(UTF-16/32) runs, and unwraps gzip/bzip2/xz streams, zip and tar archives
under one global inflation budget.
"""

from __future__ import annotations

import bz2
import codecs
import io
import lzma
import re
import tarfile
import zipfile
import zlib


# --- encoding sniffing --------------------------------------------------------
#
# Only files this layer turns into text are reachable by the content rules
# (`foreign-license-text`, `self-declared-quotation`). Everything below exists
# to keep an ordinary text file — whatever its encoding, however it has been
# scuffed — from being discarded as "binary" before any rule can read it, while
# still not pretending a render or a wavetable payload is prose.

# Longest BOM first: UTF-32-LE's BOM starts with UTF-16-LE's.
BOM_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
    (codecs.BOM_UTF8, "utf-8-sig"),
)

# Tried in order when a head carries NULs but no BOM (the shape a Windows
# editor's "Unicode" save leaves behind).
BOMLESS_WIDE_ENCODINGS = ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")

# A license notice is ASCII English prose, so "mostly ASCII" is the right
# admission test: a .wav or .npy payload reinterpreted as UTF-16 decodes to
# mostly non-ASCII code points and is correctly refused. The cost is a
# DECLARED boundary, not a silent one — see DECLARED LIMITS.
ASCII_TEXT_RATIO = 0.90

# Above this share of NULs the payload is structural (PCM silence, a tensor),
# not text someone scuffed to hide a notice.
MAX_STRAY_NUL_RATIO = 0.01


def _ascii_text_ratio(text):
    """Share of `text` that is printable ASCII or ordinary whitespace."""
    if not text:
        return 0.0
    good = sum(1 for ch in text if ch in "\t\n\r\f\v" or "\x20" <= ch <= "\x7e")
    return good / len(text)


def sniff_encoding(head: bytes):
    """An encoding name to decode this payload with, or None if it is binary.

    `head` is the first `BINARY_SNIFF_BYTES` only; a trailing split code unit
    is harmless because the result is used solely to choose the codec.
    """
    for bom, encoding in BOM_ENCODINGS:
        if head.startswith(bom):
            return encoding
    if not head:
        return "utf-8"
    if b"\0" not in head:
        return "utf-8"
    for encoding in BOMLESS_WIDE_ENCODINGS:
        width = 4 if encoding.startswith("utf-32") else 2
        # Decode whole code units only, so a split tail cannot skew the ratio.
        usable = head[: len(head) - (len(head) % width)]
        if not usable:
            continue
        if _ascii_text_ratio(usable.decode(encoding, "replace")) >= ASCII_TEXT_RATIO:
            return encoding
    # Narrow text someone has scuffed with a few NULs: sparse enough to be an
    # evasion rather than a payload, and ASCII once they are removed.
    if head.count(0) / len(head) <= MAX_STRAY_NUL_RATIO:
        stripped = head.replace(b"\0", b"").decode("utf-8", "replace")
        if _ascii_text_ratio(stripped) >= ASCII_TEXT_RATIO:
            return "utf-8"
    return None


# --- payloads the sniff refuses: wrappers and embedded strings ----------------
#
# Increment 8. The layer above decides HOW to decode a file; this one decides
# what to do with the payload it refused. Until now the answer was "nothing":
# `Tree.text()` returned None, `tripwire_hits()` returned before every content
# rule, and the only trace was a count. Two shapes went straight past the
# non-exemptible `foreign-license-text` rule on the real tree (both demonstrated
# in `reports/sxt-019/EVIDENCE.md` §14):
#
#   * a WRAPPER. A gzip/bzip2/xz stream, a zip or a tar is not opaque content —
#     it is text one `read()` away. `.gz` is deliberately absent from
#     UPSTREAM_ASSET_EXTS (this repository gzips its own evidence traces) and
#     `_extension_suffix` strips it, so `pasted_helper.py.gz` matched no
#     extension tripwire either; a zip or tar renamed `.dat` evades the
#     extension rule outright.
#   * an EMBEDDED notice. A notice pasted into a render, a tensor or a raw
#     float dump is ordinary ASCII sitting in a payload — a WAV `LIST/INFO`
#     `ICOP` chunk is where an upstream sample pack states its copyright, and
#     nothing in this repository's own renders carries one.
#
# Both are answered WITHOUT loosening the sniff, which is the failure the
# previous increment's positive control guards (decoding a render as prose would
# turn 264 renders into garbage findings on a rule nobody can exempt):
#
#   1. unwrap wrappers by MAGIC, not by extension, recursively (a `.tar.gz`
#      is two layers), bounded by an inflation budget, and run the ordinary
#      decode + content rules on each member;
#   2. for a payload that is still not text, harvest the printable-ASCII RUNS
#      that carry a word, and run the content rules on those. A license notice
#      is ASCII English prose; 16-bit PCM and float32 data produce runs with no
#      word in them.
#
# Measured on this repository before committing: 339 MiB of payloads over 335
# files (264 `.wav`, 22 `.bin`, 22 `.f32`, 18 `.gz`, 8 `.npy`, 1 `.npz`) yield
# ZERO hits on all four content signals. That matters because
# `foreign-license-text` cannot be exempted: a false positive on our own render
# would be unanswerable, so the rule would be switched off rather than answered.

GZIP_MAGIC = b"\x1f\x8b"
BZIP2_MAGIC = b"BZh"
XZ_MAGIC = b"\xfd7zXZ\x00"
ZIP_MAGIC = b"PK\x03\x04"
STREAM_WRAPPERS = ((GZIP_MAGIC, "gzip"), (BZIP2_MAGIC, "bzip2"), (XZ_MAGIC, "xz"))

# Bounds on what ONE tree entry may inflate to, so a decompression bomb cannot
# hang or OOM the audit. `MAX_UNWRAPPED_BYTES` is a budget over the WHOLE unwrap
# of an entry, summed across every stream, archive member and recursion level
# (`_InflationBudget`), not a per-level ceiling; `MAX_UNWRAP_DEPTH` bounds the
# recursion. Both are generous against this tree (its largest inflation is
# ~15 MiB at depth 1) and neither is silent: a payload that hits either is
# reported as truncated on every run and in `--json`, because a scan that could
# not finish must never look like one that passed.
MAX_UNWRAPPED_BYTES = 256 * 1024 * 1024
MAX_UNWRAP_DEPTH = 4

# A run of printable ASCII long enough to hold a word, and the word test
# itself. Three consecutive letters is the cheapest filter that keeps every
# license/copyright vocabulary word ("GNU", "Copyright", "GPL-3.0-or-later",
# a holder name) while discarding PCM and float noise: dropping a WORDLESS run
# can only bring two surviving runs CLOSER together, so it cannot break a
# phrase the rules would otherwise have matched.
#
# It is NOT merely a precision/cost knob (#283 corrected the increment-8
# record, which said so). Harvested text reaches every rule, including the
# BOOKKEEPING ones, and those are cheap enough for noise to satisfy: with this
# filter removed, `reports/sxt-024/traces/reset-midpatch-wet.npy` fails the
# real-tree audit with `dangling-record-citation`, because its noise happens to
# carry a `dR` + `90459` run. (Written as fragments here for the same reason as
# every fixture below: spelled out, this comment would itself be a citation of
# a record that does not exist — the rule reads THIS file too.) Pinned by
# `payload/citation-shaped-noise-run-stays-clean`.
PRINTABLE_RUN_RE = re.compile(rb"[\x20-\x7e\t\r\n]{6,}")
RUN_WORD_RE = re.compile(rb"[A-Za-z]{3,}")

# A UTF-8 © would end a printable-ASCII run mid-notice and take the copyright
# keyword with it. Normalised to its ASCII spelling before harvesting, which the
# `(c)` prefilter already recognises. Only this one spelling in the NARROW
# harvest: the Latin-1 single byte 0xA9 occurs constantly inside PCM and float
# data, and rewriting it there would manufacture `(c)` tokens in noise on a rule
# that cannot be exempted. (Inside a WIDE run the same byte is admitted, because
# it has to arrive NUL-padded inside an otherwise printable NUL-padded run —
# see `_wide_runs`.)
UTF8_COPYRIGHT_SIGN = b"\xc2\xa9"

# --- increment 10: the same payload, read in a WIDE encoding -------------------
#
# Increment 8 harvested the printable-ASCII runs a refused payload carries and
# then DECLARED the rest: "the harvest reads ASCII, so a notice written in a WIDE
# encoding *inside* a binary payload stays out of reach". That declaration was
# wrong in exactly the way increments 6, 8 and 9 were wrong about their own: a
# UTF-16 save is what an ordinary Windows editor produces, so "wide" is not an
# exotic carriage — and a notice re-encoded that way and spliced into a render,
# a float dump or an opaque archive member went past the non-exemptible
# `foreign-license-text` rule with the audit reporting PASS, exit 0 and
# UNCHANGED tripwire counts (demonstrated on the real tree in
# `reports/sxt-019/EVIDENCE.md` §16).
#
# The sniff already decodes a file that is wide-encoded THROUGHOUT; what it
# cannot do is admit a payload that is mostly binary with a wide-encoded notice
# in it, and loosening it is the other failure direction (increment 6's positive
# control guards that: decoding a render as prose would turn 264 renders into
# garbage findings on a rule nobody can exempt).
#
# So the runs are found the same way the ASCII ones are — by their SHAPE, not by
# a name or a declaration. An ASCII code point in UTF-16/UTF-32 is one data byte
# plus NUL padding, so a wide run is a run of NULs in one of the two half-stride
# streams whose matching data bytes are all printable:
#
#   utf-16-le  'H\0e\0'   -> NULs at odd offsets,  data at even
#   utf-16-be  '\0H\0e'   -> NULs at even offsets, data at odd
#   utf-32-le  'H\0\0\0'  -> NULs at odd offsets,  and the data stream is itself
#   utf-32-be  '\0\0\0H'     NUL-padded, so one more halving step resolves it
#
# Looking for the PADDING rather than for alternating pairs is what makes this
# affordable: `\x00{6,}` has a literal prefix, so the regex engine scans for
# candidates at memchr speed instead of restarting a character class at every
# byte. Measured over this repository's 339 MiB of payloads: 4.0 s for this
# shape against 18.8 s for the alternating-pair pattern, i.e. the same cost as
# the ASCII harvest that was already being paid (§16).
MIN_WIDE_RUN_UNITS = 6

WIDE_PAD_RUN_RE = re.compile(rb"\x00{%d,}" % MIN_WIDE_RUN_UNITS)

# The admission test for a wide run's data bytes, applied with `bytes.translate`
# (C speed) rather than a per-character ratio: EVERY data byte must be printable
# ASCII or ordinary whitespace. Not a ratio, because the padding constraint is
# already doing the discriminating work and a single stray byte simply splits one
# run into two. 0xA9 is admitted here and normalised below: a notice that writes
# its holder with the sign spelling (U+00A9) rather than the word is the first
# evasion anyone would reach for, and in a wide run that byte has to arrive
# NUL-padded inside an otherwise printable NUL-padded run — which is nothing like
# the bare 0xA9 that occurs constantly in PCM, and is why the NARROW harvest
# still refuses it.
WIDE_DATA_BYTES = bytes(range(0x20, 0x7F)) + b"\t\r\n"
LATIN1_COPYRIGHT_SIGN = b"\xa9"
WIDE_DATA_ALLOWED = WIDE_DATA_BYTES + LATIN1_COPYRIGHT_SIGN
# Derived from the byte above rather than written as a character, so this file
# carries no notice of its own — the same reason every fixture here is assembled
# from fragments (see the fixture note below).
COPYRIGHT_SIGN_CHAR = LATIN1_COPYRIGHT_SIGN.decode("latin-1")


def _decode_wide_run(data: bytes):
    """A candidate run's text, or None when its bytes are not printable.

    `data` is the run's DATA bytes with the padding already removed, so this is
    the admission test plus the U+00A9 normalisation, nothing more.
    """
    if len(data) < MIN_WIDE_RUN_UNITS:
        return None
    if data.translate(None, WIDE_DATA_ALLOWED):
        return None
    if not RUN_WORD_RE.search(data):
        return None
    # latin-1 rather than ascii: every admitted byte but 0xA9 is ASCII, and that
    # one is normalised to the spelling the `(c)` prefilter already recognises.
    return data.decode("latin-1").replace(COPYRIGHT_SIGN_CHAR, "(c)")


def _wide_runs(raw: bytes):
    """Text of each wide-encoded (UTF-16/UTF-32, either byte order) ASCII run.

    A BOM is neither required nor consumed: the run is found by its padding, so
    `\\xff\\xfe`-led text, BOM-less text and text spliced into the middle of a
    payload are all the same case here.
    """
    runs = []
    for pad_phase in (0, 1):
        pad = raw[pad_phase::2]
        data_stream = raw[1 - pad_phase :: 2]
        # Whether a code unit's data byte PRECEDES its padding or FOLLOWS it
        # depends on the byte order AND on the offset the text happens to start
        # at, which is odd as often as it is even for a notice spliced into a
        # payload. Both windows are therefore read; a misaligned one picks up a
        # padding NUL (not in `WIDE_DATA_ALLOWED`) and fails the admission test,
        # so reading both cannot invent a run — it can only read the same text
        # twice, which the coverage count says it does.
        shifts = (0, -1) if pad_phase == 0 else (0, 1)
        for match in WIDE_PAD_RUN_RE.finditer(pad):
            start, end = match.span()
            for shift in shifts:
                low = start + shift
                if low < 0:
                    continue
                # pad[k] is one byte of a code unit; data_stream[k + shift] is
                # its data byte, so these are the data bytes of the units this
                # NUL run pads.
                data = data_stream[low : end + shift]
                text = _decode_wide_run(data)
                if text is not None:
                    runs.append(text)
                    continue
                # A 32-bit code unit pads its data stream in turn, so the same
                # step once more resolves UTF-32 in either byte order. The OTHER
                # half must be all NUL for that reading to be real padding rather
                # than an arbitrary decimation of binary data — without that
                # check, quiet 16-bit PCM (whose every high byte is NUL)
                # decimates into printable noise and manufactures runs on a rule
                # that cannot be exempted.
                for inner_phase in (0, 1):
                    if data[1 - inner_phase :: 2].translate(None, b"\x00"):
                        continue
                    text = _decode_wide_run(data[inner_phase::2])
                    if text is not None:
                        runs.append(text)
                        break
    return runs


def harvest_strings(raw: bytes):
    """Text harvested from a payload the sniff refused (see `harvest_payload`)."""
    return harvest_payload(raw)[0]


def harvest_payload(raw: bytes):
    """(text, number of wide-encoded runs) for a payload the sniff refused.

    The text is the payload's printable-ASCII runs that carry a word, plus the
    same for its wide-encoded (UTF-16/UTF-32) runs. The joint is a newline, which
    every content regex treats as an ordinary word gap (`_GAP`), so a notice
    split across runs by a binary field is still matched.

    The wide-run count is returned rather than inferred: it is reported as
    coverage, so "no wide run offended" and "no wide run was examined" cannot be
    confused with each other.
    """
    if UTF8_COPYRIGHT_SIGN in raw:
        raw = raw.replace(UTF8_COPYRIGHT_SIGN, b"(c)")
    kept = [
        match.group().decode("ascii", "replace")
        for match in PRINTABLE_RUN_RE.finditer(raw)
        if RUN_WORD_RE.search(match.group())
    ]
    wide = _wide_runs(raw)
    return "\n".join(kept + wide), len(wide)


def _looks_like_wrapper(raw: bytes):
    """Cheap magic test: could `raw` be a compressed/archive wrapper?"""
    if any(raw.startswith(magic) for magic, _ in STREAM_WRAPPERS):
        return True
    if raw.startswith(ZIP_MAGIC):
        return True
    # tar's magic sits at offset 257, so there is no prefix to test.
    try:
        return tarfile.is_tarfile(io.BytesIO(raw))
    except Exception:  # pragma: no cover - defensive
        return False


class _InflationBudget:
    """One mutable remaining-byte budget, SHARED by every level of one unwrap.

    A per-level limit is not a bound on the total. Until #283 the recursion was
    handed `limit` unchanged, so a zip of many small gzip members could stay
    under the limit at every individual level while the sum vastly exceeded it:
    measured at a 1 MiB test budget, an 8.7 KB zip of 64 gzip members (each
    inflating to just under 1 MiB) yielded 64 MiB of payload with
    `truncated=False` — 16 GiB resident at the real 256 MiB budget. Passing this
    object by REFERENCE instead makes the budget a bound on the TOTAL bytes one
    tree entry may be inflated to.

    `exhausted` is the disclosure half: it becomes the caller's `truncated`, so
    a walk the budget cut short is reported as a partial read rather than
    counted as a pass.
    """

    __slots__ = ("remaining", "exhausted")

    def __init__(self, limit: int):
        self.remaining = max(0, limit)
        self.exhausted = False

    def read(self, handle):
        """`(data, over)` — read at most what is left, charging the budget.

        One byte PAST the remaining budget is requested on purpose: it is how a
        payload that exactly fills the budget is told apart from one that
        overruns it. `over` is True only in the latter case, and the budget is
        then exhausted for every later member and deeper level too.
        """
        data = handle.read(self.remaining + 1)
        if len(data) > self.remaining:
            data = data[: self.remaining]
            self.remaining = 0
            self.exhausted = True
            return data, True
        self.remaining -= len(data)
        return data, False


def _unwrap_stream(raw: bytes, kind: str, budget: "_InflationBudget"):
    """(payload, truncated) for a single-stream wrapper, or (None, False).

    The `*File` wrappers are used rather than the one-shot `decompress()`
    helpers because they handle CONCATENATED streams (a multi-member bzip2 or
    xz) and because the bounded `read()` caps the inflation without
    materialising it.

    gzip does NOT come through here: it is walked member by member by
    `_gzip_members` instead, because each of its members carries a NAME of its
    own and this function would fold them all into one unnamed payload
    (increment 12).
    """
    openers = {
        "bzip2": lambda buf: bz2.BZ2File(buf, "rb"),
        "xz": lambda buf: lzma.LZMAFile(buf, "rb"),
    }
    try:
        with openers[kind](io.BytesIO(raw)) as handle:
            out, over = budget.read(handle)
    except Exception:
        # Corrupt or not actually this wrapper. Not a finding: the payload falls
        # through to the string harvest, and whatever it is stays disclosed.
        return None, False
    return out, over


def _gzip_header_name(raw: bytes):
    """The original filename a gzip header carries (FNAME), or None.

    RFC 1952 §2.3.1: `FLG` bit 3 means a NUL-terminated original file name
    follows the fixed 10-byte header (after `FEXTRA`, if bit 2 is set too).
    `gzip.GzipFile` reads this field and throws it away, and there is no public
    API for it — so it is parsed here. It is the ONLY name a single-stream
    wrapper carries: `evidence.dat` whose gzip header says `Bank Sine.wt` has
    no other name to judge, and before increment 9 nothing read it.
    """
    if not raw.startswith(GZIP_MAGIC) or len(raw) < 11:
        return None
    flags = raw[3]
    if not flags & 0x08:  # FNAME not present
        return None
    offset = 10
    if flags & 0x04:  # FEXTRA: a 2-byte length then that many bytes
        if len(raw) < offset + 2:
            return None
        extra = raw[offset] | (raw[offset + 1] << 8)
        offset += 2 + extra
    end = raw.find(b"\0", offset)
    if end < 0 or end <= offset:
        return None
    # Latin-1 per RFC 1952; replace rather than raise on anything else.
    return raw[offset:end].decode("latin-1", "replace")


# `zlib` with the gzip header/trailer handled for us (RFC 1952), one MEMBER at
# a time: `decompressobj` stops at the member's own trailer and hands the
# remainder back as `unused_data`, which is the only boundary a concatenated
# stream has. `gzip.GzipFile` inflates straight through those boundaries, which
# is why it cannot be asked where the second member's header starts.
GZIP_WBITS = 16 + zlib.MAX_WBITS


def _gzip_members(raw: bytes, budget: "_InflationBudget"):
    """([(FNAME|None, payload)] per MEMBER, truncated), or (None, False).

    A gzip stream may be CONCATENATED — `cat a.gz b.gz > c.gz` is a valid gzip
    file whose content is `a`'s followed by `b`'s — and **every member carries
    its own FNAME header**. Increment 9 read that header once per stream, from
    the first member only, so a `.wt` named by the SECOND member's header was
    not judged at all while the first member's innocuous `.json` name was: the
    same two members in the other order fired. That order-dependence is the
    whole defect this closes (increment 12).

    The inflation budget is SHARED with every other level of the same unwrap
    (`_InflationBudget`), exactly as `_unwrap_archive` already shares it across
    a zip's or a tar's members: each member's read is charged against the one
    `remaining` counter, and the first member that overruns it truncates there
    and reports `truncated` for the whole stream — a bound on the TOTAL this
    entry inflates to, not a fresh allowance per member.

    `None` means the stream is not cleanly parseable as gzip (a corrupt member,
    or trailing bytes that are not another member's header) — the same answer,
    and the same fall-through to the string harvest, that `gzip.GzipFile`
    raising `BadGzipFile` produced before.
    """
    members = []
    rest = raw
    while rest.startswith(GZIP_MAGIC):
        name = _gzip_header_name(rest)
        try:
            obj = zlib.decompressobj(wbits=GZIP_WBITS)
            data = obj.decompress(rest, budget.remaining + 1)
        except Exception:
            return None, False
        if len(data) > budget.remaining:
            # The budget stopped the walk mid-member: keep what fits, disclose
            # the partial read, and do not pretend to have seen later members'
            # names.
            data = data[: budget.remaining]
            budget.remaining = 0
            budget.exhausted = True
            return members + [(name, data)], True
        if not obj.eof:
            # All input consumed without reaching this member's trailer: the
            # stream is truncated or corrupt, not a wrapper this audit opened.
            return None, False
        members.append((name, data))
        budget.remaining -= len(data)
        rest = obj.unused_data
    if rest or not members:
        return None, False
    return members, False


# Joins a wrapper's name to the name of what it wraps. Every component of a
# joined label is tripwired separately, so an outer name is never masked by the
# inner one (`Bank Sine.wt!meta.json` must still read as a `.wt`).
MEMBER_JOIN = "!"


def _join_member(outer, inner):
    if outer and inner:
        return f"{outer}{MEMBER_JOIN}{inner}"
    return outer or inner or ""


def _unwrap_archive(raw: bytes, budget: "_InflationBudget"):
    """([(member name, payload)], truncated) for a zip/tar, or (None, False).

    The budget is shared with every other level of the same unwrap, so the sum
    of this archive's members is charged against whatever its own wrappers
    already spent — and against whatever its members go on to inflate to.
    """
    buf = io.BytesIO(raw)
    members = None
    try:
        if zipfile.is_zipfile(buf):
            members = []
            with zipfile.ZipFile(buf) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    with archive.open(info) as handle:
                        data, over = budget.read(handle)
                    members.append((info.filename, data))
                    if over:
                        return members, True
            return members, False
    except Exception:
        return None, False
    buf.seek(0)
    try:
        if not tarfile.is_tarfile(buf):
            return None, False
        buf.seek(0)
        members = []
        with tarfile.open(fileobj=buf, mode="r") as archive:
            for info in archive:
                if not info.isfile():
                    continue
                handle = archive.extractfile(info)
                if handle is None:  # pragma: no cover - sparse/odd member
                    continue
                data, over = budget.read(handle)
                members.append((info.name, data))
                if over:
                    return members, True
        return members, False
    except Exception:
        return None, False


def unwrap_payload(raw: bytes, budget=None, depth=0):
    """([(member name, payload)] carried inside `raw`, truncated), or (None, …).

    `None` means `raw` is not a wrapper — not that it is safe. Recurses so that
    a `.tar.gz` (and a `.tar.gz` inside a zip) is unwrapped to its real members;
    `truncated` is True when the inflation budget or the depth limit stopped the
    walk, so the caller can disclose an incomplete scan instead of reporting a
    pass.

    `budget` is an `_InflationBudget` shared by the whole recursion (default: a
    fresh `MAX_UNWRAPPED_BYTES` one per entry), so `MAX_UNWRAPPED_BYTES` bounds
    the TOTAL this entry inflates to rather than each level separately (#283).

    The member NAME travels with its payload (increment 9). Unwrapping read
    member CONTENT only, so a wrapper whose members carry no marker — a zip of
    upstream `.wt` wavetables, a tar of marker-free `.cpp` sources — was
    answered by nothing: the archive extensions judge the OUTER name, which a
    `.dat` rename evades. A member that is itself a wrapper keeps its own name
    in the label (`dsp/Reverb1.h.gz!…`) rather than being replaced by what it
    wraps.

    A gzip stream is walked member by member (increment 12), so EVERY member of
    a concatenated stream contributes its own name. Reading the FNAME once per
    stream made the rule order-dependent: `cat notes.json.gz 'Bank Sine.wt.gz'`
    audited clean while the same two members in the other order fired.
    """
    if budget is None:
        budget = _InflationBudget(MAX_UNWRAPPED_BYTES)
    if depth >= MAX_UNWRAP_DEPTH:
        return None, _looks_like_wrapper(raw)
    for magic, kind in STREAM_WRAPPERS:
        if not raw.startswith(magic):
            continue
        if kind == "gzip":
            # EVERY member of a concatenated stream, each with its own FNAME
            # (increment 12). Before this, one name was read for the whole
            # stream and members 2..n were content-scanned but never named.
            members, truncated = _gzip_members(raw, budget)
        else:
            inner, truncated = _unwrap_stream(raw, kind, budget)
            members = None if inner is None else [(None, inner)]
        if members is None:
            return None, False
        entries = []
        for label, inner in members:
            deeper, deeper_truncated = unwrap_payload(inner, budget, depth + 1)
            truncated = truncated or deeper_truncated
            if deeper is None:
                entries.append((_join_member(label, ""), inner))
            else:
                entries.extend(
                    (_join_member(label, name), payload) for name, payload in deeper
                )
        return entries, truncated
    members, truncated = _unwrap_archive(raw, budget)
    if members is None:
        return None, truncated
    entries = []
    for name, member in members:
        deeper, deeper_truncated = unwrap_payload(member, budget, depth + 1)
        truncated = truncated or deeper_truncated
        if deeper is None:
            entries.append((name, member))
        else:
            entries.extend(
                (_join_member(name, inner), payload) for inner, payload in deeper
            )
    return entries, truncated
