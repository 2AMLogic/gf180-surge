# SXT-013 listening audition gate (issue #447)

Scope: playback-outcome recording and audition-confirmation gating in
`tools/listening_session.py` (session schema `sxt-013-listening-session/1.1.0`)
plus the policy §4 addendum. No DSP, renderer, cache-identity, or oracle
change (`CACHE_SCHEMA` stays `1.0.0`; cache identity is untouched per #404).
No fidelity, preset-coverage, or human-listening claim moves. Historical
sessions under `decisions/listening-sessions/` are byte-untouched: a record
without playback/audition fields is UNRECORDED, never inferred success, and
the eligibility gate rejects such records instead of counting them.

## Behavior

- `play()` returns a structured outcome per stimulus: `not_attempted_play_off`,
  `no_player_found`, `launch_error` (with `error`), `player_exit_nonzero`
  (with `returncode`), or `played_process_ok`. `played_process_ok` records
  PROCESS completion only — it is never audibility evidence.
- `rate_open()` records `playback` (both stimuli) and `audition`
  (`confirmed_heard_both`, `method`, `verification`). A rating counts toward
  favorites acceptance only when the listener explicitly confirms hearing
  BOTH named stimuli; otherwise the record keeps
  `verification: AUDITION_UNCONFIRMED_NOT_COUNTED`, `counts_toward_acceptance:
  false`, and the session continues to the next candidate.
- With `--play off`, a missing player, or failed automatic playback, the
  printed-path manual workflow is preserved: explicit confirmation plus a
  free-text audition method (recorded verbatim) keeps the rating eligible.
  Automatic success records the player command as the method.
- `rate_blind()` records `playback` outcomes for inspectability; blind
  sessions stay supplementary-only regardless (no gate applies, nothing
  counts). Dry-run placeholder records are untouched and remain unqualified.
- `acceptance_eligibility_problem(record)` is the machine-checkable gate: it
  returns the reason a record is NOT acceptance-eligible, or None. A
  pre-1.1.0-shaped record (unconditional counts flag, no audition fields) is
  rejected: unrecorded is never inferred as heard.
- `contracts/fidelity-policy-DRAFT.md` §4 gains the audition-gate bullet
  (a strengthening of the listening contract; nothing weakened).

## Results

| Check | Status |
|---|---|
| NC5 live negative control: mocked player exits 1, ordinary ratings, no confirmation → not counted; pre-#447 unconditional record rejected by the gate | PASS |
| Manual-confirmation success case (`--play off`, external method recorded verbatim) → counted | PASS |
| Automatic player success + confirmation → counted, method = player; automatic success WITHOUT confirmation → not counted (process ≠ audibility) | PASS |
| Missing player and launch exception → inspectable outcomes; external confirmation still honored, declinable | PASS |
| Session continues after an unconfirmed candidate; per-session counts include `audition_unconfirmed_not_counted` | PASS |
| Blind session records playback, stays supplementary (`acceptance_eligibility_problem` nonzero) | PASS |
| `tests/test_sxt013_apparatus.py` — 21 tests (8 audition-gate, 13 pre-existing) | PASS (21 passed, python 3.12.3) |
| `tests/test_sxt013_listening_cache.py` (#404 cache identity) + `tests/test_byte_frozen_sources.py` | PASS (41 passed) |
| Registry check | `tools/listening_session.py` is a historical `tool_sha256` stamp (`current_bytes_recorded: false`), not a live pin; no `live_pins` entry covers it — no committed record goes STALE |
| Real playback with a real audio device; audibility of any stimulus | NOT_RUN / no claim (bookkeeping only; actual listening remains human work) |

Coverage (harness bookkeeping with mocked players, scripted answers, tiny
synthetic WAVs) is separate from agreement (none measured). Transcript:
`test-transcript.txt`. Inspectable session samples (FAKE renderer + mocked
player, NOT oracle audio, NOT human listening), regenerable via
`python3 reports/sxt-013/audition-gate/generate-samples.py`:
`sample-session-player-exit-nonzero-unconfirmed.json`,
`sample-session-auto-confirmed.json`,
`sample-session-playoff-manual-confirmed.json`.

## Remains unproved

That any human heard anything (these samples are scripted); audibility of any
real stimulus through a real device; any fidelity or preset-quality claim.
