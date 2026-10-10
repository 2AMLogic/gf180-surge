# SXT-029 (#432): evidence-backed readiness for every coverage leaf/gate

Scope: component-ledger evidence consumption in `tools/publish_coverage.py`.
Coverage only. No fidelity budget, corpus identity, denominator or product
goal changed; synthetic support in the controls is never product evidence.

## Behavior
- `evidence_state(require=True)`: a readiness claim (landed PASS/PASS leaf,
  PASS gate) with absent/null/empty evidence yields `MISSING` -> gate
  `NO_VERDICT`, reason `leaf_evidence_missing:` / `gate_evidence_missing:`.
  STALE (missing file, digest mismatch) is preserved and takes precedence.
- Malformed evidence shapes REFUSE (exit 2) before any output is written.
- Routing and Airwindows section entries use the same calculation
  (`build_leaf_state`); the `stale=False` fallbacks are gone. An optional
  `canonical_leaf` on a section entry names a record in `leaves`; that
  record's integrity verdict is the entry's. No committed entry declares one.
- Section-local evidence pins are listed in `coverage.json` `inputs`.

## Results (host: python3 present; pytest via `uvx --from pytest`)
| check | status |
|---|---|
| baseline `coverage.json` sha256 882d7435...a27bc, `per-preset.csv` a4d1ec69...efc byte-identical to committed | PASS |
| `tests/test_sxt029_publication.py` + `test_sxt029_control_guard.py` + `test_byte_frozen_sources.py` (58) | PASS |
| `tests/test_negative_controls_live.py` -k coverage/registry (61 passed) | PASS |
| `tests/test_negative_controls_live.py::test_reverb2_cli_subset_records_coverage` | NOT_RUN (numpy absent in the uvx env; unrelated) |
| `python3 tools/coverage_negative_controls.py` (NC-EVIDENCE-READINESS added), exit 0, transcript `reports/coverage-v1/negative-controls.txt` | PASS |
| live control: empty-list shortcut restored | FAILS targeted assertion (healthy) |
| live control: stale=False fallback restored (routing / Airwindows) | each FAILS targeted assertion (healthy) |
| live control: canonical mapping ignored | FAILS targeted assertion (healthy) |

Fixtures (synthetic, scratch): EQ in the all-gates-PASS world: 454 reached
gates, 453 supported victims -> all NO_VERDICT for absent/null/empty
evidence. routing `ains3`: 14 affected -> STALE (hash and missing file, local
and canonical). Airwindows `49`: unreachable in the real corpus (no compiled
preset requires an Airwindows effect), so reached via a declared synthetic
graph mirror enabling the slot on 6 supported presets: 6 affected -> STALE.
Unaffected rows byte-equal in every case.

## Unproved
Byte-frozen registry has no entry for the edited files (checked). Supported
presets in the committed baseline remain 0; this change establishes no
RTL/model/reference fidelity or preset support.
