# SXT-020 evidence record — patch-image compiler (issue #13)

Branch: `loom/sxt-020-patch-images` · Issue: #13 (SXT-020) · Date: 2026-09-20

**Claim discipline.** This record covers compiler behavior only:
deterministic image emission, lossless graph carriage, explicit
machine-readable rejection, and reconciliation of rejections against the
committed SXT-017 DRAFT predictions. **No fidelity, preset-support,
preset-quality, musical-usefulness, or hardware claim is made or advanced.**
"Compiled" means only *the complete original normalized graph fits the
DRAFT-NOT-FROZEN bundle's declared gates and is expressible as an image*;
every allocation number is an SXT-015 bookkeeping placeholder
**[PENDING-SXT-016]**. Numeric tests never establish musical usefulness.

Deliverables: `compiler/` (format spec `format.md`, compiler `compile.py`,
rejection machinery `reject.py` + `rejections.json`, validation harness
`verify.py`, schema references `schema/`, golden suite `golden/` +
`build_golden.py`, `README.md`), `reports/sxt-020/compile-corpus-scan.json`,
`reports/sxt-020/negative-controls.txt`, `tests/test_sxt020_compile.py`.

Inputs: `corpus/normalized/graphs.jsonl` (sha256
`c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715`),
`contracts/profile-v1-bundle-DRAFT.json` (sha256
`89a8229bdef729196ce9f40bbc682074c14124b5a6213134383285cb96266eda`,
bundle **B4-broad**, `DRAFT-NOT-FROZEN`), `model/resources/` (SXT-015),
`tools/profile_predict.py` (SXT-017 gate evaluator, imported unmodified).
No oracle/engine build required — the compiler works over committed graphs.

## 1. Issue-#13 acceptance mapping

| #13 acceptance item | Status | Evidence |
|---|---|---|
| Image carries source preset hash, graph, routes, asset references, allocations, checksums | **PASS** | Header: `source.census_blob_sha1` (git blob SHA-1), `normalized_graph_sha256` (SHA-256 over canonical `g`), `pin`, `profile` (bundle id + file SHA-256 + embedded spec). Body `graph`: verbatim scenes/fx-slots/modulation/wavetable-assets + scalars and provenance fields — every source field exactly once; `verify.py image` **rebuilds `g` from the image and requires its hash to equal `header.normalized_graph_sha256`** (losslessness, 183-check golden suite includes this per compiled case). Body `derived.allocations`: per-instance state blocks with regions/offsets/sizes from the SXT-015 model, external-writable vs on-chip vs flash-assets, bandwidth, budgets. Checksums: `body_sha256` over canonical body + container SHA-256 over all preceding bytes. |
| Every unsupported path produces a distinct rejection reason; nothing silently dropped | **PASS** | 22-code catalog (`compiler/rejections.json`; 18 names shared with SXT-017 + `asset_unresolved`, `send_levels_not_exported`, `routing_form_unsupported`, + reserved `oscillator_submode_not_in_bundle`); emitted codes are validated against the catalog at emit time (uncataloged ⇒ abort). The compiler emits a complete image **or** a rejection record — never a reduced image (enforced by golden suite + NC1/NC4 + tests). Adaptation-class codes are compile rejections: the compiler compiles original graphs only. Corpus scan: every one of the 3,561 entries has exactly one outcome with codes. |
| Golden images byte-stable across compiler runs | **PASS** | `compiler/golden/`: 18 manifest cases (8 compiled byte-pinned images incl. the SXT-015 worked presets, 10 rejection records); `verify.py golden` recompiles every case from the committed graphs (census blob SHA asserted) and requires byte identity — **PASS: 183 checks, 0 failed**. Repeated single compiles `cmp` clean; full scan re-run `cmp` clean; `tests/test_sxt020_compile.py::test_compile_is_byte_deterministic` + `test_scan_is_current_and_reconciles` enforce in CI. No timestamps anywhere in images. |
| Rejections reconcile with SXT-017 predictions on a sample set | **PASS** (full corpus, stronger than a sample) | Gate semantics are the SXT-017 predictor's own evaluator, imported unmodified, so agreement is by construction; the compiler's gate set is a superset (image-emitter gates), so it can only reject **more**, never less. Full 3,561-entry reconciliation in `compile-corpus-scan.json`: **3,559/3,561 agree; exactly 2 deltas, both compiler-stricter, both named** (§3 below). |
| Negative control: a normalized graph carrying a profile-unsupported feature must yield a rejection, never a trimmed image | **PASS** | `reports/sxt-020/negative-controls.txt` + `verify.py controls` (**PASS: 17 checks, 0 failed**): crafted 9-enabled-instance graph (limit 8) ⇒ `rejected` with `fx_instance_overflow`, **no image emitted**; corrupted-checksum image ⇒ `ImageError` on both body-byte flip and truncation; every golden rejection record ships no image beside it. **PASS** |

Non-goal check (issue #13): chip-side interpretation (SXT-021) not started;
the format is designed for it but nothing consumes images yet.

## 2. Corpus-scan headline (`compile-corpus-scan.json`, all 3,561 graphs)

| Outcome | Total | Factory (/641) | Contributor (/2,920) |
|---|---:|---:|---:|
| **compiled** | **1,683** | 548 | 1,135 |
| rejected (codes attached) | 1,296 | 77 | 1,219 |
| unresolved (cannot evaluate today) | 582 | 16 | 566 |

Top rejection codes (presets carrying the code; multi-code entries count in
each):

| Code | Presets | Code | Presets |
|---|---:|---|---:|
| `effect_class_not_in_bundle` | 1,292 | `audio_input_dependency` | 87 |
| `oscillator_family_not_in_bundle` | 806 | `send_levels_not_exported` (SXT-020) | 73 |
| `mseg_or_formula_contents_not_exported` | 582 | `fx_instance_overflow` | 31 |
| `airwindows_algorithm_not_selected` | 256 | `asset_unresolved` (SXT-020) | 2 |
| `polylimit_reduction_required` (adapted) | 212 | | |

The 582 unresolved are the SXT-011 MSEG/Formula exposure gap (581 graphs)
plus the loader-failure class (0 in the committed export) — same
denominator discipline as SXT-017.

## 3. Reconciliation with SXT-017 predictions (B4-broad)

Predicted: supported **1,685** (549 factory + 1,136 contributor) /
unsupported 1,130 / adapted-not-predicted 164 / unresolved 582.
Mapping: supported→compiled, unsupported→rejected,
adapted→rejected (adaptation codes are compile rejections),
unresolved→unresolved.

**Agreement 3,559/3,561. Compiled 1,683 = 1,685 − 2. The two deltas,
precisely (also enumerated per-preset in the scan's `reconciliation.deltas`):**

| Preset | Predictor | Compiler | Compiler-only code that fired |
|---|---|---|---|
| `patches_3rdparty/Exquis MPE/Strings/Rock.fxp` | supported | rejected | `send_levels_not_exported` — an enabled FX sits in send slot 3; SXT-011 does not export send levels for buses 3/4 (binding exposes `send_level[0..1]`), so the image cannot express the complete send routing. Emitting one would implicitly trim the patch. |
| `patches_factory/FX/Aggero.fxp` | supported | rejected | `asset_unresolved` — a wavetable record with neither embedded bytes nor a resolved file; the engine default-table fallback would silently substitute a different table. |

Both are *image-emitter* obligations the predictor (which emits no image)
does not carry; the direction of every delta is compiler-stricter, as
designed. No preset compiles that the predictor did not predict supported.
`send_levels_not_exported` fires on 73 presets in total and
`asset_unresolved` on 2, but only these 1+1 were inside the predicted-
supported set; the other 72+1 were already rejected/unresolved for other
reasons (their records now simply carry the additional code).

## 4. Golden suite and findings

18 cases (`compiler/golden/manifest.json`): 8 compiled — simple factory
Classic (`Attacky`), all-FX-off baseline (`Amen Polska`, SXT-015 example c),
wavetable-asset (`Kick`), dual-scene (`Accordion Lead`), 4-FX-instance
(`Monster Feedback`: EQ/Distortion/Delay/Reverb 1 with insert+send roles and
two per-instance external blocks), split-scene (`Bilbo 110 BPM`: **three**
enabled Delay slots = three delay histories), send-FX (`Grant Me...`),
and `96 Osc Supersaw` (SXT-015 example b; unison 16 on all six slots,
Chorus + Reverb 2) — and 10 rejection records spanning 9 distinct codes
across all three classes (unsupported / adaptation / unresolved), including
`July` (SXT-015 example a; MSEG gap takes precedence over its
AW/class codes) and the two reconciliation-delta presets.

Findings recorded honestly:

1. **An Airwindows-carrying *compiled* image is impossible under the DRAFT
   B4-broad spec**: its `fx_type_allowlist` excludes the Airwindows class
   entirely, and the class allowlist binds before the algorithm selection
   (the effect profile-v1-DRAFT §4 already documents as "the class allowlist
   binds first"). The brief's "Airwindows-carrying" golden item is therefore
   covered on the rejection side: `July` (real preset,
   `airwindows_algorithm_not_selected` + class code) and a clearly-labeled
   **synthetic** input (`golden/inputs/synthetic-airwindows-point.line.json`)
   pinning both Airwindows-related codes. A compiled AW image becomes
   reachable only through a bundle revision (e.g. the R0 context) — recorded
   here, not worked around.
2. **The brief's "FM3 oscillator" example is in B4's allowlist**, so the
   negative control pins both sides: the same crafted FM3 graph **compiles**
   under B4-broad and **rejects** under B2-core-wet-plan3
   (`oscillator_family_not_in_bundle`; plus B2's expected polylimit code).
   Genuinely-unsupported B4 features (9th FX instance, Window/Modern
   oscillators) demonstrate the rejection path directly.
3. `XTease.fxp` (12 enabled instances, corpus max) also carries an enabled
   send3-slot FX, so its golden record pins five codes at once — the
   multi-gate fail-closed behavior on a real preset.

## 5. What remains unproved / NOT_RUN

- Every allocation number is an SXT-015 placeholder [PENDING-SXT-016]; the
  bundle budgets are candidates, not claims; cycle closure is **not gated**
  (columns only).
- No fidelity result, preset-support claim, or musical-quality judgment —
  compiled ≠ sounds like the reference; that requires the frozen fidelity
  policy and listening records (SXT-013/014, both BLOCKED).
- No chip-side interpretation (SXT-021 NOT_RUN), no RTL, no synthesis/
  place-and-route/signoff, no hardware playback.
- The compiled profile is **DRAFT-NOT-FROZEN** (freeze BLOCKED on human
  listening + SXT-016); images carry that status in every header and
  rejection record, and a bundle change re-runs the scan + golden
  regeneration visibly.
- Reserved code `oscillator_submode_not_in_bundle` is not evaluable under
  the current bundle-spec schema (declared for a future revision; gating
  submodes/subtypes/algorithms would be a visible contract revision,
  profile-v1-DRAFT §8 trigger 6).

## 6. Reproduce

```sh
python3 compiler/compile.py scan \
  --out /tmp/scan.json --reconcile reports/sxt-017/predictions/B4-broad.json
cmp /tmp/scan.json reports/sxt-020/compile-corpus-scan.json && echo IDENTICAL
python3 compiler/verify.py golden     # PASS: 183 checks
python3 compiler/verify.py controls   # PASS: 17 checks
python3 compiler/build_golden.py      # byte-identical regeneration
pytest tests/test_sxt020_compile.py   # 8 tests
```
