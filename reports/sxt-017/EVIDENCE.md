# SXT-017 evidence record — DRAFT bundle comparison + predictions (issue #12, bundle stage)

> **STAGE 2 ADDENDUM (2026-09-25, branch `feature/issue-12`).** SXT-016
> (#11) has since landed, so the cost leg this record calls
> `[PENDING-SXT-016]` has now been evaluated. **Read
> [§8 Stage 2](#8-stage-2-addendum-2026-09-25--cost-closure-leg-sxt-016-has-landed)
> at the bottom before using anything in §1–§7**: several statements below
> ("`reports/sxt-016/` does not exist", "no measured basis exists") were true
> on 2026-09-20 and are now STALE. Sections §1–§7 are preserved unedited as
> the record of what the bundle stage established on its own.

Branch: `loom/sxt-017-profile-draft` · Issue: #12 (SXT-017, **bundle stage
only**) · Date: 2026-09-20

**Claim discipline.** This record covers the *bundle-stage* portion of
SXT-017 only: a versioned candidate-bundle comparison, a deterministic
per-preset predictor, and DRAFT predictions over the committed corpus and
proposal slates. **Nothing is frozen.** Freezing profile v1 requires
SXT-013's human listening (favorites selection + frozen fidelity policy),
SXT-014's listening labels, and SXT-016's measured cost probes. As of this
record: the favorites selection is BLOCKED on human listening (only
diversity-proposal slates exist; the only listening session is a machine
dry-run), SXT-014 labels are BLOCKED on human listening, and
`reports/sxt-016/` **does not exist** — every cycle/bandwidth number below
carries a **[PENDING-SXT-016]** marker and no number was invented. No
fidelity, preset-quality, musical-usefulness, or hardware claim is made
anywhere; predicted "supported" means only "structurally within the DRAFT
bundle's declared gates/budgets".

Deliverables: `contracts/profile-v1-DRAFT.md` (bundle comparison + selected
DRAFT + revision triggers),
`contracts/profile-v1-bundle-DRAFT.json` (11 validated bundle specs),
`tools/profile_predict.py` (byte-deterministic predictor),
`reports/sxt-017/predictions/*.json` (5 headline artifacts, per-preset, all
3,561 entries each) and `predictions/variants/*.json` (7 single-dimension
variant summaries), `reports/sxt-017/negative-controls.txt`,
`tests/test_sxt017_predict.py`.

## 1. Issue-#12 acceptance mapping

| #12 acceptance item | Status (bundle stage) | Evidence |
|---|---|---|
| Bundle comparison uses complete-preset recovery of the frozen favorites set; individual feature frequencies alone do not decide | **PASS as DRAFT apparatus; FREEZE BLOCKED-on-human-listening** | The comparison is complete-preset-level: a preset counts for a bundle only if every active feature of its original normalized graph fits at once (`tools/profile_predict.py` gates; per-preset statuses with reasons in `predictions/*.json`). The Airwindows "top-12" selection is the only frequency-ranked input, and the comparison shows its limits explicitly (§4 Pareto: AW selection flips no status inside tier C; the committed slate coverage numbers, not frequencies, drive selection). The *frozen favorites set does not exist* — the coverage basis is the three SXT-013 **proposal** slates, each stamped `essentiality: UNVERIFIED`; substituting them for the frozen set at freeze time is prohibited by this record. |
| Every budget names clock, memory implementation, and measured/estimated basis (else it is not a fit claim) | **PARTIAL / [PENDING-SXT-016]** | Every budget names its basis and kind: clock 480 MHz = SXT-015 *placeholder*; cycles = cost profile `placeholder-v0` (*placeholder*); on-chip state/`1 MiB` unverified-class state = SXT-015 *placeholder* model at float32 words; 800 MB/s external bandwidth = SXT-015 *placeholder*; reserve = SXT-015 *policy*. No measured basis exists (SXT-016 not run), therefore **no fit claim is made**: cycle closure is declared `not_gated_pending_sxt_016` in every bundle spec and cycles are published as columns only. This is exactly the acceptance item's "else" branch: without a measured basis, the artifact claims no fit. |
| Predictions cover all 641 factory and 2,920 contributor entries, favorites highlighted separately | **PASS** | Each headline artifact carries exactly 3,561 per-preset records (641 factory + 2,920 contributor; tested in `tests/test_sxt017_predict.py::test_coverage_all_entries`), each with one status + machine-readable reasons; per-bank counts and three per-slate coverage sections (with predicted-supported path lists) are in every artifact. Adapted presets are counted separately and never merged into supported (tested; NC6). |
| Any gap vs the 80% wet-preset goal is resolved by a visible contract revision recorded here, not by redefining "supported" | **GAP RECORDED (visible); REVISION NOT_RUN (owner decision, inputs pending)** | Predicted coverage of B4-broad vs the 205/256 goal: balanced 72/256, factory-lean 127/256, contributor-lean 77/256; even the R0 ceiling reaches only 184/202/189. The gap, its dominant causes (582 MSEG/Formula-gap unresolved, 212 polylimit>16 adapted, 87 audio-input, slate diversity spread), and six contract-revision triggers are recorded in `contracts/profile-v1-DRAFT.md` §6/§8. "Supported" was not redefined; adapted stays excluded. The stop/escalate decision belongs to the product owner at the freeze stage once #8/#9/#11 land (issue #12's premise is unmet; freezing is blocked regardless). |
| Negative control: re-running the comparison with a deliberately inflated budget must change the selected bundle; otherwise the comparison is not sensitive and must be fixed | **PASS** (and one honest insensitivity finding) | `negative-controls.txt` NC1: starting from the 4-instance candidate, doubling `fx_instance_limit` 4→8 in a **/tmp bundle spec** changes the predicted supportable set 1,645→1,685 and balanced-slate coverage 68→72 (cross-checked equal to the committed limit-8 artifact). Recorded finding (NC2): inflating again 8→16 changes nothing within tier C — all 31 over-8 presets also fail the FX class gate — so the instance budget binds between 4 and 8 in this context, not above it; likewise the B1 floor pair 4→8 is insensitive (other gates dominate). The comparison is sensitive where its dimensions bind; the insensitive contexts are committed as visible variant rows rather than hidden. |

## 2. Freeze status

**Freeze of profile v1: BLOCKED.** Three independent blockers, all
normative:

1. SXT-013 human listening (favorites set + fidelity policy freeze) — not
   started by a human (BLOCKED-on-human-listening).
2. SXT-014 essential/optional labels — not decided (BLOCKED-on-human-listening).
3. SXT-016 measured cost probes — `reports/sxt-016/` absent; all budgets
   placeholder-based ([PENDING-SXT-016]).

Accordingly `contracts/profile-v1-DRAFT.md` is headed **"NOT FROZEN"**, the
bundle file's status field is `DRAFT-NOT-FROZEN` (the predictor refuses
anything else), and this PR deliberately says **"Advances #12 (bundle
stage)"** — it does not close #12.

## 3. The 80%-goal feasibility statement (with the essentiality caveat)

On the committed proposal slates, **no bundle — B1 through B4 or the R0
ceiling — predicts ≥205/256 coverage**, so a profile v1 freeze against these
proposals would require either a favorites set that fits or an explicit
owner-approved revision of the goal/scope (recorded as triggers, not
decided here). The caveat that governs this entire statement: the slates
are diversity-maximized *proposals* and essentiality is unverified — a
human-selected favorites set concentrated in the supported region would
score differently. Predicted structural coverage of a proposal slate is not
a musical outcome and not a favorites outcome. Details and the two-readings
separation: `contracts/profile-v1-DRAFT.md` §6.

## 4. Negative-control results (live; `negative-controls.txt`)

| Control | Targeted failure | Result |
|---|---|---|
| NC1 inflated budget (instance limit ×2 in a /tmp spec) | an insensitive comparison that cannot discriminate bundles | **PASS** — supported set changes 1,645→1,685, balanced slate 68→72; inflated run byte-consistent with the committed limit-8 artifact |
| NC2 8→16 inflation; B1 4→8 pair | (self-check) overclaiming sensitivity | **Recorded finding** — not binding in those contexts (class gates dominate); committed as visible variants, not hidden |
| NC3 unknown bundle key (`fx_instance_limt`) | silently ignoring spec errors | **PASS** — exit 2, named-key refusal |
| NC4 unknown allowlist name (`WavetableX`) | an allowlist typo becoming a silent always-false gate | **PASS** — exit 2, valid names listed |
| NC5 tampered slate census SHA | predictions against corrupted provenance | **PASS** — exit 2, integrity refusal |
| NC6 adapted-vs-supported partition | adapted presets inflating supported counts | **PASS** — statuses partition 3,561 in every headline artifact; adapted excluded from supported (also test-enforced) |
| Determinism | non-reproducible predictions | **PASS** — repeated runs byte-identical (`cmp` clean vs committed `B4-broad.json`; test-enforced) |

## 5. Headline numbers (DRAFT predictions; no support/fidelity/quality claim)

| Bundle | Supported F/C | balanced / factory-lean / contributor-lean slates |
|---|---|---|
| B1-core-narrow | 0 / 6 | 0 / 0 / 0 |
| B2-core-wet-plan3 | 0 / 8 | 0 / 0 / 1 |
| B3-ext-voice-fx | 464 / 808 | 53 / 98 / 53 |
| **B4-broad (selected DRAFT)** | **549 / 1,136** | **72 / 127 / 77** |
| R0-ceiling-reference (non-product) | 600 / 2,116 | 184 / 202 / 189 |

All cycles/RAM/bandwidth columns: SXT-015 `placeholder-v0` —
**[PENDING-SXT-016]**.

## 6. What remains unproved / NOT_RUN

- Everything freeze-related: favorites selection, essentiality labels,
  policy freeze, profile freeze (all BLOCKED as above).
- Any measured cost: area, timing, power, cycles, memory bandwidth
  (SXT-016 NOT_RUN); no fit claim exists.
- Any fidelity, RTL/model equality, preset-support, or musical-quality
  result (SXT-020+ NOT_RUN).
- Filter-subtype-level and waveshaper-algorithm-level gating (subtypes are
  engine-declared-set; per-algorithm costs pending SXT-016) — recorded as
  revision trigger 6.
- Single-dimension isolation for the oscillator-family and FX-tier
  dimensions is only implied by the B1→B2→B3→B4 ladder (multi-delta steps);
  the committed variants isolate pool/instances/unison/filters/AW. More
  isolating variants are one spec away if the freeze stage needs them.

## 7. Reproduce

```sh
python3 tools/profile_predict.py \
  --bundle contracts/profile-v1-bundle-DRAFT.json --bundle-id B4-broad \
  --slate reports/sxt-013/candidates/slate-256-balanced.json \
  --slate reports/sxt-013/candidates/slate-256-factory-lean.json \
  --slate reports/sxt-013/candidates/slate-256-contributor-lean.json \
  --out /tmp/B4.json && cmp /tmp/B4.json reports/sxt-017/predictions/B4-broad.json
pytest tests/test_sxt017_predict.py
# negative controls: see reports/sxt-017/negative-controls.txt header
```

Inputs: `corpus/normalized/graphs.jsonl` (sha256
`c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715`),
`model/resources/` (SXT-015), `reports/sxt-013/candidates/slate-256-*.json`
(proposals; integrity-checked per run). No oracle/engine build required —
all inputs are committed data.

---

## 8. STAGE 2 ADDENDUM (2026-09-25) — cost-closure leg, SXT-016 has landed

**Claim discipline (unchanged).** Every number in this addendum is an
ESTIMATE under named assumptions (`probes/common.py` `TECH`); no gf180mcu
synthesis, place-and-route, timing signoff, or hardware run stands behind
any of it. Nothing is frozen. No fidelity, preset-support, preset-quality,
or musical claim is made or advanced.

Deliverables: `tools/profile_budget.py` (cost-closure gate),
`tools/profile_budget_controls.py` (live controls),
`reports/sxt-017/cost-closure.json` (120-row grid, per-bundle),
`reports/sxt-017/negative-controls-budget.txt`,
`tests/test_sxt017_budget.py` (20 tests),
`contracts/profile-v1-DRAFT.md` §12,
`decision-records/0011-profile-v1-budget-escalation.md`.

### 8.1 What changed versus §1–§7

| §1–§7 statement | Status on 2026-09-25 |
|---|---|
| "`reports/sxt-016/` **does not exist**" | **STALE** — 76 validated probe records + `worked-bundles.json` exist |
| "No measured basis exists … therefore no fit claim is made" | **Still true, for a different reason** — an estimated basis now exists and is named per row, and it still yields **no** `within_budget` row anywhere in the grid |
| "cycles gate nothing in this DRAFT" | Unchanged for `tools/profile_predict.py`; the cost gate lives in the separate stage-2 tool, so the bundle-stage artifacts stay byte-stable |
| SXT-013 listening / SXT-014 labels blocked | **Unchanged** — #8 and #9 closed on their *apparatus*; the selection, the policy freeze, and the labels are still `BLOCKED-on-human` in their own evidence records |

### 8.2 Issue-#12 acceptance mapping, stage 2

| #12 acceptance item | Status | Evidence |
|---|---|---|
| Bundle comparison uses complete-preset recovery of the frozen favorites set; individual feature frequencies alone do not decide | **PASS as apparatus; BASIS STILL PROVISIONAL** | The cost gate ranks bundles on complete-preset recovery of the primary preferred-preset slate with corpus-wide recovery as tiebreak (`selection_rule` in the artifact); no feature frequency enters the rule. The *frozen favorites set still does not exist*, so the basis is a proposal slate stamped `essentiality: UNVERIFIED`, and the artifact says so in `goal_test.basis_note`. |
| Every budget names clock, memory implementation, and measured/estimated basis (else it is not a fit claim) | **PASS** | Every one of the 120 grid rows carries `clock_hz`, `memory_implementation` + its `A-EXT-*` assumption text, `multiplier` + its `A-DSP-*` assumption text, and `basis` = "ESTIMATE under named assumptions … NOT a measurement". Test-enforced (`test_every_grid_row_names_clock_memory_and_basis`). Consistent with the "else" branch: because the basis is estimated and components remain unpriced, **no fit claim is made** — no row is `within_budget`. |
| Predictions cover all 641 factory and 2,920 contributor entries, favorites highlighted separately | **PASS (inherited, cross-checked)** | Stage 2 consumes the bundle stage's per-preset statuses and its supported counts are asserted equal to the committed `predictions/*.json` totals per bundle and per slate (`test_supported_counts_agree_with_the_bundle_stage_artifacts`). Adapted presets remain excluded (`test_adapted_presets_are_absent_from_every_supported_count`). |
| Any gap vs the 80% wet-preset goal is resolved by a visible contract revision recorded here, not by redefining "supported" | **GAP RECORDED + ESCALATED (visible); REVISION NOT TAKEN (owner decision)** | `goal_test`: 0/256 supported on the balanced slate vs a 205/256 threshold, `goal_met: false`, `stop_escalate: true`, reasons `["preferred_preset_goal_missed", "selected_bundle_carries_no_fit_claim"]`. Escalation with five quantified options in `decision-records/0011`. "Supported" was not redefined, the goal was not lowered, adapted was not counted, and no bundle was declared to fit. |
| Negative control: re-running the comparison with a deliberately inflated budget must change the selected bundle; otherwise the comparison is not sensitive and must be fixed | **PASS** | NC-B1 ladder: budget ×1 → `B1-core-narrow`, ×2 → `B2-core-wet-plan3`, ×21 → `B3-ext-voice-fx`, ×40 → `B4-broad` — four distinct selections over the same inputs. Test-enforced (`test_inflated_budget_changes_the_selected_bundle`). Recorded companion finding NC-B5: inflation never produces a *fit claim*, because the blocker is unpriced components, not budget. |

### 8.3 Headline result

| Bundle | corpus / balanced slate | worst probe-priced lower bound (480 MHz, M32, E3) | verdict | lane floor |
|---|---|---:|---|---:|
| B1-core-narrow | 6 / 0 | 3,216 | NO_VERDICT | 1 |
| B2-core-wet-plan3 | 8 / 0 | 4,471 | overflow (placeholder-dependent) | 1 |
| B3-ext-voice-fx | 1,272 / 53 | 137,607 | **OVERFLOW (conclusive)** | ≥20 |
| B4-broad | 1,685 / 72 | 270,805 | **OVERFLOW (conclusive)** | ≥39 |
| R0-ceiling-reference | 2,716 / 184 | 270,805 | **OVERFLOW (conclusive)** | ≥39 |

DSP budget at that corner: 7,002 cyc/frame. Selected bundle:
`B1-core-narrow`, `fit_claim: false`, `stop_escalate: true`. Full analysis:
`contracts/profile-v1-DRAFT.md` §12.

### 8.4 What stage 2 does NOT establish

- Any frozen profile, budget, or product decision — the freeze is escalated,
  not made, and SXT-013 listening / SXT-014 labels remain blocked.
- Any measured cost, area, timing, power, or gf180mcu feasibility result;
  every number is an estimate under `A-CLK`/`A-DSP-*`/`A-EXT-*`/`A-SCHED-1`.
- Any claim that a `NO_VERDICT` row would close if its components were
  priced. `NO_VERDICT` is reported as NO_VERDICT, never as a pass.
- Any lane schedule. `lanes_required_floor_*` assumes perfectly divisible
  work and is a floor for decision-making, not a design.
- Any statement about presets outside each bundle's predicted-supported set;
  adapted and unsupported presets are not costed.

### 8.5 Reproduce (stage 2)

```sh
python3 tools/profile_budget.py \
  --slate reports/sxt-013/candidates/slate-256-balanced.json \
  --slate reports/sxt-013/candidates/slate-256-factory-lean.json \
  --slate reports/sxt-013/candidates/slate-256-contributor-lean.json \
  --primary-slate slate-256-balanced \
  --out reports/sxt-017/cost-closure.json     # byte-identical to the committed file
python3 tools/profile_budget_controls.py      # rewrites negative-controls-budget.txt
python3 -m pytest -q tests/test_sxt017_budget.py
```

Additional inputs beyond §7: `reports/sxt-016/probes/` (76 records, phase
pin 32), `probes/` (SXT-016 package), `model/resources/accounting.py`. No
oracle/engine build required.

---

## 9. ACCOUNTING-INPUT REVISION (2026-09-26) — SXT-028b Conditioner state, issue #117

**What changed.** Nothing in this record's method, tooling, gates, or
verdicts. One SXT-015 input moved: the `no_long_buffer` per-instance state
of the **Conditioner** class went from the shared conservative placeholder
of **8,192 B** to the **2,444 B** measured by the SXT-028b frozen model
(`reports/SXT-028b/artifacts/buffer-requirement.json`,
`on_chip_state.bytes`, model revision `8dcd09c8…`). Every other
`no_long_buffer` class still carries the 8,192 B placeholder and its
`class_state_unverified` flag.

**Effect on the committed artifacts.** All five headline predictions and
all seven variant summaries were regenerated with the §7 recipe. The whole
diff is the `on_chip_state_bytes` column of the **720 presets whose graph
carries at least one configured Conditioner slot** (707 with one instance,
9 with two, 4 with three — counted over `corpus/normalized/graphs.jsonl`
independently of the predictor); each instance drops the column by exactly
5,748 B. A configured-but-`fxd`-disabled slot still holds state, so all 720
move, not just the 672 whose Conditioner also processes. No other column,
aggregate input, provenance field, or reason code changed.

**Stop/escalate check (original issue's clause): NOT TRIGGERED.** Per-preset
supported/adapted/unsupported/unresolved status is **identical** for all
3,561 entries in every one of the 12 artifacts; `totals`, `per_bank`,
`slate_coverage`, and every per-preset `reasons` list are unchanged. §5's
headline numbers therefore stand as written, and nothing was routed to #12.
Directionally this can only ever relax the `on_chip_ram_bytes` gate, never
tighten it — a Conditioner preset gets cheaper, not dearer.

**What this does NOT establish.** It is a state-accounting correction, not
a measurement of this repository's hardware: the cycle column for
Conditioner remains the shared `cyc_fxgeneric_frame` placeholder, no bundle
gained a fit claim, no preset became supported, and the model-vs-pinned-Surge
agreement leg of SXT-028b remains BLOCKED in its own record. Not
regenerated here, and still stale on `main` for reasons predating this
change: `reports/sxt-015/*` (SXT-012 sequence-fixture growth) and
`reports/coverage-v1/*` (leaf-evidence hash drift). Re-running
`tools/publish_coverage.py` with the two revised input pins produces output
that differs from the pre-change run **only** in the two recorded input
sha256 values — no coverage verdict moved.

---

## 10. ACCOUNTING-INPUT RECONCILIATION (2026-09-27) — SXT-028f Reverb 2 per-sample traffic, issue #127

**STOP/ESCALATE EVALUATED → FIRED. The correction is NOT taken here and NOT
banked; it is routed to #12. No artifact in this record changed.** Every
number in §10.2 is a *measured prediction of what the correction would do*,
produced by running the committed tools with the corrected row into `/tmp`,
not by rewriting anything under `reports/`.

### 10.1 The input in question

`model/resources/fx_classes.py`'s per-sample external **traffic** row for the
`reverb2` class carries **40 reads / 18 writes**. SXT-028f's frozen model
measures **29 / 17** with its own `ext_read`/`ext_write` counters and derives
the same figure from the pinned structure (`model/effects/type-reverb 2/`
`reverb2_model.py` `per_sample_transactions()`;
`reports/SXT-028f/artifacts/buffer-requirement.json` `external_traffic`):

| leg | reads | writes |
|---|---:|---:|
| predelay ring | 1 | 1 |
| 12 allpass rings (`allpass::process`, 1r + 1w each) | 12 | 12 |
| 4 delay rings (`delay::process`: 2 plain output taps t1/t2 + 2 reads for the one 2-point sub-sample interpolated recirculation read, 1 write) | 16 | 4 |
| **total** | **29** | **17** |

Only the recirculation read is interpolated; `t1`/`t2` are plain single reads.
The retired 40 is not derivable from the structure under any reading —
counting *both* taps as interpolated gives 37, and `(40 − 1 − 12) = 27` is not
a whole number of reads per delay line. The Reverb 2 **state** figure never
disagreed (14,532,608 B/instance, `state_agreement: true`), and no other
class's row is affected. Derivation and controls:
`reports/sxt-015/EVIDENCE.md` §7.

### 10.2 What correcting it WOULD move (measured, not applied)

Produced with the §7 and §8.5 recipes, output to `/tmp`, with the row set to
29/17 and nothing else changed:

| artifact | what would move |
|---|---|
| `reports/sxt-015/corpus-accounting.json` | `external_memory_bytes.max_ext_traffic_bytes_per_s` 48,384,000 → 39,168,000 B/s. Same worst preset both ways (`John Valentine/FX/Fireworks - Launch.fxp`, 4 processing Reverb 2 instances): 1,008 → 816 B/frame, exactly 4 × 12 words × 4 B |
| `reports/sxt-017/predictions/*` (all 5 headline bundles) | **only** the `columns.ext_traffic_bytes_per_s` field of the 665 presets that carry a Reverb 2 slot. Per-preset `status` and every `reasons` list are **identical** for all 3,561 entries in all 5 artifacts; `totals`, `per_bank` and `slate_coverage` are identical |
| B4-broad `aggregates.predicted_supported.contributor.ext_traffic_bytes_per_s` | max 33,408,000 → 26,496,000; mean 4,858,647.887324 → 4,629,464.788732 (`factory` unchanged) |
| R0-ceiling-reference, same field | max 33,408,000 → 26,880,000; mean 5,679,969.754253 → 5,268,385.633270 (`factory` unchanged) |
| `reports/sxt-017/cost-closure.json` | `worst_ext_bytes_per_frame` + `required_ext_bytes_per_s` in **48 of 120** grid cells, all **downward** (48 down, 0 up), and `ext_bandwidth_fit` in **4** of those — see §10.3. `selected_bundle` (`B1-core-narrow`), `selected_bundle_fit_claim` (`false`), every cell `verdict`, every `admissible`/`fit_claimable`/`admissible_configs`/`fit_claim_configs`, `goal_test`, `stop_escalate` and `stop_escalate_reasons` are **unchanged** |

**Attribution control (live).** With the row **held** at 40/18 — the state
this change commits — `tools/profile_budget.py` reproduces the committed
`reports/sxt-017/cost-closure.json` **byte-identically**, and
`tools/profile_predict.py` reproduces all five committed
`predictions/*.json` **byte-identically**. So every delta tabulated above is
attributable to this one row and to nothing else in the tree, and this
change demonstrably moves no committed number.

### 10.3 STOP/ESCALATE: **TRIGGERED** — held, routed to #12, not banked

Four of the 120 `cost-closure.json` grid cells move their
`ext_bandwidth_fit` column **optimistically**, `EXCEEDS` → `within`:

| bundle | clock | multiplier | memory model | E1 sustained | required before → after | `ext_bandwidth_fit` |
|---|---:|---|---|---:|---:|---|
| B4-broad | 192 MHz | M18 | E1 | 32,000,000 B/s | 33,408,000 → 26,496,000 B/s | `EXCEEDS` → `within` |
| B4-broad | 192 MHz | M32 | E1 | 32,000,000 B/s | 33,408,000 → 26,496,000 B/s | `EXCEEDS` → `within` |
| R0-ceiling-reference | 192 MHz | M18 | E1 | 32,000,000 B/s | 33,408,000 → 26,496,000 B/s | `EXCEEDS` → `within` |
| R0-ceiling-reference | 192 MHz | M32 | E1 | 32,000,000 B/s | 33,408,000 → 26,496,000 B/s | `EXCEEDS` → `within` |

The binding preset is `Vincent Zauhar/Pads/Thicc Pad.fxp` (contributor bank,
predicted-supported in B4-broad), whose worst-case external traffic falls
696 → 552 B/frame — 144 B, i.e. 3 Reverb 2 instances × 12 words × 4 B —
crossing the E1 sustained figure at 192 MHz.

**Why it is held rather than banked.** Issue #127's stop/escalate clause is
explicit: if correcting the row moves an SXT-016 probe or SXT-017 bundle
verdict in the *optimistic* direction, stop and route to #12 (profile v1
freeze, already escalated to an operator decision) rather than banking the
improvement. Four bandwidth checks that read `EXCEEDS` would read `within`,
inside the very artifact #12 decides. Accepting a relaxation into an
escalated record is an operator act, not a builder's — so the shared row
stays at the conservative 40/18 and the correction waits.

**The ambiguity is recorded, not resolved in the favourable direction.** A
narrow reading says the clause did *not* fire: no cell `verdict` moved (all
four stay `OVERFLOW_CONCLUSIVE`), no bundle became admissible or
fit-claimable, `selected_bundle_fit_claim` stays `false`, and
`ext_bandwidth_fit` is a column, not the cell's verdict. A broad reading says
it plainly did: a previously-failing check now reads pass. **This change takes
the conservative reading on purpose** — resolving that ambiguity in the
direction that relaxes an escalated budget is precisely the call the clause
reserves for #12. If #12 rules the narrow reading correct, landing the
correction is a mechanical follow-up: flip
`_RETAINED_OVER_ESTIMATE_TX["reverb2"]["retained"]` to the measured figure,
delete the record, re-derive the artifacts in §10.2, and the test suite goes
green either way by construction (`tests/test_sxt015_fx_classes.py`,
`tests/test_sxt028f.py::test_buffer_requirement_record`).

**What the movement would NOT claim, either way.** All four cells keep
`verdict: OVERFLOW_CONCLUSIVE` on cycle closure, so none becomes a closing
configuration; no bundle gains a fit claim; `stop_escalate` stays `true` with
unchanged reasons; §5's and §8.3's headline numbers stand as written; and no
preset becomes supported.

### 10.4 Held-state consequences, stated plainly

While the hold stands, `reports/sxt-015/*` and every bandwidth column derived
from it **over-state** Reverb 2 external traffic by 12 words/sample/instance
(48 B/frame/instance). That is conservative in every consumer — it can only
make a budget look tighter, never looser — and it is declared at the table
(`model/resources/fx_classes.py` `_RETAINED_OVER_ESTIMATE_TX`), in
`reports/SXT-028f/artifacts/buffer-requirement.json`
(`traffic_over_estimate_is_deliberate: true` + `traffic_retention_record`),
and in `model/resources/README.md`. It is **not** a margin claim: no burst,
alignment or arbitration analysis stands behind the extra 11 reads / 1 write.

### 10.5 What this does NOT establish

A traffic-accounting reconciliation is not a measurement of this
repository's hardware and not a fidelity result. `cyc_fxreverb2_frame`
remains an unpriced placeholder [PENDING-SXT-016]; no bundle gained a fit
claim; no preset became supported; the SXT-028f model-vs-pinned-Surge
agreement leg remains NOT_RUN/BLOCKED in its own record (#126). Nothing is
frozen, and no budget was relaxed.
