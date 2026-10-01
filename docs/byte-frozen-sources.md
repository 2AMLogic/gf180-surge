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
| Mechanism | `model_revision()` / `frozen_revision()` self-hash, or a `fixtures/control/manifest.json` entry | `script_sha256` / `tool_sha256` stamped into the record the script produced |
| Re-derived at test time? | **Yes** — compared against the committed record | No — written once, at render time |
| Superseded values in the tree? | No. A mismatch *is* a STALE record | Yes, legitimately — and every one of these scripts has already drifted |
| Effect of editing the file | A committed `PASS` record silently becomes STALE | No record is invalidated; the record's provenance digest simply no longer resolves to any file in the tree |
| Correct assertion | live equality (what the audit does) | none — a live-equality assertion would be wrong, and would fail today |
| Lint-finding disposition | **permanently kept** (#147 / PR #152, #252) | **cleanable as ordinary code** (#269) |

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

| Script | Stamped field | Lint-finding disposition (#269) |
|---|---|---|
| `fixtures/render_fixture.py` | `script_sha256` | cleanable — the F841 `preset_slug` finding was cleaned in #269 |
| `fixtures/render_lfo_fixture.py` | `script_sha256` | cleanable — no finding as of #269 |
| `fixtures/render_mw_fixture.py` | `script_sha256` | cleanable — no finding as of #269 |
| `tools/ablate_fx.py` | `script_sha256` | cleanable — no finding as of #269 |
| `tools/ablation_delta.py` | `script_sha256` | cleanable — no finding as of #269 |
| `tools/render_lp12_reference.py` | `script_sha256` | cleanable — the two F401 `struct`/`zlib` findings were cleaned in #269 |
| `tools/render_reverb_reference.py` | `script_sha256` | cleanable — the two F841 findings (`bs`, discarded `save_trace` return) were cleaned in #269 |
| `tools/listening_session.py` | `tool_sha256` | cleanable — no finding as of #269 |

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
files further from the digests their records carry. That buys no new loss here,
because **resolvability is already spent** — all eight read
`current_bytes_recorded: false` both before and after #269's cleanup (re-derived
in the same change), so no edit can take a resolvable provenance stamp and make
it unresolvable. Only a re-render under the pinned oracle restores
resolvability, and it restores it from whatever bytes exist at render time;
holding a dead local variable in place does not bring that re-render any closer.

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
