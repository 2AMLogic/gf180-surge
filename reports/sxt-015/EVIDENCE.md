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
| 5 | Negative control: a graph exceeding declared instance limits must be rejected, not silently squeezed | **PASS** | `reports/sxt-015/negative-control/nc-instance-limit-overflow.json`: synthetic 5-instance graph (via `/tmp/sxt-015-nc-fx5.jsonl`) => `fx_instance_overflow` rejection at limit 4, fit at limit 8 (limit-driven). Controls 2–4: analysis_failure fails closed with null costs; budget overflow explicit; unison out of range flagged and clamped. All four controls PASS. |

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
  at engine constants); 2,363 presets include at least one FX class whose
  exact state is not yet pinned (conservative placeholder); 2 presets have
  wavetable assets whose flash bytes cannot be quantified from the graph
  (recorded, not guessed).
- **Budget closure under placeholder-v0:** 84 within budget / 3,477
  OVERFLOW at the placeholder clock. This split demonstrates the closure
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
