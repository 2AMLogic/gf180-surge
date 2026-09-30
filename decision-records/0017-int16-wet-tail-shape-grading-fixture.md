# 0017 — The int16 wet tail-SHAPE leg grades on a DESIGNATED committed fixture that is clear of the quantization band; the fixture-side arm of F-E is taken, the bus-side arm is rejected on measurement (#187 → SXT-017 #12)

- **Status:** RECORDED — pilot-freeze input. **Amends
  [`0016`](0016-int16-tail-shape-leg-floor.md)** by disposing of its option
  **F-E**, which 0016 recorded as NOT_RUN; it supersedes nothing in 0016 and
  moves no value 0016 pinned. No comparator constant, no committed render, and
  no landed verdict changes with this record. **Owner ratification pending** at
  the SXT-017 freeze ([#12](https://github.com/2AMLogic/gf180-surge/issues/12));
  the tail-shape budget itself remains
  **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.
- **Date:** 2026-09-27
- **Issue:** [#187](https://github.com/2AMLogic/gf180-surge/issues/187)
- **Raised by:** the bounded finding recorded while landing
  [#160](https://github.com/2AMLogic/gf180-surge/issues/160) — the int16 wet
  shape leg's demonstrated late-tail sensitivity and its own ±1 LSB
  quantization noise lived in the same 2 dB of level; parent SXT-028
  ([#21](https://github.com/2AMLogic/gf180-surge/issues/21)), source control
  [#111](https://github.com/2AMLogic/gf180-surge/issues/111)
- **Routes to:** SXT-017 ([#12](https://github.com/2AMLogic/gf180-surge/issues/12))
- **Evidence:** `reports/int16-wet-shape-fixture/EVIDENCE.md`,
  `reports/int16-wet-shape-fixture/artifacts/fixture-probe.txt`,
  `reports/int16-wet-shape-fixture/artifacts/fixture-probe.json`; measurement
  tool `tools/int16_wet_shape_fixture_probe.py`; predecessor evidence
  `reports/pilot-freeze-tail-shape-floor/EVIDENCE.md` §3 and
  `reports/tail-shape-leg/EVIDENCE.md` §4 F1.
- **Enforcement point (unchanged in the comparator):**
  `tools/compare_audio_reference.py` still ships
  `PROPOSED_TAIL["decay_curve_floor_dbfs"] = -100.0` and
  `PROPOSED_TAIL["decay_curve_max_dev_db"] = 1.0`. What this record installs is
  a **fixture-selection rule** in `contracts/fidelity-policy-DRAFT.md` §2.5(d),
  pinned by `tests/test_pilot_freeze_tail_shape_floor.py`.

## Context

0016 kept one declared tail-shape floor (−100.0 dBFS) for every bus and
*declared* the int16 quantization-dominated band **[−100.0, −72.0] dBFS**
rather than raising the floor out of it. That was forced by a measured
conflict on the mono int16 wet bus (full scale 32767, one LSB RMS
−90.3 dBFS):

- the landed #111 negative control `mono/koala2/zero-late-tail-from-44%` fails
  through **exactly one** graded window, window 22 at **−81.9 dBFS**, which is
  *inside* the band;
- the quantization-affected windows of that same fixture reach up to
  **−79.9 dBFS**, so every candidate floor that clears the ±1 LSB regime
  (≥ −80.0 dBFS) ungrades the control's only defect window and flips it
  **FAIL → PASS**.

The comparator is therefore correct but **fixture-limited** there. 0016's
option **F-E** — change the fixture or the bus instead of the budget — was the
only option that removes the regime instead of declaring it, and 0016 left it
explicitly **NOT_RUN**. #187 disposes of it.

## What was measured (`tools/int16_wet_shape_fixture_probe.py`, three legs)

The probe patches the *imported* `PROPOSED_TAIL` dict inside its own process
only; the shipped constants stayed −100.0 dBFS / 1.0 dB throughout, and no
committed render was read for anything but reading.

### Fixture eligibility, and the criterion used to select one

A committed int16 wet fixture is **eligible to carry the shape leg** when both
hold over its DECLARED tail region:

1. **coverage** — every window is graded at the declared floor
   (`graded == total`), so the leg has no coverage gap; and
2. **quantization headroom** — the *lowest graded window* loses at most
   **10 % of `decay_curve_max_dev_db`** to a worst-case coherent ±1 LSB model
   difference, i.e. `20·log10(1 + 1/r_LSB) ≤ 0.10 dB`, which for the shipped
   constants means a lowest graded window at or above **−51.6 dBFS**
   (20.5 dB above the band's upper edge, 38.7 dB above one int16 LSB RMS).

Neither clause is a grading budget: both select a *fixture*, no verdict is
derived from them, and both recompute from the shipped constants.

| Leg | Result |
|---|---|
| **1** eligibility survey of all **30** committed int16 wet fixtures | **PASS** — **7** are eligible, all of them Behemoth sequences (lowest graded window −45.7 … −49.1 dBFS, worst-case ±1 LSB spend 0.05–0.08 dB of the 1.00 dB budget, **0** graded windows in the band). Every Koala 2 and Sub 4 fixture is ineligible; `koala2/seq-notes-coverage-v1` — the fixture 0016 measured the conflict on — grades **23/50** windows, its lowest graded window is **−85.1 dBFS**, its worst-case ±1 LSB spend is **3.79 dB = 379 %** of the budget, and **7** of its graded windows lie inside the band. |
| **2** the #111 mono late-tail controls re-derived on the designated fixture | **PASS** — 7/7 controls behaved as required **and** every over-budget window of every FAIL control lies above the band. `zero-late-tail-from-98%` (exactly the last graded window — the re-derivation of `mono/koala2/zero-late-tail-from-44%`, whose one defect window sat *inside* the band) FAILs through window 49 at **−46.7 dBFS**, 25.3 dB clear of the band edge, on the **shape leg alone** (global budgets and the residual leg both pass). The #93 ±1 LSB dither control spends **0.00 dB** (measured 6.5 × 10⁻⁶ dB) of the budget here, against **0.79 dB** for the same control on `koala2/seq-notes-coverage-v1` (0016 leg 2). |
| **3** floor-insensitivity pair — this issue's failure control | **PASS** — (a) on the designated fixture, floors at −84.4, −80.0 and −72.0 dBFS change **no** control status and reduce **no** graded-window count (50/50 throughout): the fixture no longer grades inside its own quantization noise. (b) On the **old** fixture the retained #160 control still fires: `mono/koala2/zero-late-tail-from-44%` FAILs at −100.0 and −84.4 dBFS and is **DISABLED (FAIL → PASS)** at −80.0 and −72.0 dBFS. |

Run: `python3 tools/int16_wet_shape_fixture_probe.py`, overall **PASS**; numpy
1.26.4, Python 3.12.3, 2026-09-27.

## Decision

1. **The fixture-side arm of F-E is taken; no new render is required.** The
   int16 wet path stops grading tail shape inside its own quantization noise by
   grading it on an **eligible** fixture. Measured: 7 of the 30 already-committed
   int16 wet fixtures satisfy the eligibility criterion above, so the
   "render a new wet int16 fixture" arm of #187's route 1 is reported as
   **NOT_REQUIRED** — measured, and never as a pass. Nothing was rendered,
   nothing was edited, and the fixture set is unchanged.
2. **Designated int16 wet shape-grading fixture:**
   `fixtures/audio/behemoth/seq-notes-holds-v1-wet.wav`
   (50/50 windows graded, lowest graded window **−46.7 dBFS**, worst-case ±1 LSB
   spend **0.06 dB = 5.7 %** of the 1.00 dB budget, **0** windows in the band).
   The other six eligible Behemoth sequences are recorded as alternates in
   `reports/int16-wet-shape-fixture/EVIDENCE.md` §1, so the designation does not
   rest on one lucky render.
3. **`behemoth/seq-notes-coverage-v1` is NOT designated, on measurement.** It is
   the fixture #111's landed mono Behemoth controls use and it has 0 graded
   windows inside the band — but its lowest graded window sits at **−69.3 dBFS**,
   only 2.7 dB above the band edge, where a worst-case coherent ±1 LSB
   difference would still spend **0.74 dB (74 %)** of the 1.00 dB budget. Being
   outside the declared band is not the same as having quantization headroom,
   and this record does not conflate them.
4. **The #111 mono late-tail controls are re-derived on the designated
   fixture**, with one addition: `zero-late-tail-from-98%`, which zeroes exactly
   the last graded window and is the direct re-derivation of
   `mono/koala2/zero-late-tail-from-44%` outside the quantization band. All of
   them FAIL, and every over-budget window of every one of them lies above the
   band. The controls live in `tools/int16_wet_shape_fixture_probe.py` and are
   pinned by `tests/test_pilot_freeze_tail_shape_floor.py`.
5. **No landed control is retired and no verdict moves.**
   `mono/koala2/zero-late-tail-from-44%` remains a landed #111 negative control
   and remains **FAIL** at the declared floor; `tools/tail_shape_leg_checks.py`
   and its committed artifacts are untouched, so the #111 record stays
   reproducible as landed. This record *adds* a designation and a control set;
   it removes nothing.
6. **The retained failure control.** The reason the fixture changed must keep
   being demonstrable on the *old* fixture: a floor raised out of the ±1 LSB
   band must still disable a late-tail negative control there (leg 3b, and
   `test_raising_the_int16_floor_disables_a_landed_negative_control`). A "fixed"
   int16 path whose late-tail controls no longer fail anything would be a broken
   control set, not a success.
7. **The band, the floor, and the deviation budget are unchanged, and the 0016
   disposition rule stays in force.** `decay_curve_floor_dbfs` is still one
   declared −100.0 dBFS constant for every bus, `decay_curve_max_dev_db` is
   still 1.0 dB, and the int16 band **[−100.0, −72.0] dBFS** is still declared.
   A wet comparison on an **ineligible** fixture is still graded, still fails
   closed, and an over-budget window inside the band is still dispositioned by
   §2.5(b) — a bounded finding routed to SXT-017 — never by a budget change.
   This record narrows *which fixture a shape-leg result should be read on*; it
   does not exempt any bus, fixture, or window from grading.
8. **Nothing is frozen and no goal is lowered.** All tail-shape values remain
   `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`; the freeze is SXT-017's (#12). No preset
   promise, polyphony figure, coverage number, or acceptance rule is weakened
   here, and coverage is unchanged because no verdict changed.

## The bus-side arm (route 2) is REJECTED, on measurement and prerequisite

| Why | Measured / derived |
|---|---|
| **A full-scale/bus-unit change alone is cosmetic, not a fix.** `full_scale` is the *unit* the gate reports in; window levels are dBFS, so re-expressing the same committed int16 samples in a finer LSB unit leaves every window level, every graded count, and every deviation **identical**. That property is already pinned by `test_floor_is_one_full_scale_constant_shared_by_every_bus` (the same dBFS-shaped tail grades identically at int16, Q10.21 and Q9.23 full scale). | The quantization step actually present in a committed int16 render is one int16 count (−90.3 dBFS) whatever unit it is reported in. A unit change would move the *declared band arithmetic* away from the real step and buy a silent false-PASS band — the same inference-from-the-representation 0016 rejected as F-B. |
| **A real higher-resolution bus needs a new higher-resolution render**, i.e. the same prerequisite as route 1's new render: the pinned SXT-010 oracle, which lives outside this repository (`oracle/manifest.json`: `/Users/joseph/dev/surge-xt-oracle/surge`, `surgepy.cpython-311-darwin.so`) and is not available to this repository's automation. | Not available in this environment; the render step is operator-side. Reported as **NOT_RUN**, never as a pass. |
| **It disturbs more for the same end.** #187's route-2 acceptance requires re-running *every* landed wet verdict that uses the shared mono gate, because the comparison bus of all of them would change. The fixture-side arm reaches the same end — a shape-leg result read entirely outside the quantization band — while changing **no** bus, **no** constant, and **no** landed verdict. | 0 verdicts re-run because 0 verdicts changed (reported as NOT_REQUIRED, with the reason, not as a pass). |

If the bus-side arm is ever wanted anyway (for example once a float32 mono wet
reference render exists alongside the delivered int16 artifact), it remains
open: this record rejects it as the answer to #187, not as a permanent
direction, and it would need its own record, its own render evidence, and the
landed-verdict re-run its acceptance names.

## Consequences

- `contracts/fidelity-policy-DRAFT.md` §2.5 gains clause **(d)**: the
  eligibility criterion, the designated fixture, and the rule that a
  shape-leg-based claim about a wet tail is read on an eligible fixture, with an
  ineligible-fixture result dispositioned by §2.5(b) as before.
- `tools/int16_wet_shape_fixture_probe.py` carries the measurement and the
  re-derived control set; re-running it regenerates only
  `reports/int16-wet-shape-fixture/artifacts/`.
- `tests/test_pilot_freeze_tail_shape_floor.py` keeps every assertion it had
  (including 0016's live controls) and adds: the eligibility arithmetic, the
  designated fixture's measured properties, the re-derived single-window control
  FAILing above the band, the designated fixture's insensitivity to floors
  across the band, and the record/index/policy consistency for this record. If
  the rationale stops holding, those tests fail instead of the record going
  stale.
- `reports/pilot-freeze-tail-shape-floor/EVIDENCE.md` gains an append-only §7
  continuation pointing here. The #160 evidence body, its artifacts, and
  `reports/tail-shape-leg/artifacts/` are **not** edited.
- No committed render was added, edited, or removed; `fixtures/manifest.json`
  is unchanged.
- Nothing here establishes model-vs-reference fidelity, RTL equality, preset
  support, preset quality, or musical usefulness. It is a comparator- and
  fixture-selection decision.

## What remains unproved

- The int16 quantization band is **not removed from the bus** — it is avoided on
  the designated fixture. Any wet comparison on `koala2`, `sub4`, or the three
  ineligible Behemoth sequences still grades inside it, and 0016 §2.5(b) still
  governs that case.
- No real model wet render exists, so `decay_curve_max_dev_db = 1.0` is still
  unexercised against one, on any fixture (#111 §6, 0016 §5). The designation
  makes a future result *readable* outside the quantization regime; it does not
  exercise the budget.
- The eligibility criterion's 10 % headroom fraction is a declared
  fixture-selection choice, derived from the shipped deviation budget but not
  itself measured against a model. It is deliberately conservative: the
  designated fixture measures 5.7 %.
- Defects below the declared floor remain invisible to this leg by construction
  (#111 F3). On an eligible fixture there are none *inside the graded region*,
  because every window is graded; outside the declared tail region the limit is
  unchanged.
- The band edges are derived for a ±1 LSB per-sample difference. A model whose
  wet path differs by more than ±1 LSB near the lowest graded window widens the
  regime proportionally; the eligibility arithmetic generalizes (the spend is
  `20·log10(1 + e/r)`), but no such case is measured here.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). The probe uses the
Python standard library and numpy, reads only committed fixtures
(`fixtures/audio/behemoth/`, `fixtures/audio/koala2/`, `fixtures/audio/sub4/`)
and this repository's own comparator, and reproduces no Surge or third-party
code, table, or asset. No license decision is required for the material cited
here.
