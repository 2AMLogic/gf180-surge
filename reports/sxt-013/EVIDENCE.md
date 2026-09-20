# SXT-013 evidence record — favorites/fidelity APPARATUS (freeze blocked)

Branch: `loom/sxt-013-favorites-apparatus` · Issue: #8 (SXT-013) · Date: 2026-09-20

**Claim discipline.** This record covers the *automatable apparatus* for
issue #8 only: candidate-pool proposals, the listening harness, the DRAFT
policy, and the record layouts. **Nothing is frozen.** The actual favorites
selection, the 32-preset pilot completion, and the policy freeze require
human listening, which has not happened. No fidelity, support, preset-quality,
or hardware claim is made anywhere here. Machine dry-run ratings are
placeholders, not listening evidence.

## Deliverables

| Deliverable | Artifact |
|---|---|
| Deterministic candidate-pool builder | `tools/select_candidates.py` (census-hash integrity gate; 3 quota profiles; reasons per candidate) |
| Proposed slates (PROPOSALS, not selections) | `reports/sxt-013/candidates/slate-256-<profile>.json` + `pilot-32-<profile>.json` for `balanced`, `factory-lean`, `contributor-lean` |
| Listening harness | `tools/listening_session.py` (renders/locates fixtures via the unmodified SXT-012 renderer; `open` = unblinded level-correct acceptance mode; `blind` = randomized A/B, optional RMS `--level-match`, supplementary-only; census blob re-verified per candidate) |
| Machine dry-run session (NOT human listening) | `decisions/listening-sessions/20260920-machine-dryrun.json` |
| DRAFT fidelity policy | `contracts/fidelity-policy-DRAFT.md` (every tolerance `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`; per-status definitions; measurement suite; level-correct rules; listening procedure; freeze procedure) |
| Favorites template + retention layout | `decisions/favorites-TEMPLATE.md`, `decisions/README.md`, `decisions/rejected-selections/README.md` |
| Negative controls | `reports/sxt-013/negative-controls.txt` + `tests/test_sxt013_apparatus.py` (13 tests) |

## Slate sizes and quota profiles (proposals for the human chooser)

All profiles: 256-preset slate + 32-preset pilot (pilot ⊆ slate), across
basses / leads / keys / plucks / pads / rhythmic / textures, both banks.
Selection = greedy marginal coverage of normalized-graph diversity tokens
(osc families incl. Wavetable/FM2/FM3/Modern/Twist/Alias, FX presence incl.
exact `Reverb 1` / `Reverb 2` / Airwindows algorithm ids, scene modes,
unison buckets, filters, waveshapers, LFO shapes incl. MSEG/Formula gap
markers, modroute density) under explicit quotas. **No popularity signal
exists in the inputs and none is used.**

| Profile | Slate 256 | Pilot 32 | Explicit quotas |
|---|---|---|---|
| `balanced` (proposed default) | factory 64 / contributor 192 | factory 10 / contributor 22 | per-category 25% minority-bank floor; global factory floor 64; author cap 8 (pilot 2) |
| `factory-lean` | factory 128 / contributor 128 | factory 16 / contributor 16 | 50% factory target per category; global factory floor 128 |
| `contributor-lean` | factory 48 / contributor 208 | factory 6 / contributor 26 | factory held at exactly 48/256 (≈ corpus share 641/3561; both banks covered) |

Category quotas (all profiles): basses 40, leads 40, keys 34, plucks 32,
pads 36, rhythmic 38, textures 36. Recorded deviations (visible, never
silent): factory has no textures directory (textures necessarily
all-contributor); textures author concentration required 13–31 recorded
author-cap overruns to meet the quota (`quota_accounting.notes` in each
slate). Pool accounting per run: 3,474 eligible of 3,561 entries;
87 excluded for `audio_input` dependency (rendered output would depend on an
external input signal); 819 directories outside the seven quota categories
(available to a revised mapping; never silently dropped); 1 unison anomaly
clamped and recorded.

## Acceptance mapping (issue #8)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | 32-preset pilot completed; evaluation process documented; pilot does not substitute for the 256 goal | **APPARATUS PASS / PILOT BLOCKED-on-human-listening** | Pilot slate proposed (`pilot-32-balanced.json`, 32 candidates, subset of the 256 — test-enforced); evaluation process documented in `contracts/fidelity-policy-DRAFT.md` §2–§4 and demonstrated end-to-end by the machine dry-run below. **No human listening session exists**, so the pilot is NOT completed and claims nothing. The pilot can never substitute for the 256 goal (policy §6.4). |
| 2 | 256 selections named with corpus hashes; categories and both banks covered; originals and rejections retained | **APPARATUS PASS / SELECTION BLOCKED-on-human-listening** | Three complete 256-preset proposal slates with per-candidate census blob SHA-1 + reasons + quota accounting (above); retention layouts for rejections defined (`decisions/rejected-selections/README.md`). The frozen `decisions/favorites-v1` does **not exist**; selecting 256 presets by listening is the human operator's task. |
| 3 | Fidelity policy frozen before SXT-017; per-status definitions included | **DRAFT PASS / FREEZE BLOCKED-on-human-listening** | `contracts/fidelity-policy-DRAFT.md` is complete: per-status definitions (supported/adapted/unsupported/unresolved, plan §2 verbatim meaning), measurement suite (pitch/timing/gain, envelope/modulation, spectral/aliasing, filter/feedback stability, stereo/effect-decay), level-correct rules (no per-clip normalization), listening procedure (blind supplementary only), negative-control requirements, freeze procedure. Every tolerance is `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`. Freezing requires the pilot (policy §6); SXT-017 must not treat this draft as frozen. |
| 4 | Listening records retained | **APPARATUS PASS / RECORDS BLOCKED-on-human-listening** | Session schema + retention location live (`decisions/listening-sessions/`); the committed session is a machine dry-run with placeholder ratings (`status: DRY_RUN_NOT_HUMAN_LISTENING`, `counts_toward_acceptance: false` on every record). Zero human listening records exist. |
| 5 | Negative control: degraded render (e.g., substituted generic reverb) must fail the frozen policy or be classed adapted, never supported | **NOT_RUN (requires the frozen policy and a chip/model render to test)** | The control is *specified* (policy §5.1: generic-reverb substitution under a support claim must FAIL or be classed adapted) but cannot be executed before (a) the policy is frozen and (b) a non-reference render exists to degrade. Builder-side controls ARE live today (below). |

Apparatus-level negative controls — **PASS** (`reports/sxt-013/negative-controls.txt`):

- **Determinism**: two full builder runs → byte-identical slates (6/6
  artifacts; also enforced in CI by `test_committed_artifacts_are_current`).
- **Census-hash tamper**: flipped blob SHA inside `graphs.jsonl` →
  `REFUSING … census-hash integrity check FAILED`, exit 2, no slate written;
  corrupted census CSV → refused exit 2; dropped census entry → refused
  exit 2 (never silently skipped). Restored inputs reproduce NC1 exactly.

## Dry-run session (machine; NOT human listening) — outcome

`decisions/listening-sessions/20260920-machine-dryrun.json`:
scripted operator, 3 candidates spread across the balanced pilot slate
(`Basses/Doomsday.fxp` factory, `Keys/Experiment.fxp` factory,
`Altenberg/Pads/Mana Quest.fxp` contributor), sequence
`seq-notes-coverage-v1`, wet-vs-dry pairs. Every candidate passed the
integrity chain (slate census hash == committed census == on-disk blob in the
pinned engine tree) and was rendered end-to-end through the unmodified SXT-012
renderer. Ratings are deliberately `null` placeholders;
`status: DRY_RUN_NOT_HUMAN_LISTENING`; zero records count toward acceptance.
Interactive `open` and `blind`/`--level-match` modes were exercised separately
in scratch sessions (records not committed; they contain no human judgments
either). **This demonstrates plumbing only.**

## What the human operator must do (exact next actions)

1. Pick a quota profile (`balanced` recommended default) — or revise the
   category↔directory mapping (`CATEGORY_DIRS`) and quotas; slates regenerate
   deterministically: `python3 tools/select_candidates.py --profile <p> --out-dir <dir>`.
2. Complete the 32-preset pilot listening set on stable fixtures:
   `python3 tools/listening_session.py --slate reports/sxt-013/candidates/pilot-32-balanced.json --operator <name> --mode open`
   (acceptance mode: unblinded, level-correct; blind/level-matched sessions
   may supplement). Retain every session JSON.
3. Freeze the policy: replace each `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`
   tolerance with a pilot-justified budget; publish
   `contracts/fidelity-policy-v1.md` (policy §6). Any budget the pilot cannot
   justify stays named as unresolved.
4. Then run the 256-preset listening selection from the frozen policy's
   process; populate `decisions/favorites-v1.json` per
   `decisions/favorites-TEMPLATE.md`; retain all rejected selections with
   reasons.
5. Execute the degraded-render negative control (policy §5.1) once a frozen
   policy and a degradable render exist.

Until steps 2–4 complete: **issue #8 is not done, nothing is frozen, and
SXT-017 has no frozen policy to compare against.**

## Licensing / provenance

- `tools/select_candidates.py`, `tools/listening_session.py`, and the tests
  are original to this repository (Apache-2.0 per `LICENSE`); stdlib only.
- Listening/audition METHOD adapted per `docs/REUSE-AUDIT.md` from the
  Parasynth audition harness (`gf180-parasynth@cbcc8b9e`, Apache-2.0) and the
  TorchSynth explorer session/favorites contracts
  (`gf180-torchsynth@6532ec08`, Apache-2.0), plus the sibling dx7 U01/U02
  procedure. **No sibling code was copied**; no adoption decision is required
  for method reference. Interfaces were adapted to the corpus/slate workflow.
- Candidate slates reference census entries by path + git blob SHA-1; no
  preset payloads are committed. Audio renders referenced by the dry-run
  session are this project's own renders (re-derivable via the harness; the
  cache directory `.listening-cache/` is not committed).

## Explicitly NOT established by this work

- Any favorites selection, frozen set, or frozen policy — the two freeze
  items are **BLOCKED on human listening** with the operator checklist above.
- Any listening evidence: the only committed session is a machine dry-run.
- Any fidelity, support, coverage, or preset-quality claim; slates are
  proposals computed from static normalized data (corpus/normalized/README.md
  claim scope applies unchanged).
- Any stereo, tempo-synced, long-tail (>2.5 s), or per-voice-stem listening
  coverage — the SXT-012 harness limitations carry through unchanged.
- The generic-reverb negative control (acceptance item 5) — specified, not
  run.
