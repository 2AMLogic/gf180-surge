# Issue #392 - allocation offset / overlap / ownership verification

Scope: structural checks in `compiler/verify.py` only. Establishes nothing
about hardware state isolation, fidelity, or preset quality. ABI, golden image
bytes and compiler accounting are unchanged.

## Gap (before the fix) - observed
`gap_probe.py` mutates `four-fx-instance` (external_writable `fx_slot_5` offset
2097152 -> 0, in both the block and its `fx_instances` copy), recomputes
`body_sha256` and the container digest, and runs the verifier. Pre-fix output
(`gap-before-fix.txt`): all `image/*` PASS and `alloc ok True` -> an
overlapping layout was accepted. Status: gap PASS-through demonstrated.

## Fix
New `layout_checks()` called from `alloc_checks()`, per address space
(on_chip, external_writable, flash_assets): `alloc/offsets-integer-nonneg/<r>`
(rejects bool, float, negative), `alloc/blocks-contained/<r>`,
`alloc/no-overlap/<r>`; plus `alloc/unique-slot-ownership` and
`alloc/fx-instances-agree-with-blocks`. Zero-length blocks are accepted and
skipped by the overlap test.

## Controls (live, `verify.py controls`, NC5; output `controls-after.txt`)
All mutations are checksum-valid (image/* PASS); each must FAIL its check:
overlap (ext, on_chip), out-of-range, negative offset, bool offset,
duplicate slot ownership -> PASS (control fails the targeted check).
Positives: unmodified golden (on_chip voice_state@0 and external fx_slot_4@0
share offset 0 across address spaces) and an appended zero-length block ->
PASS (accepted).

## Commands / results
- `python3 compiler/verify.py controls` -> PASS (25 checks)
- `python3 compiler/verify.py golden` -> PASS (271 checks; goldens byte-identical)
- `python3 compiler/verify.py alloc compiler/golden/compiled/four-fx-instance.image.bin` -> PASS (`golden-alloc-after.txt`)
- `uvx pytest tests/test_sxt020_compile.py tests/test_byte_frozen_sources.py` -> PASS (38)
- `tests/test_negative_controls_live.py` -> NOT_RUN to a verdict here: the
  throwaway uvx env lacks numpy (13 ModuleNotFoundError in aw*/reverb tools,
  unrelated to this change).
- `compiler/verify.py` is not in the byte-frozen registry; no records re-derived.

## Not proved
Layout agreement with a hardware memory map; per-instance state isolation in
RTL; anything about sound.
