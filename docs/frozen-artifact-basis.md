# Artifacts frozen at a superseded basis

**These committed artifacts record a *retired* accounting / input basis on
purpose.** Do not "fix" one by regenerating it on its own: each entry below
names what the freeze costs to retire, and every one of them is retired by a
run that re-emits the artifact *and* re-derives every digest its leaf records
for it, in the same change.

Machine-readable registry:
[`docs/frozen-artifact-basis.json`](frozen-artifact-basis.json).
Audit: `tests/test_frozen_artifact_basis.py` (re-derives each live basis,
re-reads each frozen value out of the artifact, and scans the tree for
unregistered records carrying a frozen value).

**What this registry is and is not.** It is evidence bookkeeping: it records
which basis a committed artifact quotes. It establishes nothing about RTL
exactness, model-vs-reference agreement, cycles, area, technology,
preset support, or preset quality — those claims live in the leaf reports and
are unaffected by this file. Supported-preset delta: **0**.

## Why this file exists

#239 (PR #249) moved the SXT-015 accounting basis —
`sxt-015-accounting/1.0.0` → `1.1.0`, `params_digest` `646942e9c3887ecb` →
`a639d3115ae1a0ca` — and re-exported every artifact that a test holds
current. Six committed artifacts were deliberately **not** regenerated and
were recorded as STALE in
[`reports/sxt-015/EVIDENCE.md` §8.5](../reports/sxt-015/EVIDENCE.md).

Every one of those six is **self-verifying**: it is checked against digests
it records itself, never against the live model. So nothing in CI could tell
a deliberate freeze from silent rot, and the next basis move would have added
to the pile just as quietly. Issue #246 is that gap; this registry plus its
audit is the fix.

## A freeze is not a currency pin — never conflate them

|  | Currency pin | Frozen basis (this registry) |
|---|---|---|
| What is asserted live | the artifact equals the live basis | the artifact equals its **declared, superseded** value, and the live basis equals the value the declaration is superseded **by** |
| Superseded values in the tree? | No — a mismatch *is* a STALE record | Yes, deliberately, at a named value with a recorded reason |
| What a basis move does | breaks the pin until the artifact is re-exported | fails the audit until each frozen entry gets a *fresh decision* (re-emit, or re-declare against the new basis) |
| Correct disposition of a drifted value | regenerate the artifact | read `retired_by`, then do that whole run — not a one-file regeneration |

The second column's live half is what makes the next basis move fail closed:
mutating the live `params_digest` fails
`test_live_basis_still_equals_the_value_the_freezes_cite`, and a frozen
artifact that silently drifts off its declared value fails
`test_frozen_artifact_still_records_its_declared_basis`. Both directions are
covered, because both have happened.

The two mechanisms are complements, not alternatives, and the tree now
carries one of each: `tests/test_sxt015_currency.py` (issue #247,
`reports/sxt-015/EVIDENCE.md` §9) is the **currency** side — it re-runs
`tools/account_corpus.py` and requires byte-equality with every committed
`reports/sxt-015/` export, so nothing in that directory may lag the tool.
This registry is the **freeze** side, for artifacts that deliberately may
lag, at a named value, with a named retirement path. An artifact belongs to
exactly one of the two; none of the six below is covered by a currency
check, which is why they could drift unnoticed.

## Live bases

| Basis id | Re-derived from | Live value | Moved by |
|---|---|---|---|
| `sxt-015-accounting` | `model.resources.accounting:MODEL_VERSION` / `params_digest()` | `sxt-015-accounting/1.1.0` / `a639d3115ae1a0ca` | #239 (PR #249) |
| `sxt-020-compile-scan` | sha256 of `reports/sxt-020/compile-corpus-scan.json` | `791b2c88b7360256…` | #239 (PR #249) |

## Frozen artifacts

| Artifact | Leaf | Frozen at | Declared in | Retired by |
|---|---|---|---|---|
| `model/integration/preset/Hell_s_Bells__e499f78d.image.json` | SXT-025 | `sxt-015-accounting/1.0.0` / `646942e9c3887ecb` | `reports/sxt-025/EVIDENCE.md` | an oracle-gated SXT-025 re-extraction + re-render |
| `reports/sxt-025/negative-controls/image-permuted-placement.json` | SXT-025 | same | `reports/sxt-025/EVIDENCE.md` | a `model/integration/negative_controls.py` re-run after the image above |
| `reports/sxt-026/artifacts/Kick__4f2443aa.image.json` | SXT-026 | same | `reports/sxt-026/EVIDENCE.md` | `tools/run_sxt026_checks.py --asset-root <pinned tree>` |
| `reports/sxt-027/leaf-plan.json` | SXT-027 | `sxt-015-accounting/1.0.0` + `compile_scan e23e351c…` | `reports/sxt-027/EVIDENCE.md` | an SXT-027 leaf-ledger revision (`tools/generate_voice_leaves.py`) + coverage republication |
| `reports/sxt-027/leaf-backlog.json` | SXT-027 | same | `reports/sxt-027/EVIDENCE.md` | same |
| `reports/sxt-027/leaves-filed.json` | SXT-027 | `compile_scan e23e351c…` | `reports/sxt-027/EVIDENCE.md` | same |

Per-artifact reasons — including why re-emitting is *not* the cheap option
for any of them — are in the `why` field of each JSON entry, and the owning
leaf's EVIDENCE declares the freeze in its own terms.

Two of the six are oracle-gated (`NOT_RUN` here, not "skipped"): the SXT-025
image's dependent digests come from a `surgepy` extraction run, and the
SXT-026 image can only be emitted with the pinned Surge `resources/data`
asset tree, without which the compiler would drop the embedded wavetable
asset manifest the leaf's identity evidence reads.

## Adding or retiring an entry

1. **Retiring** (the artifact is being brought current): run the whole
   `retired_by` procedure, re-pin every digest the owning leaf records for
   that artifact in the same change, delete the registry entry, and replace
   the leaf's freeze declaration with the re-export note. Partial retirement
   — regenerating the artifact but not its dependent digests — is what this
   registry exists to prevent.
2. **Adding**: add the entry (path, leaf, `declared_in`, each
   `frozen_values` row, `why`, `retired_by`), declare it in the owning leaf's
   EVIDENCE naming the artifact, the frozen value, and this registry, then
   run `python3 -m pytest tests/test_frozen_artifact_basis.py`. A new basis
   also needs a live re-derivation in `LIVE_BASES` in that test — the audit
   refuses a basis it cannot re-derive.

Original to this repository (Apache-2.0 per `LICENSE`).
