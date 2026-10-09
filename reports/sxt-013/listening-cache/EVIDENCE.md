# SXT-013 listening-cache identity binding (issue #404)

Scope: cache/session bookkeeping in `tools/listening_session.py` only. No DSP,
renderer, or oracle change. No fidelity, preset-coverage, or human-listening
claim moves. Historical sessions (`decisions/listening-sessions/20260920-*`)
are untouched and not revalidated; existing basename-keyed cache directories
are never consulted (unverified, re-rendered rather than relabeled).

## Behavior

- Cache entry: `<cache>/by-identity/<sha256(identity)>/` with `identity.json`
  plus `<seq>-wet.wav` / `<seq>-dry.wav`.
- Identity: census-relative preset path, verified blob SHA-1, sequence id and
  sequence-file sha256, renderer path and sha256, oracle manifest sha256,
  pinned engine commit, manifest python runtime, sample rate, block size,
  render policy. Runtime identity basis is the committed oracle manifest plus
  live renderer bytes; the engine binary is NOT live-probed (stated in the record).
- Reuse requires: identity record present, parseable, schema match, recorded
  identity equal to the requested one, and both WAV sha256 equal to the record.
  Otherwise the entry is re-rendered (to a temp dir, then swapped in).
- Session `audio.binding` persists identity, key, cache entry name, identity
  record sha256, disposition (`rendered`/`reused_verified`), refusal reason.
- Missing/unusable oracle or renderer failure -> `Blocked`: the record is
  `verification_status: BLOCKED`, `audio: null`, no ratings, not counted;
  `counts.blocked` is recorded. No prompts occur for that entry.

## Results

| Check | Status |
|---|---|
| Failure control: legacy basename cache reuses A's audio for same-name B (fake renderer) | PASS (control demonstrates the defect; renderer called once) |
| Same-basename A/B get independent entries and distinct audio, correct session association | PASS |
| Seeded legacy A entry not reused for B | PASS |
| Valid entry reused with renderer not invoked; binding retained | PASS |
| Tampered wet / tampered dry / missing / corrupt / mismatched identity record -> reuse refused, re-render | PASS |
| Changed preset path/blob, sequence digest, renderer digest, oracle manifest/commit -> different entry | PASS |
| Missing oracle -> BLOCKED, zero acceptance-counting records | PASS |
| `tests/test_sxt013_apparatus.py` (13 pre-existing tests) | NOT_RUN (pytest unavailable on this host; no host-wide install allowed) |
| `tests/test_byte_frozen_sources.py` | NOT_RUN (needs pytest). `tools/listening_session.py` is a `tool_sha256` historical stamp (`current_bytes_recorded: false`), not a live pin: no `live_pins` entry covers it, so no live record can go STALE |
| Real render under the pinned oracle (cache reuse over genuine audio) | NOT_RUN (pinned oracle/surgepy unavailable here) |
| Human listening / fidelity / coverage | NOT_RUN / no claim |

Coverage (what the tests exercise: bookkeeping with a fake renderer writing
tiny distinct WAVs) is separate from agreement (none measured).

Reproduce: `python3 -I tests/test_sxt013_listening_cache.py -v`
(also pytest-collectable). Transcript: `test-transcript.txt`. Inspectable
samples (FAKE renderer, not oracle audio): `sample-identity-record-fake-renderer.json`,
`sample-session-fake-renderer.json`.

## Remains unproved

Genuine-oracle cache behavior; that `renderer_sha256` + manifest digest fully
determine engine runtime (engine binary not probed); anything about sound.
