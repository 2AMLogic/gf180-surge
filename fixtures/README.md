# Render fixtures (SXT-012)

Versioned event sequences and audio fixtures rendered through the pinned
native Surge oracle (`surge-synthesizer/surge@58914e59…`, 48 kHz, via the
`surgepy` binding). These fixtures exist so that every later comparison —
model-vs-reference, RTL-vs-model, effect ablation — runs against fixed,
re-fetchable audio with known variance.

**Claim scope.** These fixtures establish *reference-vs-reference* behavior
only: what the pinned engine itself does under this harness. They establish no
fidelity claim (nothing here compares the engine to our model or RTL), no
preset-support claim, and no musical-quality claim.

## Layout

```
fixtures/
  sequences/            versioned event-sequence library (JSON, one file per sequence)
    generate_sequences.py  provenance generator (see "Sequence library" below)
  render_fixture.py     render harness (wet + diagnostic dry)
  verify_fixtures.py    comparator / integrity verifier
  diagnose_variation.py render-variation mechanism diagnostic
  manifest.json         aggregate metadata (hashes of everything)
  audio/<preset>/<sequence-id>-wet.wav   the committed WET render
  audio/<preset>/<sequence-id>-dry.wav   the committed diagnostic DRY render
  audio/<preset>/<sequence-id>.json      per-fixture metadata sidecar
```

## Sequence library

One JSON file per sequence with stable ids `seq-<family>-<descriptor>-vN`.
Content-addressed by SHA-256 (recorded in `manifest.json`); any content change
requires a new id (`-v2`), never an in-place edit of a `-v1` file.
`generate_sequences.py` is the provenance generator: the committed JSONs are
the source of truth for rendering, and re-running the generator must reproduce
them byte-for-byte (`python3 fixtures/sequences/generate_sequences.py`).

### Schema (schema_version 1)

| Field | Meaning |
|---|---|
| `id` | stable sequence id, equals the file name |
| `schema_version` | 1 |
| `sample_rate` | 48000 (all `t` values are integer samples at this rate) |
| `description` | human-readable intent |
| `coverage` | machine-readable coverage tags (registers, velocities, holds, controls…) |
| `events` | time-sorted event list (below) |
| `tail_s` | seconds rendered after the last event (default 2.5) |
| `settle_s` | seconds of silence processed and discarded before t=0 (default 0.25) |
| `tempo_events_renderable` | whether the surgepy renderer can apply `tempo` events (false for the tempo sequence — see limitations) |
| `notes` | caveats |

Event types (channel 0; integer values):

| `type` | Fields | Engine call |
|---|---|---|
| `note_on` | `t, channel, note (0-127), velocity (0-127)` | `playNote(ch, note, vel, 0)` |
| `note_off` | `t, channel, note, velocity (0-127, default 0)` | `releaseNote(ch, note, vel)` |
| `cc` | `t, channel, controller (0-127), value (0-127)` | `channelController(ch, cc, v)` |
| `pitch_bend` | `t, channel, value (-8192..8191)` | `pitchBend(ch, v)` |
| `channel_pressure` | `t, channel, value (0-127)` | `channelAftertouch(ch, v)` |
| `tempo` | `t, bpm` | recorded, not applied (see limitations) |

Timing vocabulary: registers low=C2 (36) / mid=C4 (60) / high=C6 (84);
velocities soft=30 / medium=70 / hard=120; holds short=200 ms / long=1200 ms.
Declared fixture polyphony target: **8 simultaneous voices** (plan section 3
hypothesis), exercised by `seq-poly-8-v1`; a preset whose own polyphony limit
is lower sounds fewer voices, which the fixtures do not hide.

Macro CCs 41/42 (macros 1/2) follow the pinned engine's default mapping
(`controllers[i] = 41 + i` for a fresh default-settings instance).

### Current library (v1)

| id | coverage |
|---|---|
| `seq-notes-coverage-v1` | low/mid/high × soft/medium/hard velocity, short holds, releases |
| `seq-notes-holds-v1` | short vs long holds, release velocity |
| `seq-notes-repeated-v1` | repeated same-pitch notes (fast + moderate) |
| `seq-poly-8-v1` | declared polyphony (8 voices) |
| `seq-tempo-change-v1` | tempo steps 120→90→150 BPM (events recorded, not renderable via surgepy) |
| `seq-sustain-pedal-v1` | sustain pedal (CC64) held releases |
| `seq-pitchbend-v1` | pitch bend ±full range, return to center |
| `seq-modwheel-v1` | mod wheel (CC1) staircase |
| `seq-pressure-v1` | channel pressure staircase |
| `seq-macro-sweep-v1` | macro 1/2 sweeps (CC41/CC42) |

## Render policies (implemented in `render_fixture.py`)

**Reset** (per bus render): (1) fresh `surgepy.createSurge(48000)` instance;
(2) `loadPatch()` of the census-blob-verified preset file; (3) controller
reset on channel 0 — pitch bend 0, CC64 0, CC1 0, CC11 0, channel pressure 0,
`allNotesOff()`; (4) settle: `settle_s` (0.25 s = 240 blocks) of silence
processed and discarded. Fixture t=0 begins after settle.

**Scheduling**: event times are integer samples; the engine consumes events
only at compiled block boundaries (32 samples at 48 kHz ≈ 0.667 ms). Each
event is dispatched before the first block whose start sample is ≥ `t`
(ceil quantization): an event never sounds before its scheduled time and at
most 31 samples late. Same-block events dispatch in file order.
**Sub-block timing is not representable** through `processMultiBlock`; a
1-sample timing perturbation is below scheduling granularity (demonstrated in
the negative controls). Sequence times remain exact integers so a future
sample-accurate harness can render the same library.

**Tail**: render span = last event sample + `tail_s` (2.5 s), rounded up to
whole blocks; identical for wet and dry of the same fixture. 2.5 s covers the
pilot presets' delay/reverb tails at their stored settings; long-tail presets
will need larger per-sequence tails (bump the sequence's `tail_s` field in a
new version rather than editing renders).

**Wet vs dry**: the WET render is the unmodified loaded patch (all patch-defined
effects active) and is the product reference. The DRY render is diagnostic:
identical fresh instance and sequence, but before settle all 16 FX-slot `type`
parameters are set to `fxt_off` (0) via `setParamVal` — the official host
parameter path, which makes the engine's `loadFx` swap every slot to Off at the
next control pass (the settle pass). The harness reads the types back after
settle and refuses to emit a dry fixture unless all 16 read Off. Nothing else
differs. (Per-note/per-stage stems beyond this dry bus are not available
through surgepy — no per-voice tap — and are NOT_RUN, not approximated.)

**Audio**: stereo float output downmixed to mono (L+R)/2, written as 16-bit
PCM WAV; samples are hard-clipped to [-1, 1] and the clipped-sample count is
recorded in the sidecar. **No normalization, no time warping, no fades.**
(The committed bus is mono per the SXT-012 deliverable; stereo-field
diagnostics are future work.)

**Tempo**: `surgepy` exposes no transport-tempo setter (engine `time_data` is
not bound; only patch-load tempo is honored by the engine). `tempo` events are
counted and reported (`tempo_events_applied: 0`) but cannot be applied
mid-render; renders run at the pinned 120 BPM. This is a documented harness
limitation, not a claim that tempo-synced behavior is covered.

## Metadata

`manifest.json` records: tool version (repo commit + script sha256), engine
identity (commit, version string, surgepy module, sample rate, block size,
tempo), the SHA-256 of every library sequence, preset paths + census blob
SHA-1s, the policy block, per-fixture entries (frames, duration, wet/dry WAV
sha256), and byte totals.

Each `audio/<preset>/<sequence>.json` sidecar records the same for its fixture
plus render statistics: peak, clipped samples, dispatched tempo count, dry
bypass verification, and the exact scheduling/tail/settle values used.

## Repeatability and known engine variation

Each pilot fixture was rendered 3× in fresh instances; per-bus SHA-256
bit-identity (or quantified variation) is recorded in
`reports/sxt-012/repeatability.json`. Two classes exist, rooted in the
engine's wall-clock-seeded audio RNG (`RNGGen` in `SurgeStorage.h`, seeded
from `system_clock::now()`; no seed API, and `surgepy` exposes none):

- **Bit-identical**: presets whose oscillators do not free-run at voice start
  (stored `retrigger` on, e.g. `Basses/Sub 4.fxp`, `Basses/Behemoth.fxp`).
- **Quantified variation**: presets with free-running initial oscillator phase
  (stored `retrigger` off, e.g. `Leads/Koala 2.fxp`): each voice consumes
  `rand_01()` at note-on (`ClassicOscillator.cpp`/`SineOscillator.cpp`), so
  instances differ by initial phase. `fixtures/diagnose_variation.py`
  demonstrates the attribution: forcing `retrigger` on (a diagnostic
  adaptation, never used for committed fixtures) renders bit-identically.

Later fidelity work must treat these classes differently (plan section 5:
raw waveform subtraction is not required to succeed across free-running
phases); this characterization is the input to that policy choice.

## Byte-exact reproduction

Requires the pinned oracle build (see `oracle/manifest.json`: engine commit,
`build-py311`, python 3.11.16) and a clean pinned-inputs tree:

```sh
# full pilot set (writes fixtures/audio/ + fixtures/manifest.json)
python3 fixtures/render_fixture.py render-all
# one fixture
python3 fixtures/render_fixture.py render --preset sub4 --sequence seq-notes-coverage-v1
# repeatability run (3 fresh-instance renders per bus per fixture)
python3 fixtures/render_fixture.py repeatability --repeats 3
# integrity/comparator pass over the committed manifest
python3 fixtures/verify_fixtures.py
# variation mechanism diagnostic
python3 fixtures/diagnose_variation.py --preset "Leads/Koala 2.fxp"
```

Bit-exactness is scoped to the recorded environment (`oracle/manifest.json`
`environment` block); other hosts must re-run rather than assume equality.
Free-phase presets reproduce only within their quantified variation (above).

## Licensing / provenance

Everything under `fixtures/` is original to this repository (Apache-2.0 per
`LICENSE`). The harness imports the externally pinned GPL engine at runtime
and copies no Surge source, tables, or presets into this repository. WAVs in
`fixtures/audio/` are this project's own renders of loaded presets, not
redistributed upstream content.
