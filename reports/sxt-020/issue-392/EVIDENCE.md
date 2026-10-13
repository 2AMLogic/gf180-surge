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

## Review round 1 (Judge, head bd9585b) - two further gaps, fixed
Observed before this round (`review_gap_probe.py` run against a `git archive`
of bd9585b, output `review-gap-before-fix.txt`): all three checksum-valid
mutations produced no failing check at all:
- `reverse_packing`: external `fx_slot_5` at 0, `fx_slot_4` at 2228224 (both
  placement copies). Nonoverlapping and contained, but reverses the
  format.md section 5 cumulative slot order.
- `empty`: `allocations.fx_instances = []` (agreement check was vacuous).
- `duplicate`: first `fx_instances` entry appended twice.

Fix:
- `expected_layout()` re-derives the format.md section 5 layout from the
  SXT-015 account and the source graph's wavetable records (on_chip:
  `voice_state` then on-chip `fx_slot_N` in slot order; external_writable:
  external `fx_slot_N` in slot order; flash_assets: embedded wavetables in
  record order; offsets cumulative from 0), mirroring compile.py
  `_allocations()`. New check `alloc/cumulative-layout/<region>` requires the
  image's blocks of the normative kinds (`voice_state_aggregate`,
  `fx_instance_state`, `flash_asset_wavetable`) to equal that layout exactly
  (name, kind, offset, size). Blocks of any other kind are not part of the
  compiler layout and are held only to the typing/containment/overlap checks;
  this is what keeps the documented zero-length probe accepted.
- New check `alloc/fx-instances-one-per-slot`: the `fx_instances` placement
  copy must hold exactly one integer-slot entry per expected instance slot
  (no missing, extra or duplicate owners). `alloc/fx-instances-agree-with-blocks`
  runs only after that passes; otherwise it FAILs as skipped.

After (`review-gap-after-fix.txt`): `reverse_packing` fails only
`alloc/cumulative-layout/external_writable`; `empty` and `duplicate` fail
`alloc/fx-instances-one-per-slot` (and the skipped agreement check).

## Controls (live, `verify.py controls`, NC5; output `controls-after.txt`)
All mutations are checksum-valid (image/* PASS); each must FAIL its check:
overlap (ext, on_chip), out-of-range, negative offset, bool offset,
duplicate slot ownership, reverse packing
(`alloc/cumulative-layout/external_writable`), and `fx_instances` empty /
one entry omitted / first entry duplicated (`alloc/fx-instances-one-per-slot`)
-> PASS (each control fails its targeted check).
Positives: unmodified golden (on_chip voice_state@0 and external fx_slot_4@0
share offset 0 across address spaces) and an appended zero-length block ->
PASS (accepted by all 15 layout checks, including the new cumulative-layout
and fx-instances checks).

## Commands / results
Re-run after review round 1 (Python 3.12, worktree):
- `python3 compiler/verify.py controls` -> PASS (29 checks; `controls-after.txt`)
- `python3 compiler/verify.py golden` -> PASS (303 checks, including
  byte-identical recompilation; no file under `compiler/golden/` changed)
- `python3 compiler/verify.py alloc compiler/golden/compiled/four-fx-instance.image.bin` -> PASS (31 checks; `golden-alloc-after.txt`)
- `uvx --with pytest pytest tests/test_sxt020_compile.py` -> PASS (12, ~9 s),
  including the new CLI tests for reverse packing and empty/duplicate
  `fx_instances`
- `uvx --with pytest pytest tests/test_byte_frozen_sources.py` -> PASS (28, ~47 s)
- `tests/test_negative_controls_live.py` -> NOT_RUN: deliberately not run on
  this shared host (the reviewer's bounded runs of it timed out; earlier the
  throwaway env also lacked numpy). No pass is claimed for it.
- `compiler/verify.py` is not in the byte-frozen registry; no records re-derived.

## Not proved
Layout agreement with a hardware memory map (the cumulative layout is the
compiler's format.md rule, not an RTL address map); per-instance state isolation in
RTL; anything about sound.
