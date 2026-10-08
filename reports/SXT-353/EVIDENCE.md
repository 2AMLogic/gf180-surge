# SXT-353 evidence: voice-scope coverage ledger reconciliation (issue #353)

Scope: bookkeeping reconciliation of the SXT-029 selected voice leaf with the
landed SXT-026a (#48) evidence. No oracle render, no budget change, no
fidelity-freeze decision. Coverage is reported separately from agreement.

## Change
- `reports/coverage-v1/leaf-verification.json`: `voice_leaf_key`
  `voice:attacky-slice` -> `voice:sine-fm-lp24-v2`; removed the redundant
  unlanded `fx:SXT-026a-voice-scope-extension` entry (landed record is the v2
  voice entry; its pins are unchanged and verified live).
- `tools/publish_coverage.py`: the supported-set note is derived from the
  selected leaf (no unconditional "two in-slice presets" text).
- `tools/coverage_negative_controls.py`: counterfactual `verified_scope` now
  follows `voice_leaf_key`; two new controls added.
- Republished `coverage.json`, `per-preset.csv`; README reconciled (headline
  counts, F-1 wording, leaf ledger, 24 open leaves matching coverage.json);
  `negative-controls.txt` regenerated.
- Neither edited tool is in the byte-frozen registry.

## Headline counts (3,561 entries, all represented)
| status | before | after |
|---|---:|---:|
| supported | 0 | 0 |
| adapted | 165 | 164 |
| unsupported | 1,132 | 1,132 |
| unresolved | 2,264 | 2,265 |

Fidelity freeze remains BLOCKED; supported stays 0; adapted never supported.

## Changed rows (CSV diff: exactly 2 of 3,561)
1. `Rozzer/Bells/Hell's Bells.fxp`: adapted -> unresolved. voice_leaf_gate
   NOT_RUN -> NO_VERDICT. Reasons before: `adapted_edit:sxt025_F1_voice_boundary`,
   `fidelity_freeze_pending`, `voice_leaf_scope_exceeded`. After:
   `f1_resolved:SXT-026a-original-voice-stage(fixture-verified;#48)`,
   `fidelity_freeze_pending`,
   `voice_leaf_caveat:model-vs-reference-NO_VERDICT-vs-proposed`. The missing
   fidelity qualification stays explicit (NO_VERDICT, freeze #12).
2. `Zoozither/Leads/Quickspit.fxp`: status unchanged (unresolved); reason
   `voice_scope_unfixture_verified:Quickspit(F-1-arithmetic-overlap-only)` ->
   `voice_leaf_scope_exceeded:outside-fixture-verified-set(...)`, because v2
   records Quickspit's overlap row as corrected (engine-refused mono playmode).
Attacky: row unchanged. v1 and v2 both record RTL PASS / model-vs-reference
NO_VERDICT and list Attacky fixture-verified, so no class-wide verdict was
transferred to a new scope. The historical SXT-025 dry-bus diagnostic record is
untouched; only its use as a classification is superseded.
Other coverage.json deltas: bank/contributor adapted 145->144, unresolved
1700->1701, voice gate NO_VERDICT 1, ledger entry removed, pin sha of the table.

## Verification (statuses)
- `python3 tools/publish_coverage.py` twice-equivalent: PASS (baseline at
  origin/main reproduced byte-identically before editing; republished output
  matches test).
- `uvx pytest -q tests/test_sxt029_publication.py tests/test_byte_frozen_sources.py`:
  33 passed, exit 0 (pytest via throwaway uvx env; host tools unchanged).
- `python3 tools/coverage_negative_controls.py`: exit 0, RESULT PASS, 7 controls
  (transcript `reports/coverage-v1/negative-controls.txt`):
  - existing NC-STALE-HASH, NC-STALE-MISSING, NC-ROW-MISSING, NC-SHA-DISAGREE,
    NC-RNG-EXCLUSION: PASS.
  - NC-F1-ORIGINAL-STAGE: removing Hell's Bells fixture verification restores
    adapted + `adapted_edit:sxt025_F1_voice_boundary`: PASS.
  - NC-VOICE-PIN-CORRUPT: corrupt v2 evidence pin in the verified-world
    counterfactual: supported 1682 -> 0, all voice gates STALE: PASS.

## Not proved
Fidelity, preset support, listening quality, hardware/synthesis: NOT_RUN /
unestablished. model-vs-reference remains NO_VERDICT (F-48a/F-48b -> #12).
