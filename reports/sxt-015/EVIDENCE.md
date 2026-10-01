# SXT-015 — Resource accounting: evidence record (issue #10)

Model: `model/resources/accounting.py` (+ `fx_classes.py`, `params.py`,
`schema.json`, `README.md`). Tool: `tools/account_corpus.py`.
Inputs: `corpus/normalized/graphs.jsonl` (3,561 SXT-011 normalized graphs),
`fixtures/sequences/` (10 sequence fixtures), `corpus/census-v0.1/`
(cross-check only).

**Standing disclaimer.** Everything in this report is a *bookkeeping model
output under named assumptions* (cost profile `placeholder-v0`, named
candidate limits, named placeholder clock and external-memory bandwidth).
These are **NOT** area/cycle measurements (that is SXT-016), **NOT** a
profile freeze (that is SXT-017), **NOT** fidelity or preset-quality claims,
and **NO** FPGA/gf180mcu/hardware claim of any kind. Every cycle number
exists so the closure machinery is executable and must be replaced by SXT-016.

## 1. Issue-#10 acceptance mapping

| # | Acceptance item (issue #10) | Status | Evidence |
|---|---|---|---|
| 1 | Per-instance effect state counted separately from shared arithmetic | **PASS** | Every configured slot yields its own instance entry with its own `state_bytes` (`accounting.py` FX section); `fx_summary.distinct_type_count` is reported beside instance counts. Corpus: 707/3,561 presets have enabled instances > distinct types (188 with two or more enabled Delays — 173 exactly two — each slot its own delay history). Two Delay slots are never merged. |
| 2 | External writable-memory traffic modeled separately from on-chip state; flash not accepted as delay/reverb storage | **PASS** | `memory` object: `external_writable_state_bytes`, `on_chip_state_bytes`, `flash_asset_bytes` are separate sums. Classification rule: writable class > 64 KiB => external writable (`external_threshold_bytes`, policy). `flash_writable = 0` is a declared policy param citing plan section 3; flash carries assets only (`assets.flash_role`). |
| 3 | Worst-case complete-patch cost computable for any normalized graph within declared limits; overflow is an explicit rejection | **PASS** | `budget` object closes the plan-section-5 formula per graph (`gross = F/Fs`, reserve, cost = voice+fx+modulation+events). Overflow => `budget_overflow` rejection object, status `rejected` — never a silent squeeze. Corpus scan: 3,561/3,561 graphs accounted (0 analysis failures in the committed export; the fail-closed path itself is demonstrated by negative control 2). |
| 4 | Instance limits distinct from supported-type counts | **PASS** | `fx_instance_limit` applies to **enabled instances** (slots), independent of the distinct-type count; a preset with Delay+Delay+Delay is 3 instances of 1 type. Candidate limits {4, 8} are declared policy, NOT frozen product limits (SXT-017 freezes). |
| 5 | Negative control: a graph exceeding declared instance limits must be rejected, not silently squeezed | **PASS** | `reports/sxt-015/negative-control/nc-instance-limit-overflow.json`: synthetic 5-instance graph (via `/tmp/sxt-015-nc-fx5.jsonl`) => `fx_instance_overflow` rejection at limit 4, fit at limit 8 (limit-driven). Controls 2–4: analysis_failure fails closed with null costs; budget overflow explicit; unison out of range flagged and clamped. Control 5 (added with the §8 shape decision): the modulation term moves only for voice-list rows and only with the live-voice count. All five controls PASS. |

## 2. Worked examples (issue-#10 deliverable: four-instance and two-scene-unison)

All three are real corpus presets; accounts are committed under
`reports/sxt-015/examples/`. Cycle totals use `placeholder-v0` and support no
technology claim.

| Case | Preset (blob sha) | Voice | FX instances (slot/class/state B/ext) | Ext writable state | Ext traffic | Closure (placeholder-v0) |
|---|---|---|---|---|---|---|
| (a) four-instance | `patches_3rdparty/A.Liv/Keys/July.fxp` (`315c0a1a27a671297f437026c021ce917f1e3875`) | Single; worst 16 voices; 32 unison-osc instances | 4 enabled / 4 types: 0 Phaser 8 192 (chip), 2 Audio In 8 192 (chip), 3 Delay 2 097 152 (ext), 6 Airwindows 1 048 576 (ext, unverified) | 3 145 728 B | 24 B/frame = 1.15 MB/s | OVERFLOW (explicit; voice dominates under placeholder costs) |
| (b) two-scene unison-heavy | `patches_3rdparty/Luna/Leads/96 Osc Supersaw.fxp` (`feeaa7db6bf4c2ef08cd48e62f0b44fe0d11dda4`) | **Dual** (2 pool voices/note); worst 16 voices; **768** unison-osc instances | 2 enabled / 2 types: 0 Chorus 1 048 624 (ext), 6 Reverb 2 14 532 608 (ext) | 15 581 232 B | 252 B/frame = 12.1 MB/s | OVERFLOW (explicit) |
| (c) all-FX-off baseline | `patches_3rdparty/A.Liv/Basses/Amen Polska.fxp` (`4476029209d77064a7c2bf4f58fef78f7f2c10fc`) | Single; worst 16 voices; 80 unison-osc instances | none | 0 B | 0 B/frame | OVERFLOW (explicit; voice-only under placeholder costs) |

Notes:
- Example (a) also demonstrates **routing concurrency**: its scene-B insert
  slots do not process in Single scene mode (`routing_inactive`), so
  configured = enabled = 4 but only 2 instances process per frame — state is
  retained, per-frame cost/traffic is not counted for inactive routes.
- Example (b) exercises per-instance long buffers: one Chorus (mono
  1<<18-sample buffer, `ChorusEffect.h`) and one Reverb 2 (12 allpass +
  4 delay buffers of 131 072 + a 1 536 000-sample predelay, `Reverb2.h`) =>
  ~15.6 MB of external writable state for **two** instances.
- The all-FX-off baseline still carries the full voice path, modulation
  rows, and event queue cost: effects are additive on top of it.
- Under the placeholder profile even (c) overflows at the placeholder clock:
  that is a statement about the placeholder numbers, **not** about any real
  technology (see assumptions table).

## 3. Corpus scan (all 3,561 graphs) — model outputs under named assumptions

`reports/sxt-015/corpus-accounting.json` (deterministic; re-run reproduces
it byte-identically). Headlines:

- **FX instance fit (enabled instances, candidate limits):**
  - limit **4**: **2,912 / 3,561** fit (factory 638/641, contributor
    2,274/2,920); 649 exceed (machine-readable reasons in
    `exceeds_candidate_limits["4"]`).
  - limit **8**: **3,530 / 3,561** fit (factory 641/641, contributor
    2,889/2,920); **31 exceed**, max observed 12 enabled instances
    (`Jacky Ligon/Soundscapes/XTease.fxp`).
- **Census cross-check: PASS** — configured non-Off slot counts re-derived
  from the normalized graphs match `corpus/census-v0.1` per-preset counts
  for 3,560/3,560 comparable entries (`Snare Tight.fxp` has no census FX
  count: the static parser could not read its raw XML; the native loader
  resolved it in SXT-011 and it is accounted normally here). Instance fits
  are deliberately >= the census slot fits because `fxd`-disabled slots do
  not process.
- **Instance vs type:** 707 presets have more enabled instances than
  distinct types (188 with two or more enabled Delay instances — 173 exactly
  two; 224 with two or more enabled Airwindows instances, of which 44 repeat
  the same algorithm id; 170 with two or more enabled EQ instances) — type
  counts alone would understate instance state.
- **External writable memory:** 2,987 presets carry external-class state;
  max single-preset external state 62.6 MB (multi-Reverb2/Delay cases);
  max modeled external traffic 48.4 MB/s (placeholder word width, 48 kHz).
- **Voice distribution (worst case):** dominated by polylimit 16
  (2,978 presets; `voice_pool_limit` 32 binds only where polylimit > 32).
  Worst unison-oscillator instances reach 1,536 (heavy supersaw presets).
- **Anomalies surfaced (explicit, never silent):** 58 presets carry unison
  outside 1..16 (clamped to MAX_UNISON with raw value recorded); 87 presets
  declare the audio-input dependency; 577 MSEG/Formula LFO content gaps and
  599 scene-LFO (SLFO) export gaps (SXT-011 exposure notes, state counted
  at engine constants); 2,178 presets include at least one FX class whose
  exact state is not yet pinned (conservative placeholder; 2,363 as first
  written — the #117 Conditioner promotion, absorbed by the §8 re-export);
  2 presets have wavetable assets whose flash bytes cannot be quantified
  from the graph (recorded, not guessed).
- **Budget closure under placeholder-v0:** **75 within budget / 3,486
  OVERFLOW** at the placeholder clock (84 / 3,477 as first written, before
  the §8 modulation-shape decision moved 9 presets; that decision's flip
  list is enumerated in §8.3 and in
  `decision-239-modroute-shape.json`). This split demonstrates the closure
  machinery; it is NOT a technology result.

**Stop/escalate note (per issue #10):** 31 presets (0.9%) exceed 8
instances. This is recorded as a bounded finding for SXT-013/SXT-017
(candidate contract revision), not a silent limit weakening. The list is
committed in `corpus-accounting.json`.

## 4. Assumptions table (named; see `model/resources/params.py` for all)

| Assumption | Value | Kind | Replaced by |
|---|---|---|---|
| Clock F for closure | 480 MHz | placeholder | SXT-016 measured/assumed gf180mcu timing |
| Reserve | 20% of gross | policy (plan §5) | SXT-017 freeze |
| External sustained bandwidth | 800 MB/s | placeholder | SXT-016 + DX7 H01/H02 arbitration alignment |
| Cost profile | `placeholder-v0` (all `cyc_*`) | placeholder | SXT-016 kernel measurements |
| Voice pool limit | 32 voices | policy | SXT-017 (plan §3 starts at 8 scene voices) |
| FX instance limits | candidates {4, 8} | policy | SXT-017 freeze |
| External threshold | 64 KiB writable class | policy | SXT-017 memory map |
| Word width | 4 B (float32) | policy | SXT-016/023 fixed-point re-derivation |
| Event queue depth | 16 (worst fixture burst 8, power-of-two) | corpus_derived | SXT-021 scheduling design |
| Unverified FX class state | 1 MiB, ext-classified, flagged | placeholder | SXT-028 per-algorithm leaf issues |
| Delay param-derived sizing margin | +12 semitones on the time exponent | placeholder | SXT-023 (`Delay.h` modulatable range) |

## 5. Negative controls (live; each targets a specific failure mode)

| Control | Targeted failure | Demonstrated outcome |
|---|---|---|
| `nc-instance-limit-overflow.json` (fixture `/tmp/sxt-015-nc-fx5.jsonl`) | silently squeezing an over-limit graph | 5-instance graph REJECTED with `fx_instance_overflow` at limit 4; same graph fits at limit 8 => rejection is limit-driven and explicit. **PASS** |
| `nc-analysis-failure-fails-closed.json` | default costs for a non-normalized graph | `analysis_failure` input => null cost objects, fail closed. **PASS** |
| `nc-budget-overflow.json` (declared experiment: clock overridden to 1 MHz) | hiding a budget overflow | explicit `budget_overflow` rejection object. **PASS** |
| `nc-unison-out-of-range.json` | trusting or dropping out-of-range unison | `unison_out_of_range` anomaly with raw value + engine-constant clamp. **PASS** |
| `nc-modroute-shape.json` (§8) | a shape change that leaves every account numerically identical, or one that scales the wrong rows | three arms off one real base graph with every modulation list emptied and three DECLARED filter-destination rows placed on exactly one bus: voice rows at 16 worst-case voices charge 720 cyc vs the retired shape's 45; the same rows at polylimit 1 charge exactly the retired 45; the same rows on the SCENE list charge 45 at 16 voices. **PASS** |

## 6. What remains unproved

- Every cycle, bandwidth, and state-bytes number for unverified classes is a
  named placeholder until SXT-016/023/024/028 measure or pin it.
- No synthesis/place-and-route/signoff, no hardware playback, no fidelity,
  and no preset-quality claim is made or advanced by this issue.
- Scene-LFO (SLFO) definitions and MSEG/Formula curves are SXT-011 export
  gaps; they are counted at engine constants and flagged, not interpreted.
- Delay param→line sizing (incl. modulatable range) needs SXT-023
  confirmation; the allocated-line constant is used for worst-case state
  regardless of set time.
- The 31 over-8 presets are a bounded finding awaiting the SXT-013/SXT-017
  contract decision, not a support statement in either direction.

---

## 7. CLASS-TABLE RECONCILIATION (2026-09-27) — Reverb 2 per-sample traffic, issue #127

**Outcome: the row is NOT corrected. It is deliberately RETAINED at the
conservative over-estimate, the retention is now declared and
machine-checked, and the correction is routed to #12.** Acceptance option
(b) of issue #127, chosen because option (a) trips that issue's own
stop/escalate clause (§7.4).

### 7.1 The discrepancy, and the structure that settles it

`model/resources/fx_classes.py` carries, for `reverb2`, **40 reads / 18
writes** per sample per instance. SXT-028f's frozen model measures **29 / 17**
with its own `ext_read`/`ext_write` counters and derives the same figure from
the pinned structure:

| leg | reads | writes |
|---|---:|---:|
| predelay ring | 1 | 1 |
| 12 allpass rings (`allpass::process`, 1r + 1w each) | 12 | 12 |
| 4 delay rings (`delay::process`: 2 plain output taps t1/t2 + 2 reads for the one 2-point sub-sample interpolated recirculation read, 1 write) | 16 | 4 |
| **total** | **29** | **17** |

Only the recirculation read is interpolated; the two output taps are plain
single reads, which is what the retired row's comment ("4 delays (2 taps x
subsample interp + 1 write)") got wrong. Even counting *both* taps as
interpolated gives 37, not 40, and `(40 − 1 predelay − 12 allpass) = 27` is
not a whole number of reads per delay line — so 40 is not derivable from the
structure under any reading. It is a miscount, not a declared margin.

**State bytes were never in dispute**: `_PINNED_STATE_BYTES["reverb2"]` =
14,532,608 B agrees with the model exactly, before and after this change
(`state_agreement: true`).

### 7.2 What changed in the tree

No accounting output moved. `reports/sxt-015/corpus-accounting.json`,
`examples/*`, `negative-control/*`, `reports/sxt-016/*`, `reports/sxt-017/*`,
`reports/sxt-020/*`, `reports/coverage-v1/*` and `compiler/golden/*` are
**untouched**, and `tools/profile_budget.py` still reproduces the committed
`reports/sxt-017/cost-closure.json` **byte-identically** with this change
applied (verified). What changed:

| file | change |
|---|---|
| `model/resources/fx_classes.py` | the row is now `dict(_RETAINED_OVER_ESTIMATE_TX["reverb2"]["retained"])` — same 40/18 value, one source of truth. The new `_RETAINED_OVER_ESTIMATE_TX` record carries the measured 29/17, the leaf, the leaf artifact and field, the finding id, the *numeric* cost of correcting it, and what retires the hold (`#12`). `retained_over_estimate()` exposes it. The row comment carries the structural derivation. |
| `tools/reverb2_buffer_report.py` | `sxt015_reconciliation` is phrased from the **live** table values instead of a hard-coded sentence (a hard-coded one survives a table edit and then misdescribes it), and now names the **direction** of any disagreement plus whether an over-estimate is *declared deliberate*. New fields: `traffic_direction`, `traffic_over_estimate_is_deliberate`, `traffic_retention_record`. |
| `reports/SXT-028f/artifacts/buffer-requirement.json` | regenerated by that tool (not hand-edited). `traffic_agreement` stays `false` — that is what the regenerated record shows, because the row was retained — but it is now `sxt015_over_estimates` + `deliberate` with the hold attached, not an unexplained disagreement. |
| `tests/test_sxt028f.py`, `tests/test_sxt015_fx_classes.py` | the assertions now pin the *disposition* rather than the bare disagreement (§7.3), and pass unchanged under option (a) as well. |
| `reports/SXT-028f/EVIDENCE.md` §6/§9, `model/resources/README.md` | the finding is marked dispositioned; the retention rule is documented where a reader of the table will find it. |

### 7.3 Controls (live)

- **The row is consumed, not decorative** —
  `test_traffic_row_is_consumed_by_the_accounting_output` flips the `reverb2`
  row by four known deltas `(−11,−1) (+7,0) (0,+3) (+13,+5)` and requires the
  accounting output to move by exactly
  `(Δreads + Δwrites) × mem_word_bytes × processing instances`.
  Demonstrated sensitive: with the accounting path stubbed to a hard-coded
  40/18 (a decorative table) the control fails —
  *"moved the accounting output by 0 B/frame, not the predicted −48 B/frame"*.
  This matters here specifically: a hold is only meaningful if the held row is
  actually read.
- **An undeclared over-estimate is a stale row, and fails** —
  `test_reverb2_traffic_row_is_a_declared_conservative_hold` requires any
  row ≠ measurement to be declared in `_RETAINED_OVER_ESTIMATE_TX`, to be
  conservative **componentwise**, and to state its cost and unblocking
  condition. A retained *under*-estimate can never satisfy it.
- **The hold is one row, not a tier-wide excuse** —
  `test_retained_over_estimate_set_is_exactly_reverb2`.
- **The leaf and the table cannot drift apart** — the measured leg is asserted
  equal to `per_sample_transactions()` *and* to the committed SXT-028f
  artifact; `tests/test_sxt028f.py` separately ties that artifact to the
  model's live counters.
- **Direction is checked, not assumed** — `tests/test_sxt028f.py` fails if
  SXT-015 ever *under*-estimates Reverb 2 traffic, which is the only direction
  that would make a downstream bandwidth result optimistic.

### 7.4 Why the correction is held (stop/escalate fired)

Re-deriving with 29/17 is conservative everywhere in **this** record —
`max_ext_traffic_bytes_per_s` would fall 48,384,000 → 39,168,000 and worked
example (b) 252 → 204 B/frame, with no status, fit count, anomaly code,
rejection code or census verdict moving. But it also moves **4 of the 120
`reports/sxt-017/cost-closure.json` grid cells' `ext_bandwidth_fit` column
from `EXCEEDS` to `within`** — a previously-failing check reading pass, inside
the artifact that #12's escalated profile-v1 freeze decides. Issue #127's
stop/escalate clause names exactly that case and says to route it to #12
rather than bank it. Measured before/after for all 120 cells, the attribution
control, and what the movement does **not** claim: `reports/sxt-017/EVIDENCE.md`
§10.

Note for whoever lands the correction after #12: regenerating
`corpus-accounting.json` will also absorb two deltas that are **already**
stale on `main` and have nothing to do with this row —
`event_profile.sequence_fixtures` 10 → 18 with `peak_events_per_second`
13.333333 → 137.142857 (SXT-012 fixture growth) and
`anomaly_code_counts.class_state_unverified` 2,363 → 2,178 (the #117
Conditioner promotion), both already recorded in
`reports/sxt-017/EVIDENCE.md` §9. Keeping this change artifact-free keeps
those two out of it.

### 7.5 Claim scope unchanged

This is bookkeeping-model accounting, not a measurement. No cycle, area,
technology, fidelity, preset-support or preset-quality claim is made or
advanced; no budget was relaxed; nothing is frozen.

---

## 8. COST-MODEL SHAPE DECISION (2026-09-30) — modulation rows are charged per evaluation, issue #239

**Outcome: the shape change is IMPLEMENTED, not declined.** Modulation rows
are now charged by the scope they are *evaluated* in — a global-list or
scene-list row once per frame, a **voice**-list row once per worst-case live
voice per frame. `cyc_modroute_frame` is **unchanged at 15 cycles per row
evaluation**; the decision changed the evaluation *count*, never the
constant. The second half of the issue (a modulation-source state row) is
decided the other way: **no new row**, the per-voice source registers are
declared *inside* `voice_base_state_bytes`, value also unchanged.

### 8.1 The finding, and why it was implemented rather than held

SXT-036 (#70, fifth increment) measured, on its frozen behavioral schedule
(`rtl/voice/tb_vel.sv` `OPS` counters, five stimuli, a 0..6 route-table
sweep, every run also exact against the frozen model):

```
route evaluations = routes × per-voice control passes
```

i.e. a voice-list row is evaluated once per **live voice** per frame, while
the accounting charged every row **once per frame**, independent of voice
count. `reports/SXT-036/artifacts/cost-accounting.{txt,json}` recorded the
gap as a bounded finding rather than fixing it inside a voice leaf.

Two things separate this from the §7 Reverb 2 case, where a disagreeing row
was deliberately **held**:

1. **Direction.** §7's row is a conservative *over*-estimate, which may be
   retained under a declared hold. This one was an *under*-estimate: it made
   a complete patch look cheaper than the measured schedule says it is.
   A budget-closure model may hold an over-estimate; holding an
   under-estimate would make a future `within_budget` verdict optimistic for
   a reason already known and recorded.
2. **Shape vs constant.** SXT-016 replaces *constants*; the number of times
   a row is evaluated is the model's own structure, which is SXT-015's to
   fix. The constant — the part SXT-016 owns — is untouched here, and no
   probe pins it (asserted over all 76 committed probe records).

**Stop/escalate (per #239): NOT TRIGGERED.** Nothing was frozen: the profile
is still `placeholder-v0`, no candidate limit, pool, budget or acceptance
rule was relaxed, no bundle gained a fit claim, and no preset became
supported (supported-preset delta **0**). The cost-profile *freeze* remains
SXT-017 (#12) work.

### 8.2 What changed in the tree

| file | change |
|---|---|
| `model/resources/accounting.py` | `_split_modroutes()` splits rows by evaluation scope and is now the single row-counting definition (`_count_modroutes()` calls it, so the count and the split cannot drift); `_modroute_evaluations(g, worst_voices)` = `rows_per_frame + worst_voices × rows_per_voice`; `mod_cycles = mod_evaluations × REG.cyc_modroute_frame`; the account carries a new `budget.modulation_rows` block reporting both row classes, the voice count, the evaluation count and the per-evaluation constant. `MODEL_VERSION` 1.0.0 → **1.1.0** (the formula moved, so the version must). |
| `model/resources/params.py` | `cyc_modroute_frame` **value unchanged (15)**; its `estimate_ref` now states the per-*evaluation* semantics, names the measured law, and records that SXT-016 still owns the constant (derived bracket 2..8 ⇒ 15 stays conservative per evaluation). `voice_base_state_bytes` **value unchanged (4096)**; its `estimate_ref` now enumerates the per-voice modulation-source registers explicitly, which is the state-row decision. `params_digest` 646942e9c3887ecb → **a639d3115ae1a0ca**. |
| `tools/account_corpus.py` | negative control 5 (`nc-modroute-shape.json`, §5 table) and `modroute_shape_decision()`, which re-derives the retired shape from each record's own numbers and enumerates every status flip → `reports/sxt-015/decision-239-modroute-shape.json`. |
| `probes/worked_bundle.py` | the SXT-016 worked bundle read a *second copy* of the old formula; it now reads `budget.modulation_rows.row_evaluations_per_frame` off the account. One source of truth. |
| `tools/vel_cost_accounting.py` | SXT-015 pin **re-recorded** (`model_version`, `params_digest`) from the live model — never re-tuned, `cyc_modroute_frame` still pinned at 15 — and the carrier section is now a per-carrier *conformance* check (`shape_resolution`) instead of a divergence record. The remaining constant-level divergence is still recorded, not reconciled. |
| `tools/publish_coverage.py` | two `STRUCTURAL_INPUTS` sha256 pins **revised in the same commit as the data they cover**, as that table's own rule requires: `reports/sxt-020/compile-corpus-scan.json` and `reports/sxt-017/predictions/B4-broad.json`. Each revision carries a comment naming what moved inside the pinned file and why no published gate, status or denominator moved with it (§8.5). |
| `docs/dag.json` | `evidence_sha256` refreshed for nodes 10 (SXT-015) and 11 (SXT-016) because this change edits both EVIDENCE files. Refreshed through `tools/compile_backlog_dag.py render`, never by hand; `--check` (the `dag-check` CI job) then reports PASS with 26 nodes and STALE=0. No node's `status` changed. |
| `tests/test_sxt015_modroute_shape.py` (new), `tests/test_sxt036_vel_cost.py` | see §8.4. |
| regenerated deterministically | `reports/sxt-015/{corpus-accounting.json,examples/*,negative-control/*}`, `reports/sxt-016/{worked-bundles.json,probes/SUMMARY.md}`, `reports/sxt-017/{cost-closure.json,predictions/*,predictions/variants/*}`, `reports/sxt-020/compile-corpus-scan.json`, `reports/coverage-v1/coverage.json`, `compiler/golden/*`, `reports/SXT-036/artifacts/cost-accounting.{txt,json}`. |

### 8.3 What it moved — the flip list, enumerated

Corpus-wide, the modulation term moved for **3,234 of 3,561** normalized
graphs (every preset that has at least one voice-list row); it moved for
none of the others. Nine presets cross the `placeholder-v0` DSP budget
(8,000 cyc/frame at the placeholder clock) as a result. **Every flip is
`fit → rejected`**; `status_flipped_toward_fit` is empty and must stay empty
— the new shape charges ≥ the retired one for every graph
(`worst_case_voices ≥ 1`), so no account can get cheaper.

| preset | bank | worst voices | rows per-frame / per-voice | row evals/frame | modulation cyc (retired → this) | total cyc (retired → this) |
|---|---|---:|---|---:|---:|---:|
| `patches_3rdparty/Luna/MPE/FM Trumpet.fxp` | contributor | 16 | 1 / 5 | 81 | 90 → 1215 | 7310 → 8435 |
| `patches_3rdparty/Malfunction/Brass/Clean Trumpet.fxp` | contributor | 16 | 5 / 24 | 389 | 435 → 5835 | 7655 → 13055 |
| `patches_3rdparty/Slowboat/Basses/Bass Guitar 3.fxp` | contributor | 3 | 0 / 20 | 60 | 300 → 900 | 7940 → 8540 |
| `patches_3rdparty/Slowboat/Basses/Bass Guitar 5.fxp` | contributor | 2 | 0 / 31 | 62 | 465 → 930 | 7785 → 8250 |
| `patches_3rdparty/Slowboat/Drums/Toms 1.fxp` | contributor | 2 | 8 / 34 | 76 | 630 → 1140 | 7850 → 8360 |
| `patches_3rdparty/Slowboat/Drums/Toms 2.fxp` | contributor | 2 | 10 / 41 | 92 | 765 → 1380 | 7985 → 8600 |
| `patches_3rdparty/Slowboat/FX/Water Tank.fxp` | contributor | 8 | 8 / 3 | 32 | 165 → 480 | 7725 → 8040 |
| `patches_factory/Basses/FM Slap.fxp` | factory | 16 | 0 / 4 | 64 | 60 → 960 | 7280 → 8180 |
| `patches_factory/Polysynths/Shenanigans.fxp` | factory | 16 | 5 / 3 | 53 | 120 → 795 | 7340 → 8015 |

Corpus closure therefore reads **75 within budget / 3,486 OVERFLOW**
(was 84 / 3,477). **A `placeholder-v0` closure verdict is not a
preset-support claim in either direction** — it is a demonstration that the
closure machinery runs against named placeholders, and the profile is the
very thing SXT-016 replaces. No preset's *support* status changed anywhere
(§8.5).

The four carriers #70 named are all already `rejected` under
`placeholder-v0`, so on them the decision changed a term and no verdict, as
that issue predicted; the nine flips above are the corpus-wide part that its
scope note did not cover.

### 8.4 Controls (live; each demonstrably fails the check it targets)

- **The shape is actually different** — `nc-modroute-shape.json` (§5) and
  `test_the_failure_control_of_the_issue_actually_fires`: voice rows at 16
  worst-case voices charge 720 cyc where the retired shape charges 45; the
  identical rows at polylimit 1 charge exactly the retired 45; the identical
  rows moved to the *scene* list charge 45 even at 16 voices. A change that
  left every account numerically identical, or that scaled every row, fails
  all three arms.
- **The right rows scale, by the right factor** —
  `test_the_shape_is_consumed_row_class_by_row_class` moves the row split by
  five known deltas and requires the accounted term to move by exactly
  `(Δscene_rows + Δvoice_rows × worst_voices) × cyc_modroute_frame`.
- **Mutation-checked, twice, in opposite directions.** With
  `_modroute_evaluations` reverted to `rows_total` (the retired shape) in the
  live model, **12** tests across `tests/test_sxt015_modroute_shape.py` and
  `tests/test_sxt036_vel_cost.py` FAIL, including the flip-list re-derivation.
  With it mutated the *other* way — `worst_voices × rows_total`, i.e. scaling
  **every** row class instead of only the voice rows — a different **12** fail,
  among them
  `test_a_graph_with_no_voice_rows_is_voice_count_independent` and the
  `(Δscene_rows, 0)` arms of the row-class test, which the first mutant leaves
  green. Restoring the shape returns both sets to green. So the suite pins the
  shape from both sides: neither "changed nothing" nor "scaled everything"
  passes it.
- **The flip list is generated, not hand-maintained** —
  `test_the_committed_decision_record_is_re_derivable` re-scans all 3,561
  graphs and requires byte-equality with the committed record;
  `test_every_flip_is_toward_rejection_and_is_explained_by_voice_rows`
  requires every entry to have voice rows, `worst_case_voices > 1`, no other
  rejection code, and the budget strictly between the two totals.
- **The measured law is still the source** — `tools/vel_cost_accounting.py`
  re-runs the iverilog measurement and now *fails* if any carrier's
  accounted modulation term stops equalling `evaluations ×
  cyc_modroute_frame` (`shape_resolution.per_carrier`), and its pin still
  REFUSES (exit 2) on any SXT-015 drift.

### 8.5 Downstream artifacts — what moved, and what did not

- `reports/sxt-017/predictions/*` (5 headline + 7 variants): per-preset
  `status`, every `reasons` list, `totals`, `per_bank` and `slate_coverage`
  are **identical** for all 3,561 entries in all 12 artifacts. What moved is
  the reported `cost_cycles_per_frame_placeholder_v0` column (3,234
  presets), the `budget_closure_placeholder_v0` column (9 presets at pool
  16 — B3/B4/R0 — and 80 at pool 8 — B1/B2 — all `within_budget →
  OVERFLOW`), their aggregates, and `provenance.accounting_model_version`.
  Cycles gate nothing in that stage by construction (§8 addendum), so no
  prediction verdict depends on this change.
- `reports/sxt-017/cost-closure.json`: `worst_mixed_cycles_per_frame` in
  **48 of 120** grid cells, all **upward** (48 up, 0 down), and
  `lanes_required_floor_mixed` in **3** cells (B1 @96 MHz M32 7 → 8;
  B2 @96 MHz M32 13 → 14, twice). **Unchanged:** every cell `verdict`,
  `worst_probe_only_cycles_per_frame` (the modulation term is a placeholder
  component, excluded from the lower bound by construction), every
  `ext_*` column, `admissible`, `fit_claimable`, `selected_bundle`
  (`B1-core-narrow`), `selected_bundle_fit_claim` (`false`), `goal_test`,
  `stop_escalate` and `stop_escalate_reasons`. Unlike §7.4 the movement is
  **pessimistic**, so no previously-failing check reads as passing and
  nothing is routed to #12 by this change.
- `compiler/golden/*` + `reports/sxt-020/compile-corpus-scan.json`:
  regenerated (`compiler/build_golden.py`, `compiler/compile.py scan`);
  `compiler/verify.py golden` 183 checks PASS, `controls` 17 checks PASS.
  The scan's only changed field is
  `provenance.accounting_model_version` — all 3,561 compile statuses and the
  2 named reconciliation deltas are unchanged.
- `reports/coverage-v1/` (SXT-029 publication): two `STRUCTURAL_INPUTS` pins
  in `tools/publish_coverage.py` are revised in this commit, because that
  tool REFUSES (exit 2) rather than republishing over moved inputs and its own
  rule is that "the pin changes in the same commit as the data". The pinned
  files are the two regenerated above — `reports/sxt-020/compile-corpus-scan.json`
  and `reports/sxt-017/predictions/B4-broad.json`. Re-published:
  **`per-preset.csv` is byte-identical**, and the only change in
  `coverage.json` is the two recorded input sha256 values — so no
  `headline_status`, no gate cell, no `b4_prediction`, no slate membership and
  no denominator moved. `tests/test_sxt029_publication.py` (5 tests) passes,
  including its stale-pin-must-downgrade control. **Coverage claim delta: 0.**
- **STALE BASIS in three SXT-027 artifacts, deliberately not regenerated:**
  `reports/sxt-027/{leaf-plan,leaf-backlog,leaves-filed}.json` each record the
  compile-scan sha256 they were generated from
  (`inputs.compile_scan = e23e351c…`), which is now the superseded value.
  Their *content* is derived from compile statuses and leaf attribution, none
  of which this change moves, and two of the three are themselves pinned
  structural inputs — re-emitting them is an SXT-027 leaf-ledger revision, not
  a cost-model one. Recorded as STALE, not corrected; noted on follow-up #246
  alongside the image snapshots below.
- **NOT regenerated, pre-existing drift unrelated to this change:**
  `reports/sxt-016/probes/probe_scheduler__event_queue_and_control__a24__m{18,32}__onchip.json`
  record `fixture_files` / `total_events_across_fixtures` from the SXT-012
  sequence library, which grew on `main` (10 → 18 fixtures) without a probe
  re-run. Re-running `probes/run_all.py` therefore moves those two records
  for a reason that has nothing to do with the modulation shape, so they are
  left exactly as committed and only the two artifacts this change actually
  moves (`worked-bundles.json`, `probes/SUMMARY.md`) are taken from that run.
- **Absorbed, pre-existing, and NOT caused by this change** (both already
  flagged in `reports/sxt-017/EVIDENCE.md` §9 and in §7.4 above as awaiting
  the next re-export): `event_profile.sequence_fixtures` 10 → 18 with
  `peak_events_per_second` 13.333333 → 137.142857 (SXT-012 fixture growth),
  and `anomaly_code_counts.class_state_unverified` 2,363 → 2,178 (the #117
  Conditioner promotion). Neither moves any status: re-scanning with the
  *retired* shape and today's tree reproduces the committed 84 / 3,477
  closure split exactly, so all nine flips are attributable to the shape and
  to nothing else.
- **STALE BASIS, deliberately not regenerated here:** three committed image
  snapshots still record the superseded accounting basis
  (`sxt-015-accounting/1.0.0` / `646942e9c3887ecb`) —
  `model/integration/preset/Hell_s_Bells__e499f78d.image.json`,
  `reports/sxt-026/artifacts/Kick__4f2443aa.image.json`,
  `reports/sxt-025/negative-controls/image-permuted-placement.json`. They
  are self-verifying snapshots whose own leaves' claims (SXT-025 integration
  exactness, SXT-026 wavetable, placement controls) do not read the
  modulation term, and re-emitting them means re-pinning each leaf's
  recorded image sha256 — that belongs to those leaves, not here. Recorded
  as STALE, not corrected, and filed as follow-up #246.

### 8.6 What this does NOT establish

`cyc_modroute_frame` is still a `placeholder` that **no** SXT-016 probe
pins, and SXT-036's own derived bracket (2..8 cycles per evaluation, under
two named readings of A-DSP-1c / A-ALU-1) is derived, not measured. So this
is a *shape* correction inside a bookkeeping model: no cycle, area,
technology, timing, synthesis, fidelity, preset-support or preset-quality
claim is made or advanced, no profile is frozen, and the voice-row term is
deliberately an upper bound in dual/split scene modes (a pool voice is
resident in exactly one scene) in the same conservative style as the
per-voice osc/filter terms. Supported-preset delta: **0**.

## 9. CURRENCY CHECK (2026-09-30) — the export is now kept current by CI, issue #247

The two deltas §7.4 says "the next re-export will absorb" were absorbed by
the #239 re-export (§8.5) without any check having flagged them: unlike
`reports/sxt-017/*` and `reports/sxt-020/*`, this directory had no test that
re-runs its generator. `tests/test_sxt015_currency.py` adds one in the same
style.

**What it checks.** `tools/account_corpus.py` is re-run in full (all 3,561
graphs, worked examples, negative controls) into a temp dir; every emitted
file must be byte-identical to its committed copy, and the two file sets must
match (orphans and un-committed new outputs both fail). One file is exempt by
name: this `EVIDENCE.md`, which the tool does not emit. No subset is sampled.
Runtime: one scan ~4-5 s CPU; the module (one full run plus three sandbox
control runs) ~17 s CPU / ~31 s wall on the #247 build host.

**Status when it landed:** PASS — `main` at `dbd8df0` regenerates byte-for-byte,
so no artifact was re-exported by this change and nothing moved.

**Decision on the fixture library.** `fixtures/sequences/` is treated as a
first-class input with no tolerance window: a fixture that moves the export
fails the check until the export is regenerated in the same change. It is not
cost-neutral by construction — `max_coincident_events > event_queue_depth` is
an `event_queue_overflow` rejection, and the profile's peaks are copied into
each worked example's `account.events` — and "current except for fixtures"
would not tell a reader which inputs the export was computed against. To keep
such re-exports reviewable, a failure names the top-level keys that moved.
A re-export that moves a status, fit count, rejection code or anomaly count is
still enumerated here first (the §8.3 pattern).

**Failure controls (live).** Both run in the suite against a sandbox copy of
the tool's inputs (preceded by an unmutated-sandbox control that must stay
current), and were also run once against the real tree, then reverted:

| mutation | check result | finding |
|---|---|---|
| copy `seq-poly-8-v1.json` to a new 19th fixture | **FAIL** | `corpus-accounting.json: stale (top-level keys moved: event_profile)` |
| rename the `Conditioner` key in `_NO_LONG_BUFFER_MEASURED` (reverts the #117 promotion) | **FAIL** | `corpus-accounting.json: stale (top-level keys moved: anomaly_code_counts)` |

Claim scope: bookkeeping freshness only. No cycle, area, technology,
fidelity, preset-support or preset-quality claim; supported-preset delta
**0**.
