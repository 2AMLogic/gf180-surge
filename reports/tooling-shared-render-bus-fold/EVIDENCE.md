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
committed envelope reported `status: drifted`, exit 3. Then, in order:

1. `signoff/t1-item9-inventory.json` — added
   `tests/test_shared_render_bus_fold.py` to `testbenches`, sorted (225 → 226
   entries, 120 → 121 `tests/test_*.py`, all unique, globally C-sorted).
2. `signoff/t1-item9-attestation.json` — re-attested with `--attest 9 … -o`.
   228 → 229 checks, 229/229 passed, `cold_start` exit 0.
3. `signoff/block-manifest.json` — item 9 `content_hash` updated.
4. `signoff/block-manifest.signoff.json` — re-rendered.

`--check` now reports `status: match` / `fresh_status: pass` (exit 0) for item
9 **and** for item 10 (whose inventory — `README.md`, `LICENSE`, the three
workflows — this change does not touch), and
`klt signoff --manifest signoff/block-manifest.json --format json` reproduces
the committed report byte-identically.

**The manifest's declared `content_hash` is the *inventory*'s digest, not the
envelope's.** The issue body's step 5(c) describes it as "the envelope file's
own sha256"; that is wrong, and `docs/byte-frozen-sources.md` § "Whether
`signoff/block-manifest.signoff.json` also has to be re-rendered" is right.
Verified directly: the committed value `sha256:198b29f7…` is the sha256 of
`signoff/t1-item9-inventory.json` at `83bbc5a` (the envelope's own bytes hash
to `sha256:c1de5a7d…`), and the re-rendered report names
`artifact_binding.path = signoff/t1-item9-inventory.json` beside it. The action
is the same — the inventory changed, so both the declared hash and the report
had to move — but the value written is the new inventory's digest.

### What the re-attestation changed, against the stop condition

The issue's stop/escalate condition is "if re-attesting under pinned
`klt 0.8.0` changes a content hash beyond the inventory binding and the new
test's entry, stop and report". It is **not** triggered. The complete diff
between the committed and fresh envelopes:

| field | committed | fresh | disposition |
|---|---|---|---|
| `tests/test_shared_render_bus_fold.py` entry | *(absent)* | added | the new test's entry — allowed |
| `tests/test_shared_event_dispatcher.py` `content_hash` | changed | | the file step 3 edits — in scope |
| `provenance.input.content_hash` | `sha256:198b29f7…` | `sha256:251a5215…` | the inventory binding — allowed |
| `attestation.check_count` / `passed_count` | 228 / 228 | 229 / 229 | mechanical |
| `summary` | 228/228 | 229/229 | mechanical |
| `provenance.klt_version` | `0.9.2.dev887+gec7400b7d8e5` | `0.8.0` | see below |

No other per-file `content_hash` changed, and no entry was removed.

**Two disclosures about the producer.**

- **The committed envelope was attested under an undisclosed `klt` dev build**
  (`0.9.2.dev887+gec7400b7d8e5`) rather than `signoff/requirements.txt`'s
  `klayout-tools==0.8.0`. Re-attesting under the pin, as this issue's step 5
  requires, incidentally corrects that field for the item-9 envelope. This is
  the defect class **#670 F-1** is open to fix; it is recorded here, not
  claimed as closing #670, and #670 F-1 also covers the item-10 envelope, which
  this change does not re-attest.
- **`cold_start` ran under this host's `iverilog 13.0`, not the inventory's
  declared `12.0-2build2`.** `klt`'s `pin` check echoes the declared pins; it
  does not verify them against the attesting environment, so the recorded
  `cold_start` exit 0 is an attestation about *this host's* run. The other
  three declared pins were matched deliberately, in a throwaway `/tmp` venv
  built from `signoff/requirements.txt` + `requirements-ci.txt`: CPython
  3.12.3, `numpy 2.4.2`, `pytest 9.1.1`, `klt 0.8.0` (the host's ambient
  `numpy` is 1.26.4 and its `klt` is `0.9.2.dev1029+g76f47afa48f1`, so neither
  was used). `iverilog` could not be matched — this is a shared dispatch worker
  whose apt-provisioned tools are identical across the fleet and must not be
  changed from a sweep. `cold_start` is `local_only`, so `--check` skips it and
  carries this outcome; the declared `iverilog` pin is exercised on every PR by
  `ci.yml`'s `rtl-sim` job, which runs the same pytest command under
  `12.0-2build2`. Coverage of the declared pin on this host: **none** — that is
  a disclosure, not a pass.

## Verification statuses

| Check | Status | Note |
|---|---|---|
| `pytest tests/test_shared_render_bus_fold.py tests/test_shared_event_dispatcher.py tests/test_t1_item9_inventory_complete.py tests/test_byte_frozen_sources.py` | PASS | 69 passed |
| Failure controls bite (settle skipped / tail dropped / shared instance) | PASS | observed failures quoted above |
| `FOLDED_VIA` pin bites (five legs) | PASS | observed failures tabulated above |
| `tools/render_wt_reference.py --help` unchanged | PASS | byte-identical |
| `python3 -I -m compileall` over the CI path set | PASS | |
| `tools/check_provenance.py`, `check_artifact_manifests.py`, `check_census_consistency.py`, `compile_backlog_dag.py --check` | PASS | unaffected, run for completeness |
| `klt signoff --attest 9 … --check` under pinned `klt 0.8.0` | PASS | `status: match`, `fresh_status: pass`, exit 0 |
| `klt signoff --attest 10 … --check` under pinned `klt 0.8.0` | PASS | `status: match`, exit 0; inventory untouched by this change |
| `klt signoff --manifest signoff/block-manifest.json` reproduces the committed report | PASS | byte-identical (`cmp`), grader exit 3 = ran clean, some T1 item unmet |
| `cold_start` full suite inside the re-attestation | PASS | exit 0, under CPython 3.12.3 / numpy 2.4.2 / pytest 9.1.1 — but host `iverilog 13.0`, not the declared `12.0-2build2` (see disclosure above) |
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
