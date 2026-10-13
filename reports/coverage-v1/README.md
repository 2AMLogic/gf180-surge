# coverage-v1 — per-preset statuses over committed evidence (SXT-029, issue #22)

**Claim counts, not a completion percentage.** This directory publishes the
conservative reconciliation of what the committed evidence actually supports
today. Nothing here is a fidelity, musical-quality, FPGA/gf180mcu synthesis,
or hardware-playback claim, and no number in this directory says anything
about how any preset sounds.

## Headline (all 3,561 corpus entries; every entry has exactly one status)

| status | factory (641) | contributor (2,920) | total (3,561) |
|---|---:|---:|---:|
| supported | 0 | 0 | **0** |
| adapted (never counts toward supported) | 20 | 144 | **164** |
| unsupported | 57 | 1,075 | **1,132** |
| unresolved | 564 | 1,701 | **2,265** |

**supported = 0 is the honest result, not a failure of this pipeline.** The
1,685 `supported` entries in the SXT-017 B4-broad *prediction* qualify
nothing: prediction ≠ qualification. No compiled corpus preset has a verified
voice path: the selected voice leaf `voice:sine-fm-lp24-v2` (SXT-026a, #48)
fixture-verifies `Basses/Attacky.fxp` and `Bells/Hell's Bells.fxp` on the
original voice stage, but its model-vs-reference verdict is NO_VERDICT
against the [PROPOSED] budgets (dry and wet both miss; F-48a/F-48b -> #12) —
fixture verification and exact RTL agreement are not fidelity or support;
the Delay leaf is FAIL (SXT-023); the wavetable leaf is partial at deep mips
(SXT-026 §4); the fidelity-budget freeze (#12) is open, so every
model-vs-reference number remains PENDING-FREEZE; no preset-scoped
complete-wet integration record is PASS (#384; `integration_gate` is NOT_RUN
on all 1,683 compiled rows); and no listening record exists (#8/#9).

Favorites slates (SXT-013 *proposal* slates — no frozen favorites set exists)
are reported as PROSPECTIVE only; the ≥205/256 target is assessed **NO_VERDICT**
(BLOCKED), never PASS: balanced 0 supported / 256, contributor-lean 0/256,
factory-lean 0/256 (per-status breakdowns in `coverage.json`).

## Methodology: the conservative conjunction

A preset is **supported** only if *every* step on its path is verified:

    supported = normalized ✓
              AND compile scan: compiled ✓        (SXT-020)
              AND voice leaf verified for this preset's path
              AND every active FX class on a verified leaf
                  (per-instance state preserved; original placement/order)
              AND every required routing form on a verified leaf
              AND wavetable use inside the verified envelope
              AND fidelity-freeze gate PASS       (#12)
              AND preset-scoped complete-wet integration
                  record PASS                     (#384)

Anything else gets the hardest honest label that fits:

- **adapted** — renderable only with *disclosed edits*, per committed records:
  the SXT-017 polylimit-reduction policy (`poly_gate: adapted_beyond_pool`;
  164 presets whose rejection codes are exactly `polylimit_reduction_required`)
  and, only while the selected voice leaf does not fixture-verify the original
  voice stage, finding F-1 (Hell's Bells; the SXT-025 integration used the
  engine's dry bus as the declared voice-stage boundary — a historical
  diagnostic record, superseded by the SXT-026a original-stage run, after
  which Hell's Bells is **unresolved**, not adapted). Adapted presets are **never**
  counted toward supported. Where an adapted-class preset has *additional*
  blockers, it keeps the harder headline (`unsupported`/`unresolved`) and
  carries `also_requires_edit:…` in its reasons.
- **unsupported** — the compile scan structurally rejects the original graph,
  with machine-readable codes (`scan_code:…` in `reasons`). Nothing was ever
  trimmed or repaired.
- **unresolved** — within bundle scope (or blocked by a declared data gap) but
  at least one named verification step is missing. `reasons` names the step
  and its issue: e.g. `voice_leaf_not_landed:SXT-026a(#48)`,
  `leaf_unverified:fx:Delay(#16-RTL-and-reference-FAIL->#12-decision)`,
  `leaf_partial:osc:Wavetable(SXT-026-s4-deep-mip-finding->#12)`,
  `fidelity_freeze_pending:#12/SXT-017`.

Gate columns use the vocabulary PASS / FAIL / NOT_RUN / BLOCKED / NO_VERDICT /
STALE. **NOT_RUN is never counted as a pass.** The empty cell means the gate
was not reached (a structural status preceded it) or is vacuous (no FX
required); it is never a pass either.

### Leaf agreement is not complete-preset qualification (#384)

Every leaf on a preset's path can be verified and the fidelity policy frozen
without anything having shown that **this** preset's original wet graph —
voice plus every selected effect, in its stored placement and order, with
per-instance state, gain staging, event timing and tails — passes that
policy when integrated. Leaf verdicts are per-component; support is
per-preset. The **`integration_gate`** column therefore reads the
hash-pinned ledger `integration-ledger.json` (a pinned structural input),
whose records are keyed by corpus **bank / path / blob** identity and a
declared **qualification scope** (`original` or `adapted`). A record pins,
by full sha256, the patch image, the oracle fixture, the event sequence, the
fidelity policy, and the integrated evidence; it names the preset's
normalized-graph sha256 (the compiler's `graph_sha256`) and its placement /
order identity (`slot:role:class` per required instance); and it carries
**separate** integrated RTL-vs-model and model-vs-reference verdicts plus a
verdict per required aspect (`timing`, `gain`, `routing_order`,
`per_instance_state`, `tails`).

| situation | `integration_gate` | reason prefix |
|---|---|---|
| no record for the preset | NOT_RUN | `integration_not_run:` |
| only an adapted-scope record | NOT_RUN | `integration_adapted_only:` |
| record names another blob/bank | NOT_RUN | `integration_preset_identity_mismatch:` |
| a pin does not re-hash / file missing | STALE | `integration_evidence_stale:` |
| graph or placement/order identity differs | STALE | `integration_graph_identity_mismatch:` / `integration_order_identity_mismatch:` |
| record policy is not the frozen policy | STALE | `integration_policy_identity_mismatch:` |
| no frozen policy identity exists (#12 open) | NO_VERDICT | `integration_policy_not_frozen:` |
| explicit blocker | BLOCKED | `integration_blocked:` |
| a leg or aspect FAIL / NOT_RUN / NO_VERDICT | that status | `integration_<leg>_<STATUS>:` / `integration_aspect_<a>_<STATUS>:` |
| all of the above clean, both legs and every aspect PASS | PASS | — |

The worst applicable status wins (PASS < NO_VERDICT < NOT_RUN < BLOCKED <
FAIL < STALE). A PASS is never inferred from a leaf-family match, a closed
issue, file existence or refreshed hashes, and a record qualifies only the
preset it names. `integration_record` names the record that was evaluated.
Synthetic records are refused in a published run.

The committed ledger holds two records, both for Hell's Bells and neither
PASS: the **SXT-025 dry-bus run** (`sxt-025-hells-bells-drybus-adapted`,
scope **adapted** — finding F-1's voice-stage substitution; it is listed on
the row as `integration_adapted_only:` and can never become original-voice
qualification), and the **SXT-026a original-voice re-run**
(`sxt-026a-hells-bells-original-voice`, scope original): integrated
RTL-vs-model **NOT_RUN** (no single integrated RTL run of the original
voice stage plus Reverb 1 is committed), model-vs-reference **NO_VERDICT**
(full render and tail measured FAIL against the [PROPOSED] budgets, F-48b →
#12), per-instance state **NO_VERDICT** (single instance), policy
**not frozen** → row gate **NOT_RUN**. Every other compiled row has no
record (NOT_RUN). This gate changed no headline status: supported stays 0.

**`fx_rng_gate`** (added by #122, decision record
`decision-records/0013-fx-modulation-rng-stream.md`) reads **BLOCKED** on
every preset carrying a required effect instance whose sound depends on an
RNG stream that cannot be pinned under the SXT-010 manifest — measured in
`reports/SXT-028-rng/artifacts/coverage-impact.json` and pinned by sha256
like every other structural input. Such a preset can never be reported
`supported`: its **original** wet sound cannot be reproduced or compared, and
substituting a convenient deterministic shape would make it *adapted*, which
by plan §2 never counts. This is a published coverage **reduction**, not a
deduction — the denominators below are unchanged, nothing was removed from
the corpus, and the affected count appears in `coverage.json` →
`fx_rng_exclusion` with its per-class and per-slate breakdown. The gate is
proven load-bearing by `NC-RNG-EXCLUSION` in `negative-controls.txt`.

Coverage (the counts above) is reported **separately** from agreement and from
listening: no fidelity metric is copied into these artifacts. Agreement
evidence lives only in the linked records — `reports/sxt-022/EVIDENCE.md` (dry
voice slice), `sxt-023` (EQ verified; Delay FAIL), `sxt-024` (Reverb1
verified), `sxt-025` (integrated wet path; adapted-only per F-1), `sxt-026`
(wavetable; deep-mip finding). Listening outcomes do not exist anywhere in the
repository; `essentiality_listening` therefore reads BLOCKED on every
favorites-slate row.

Deliberately **not** published: per-preset "actual" resource use and
polyphony. No measured per-preset actuals exist (SXT-015/016 cycles are
named placeholders that gate nothing); publishing per-row resource columns
would fabricate precision. The prospective SXT-017 prediction columns
(`b4_prediction`) are carried per row for reconciliation only.

## Denominators

- Corpus: **3,561** (factory **641**, contributor **2,920**) — every
  `corpus/normalized/graphs.jsonl` entry appears exactly once in
  `per-preset.csv`; the pipeline refuses otherwise.
- Favorites: three SXT-013 proposal slates of **256** each (balanced,
  contributor-lean, factory-lean), PROSPECTIVE only. The reconciliation of
  slates × statuses is in `coverage.json` (`favorites_slates`).

## Leaf ledger (what exists; filing is not progress)

Landed leaves: `voice:sine-fm-lp24-v2` (SXT-026a, selected; fixture scope =
Attacky and Hell's Bells; Quickspit is outside it — engine-refused mono
playmode) and its predecessor `voice:attacky-slice` (SXT-022, scope = Attacky
only), `mod:lfo` (SXT-032,
scope = LFO1-6 modulator on the Attacky slice via a declared synthetic
runtime-route fixture; supported delta 0), `fx:EQ` and
`fx:Reverb1` (SXT-023/SXT-024 — leaf-verified, PENDING-FREEZE caveats
recorded), `fx:Delay` (SXT-023 — landed, **FAIL**, routed #16→#12),
`osc:Wavetable` (SXT-026 — landed, **PARTIAL**: deep-mip finding routed to the
freeze).

Filed open leaves (**24**; #48 / SXT-026a is landed, with verification
NO_VERDICT, and is no longer open): #53–#64 (SXT-028a–l, effects), #66–#77
(SXT-032–043, voice). Backlogs: **60** unfiled voice leaves (SXT-027, 29 of
them zero-slate-basis/deferred) and **10** unfiled Airwindows leaves
(SXT-028m–v). Machine-readable ledger: `leaf-verification.json` (statuses,
evidence pins) and `coverage.json` (`leaf_ledger`).

## Open decisions ledger

| decision | state | what it blocks |
|---|---|---|
| #12 (SXT-017) freeze profile v1 / fidelity budgets | OPEN | every supported promotion; all reference verdicts are PENDING-FREEZE |
| #16→#12 delay exactness + budget decision | OPEN | every preset with an active Delay slot (SXT-023 A1/A2 FAIL); Chorus budgets too (SXT-028c marker) |
| #8/#9 listening labels (essentiality) | BLOCKED-on-human | favorites-target assessment (NO_VERDICT), leaf ordering; never a support gate |
| #23 (SXT-030) FPGA + external memory | OPEN | hardware claims (non-goal here) |
| #24 (SXT-031) gf180 implementation | OPEN | silicon claims (non-goal here) |

## Files

- `per-preset.csv` — 3,561 rows; columns: bank, path, blob_sha1 (full, never
  truncated), headline_status, gate columns, compile_codes, fx_required,
  b4_prediction (prospective), slates, reasons (machine-readable, `;`-joined).
- `coverage.json` — totals, per-bank aggregates, gate distributions, slate
  reconciliation, leaf ledger, open decisions, B4-vs-headline reconciliation
  matrix, input pins (full sha256), links to agreement evidence.
- `leaf-verification.json` — committed input: per-leaf verification verdicts
  with full-sha256 evidence pins (re-hashed at run time; mismatch ⇒ STALE ⇒
  downgrade).
- `integration-ledger.json` — committed, sha256-pinned input (#384):
  preset-scoped complete-wet integration records (see above).
- `negative-controls.txt` — committed transcript of the control run below.

## Negative controls (live; each must demonstrably fail the check it targets)

Run `python3 tools/coverage_negative_controls.py` (scratch space
`/tmp/sxt029-negative-controls`; published outputs untouched):

- **NC-STALE-HASH** — in a declared counterfactual world (synthetic table:
  all leaves verified, freeze PASS → 1,682 supported with the synthetic integration ledger; see NC-INTEGRATION), the fx:EQ evidence
  hash is pointed at a mismatching file → all 453 EQ-dependent supported
  presets are **downgraded** supported→unresolved with `stale_leaf:` reasons;
  none is reported supported.
- **NC-STALE-MISSING** — silent-stub class: the EQ evidence file is absent →
  same downgrade; the pipeline neither crashes nor passes silently.
- **NC-ROW-MISSING** — a corpus entry with no compile-scan outcome → the run
  REFUSES (exit 2) and writes no outputs (fails closed).
- **NC-SHA-DISAGREE** — a graphs blob sha disagreeing with the scan → REFUSE
  (exit 2).
- **NC-INTEGRATION** (#384) — the counterfactual world also carries a declared
  synthetic integration ledger (one matching original-scope PASS record per
  compiled preset, plus a synthetic frozen-policy pin): 1,682 supported. The
  same component-PASS, freeze-PASS world with the committed ledger supports
  **0** (every one of those rows `integration_gate=NOT_RUN`) — freezing
  budgets and verifying leaves alone promote nothing. Holding every component
  gate PASS, each single-record mutation of one victim (record removed,
  evidence hash corrupted, blob identity changed, graph identity changed,
  placement/order changed, adapted-only, dropped-tail FAIL, wrong-order FAIL,
  shared-instance-state FAIL, integrated RTL-vs-model FAIL,
  model-vs-reference FAIL, blocker, NO_VERDICT, policy identity mismatch)
  removes exactly that preset with the expected status and named reason; a
  record relabelled onto another preset qualifies neither; a synthetic ledger
  in the default input position is REFUSED.

## Reproduce

```sh
python3 tools/publish_coverage.py             # deterministic; refuses on any input-pin mismatch
python3 tools/coverage_negative_controls.py   # controls; transcript re-written
```

Same committed inputs ⇒ byte-identical outputs (sorted keys, fixed column
order, no clock). Input integrity is fail-closed: any structural input whose
full sha256 differs from the pin refuses the run; legitimate data updates
must revise the pin in the same commit (visible contract revision).
`--leaf-table` / `--integration-ledger` / `--control-allow-input-drift` exist for the controls only
and are never valid for a published run.

**That invariant is asserted, not just documented** (`#125`):
`tests/test_sxt029_publication.py` re-derives every evidence pin in
`leaf-verification.json`, republishes into a scratch directory and requires
byte equality with the two committed artifacts, and re-runs the stale-pin
downgrade control against the real table. A leaf whose evidence record is
edited after publication must therefore revise its pin **and** republish in
the same commit; the revision is recorded in
`leaf-verification.json::evidence_pin_revisions` (which edit moved the file,
and why no verification status moved with it).

## What would change these numbers

Landing a leaf's evidence (#48, #53–#64, #66–#77, …), resolving the delay
defect and the #16→#12 budget decision, closing the wavetable deep-mip
finding, freezing the fidelity budgets (#12), committing preset-scoped
original-scope integration evidence (integrated RTL-vs-model and
model-vs-reference under the frozen policy, #18/#48/#384), and recording
listening labels
(#8/#9 — required for the favorites-target assessment, not for individual
support). When that happens, re-running the tool promotes exactly the presets
whose every path step is then verified — and not one more.
