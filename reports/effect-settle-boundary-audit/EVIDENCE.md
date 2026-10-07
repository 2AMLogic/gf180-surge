# #318 -- cross-runner settle-boundary audit

Date: 2026-10-07 · Issue: #318 · Epic: #3 · Escalation gate: SXT-017 (#12)
Source revision of the run: `e3a5e8891e46b9df8fbac0600a30e4b6a41d8ba5`
(clean tree) · Tool: `tools/audit_effect_settle_boundaries.py` · Tests:
`tests/test_effect_settle_boundaries.py`

**Claim scope.** This is a harness-boundary audit. It is not a fidelity
result, not a support claim, and not a musical-quality claim. It edits no
runner, frozen model, RTL, budget, fixture or committed leaf record. Every
committed number below is quoted from its committed record and left in place.

## 0. Status summary

| acceptance item (#318) | status | where |
|---|---|---|
| per-leaf table: runner pre-roll, engine A (measured), C both pre-rolls | **partial**: pre-roll and C measured on every leaf that has committed fixtures (15 carrier rows); **A/B BLOCKED** on every leaf except SXT-028e-sse | §3, `audit-table.md` |
| leaves on the wrong boundary: delta to the **committed** numbers stated | **SXT-023 (Delay/EQ): runner pre-roll is neither candidate boundary (source fact)**; deltas stated vs the committed records for both candidates, routed to #12 | §4.1 |
| leaves on the correct boundary recorded as a measured fact | **PASS for SXT-028e-sse only** (A/B measured in #136, C reproduced here); every other leaf BLOCKED | §4.3 |
| leaves that cannot be measured: NOT_RUN with reason | **done**: Phaser (8 rows), Chorus `melon`, Reverb 2 `grant_me`/`harp`/`novuo`, the other SSE carriers, and 10 effect-model dirs with no `run_*_model.py` | §3, §5 |
| live NC-C-shape control per boundary-dependent leaf | **PASS for SXT-028e-sse** (375 pre-roll FAILs, as required); **NOT_RUN elsewhere** -- the wrong boundary is not yet known | §6 |
| live A/B/C against the pinned oracle on every reachable leaf | **BLOCKED** -- pinned oracle unavailable on this host | §2 |

**Live acceptance of #318 is still outstanding.** The A/B legs must run on a
host with the pinned oracle (§8). Unit tests cannot replace them. This PR is
`Part of #318`. It does not close the issue.

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

The rule is fail-closed and is the probe's own (`decide_boundary`). The
boundary is **RESOLVED (pre-roll 0)** only when A and B are both measured and
both byte-identical. If either is measured and differs, the boundary is
**UNRESOLVED**, which makes the row NO_VERDICT. If neither is measured, the
row is **BLOCKED** on the named dependency. C is recorded and never used to
choose a pre-roll.

Two limitations are stated explicitly:

1. **Output invariance is not state invariance.** Byte-identical A/B outputs
   establish the tested output behaviour. They do not prove that every
   internal state variable stayed unchanged.
2. **The probe's rule can only ever RESOLVE the 0 boundary.** A runner that
   pre-rolls the full fixture settle can at best be NO_VERDICT under this
   method, even when A shows that the engine's effect does evolve during
   the settle. Positively establishing "375" would need a further leg, for
   example A at several settle lengths plus a model trajectory match. That
   leg is not designed here.

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
| host | AWS dispatch worker, `Linux-6.17.0-1019-aws-x86_64-with-glibc2.39` |
| python / numpy | 3.12.3 / 1.26.4 (worktree-local venv; numpy at the manifest's runtime version) |
| engine pin | `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71` (`oracle/manifest.json` sha256 `874f50de…d8ef`) |
| oracle | **UNAVAILABLE**: `ORACLE_PREBUILT_URL` and `ORACLE_SURGE_DIR` unset; no surgepy build under the manifest's default checkout. Nothing was installed. `oracle/fetch-and-build.sh --prebuilt` was **not** run, because it needs the private `ORACLE_PREBUILT_URL`. |
| consequence | A and B are **BLOCKED** on "pinned oracle unavailable on this host" for every leaf. The exception is SXT-028e-sse, whose A/B is the committed #136 record. The audit links that record to the committed anchor fixture by buffer hash (`deca8b7a…c845`). |

Each per-leaf JSON records its own `environment` and `oracle` blocks. Source
files are identified by git blob id, not sha256, so the audit creates no
unregistered byte-frozen pin (`docs/byte-frozen-sources.md`).

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

| leaf | carrier / seq | A / B | committed (pre-roll used) | pre-roll 0 | pre-roll 375 | row status |
|---|---|---|---|---|---|---|
| SXT-023 Delay | dexie / notes | BLOCKED | **FAIL** -44.18 dBFS, 72,737.7 LSB (240) | FAIL -49.32 / 43,457.8 | **PASS** -75.00 / 3,821.3 | BLOCKED; source FAIL |
| SXT-023 Delay | metallic / notes | BLOCKED | **FAIL** -33.48, 195,634.1 (240) | FAIL -33.46 / 209,141.8 | FAIL -50.77 / 22,069.7 | BLOCKED; source FAIL |
| SXT-023 EQ | fm_bass_1 / notes | BLOCKED | **PASS** -120.04, 7.75 (240) | **FAIL** -72.15 / 14,262.7 | PASS -120.04 / 7.75 (byte-identical to 240) | BLOCKED; source FAIL |
| SXT-028c Chorus | alienappears / notes | BLOCKED | PASS -94.59, 530.4 (375) | PASS -94.44 / 530.4 | PASS (= committed) | BLOCKED |
| SXT-028c Chorus | alienappears / poly8 | BLOCKED | PASS -79.65, 1,230.1 (375) | PASS -79.23 / 1,241.6 | PASS (= committed) | BLOCKED |
| SXT-028c Chorus | fmcombo / notes | BLOCKED | PASS -98.42, 274.9 (375) | **FAIL** -15.50 / 1,051,694.1 | PASS (= committed) | BLOCKED |
| SXT-028c Chorus | fmcombo / poly8 | BLOCKED | PASS -106.01, 114.4 (375) | **FAIL** -19.91 / 573,764.0 | PASS (= committed) | BLOCKED |
| SXT-028c Chorus | fmtwang2 / notes | BLOCKED | PASS -101.42, 186.4 (375) | **FAIL** -26.39 / 346,572.9 | PASS (= committed) | BLOCKED |
| SXT-028c Chorus | fmtwang2 / poly8 | BLOCKED | PASS -99.58, 177.2 (375) | **FAIL** -13.45 / 1,479,919.5 | PASS (= committed) | BLOCKED |
| SXT-028f Reverb 2 | moire1 / notes | BLOCKED | PASS -130.34, 1.67 (375) | **FAIL** -55.17 / 11,736.8 | PASS (= committed) | BLOCKED |
| SXT-028f Reverb 2 | moire1 / poly8 | BLOCKED | PASS -129.23, 2.63 (375) | **FAIL** -45.07 / 33,029.1 | PASS (= committed) | BLOCKED |
| SXT-028f Reverb 2 | mystical / notes | BLOCKED | PASS -126.42, 2.88 (375) | **FAIL** -50.79 / 16,373.8 | PASS (= committed) | BLOCKED |
| SXT-028f Reverb 2 | mystical / poly8 | BLOCKED | PASS -126.81, 4.00 (375) | **FAIL** -51.26 / 17,321.5 | PASS (= committed) | BLOCKED |
| SXT-028f Reverb 2 | tacobell / notes | BLOCKED | PASS -118.66, 9.00 (375) | **FAIL** -51.99 / 20,923.3 | PASS (= committed) | BLOCKED |
| SXT-028f Reverb 2 | tacobell / poly8 | BLOCKED | PASS -114.32, 22.0 (375) | **FAIL** -47.20 / 43,532.1 | PASS (= committed) | BLOCKED |
| SXT-028e-sse | syn-d0-m3 / poly8 (anchor) | **identical / identical** (#136) | PASS -113.64, 10.5 (0) | PASS (= committed) | **FAIL** -40.08 / 672,130.4 | **PASS** |
| SXT-028g Phaser | 8 synthetic corners | BLOCKED | none | NOT_RUN | NOT_RUN | NOT_RUN |
| SXT-028c / SXT-028f | melon; grant_me, harp, novuo | BLOCKED | none (renders REFUSED by the 3x determinism gate) | NOT_RUN | NOT_RUN | NOT_RUN |

In the 0 and 375 columns, each cell is the comparator verdict, then mono
rms dBFS / max |diff| LSB (Q10.21). L/R metrics, spectral correlation, tail
gate, and per-channel deltas against the committed record are in the
per-leaf JSON (`baseline.deltas_vs_committed`). All are under the current
`fs-log-floor-v2` spectral definition, which matches every committed record
audited, so no delta mixes definitions.

## 4. Findings

### 4.1 F-318-1 -- `run_fx_model.py` pre-roll matches neither candidate boundary (SXT-023 Delay + EQ)

* **Source fact, independent of A/B.** The runner pre-rolls 240 blocks
  (0.16 s). Its docstring and comment assume that "the fixture dry WAV starts
  at engine block 240". That assumption repeats the `fixtures/render_fixture.py`
  docstring ("0.25 s (240 blocks)"). But the renderer computes
  `int(0.25 * 48000) // 32 = 375`, and the three SXT-023 sidecars declare
  `settle_s 0.25` and `block_size 32`. Under the probe's rule, 240 can never
  be declared the boundary. Row status is still **BLOCKED** because A/B are
  unmeasured. The separate `source_reconciliation` check is **FAIL**.
* **The committed SXT-023 numbers depend on it.** All three carriers'
  model outputs differ at 0, 240 and 375. The exception is EQ, where 240 and
  375 are byte-identical because the EQ ramps converge within 240 blocks.
  Deltas against the committed records, mono:
  * **dexie (Delay)**: committed FAIL (-44.18 dBFS / 72,737.7 LSB, tail gate
    FAIL). At 375: **PASS** (-75.00 dBFS / 3,821.3 LSB, tail -49.1 dB).
    Delta: -30.8 dB rms. At 0: FAIL (-49.32 / 43,457.8).
  * **metallic (Delay)**: committed FAIL (-33.48 / 195,634.1). At 375:
    still FAIL (-50.77 / 22,069.7, max |diff| and tail gate). Delta: -17.3 dB
    rms. At 0: FAIL (-33.46 / 209,141.8).
  * **fm_bass_1 (EQ)**: committed PASS (-120.04 / 7.75) is unchanged at 375.
    At 0 it **FAILs** (-72.15 / 14,262.7).
* **Bearing on `reports/sxt-023/delay-budget-diagnosis.md`.** That diagnosis
  feeds SXT-017 option 1, "declare LFO→delay-time modulation outside the
  frozen delay scope". It attributes the delay miss to a rate-invariant
  "LFO-presence" error. Its numbers were produced through this 240-block
  runner. This audit **does not** claim to explain that miss: the boundary
  is unmeasured, and C is not used to choose. It does record that the
  committed dexie miss is not invariant to the pre-roll (-44.2 → -75.0 dBFS
  at the fixture-settle candidate). So a scope cut decided on those numbers
  would rest on an unmeasured harness boundary. A **candidate** mechanism,
  read from the diagnosis's own citation of `Delay.h` and not measured here:
  `LFOval = 0.99f*LFOval ± …` per block is an AR(1) state that starts at its
  init value. After 240 blocks it still carries about 0.99^240 ≈ 9 % of its
  initial transient; after 375 blocks, about 2 %.
* **Routed to #12** with both numbers. Nothing is replaced: the committed
  SXT-023 records, budgets and verdicts stand as committed. A corrective
  change to the runner would move committed evidence. It belongs in a
  separately reviewed follow-up after the live A/B, with these old and new
  numbers retained.

### 4.2 F-318-2 -- Chorus and Reverb 2 committed PASSes depend on an unmeasured boundary

Both runners pre-roll the full fixture settle (375, source check PASS), and
their boundary is **BLOCKED**:

* **Reverb 2.** All 6 committed PASS rows FAIL at pre-roll 0 (-45 to -55
  dBFS).
* **Chorus.** 4 of the 6 committed PASS rows FAIL at pre-roll 0 (`fmcombo`,
  `fmtwang2`, -13 to -26 dBFS). `alienappears` (Reverb1 → Chorus in global
  slots) PASSes at both pre-rolls. Its model output does differ (-94.44 vs
  -94.59 dBFS), but this comparator cannot tell the two boundaries apart on
  that carrier.

So 10 committed PASS rows hold only if the engine's effect does evolve
during the silent settle. That is exactly what A measures, and A is
unmeasured. If A shows byte-identity on these carriers, as it did for
Distortion SSE, these runners are on the wrong boundary and those PASSes
FAIL. That is the issue's stop/escalate condition. This audit cannot
trigger it, but it has made it measurable on the first oracle host.

C is recorded, not used. For example, the 375 leg of Reverb 2 agrees to
1.7–22 LSB while the 0 leg is off by 10^4 LSB. That pattern is not a
boundary determination, and nothing is selected by it. Even a measured A
showing engine evolution would leave these rows NO_VERDICT under the probe's
rule (§1, limitation 2). The method gap is part of the outstanding work.

### 4.3 F-318-3 -- SXT-028e-sse: correct boundary, reproduced (PASS)

The #136 worked example is reproduced by the audit's adapter and the leaf's
own comparator against the committed anchor fixture:

| pre-roll | mono max / rms | result |
|---|---|---|
| 0 | 10.5 LSB / -113.64 dBFS | PASS |
| 375 | 672,130.4 LSB / -40.08 dBFS | FAIL |

Those values match `reports/SXT-028e-sse/artifacts/settle-boundary.json`.
The committed A/B record is bound to the committed fixture by buffer hash.
Runner pre-roll 0 equals the measured boundary: **PASS**, as a measured fact
for this leaf on its anchor. The other SSE synthetic carriers were not
re-derived here (NOT_RUN, bounded audit). Their committed records already
run pre-roll 0.

### 4.4 F-318-4 -- `alienappears` committed model render does not reproduce byte-for-byte here (STALE for reproduction)

On this host (x86_64 Linux, numpy 1.26.4), the production leg's render of
`SXT-028c/alienappears` (both sequences) differs from the committed
`model__alienappears__*.f32.wav`. The metrics agree to a relative 4.7e-7,
and the comparator verdict (PASS) is reproduced. The baseline row is
therefore **STALE** for byte reproduction, and every alienappears delta in
the JSON is against the committed record.

The cause was not diagnosed. One candidate, not verified: the Reverb1
coefficient plane's numpy float32 `power`, whose build dependence is noted
in `.github/workflows/ci.yml`. Every other carrier's production leg
reproduces its committed model render byte-for-byte. Committed comparator
metrics re-derive within 1e-9 relative, with deviations of at most 6e-16
from float64 FFT/RMS rounding.

### 4.5 F-318-5 -- coverage gaps (NOT_RUN, with reasons)

* **SXT-028g Phaser.** There are no committed fixture buses. All 8 input
  records are `synthetic-corner`, which the runner refuses for a reference
  render, and every SXT-028g leg is NOT_RUN
  (`reports/SXT-028g/artifacts/oracle-status.json`). Its 375 pre-roll is
  inherited from Chorus, so it shares the F-318-2 dependence once it has
  fixtures.
* **Chorus `melon`; Reverb 2 `grant_me`, `harp`, `novuo`.** The pinned-engine
  renders were REFUSED by the 3x determinism gate (committed
  `render-refusals.txt`), so there is no fixture.
* **Effect models with no `run_*_model.py` runner:** `reverb1` (own
  SXT-024 harness; also a chain occupant covered by the Chorus rows),
  `aw-4`, `aw-49`, `rf-rf-*` (5), `type-conditioner`, `type-distortion`.
  Their own harnesses' settle handling is **not audited** (NOT_RUN), never
  assumed correct (`inventory.json → not_runner_reached_models`).

## 5. Fail-closed behaviour (unit-tested)

`tests/test_effect_settle_boundaries.py` (45 tests) checks the following:

* inventory completeness and the source-derived pre-roll of each runner,
  including the inherited Phaser constant;
* a refusal on an unaudited runner or an unclassified model dir;
* the decision rule for every A/B combination;
* A/B failure gives NO_VERDICT even when C discriminates;
* unmeasured A/B gives BLOCKED, never PASS;
* a measured wrong boundary gives FAIL and routes to #12;
* a missing fixture gives a reasoned NOT_RUN;
* refused or malformed comparator records, missing channels or metrics,
  mixed spectral definitions and unequal-length outputs are rejected;
* the committed records keep the status vocabulary, and no row is PASS
  without measured A and B;
* the SSE row reproduces the worked example.

## 6. Negative controls

* **SXT-028e-sse NC-C shape (live, offline-measurable):** the wrong
  boundary (375) **FAILs** the declared comparison, so the control is
  **PASS** (`nc_c_control`).
* **Every other leaf:** **NOT_RUN**. Which boundary is wrong is not known
  until A/B are measured. Each candidate's comparator verdict is already
  recorded under C, so the control is designated, not re-run, once A/B
  resolve. For `alienappears`, both pre-rolls PASS, so an NC-C there would
  not discriminate (recorded).
* **The audit's own controls** (unit tests above): a doctored inventory and
  doctored records fire the refusals.

## 7. What this does NOT establish

* Any leaf's engine-side boundary other than SXT-028e-sse's anchor (A/B
  BLOCKED).
* That the SXT-023 runner is wrong in a *measured* sense. Only the source
  fact (neither candidate) is established.
* That the 10 boundary-dependent Chorus and Reverb 2 PASSes are right or
  wrong.
* Any explanation of the SXT-023 delay miss.
* RTL exactness, model-vs-reference agreement beyond the quoted comparator
  numbers, preset support, or musical quality.

## 8. Reproduction and outstanding live acceptance

```sh
python3 tools/audit_effect_settle_boundaries.py inventory
python3 tools/audit_effect_settle_boundaries.py run --work <scratch>   # all runners
python3 tools/audit_effect_settle_boundaries.py table
python3 -m pytest -q tests/test_effect_settle_boundaries.py
```

Model renders go to the scratch dir and are not committed. Their sha256 and
the exact model/comparator commands for every leg are in the per-leaf JSON
(`C_model_boundary_vs_engine.legs.*`).

**Outstanding.** Run the same `run` on a host with the pinned oracle
(`oracle/fetch-and-build.sh --prebuilt`, #232). The live A/B adapter
(`live_ab_factory`: A at 0.25 s vs 2.5 s settle, a dry-bus diagnostic, B as
native load vs save+reload) **has never been exercised**, because no oracle
was available here. Its first run is itself evidence to retain. Then route
the result:

* If A/B resolve to 0 on the Chorus or Reverb 2 carriers, the F-318-2 rows
  FAIL. Stop and escalate to #12 with both numbers.
* If A shows that the effect evolves during the settle, those rows stay
  NO_VERDICT until the method gap (§1, limitation 2) is closed.

Either way, the SXT-023 runner needs a reviewed corrective follow-up. It
carries the old and new numbers above and the #12 decision.
