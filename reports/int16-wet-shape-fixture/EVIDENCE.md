# int16 wet tail-SHAPE grading: which committed fixture is clear of the quantization band (evidence record)

Issue: #187 · Parent: #21 (SXT-028 expansion) · Continuation of: #160 /
[`decision-records/0016`](../../decision-records/0016-int16-tail-shape-leg-floor.md)
option **F-E** (recorded there as NOT_RUN) · Source control: #111 ·
Routes to: SXT-017 (#12) · Date: 2026-09-27

Decision recorded in
[`decision-records/0017`](../../decision-records/0017-int16-wet-tail-shape-grading-fixture.md)
and in `contracts/fidelity-policy-DRAFT.md` §2.5(d). Measurement tool:
`tools/int16_wet_shape_fixture_probe.py`. Tests:
`tests/test_pilot_freeze_tail_shape_floor.py`.

**Claim discipline.** This is a **comparator- and fixture-selection** record.
It establishes four things and nothing else: (1) 7 of the 30 committed int16
wet fixtures already grade their whole declared tail region with the worst
graded window at least 20 dB clear of the int16 ±1 LSB band, so no new render is
needed to get the shape leg out of the quantization regime; (2) on the
designated one of those fixtures the #111 mono late-tail controls — including a
re-derived single-window control that replaces the one whose only defect window
sat inside the band — all FAIL, and every over-budget window of every one of
them lies above the band; (3) on that fixture the controls are insensitive to
the floor anywhere across the band; (4) on the OLD fixture the #160 failure
control still fires. It makes **no** model-vs-reference fidelity claim, **no**
RTL claim, **no** preset-support or coverage claim, and **no** sound-quality
claim (no human listening). It **freezes no budget**: the tail-shape values
remain `[PROPOSED-TO-BE-FROZEN-AT-PILOT]` and the freeze is SXT-017's (#12).

**No committed budget, render, or verdict changed.**
`tools/compare_audio_reference.py` still ships
`decay_curve_floor_dbfs = -100.0` and `decay_curve_max_dev_db = 1.0`. The probe
applies candidate floors by patching the *imported* `PROPOSED_TAIL` dict inside
its own process; the tool file is untouched. No fixture was rendered, added,
edited, or removed, and `fixtures/manifest.json` is unchanged. Consequently no
landed wet verdict, comparison artifact, or coverage number is invalidated by
this issue, and #187's route-2 "re-run every landed wet verdict" arm does not
apply — it is reported below as NOT_REQUIRED, never as a pass.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| A committed int16 wet fixture whose DECLARED tail region has **no** graded window inside the quantization band and a worst-case ±1 LSB spend of ≤10 % of the deviation budget exists — 7 of 30 do | **PASS** (leg 1) | `artifacts/fixture-probe.txt` §1 |
| The fixture #160 measured the conflict on (`koala2/seq-notes-coverage-v1`) is **ineligible**: 23/50 windows graded, lowest graded −85.1 dBFS, worst-case ±1 LSB spend 3.79 dB = **379 %** of the 1.00 dB budget, 7 graded windows in band | **PASS** (leg 1) | `artifacts/fixture-probe.txt` §1 |
| The #111 mono late-tail controls re-derived on the designated fixture all FAIL, and **every** over-budget window of **every** FAIL control lies above the band (lowest −46.7 dBFS vs the −72.0 dBFS edge) | **CONTROL-OK**, 7/7 (leg 2) | `artifacts/fixture-probe.txt` §2 |
| The re-derived single-window control `zero-late-tail-from-98%` FAILs on the **shape leg alone** (global budgets and the residual leg pass) through exactly window 49 at −46.7 dBFS — the direct replacement for `mono/koala2/zero-late-tail-from-44%`, whose one defect window sat at −81.9 dBFS *inside* the band | **CONTROL-OK** (leg 2) | `artifacts/fixture-probe.txt` §2 |
| A ±1 LSB dither over the first half of the declared tail spends **0.00 dB** (measured 6.5 × 10⁻⁶ dB) of the 1.00 dB budget on the designated fixture (0016 leg 2 measured **0.79 dB** for the same control on `koala2/seq-notes-coverage-v1`) | **PASS** (leg 2) | `artifacts/fixture-probe.txt` §2 |
| On the designated fixture, floors at −84.4, −80.0 and −72.0 dBFS change no control status and no graded-window count (50/50 throughout) | **PASS** (leg 3a) | `artifacts/fixture-probe.txt` §3 |
| Failure control: on the OLD fixture, `mono/koala2/zero-late-tail-from-44%` still FAILs at the declared floor and is still **DISABLED (FAIL → PASS)** at −80.0 and −72.0 dBFS | **CONTROL-OK** — the reason the fixture changed is still live | `artifacts/fixture-probe.txt` §3, `tests/test_pilot_freeze_tail_shape_floor.py` |
| A new fixture render under the pinned reference manifest (SXT-010) | **NOT_REQUIRED** (measured: 7 committed fixtures already qualify). The pinned oracle is external and macOS-only (`oracle/manifest.json`), so a render would be operator-side; none was attempted or claimed | this section, `decision-records/0017` §1 |
| Bus-side arm (grade the mono wet path on a higher-resolution bus) | **NOT_RUN** — rejected for #187 on measurement and prerequisite, not attempted | `decision-records/0017` § "The bus-side arm (route 2) is REJECTED" |
| Landed wet verdicts re-run | **NOT_REQUIRED** (no constant, bus, fixture, or render changed); #111's own re-run remains the current one | `reports/tail-shape-leg/artifacts/landed-verdict-rerun.txt` (unmodified) |
| Any fidelity, support, coverage, or quality claim | **none made** | this section |

Run: `python3 tools/int16_wet_shape_fixture_probe.py` at repo HEAD
`577eea9609ae` (worktree; the only uncommitted files were this issue's own),
numpy 1.26.4, Python 3.12.3, 2026-09-27. Overall **PASS**.

## 1. Eligibility survey (leg 1)

The band arithmetic is 0016's, recomputed from the shipped constants: one int16
LSB RMS is **−90.3 dBFS**; a ±1 LSB model difference alone exceeds the 1.00 dB
deviation budget below **−84.4 dBFS** (incoherent) and below **−72.0 dBFS**
(coherent worst case); the declared quantization-dominated band is
**[−100.0, −72.0] dBFS**.

A committed int16 wet fixture is **eligible to carry the shape leg** when, over
its declared tail region:

1. **coverage** — `graded_windows == total_windows` at the declared floor, and
2. **quantization headroom** — the lowest graded window's worst-case coherent
   ±1 LSB spend `20·log10(1 + 1/r_LSB)` is at most **10 %** of
   `decay_curve_max_dev_db`, i.e. ≤ 0.10 dB, i.e. a lowest graded window at or
   above **−51.6 dBFS** (20.5 dB above the band edge, 38.7 dB above one LSB).

Neither clause is a grading budget — they select a fixture, and no verdict is
derived from them.

| Fixture (declared wet tail region) | graded/total | lowest graded | windows in band | worst-case ±1 LSB spend | eligible |
|---|---|---|---|---|---|
| `behemoth/seq-tempo-change-v1` | 50/50 | −45.7 dBFS | 0 | 0.05 dB (5 %) | **YES** |
| `behemoth/seq-modwheel-v1` | 50/50 | −46.5 dBFS | 0 | 0.06 dB | **YES** |
| `behemoth/seq-macro-sweep-v1` | 50/50 | −46.6 dBFS | 0 | 0.06 dB | **YES** |
| **`behemoth/seq-notes-holds-v1` (DESIGNATED)** | **50/50** | **−46.7 dBFS** | **0** | **0.06 dB (5.7 %)** | **YES** |
| `behemoth/seq-notes-repeated-v1` | 50/50 | −47.0 dBFS | 0 | 0.06 dB | **YES** |
| `behemoth/seq-pitchbend-v1` | 50/50 | −47.5 dBFS | 0 | 0.06 dB | **YES** |
| `behemoth/seq-sustain-pedal-v1` | 50/50 | −49.1 dBFS | 0 | 0.08 dB | **YES** |
| `behemoth/seq-pressure-v1` | 50/50 | −52.1 dBFS | 0 | 0.11 dB (11 %) | no — headroom |
| `behemoth/seq-poly-8-v1` | 50/50 | −68.5 dBFS | 0 | 0.68 dB (68 %) | no — headroom |
| `behemoth/seq-notes-coverage-v1` | 50/50 | −69.3 dBFS | 0 | **0.74 dB (74 %)** | no — headroom |
| `sub4/*` (10 fixtures) | 2/50 … 10/50 | −80.6 … −84.2 dBFS | 1 | 2.45 … 3.49 dB | no — coverage + headroom |
| `koala2/*` (10 fixtures) | 23/50 … 33/50 | −83.1 … −99.8 dBFS | 7 … 10 | 3.15 … 12.04 dB | no — coverage + headroom |
| — of which **`koala2/seq-notes-coverage-v1`** (the #160 conflict fixture) | 23/50 | −85.1 dBFS | 7 | **3.79 dB (379 %)** | no |

Full per-fixture rows: `artifacts/fixture-probe.txt` §1 and
`artifacts/fixture-probe.json` `legs.1.rows`.

**Two things this table settles.** First, the fixture-side arm of F-E needs **no
new render**: 7 committed fixtures already satisfy both clauses. Second, *being
outside the declared band is not the same as having quantization headroom* —
`behemoth/seq-notes-coverage-v1`, the fixture #111's landed mono Behemoth
controls use, has 0 windows in the band yet would still lose 74 % of the
deviation budget to a worst-case ±1 LSB difference in its lowest graded window
(−69.3 dBFS, only 2.7 dB above the edge). That is why the designation moved to
`seq-notes-holds-v1` rather than staying on `seq-notes-coverage-v1`.

## 2. The re-derived controls (leg 2)

Designated fixture `fixtures/audio/behemoth/seq-notes-holds-v1-wet.wav`,
declared wet tail region `[177600, 297600)`, 2400-frame (50 ms) windows, graded
through the real `compare_audio_reference.main()` entry point at the declared
floor. Every control model is derived from the committed reference render
(baseline model := reference), so a PASS is a tool self-test, never a fidelity
result.

Each control's full name carries the **sequence** as well as the preset —
`mono/behemoth/seq-notes-holds-v1/<suffix>` — because the landed #111 mono
Behemoth controls use the same suffixes on `seq-notes-coverage-v1` and the two
sets must never be confused. The suffixes alone are shown below.

| Control | required | observed | over-budget windows | lowest over-budget level | shape leg sole failing leg | result |
|---|---|---|---|---|---|---|
| `baseline` | PASS | PASS | none | — | — | CONTROL-OK |
| `zero-late-tail-from-40%` | FAIL | FAIL | 30 | −46.7 dBFS | no (residual leg fails too) | CONTROL-OK |
| `zero-late-tail-from-60%` | FAIL | FAIL | 20 | −46.7 dBFS | no (residual leg fails too) | CONTROL-OK |
| `zero-late-tail-from-95%` | FAIL | FAIL | 3 (47, 48, 49) | −46.7 dBFS | **yes** | CONTROL-OK |
| `zero-late-tail-from-98%` | FAIL | FAIL | **1 (49)** | **−46.7 dBFS** | **yes** | CONTROL-OK |
| `late-tail-decays-too-fast-from-40%` | FAIL | FAIL | 29 | −46.7 dBFS | no (residual leg fails too) | CONTROL-OK |
| `dither-first-half` (±1 LSB) | PASS | PASS | none | — | — | CONTROL-OK |

7/7 controls behaved as required **and** failed only above the band
(edge −72.0 dBFS; the lowest over-budget window of any control is −46.7 dBFS,
25.3 dB clear).

`zero-late-tail-from-98%` is the re-derivation that matters: it zeroes exactly
one graded window — the last one — so it is the structural twin of
`mono/koala2/zero-late-tail-from-44%`, which also failed through exactly one
window. The difference is the level: **−46.7 dBFS here, −81.9 dBFS there.** The
comparator's demonstrated single-window late-tail sensitivity is therefore now
exercised 43.6 dB above one int16 LSB RMS instead of 8.4 dB above it.

The ±1 LSB dither control is the other half of the same statement: the same
deterministic ±1 LSB pattern that spends **0.79 dB of the 1.00 dB budget** on
`koala2/seq-notes-coverage-v1` (0016 leg 2, finding F1) spends **0.00 dB**
(6.5 × 10⁻⁶ dB) here.
On the designated fixture the budget is not being consumed by quantization.

## 3. Floor-insensitivity pair — the failure control (leg 3)

**(a) The designated fixture no longer grades inside its own quantization
noise.** Every control above was re-graded at −100.0 (declared), −84.4, −80.0
and −72.0 dBFS. No status changed and no graded-window count changed (50/50 at
every floor): there is nothing in the band for a floor inside the band to
ungrade.

**(b) The reason the fixture changed is still demonstrable on the old
fixture.** #160's live control was re-run here:

| Floor | `mono/koala2/zero-late-tail-from-44%` | graded windows |
|---|---|---|
| **−100.0 dBFS (declared)** | **FAIL** (as landed) | 23/50 |
| −84.4 dBFS | FAIL (as landed) | 22/50 |
| **−80.0 dBFS** | **PASS — DISABLED by the raised floor** | 20/50 |
| **−72.0 dBFS** | **PASS — DISABLED by the raised floor** | 16/50 |

So: the landed control still FAILs at the declared floor (the acceptance
condition #187 names), and a floor raised out of the ±1 LSB band still disables
it on the old fixture (the failure control #187 names). A "fixed" int16 path
whose late-tail controls no longer failed anything would be a broken control
set; this one still fails what it targets.

## 4. Decision (recorded; see `decision-records/0017` for the full record)

Take the **fixture-side** arm of 0016's option F-E: designate
`fixtures/audio/behemoth/seq-notes-holds-v1-wet.wav` as the int16 wet
shape-grading fixture under the two-clause eligibility criterion above, re-derive
the #111 mono late-tail controls on it (adding the single-window
`zero-late-tail-from-98%`), and leave the floor, the deviation budget, the
declared band, the 0016 disposition rule, every committed render, and every
landed verdict exactly as they are. The **bus-side** arm is rejected for #187 —
a full-scale/unit change is cosmetic (dBFS window levels are invariant under the
unit, a property already pinned by
`test_floor_is_one_full_scale_constant_shared_by_every_bus`), a real
higher-resolution bus needs a new render from the external macOS-only pinned
oracle, and its acceptance would require re-grading every landed wet verdict to
reach the same end. It remains open as a future direction with its own record.

## 5. Reproduce

```
python3 tools/int16_wet_shape_fixture_probe.py   # regenerates artifacts/fixture-probe.{txt,json}
python3 -m pytest -q tests/test_pilot_freeze_tail_shape_floor.py
```

`tools/tail_shape_floor_probe.py` (#160) and `tools/tail_shape_leg_checks.py`
(#111) are deliberately **not** modified by this issue, so their committed
artifacts stay reproducible as landed; re-running either still reproduces its
own record.

## 6. What remains unproved

* Nothing here says any model reproduces any reference, any RTL matches any
  model, or any preset is supported or sounds good. No listening took place.
* The quantization band is **avoided on one designated fixture, not removed from
  the int16 bus.** `koala2`, `sub4`, and three Behemoth sequences still grade
  inside it, and an over-budget window inside the band there is still
  dispositioned by `contracts/fidelity-policy-DRAFT.md` §2.5(b) — a bounded
  finding routed to SXT-017 (#12), never a budget change.
* `decay_curve_max_dev_db = 1.0` is still unexercised against a real model wet
  render, on any fixture. The designation makes a future result *readable*
  outside the quantization regime; it does not exercise the budget.
* The 10 % headroom fraction is a declared fixture-selection choice derived from
  the shipped deviation budget, not a measured model property. It is
  deliberately conservative — the designated fixture measures 5.7 %.
* Defects below the declared floor remain invisible to this leg by construction
  (#111 F3); on an eligible fixture there are none inside the graded region
  because every window is graded, but the limit outside the declared tail region
  is unchanged.
* The band edges assume a ±1 LSB per-sample difference. A model differing by
  more than ±1 LSB near the lowest graded window widens the regime
  proportionally; the eligibility arithmetic generalizes (`20·log10(1 + e/r)`),
  but no such case is measured here.
* No new fixture was rendered: the new-render arm of #187's route 1 is
  **NOT_REQUIRED** (measured), and the bus-side arm is **NOT_RUN** (rejected,
  not attempted). Neither is reported as a pass.
