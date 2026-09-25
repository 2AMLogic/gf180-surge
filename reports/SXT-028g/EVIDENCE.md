# SXT-028g evidence record — Phaser (sst-effects `Phaser`): frozen fixed-point model, exact RTL, per-instance state, tails; reference agreement NOT_RUN

Branch: `feature/issue-59` · Issue: #59 (SXT-028g) · Parent: #21 (SXT-028) ·
Epic: #3 · Date: 2026-09-25

Engine pin (external, GPL-3.0-or-later; nothing copied into this repository):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz,
compiled block size 32 (`oracle/manifest.json`). Algorithm authority, read
and cited: `libs/sst/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b`
`include/sst/effects/Phaser.h` + `EffectCore.h` +
`include/sst/effects-shared/WidthProvider.h`;
`libs/sst/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96`
`modulators/FXModControl.h`, `dsp/BlockInterpolators.h`, `dsp/MidSide.h`;
`libs/sst/sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6`
`filters/BiquadFilter.h`; surge `src/common/dsp/effects/SurgeSSTFXAdapter.h`
and `PhaserEffect.{h,cpp}`. Full per-symbol citation is in
`model/effects/type-phaser/README.md` and in the model docstring.

## Claim discipline (AGENTS.md — three claims, never inferred from each other)

| # | Claim | Status here | Evidence |
|---|---|---|---|
| 1 | The RTL matches the frozen fixed-point model **exactly** | **PASS** | `rtl-exactness.json` |
| 2 | The model reproduces the pinned Surge engine within declared budgets | **NOT_RUN** | `artifacts/oracle-status.json` |
| 3 | The instrument sounds good | **NO_VERDICT** | nothing here bears on it |

This record establishes **no** preset-support claim, **no** coverage claim,
**no** musical-quality claim, **no** FPGA/gf180mcu synthesis, place-and-route,
signoff, timing, area or hardware-playback claim, and it **freezes no budget**.
No generic substitute is used under any support claim — NC-A keeps that
control live and labels the substitute ADAPTED.

**Why claim 2 is NOT_RUN.** This leaf was built in an environment with no
pinned-engine checkout and no importable `surgepy`. That was *measured*, not
assumed: `tools/phaser_oracle_status.py` probes for the checkout and attempts
the import, and writes `artifacts/oracle-status.json`
(`oracle_status: UNAVAILABLE`; all four oracle legs `NOT_RUN`). The
extraction, fixture-render, model-render and reference-comparison tools were
therefore **never invoked**; `artifacts/extract-refusals.txt` and
`artifacts/render-refusals.txt` record that as NOT_RUN rather than as a set of
per-carrier refusals. A test that did not run is not a pass.

## Headline results

| Item | Status | Evidence |
|---|---|---|
| Fixed-model ↔ RTL integer equality | **PASS** — 6 cases, 83,968 output samples, 3,872 cascade points, 94 state checkpoints, 3,102 state fields, all exact; revision pin matched on every case | `rtl-exactness.json` |
| RTL negative controls | **4/4 CONTROL-OK** (`mutant-shared`, `mutant-stageorder`, `mutant-lagcoef`, `mutant-noclamp`) | `rtl-exactness.json` |
| Model-side negative controls | **6/6 CONTROL-OK** (NC-A … NC-F) | `negative-controls/negative-controls.json` |
| Per-instance state (two concurrent instances) | **PASS** — dual-instance equality holds per instance; the shared-state mutant FAILS it | `rtl-exactness.json`, `tests/test_sxt028g.py` |
| Tails: declared span, reset/panic, mid-tail patch change | **PASS** (model + RTL); dropped-tail control FAILS as required | §4, NC-B, `artifacts/tail-window.json` |
| External-memory residency + traffic | **PASS (measured): 0 external bytes, 0 words/sample**; exact on-chip inventory 812–3,500 B/instance | `artifacts/buffer-requirement.json` |
| External-memory / cost **closure** | **`[PENDING-SXT-016]`** — no number invented | §5 |
| Model ↔ pinned engine vs `[PROPOSED]` budgets | **NOT_RUN** (no oracle) | `artifacts/oracle-status.json` |
| Preset extraction (census-verified) | **NOT_RUN** (no oracle) | `artifacts/extract-refusals.txt` |
| Newly-enabled presets supported by this leaf | **0** (honest delta; see §7) | this record |

## 1. What the frozen model is

`model/effects/type-phaser/phaser_model.py`, revision pinned by
`model_revision()` (sha256 of the file) and carried in every trace.
`model/effects/type-phaser/README.md` is the freeze document: word lengths
(Q10.21 audio / Q13.18 block ramps / Q24.43 coefficients, lags and LFO),
the block schedule, the per-instance state layout and ownership, the declared
control-plane boundary, the declared deviations and the declared fail-closed
scope omissions.

Engine behaviours reproduced **as pinned** (each is load-bearing and covered
by a checkpoint or a test, not a model simplification):

* **`slowrate = 8`.** `setvars()` runs once per 8 blocks; `mix` is retargeted
  every block while `widthS`, the feedback/tone lipols and every biquad
  coefficient are retargeted only on the slow block.
* **One-slow-block LFO latency.** `Phaser::setvars` calls
  `modLFO.processStartOfBlock(...)` and then `valueStereo()`, but the Phaser
  **never** calls `modLFO.process()`. The `FXModControl` output lipols
  therefore never advance, so the value consumed is the *previous* slow
  block's waveform sample scaled by the *previous* slow block's depth —
  except on the first call, where the lipol `first_run` snap makes it
  current. (`test_one_slow_block_lfo_latency_is_reproduced`.)
* **Legacy branch.** For `n_stages < 2` `Phaser.h` loops `i < 2` and so
  configures biquads 0..3, while `processBlock` runs only stage 0
  (biquads 0/1). Reproduced exactly; the state inventory follows the
  allocation, not the usage.
  (`test_legacy_branch_allocates_four_units_but_runs_one_stage`.)
* **Tone read order.** The lp/hp cutoffs are derived from `tone.v` *after*
  `tone.newValue(...)`, i.e. from the previous slow block's converged value.
* **`widthM` is never applied** — `useLinearWidth()` is false for the Surge
  `FXConfig` (no `widthIsLinear` member in `SurgeSSTFXAdapter.h`), so only
  the side channel is scaled.
* **±32 recursive-node clamp**, per-stage re-rounding of the cascade value
  (the engine returns `float` from `BiquadFilter::process_sample`), and the
  mono/stereo split of the biquads (`process_sample` uses one register pair;
  `process_block` uses two).

## 2. Fixed-model ↔ RTL equality (claim 1) — **PASS**

`rtl/effects/type-phaser/tb_phaser.sv`, driven by
`tools/compare_rtl_model_phaser.py` (iverilog). Compared with **integer
equality** — any mismatch is a FAIL:

* every per-instance output sample of every block (`O` lines);
* every declared checkpoint's per-instance state (`T` lines): `dL`/`dR`, the
  feedback and tone lipol `v`/`dv`/`new_v`, the `widthS` and `mix` ramp
  `current`+`target`, the tone lp/hp coefficient lags and all four TDF2
  registers, an **order-sensitive 64-bit hash over every live APF biquad
  state word** (lags, targets and both registers, stage- and channel-major),
  and the external-memory counters (which must stay 0);
* every cascade checkpoint (`X` lines): the post-stage `(dL, dR)` pair for
  each stage of the first four samples — this pins the cascade **order**;
* the frozen-revision pin: a trace whose revision word does not match the
  live model is REFUSED, never PASS.

| Case | Blocks × inst | What it exercises | Result |
|---|---|---|---|
| `prs-dual-128` | 128 × 2 | 4-stage and 8-stage instances, disjoint state, serial chaining | exact |
| `prs-clamp-96` | 96 × 2 | near self-oscillation (\|feedback\| = 0.95, ±8 stimulus); the ±32 clamp engaged **27 times** | exact |
| `prs-reset48-128` | 128 × 2 | reset / panic (`suspendProcessing` → `initialize`) before block 48 | exact |
| `prs-patch64-160` | 160 × 2 | input silent at block 48, **parameters changed at block 64 mid-tail** | exact |
| `prs-legacy-96` | 96 × 2 | legacy branch (stages = 1) + deactivated mod rate + tone deactivated | exact |
| `prs-maxstages-48` | 48 × 2 | `max_stages = 16` (32 APF biquad units) | exact |

Totals: 83,968 output samples, 3,872 cascade points, 94 state checkpoints,
3,102 state fields — all exact; revision pin matched on all six cases.

## 3. Negative controls — all live, each demonstrably failing its target

A control that *passes* is a broken control. Both tools exit non-zero if any
control fails to fire.

### 3a. RTL mutants (`rtl-exactness.json`)

Generated from `tb_phaser.sv` by source substitution into a scratch
directory (the SXT-028c pattern), then run against the same stimulus the
golden case used:

| Control | Targets | Stimulus | Result |
|---|---|---|---|
| `mutant-shared` | **shared state**: both instances' APF/`dL` histories pooled into one (the `rtl/effects/tb_fx_shared_line.sv` pattern) | `prs-dual-128` | **FAILS** dual-instance equality — CONTROL-OK |
| `mutant-stageorder` | cascade walked in reverse stage order | `prs-dual-128` | **FAILS** — CONTROL-OK |
| `mutant-lagcoef` | biquad coefficient-lag rate doubled | `prs-dual-128` | **FAILS** — CONTROL-OK |
| `mutant-noclamp` | ±32 recursive-node clamp removed | `prs-clamp-96` | **FAILS** — CONTROL-OK |

**Control coverage is itself checked.** `mutant-noclamp` originally *passed*
against the ±1.0 stimulus, because that stimulus never reaches ±32 — a broken
control. It is now scored against `prs-clamp-96`, and the harness refuses to
score it at all unless the frozen model reports a non-zero clamp-engagement
count on that stimulus (27 here). The engagement count is recorded per case
in `rtl-exactness.json` and asserted by `tests/test_sxt028g.py`.

### 3b. Model-side controls (`negative-controls/negative-controls.json`)

Anchored on the frozen model and on the declared agreement threshold
(8,192 LSB Q10.21 — the same `max_abs_diff_lsb` the reference comparator
proposes for this effect-slice family). **Every control also records a
`reference_anchored_leg` with status NOT_RUN**: re-running it against oracle
fixtures is required before any model-vs-reference statement.

| Control | Targets | Result |
|---|---|---|
| **NC-A** generic substitute | a convenient generic (one static allpass per channel, no LFO, no spread, no stereo) | exceeds the declared threshold → FAILS agreement; labelled **ADAPTED**, `counts_toward_original_preset_coverage: false` — CONTROL-OK |
| **NC-B** dropped tail | render truncated to 1/8 of the declared `getRingoutDecay` span | full render passes the tail check; truncated render **FAILS** both legs (region coverage and terminal energy) — CONTROL-OK |
| **NC-C** wrong order | two instances chained A→B vs B→A (slot-content permutation) | permutation exceeds the threshold; the *unpermuted* chain is bit-identical, so the detector is not always-firing — CONTROL-OK |
| **NC-D** stale stub | a trace whose outputs match but whose frozen-revision pin is stale | comparator REFUSES it (`revision_pin.ok == false`, `exact == false`), never PASS — CONTROL-OK |
| **NC-E** bypass transparency | `mix = 0` transparency and wet-leak detection | residual within the declared bound; an injected `mix = 0.05` leak is detected by the same check; the unmodified wet path is retained in both legs — CONTROL-OK |
| **NC-F** LFO-depth sensitivity | modulation depth halved | exceeds the threshold while the null leg is bit-identical → the LFO trajectory is load-bearing — CONTROL-OK |

**Bounded finding surfaced by NC-E (not a weakening).** `mix = 0` is *not*
bit-exactly transparent in this model. `lipol_sse::set_target_smoothed`
converges as `target ← round_half_up(0.25·f + 0.75·target)`, which **sticks at
2 LSB in Q13.18** for `f = 0` (round-half-up of 1.5 is 2), whereas the engine's
float ramp underflows to 0. The residual is therefore bounded by that floor
and is measured, not waived. This is a property of the shared `Lipol` used by
**every** effect model in this repository (Delay, EQ, Chorus, Phaser), not of
the Phaser, and it is declared in `model/effects/type-phaser/README.md`. It
does not affect claim 1 (the RTL reproduces the same floor exactly).

## 4. Tails — declared span, reset/panic, mid-tail patch change

**Declared span.** `Phaser::getRingoutDecay()` in **blocks of 32** at 48 kHz:
1,000 blocks (0.667 s) for |feedback| ≤ 0.5, 3,000 (2.0 s) above 0.5,
5,000 (3.33 s) above 0.9, and **−1** for |feedback| > 1 (possible
self-oscillation), for which **no finite span can be declared and the tail
check REFUSES** rather than inventing one. Per-corner windows:
`artifacts/tail-window.json`.

**Acceptance rule.** A render must cover the declared span *after the input
goes silent*, the tail must be present where the input stops, and it must have
decayed to the declared terminal floor by the render's end.
`tools/render_phaser_fixtures.py` **refuses** any SXT-012 sequence whose
`tail_s` is shorter than the patch's declared span, so a dropped tail cannot
enter the evidence in the first place. NC-B shows the check is real: the full
render passes, the truncated render fails.

**Reset / panic.** `Phaser.h` routes `suspendProcessing()` to `initialize()`:
the whole per-instance state is cleared and the tail stops. Specified in the
README, implemented as `PhaserModel.reset()`, tested at model level
(`test_reset_panic_clears_the_tail`) and exercised through the RTL by
`prs-reset48-128`.

**Patch change mid-tail.** The engine mutates `FxStorage` in place; the
running instance keeps `dL`/`dR`, every biquad register and every ramp, and
only picks the new values up at the next `setvars` (`bi == 0`) boundary — so
the tail *continues* rather than restarting. Specified in the README,
implemented as `PhaserModel.set_params()`, tested at model level
(`test_patch_change_mid_tail_continues_the_tail`) and exercised through the
RTL by `prs-patch64-160` (silent from block 48, parameters changed at block
64, RTL exact throughout). A stage-count change is **refused**: that is the
`init_stages` allocation path, outside the frozen scope.

## 5. External memory and cost — measured residency, `[PENDING-SXT-016]` closure

**The Phaser owns no delay line.** `Phaser.h` has no line buffer: the effect
is a cascade of biquad allpass sections plus a one-sample recursive node.
Measured from the frozen model's own `ext_reads`/`ext_writes` transaction
counters over 128-block renders on three corners (`artifacts/buffer-requirement.json`):

* external writable memory: **0 bytes**;
* audio-rate external traffic: **0 words/sample**, 0 B/s at 48 kHz;
* flash is never writable delay memory (plan §3) and none is used here.

Exact on-chip state inventory per instance (from
`phaser_model.state_inventory`, not an estimate):

| stages | biquad units | bytes |
|---|---|---|
| 1 (legacy) | 4 | 812 |
| 2 | 4 | 812 |
| 4 (default) | 8 | 1,196 |
| 8 | 16 | 1,964 |
| 16 (max) | 32 | **3,500** |

Two configured Phaser slots are two independent state sets
(`per_additional_instance_bytes_worst_case: 3500`, external 0).

**SXT-015 reconciliation.** `reports/sxt-015/examples/example-a-four-fx-instances.json`
carries the Phaser as `tier: no_long_buffer`, `external: false`,
`ext_reads_per_frame: 0`, `ext_writes_per_frame: 0`, `state_bytes: 8192`, with
the anomaly flag `class_state_unverified` and the note *"exact state sizing
ESTIMATE-REF deferred to SXT-028"*. This leaf **confirms** the tier and the
traffic and **supersedes** the byte placeholder with the exact inventory:
3,500 B worst case ≤ 8,192 B, so the placeholder was conservative, not wrong.
`class_state_unverified` is resolved for the Phaser class.

**Cost closure: `[PENDING-SXT-016]`.** No cycles-per-frame, schedule-fit or
bundle-closure number is asserted by this leaf. SXT-015 accounting consumes
the inventory above and SXT-016 decides fit; profile v1 is **not frozen**
(SXT-017, #12, currently `loom:operator-only` after PR #109 found no candidate
bundle meeting the budget goal at any measured clock/memory/schedule corner).
Nothing in this record may be read as a cost or fit claim.

**Stop/escalate check (issue #59).** The escalation condition — *"the effect
cannot be bounded in state/cost under the shared instance schedule"* — did
**not** fire: the state is bounded exactly (≤ 3,500 B/instance, zero external
traffic, no long buffer). Nothing is routed to #12 from this leaf on those
grounds. The separate budget-freeze gate remains #12's, untouched here.

## 6. Reference budgets (claim 2) — **NOT_RUN**, budgets `[PROPOSED, not frozen]`

The comparator (`tools/compare_phaser_reference.py`) reuses the shared stereo
effect-slice machinery of SXT-028c unchanged — the same metrics, the same
`[PROPOSED]` budget family (`max_abs_diff_lsb` 8,192; `rms_diff_dbfs` −46;
`spectral_corr_min` 0.98) and the same issue-#100 declared-region wet tail
gate. No budget is re-proposed per leaf and none is frozen: freeze is gated on
SXT-017 (#12).

It was **not run**: there is no oracle in this environment, so there are no
fixture buses and no model wet render. The tool refuses with `NO_VERDICT` /
exit 2 in that state rather than skipping silently, and
`tests/test_sxt028g.py::test_reference_comparison_is_not_claimed_without_an_oracle`
asserts that **no** `compare-*.json` record may exist while
`oracle-status.json` says `UNAVAILABLE`.

The scaffolding is complete and ordered so the leg runs correctly the moment
an oracle host is available:

```sh
python3 tools/extract_phaser_inputs.py        # census-verified, fail-closed
python3 tools/render_phaser_fixtures.py       # wet/dry buses, tails enforced
python3 model/effects/run_phaser_model.py --slug <slug> --seq <seq>
python3 tools/compare_phaser_reference.py --slug <slug> --seq <seq>
```

Carriers queued (B4-scope, named by issue #59; census blob SHA-1 from
`reports/sxt-028/leaves/SXT-028g/newly-enabled.json`, re-verified by the
extractor at run time): `Argitoth/FX/Reson.fxp` (`ba7d2c45b8ed…`),
`Bluelight/Basses/Bass 11.fxp` (`bebc1a6c8d18…`),
`Bluelight/Basses/Bass 17.fxp` (`7c8cd4d1060b…`), each over
`seq-notes-coverage-v1` and `seq-poly-8-v1`.

**Parameter corners in the meantime.** The oracle-independent legs are driven
by eight synthetic parameter corners
(`model/effects/type-phaser/corners.py` → `model/effects/fx_inputs/type-phaser-synth-*.json`)
covering the default (4), minimum-legacy (1), 2, 8 and maximum (16) stage
counts, all five deterministic LFO waveforms, tone active and deactivated,
mod-rate active and deactivated, and both near-self-oscillation polarities.
Every such file is self-labelling: `"source": "synthetic-corner"`,
`"census_blob_sha1": null`, `complete_wet_render_possible: false`, and a
`warning` field stating that it is not a preset extraction and carries no
support, coverage or fidelity claim. `run_phaser_model.py` **refuses** to
render a reference comparison from any record whose `source` is not
`oracle-extraction`.

## 7. Coverage — **0 presets supported by this leaf**

The issue's *Newly enabled presets* numbers (97 strict-FX-complete,
155 B4-scope candidates) are FX-scope accounting upper bounds from the
generator, not support claims, and nothing here changes that. This leaf
supports **zero** presets: no preset was extracted, no preset was rendered, no
complete wet sound was compared against the pinned engine, and the voice
stage, scheduling and the profile v1 freeze all still gate actual support.
Coverage publication (#22) is a non-goal here and no coverage artifact is
written.

## 8. Declared scope omissions (fail-closed) and the finding they carry

* **`mod_wave` 5 (Noise) and 6 (Sample & Hold) are REFUSED.** `FXModControl`
  drives those shapes from `sst::basic_blocks::dsp::RNG`, so they are not
  bit-reproducible against the pinned oracle without an RNG-stream pin. The
  model raises, and `tools/extract_phaser_inputs.py` refuses any carrier using
  them — rather than substituting a convenient deterministic shape, which
  would be exactly the adaptation AGENTS.md forbids.
  **This is a bounded finding.** It blocks only the affected carriers; it does
  not weaken any acceptance rule, and it does not reduce the product goal. The
  two enforcement points are kept in agreement by a test
  (`test_extractor_refuses_rng_waveforms_by_construction`). Extending the
  frozen scope to the RNG waveforms needs its own leaf (an RNG-stream pin plus
  a determinism policy, or a visible contract revision through SXT-017 if the
  stream cannot be pinned): filed as **#122**.
* Parameter modulation **into** phaser parameters: fail-closed; the extractor
  refuses any preset with an FX-destination modulation route.
* The runtime `n_stages` change path (`init_stages` allocating new biquads
  mid-render): `n_stages` is block-constant in the frozen scope;
  `set_params()` refuses a stage-count change.

## 9. Known deviations that are *not* measured here

The dominant declared deviation of this leaf is the audio **grid**: the engine
carries the cascade in float32 (relative precision) and this model carries it
in Q10.21 (absolute precision ≈ 4.77e-7). Per-stage re-rounding is
structurally faithful (the engine also rounds to float32 between stages), but
the grids differ, and in a feedback loop at |feedback| → 0.95 the loop gain
amplifies whatever the grid drops. **No measurement of that effect exists in
this record** — it is exactly what claim 2 would quantify, and claim 2 is
NOT_RUN. Do not read claim 1's PASS as evidence about it.

## 10. Provenance and licensing

Everything added by this leaf is original to this repository (Apache-2.0 per
`LICENSE`). The pinned Surge / sst trees were **read and cited only**; no
code, table or asset was copied, so no license decision record is required
(AGENTS.md licensing rule). Constant inventory with per-constant origin is in
`model/effects/type-phaser/README.md` §Provenance: every constant is either a
cited literal from a pinned source or a formula re-derivation evaluated in
double and quantized once. There are no opaque designed constants.

## 11. Reproduce

```sh
python3 model/effects/type-phaser/corners.py --write   # synthetic corners
python3 tools/phaser_oracle_status.py                  # measured oracle probe
python3 tools/compare_rtl_model_phaser.py              # claim 1 + RTL mutants
python3 tools/phaser_negative_controls.py              # NC-A … NC-F
python3 tools/phaser_buffer_report.py                  # state + traffic
python3 -m pytest tests/test_sxt028g.py -q
```

## 12. Artifacts

| Path | Contents |
|---|---|
| `rtl-exactness.json` | claim 1: 6 cases + 4 RTL mutants, revision pin, per-case clamp coverage |
| `negative-controls/negative-controls.json` / `.txt` | NC-A … NC-F with metrics and per-control `reference_anchored_leg` status |
| `artifacts/buffer-requirement.json` | measured traffic, exact state inventory, SXT-015 reconciliation, `[PENDING-SXT-016]` closure |
| `artifacts/tail-window.json` | declared `getRingoutDecay` span per corner + the terminal-energy floor |
| `artifacts/oracle-status.json` | measured oracle probe; per-leg NOT_RUN record |
| `artifacts/extract-refusals.txt` | extraction NOT_RUN record + queued carriers and their census blobs |
| `artifacts/render-refusals.txt` | fixture-render NOT_RUN record + the re-run recipe |
