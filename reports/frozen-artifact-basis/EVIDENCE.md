# Frozen-artifact-basis evidence record (issue #246)

Issue: #246 · Date: 2026-09-30 · Branch: `feature/issue-246`

**Claim discipline.** This record establishes exactly one thing: six
committed artifacts that recorded a superseded accounting / input basis now
carry a **recorded per-artifact disposition** and a **machine check** that
fails closed on further drift. It establishes **no** RTL-exactness,
model-vs-reference, cycle, area, technology, preset-support or
preset-quality claim, moves **no** leaf verdict, and makes no statement
about how anything sounds. Supported-preset delta: **0**.

## The finding this dispositions

#239 (PR #249, merged 2026-09-30) moved the SXT-015 accounting basis —
`MODEL_VERSION` `sxt-015-accounting/1.0.0` → `1.1.0` and `params_digest`
`646942e9c3887ecb` → `a639d3115ae1a0ca` — and re-exported
`reports/sxt-020/compile-corpus-scan.json` (whose sha256 moved to
`791b2c88b7360256…`). Six committed artifacts were deliberately not
regenerated and were recorded as STALE in `reports/sxt-015/EVIDENCE.md`
§8.5. Each is **self-verifying** — checked against digests it records
itself, never against the live model — so nothing in CI could distinguish a
deliberate freeze from silent rot, and the next basis move would have added
to the pile just as quietly.

**Relation to #247 (complement, not overlap).** #247 landed
`tests/test_sxt015_currency.py` (`reports/sxt-015/EVIDENCE.md` §9): a
**currency** check that re-runs `tools/account_corpus.py` and requires
byte-equality with every committed `reports/sxt-015/` export. It is the
right mechanism for an artifact that must never lag the tool, and it covers
none of the six here — none of them lives under `reports/sxt-015/`, and all
six are artifacts that deliberately *may* lag. This record is the other
half of that pair: a declared freeze at a named value, plus the live
assertion that makes the *next* basis move fail closed. An artifact belongs
to exactly one of the two mechanisms, and conflating them would either
falsify a run stamp (freezing what should be current) or read a deliberate
freeze as rot (holding a freeze to a currency pin).

## Disposition: all six declared FROZEN (option (b)), none re-emitted

| Artifact | Leaf | Disposition | Declared in |
|---|---|---|---|
| `model/integration/preset/Hell_s_Bells__e499f78d.image.json` | SXT-025 | FROZEN at `sxt-015-accounting/1.0.0` / `646942e9c3887ecb` | `reports/sxt-025/EVIDENCE.md` |
| `reports/sxt-025/negative-controls/image-permuted-placement.json` | SXT-025 | FROZEN, same values | `reports/sxt-025/EVIDENCE.md` |
| `reports/sxt-026/artifacts/Kick__4f2443aa.image.json` | SXT-026 | FROZEN, same values | `reports/sxt-026/EVIDENCE.md` |
| `reports/sxt-027/leaf-plan.json` | SXT-027 | FROZEN at `sxt-015-accounting/1.0.0` + `compile_scan e23e351c…` | `reports/sxt-027/EVIDENCE.md` |
| `reports/sxt-027/leaf-backlog.json` | SXT-027 | FROZEN, same values | `reports/sxt-027/EVIDENCE.md` |
| `reports/sxt-027/leaves-filed.json` | SXT-027 | FROZEN at `compile_scan e23e351c…` | `reports/sxt-027/EVIDENCE.md` |

Registry: `docs/frozen-artifact-basis.json` (human index:
`docs/frozen-artifact-basis.md`). Each entry names the exact JSON path, the
frozen value, the live value it is superseded by, the reason, and what
retires the freeze.

**Why option (b) for every one of them, and not (a) re-emission.** The
acceptance rule for (a) is "regenerated **with every dependent recorded
sha256 updated in the same change**". None of the six can satisfy that here:

* **SXT-025 image** — re-emission itself is trivial and verdict-neutral
  (control D1: exactly four fields move, and the fields `IntegrationRun`
  reads are byte-identical). But the digests this leaf records for the image
  are stamps of the **oracle-gated** extraction run
  (`model/integration/extract_preset_inputs.py`, which loads the preset in
  the pinned engine). `import surgepy` fails here, so re-deriving them is
  **NOT_RUN**; hand-editing them would falsify a run stamp, and re-emitting
  without them would leave the chain further out of date.
* **SXT-025 NC-A control** — not independently emitted at all. It is written
  by `model/integration/negative_controls.py::nc_a` from a deep copy of the
  committed image (control D3: it carries the image's own `body_sha256`), so
  its basis follows the image by construction.
* **SXT-026 image** — re-emission is **NOT_RUN (BLOCKED on the pinned
  oracle asset tree)**. Control D2: compiling without `--asset-root` makes
  the basis current while **deleting** `derived.wavetable_asset_manifests`,
  the embedded manifest that the leaf's end-to-end asset-identity evidence
  verifies. Weakening the leaf to refresh a provenance stamp is not a
  re-basing.
* **SXT-027 trio** — generator-run stamps over content #239 did not move.
  Two of the three are pinned `STRUCTURAL_INPUTS` of
  `tools/publish_coverage.py`, so re-emitting them is an SXT-027 leaf-ledger
  revision plus a `reports/coverage-v1/` republication — re-deriving a leaf
  ledger as a side effect of a stamp refresh, which #246's stop/escalate
  clause forbids.

**Stop/escalate did not fire on a verdict.** No re-emission was performed,
so no exactness verdict was re-baselined. The one verdict-adjacent
consequence of this change is mechanical and recorded: editing
`reports/sxt-026/EVIDENCE.md` moves its sha256, so its pin in
`reports/coverage-v1/leaf-verification.json` is revised and
`reports/coverage-v1/` republished in the same commit — a republication in
which `per-preset.csv` is byte-identical and only the recorded input sha256
moves (coverage claim delta **0**).

## Machine check

`tests/test_frozen_artifact_basis.py` (18 tests). Three assertions carry the
weight:

1. **each frozen artifact still records exactly its declared value** — a
   silent re-emission FAILS (control C2);
2. **each named live basis, re-derived live, still equals the value the
   declarations are superseded by** — mutating the live `params_digest`
   FAILS (control C1), as does a move in the live compile-scan digest
   (control C3). This is what makes the *next* basis move force a fresh
   per-artifact decision instead of silent accumulation;
3. **no other machine record carries a frozen value unregistered** — a newly
   generated artifact cannot quietly inherit the retired basis (control C4).

Plus: every entry must be declared in its owning leaf's EVIDENCE naming the
artifact, the frozen value and the registry (control C5), every basis must
have a live re-derivation in the audit, and a "frozen" value that equals the
live value is refused (an entry that is really current must be retired, not
left in the registry).

## Controls (live; each demonstrably fails the check it targets)

`artifacts/controls.txt` — C0 baseline PASS, C1–C5 each FAIL the targeted
assertion and were reverted, plus the D1–D3 disposition transcripts. Every
control mutated one file and was reverted; the tree was clean afterwards.

## Status table

| Check | Status |
|---|---|
| Per-artifact disposition recorded for all six | **PASS** |
| Freeze declared in each owning leaf's EVIDENCE | **PASS** (`tests/test_frozen_artifact_basis.py::test_each_freeze_is_declared_in_its_leaf_evidence`) |
| Machine check for the chosen disposition exists and is live | **PASS** (18 tests) |
| Failure control: live `params_digest` mutation FAILS the check | **PASS** (C1) |
| Failure control: artifact drifting off its declared basis FAILS | **PASS** (C2) |
| Re-emission of the SXT-025 image + its dependent digests | **NOT_RUN** (oracle `surgepy` unavailable) |
| Re-emission of the SXT-026 image | **NOT_RUN** (pinned asset tree unavailable) |
| `reports/sxt-015/EVIDENCE.md` §8.5 STALE records dispositioned | **PASS** (both bullets carry the disposition and point at the registry) |
| Pre-existing SXT-025 image-digest chain drift (pre-`65a4b52`) | **STALE** — recorded in `reports/sxt-025/EVIDENCE.md`, out of scope for #246 |

## What this record does NOT establish

- Nothing about any leaf's RTL-vs-model or model-vs-reference verdict: the
  freezes were chosen precisely because no leaf claim reads the moved term.
- No statement that the frozen artifacts are *correct* — only that the basis
  they quote is superseded on purpose, at a named value, with a named
  retirement path.
- No cycle, area, technology, timing, synthesis, fidelity, preset-support or
  preset-quality claim, and no profile freeze. Supported-preset delta **0**.
- Not a currency guarantee: a reader who needs an artifact on the live basis
  must run its `retired_by` procedure. The audit says the freeze is
  *declared*, never that it is *desirable*.

## Reproduce

```sh
python3 -m pytest tests/test_frozen_artifact_basis.py
python3 -m pytest tests/test_sxt025_integration.py tests/test_sxt029_publication.py
python3 tools/compile_backlog_dag.py --check
```

## Licensing / provenance

`docs/frozen-artifact-basis.{json,md}`,
`tests/test_frozen_artifact_basis.py` and everything under
`reports/frozen-artifact-basis/` are original to this repository
(Apache-2.0 per `LICENSE`); Python stdlib only, importing this repository's
own SXT-015 accounting model. No Surge-derived code, tables or assets are
involved, and nothing in this change reads the pinned GPL engine.
