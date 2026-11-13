# Tooling audit — private oracle event dispatchers folded onto the shared one (issue #640)

Branch: `feature/issue-640` · Issue: #640 (Hermit simplification, autonomous
parallel-drift pass) · Date: 2026-11-13 · Base: `origin/main` @ `a18de1b`

**Claim discipline.** This record covers a source change plus a read-only
static audit. It makes **no** fidelity, RTL-exactness, coverage, synthesis or
musical-quality claim, and it re-renders nothing: no committed reference WAV,
sidecar or verdict is re-derived, re-graded or relabelled. The pinned oracle is
not available on the host that produced this record, so every question that
needs an engine render is reported `NOT_RUN`, not answered.

## What changed

`fixtures/render_fixture.py` has carried a shared event dispatcher since
SXT-012: `dispatch(s, events, block, quant)` (lines 191-208), which forwards
all five event types the shared loader admits — `note_on`, `note_off` **with
its declared velocity**, `cc`, `pitch_bend`, `channel_pressure` — and
deliberately ignores `tempo` (surgepy cannot apply it). Eight tools already
imported it as `rf.dispatch`. Nine more renderers carried private copies that
each forwarded a narrower set, with no refusal for the events they skipped, so
a sequence carrying an event type a copy ignored produced a reference with that
event missing and a sidecar still citing the sequence's sha256.

Seven of the nine are now folded onto the shared dispatcher:

| Renderer | Forwarded before | Now |
|---|---|---|
| `fixtures/render_lfo_fixture.py` | note_on, note_off (velocity forced 0), cc | `rf.dispatch` |
| `fixtures/render_mw_fixture.py` | note_on, note_off (velocity forced 0), cc | `rf.dispatch` |
| `model/voice/render_uni_reference.py` | note_on, note_off, cc | `rf.dispatch` |
| `tools/_render_reference_common.py` | note_on, note_off | `rf.dispatch` (resolved lazily, see below) |
| `tools/render_lp12_reference.py` | note_on, note_off, cc (own `def dispatch`) | `rf.dispatch` |
| `tools/render_pm_reference.py` | note_on, note_off; **refused** anything else | `rf.dispatch`, behind a hoisted refusal |
| `tools/render_wt_reference.py` | note_on, note_off | `rf.dispatch` |

`fixtures/render_fixture.py` itself is imported, never edited: its bytes are
unchanged and the 30 committed records stamping them still resolve.

### Two renderers were not folded, each for a stated reason

- **`fixtures/render_slfo_fixture.py` — issue #640's own stop condition.**
  `docs/byte-frozen-sources.json` records this file with
  `current_bytes_recorded: true`: the six
  `reports/SXT-041/artifacts/reference-*.json` sidecars stamp its current
  bytes, so editing it spends a resolvable provenance stamp. Folding it is only
  valid in a change that re-renders those six references under the pinned
  oracle. That render is **NOT_RUN** here (no oracle on this host), so the file
  is untouched and its sha256 (`0611c7f4…`) still resolves.

- **`tools/render_lp24_tap_reference.py` — an interpreter constraint, found
  during this work and not anticipated by the issue.** Importing
  `fixtures/render_fixture.py` runs `oc.reexec_under_pinned_python()` at import
  time, which re-execs the process under `oracle/manifest.json`'s
  `build.python_interpreter`. This tool deliberately has no such re-exec: it
  loads an **external** surgepy module from `--engine-dir` (a tap-instrumented
  build and an unpatched build of the same pin) and must stay on the
  interpreter those modules were built for, which its caller chooses. Folding
  it would silently change which interpreter drives an exact-bit neutrality
  comparison, and that cannot be verified without the oracle host. Instead the
  two defects the issue names for this file are removed directly: the silent
  `[e for e in seq["events"] if e["type"] in ("note_on", "note_off")]` filter
  is replaced by an explicit refusal (`non_note_event_types`, exit 2), and the
  `else:`-means-note_off catch-all is now guarded by that refusal and
  commented. It forwards the same two event types as before, but no longer
  drops a third silently.

`tools/render_reverb_reference.py` keeps its own lossless copy: the issue
scoped folding it as optional tidy-up, outside the acceptance check.

### Behaviour differences the fold introduces

1. `cc`, `pitch_bend` and `channel_pressure` now reach the engine in the four
   renderers that dropped them, and `note_off` carries its declared velocity in
   the two that forced 0. This governs **future** renders only.
2. Three copies read `e.get("velocity", 100)` on `note_on`; the shared
   dispatcher reads `e["velocity"]`. A sequence with no declared attack
   velocity is now a visible `KeyError` instead of a silent 100 — surfaced, not
   defaulted. Finding F-640-3 shows no committed sequence relies on it.
3. `tools/render_pm_reference.py` refused a non-note event lazily, when the
   dispatch loop reached it; an event past the last note's render span was
   therefore never checked. The refusal is now a pre-pass over the whole
   sequence (`refuse_non_note_events`), with its message verbatim, so the
   SXT-043 "every non-note modulation source is inert" declaration is checked
   for every event before any audio is produced.
4. `tools/_render_reference_common.py` resolves the dispatcher through
   `shared_dispatch()` on first use rather than at module import. Both its
   callers (`tools/render_classic_reference.py`, `tools/render_sine_reference.py`)
   import this module **before** they call `oc.reexec_under_pinned_python`, so a
   module-level import would move their re-exec point and their `--help` path.

## Audit: did the drift reach a committed reference?

Artifact: `artifacts/dispatcher-drift-audit.json` (read-only; records every
committed record under each leaf's `reports/` directory, the sequence it cites,
that sequence's event types, and the event types the renderer did not forward
on `a18de1b`).

### F-640-1 `FINDING` — two committed references cite a release velocity they were not sent

`fixtures/sequences/seq-notes-holds-v1.json` event 7 is
`{"type": "note_off", "note": 60, "t": 177600, "velocity": 100}` — the only
nonzero release velocity in any committed sequence. Two committed reference
sidecars cite it (sequence sha256 `a43affac…`, which still matches the file)
and were produced by a renderer that sent release velocity `0`:

| Record | Leaf | Renderer | Stamp resolves today |
|---|---|---|---|
| `reports/sxt-032/artifacts/reference-seq-notes-holds-v1.json` | SXT-032 | `fixtures/render_lfo_fixture.py` | no (`a3f534a1…`, already unresolvable on `a18de1b`) |
| `reports/SXT-041/artifacts/reference-seq-notes-holds-v1-slfo-fixture.json` | SXT-041 | `fixtures/render_slfo_fixture.py` | yes (`0611c7f4…`) |

The SXT-032 record is **new on this pass** — issue #640 reported the SXT-041
one and listed the LFO, mod-wheel, unison, LP12, PM and WT records as not
audited. It is a provenance mismatch of the same class, so the finding covers
two records, not one.

**Not established (`NOT_RUN`):** whether release velocity reaches audio in
either fixture configuration, and therefore whether either committed WAV
differs from a correct render. Deciding that needs an oracle render both ways.
Nothing here re-grades either record; this is **for a human ruling**.

### F-640-2 `MEASURED` — no committed reference lost a bend or a pressure event

No committed reference anywhere cites a sequence containing a `pitch_bend` or
`channel_pressure` event. The only non-note event type that reaches a committed
reference is `cc`, via `fixtures/sequences/seq-modwheel-v1.json`, rendered
through `render_lfo_fixture.py`, `render_mw_fixture.py` and
`render_slfo_fixture.py` — all three of which forwarded `cc`. The four copies
that dropped `cc` never produced a committed reference from a cc-bearing
sequence. This closes the issue's open question for the mod-wheel, unison,
LP12, PM, WT and LP24 records.

### F-640-3 `MEASURED` — the note_on velocity default was never exercised

Every `note_on` in all 20 committed sequences carries an explicit `velocity`,
so the `e.get("velocity", 100)` default in `_render_reference_common.py`,
`render_pm_reference.py` and `render_wt_reference.py` never applied to a
committed render. Folding them changes no committed render.

## Acceptance check and failure control

`tests/test_shared_event_dispatcher.py` (24 cases, no engine, no numpy):

- **Behavioural.** `dispatch` is compiled from the committed bytes of
  `fixtures/render_fixture.py` by `ast` (the function is pure, so it runs
  standalone without the ABI-specific numpy the oracle build needs) and driven
  with a recording stub synthesizer over a sequence carrying all five event
  types plus a `tempo` event and a nonzero `note_off` velocity. The recorded
  call list must match exactly, `tempo` must be consumed without a call, and
  block-boundary truncation is checked.
- **Failure control (required).** `lossy_dispatch_control` reproduces the
  pre-change body of `fixtures/render_slfo_fixture.py` verbatim in behaviour.
  The test asserts it does **not** match the expected call list, and names the
  three specific losses (no `pitchBend`, no `channelAftertouch`, release
  velocity 0 where 100 was declared), so the control cannot rot into passing
  for an unrelated reason.
- **Source pins.** Each folded renderer must call a shared `dispatch` resolved
  from `render_fixture`, and must contain no `playNote`/`releaseNote` of its
  own. `pitchBend`/`channelController`/`channelAftertouch` are deliberately not
  markers — the RESET policy every renderer implements calls all three on a
  fresh instance, which is not event dispatch.
- **Exemption ratchet.** The two unfolded files are asserted to be *exactly*
  the set still carrying a private note dispatch, each with a recorded reason;
  folding one without updating the table fails, and so does regressing a folded
  file back to a private copy. A further assertion pins that
  `render_slfo_fixture.py` still hard-codes release velocity 0, to be removed
  only by the change that re-renders the SXT-041 references.
- **Finding basis.** `seq-notes-holds-v1` is asserted to be the only committed
  sequence declaring a nonzero release velocity, and both F-640-1 sidecars are
  asserted to still cite it at its current sha256, so the finding cannot rot
  while it waits for a ruling.

Control demonstrated, not asserted: reverting `tools/render_wt_reference.py` to
its `a18de1b` bytes makes 3 of the 24 cases fail
(`test_folded_renderer_calls_the_shared_dispatcher[…wt…]`,
`test_folded_renderer_keeps_no_private_event_dispatch[…wt…]`,
`test_exempt_renderers_are_exactly_the_documented_set`); restoring the fold
returns 24 passed.

## Verification status

| Check | Status |
|---|---|
| `tests/test_shared_event_dispatcher.py` | PASS (24) |
| Failure control fails on pre-change bytes | PASS (demonstrated, see above) |
| `tests/test_byte_frozen_sources.py` | PASS |
| `tests/test_t1_item9_inventory_complete.py` | PASS |
| `tests/test_report_status_tokens.py` | PASS |
| `tests/test_check_artifact_manifests.py` | PASS |
| `klt signoff --attest 10 … --check` (hygiene envelope) | PASS (`match`, pinned `klt 0.8.0`) |
| `klt signoff --attest 9 … --check` (item 9 envelope) | PASS (`match`, `fresh_status: pass`, pinned `klt 0.8.0`) after re-attestation in this change |
| `klt signoff --manifest signoff/block-manifest.json` reproduces the committed verdict of record | PASS (byte-identical, exit 3 = items unmet, as before; item 9 cites 227/227) |
| Full `pytest tests` run to completion by this change | **NOT_RUN** — see the note below |
| `fixtures/render_fixture.py` bytes unchanged | PASS (sha256 `13c3c772…`, 30 records still resolve) |
| `fixtures/render_slfo_fixture.py` bytes unchanged | PASS (sha256 `0611c7f4…`, 6 records still resolve) |
| Any committed reference re-rendered | NOT_RUN (no pinned oracle on this host; none intended) |
| Whether F-640-1 changed a rendered sample | NOT_RUN (needs an oracle render both ways) |
| Model-vs-reference agreement, fidelity, coverage | NO_VERDICT (out of scope; nothing here establishes any) |

### Note on the item 9 envelope's `cold_start`

The item 9 inventory's `cold_start` check is `python3 -m pytest -q -p
no:cacheprovider tests` with `local_only: true`. The envelope was re-attested
with `--skip-local-only`, which **carries the committed `cold_start` outcome**
(`exit_status: 0`) rather than re-deriving it — exactly what
`.github/workflows/signoff.yml`'s `--check` does on every PR, and what that
workflow's own comment describes ("cold_start is local_only: --check skips it
and carries the committed outcome"). What this change *did* re-derive is every
content hash in the envelope and its check count (226 -> 227, the new test).

**The full suite was not run to completion here, and is not claimed as a pass.**
Two attempts on this shared dispatch worker exceeded `klt`'s hard-coded
1800 s `_COMMAND_EVIDENCE_TIMEOUT_S` (~47 min projected wall at a host load of
16-34 on 16 cores); both left the committed envelope untouched. Partial
progress was clean (~25% of the suite, zero failures, skips only) and the
targeted batch below is green, but `tests` as a whole is CI's gate
(`.github/workflows/ci.yml` and the `rtl-sim` job re-run it with the pinned
`iverilog` on every PR), not this record's claim.

Targeted batch run to completion here, under `pytest 9.1.1` / `numpy 2.4.2`
(the `requirements-ci.txt` pins) on CPython 3.12.3 in a throwaway venv —
**144 passed**:
`test_shared_event_dispatcher.py`, `test_byte_frozen_sources.py`,
`test_t1_item9_inventory_complete.py`, `test_report_status_tokens.py`,
`test_check_artifact_manifests.py`, `test_frozen_artifact_basis.py`,
`test_render_lp24_tap_reference.py`, `test_osc_fixture_core_equivalence.py`.
