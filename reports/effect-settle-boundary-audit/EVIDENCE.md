# #318 -- cross-runner settle-boundary audit

Date: 2026-10-07 · Issue: #318 · Epic: #3 · Escalation gate: SXT-017 (#12)
Source revision of the live run: `cf82d7a9602025d92834eabb5c30dd4ccca7fce4`
(clean tree; recorded per leaf JSON) · Tool: `tools/audit_effect_settle_boundaries.py` · Tests:
`tests/test_effect_settle_boundaries.py`

**Claim scope.** This is a harness-boundary audit. It is not a fidelity
result, not a support claim, and not a musical-quality claim. It edits no
runner, frozen model, RTL, budget, fixture or committed leaf record. Every
committed number below is quoted from its committed record and left in place.

## 0. Status summary

Second increment of #318: the A/B legs now ran **live on the pinned oracle**.

| acceptance item (#318) | status | where |
|---|---|---|
| per-leaf table: runner pre-roll, engine A (measured), C both pre-rolls | **satisfied** for every leaf with a reachable carrier (fx Delay/EQ, Chorus, Reverb 2, SSE anchor; 16 carrier rows with C; 6 Phaser factory carriers A/B only) | §3, `audit-table.md` |
| wrong-boundary leaves: delta to **committed** numbers stated | **satisfied** for SXT-023 (runner 240 matches neither candidate); no Chorus/Reverb 2/EQ/SSE committed PASS moves | §4.1-4.3 |
| correct-boundary leaves recorded as a measured fact | **NOT satisfied as a boundary verdict**: every row is NO_VERDICT under the fail-closed rule. Measured facts are recorded (A, A_early, B, A0, C, diagnostic D) but none positively declares a boundary | §4 |
| unmeasurable leaves NOT_RUN with reason | **satisfied** (Phaser synthetic corners, Chorus `melon`, Reverb 2 `grant_me`/`harp`/`novuo`, 7 SSE carriers, 10 model dirs without a runner); Phaser factory carriers A0 FAIL | §4.5 |
| live NC-C-shape control per boundary-dependent leaf | **partial**: no leaf has a RESOLVED boundary, so the NC-C "wrong boundary must FAIL" control is NOT_RUN per row (SSE keeps #136's committed NC-C and the 375 pre-roll FAILs here as data). A live NC-D control on the diagnostic leg is PASS on every row with a D leg | §6 |
| live A/B/C against the pinned oracle on every reachable leaf | **satisfied** (this run), with the platform caveat for SXT-023 in §2 | §2 |

This PR is `Part of #318`: the audit is complete and committed, but the
boundary is not positively resolved for any leaf except by earlier #136 work,
and the leaf-correction decisions belong to #12.

## 1. Question and method

The SXT-012 fixture renderer (`tools/render_fx_fixtures.py`,
`fixtures/render_fixture.py`) runs a silent settle of
`int(settle_s * 48000) // block_size` blocks before the first event and
discards it. Every committed sidecar audited here declares `settle_s = 0.25`
and `block_size = 32`, which gives **375 blocks**, re-derived per sidecar by
the audit.

A runner that reads the fixture's dry or bypass bus has to choose how many
blocks of silence to run through the effect model before the fixture audio.
There are two candidate boundaries:

* **0**: the engine's effect enters the first audio block in its `init()`
  state.
* **375**: the effect saw every settle block.

The method is `tools/probe_distortion_sse_settle_boundary.py`. It is reused
through small adapters and left untouched.

* **A** -- engine wet bus with a 375-block settle vs a 3750-block settle.
* **B** -- the carrier as rendered vs saved to `.fxp` and re-loaded through
  `loadPatch` into a fresh instance. For a real factory preset, this audit
  instantiates B as native `loadPatch` vs `savePatch` + `loadPatch`.
* **C** -- the leaf's frozen model run at each candidate pre-roll (0, the
  runner's own value, 375), graded by **the leaf's own declared comparator**
  (`compare_fx_reference.py`, `compare_chorus_reference.py`,
  `compare_reverb2_reference.py`, `compare_distortion_sse_reference.py`).
  The engine side is the **committed** wet bus. The comparator keeps L, R and
  mono metrics, the declared tail-region gate, fixed gain and zero alignment
  shift. The audit refuses unequal-length outputs, so nothing is truncated,
  normalized or time-warped.

The rule is fail-closed. It starts from the probe's (A and B byte-identical
=> RESOLVED, declared pre-roll 0) and is **tightened, never relaxed**: the
boundary is RESOLVED only if A, A_early and B are all byte-identical and the
A0 repeatability control did not fail. A measured difference or an A0 failure
makes the boundary UNRESOLVED, which makes the row NO_VERDICT. Unmeasured legs
are BLOCKED/NOT_RUN. C and D are recorded and never used to choose a
pre-roll. Added legs, all live:

* **A0** -- every live bus is rendered twice in fresh instances. Without it a
  nondeterministic engine would read as "the effect evolved".
* **A_early** -- settle 2 vs 375. A (375 vs 3750) cannot tell "no evolution"
  from "evolution that converged before block 375". The probe rule's reading
  of `fm_bass_1` shows why (§4.3). Each row also renders the all-off dry bus
  at the same settles; if the dry bus also differs, A_early is recorded as
  `CONFOUNDED_SYNTH_SIDE` and says nothing about the effect. It does so on
  **every** carrier (synth voices settle for about 120 blocks), so A_early
  as a gate can only withhold RESOLVED, and is stated as such.
* **D (diagnostic)** -- the model pre-rolled N blocks vs the live engine
  rendered with an N-block settle (N = 375, 3750), graded by the leaf's own
  comparator. Not an input to the boundary decision.

Limitations:

1. **Output invariance is not state invariance.** Byte-identical A/B outputs
   establish the tested output behaviour. They do not prove that every
   internal state variable stayed unchanged.
2. **The rule can only ever RESOLVE the 0 boundary.** A runner that pre-rolls
   the fixture settle is at best NO_VERDICT under this method, even when the
   engine measurably evolves. D is the evidence for that case, and it is
   diagnostic.

How the adapters run (`_leg`): each leg runs in a fresh interpreter. The
adapter imports the runner and overrides its pre-roll in memory only.

* `SETTLE_BLOCKS`: overridden for Delay/EQ, Chorus and Reverb 2.
* Phaser: the adapter overrides both its own and the inherited Chorus
  constant.
* Distortion SSE: the pre-roll goes through the existing
  `silent_preroll_blocks` keyword.

Every production leg reproduces the committed model render byte-for-byte,
except one carrier (§4.4). That check also validates the adapters.

## 2. Environment and oracle status

| item | value |
|---|---|
| host | AWS dispatch worker, `Linux-7.0.0-1010-aws-x86_64-with-glibc2.39` |
| python / numpy | 3.11.16 / 1.26.4 (the oracle's own interpreter; the oracle venv, nothing installed) |
| engine pin | `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy `1.4.HEAD.58914e59c` |
| manifest | `oracle/manifest.json` sha256 `874f50de...d8ef`; engine submodules sha256 `61823b18...a553` |
| oracle artifact | prebuilt (#232) `linux-x86_64`, installed artifact sha256 `d2cc7029...f571` == manifest prebuilt sha256 (`matches_manifest: true`) |
| invocation | `ORACLE_SURGE_DIR=~/.cache/gf180-surge-oracle/<pin>/linux-x86_64 LD_LIBRARY_PATH=<oracle cpython-3.11.16>/lib <oracle venv>/bin/python tools/audit_effect_settle_boundaries.py run --work <scratch>` |
| audit tool | git blob `b5f0b7a7...2a`, recorded in every per-leaf JSON with the runner/comparator blob ids |

Per-leaf JSON carries the full `environment` and `oracle` blocks, the sidecar
and sequence hashes, A/B bus sha256 values, both C metric sets (L/R/mono) and
the baseline deltas.

**Platform caveat (SXT-023 only).** The committed SXT-023 fixtures were
rendered on **darwin** (`surgepy.cpython-311-darwin.so` in the sidecar). The
live linux 375-block wet bus is not byte-equal to them
(`A_short_matches_committed_reference: false`; mono max diff 6.6e-5 for
`dexie`, 2.0e-2 for `metallic`, 1.3e-3 for `fm_bass_1`). A/B are internal to
this host's engine and stay valid, but they are not a statement about the
darwin buses that C uses. The Chorus, Reverb 2 and SSE fixtures match the live
render **byte for byte**, so for them A/B/C share one bus.

**Determinism control A0.** Every live bus is rendered twice in fresh
instances. All Delay/EQ/Chorus/Reverb 2/SSE buses are repeatable. All three
Phaser factory presets (`Phasey`, `Squelch`, `Sticky`) are **not**
repeatable, dry bus included (14 of 14 buses), so their A/B legs are
UNRESOLVED/NO_VERDICT and say nothing about the boundary.

## 3. Inventory and per-leaf table

`inventory.json` (source-derived, no import) holds the following:

| runner | leaves (chain occupants) | production pre-roll | source of the value | = fixture settle (375)? |
|---|---|---|---|---|
| `run_fx_model.py` | SXT-023 Delay (`dexie`, `metallic`), SXT-023 EQ (`fm_bass_1`) | **240** (= 0.16 s) | `SETTLE_BLOCKS = 240` | **no** -- and not 0 |
| `run_chorus_model.py` | SXT-028c Chorus (+ EQ in `fmcombo`, + Reverb1 in `alienappears`) | 375 | `SETTLE_BLOCKS = 375` | yes |
| `run_phaser_model.py` | SXT-028g Phaser | 375 | imported from `run_chorus_model.py` | yes (inherited) |
| `run_reverb2_model.py` | SXT-028f Reverb 2 (input = engine per-slot bypass bus) | 375 | `SETTLE_BLOCKS = 375` | yes |
| `run_distortion_sse_model.py` | SXT-028e-sse Distortion (SSE models) | 0 | `run(silent_preroll_blocks=0)` default | no -- measured 0 (#136) |

The full per-carrier table is `audit-table.md`, generated from the per-leaf
JSON. It is condensed here to the mono metrics. Each carrier is followed by
its sequence: **notes** = `seq-notes-coverage-v1`, **poly8** =
`seq-poly-8-v1`. "Committed" means the leaf's committed comparator record.

| leaf | carrier / seq | A (375 vs 3750) / B (load vs reload) | committed (pre-roll used) | pre-roll 0 | pre-roll 375 | row status |
|---|---|---|---|---|---|---|
| SXT-023 Delay | dexie / notes | DIFFERS / DIFFERS | **FAIL** -44.18 dBFS, 72,737.7 LSB (240) | FAIL -49.32 / 43,457.8 | **PASS** -75.00 / 3,821.3 | NO_VERDICT; source FAIL |
| SXT-023 Delay | metallic / notes | DIFFERS / identical | **FAIL** -33.48, 195,634.1 (240) | FAIL -33.46 / 209,141.8 | FAIL -50.77 / 22,069.7 | NO_VERDICT; source FAIL |
| SXT-023 EQ | fm_bass_1 / notes | identical / identical | **PASS** -120.04, 7.75 (240) | **FAIL** -72.15 / 14,262.7 | PASS -120.04 / 7.75 (byte-identical to 240) | NO_VERDICT; source FAIL |
| SXT-028c Chorus | alienappears / notes, poly8 | DIFFERS / identical | PASS -94.59, 530.4; -79.65, 1,230.1 (375) | PASS -94.44 / 530.4; -79.23 / 1,241.6 | PASS (= committed) | NO_VERDICT |
| SXT-028c Chorus | fmcombo / notes | DIFFERS / identical | PASS -98.42, 274.9 (375) | **FAIL** -15.50 / 1,051,694.1 | PASS (= committed) | NO_VERDICT |
| SXT-028c Chorus | fmcombo / poly8 | DIFFERS / identical | PASS -106.01, 114.4 (375) | **FAIL** -19.91 / 573,764.0 | PASS (= committed) | NO_VERDICT |
| SXT-028c Chorus | fmtwang2 / notes | DIFFERS / identical | PASS -101.42, 186.4 (375) | **FAIL** -26.39 / 346,572.9 | PASS (= committed) | NO_VERDICT |
| SXT-028c Chorus | fmtwang2 / poly8 | DIFFERS / identical | PASS -99.58, 177.2 (375) | **FAIL** -13.45 / 1,479,919.5 | PASS (= committed) | NO_VERDICT |
| SXT-028f Reverb 2 | moire1 / notes, poly8 | DIFFERS / identical | PASS -130.34, 1.67; -129.23, 2.63 (375) | **FAIL** -55.17 / 11,736.8; -45.07 / 33,029.1 | PASS (= committed) | NO_VERDICT |
| SXT-028f Reverb 2 | mystical / notes, poly8 | DIFFERS / identical | PASS -126.42, 2.88; -126.81, 4.00 (375) | **FAIL** -50.79 / 16,373.8; -51.26 / 17,321.5 | PASS (= committed) | NO_VERDICT |
| SXT-028f Reverb 2 | tacobell / notes, poly8 | DIFFERS / identical | PASS -118.66, 9.00; -114.32, 22.0 (375) | **FAIL** -51.99 / 20,923.3; -47.20 / 43,532.1 | PASS (= committed) | NO_VERDICT |
| SXT-028e-sse | syn-d0-m3 / poly8 (anchor) | identical / identical (live == #136 hashes) | PASS -113.64, 10.5 (0) | PASS (= committed) | **FAIL** -40.08 / 672,130.4 | NO_VERDICT (probe rule v1 read PASS; retained) |
| SXT-028g Phaser | phasey, squelch, sticky x 2 seqs | A0 FAIL (engine not repeatable) | none (no fixture) | NOT_RUN | NOT_RUN | NO_VERDICT (A/B only) |
| SXT-028g Phaser | 8 synthetic corners | not run | none | NOT_RUN | NOT_RUN | NOT_RUN |
| SXT-028c / SXT-028f | melon; grant_me, harp, novuo | not run | none (renders REFUSED by the 3x determinism gate) | NOT_RUN | NOT_RUN | NOT_RUN |

Each pair of figures in a row after "notes, poly8" is notes then poly8.

In the 0 and 375 columns, each cell is the comparator verdict, then mono
rms dBFS / max |diff| LSB (Q10.21). L/R metrics, spectral correlation, tail
gate, and per-channel deltas against the committed record are in the
per-leaf JSON (`baseline.deltas_vs_committed`). All are under the current
`fs-log-floor-v2` spectral definition, which matches every committed record
audited, so no delta mixes definitions.

## 4. Findings

### 4.1 F-318-1 -- `run_fx_model.py` pre-roll (240) matches neither candidate boundary (SXT-023 Delay + EQ)

* **Source fact.** The runner pre-rolls 240 blocks (0.16 s), on the
  assumption that the fixture dry WAV starts at engine block 240 (repeating a
  `fixtures/render_fixture.py` docstring). The renderer computes
  `int(0.25 * 48000) // 32 = 375` and the three sidecars declare
  `settle_s 0.25`, `block_size 32`. `source_reconciliation`: FAIL.
* **Measured engine behaviour (live).** The Delay engine bus is
  repeatable (A0) and its dry bus is settle-invariant, yet the wet bus differs
  between 375 and 3750 settle blocks (`dexie`, `metallic`; first difference at
  block 4 of audio). So the Delay effect's output depends on settle length:
  the engine does evolve during a silent settle. That is a measured output
  difference, not an identified mechanism. Delay's LFO state is a candidate
  (read from the committed diagnosis's own `Delay.h` citation, not measured
  here). `dexie` B also differs (native vs save+reload); `metallic` B does not.
  EQ (`fm_bass_1`): A identical, converged from settle 120 on, B identical.
* **The committed SXT-023 numbers depend on the pre-roll** (mono, committed
  record vs the same model at 375, both under `fs-log-floor-v2`):
  * **dexie (Delay)**: committed FAIL, -44.18 dBFS / 72,737.7 LSB, tail gate
    FAIL. At 375: **PASS**, -75.00 / 3,821.3, tail -49.1 dB. At 0: FAIL
    (-49.32 / 43,457.8).
  * **metallic (Delay)**: committed FAIL, -33.48 / 195,634.1. At 375: still
    FAIL (-50.77 / 22,069.7). At 0: FAIL (-33.46 / 209,141.8).
  * **fm_bass_1 (EQ)**: committed PASS (-120.04 / 7.75) is byte-identical at
    375. At 0 it FAILs (-72.15 / 14,262.7).
* **Diagnostic D.** Model pre-roll N vs live engine settle N: `dexie` PASSes
  at N = 375 and 3750 with pre-roll = settle and FAILs at 0 and at 240;
  `metallic` FAILs for every pre-roll, so the boundary does not explain the
  `metallic` miss; `fm_bass_1` PASSes at 240 and at settle, FAILs at 0.
  Caveat: the D buses are linux-live; the SXT-023 committed buses are darwin
  (§2). The committed-bus C numbers above are what the delta is against.
* **Bearing on `reports/sxt-023/delay-budget-diagnosis.md`.** That diagnosis
  feeds SXT-017 option 1 ("declare LFO->delay-time modulation outside the
  frozen delay scope") through this 240-block runner. The committed `dexie`
  miss is not invariant to the pre-roll (-44.2 -> -75.0 dBFS, FAIL -> PASS at
  375), so a scope cut decided on those numbers rests on a harness boundary
  that no measurement supports. **Not explained or fixed here.** The
  `metallic` FAIL persists.
* **Routed to #12 (SXT-017)** with both numbers (`escalation` in
  `fx.json`). Nothing is replaced: committed SXT-023 records, budgets and
  verdicts stand. A runner correction moves committed evidence and belongs to
  a separately reviewed follow-up.

### 4.2 F-318-2 -- Chorus and Reverb 2: the runner's 375 is consistent with the engine; no committed PASS moves

Both runners pre-roll the fixture settle (375, source check PASS).

* **A (live):** every Chorus and Reverb 2 carrier (all 12 rows) has A0
  repeatable, dry bus settle-invariant, and a **wet bus that differs between
  375 and 3750 settle blocks**. First differing audio block ranges from 0 to
  626 depending on carrier. These effects (modulated / long-tailed) advance
  state during a silent settle, unlike Distortion SSE.
* **C:** all 10 Chorus/Reverb 2 rows that discriminate FAIL at pre-roll 0 and
  PASS at 375 (the committed numbers); `alienappears` passes at both.
* **D:** pre-roll = settle passes at 375 **and** 3750 on all 12 rows; the
  production 375 FAILs against the engine at 3750 on 10 rows (expected: the
  engine state moved).
* **Reading, without over-claiming.** Nothing contradicts the runner's 375
  and every diagnostic is consistent with it, so the stop/escalate condition
  ("a committed PASS depends on the wrong boundary") is **not triggered** on
  these leaves. But the rule cannot positively resolve a non-zero boundary, so
  rows stay NO_VERDICT. This is a bounded diagnostic result, not a boundary
  proof. Output invariance is not state invariance.

### 4.3 F-318-3 -- the probe's A-and-B rule is not sufficient; SXT-028e-sse is reproduced but not re-resolved

* **SXT-028e-sse anchor.** Live A and B reproduce the committed #136 hashes
  (`deca8b7a...c845`, A and B identical; the fixture matches the live render
  byte for byte). C reproduces: pre-roll 0 -> 10.5 LSB / -113.64 dBFS PASS;
  375 -> 672,130.4 LSB / -40.08 dBFS FAIL. D agrees (pre-roll 0 passes at both
  settles; pre-roll = settle fails). But A_early (2 vs 375) differs and the
  dry bus differs too (`CONFOUNDED_SYNTH_SIDE`; wet and dry both converge from
  settle 120), so this audit's rule withholds RESOLVED: **NO_VERDICT**, with
  the probe-rule reading (RESOLVED/PASS) kept under `probe_rule_v1` and
  `probe_rule_v1_reading_changed`. #136's committed PASS and its committed
  NC-C are untouched; this audit does not supersede them. The comparator-level
  evidence that SSE's boundary is 0 stands as data, as does #136's A/B.
* **Why A alone is not enough: `fm_bass_1` (EQ).** The probe rule reads it
  RESOLVED/0 (A and B identical), which would call runner 240 FAIL. But the
  EQ model at pre-roll 0 FAILs against the engine (-72.15 dBFS) while 240 and
  375 PASS: the engine's EQ state evolved and converged before block 375, so
  A (375 vs 3750) is blind to it. The v1 reading is therefore retained but
  not trusted for any row.

### 4.4 F-318-4 -- `alienappears` committed model render does not reproduce byte-for-byte here (STALE for reproduction)

The production leg's render of `SXT-028c/alienappears` (both sequences)
differs from the committed `model__alienappears__*.f32.wav` on this host
(x86_64 Linux, numpy 1.26.4). Metrics agree to a relative 4.7e-7 and the
comparator verdict (PASS) reproduces. The cause was not diagnosed (a candidate,
not verified: numpy float32 `power`, noted in `.github/workflows/ci.yml`).
Every other production leg reproduces its committed model render
byte-for-byte; committed comparator metrics re-derive within 1e-9 relative.

### 4.5 F-318-5 -- coverage gaps

* **SXT-028g Phaser.** Committed fixtures: none; all 8 input records are
  `synthetic-corner` (NOT_RUN, `reports/SXT-028g/artifacts/oracle-status.json`).
  Live engine-side A/B ran on the three queued factory carriers (`Phasey`,
  `Squelch`, `Sticky`, census-blob verified): **A0 FAILs, including the dry
  bus** (the engine is not repeatable in fresh instances on these presets), so
  they are UNRESOLVED/NO_VERDICT and say nothing about the Phaser boundary or
  runner pre-roll (375, inherited). The cause of the nondeterminism was not
  investigated (candidate, unverified: a preset randomness source). C is
  NOT_RUN: no fixture buses.
* **Chorus `melon`; Reverb 2 `grant_me`, `harp`, `novuo`.** Pinned-engine
  renders were REFUSED by the 3x determinism gate; no fixture. NOT_RUN.
* **SSE:** the 7 non-anchor synthetic carriers were not re-derived (NOT_RUN;
  their committed records already use pre-roll 0).
* **Models with no `run_*_model.py`:** `reverb1`, `aw-4`, `aw-49`, `rf-rf-*`
  (5), `type-conditioner`, `type-distortion`: harness settle handling not
  audited (NOT_RUN, `inventory.json`).

## 5. Fail-closed behaviour (unit-tested)

`tests/test_effect_settle_boundaries.py` checks inventory completeness and
inherited pre-rolls, refusal of unaudited runners, the decision rule for
every A0/A/A_early/B combination, A/B failure => NO_VERDICT even when C
discriminates, unmeasured => BLOCKED, a measured wrong boundary => FAIL routed
to #12, reasoned NOT_RUN, rejection of refused/malformed/mixed-definition
comparator records and unequal-length outputs, A_early attribution, and the
committed records' status vocabulary, provenance and SSE worked example.

## 6. Negative controls

* **NC-C shape** (wrong boundary must FAIL): needs a RESOLVED boundary, so it
  is **NOT_RUN on every row** (reason recorded). The SSE anchor's wrong
  boundary (375) does FAIL (data above) and #136's committed NC-C stands.
* **NC-D (live, diagnostic):** a model pre-roll that does not equal the engine
  settle must FAIL the leaf's own comparator. PASS on every row where D is
  measured (`nc_d_control`; derived by `rederive` from recorded verdicts).
  It controls the diagnostic only, not the boundary decision.
* **Boundary-insensitive carriers** (`alienappears`): both pre-rolls pass, so
  no failing control can discriminate; recorded as a fact.

## 7. What this does NOT establish

* A positively resolved boundary for any leaf by this audit.
* That runner 375 is correct for Chorus/Reverb 2/Phaser (consistent, not
  proven) or that SXT-023's 240 is wrong in a state-level sense (it matches
  neither candidate; the committed `dexie` number moves at 375).
* Anything about the darwin SXT-023 fixtures from the linux A/B.
* Any explanation of the SXT-023 delay miss, RTL exactness, model-vs-reference
  agreement beyond the quoted comparator numbers, preset support or quality.

## 8. Reproduction

```sh
python3 tools/audit_effect_settle_boundaries.py inventory
# live (needs the pinned oracle importable; see section 2 for the invocation)
python3 tools/audit_effect_settle_boundaries.py run --work <scratch>
python3 tools/audit_effect_settle_boundaries.py table
python3 tools/audit_effect_settle_boundaries.py rederive
python3 -m pytest -q tests/test_effect_settle_boundaries.py tests/test_byte_frozen_sources.py
```

Model renders go to the scratch dir and are not committed; their sha256 and
the exact commands of every leg are in the per-leaf JSON.

**Follow-ups (not done here).** A positive method for a non-zero boundary
(A_early without the synth confound, e.g. an effect-only input tap); the SXT-023
runner correction and darwin/linux fixture parity (#12 decision); Phaser
nondeterminism and fixtures; remaining SSE carriers.
