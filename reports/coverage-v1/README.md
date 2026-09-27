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
| adapted (never counts toward supported) | 20 | 145 | **165** |
| unsupported | 57 | 1,075 | **1,132** |
| unresolved | 564 | 1,700 | **2,264** |

**supported = 0 is the honest result, not a failure of this pipeline.** The
1,685 `supported` entries in the SXT-017 B4-broad *prediction* qualify
nothing: prediction ≠ qualification. No compiled corpus preset has a verified
voice path (finding F-1: the only two presets inside the landed voice
arithmetic carry no FX, and only `Basses/Attacky.fxp` is fixture-verified);
the Delay leaf is FAIL (SXT-023); the wavetable leaf is partial at deep mips
(SXT-026 §4); the fidelity-budget freeze (#12) is open, so every
model-vs-reference number remains PENDING-FREEZE; and no listening record
exists (#8/#9).

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

Anything else gets the hardest honest label that fits:

- **adapted** — renderable only with *disclosed edits*, per committed records:
  the SXT-017 polylimit-reduction policy (`poly_gate: adapted_beyond_pool`;
  164 presets whose rejection codes are exactly `polylimit_reduction_required`)
  and finding F-1 (Hell's Bells; the SXT-025 integration used the engine's dry
  bus as the declared voice-stage boundary). Adapted presets are **never**
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

Landed leaves: `voice:attacky-slice` (SXT-022, scope = Attacky only; Quickspit
is F-1 arithmetic overlap **without** fixture evidence), `mod:lfo` (SXT-032,
scope = LFO1-6 modulator on the Attacky slice via a declared synthetic
runtime-route fixture; supported delta 0), `fx:EQ` and
`fx:Reverb1` (SXT-023/SXT-024 — leaf-verified, PENDING-FREEZE caveats
recorded), `fx:Delay` (SXT-023 — landed, **FAIL**, routed #16→#12),
`osc:Wavetable` (SXT-026 — landed, **PARTIAL**: deep-mip finding routed to the
freeze).

Filed open leaves (**25**): #48 (SXT-026a voice-scope extension — the F-1
leaf that gates every FX preset), #53–#64 (SXT-028a–l, effects), #66–#77
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
- `negative-controls.txt` — committed transcript of the control run below.

## Negative controls (live; each must demonstrably fail the check it targets)

Run `python3 tools/coverage_negative_controls.py` (scratch space
`/tmp/sxt029-negative-controls`; published outputs untouched):

- **NC-STALE-HASH** — in a declared counterfactual world (synthetic table:
  all leaves verified, freeze PASS → 1,681 supported), the fx:EQ evidence
  hash is pointed at a mismatching file → all 453 EQ-dependent supported
  presets are **downgraded** supported→unresolved with `stale_leaf:` reasons;
  none is reported supported.
- **NC-STALE-MISSING** — silent-stub class: the EQ evidence file is absent →
  same downgrade; the pipeline neither crashes nor passes silently.
- **NC-ROW-MISSING** — a corpus entry with no compile-scan outcome → the run
  REFUSES (exit 2) and writes no outputs (fails closed).
- **NC-SHA-DISAGREE** — a graphs blob sha disagreeing with the scan → REFUSE
  (exit 2).

## Reproduce

```sh
python3 tools/publish_coverage.py             # deterministic; refuses on any input-pin mismatch
python3 tools/coverage_negative_controls.py   # controls; transcript re-written
```

Same committed inputs ⇒ byte-identical outputs (sorted keys, fixed column
order, no clock). Input integrity is fail-closed: any structural input whose
full sha256 differs from the pin refuses the run; legitimate data updates
must revise the pin in the same commit (visible contract revision).
`--leaf-table` / `--control-allow-input-drift` exist for the controls only
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
finding, freezing the fidelity budgets (#12), and recording listening labels
(#8/#9 — required for the favorites-target assessment, not for individual
support). When that happens, re-running the tool promotes exactly the presets
whose every path step is then verified — and not one more.
