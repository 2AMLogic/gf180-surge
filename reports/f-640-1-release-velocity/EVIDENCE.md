# F-640-1 measured under the pinned oracle — does the dropped release velocity reach audio? (issue #660)

Branch: `feature/issue-660` · Issue: #660 · Date: 2026-11-14 · Base:
`origin/main` @ `7de0a780` · Engine: pinned `58914e59c608ed4384ba6002e44c3465c58b2e71`,
stock prebuilt (`1.4.HEAD.58914e59c`)

**Claim discipline.** This record answers one question with engine renders:
for the two fixture configurations named by finding **F-640-1**, is the
rendered audio changed by the release velocity their renderers dropped? It
makes **no** fidelity, coverage, RTL-exactness, synthesis or musical-quality
claim, and it re-renders, re-grades and relabels no committed reference. The
finding itself is **not** restated here — it is
`reports/tooling-oracle-dispatcher-fold/EVIDENCE.md` → F-640-1, machine-readable
in that leaf's `artifacts/dispatcher-drift-audit.json`.

## Answer

**The dropped release velocity does not reach the audio in either
configuration.** Rendering `seq-notes-holds-v1` with the release velocity the
renderers sent (`0`) and with the value the sequence declares (`100`) produces
**bit-identical** raw float mono buffers in both leaves, as does forcing `127`.
The mismatch between what the two sidecars cite and what their renderer sent is
therefore **provenance-only**: both committed WAVs stand, byte-unchanged.

| Record | Leaf | Status | What the status means |
|---|---|---|---|
| `reports/SXT-041/artifacts/reference-seq-notes-holds-v1-slfo-fixture.json` | SXT-041 | **PASS** | The committed WAV is unaffected by the dropped release velocity. The citation mismatch is provenance-only. |
| `reports/sxt-032/artifacts/reference-seq-notes-holds-v1.json` | SXT-032 | **PASS** | Same. |

`PASS` here means exactly "this leaf's committed reference is not stale with
respect to the release velocity its sequence declares". It is **not** a
fidelity verdict, a coverage claim, or an endorsement of either record for any
other purpose.

## Coverage (reported separately from the result)

| | |
|---|---|
| Leaves requested | 2 (SXT-041, SXT-032) |
| Leaves whose baseline reproduced, so comparison ran | **2** |
| Leaves reported `NOT_RUN` | 0 |
| Fixture configurations covered | the two named by F-640-1, each at one sequence (`seq-notes-holds-v1`) |
| Presets covered | one (`Basses/Attacky.fxp` plus each leaf's declared routes) |

This answers the question **for these two fixture configurations only**. It
does not generalize to other presets, other routes, or other sequences; a
preset that routes release velocity would behave differently and nothing here
says otherwise.

## Method

`tools/probe_release_velocity.py` calls each committed renderer's own
`render_bus` with a shim in place of the `surgepy` module. The shim returns a
proxy around the real Surge instance that intercepts exactly two calls,
`releaseNote` and `playNote`, and substitutes the leg's velocity. Everything
else — reset, routes, definition overrides, settle, block-quantized scheduling,
tail, mono/int16 audio policy, the three-repeat determinism gate — is the
committed code path, and **neither renderer was edited** (`fixtures/render_slfo_fixture.py`
is byte-stamped by six SXT-041 sidecars; its sha256 `0611c7f4…` is unchanged).

The substituted values come from a FIFO built from the sequence itself, and
each interception asserts the channel and note it was handed match the next
declared event, with a refusal if any event goes undispatched. The velocities
actually forwarded to the engine are recorded per leg in
`artifacts/comparison.json`, so the `identical` result is auditable: the two
legs demonstrably sent different bytes to the engine.

Legs per leaf, three fresh-instance repeats each (all bit-identical across
repeats):

| Leg | Release velocity sent | Note-on velocity | Purpose |
|---|---|---|---|
| `zero` | `0` on every `note_off` | declared | baseline — must reproduce the committed WAV |
| `declared` | `0, 0, 0, 100` (the sequence's own) | declared | **the measurement** |
| `extreme` | `127` on every `note_off` | declared | wider sweep of the same axis |
| `noteon` | `0` | declared **+1** | observation, not a control (see below) |
| `control` | `0`, but `releaseNote` handed note **+1** | declared | **the failure control** |

## Baseline reproduction (gate, run before any comparison)

| Leaf | Committed `wav_sha256` | Rendered by the `zero` leg | Reproduces |
|---|---|---|---|
| SXT-041 | `28839ad2f2e4c37d1bb0369fa63f9d74522df5faebfbd1d6984b9b19a3fb6b05` | identical | **yes** |
| SXT-032 | `0f72f0256607b9804a9f07c8433eaddec7bf6f2bbf71992910961cfbef1d4bd5` | identical | **yes** |

Both sidecars' `wav_sha256` also match the committed WAV files on disk, so the
gate compares real bytes. SXT-041's sidecar `wav` field points at a
`/tmp/sxt041-regen/…` scratch path; the match is on digest, not path.

**The SXT-032 baseline reproduced, which issue #660 did not expect.** The issue
anticipated `NOT_RUN` for that leaf because its sidecar records engine
`1.4.sxt037-tap.01b20d0b8` while the staged oracle is stock. That expectation
rested on a field that does not mean what it appears to mean — see F-660-1
below.

## Results

| Comparison | SXT-041 | SXT-032 |
|---|---|---|
| `declared` vs `zero` (**the measurement**) | identical, 0/297600 samples differ | identical, 0/297600 |
| `extreme` (127) vs `zero` | identical, 0/297600 | identical, 0/297600 |
| `noteon` +1 vs `zero` (observation) | identical, 0/297600 | identical, 0/297600 |
| `control` (release note +1) vs `zero` | **different**, 288000/297600 samples, first at sample 9600 (0.200 s), max abs diff 0.960 | **different**, 288000/297600, first at sample 9600 (0.200 s), max abs diff 0.776 |

## Failure control

**Targets**: the claim that this comparison can see a change in an argument of
`releaseNote` at all. Without it, an `identical` result for the velocity
argument is indistinguishable from a blind apparatus.

**It fails the check it targets**: perturbing the *note number* handed to
`releaseNote` by +1 — so the held note is never released and sustains through
the tail — changes 288000 of 297600 samples in both leaves, with the first
difference at sample 9600, exactly the first `note_off` in the sequence
(`t = 9600`). Proxy interception reaches the engine, the renderer renders what
the proxy forwards, and the bit-comparator reports differences when they exist.

**A velocity perturbation is deliberately not the control here, and the first
attempt at one was wrong.** The control was initially a +1 note-on velocity
perturbation; it came back identical, and the probe correctly refused a verdict
(`NO_VERDICT`) rather than reporting the measurement as a pass. Rendering the
preset directly at note-on velocities 1, 70, 71 and 127 gives one and the same
buffer (sha256 `569722de…`, peak 0.390136 at all four): **this fixture preset
responds to no velocity at all**, so no velocity perturbation could distinguish
a working apparatus from a broken one. That insensitivity is now recorded as
the `noteon` observation, and the control perturbs a different argument of the
very call under test instead. The sequence's own `coverage` field claims
`release:release-velocity`; this measurement shows that claim is not exercised
by this preset.

## Independent corroboration (no probe, no shim)

`artifacts/renderer-corroboration.json`: each committed renderer was run
unmodified through its own CLI against the same sequence under the same oracle.

- `fixtures/render_slfo_fixture.py` (sends a literal `0`) reproduced
  `28839ad2…`.
- `fixtures/render_lfo_fixture.py` (folded by #640, so it now sends the
  **declared 100**) reproduced `0f72f025…` — the SXT-032 reference that was
  rendered with `0`.

The second run is the sharper of the two: it reaches the measurement's result
without the probe being involved at all.

## New finding — F-660-1 (recorded, not adjudicated here)

**A reference sidecar's `engine.version_string` does not identify the engine
that rendered it.** Both renderers copy `engine.commit` and
`engine.version_string` into their sidecars from the *extractor inputs* file —
`fixtures/render_lfo_fixture.py:229-230` from `model/voice/attacky_lfo_inputs.json`,
`fixtures/render_slfo_fixture.py:286-287` from `model/voice/attacky_slfo_inputs.json`
— never from `surgepy.getVersion()`.

Demonstrated live: the corroboration runs above executed on the stock oracle
(`1.4.HEAD.58914e59c`), and the SXT-032 run still wrote
`1.4.sxt037-tap.01b20d0b8` into its own fresh sidecar.

**Consequence.** `reports/sxt-032/artifacts/reference-seq-notes-holds-v1.json`'s
engine identity does not attribute that WAV to a tap build; it repeats what the
extractor sidecar said. Any argument reasoning from a reference sidecar's
engine identity to the build that rendered it is unsupported for these two
renderers. In particular, nothing here establishes that a `sxt037-tap` build
and the stock build render identically — that comparison cannot be read out of
these records at all.

**Status**: `NO_VERDICT` — established by the runs above, not adjudicated by
this issue. Observed in these two renderers only; the other renderers are not
audited here. Filed as a follow-up; nothing is re-graded or relabelled for it.

## Decisions this record makes explicit

- **`fixtures/render_slfo_fixture.py` stays unfolded, bytes unchanged**
  (sha256 `0611c7f4…`). Issue #660's acceptance step 4 makes folding it valid
  only in the change that re-renders the six SXT-041 references; with the
  buffers identical, that re-render would spend a resolvable provenance stamp
  and produce byte-identical audio. The `EXEMPT` entry and
  `test_slfo_exemption_still_describes_the_file` in
  `tests/test_shared_event_dispatcher.py` are left in force, and the stop
  condition they record still holds — with this record now naming *why* it
  holds rather than leaving the question open.
- **No committed reference, sidecar or WAV is modified**, and
  `docs/byte-frozen-sources.json` is untouched.
- **The probe records no source digest — its own or either renderer's.** A
  `script_sha256` self-stamp is one-shot bookkeeping no test re-derives
  (`docs/byte-frozen-sources.json` → `historical_provenance_note`), and adding
  one would pull this probe into that registry's table, its whole-registry
  count prose, and the item 9 signoff envelope that follows. Recording
  `fixtures/render_lfo_fixture.py`'s *current* digest would additionally flip
  that entry's `current_bytes_recorded` to `true`, imposing a provenance cost
  on a renderer #640 had just freed of one. The record carries the repo commit
  it ran against, the engine's identity and module digest, and the committed
  digests it is checked against; the probe lands in the same change as the
  record, and re-running it re-derives the result.

## What this does not establish

- Nothing about any other preset, route set or sequence. A preset that routes
  release velocity would differ, and this says nothing about one.
- Nothing about the other committed records that cite `seq-notes-holds-v1`.
  #660's revision records that `reports/sxt-012/repeatability.json` cites it at
  the same sha256 outside the audit's nine-renderer population — a
  reference-vs-reference repeatability record, which a dropped release velocity
  does not undermine — and that searching by sequence *name* finds further
  records still (SXT-036, SXT-038, SXT-043). Those are **out of scope** and are
  not re-graded here.
- Nothing about whether the `sxt037-tap` build and the stock build agree (see
  F-660-1).
- No model-vs-reference, RTL-vs-model, coverage or musical claim.

## Reproduction

```bash
oracle/fetch-and-build.sh --prebuilt     # prints the ORACLE_* exports to set
export ORACLE_SURGE_DIR=... ORACLE_PYTHON=... LD_LIBRARY_PATH=...

"$ORACLE_PYTHON" tools/probe_release_velocity.py \
    --out reports/f-640-1-release-velocity/artifacts/comparison.json --repeats 3

# the shim-free corroboration
"$ORACLE_PYTHON" fixtures/render_slfo_fixture.py \
    --sequence seq-notes-holds-v1 --out-dir <scratch> --repeats 3
"$ORACLE_PYTHON" fixtures/render_lfo_fixture.py \
    --sequence seq-notes-holds-v1 --out-dir <scratch> --repeats 3
```

Host note: these are single local renders (one engine, one corner), which the
dispatch-worker rules permit locally. No `klt sim` batch submission applies.

## Artifacts

| File | Contents |
|---|---|
| `artifacts/comparison.json` | per-leaf baseline gate, the four comparison legs, the velocities forwarded to the engine, the failure control, and one status per record |
| `artifacts/renderer-corroboration.json` | the two unmodified-renderer runs and F-660-1 |
