# NumPy stamp inventory — classification of every committed NumPy version stamp

Issue #373 · classification only: no evidence regenerated, no record edited or
re-graded (`git diff` under `reports/` is empty by construction of this issue;
the byte-frozen source registry `docs/byte-frozen-sources.md` lists no file
this change touches).

Parent: #354 (CI Python test dependency pinning), which is blocked on this
classification. Base commit for every count below:
`7f2b1a3110f8b4064d30a4a84f4d335838f47e5a` (2026-10-11; the tree of
`d6ff5b7` — the commit the curator's starting inventory verified against —
plus a Loom resync commit that touches only `.loom/`).

## How to re-derive (repeatable search)

```sh
# canonical enumerator (this repo, stdlib-only, read-only):
python3 tools/numpy_stamp_inventory.py            # lists every stamp
python3 tools/numpy_stamp_inventory.py --check    # audits tree vs this doc
python3 tools/numpy_stamp_inventory.py --json     # machine-readable

# independent cross-check grep (equivalent result: 68 occurrences / 53 files):
git grep -n -i -E 'numpy[a-z_]*"?[[:space:]]*[:=][[:space:]]*"?[0-9]+\.[0-9]+\.[0-9]+|\bnumpy[[:space:]]+[0-9]+\.[0-9]+\.[0-9]+' -- reports/
```

At the base commit the search finds **68 stamp occurrences in 53 files under
`reports/`**, grouping into the 12 record groups below (4 groups were absent
from the issue body's starting enumeration of 5 records: the SXT-028e-sse
host-run record, the sxt-024 #108/#112 precision-pin artifacts, the sxt-013
listening-cache records, and the sxt-010 first-capture record; the curator's
12-record table additionally did not include the `.txt`/`.md` companion echoes
of the JSON records). A repo-wide variant of the grep (same expression over
the whole tree, `reports/` and `oracle/` excluded) returns only prose in
`tests/test_sxt028e_sse.py:840` — a docstring restating the SXT-028e-sse
cross-environment measurements — so `reports/` plus the separate oracle runtime row
below is the complete stamp domain.

Classes, per issue #373:

- **Live** — a CI or acceptance check re-computes the stamp and needs a
  matching environment.
- **Historical provenance** — recorded for the record, never re-checked.
- **Declared cross-environment** — the consumer has an explicit tolerance or
  exclusion mechanism that allows a version difference.

A version difference alone does not make a record STALE; each classification
below cites the traced consumer that justifies it.

## Inventory — `reports/` records

| Group | Stamped files | Version | Class | Consumers / justification (traced) |
|---|---|---|---|---|
| effect-settle-boundary-audit (issue #318) | `reports/effect-settle-boundary-audit/chorus.json`<br>`reports/effect-settle-boundary-audit/distortion_sse.json`<br>`reports/effect-settle-boundary-audit/fx.json`<br>`reports/effect-settle-boundary-audit/phaser.json`<br>`reports/effect-settle-boundary-audit/reverb2.json`<br>`reports/effect-settle-boundary-audit/EVIDENCE.md` | 1.26.4 | Historical provenance | Only test consumer asserts presence, not value: `tests/test_effect_settle_boundaries.py:399-405` requires each record's `environment.numpy` key to be non-empty and checks nothing against the installed numpy. Writer: `tools/audit_effect_settle_boundaries.py:1912`. The second stamp per JSON (line ~46) is the oracle-identity `buildinfo` block, emitted from the oracle's `BUILDINFO.json` by `tools/audit_effect_settle_boundaries.py:984-993`, which compares `engine_commit` and the artifact sha256 against `oracle/manifest.json` — never numpy. No consumer re-computes the value. |
| SXT-028e-sse negative controls | `reports/SXT-028e-sse/negative-controls/negative-controls.json`<br>`reports/SXT-028e-sse/negative-controls/negative-controls.txt`<br>`reports/SXT-028e-sse/EVIDENCE.md` | 2.5.3 (the EVIDENCE prose also names 2.4.2 as a compared environment) | Historical provenance | The consumer never re-checks the stamp value and holds no tolerance keyed to the numpy version: `tests/test_sxt028e_sse.py:883` asserts only that the `numpy` key is present (it may legitimately be null), and the NOT_RUN skip (`tests/test_sxt028e_sse.py:892`) is keyed to the libm-bound stimulus digest — which bounds the recorded *input*, not numpy ("Bounded by the recorded numpy version, not by the digest", `tests/test_sxt028e_sse.py:857`). The cross-version numbers in `reports/SXT-028e-sse/EVIDENCE.md:206-209` are measured regeneration differences from an unmodified tree, not a consumer acceptance budget: Linux/glibc (numpy 2.5.3) leaves every `max_abs_diff_lsb`/`rms_diff_*` and verdict field byte-identical while 12 `spectral_corr` fields move ≤ 8.1e-16 relative — so the record as a whole is not byte-identical; Apple libm (numpy 2.4.2) moves 43 max/rms fields — FX-model-7 legs by up to 12 % relative — plus 12 more spectral fields ≤ 2.3e-16, so the small spectral deltas bound only `spectral_corr`, not all metric fields. The stamp records which numpy build the measured `spectral_corr` fields were taken under (mechanism 2, `reports/SXT-028e-sse/EVIDENCE.md:230-234`). Writer: `tools/distortion_sse_negative_controls.py:213-224` (writes null when numpy is absent — no committed record carries that shape today, but the finder matches it). |
| SXT-028e-sse arm64 host record | `reports/SXT-028e-sse/artifacts-arm64-macos/host-run-record.json` | 1.26.0 (key `numpy_in_pinned_python`) | Historical provenance | No consumer anywhere in the repo: a search for `host-run-record` and `numpy_in_pinned_python` over `tests/`, `tools/`, and `docs/` matches only the record itself. Provenance of the macOS host interpreter that built the arm64 oracle. The alternative key name is why the finder's pattern is `numpy[a-z_]*`, not bare `numpy`. |
| int16-wet-shape-fixture (issue #187 / DR-0017) | `reports/int16-wet-shape-fixture/artifacts/fixture-probe.json`<br>`reports/int16-wet-shape-fixture/artifacts/fixture-probe.txt`<br>`reports/int16-wet-shape-fixture/EVIDENCE.md` | 1.26.4 | Historical provenance | Test consumer asserts verdicts and declared budgets only (`tests/test_pilot_freeze_tail_shape_floor.py:440-459`: overall PASS, shipped budget constants, control outcomes); it never reads the environment block. Writer: `tools/int16_wet_shape_fixture_probe.py:635` (txt echo at :627). |
| pilot-freeze-tail-shape-floor (issue #111 leg / DR-0016) | `reports/pilot-freeze-tail-shape-floor/artifacts/floor-probe.json`<br>`reports/pilot-freeze-tail-shape-floor/artifacts/floor-probe.txt`<br>`reports/pilot-freeze-tail-shape-floor/artifacts/issue-111-leg2-controls-rerun.txt`<br>`reports/pilot-freeze-tail-shape-floor/EVIDENCE.md` | 2.4.2 | Historical provenance | Test consumer asserts verdicts/budgets only (`tests/test_pilot_freeze_tail_shape_floor.py:144-160`); no environment read. Writer: `tools/tail_shape_floor_probe.py:440` (markdown header echo at :433 — the non-JSON stamp shape the issue's test plan calls out). |
| spectral-corr-fs-floor (issue #110) | `reports/spectral-corr-fs-floor/artifacts/checks-summary.json`<br>`reports/spectral-corr-fs-floor/artifacts/dry-parity.txt`<br>`reports/spectral-corr-fs-floor/artifacts/floor-sensitivity.txt`<br>`reports/spectral-corr-fs-floor/artifacts/regrade-ledger-run.txt`<br>`reports/spectral-corr-fs-floor/artifacts/rerender-proof.txt`<br>`reports/spectral-corr-fs-floor/artifacts/tail-gate-controls.txt`<br>`reports/spectral-corr-fs-floor/artifacts/unit-sweep.txt` | 2.4.1 | Historical provenance | The test that reads this record takes only its `base_rev` for merge-base attribution (`tests/test_spectral_corr_fs_floor.py:176-179`); no stamp comparison. Writer: `tools/spectral_corr_fs_floor_checks.py:764` (txt run-header echoes at :669, :773). |
| spectral-corr-per-leaf-migration (issue #165) | `reports/spectral-corr-per-leaf-migration/artifacts/checks-summary.json`<br>`reports/spectral-corr-per-leaf-migration/artifacts/l2-producer-rerun.txt`<br>`reports/spectral-corr-per-leaf-migration/artifacts/l2-rename.txt`<br>`reports/spectral-corr-per-leaf-migration/artifacts/migrated-rerun.txt`<br>`reports/spectral-corr-per-leaf-migration/artifacts/migration-flips.txt`<br>`reports/spectral-corr-per-leaf-migration/artifacts/rename-idempotency.txt`<br>`reports/spectral-corr-per-leaf-migration/artifacts/single-definition-scan.txt` | 2.4.2 | Declared cross-environment | The stamp key is excluded by name from the producer's own record-vs-record comparison: `tools/spectral_corr_per_leaf_checks.py:110-135` lists `numpy` in `RUN_META` — "run metadata that legitimately differs between two runs of the same producer" — and `strip_meta`/`canon` remove it before comparing. That exclusion is scoped to the stamp and run metadata; it does not exempt the record's (potentially numpy-sensitive) metric fields, which the same tool's manual replay legs do compare against regenerated output: leg 2 re-runs the migrated producers in subprocesses and requires canonical equality after the metadata strip (`:180-181`, `:192-197`), and leg 5 records rerun-vs-committed `l2_spectral_corr` relative differences (`:399-405`, `:437-443`, `:458-465`). Those legs run in neither CI nor pytest — the test consumer asserts the shared definition string and leg statuses and explicitly does not re-derive measurements (`tests/test_spectral_corr_single_definition.py:315-337`) — so they bound manual evidence regeneration, not #354's CI pin. |
| stereo-comparator-tail-gate (issue #100) | `reports/stereo-comparator-tail-gate/artifacts/checks-summary.json`<br>`reports/stereo-comparator-tail-gate/artifacts/negative-controls.txt`<br>`reports/stereo-comparator-tail-gate/artifacts/rms-floor.txt`<br>`reports/stereo-comparator-tail-gate/artifacts/spectral-corr-sweep.txt`<br>`reports/stereo-comparator-tail-gate/artifacts/sxt023-sxt024-rerun.txt`<br>`reports/stereo-comparator-tail-gate/artifacts/sxt028c-rerun.txt` | 2.4.1 | Historical provenance | Test consumers assert leg/control statuses and case counts (`tests/test_stereo_tail_gate.py:190-212`) and use the record's `base_rev` for attribution (`tests/test_spectral_corr_fs_floor.py:151-186`); neither reads the stamp. Writer: `tools/stereo_tail_gate_checks.py:1081` (txt echoes at :1102). |
| tail-shape-leg (issue #111) | `reports/tail-shape-leg/artifacts/checks-summary.json`<br>`reports/tail-shape-leg/artifacts/canonical-reruns.txt`<br>`reports/tail-shape-leg/artifacts/landed-verdict-rerun.txt`<br>`reports/tail-shape-leg/artifacts/late-tail-controls.txt`<br>`reports/tail-shape-leg/EVIDENCE.md` | 2.4.1 | Historical provenance | Test consumer asserts issue/overall/budget/leg fields (`tests/test_tail_shape_leg.py:245-262`); no environment read. Writer: `tools/tail_shape_leg_checks.py:487` (txt echoes at :503). |
| sxt-024 precision-pin records (issues #108/#112) | `reports/sxt-024/EVIDENCE.md`<br>`reports/sxt-024/artifacts/issue-108/DIFF.txt`<br>`reports/sxt-024/artifacts/issue-108/WHY-NOT-REGENERATED.txt`<br>`reports/sxt-024/artifacts/issue-112/CONTROL.txt`<br>`reports/sxt-024/artifacts/issue-112/DIFF.txt`<br>`reports/sxt-024/artifacts/issue-112/PRECISION-PROBE.txt`<br>`reports/sxt-024/artifacts/issue-112/TAIL-SHAPE-LEG.txt` | 1.26.4 | Historical provenance | These stamps document the two pre-#112 NumPy regimes under which the committed sxt-024 records were written. The NumPy-sensitive constant they explain (the float32 `send_gain` cube) was made NumPy-independent by #112: the pin is computed with explicit float32 multiplies "independent of the installed NumPy version" (`tests/test_sxt024_reverb1.py:135-160`), and `test_committed_records_carry_the_pinned_send_gain` (:180-213) re-derives `send_gain` from every committed record and requires exact equality — a live consumer that is version-independent by construction, so the stamps themselves are never re-checked. This group is the repo's own precedent for the float32-power hazard noted in `.github/workflows/ci.yml:129-133`. |
| sxt-013 listening cache | `reports/sxt-013/listening-cache/sample-identity-record-fake-renderer.json`<br>`reports/sxt-013/listening-cache/sample-session-fake-renderer.json` | 1.26.4 (key `oracle_python_runtime`) | Historical provenance | The listening-cache consumers (`tests/test_sxt013_listening_cache.py`) check cache validity and apparatus; no test reads the runtime string. The stamps are echoes of the pinned oracle runtime made while recording the fake-renderer listening session. |
| sxt-010 first capture (SXT-010) | `reports/sxt-010/first-capture/first-note.json`<br>`reports/sxt-010/EVIDENCE.md` | 1.26.4 (key `python_runtime`) | Historical provenance | The test that reads `first-note.json` asserts only the historical absence of the `oracle_binding` key (`tests/test_oracle_binding_metadata.py:36-40`); no version comparison. The runtime string is oracle-manifest provenance (SXT-010 leg 1, `reports/sxt-010/EVIDENCE.md:18,30`). |

## Separate row — the oracle evidence runtime (outside the automated search)

| Group | Stamped files | Version | Class | Consumers / justification (traced) |
|---|---|---|---|---|
| Oracle evidence runtime (SXT-010 manifest) | `oracle/manifest.json` | 1.26.4 (with CPython 3.11.16; lines 59, 100, 126) | Live | `oracle/fetch-and-build.sh:85` reads the manifest's numpy pin and `oracle/fetch-and-build.sh:126-127` requires the built venv to satisfy `numpy.__version__ == pin` exactly, at oracle build time. This is the only live NumPy equality check in the repository. It is scoped to constructing the pinned oracle venv — **not a CI pin and not a CI obligation**: it never constrains the numpy that CI installs for pytest, and #354 must not record its CI pin into `oracle/manifest.json` (the oracle runtime stays CPython 3.11.16 / numpy 1.26.4, per the manifest's own rationale at line 59). |

## Live-class conclusion for #354

**No `reports/` record is Live: zero committed NumPy stamps are re-computed
or compared by CI or by any pytest acceptance check.** Traced outcome per
consumer family:

- presence-only assertions (settle records, SXT-028e-sse),
- explicit run-metadata exclusion of the stamp key, plus manual
  environment-sensitive replay legs (per-leaf migration),
- deliberately NumPy-independent live re-derivation (sxt-024 `send_gain`),
- libm-bound digest re-derivation that skips off-host (SXT-028e-sse),
- structure/verdict assertions that never open the environment block
  (int16/pilot-freeze, fs-floor, stereo, tail-shape-leg, sxt-013, sxt-010),
- no consumer at all (host-run-record).

Therefore **there is no conflict: no stamp constrains #354's CI pin**, and
#354 can pick the pin on the test suite's own numeric needs. Context for that
choice, recorded here so it is not re-derived: both CI jobs install numpy
**unpinned** today (`.github/workflows/ci.yml:134` for `tests`,
`:165` for `rtl-sim`), numpy is required because tests import
`model/effects/reverb1/coefficient_plane.py`, and the float32 `power`
divergence across NumPy majors is why a numpy-optional fallback was rejected
(`.github/workflows/ci.yml:129-133`). Two distinct obligations must not be
conflated here. (a) *Stamps*: no CI job or pytest acceptance check compares
any committed stamp value against the installed numpy, so no stamp constrains
#354's pin and a stamp difference alone can never gate CI. (b) *Numeric
replay*: the repo does compare committed records against live-computed
metrics — in one manual evidence tool, `tools/spectral_corr_per_leaf_checks.py`
(the issue #165 transcript): its leg 2 re-runs the two migrated producers in
subprocesses (`:180-181`) and requires canonical equality against the
committed records after stripping `RUN_META` (`:192-197`), and its leg 5
re-runs the renamed L2 producers from committed inputs and records
rerun-vs-committed `l2_spectral_corr` relative differences (`:399-405`,
`:437-443`, `:458-465`). The `numpy`-key exclusion covers the stamp and run
metadata only — it does not exempt numpy-dependent metric fields — so leg 2's
exact replay equality is environment-sensitive: regenerating that evidence
under a different numpy than the stamped 2.4.2 must expect a visible leg-2
FAIL/NOT_RUN, not a silent re-grade. Neither leg is invoked by CI or pytest
(`tests/test_spectral_corr_single_definition.py:315-337` asserts the
committed summary's structure and explicitly does not re-derive
measurements), so these replay obligations bound manual evidence
regeneration, not #354's CI pin. No bounded finding is required.

## Failure control (automated)

`tools/numpy_stamp_inventory.py --check` (stdlib-only, read-only) and
`tests/test_numpy_stamp_inventory.py` enforce this doc against the tree:

- a stamped file under `reports/` missing from the table above → FAIL
  (demonstrated by `test_scratch_injected_stamp_fails_the_audit`, which
  injects `reports/scratch-control/injected.json` with a fabricated
  `"numpy": "9.9.9"` stamp into a scratch copy and requires the audit to flag
  it);
- a table row claiming a `reports/` path that no longer stamps → FAIL
  (stale rows);
- a row whose class is not exactly one of the three classes → FAIL
  (demonstrated by `test_unclassified_row_fails_the_audit`);
- the oracle runtime row must be present, classified Live, with its
  oracle-build scope stated (`test_oracle_runtime_is_a_separate_live_row_not_a_report_record`).

No committed record carries a null stamp today, but the finder matches
`"numpy": null` (the shape `tools/distortion_sse_negative_controls.py:213-215`
writes when numpy is absent) so such a record cannot be added silently either.
