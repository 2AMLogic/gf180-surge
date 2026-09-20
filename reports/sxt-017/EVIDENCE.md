# SXT-017 evidence record — DRAFT bundle comparison + predictions (issue #12, bundle stage)

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
