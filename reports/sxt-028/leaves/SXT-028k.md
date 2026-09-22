**Epic:** #3 (effects expansion) · **Plan:** docs/surge-xt-chip-plan-v0.1-2026-09-20.md §6 (SXT-028 row) · planning ID: SXT-028k · raised by SXT-028 (#21)

**essentiality UNVERIFIED -- listening pending (#9).** Issue text only: no model/RTL exists, no fidelity or support claim, no cost claim, no musical-quality claim. Ablation deltas are reference-vs-reference diagnostics (SXT-014).

## Outcome

One algorithm per leaf: Airwindows algorithm leaf: Logical (id 4). Preserves per-instance state and tails under the shared instance schedule; no monolithic FX port.

## Recovery ordering (diagnostic)
No SXT-014 ablation carrier for this feature; ordered by B4-scope carrier frequency (30 presets). Essentiality UNVERIFIED -- listening pending (#9).

## Scope and pinned sources

- surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71: libs/airwindows/src/Logical4.h + libs/airwindows/include/airwindows/AirWinBaseClass.h (vendored at the engine commit; algorithm id registry)
- surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71: src/common/dsp/effects/airwindows/AirWindowsEffect.{h,cpp} (shared adapter: param block, IO buffers, per-instance state object)
- Parameter mapping: pinned AirWindowsEffect adapter + surgepy readback at load, cross-checked against graphs.jsonl (SXT-011). p[0] selects the algorithm id; the 12-slot block is the shared AirWindowsEffect adapter
- Routing roles exercised by this leaf's B4-scope carriers: ains1, ains2, ains3, ains4, global1, global2, global3, send1, send2, send3, send4
- State: every concurrent instance keeps independent histories; arithmetic may be shared only observably (plan section 4; AGENTS.md). delay/reverb-class buffers live in external WRITABLE memory; processing stays on-chip; flash is not writable delay memory.
- Ext-mem traffic estimate: [PENDING-SXT-016] estimate via SXT-015 accounting on the frozen model; no number invented here

## Fixtures plan

- No SXT-014 ablation carrier exists for this algorithm: render new reference fixtures from the pinned oracle under SXT-012 policies (tools/render_fx_fixtures.py pattern), original + per-slot bypass + all-off dry, tails included.
- Proposed additional fixture presets (B4-scope carriers, census-blob sha verified at render): resources/data/patches_3rdparty/Cybersoda/Drums/Acoustic Snare.fxp (contributor, blob c840ab363c2e...); resources/data/patches_3rdparty/Exquis MPE/Ambiance/Dad.fxp (contributor, blob 3ee118ab69ae...); resources/data/patches_3rdparty/Exquis MPE/Basses/3x101.fxp (contributor, blob 6ffb39c5d07e...)
- Sequences: seq-notes-coverage-v1 + seq-poly-8-v1 (SXT-012 library, SHA-256-pinned; reports/sxt-014 run manifests).
- Comparability caveat: free-phase presets have single-instance numeric deltas with a repeatability-class floor (reports/sxt-012/repeatability.json); bit-identical-class presets preferred for exactness claims.
- Parameter corners: loader defaults, extremes of each named param, and the fixture preset's stored values; temposync cases pin loadPatch tempo (SXT-023 pattern).

## Acceptance

- [ ] Fixed-model/RTL equality: RTL matches the frozen fixed-point model exactly (integer equality at declared checkpoints; tools/compare_rtl_model_fx.py pattern). This is a separate claim from reference agreement.
- [ ] Algorithm identity: the shared adapter dispatches p[0] to exactly this algorithm; sibling algorithms remain out of scope of this leaf.
- [ ] Reference budgets [PROPOSED, not frozen]: model-vs-pinned-engine agreement within declared max/rms/corr budgets on the fixture presets; budgets freeze only via SXT-017 (#12).
- [ ] Per-instance state: two concurrent instances of this algorithm keep independent histories (dual-slot model-level fixture); RTL/model equality must hold per instance.
- [ ] Tails: acceptance renders include the effect's own tail span; patch-change mid-tail and reset/panic behavior specified and tested; dropped-tail renders FAIL.
- [ ] External-memory traffic: state residency + read/write traffic estimate from the frozen model via SXT-015 accounting [PENDING-SXT-016]; long buffers external-writable, never flash.
- [ ] Negative controls live: each control below demonstrably fails the check it targets; a control that passes is a broken control.

### Negative controls (each must demonstrably fail)

- Wrong order: two same-class slots swapped (slot-content permutation, tools/ablate_fx.py permute pattern) must FAIL the order-sensitive equality/agreement check.
- Shared state: a mutant that pools the two instances' histories into one (tb_fx_shared_line pattern) must FAIL the dual-instance equality check.
- Generic substitute: any variant that swaps this algorithm for a convenient generic is labeled ADAPTED and must be refused/excluded from original-preset coverage (tools/ablate_fx.py substitute pattern); bypass tests retain the unmodified wet reference.
- Dropped tail: truncating the render before the declared tail span must FAIL the tail check.
- Stale stub: the RTL harness pins the frozen-model revision hash; a stale harness must refuse to report PASS.

## Deliverables

- model/effects/aw-4/ -- frozen fixed-point model + README (word lengths, state layout, per-instance state ownership) (model/effects/README.md pattern)
- model/effects/fx_inputs/aw-4-*.json -- fail-closed input extraction (extract_fx_inputs.py pattern; census blob re-verified, graphs cross-check, drift asserted 0)
- rtl/effects/aw-4/ -- RTL + iverilog testbench incl. the dual-instance and negative-control benches
- reports/SXT-028k/ -- EVIDENCE.md: verification statuses PASS/FAIL/NOT_RUN/BLOCKED, budgets vs achieved, coverage separate from agreement, ext-mem estimate [PENDING-SXT-016]
- tests/test_sxt028k.py -- generator-consistency + exactness harness guards (oracle-dependent tests skip NOT_RUN without oracle)
- decision-records/ entry: license decision record for any airwindows table/code adoption before merge (AGENTS.md licensing rule; libs/airwindows LICENSE terms reviewed)

## Dependencies

- #9 SXT-014 (done: numeric deltas; listening labels BLOCKED-on-human)
- #12 SXT-017 profile freeze (budget freeze gate)
- #16 SXT-023 Delay/EQ (per-effect acceptance pattern + the open delay-budget finding feeds SXT-017)
- #17 SXT-024 Reverb 1 (done: per-effect acceptance pattern, DR-0003 constant-table pattern)
- #18 SXT-025 (done: integration boundary)

## Newly enabled presets

- Strict-FX-complete: 0 presets; B4-scope candidates (upper bound): 30 (factory 0, contributor 30).
- Rule: strict-FX-complete: every active FX class of the preset is landed/in-flight (Delay in-flight (SXT-023, #16; open delay-budget finding); EQ in-flight (SXT-023, #16); Reverb 1 landed (SXT-024, #17)) or this leaf's own feature; B4-scope candidate count is the upper bound. Presets needing sibling 028 leaves count toward neither until the last sibling lands.
- Hashes: reports/sxt-028/leaves/SXT-028k/newly-enabled.json (full path + blob-SHA-1 lists).
- Caveat: FX-scope accounting only; voice stage, scheduling, and profile v1 freeze gate actual support. NOT a support claim.

## Non-goals

- Implementing the leaf here; coverage publication (#22); any substitute/generic effect under a support claim

## Stop / escalate

If the effect cannot be bounded in state/cost under the shared instance schedule, record the finding and route to SXT-017 (#12) before freezing budgets; do not weaken acceptance to pass.

## Reusable substrate

- Leaf/bench style: per-block leaves with injected-defect negative controls (Parasynth verifier style, gf180-parasynth@cbcc8b9e rtl-sketch/verify_synth_top.py); adapt method, re-derive checks.
- Algorithm authority: pinned Surge sources only; no sibling FX DSP; no generic substitutes under support claims.
- Governed by #25 and docs/REUSE-AUDIT.md: adapt method freely; copy code/tables only through a recorded adoption with pinned source, attribution, tests, and a local negative control; license decision record before merge.

---

Generated by SXT-028 issue generator (tools/generate_effect_leaves.py); Allocation: SXT-028a–028v reserved by this generator run (22 leaves; first 12 filed now, rest in leaf-backlog.json). Deterministic regeneration: `python3 tools/generate_effect_leaves.py --verify`.
