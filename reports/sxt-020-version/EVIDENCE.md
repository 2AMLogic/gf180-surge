# SXT-020 version-consistency evidence (issue #391)

Scope: structural container verification only. No fidelity, support, audio, or
hardware claim. Profile remains DRAFT-NOT-FROZEN.

Positive input: `compiler/golden/compiled/simple-classic.image.bin`,
sha256 `6b0befea10eb654acc217c650cd4bc4c4bb8b2f532aa54616a7996e499d3b55b`
(unchanged; `git diff -- compiler/golden` empty).

## Mutations (compiler/version_controls.py)
Graph/body bytes unchanged; header JSON re-serialized canonically, header_len
and container sha256 recomputed, so every control is checksum-valid.

| control | mutation |
|---|---|
| binary-major-99 | binary byte 4 = 99 |
| binary-minor-99 | binary byte 5 = 99 |
| binary-minor-0-vs-header-1 | binary byte 5 = 0 (header says 1) |
| header-format-major-99 | header.format_major = 99 |
| header-format-minor-99 | header.format_minor = 99 |
| header-format-minor-0-vs-binary-1 | header.format_minor = 0 |
| header-format-major-str | header.format_major = "1" (type) |

Mutant sha256:

| control | sha256 |
|---|---|
| binary-major-99 | 36fb1e6c8350d1725c1df322ead94296f81ac2a0d44144c1e64abc45bc528890 |
| binary-minor-99 | e8178880f7b49a547e556cfe4314b63b8792ba20d9757af4b1bc25cc9caa5002 |
| binary-minor-0-vs-header-1 | 621c04bca6684d5880a2dfa23e1d735d9c8c18156e01bcc9e53d22e6b53b91ca |
| header-format-major-99 | 97b4bf13eca707668ef55847348575f08040df0d791e4fb59fb5c525fe164e4a |
| header-format-minor-99 | b658093778f576ec05294c340beda36a2b9ef20da3035821c6a8e3b1d51a713e |
| header-format-minor-0-vs-binary-1 | a21088cd9550d72e87a59f6c2e927f0640faa0f446713b401d50077e39876c87 |
| header-format-major-str | d4aea79fa0bec6cc8e9bdae8792e008050c99cb97856f2f68f9e312c97007aec |

## Results (python3 compiler/verify.py image <file>)

Before fix (`before-fix.txt`, pre-change tree): all 7 controls exit 0, no FAIL
-> old acceptance REPRODUCED (defect confirmed).

After fix (`after-fix.txt`): all 7 controls exit 1 with a `FAIL image/parse -
version: ...` line naming the specific contradiction. Status: PASS (controls
rejected as required).

Golden image: `verify.py image` PASS (5 checks), exit 0.

## Coverage vs agreement
Execution coverage: 7 of 7 version controls run before and after; golden
suite (183 checks, PASS), negative controls (17 checks, PASS),
`tests/test_sxt020_compile.py` (10 passed) and `tests/test_byte_frozen_sources.py`
(passed) executed. Agreement: golden bytes identical; rejections match
expected version-specific messages.
Not covered: no backward-compatible versions (none accepted by design);
other formats' consumers outside compiler/ were not audited.
