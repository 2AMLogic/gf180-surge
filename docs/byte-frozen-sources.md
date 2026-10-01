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
again with a live control). The correct disposition of those findings is
**permanently kept, for the reason recorded here** — not "pending cleanup".

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
| Mechanism | `model_revision()` / `frozen_revision()` self-hash, or a `fixtures/control/manifest.json` entry | `script_sha256` / `tool_sha256` stamped into the record the script produced |
| Re-derived at test time? | **Yes** — compared against the committed record | No — written once, at render time |
| Superseded values in the tree? | No. A mismatch *is* a STALE record | Yes, legitimately — and every one of these scripts has already drifted |
| Effect of editing the file | A committed `PASS` record silently becomes STALE | No record is invalidated; the record's provenance digest simply no longer resolves to any file in the tree |
| Correct assertion | live equality (what the audit does) | none — a live-equality assertion would be wrong, and would fail today |

## Live pins

14 pin sites covering 17 files. Digests, the full `recorded_in` record lists,
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

## Historical provenance (NOT byte-frozen)

These scripts stamp a sha256 of their own bytes into the records they produce.
The stamp says *which bytes produced this record*, so superseded values are
expected: as of this registry, **none** of the eight scripts' current bytes
match any committed stamp (`current_bytes_recorded: false` for every entry).
Editing one therefore invalidates no record. What it does cost is resolvability:
the record's provenance digest no longer names any file in the tree, and only a
re-render under the pinned oracle restores that.

| Script | Stamped field |
|---|---|
| `fixtures/render_fixture.py` | `script_sha256` |
| `fixtures/render_lfo_fixture.py` | `script_sha256` |
| `fixtures/render_mw_fixture.py` | `script_sha256` |
| `tools/ablate_fx.py` | `script_sha256` |
| `tools/ablation_delta.py` | `script_sha256` |
| `tools/render_lp12_reference.py` | `script_sha256` |
| `tools/render_reverb_reference.py` | `script_sha256` |
| `tools/listening_session.py` | `tool_sha256` |

`#254`'s source table listed `fixtures/render_fixture.py`,
`tools/render_lp12_reference.py` and `tools/render_reverb_reference.py` as
byte-frozen. Re-derived against the tree, they are not: their recorded stamps
are already superseded. Whether the lint findings in those three may now be
removed is a separate disposition question and is **not** settled by this
registry.

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
