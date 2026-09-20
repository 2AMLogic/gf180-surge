# SXT-020 — Patch-image compiler (`compiler/`)

Turns SXT-011 normalized patch graphs (`corpus/normalized/graphs.jsonl`)
into **versioned patch images** — or into explicit, machine-readable
**rejection records**. The chip never receives an implicitly trimmed patch:
for every input there is either a complete image or a rejection with
cataloged codes. Never both, never neither, never a reduced image.

**Status: DRAFT.** Compiled against `profile-v1-DRAFT` bundle **B4-broad**
(`DRAFT-NOT-FROZEN`). An image is a structural artifact: it makes no
fidelity, support, or preset-quality claim, and every allocation number is
an SXT-015 placeholder [PENDING-SXT-016].

| File | Contents |
|---|---|
| `format.md` | image format v1 spec: container layout, header/body, allocations, determinism + versioning policy, claim discipline |
| `version.py` | format + compiler version identity (single source) |
| `compile.py` | the compiler: `compile` (one entry → `.image.bin` + `.image.json`, or `.rejection.json`) and `scan` (all 3,561 → corpus scan + SXT-017 reconciliation) |
| `reject.py` | rejection machinery: catalog load, fail-closed code validation, outcome classification, engine routing-order facts |
| `rejections.json` | the rejection catalog: 22 codes (18 shared with SXT-017, 4 SXT-020) + declared non-gates |
| `verify.py` | validation harness: `image` (parse + checksums + losslessness), `alloc` (reconciliation vs the SXT-015 model + budgets), `golden` (full suite), `controls` (negative controls) |
| `build_golden.py` | regenerates `golden/` deterministically |
| `schema/` | field-by-field reference for header and body |
| `golden/` | 18 pinned cases (8 compiled byte-pinned images, 10 rejection records incl. 2 synthetic inputs) + `manifest.json` |

## Reconciled gate semantics

Feature/resource gates are the SXT-017 predictor's own evaluator
(`tools/profile_predict.py`), imported unmodified — compile outcomes
reconcile with `reports/sxt-017/predictions/` by construction. On top, the
compiler applies image-emitter gates (`asset_unresolved`,
`send_levels_not_exported`, `routing_form_unsupported`) and can therefore
reject **more**, never less; every delta vs the predictions is enumerated in
the scan.

## Usage

```sh
# one preset -> image or rejection record
python3 compiler/compile.py compile \
  --path "resources/data/patches_factory/Basses/Attacky.fxp" --out-dir /tmp/out

# full corpus + reconciliation vs the committed SXT-017 prediction
python3 compiler/compile.py scan \
  --out reports/sxt-020/compile-corpus-scan.json \
  --reconcile reports/sxt-017/predictions/B4-broad.json

# validate an image; run the golden suite; run negative controls
python3 compiler/verify.py image /tmp/out/Attacky__*.image.bin
python3 compiler/verify.py golden
python3 compiler/verify.py controls

# regenerate goldens (byte-identical; CI test flags drift)
python3 compiler/build_golden.py
pytest tests/test_sxt020_compile.py
```

Determinism: same graph bytes + same bundle file + same compiler version ⇒
byte-identical outputs (canonical JSON, no timestamps). Python 3 stdlib
only; no engine tree required.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). Imports this
repository's own SXT-015 accounting model and SXT-017 predictor; reads the
committed SXT-011 graphs. No Surge source, tables, algorithm lists, or
preset payloads are copied. The lossless round-trip / explicit-rejection
*method* follows the issue-#13 reusable-substrate pointers (DX7 gf180-dx7#8
SysEx codec discipline; gf180-torchsynth content addressing) as method only
— no sibling code was copied (`docs/REUSE-AUDIT.md`).
