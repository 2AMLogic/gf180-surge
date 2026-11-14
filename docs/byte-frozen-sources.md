# Byte-frozen source files

**Do not edit a file listed under "Live pins" below — not even to remove an
unused import, fix a typo in a comment, or reflow whitespace.** A sha256 over
its exact bytes is recorded inside committed evidence, and a test re-derives
that digest from the current bytes on every run. Any byte change turns a
committed `status: PASS` record STALE, and the only way to restore it is to
re-run that leaf's comparator and negative-control tooling (and, for the
fixture renderers, the pinned Surge oracle) and re-commit every record the
registry lists.

Machine-readable registry: [`docs/byte-frozen-sources.json`](byte-frozen-sources.json).
Audit: `tests/test_byte_frozen_sources.py` (recomputes every digest, rediscovers
every pin site from the tree, and fails if the registry has drifted).

**What this registry is and is not.** It is evidence bookkeeping: it records
which bytes a committed record pins. It establishes nothing about RTL
exactness, model-vs-reference agreement, or preset quality — those claims live
in the leaf reports and are unaffected by this file.

## Why this file exists

The rule was written down only in a commit message (`2b268c7`, PR #152). Nothing
in the tree said so, so a routine `ruff check` / pyflakes run surfaces unused
names in these files and the same set of removals has been proposed twice and
declined twice (#147 / PR #152, reverted after a Judge block; #252, declined
again with a live control). For a file under [Live pins](#live-pins) the
correct disposition of those findings is **permanently kept, for the reason
recorded here** — not "pending cleanup". The declines swept in three scripts
that are *not* live pins; #269 separates them out and records the opposite
disposition for that class (see
[Disposition of the lint findings in these eight scripts](#disposition-of-the-lint-findings-in-these-eight-scripts-269)).

A live control run while #252 was open: removing the unused `D_LP, D_LPINV`
import from `distortion_model.py` failed 3 tests in `tests/test_sxt028e.py`,
while removing `import sys` from `galactic_model.py` moved `frozen_revision()`
from `569bff13caa7dad8…` to `76efad1cf08fb1b4…` with **zero** test failures.
That CI gap (#254) is now closed from two directions: `tests/test_sxt028a.py`
compares the SXT-028a records against the live `frozen_revision()`, and
`tests/test_byte_frozen_sources.py` re-derives every pin in the registry.

## Two classes of recorded digest — never conflate them

| | Live pin | Historical provenance |
|---|---|---|
| Mechanism | `model_revision()` / `frozen_revision()` self-hash, a `fixtures/control/manifest.json` entry, or a plain sha256 row in a committed evidence table (SXT-043 `fixture_config.py`) | `script_sha256` / `tool_sha256` stamped into the record the script produced |
| Re-derived at test time? | **Yes** — compared against the committed record | No — written once, at render time |
| Superseded values in the tree? | No. A mismatch *is* a STALE record | Yes, legitimately — and every one of these scripts has already drifted |
| Effect of editing the file | A committed `PASS` record silently becomes STALE | No record is invalidated; the record's provenance digest simply no longer resolves to any file in the tree |
| Correct assertion | live equality (what the audit does) | none — a live-equality assertion would be wrong, and would fail today |
| Lint-finding disposition | **permanently kept** (#147 / PR #152, #252) | **cleanable as ordinary code** (#269) |

## Live pins

61 pin sites covering 64 files. Digests, the full `recorded_in` record lists,
and the per-leaf freshness test are in the JSON registry; this table is the
human-readable index.

| Pin site | Covers | Leaf | Freshness test |
|---|---|---|---|
| `model/effects/aw-4/logical4_model.py::model_revision()` | `model/effects/aw-4/logical4_model.py` + `model/effects/aw-4/tables.py` (one hash over both, in that order) | SXT-028k | `tests/test_sxt028k.py` |
| `model/effects/aw-49/galactic_model.py::frozen_revision()` | `model/effects/aw-49/galactic_model.py` | SXT-028a | `tests/test_sxt028a.py` (added by #254) |
| `model/effects/rf-rf-ains34/rf_ains34_model.py::model_revision()` | itself | SXT-028i | `tests/test_sxt028i.py` |
| `model/effects/rf-rf-bins12/rf_bins12_model.py::model_revision()` | itself | SXT-028h | `tests/test_sxt028h.py` |
| `model/effects/rf-rf-global2/rf_global2_model.py::model_revision()` | itself | SXT-028d | `tests/test_sxt028d.py` |
| `model/effects/rf-rf-global34/rf_global34_model.py::model_revision()` | itself | SXT-028j | `tests/test_sxt028j.py` |
| `model/effects/rf-rf-send34/rf_send34_model.py::model_revision()` | itself | SXT-028l | `tests/test_sxt028l.py` |
| `model/effects/type-chorus/chorus_model.py::model_revision()` | itself | SXT-028c | `tests/test_sxt028c.py` |
| `model/effects/type-conditioner/conditioner_model.py::model_revision()` | itself | SXT-028b | `tests/test_sxt028b.py` |
| `model/effects/type-distortion/distortion_model.py::model_revision()` | itself | SXT-028e | `tests/test_sxt028e.py` |
| `model/effects/type-distortion-sse/distortion_sse_model.py::model_revision()` | `model/effects/type-distortion-sse/sse_tables.py` + `model/effects/type-distortion-sse/quad_shapers.py` + `model/effects/type-distortion-sse/distortion_sse_model.py` (one hash over all three, in that order — none of them has an independent pin) | SXT-028e-sse | `tests/test_sxt028e_sse.py` |
| `model/effects/type-phaser/phaser_model.py::model_revision()` | itself | SXT-028g | `tests/test_sxt028g.py` |
| `model/effects/type-reverb 2/reverb2_model.py::model_revision()` | itself | SXT-028f | `tests/test_sxt028f.py` |
| `fixtures/control/manifest.json::files[…]` | `fixtures/control/sequences/generate_control_sequences.py` | SXT-021 | `tests/test_sxt021_control.py` |
| `reports/SXT-043/EVIDENCE.md` provenance table | `model/voice/playmode/fixture_config.py` (revision 2; plain sha256 of its bytes, no self-hash function) | SXT-043 | `tests/test_sxt043_fixture_rev2.py` |
| `signoff/t1-item9-attestation.json` check for `model/integration/negative_controls.py` | `model/integration/negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/aw49_negative_controls.py` | `tools/aw49_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/aw4_negative_controls.py` | `tools/aw4_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/check_provenance_controls.py` | `tools/check_provenance_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/chorus_negative_controls.py` | `tools/chorus_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_aw4.py` | `tools/compare_rtl_model_aw4.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_aw49.py` | `tools/compare_rtl_model_aw49.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_chorus.py` | `tools/compare_rtl_model_chorus.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_conditioner.py` | `tools/compare_rtl_model_conditioner.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_distortion.py` | `tools/compare_rtl_model_distortion.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_distortion_sse.py` | `tools/compare_rtl_model_distortion_sse.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_fx.py` | `tools/compare_rtl_model_fx.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_lp12.py` | `tools/compare_rtl_model_lp12.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_lp24.py` | `tools/compare_rtl_model_lp24.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_lpmoog.py` | `tools/compare_rtl_model_lpmoog.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_phaser.py` | `tools/compare_rtl_model_phaser.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_reverb2.py` | `tools/compare_rtl_model_reverb2.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_rf_ains34.py` | `tools/compare_rtl_model_rf_ains34.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_rf_bins12.py` | `tools/compare_rtl_model_rf_bins12.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_rf_global2.py` | `tools/compare_rtl_model_rf_global2.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_rf_global34.py` | `tools/compare_rtl_model_rf_global34.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/compare_rtl_model_rf_send34.py` | `tools/compare_rtl_model_rf_send34.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/conditioner_negative_controls.py` | `tools/conditioner_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/control_negative_controls.py` | `tools/control_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/coverage_negative_controls.py` | `tools/coverage_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/distortion_negative_controls.py` | `tools/distortion_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/distortion_sse_negative_controls.py` | `tools/distortion_sse_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/fx_rng_negative_controls.py` | `tools/fx_rng_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/kt_negative_controls.py` | `tools/kt_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/lfo_negative_controls.py` | `tools/lfo_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/lp12_negative_controls.py` | `tools/lp12_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/lp24_negative_controls.py` | `tools/lp24_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/lpmoog_negative_controls.py` | `tools/lpmoog_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/mw_negative_controls.py` | `tools/mw_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/phaser_negative_controls.py` | `tools/phaser_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/profile_budget_controls.py` | `tools/profile_budget_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/reverb2_negative_controls.py` | `tools/reverb2_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/reverb2_reference_controls.py` | `tools/reverb2_reference_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/reverb_negative_controls.py` | `tools/reverb_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/rf_ains34_negative_controls.py` | `tools/rf_ains34_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/rf_bins12_negative_controls.py` | `tools/rf_bins12_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/rf_global2_negative_controls.py` | `tools/rf_global2_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/rf_global34_negative_controls.py` | `tools/rf_global34_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/rf_send34_negative_controls.py` | `tools/rf_send34_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/slfo_negative_controls.py` | `tools/slfo_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |
| `signoff/t1-item9-attestation.json` check for `tools/vel_negative_controls.py` | `tools/vel_negative_controls.py` (plain sha256 of its bytes; no self-hash function) | T1 item 9 (#538) | `tests/test_byte_frozen_sources.py` |

The 46 `T1 item 9` rows are testbench and negative-control scripts whose bytes
`signoff/t1-item9-attestation.json` (klt `--attest 9`, #538) records as `content_hash`
values and `signoff.yml` re-checks live. They are live pins like any other row: any
edit, including lint or whitespace, makes that attestation and the item 9 verdict
in `signoff/block-manifest.signoff.json` STALE until both are re-derived in the same
change. They are covered by the audit's live equality check in
`tests/test_byte_frozen_sources.py`; they have no leaf-specific freshness test.
They are 46 of the 225 files that attestation content-hashes — see
[Whole-inventory attestation pins](#whole-inventory-attestation-pins-tests-rtl-benches-hygiene-files)
for the other 179, for the item 10 hygiene files, and for exactly what a
regeneration has to re-commit.

Two of the self-hash pins are also recorded in their RTL traces as a **revision
word** — the low 32 bits, `int(revision[:8], 16)`: SXT-028a's
`cases[].revision_pin.expected == 1453063955` and SXT-028k's equivalent. The
registry lists those records under `recorded_word_in`, and the audit checks that
form too.

`model/effects/type-phaser/phaser_model.py` and
`model/effects/aw-4/logical4_model.py` additionally keep a local
`class Refuse(Exception)` for the same reason — see `refusal.py` and
`tests/test_shared_refuse.py`, whose allowlist is the same freeze seen from the
`Refuse`-consolidation side (#258).

## Whole-inventory attestation pins (`tests/`, `rtl/` benches, hygiene files)

The per-file rows above are **not** the whole set of files whose bytes a
committed record pins. Two `klt signoff --attest` envelopes content-hash *every*
file in an inventory, and `.github/workflows/signoff.yml` re-checks both on every
`pull_request` and on every push to `main`, exiting 3 on any drift:

| Envelope | Inventory — the authoritative list | Content-hashed files | Rest of the envelope |
|---|---|---|---|
| `signoff/t1-item9-attestation.json` | `signoff/t1-item9-inventory.json`, key `testbenches` | 225 of 228 checks: 120 under `tests/`, 59 `rtl/*.sv` benches and mutant controls, 45 `tools/*.py`, and `model/integration/negative_controls.py` | one `cold_start` command check, two `pin` checks |
| `signoff/item-10.attestation.json` | `signoff/hygiene-inventory.json`, key `hygiene` | 5 of 9 checks: `README.md`, `LICENSE`, `.github/workflows/ci.yml`, `.github/workflows/signoff.yml`, `.github/workflows/slow-controls.yml` | four `command` audit checks |

**Read the inventories; this registry does not transcribe them.** The 46
`T1 item 9` rows in the [Live pins](#live-pins) table are only the `tools/` +
`model/` subset the registry audit can discover on its own. The other 179 item 9
files and the five item 10 hygiene files deliberately have no rows there:
enumerating them would duplicate the inventories verbatim and rot on every new
test or bench.

### The obligation is "re-attest in the same change", not "do not edit"

These two obligations are different, and only the first applies to a file that
is in an inventory but has no [Live pins](#live-pins) row:

- **Inventory-only files** (`tests/`, the `rtl/` benches and mutants,
  `README.md`, `LICENSE`, the three workflows) are ordinary editable sources.
  The envelope records that they exist and what their bytes were. Edit them for
  any reason a normal change justifies — then **re-attest the affected envelope
  in the same change**, or CI's `signoff` job goes red.
- **Every file with a [Live pins](#live-pins) row** keeps the stronger rule
  stated at the top of this file: do not edit, and a lint finding inside one is
  permanently kept. Nothing here relaxes that. That covers the 13 `self_hash`
  pins, the two other `manifest_entry` pins (`fixtures/control/manifest.json`
  and the SXT-043 evidence table), and the 46 item 9 rows.

The 46 item 9 rows sit in both camps — they are listed pins *and* they are item 9
inventory entries — so the stronger rule wins for them.

### The registry audit does not fire for inventory-only files

`tests/test_byte_frozen_sources.py` cannot see them, by construction rather than
by a missed regeneration: `discover_recorded_sources()` iterates
`tracked_python()`, which is `*.py` **outside** `tests/` ("a test file is never
pinned"). So `.sv`, `.yml`, `README.md`, `LICENSE` and everything under `tests/`
are excluded by design. **`klt signoff --check` is their freshness check** — the
registry audit is not, and will pass in silence while an envelope is drifted.

### Measured outcomes

Each row appends one comment line to one file, runs the check, and restores the
file. Measured 2026-11-13 in a worktree at `d5ac9f6` with
`uvx --from klayout-tools==0.8.0 klt` and `pytest 9.1.1`; `git status
--porcelain` was empty after every probe.

| File edited | Attested by | `klt signoff --attest N … --check` | `pytest tests/test_byte_frozen_sources.py` |
|---|---|---|---|
| (none — baseline) | — | item 9 `match`, exit 0; item 10 `match`, exit 0 | 28 passed |
| `tests/test_ci_dependency_pins.py` | item 9 | `drifted`, exit 3 (`attestation.checks.67.content_hash`) | 28 passed — **silent** |
| `rtl/control/tb_control.sv` | item 9 | `drifted`, exit 3 (`attestation.checks.2.content_hash`) | 28 passed — **silent** |
| `.github/workflows/ci.yml` | item 10 | `drifted`, exit 3 (`attestation.checks.0.content_hash`) | 28 passed — **silent** |
| `tools/vel_negative_controls.py` (a registry row, for contrast) | item 9 | `drifted`, exit 3 (`attestation.checks.217.content_hash`) | 2 failed, 26 passed |

The `drifted` / exit 3 column is this section's failure control: if any of the
three inventory-only classes had read `match`, the claim above would be wrong.
The last row is the non-vacuity leg — it shows the registry audit is not simply
always silent, it is silent *specifically* for files it has no row for.

### Regenerating either envelope

The `klayout-tools` pin lives only in
[`signoff/requirements.txt`](../signoff/requirements.txt) (`klayout-tools==0.8.0`
as of `d5ac9f6`), the same pin `signoff.yml` installs.

```sh
python3 -m venv /tmp/klt-venv
/tmp/klt-venv/bin/pip install -r signoff/requirements.txt

# item 10 (hygiene) — seconds; its four audit checks are stdlib-only scripts.
/tmp/klt-venv/bin/klt signoff --attest 10 --inventory signoff/hygiene-inventory.json \
    -o signoff/item-10.attestation.json
/tmp/klt-venv/bin/klt signoff --attest 10 --inventory signoff/hygiene-inventory.json \
    --check signoff/item-10.attestation.json

# item 9 (testbenches) — runs the full pytest suite; see the caveat below.
/tmp/klt-venv/bin/klt signoff --attest 9 --inventory signoff/t1-item9-inventory.json \
    -o signoff/t1-item9-attestation.json
/tmp/klt-venv/bin/klt signoff --attest 9 --inventory signoff/t1-item9-inventory.json \
    --check signoff/t1-item9-attestation.json
```

**Item 9 regeneration runs the `cold_start` full suite; `--check` does not.**
Measured: `--attest 9` refuses an inventory with no `cold_start` (exit 1, "item 9
inventory must declare 'cold_start'"), and a regeneration run does execute the
declared `python3 -m pytest -q -p no:cacheprovider tests` with `cwd: .`,
resolving `python3` from `PATH`. A venv holding only `signoff/requirements.txt`
is therefore **not** a sufficient regeneration environment — the suite's own
pinned dependencies (`pytest 9.1.1`, `numpy 2.4.2`, python 3.12, and `iverilog
12.0-2build2` for the RTL cases) must be the ones `python3 -m pytest` picks up,
or `cold_start` fails and the envelope records a failing check. `--check` skips
it and carries the committed outcome (`[SKIP] cold_start … local_only, not run;
committed outcome: pass`), which is why the `signoff` job never pays that cost.
The wall-clock cost of a successful `cold_start` is **not timed by this
section** — treat it as "a full suite run", not as a known number.

`--attest 10 … -o` was verified here to reproduce the committed
`signoff/item-10.attestation.json` byte-for-byte (exit 0). The item 9
regeneration command was exercised far enough to confirm it runs `cold_start`,
not to completion.

### Whether `signoff/block-manifest.signoff.json` also has to be re-rendered

Usually not — and the reason is worth knowing before regenerating anything.
[`signoff/block-manifest.json`](../signoff/block-manifest.json) declares, for
each envelope, a `content_hash` that is the sha256 of the **inventory** the
envelope was produced from, not of the envelope's own bytes
(`sha256:490713ad…` is `signoff/t1-item9-inventory.json`'s own digest). The
rendered report then echoes the envelope's `summary` and its
`check_count` / `passed_count`. Measured both directions:

- Changing the envelope's **bytes** without changing its content (a trailing
  newline) left a fresh `klt signoff --manifest signoff/block-manifest.json
  --format json` render byte-identical to the committed report. So regenerating
  an envelope from an **unchanged** inventory leaves the report alone and there
  is nothing extra to commit.
- Changing the envelope's `summary` string changed exactly that field in a fresh
  render. So anything that moves the envelope's summary or check counts — in
  practice, a change to the **inventory** — does require re-rendering
  `signoff/block-manifest.signoff.json` *and* updating the manifest's declared
  `content_hash`, in the same change.

This sharpens, rather than contradicts, the "until both are re-derived" sentence
in the item 9 paragraph above: an edit to an attested file makes the committed
envelope STALE unconditionally, but the report only has to be re-committed when
the regeneration actually moves bytes the report echoes.

## Historical provenance (NOT byte-frozen)

These scripts stamp a sha256 of their own bytes into the records they produce.
The stamp says *which bytes produced this record*, so superseded values are
expected: of the ten scripts below, **eight** have current bytes that match
no committed stamp (`current_bytes_recorded: false`). Two are exceptions:
`fixtures/render_fixture.py`, re-rendered under the pinned oracle by #126 and
again by #136, and `fixtures/render_slfo_fixture.py`, added by SXT-041 (#75),
whose current bytes are hashed into the reference sidecars it produced
because that leaf's records were rendered from the file as committed — both
detailed below. That flag is bookkeeping about resolvability, **not** a live
pin: no test asserts byte-equality for anything in this table, and an edit to
any of the nine still invalidates no record.
Editing one therefore invalidates no record. What it does cost is resolvability:
the record's provenance digest no longer names any file in the tree, and only a
re-render under the pinned oracle restores that. (The tenth entry is the
degenerate case: `reports/sxt-013/audition-gate/generate-samples.py` stamps no
digest at all — it redacts — so there is nothing to resolve from the start.)

**One of the eight is now resolvable again (#126).** `fixtures/render_fixture.py`
reads `current_bytes_recorded: true`: the SXT-028f Reverb 2 fixture bundles were
re-rendered under the pinned oracle, so `reports/SXT-028f/artifacts/determinism-gate.json`
and the six `reports/SXT-028f/fixtures/*.json` sidecars stamp its current bytes
— and since #136 the fourteen `reports/SXT-028e-sse/fixtures/*.json` sidecars
stamp them too, so the stamp is now resolvable through two independent leaves.
This is exactly the re-render case flagged under
[what the decision does not license](#disposition-of-the-lint-findings-in-these-eight-scripts-269)
— it is **not** a live pin (nothing re-derives the stamp, and the entry still
carries no `sha256` field), but its lint disposition was revisited rather than
assumed, and the #269 "resolvability is already spent" argument no longer applies
to that one entry. The ninth entry is a second, independent exception —
`fixtures/render_slfo_fixture.py`, added by SXT-041 (#75) after #269 and so not
one of its eight; see its own note below. The tenth entry (`reports/sxt-013/
audition-gate/generate-samples.py`, added by #447) also reads `false`: it
writes the samples' `harness.tool_sha256` as the literal placeholder
`<omitted>`, stamping no digest of any file — the audit's heuristic flags it
on the quoted field literal plus `__file__`, and it is declared here with
that nuance rather than restructured around the check. The remaining eight stay `false`.

| Script | Stamped field | Lint-finding disposition (#269; revisited for `fixtures/render_fixture.py` in #126, and stated for `fixtures/render_slfo_fixture.py` in SXT-041 (#75) on the same terms) |
|---|---|---|
| `fixtures/render_fixture.py` | `script_sha256` | cleanable, cost no longer zero — an edit now makes a **resolvable** stamp unresolvable until **both** the SXT-028f (#126) and the SXT-028e-sse (#136) bundles are re-rendered (the F841 `preset_slug` finding was cleaned in #269) |
| `fixtures/render_lfo_fixture.py` | `script_sha256` | cleanable — no finding as of #269 |
| `fixtures/render_mw_fixture.py` | `script_sha256` | cleanable — no finding as of #269 |
| `fixtures/render_slfo_fixture.py` | `script_sha256` | cleanable, cost no longer zero — an edit makes a **resolvable** stamp unresolvable until the SXT-041 (#75) references (the six `reports/SXT-041/artifacts/reference-*.json` sidecars) are re-rendered under the pinned oracle, and fails `test_historical_provenance_carries_no_live_equality_claim` until either that re-render lands or the flag is set `false` in the same change (no finding as of SXT-041) |
| `tools/ablate_fx.py` | `script_sha256` | cleanable — no finding as of #269 |
| `tools/ablation_delta.py` | `script_sha256` | cleanable — no finding as of #269 |
| `tools/render_lp12_reference.py` | `script_sha256` | cleanable — the two F401 `struct`/`zlib` findings were cleaned in #269 |
| `tools/render_reverb_reference.py` | `script_sha256` | cleanable — the two F841 findings (`bs`, discarded `save_trace` return) were cleaned in #269 |
| `tools/listening_session.py` | `tool_sha256` | cleanable — no finding as of #269 |
| `reports/sxt-013/audition-gate/generate-samples.py` | `tool_sha256` | cleanable — ordinary code, per the #269 disposition extended by #447. Not a real stamp site: it writes the samples' `harness.tool_sha256` as the literal placeholder `<omitted>` and stamps no digest of itself; `current_bytes_recorded: false` because no record carries its bytes' digest (added by #447) |

### Disposition of the lint findings in these eight scripts (#269)

**Decided: these eight are ordinary code. A dead-code finding in one of them is
cleanable under the normal rules, with no registry ceremony and no leaf
re-run.** This is an explicit decision, not an inheritance. `#254`'s source
table listed `fixtures/render_fixture.py`, `tools/render_lp12_reference.py` and
`tools/render_reverb_reference.py` as byte-frozen; re-derived against the tree
they are not, so the reason the findings in them were declined in #147/PR #152
and again in #252 — "removing this turns a committed `PASS` record STALE" — is
simply not true of these files. It remains true of every file under
[Live pins](#live-pins), which this decision does not touch.

What the decision costs, stated rather than waved past: each edit moves these
files further from the digests their records carry. For **seven of the eight**
that buys no new loss, because resolvability is already spent — they read
`current_bytes_recorded: false` both before and after #269's cleanup (re-derived
in the same change), so no edit can take a resolvable provenance stamp and make
it unresolvable. Only a re-render under the pinned oracle restores
resolvability, and it restores it from whatever bytes exist at render time;
holding a dead local variable in place does not bring that re-render any closer.

**`fixtures/render_fixture.py` is now the exception** (#126, the SXT-028f
reference leg): that re-render happened, its stamp resolves again, and so an
edit there *does* spend something. The decision stands — it is still ordinary
code and still not a live pin — but clean it in a change that either re-renders
the SXT-028f bundles or says plainly that the stamp stopped resolving. This is
the "does not survive a re-render" clause below, applied rather than deferred.

**The ninth entry inherits the same disposition (SXT-041, #75).**
`fixtures/render_slfo_fixture.py` is ordinary code on the same terms: a lint
finding in it is cleanable with no registry ceremony and no leaf re-run. Its
stamp is currently *resolvable* (`current_bytes_recorded: true`), as
`fixtures/render_fixture.py`'s has been since #126; what differs is the route.
`fixtures/render_fixture.py` regained resolvability by being re-rendered, while
this entry's never lapsed: SXT-041's references were rendered from the file as
committed. Either way the #126 precedent applies — an edit spends that
resolvability, which costs no committed record its validity, and is restored
by re-rendering the SXT-041 references under the pinned oracle; its row in the
table above records that cost.

**The tenth entry inherits the same disposition (#447).**
`reports/sxt-013/audition-gate/generate-samples.py` is ordinary code on the
#269 terms. It is declared only because the audit's self-stamping heuristic
fires on it; it writes no digest of itself, so its stamp has never resolved
and an edit to it spends nothing.

Which counts are #269's: this subsection's heading ("these eight scripts"), its
"seven of the eight" paragraph, and the "eight scripts' own write sites" check
below are #269's ruling over the eight entries that existed when it was made,
and are deliberately not renumbered. The whole-registry counts at the top of
this section — ten entries, eight `false`, two exceptions — describe the
registry as it stands and do move with it.

What this decision does **not** license:

- It is not a licence to edit a [live pin](#live-pins). The two live-pinned
  files that carry unrelated ruff findings today
  (`model/effects/aw-49/galactic_model.py`,
  `model/effects/type-distortion/distortion_model.py`) stay frozen; they need
  the full procedure in
  [If you must edit a live-pinned file](#if-you-must-edit-a-live-pinned-file).
- It does not add a live-equality claim to a provenance entry. A provenance
  entry carries no `sha256` field and asserts no live equality — that is what
  `test_historical_provenance_carries_no_live_equality_claim` enforces, in both
  directions, and doctoring a `current_bytes_recorded` flag to `true` still
  fails it.
- It does not survive a re-render. If one of these scripts' fixtures is ever
  re-rendered under the pinned oracle, its stamp resolves to the tree again;
  that does **not** make it a live pin (nothing re-derives it), but the entry
  should be revisited here rather than assumed still "cleanable" by default.
  **This happened in #126** for `fixtures/render_fixture.py` — see the note on
  its row above for the revisited disposition.

If a consumer is ever found that re-derives one of these stamps and compares it,
that script is a live pin in disguise: move it to `live_pins` and stop cleaning
it. Checked for #269 across tracked `.py`/`.sh`/`.yml` — the only readers of
`script_sha256`/`tool_sha256` are the eight scripts' own write sites and this
registry's audit, which asserts the *absence* of live equality.

## If you must edit a live-pinned file

1. Say which claim the edit serves. A lint finding is not one — see the two
   declined attempts above.
2. Re-run the owning leaf's comparator and negative-control tooling (and the
   pinned Surge oracle where the leaf's records need re-rendering), in the
   environment the records were produced in.
3. Re-commit **every** record listed under that pin's `recorded_in` (and
   `recorded_word_in`) in the **same** change as the source edit, and update
   the pin's `sha256` in `docs/byte-frozen-sources.json`.
4. Record what moved the pin and why — the convention
   `reports/coverage-v1/leaf-verification.json::evidence_pin_revisions`
   already uses (`moved_by`, `decision`) is the model to follow.
5. `python3 -m pytest -q tests/test_byte_frozen_sources.py` plus the leaf's own
   test file must pass before the change lands. A partial re-derivation that
   leaves one record behind is a STALE record reported as PASS, which is worse
   than the finding you were cleaning up.
