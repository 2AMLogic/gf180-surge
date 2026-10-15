#!/usr/bin/env python3
"""SXT-020 version-consistency controls (issue #391).

Derives checksum-valid mutants of a good image that change ONLY version
declarations (graph/body unchanged), re-running canonical JSON lengths and the
container digest so the verifier's version checks (not checksum checks) are
what is exercised. Used by tests/test_sxt020_compile.py and by the evidence
runner (reports/sxt-020-version/run_evidence.py).
"""
import hashlib
import json
import struct

CONTROLS = [
    # name, binary major, binary minor, header field overrides
    ("binary-major-99", 99, None, {}),
    ("binary-minor-99", None, 99, {}),
    ("binary-minor-0-vs-header-1", None, 0, {}),
    ("header-format-major-99", None, None, {"format_major": 99}),
    ("header-format-minor-99", None, None, {"format_minor": 99}),
    ("header-format-minor-0-vs-binary-1", None, None, {"format_minor": 0}),
    ("header-format-major-str", None, None, {"format_major": "1"}),
]


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def mutate(data, major=None, minor=None, header_overrides=None):
    """Return a checksum-valid image with changed version declarations."""
    hlen, blen = struct.unpack("<HI", data[6:12])
    header = json.loads(data[12:12 + hlen].decode("utf-8"))
    body_bytes = data[12 + hlen:12 + hlen + blen]
    header.update(header_overrides or {})
    hb = _canon(header)
    payload = (data[:4] + struct.pack(
        "<BBHI", data[4] if major is None else major,
        data[5] if minor is None else minor, len(hb), len(body_bytes))
        + hb + body_bytes)
    return payload + hashlib.sha256(payload).hexdigest().encode("ascii")
