# Tooling audit — the wavetable renderer's private `render_bus` folded onto the shared one (issue #663)

Branch: `feature/issue-663` · Issue: #663 (Hermit simplification, autonomous
parallel-drift pass; revised by Curator against Champion send-back
`champion:revise:body-828605689917def8`) · Date: 2026-11-14 · Base:
`origin/main` @ `83bbc5a`.

**Claim discipline.** This record covers a source change plus static and
stub-level measurement. It makes **no** fidelity, RTL-exactness, coverage,
synthesis, place-and-route, hardware or musical-quality claim, and it
re-renders nothing: no committed SXT-026 reference WAV, sidecar or verdict is
re-derived, re-graded or relabelled. The pinned oracle is not available on the
host that produced this record, so every question that needs an engine render
is reported `NOT_RUN`, not answered. The finding this change resolves is
**duplication**, explicitly *not* a defect: it is not claimed, here or
anywhere, that the two loops ever produced different audio.

## What changed

`tools/render_wt_reference.py` carried a private `render_bus()` that was
`tools/_render_reference_common.render_bus()` with a different constructor
call. Extracting both bodies with `ast.get_source_segment` and diffing them
whitespace-normalized on `origin/main` @ `83bbc5a` leaves exactly **five**
difference sites (re-derived independently for this record, not read back from
the issue body):

| site | `tools/render_wt_reference.py` (before) | `tools/_render_reference_common.py` (before) |
|---|---|---|
| signature | `(surgepy, oc, seq, overrides, repeats=1, preset_rel=fc.PRESET_REL)` | `(surgepy, oc, fc, seq, carrier, repeats=1)` |
| instance | `fc.build_instance(surgepy, oc, overrides, preset_rel)` | `fc.build_instance(surgepy, oc, carrier)` |
| pre-init | *(absent)* | `total_blocks = 0` / `total_samples = 0` before the loop |
| dispatcher | `rf.dispatch(...)` (module-level `import render_fixture as rf`) | `dispatch = shared_dispatch()` resolved inside the loop |
| hashing | hashes every repeat **twice** | hashes once into `hashes`, reused for both |

plus one cosmetic difference inside the constructor hunk (the loop variable `r`
vs `_r`). Controller reset, settle, tail, block quantization, the event loop,
the mono fold and the clip count are byte-identical after whitespace
normalization, and both dispatcher forms resolve to the same
`fixtures/render_fixture.dispatch`.

Three edits remove the duplicate:

1. **`tools/_render_reference_common.render_bus` now takes a zero-argument
   instance factory**: `render_bus(seq, make_instance, repeats=1)`, replacing
   `(surgepy, oc, fc, seq, carrier, repeats=1)`. Measured: inside that body
   `fc.` resolves only to `['fc.build_instance']`, `oc.` to `[]`, and `surgepy`
   only to the two `fc.build_instance` argument positions — all three
   parameters were reachable *only* through the constructor call, so one
   factory replaces all three. Its existing caller,
   `run_reference_renderer`, now passes
   `lambda: fc.build_instance(surgepy, oc, args.carrier)`.
2. **`tools/render_wt_reference.py` delegates.** Its private `render_bus` and
   its one-line `sha256_file` wrapper are deleted, along with the now-unused
   `import render_fixture as rf`, `hashlib` and `numpy` imports; `main()` calls
   the shared `render_bus` with
   `lambda: fc.build_instance(surgepy, oc, overrides, inputs["preset_path"])`
   and takes `oc.sha256_file(wav_path)` directly. `main()` itself — its
   `--inputs` / `--original` arguments, blob gate and every sidecar field — is
   unchanged.
3. **`tests/test_shared_event_dispatcher.py` records the file's new
   disposition** (see below).

`fixtures/render_fixture.py` is imported, never edited: its bytes are
unchanged, so the committed records stamping them still resolve.

### Why `fc.PRESET_REL` going unused in this file is not a behaviour change

`fc.PRESET_REL` appeared in `tools/render_wt_reference.py` exactly once, as the
default of the deleted signature's `preset_rel` parameter. `main()` always
passed `inputs["preset_path"]` explicitly, on both the `--original` and the
declared-fixture path, so that default was never reachable from the CLI. The
name stays defined in `model/oscillators/wavetable/fixture_config.py:23` for
its other consumers (20 files reference it).

## The pin this change had to move, and why it is not a weakening

PR #659 (issue #640) added `tools/render_wt_reference.py` to the `FOLDED`
tuple of `tests/test_shared_event_dispatcher.py`, where
`test_folded_renderer_calls_the_shared_dispatcher` asserts the file calls a
`dispatch(...)` and mentions `render_fixture`. After the fold the file calls no
dispatcher at all — the dispatch happens one level down, inside the shared
`render_bus` — so that test would fail. **Measured post-fold, not predicted:**

```
tools/render_wt_reference.py
  _dispatch_call_names      -> []
  'render_fixture' in src   -> True
  _event_api_calls          -> []

test_folded_renderer_calls_the_shared_dispatcher:
  -> FAILS assertion 1: "tools/render_wt_reference.py no longer calls a shared
     dispatch(); #640 folded it onto fixtures/render_fixture.py"
  -> assertion 2 ('render_fixture' in src) would have passed VACUOUSLY, on the
     module docstring alone:
       tools/render_wt_reference.py:14: render_fixture.py): fresh instance per render, …
       tools/render_wt_reference.py:20: `render_fixture.dispatch`, so every event type …
```

So relaxing assertion 1 was rejected: assertion 2 already passes on a docstring
mention, and a relaxed assertion 1 would pass for any file that merely names
`render_fixture`, leaving no real pin. Dropping the file from `FOLDED` with no
replacement was rejected (it loses the #640 pin, and that table's own comment
forbids a silent departure); moving it to `EXEMPT` was rejected (`EXEMPT` means
"still carries a private note dispatch", which is false here).

Instead the file moves to a third registry, `FOLDED_VIA`, for a file folded
*transitively*, and a new test
`test_transitively_folded_renderer_keeps_no_render_loop` pins five properties
per entry: the named harness is itself in `FOLDED`; the harness exposes the
`render_bus` being delegated to; the file imports it; the file actually calls
`render_bus`; and the file retains no loop of its own — no `dispatch`, no
`createMultiBlock`, no `processMultiBlock`.
`test_folded_renderer_keeps_no_private_event_dispatch` and
`test_exempt_renderers_are_exactly_the_documented_set` were both widened to
cover `FOLDED_VIA`, so `playNote`/`releaseNote` absence stays pinned
throughout. The net pin on this file moves from "calls `dispatch` directly" to
the strictly stronger "has no render loop at all, and delegates to a file that
does".

**The new pin is live, not decorative.** Each leg was made to fail on a
deliberate violation of the folded file (mutating its source in memory,
leaving the tree untouched):

| Mutation of `tools/render_wt_reference.py` | `test_transitively_folded_renderer_keeps_no_render_loop` |
|---|---|
| re-adds a private `rf.dispatch(...)` call | FAILS — "dispatches events itself again" |
| stops importing the harness | FAILS — "does not import `_render_reference_common`" |
| imports the harness but never calls `render_bus` | FAILS — "imports … but never calls render_bus" |
| re-adds a `createMultiBlock` call | FAILS — "calls ['createMultiBlock'] directly, so it has a private render loop again" |
| harness removed from `FOLDED` (registry leg) | FAILS — "delegates to … which is not in FOLDED: the transitive pin would rest on an unpinned file" |

## The new behavioural test and its failure controls

`tests/test_shared_render_bus_fold.py` (new) drives the one surviving loop with
a **recording stub synthesizer** — no oracle, no engine, no audio. It does not
import `fixtures/render_fixture.py` (which enforces the manifest-pinned
interpreter at import time); it compiles that module's `dispatch` from its
committed bytes in isolation, the technique
`tests/test_shared_event_dispatcher.py` already uses.

What it pins:

- **The loop policy, against hand-computed literals**, not re-derived from the
  code: with block size 32, `settle_s` 0.01 and `tail_s` 0.01 over a three-event
  sequence ending at t=1000, the loop must make exactly the recorded sequence —
  the five RESET calls plus `allNotesOff`, `getBlockSize`, a 15-block settle
  allocated *and processed*, a 47-block render span, and the three events
  dispatched at blocks 0, 10 and 32 with segment processing `(0,10)`, `(10,22)`,
  `(32,15)`. `note_off` carries its **declared** velocity 90, not 0.
- **The claim the fold rests on**: a wavetable-shaped factory
  (`(surgepy, oc, overrides, preset_rel)`, 4 constructor arguments) and a
  classic-shaped factory (`(surgepy, oc, carrier)`, 3) drive that loop to the
  *same* call sequence and the *same* seven `info` keys. The two shapes are
  asserted to really differ, so the test cannot pass by driving one shape twice.
- **`info` key equality**: both renderer families build
  `blocks`, `frames`, `peak_abs_float`, `clipped_samples`, `repeats`,
  `repeat_hashes`, `bit_identical_repeats` — same keys, same order. This is what
  makes "the wavetable sidecar's `{"sample_rate": SR, **info}` spread is
  unchanged" a checkable criterion rather than an assurance.
- **Fresh instance per repeat**: the factory is called once per repeat and each
  repeat drives a distinct instance.

**Failure controls.** Each control is the harness's *real* loop body with one
policy line replaced, compiled from `tools/_render_reference_common.py`'s own
committed bytes — not a hand-written straw man. If a mutated line is ever
reworded the control asserts on its own target's uniqueness and fails loudly
rather than rotting into a vacuous pass. A no-op mutation is also exercised, so
a control that failed for an unrelated reason (a missing name in the exec
namespace, say) could not masquerade as a biting control. Observed:

```
=== POSITIVE: the real shared render_bus ===
  assert_loop_policy                -> PASS
  assert_fresh_instance_per_repeat   -> PASS

=== FAILURE CONTROL: settle skipped ===
  -> FAILS as required, at test_shared_render_bus_fold.py:278
     assert log == EXPECTED_CALLS

=== FAILURE CONTROL: tail dropped ===
  -> FAILS as required, at test_shared_render_bus_fold.py:278
     assert log == EXPECTED_CALLS

=== FAILURE CONTROL: instance shared across repeats ===
  -> FAILS as required, at test_shared_render_bus_fold.py:256
     assert len(seen) == repeats
     the loop called the instance factory 1 times for 3 repeats; one fresh
     instance per repeat is the policy
```

The tail control additionally names its specific loss (span shrinks from 1480
frames / 47 blocks to 1000 / 32), so it cannot start passing for an unrelated
reason.

**One control's reach is recorded rather than overstated.** The
shared-instance control is **invisible to the call log**: a reused instance
still runs the full reset/settle/render body on every repeat, so the recorded
sequence is identical either way. Instance sharing is caught only by the
per-instance assertion, which is why that policy has its own assertion and its
own control. The test asserts that invisibility explicitly, so if it ever
changes, which assertion catches sharing is re-derived rather than assumed.

## `--help` is unchanged

`tools/render_wt_reference.py --help` output is **byte-identical** before and
after the fold, compared with `sys.argv[0]` held equal across both runs (an
earlier comparison differed only in argparse's usage-line wrapping, an artifact
of the temporary filename used to host the pre-fold copy, not of the change).

## The attestation chain

`tests/test_shared_event_dispatcher.py` is line 108 of
`signoff/t1-item9-inventory.json`, and the new test file joins it there, so
editing one and adding the other obliges a re-attestation in the same change —
`tests/test_byte_frozen_sources.py` does not warn about this, and
`.github/workflows/signoff.yml` exits non-zero on the drift. Neither renderer
is in any registry: `tools/render_wt_reference.py` and
`tools/_render_reference_common.py` each appear **0** times in
`docs/byte-frozen-sources.json`, `signoff/t1-item9-inventory.json` and
`signoff/hygiene-inventory.json`, and the wavetable sidecar records no
`script_sha256` / `tool_sha256`, so no committed record resolves against
either file's bytes. That is why the unused `hashlib` / `numpy` imports could
be removed here.

The drift was confirmed before it was fixed: `--attest 9 … --check` against the
committed envelope reported `status: drifted`, exit 3. It was then repaired by
the **surgical count-moving procedure** (`docs/byte-frozen-sources.md`), **not**
by a fresh `klt signoff --attest 9 … -o` run. Measured by reading the blobs
directly (`git show <rev>:<path>`; base = `ebd2ba48`, the merge-base with
`origin/main`; head = `20e113d3`):

1. `signoff/t1-item9-inventory.json` — added
   `tests/test_shared_render_bus_fold.py` to `testbenches`, sorted (232 → 233
   entries, 126 → 127 `tests/test_*.py`).
2. `signoff/t1-item9-attestation.json` — edited in place: check 105
   (`tests/test_shared_event_dispatcher.py`) re-hashed, a new `present` entry
   for `tests/test_shared_render_bus_fold.py` added, `check_count` /
   `passed_count` / `summary` moved 235 → 236, and
   `provenance.input.content_hash` re-derived from the new inventory.
3. `signoff/block-manifest.json` — item 9 `content_hash` updated.
4. `signoff/block-manifest.signoff.json` — re-rendered.
5. `docs/byte-frozen-sources.md` — the registry prose row now reads "233 of 236
   checks: 127 under `tests/`" (`tests/test_byte_frozen_sources.py` requires it).

`klt 0.8.0 signoff --attest 9 … --check` reads `status: match` locally and the
`klt signoff verdict of record` CI check passes at the PR head.

**The manifest's declared `content_hash` is the *inventory*'s digest, not the
envelope's.** The issue body's step 5(c) describes it as "the envelope file's
own sha256"; that is wrong, and `docs/byte-frozen-sources.md` § "Whether
`signoff/block-manifest.signoff.json` also has to be re-rendered" is right.
The base value `sha256:340cafb9…` is the sha256 of
`signoff/t1-item9-inventory.json` at `ebd2ba48`, and the re-rendered report names
`artifact_binding.path = signoff/t1-item9-inventory.json` beside it. The action
is the same — the inventory changed, so both the declared hash and the report
had to move — but the value written is the new inventory's digest.

### What the surgical edit changed, against the stop condition

The issue's stop/escalate condition is "if re-attesting under pinned
`klt 0.8.0` changes a content hash beyond the inventory binding and the new
test's entry, stop and report". It is **not** triggered. The complete diff
between the base envelope (`ebd2ba48`) and the landed envelope (`20e113d3`):

| field | base | landed | disposition |
|---|---|---|---|
| `tests/test_shared_render_bus_fold.py` entry | *(absent)* | added (`sha256:fb5a9766…`) | the new test's entry — allowed |
| `tests/test_shared_event_dispatcher.py` `content_hash` | `sha256:19360551…` | `sha256:c85b8a42…` | the file step 3 edits — in scope |
| `provenance.input.content_hash` | `sha256:340cafb9…` | `sha256:d06910b5…` | the inventory binding — allowed |
| `attestation.check_count` / `passed_count` | 235 / 235 | 236 / 236 | mechanical |
| `summary` | 235/235 | 236/236 | mechanical |
| `provenance.klt_version` | `0.8.0` | `0.8.0` | **unchanged** by this change |

No other per-file `content_hash` changed, and no entry was removed.

**What this change does *not* establish.**

- **`cold_start` was not re-run for this change.** The landed envelope's
  `cold_start` check is byte-identical to the one on `main`; it was carried
  forward, not freshly recorded, and no `cold_start` leg of this change backs
  it. Its status here is **STALE** (carried from `main`'s envelope), not PASS.
  The surgical procedure deliberately does not re-run it.
- **No `klt` producer correction occurred.** The base envelope already carried
  `provenance.klt_version: 0.8.0`; this change leaves it there. The #670 F-1
  defect class (envelopes attested under an undisclosed `klt` dev build) is not
  touched by this change and is not claimed as closed by it.
- **Superseded earlier draft.** A previous revision of this record described a
  full `--attest 9 … -o` re-attestation (225 → 226 / 228 → 229 counts) run under
  a throwaway venv (CPython 3.12.3, `numpy 2.4.2`, `pytest 9.1.1`, `klt 0.8.0`)
  on a host with `iverilog 13.0`. That run is not what landed: none of its
  outputs are in the tree, and nothing above relies on it. The declared
  `iverilog 12.0-2build2` pin is exercised on every PR by `ci.yml`'s `rtl-sim`
  job; coverage of that pin on this host: **none**.

## Verification statuses

| Check | Status | Note |
|---|---|---|
| `pytest tests/test_shared_render_bus_fold.py tests/test_shared_event_dispatcher.py tests/test_t1_item9_inventory_complete.py tests/test_byte_frozen_sources.py` | PASS | 69 passed |
| Failure controls bite (settle skipped / tail dropped / shared instance) | PASS | observed failures quoted above |
| `FOLDED_VIA` pin bites (five legs) | PASS | observed failures tabulated above |
| `tools/render_wt_reference.py --help` unchanged | PASS | byte-identical |
| `python3 -I -m compileall` over the CI path set | PASS | |
| `tools/check_provenance.py`, `check_artifact_manifests.py`, `check_census_consistency.py`, `compile_backlog_dag.py --check` | PASS | unaffected, run for completeness |
| `klt signoff --attest 9 … --check` under pinned `klt 0.8.0` | PASS | `status: match`, `fresh_status: pass`, exit 0 (envelope produced by the surgical procedure, not a fresh `-o` run) |
| `klt signoff --attest 10 … --check` under pinned `klt 0.8.0` | PASS | `status: match`, exit 0; inventory untouched by this change |
| `klt signoff --manifest signoff/block-manifest.json` reproduces the committed report | PASS | byte-identical (`cmp`), grader exit 3 = ran clean, some T1 item unmet |
| `cold_start` full suite inside the item-9 envelope | STALE | carried byte-identical from `main`'s envelope; not re-run for this change (see "What this change does *not* establish") |
| Declared `iverilog 12.0-2build2` pin exercised on this host | NOT_RUN | coverage: none; `ci.yml`'s `rtl-sim` job is where that pin runs |
| Bit-identity of a real wavetable render before/after the fold | NOT_RUN | no pinned oracle on this host |
| Model-vs-reference agreement, RTL-vs-model exactness, preset quality | NO_VERDICT | out of scope; nothing here speaks to them |

## What remains unproved after this lands

Bit-identity of a real wavetable render before and after the fold under the
pinned oracle. The stub test establishes call-sequence and `info`-key equality
only; an oracle-host re-render of one committed SXT-026 reference with a
matching sha256 would establish the stronger claim and is optional follow-up.
Nothing here establishes RTL-vs-model exactness, model-vs-Surge agreement,
original-Surge fidelity, preset coverage or preset quality, and no committed
SXT-026 or SXT-041 record is re-rendered, re-graded or relabelled.
