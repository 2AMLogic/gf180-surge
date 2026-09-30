# 0016 — The tail-shape leg keeps ONE declared floor (−100.0 dBFS) for every bus; the int16 quantization-dominated regime is documented, not floored away (#160 → SXT-017 #12)

- **Status:** RECORDED — pilot-freeze input. The decision is in force at the
  enforcement point named below (which is **unchanged** by this record: no
  comparator constant moved). **Owner ratification pending** at the SXT-017
  freeze ([#12](https://github.com/2AMLogic/gf180-surge/issues/12)); the
  budget itself remains **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**. Supersedes
  nothing. **AMENDED 2026-09-27 by
  [`0017`](0017-int16-wet-tail-shape-grading-fixture.md) (#187)**, which
  disposes of option **F-E** below — recorded here as NOT_RUN — by taking its
  **fixture-side** arm and rejecting its bus-side arm on measurement: the int16
  wet shape leg is graded on a *designated* committed fixture whose whole
  declared tail region is clear of the quantization band
  (`fixtures/audio/behemoth/seq-notes-holds-v1-wet.wav`; measured: no new
  render was required, 7 of the 30 committed int16 wet fixtures already
  qualify). Nothing in *this* record changes: every value, option table row,
  and consequence below still stands, the band and its disposition rule stay in
  force for ineligible fixtures, and the live control of §"Consequences"
  (a raised floor disables `mono/koala2/zero-late-tail-from-44%`) is retained
  and still fires.
- **Date:** 2026-09-27
- **Issue:** [#160](https://github.com/2AMLogic/gf180-surge/issues/160)
- **Raised by:** the tail-shape leg of the wet-path tail gate,
  [#111](https://github.com/2AMLogic/gf180-surge/issues/111) finding **F1**;
  parent SXT-028 ([#21](https://github.com/2AMLogic/gf180-surge/issues/21))
- **Routes to:** SXT-017 ([#12](https://github.com/2AMLogic/gf180-surge/issues/12))
- **Evidence:** `reports/pilot-freeze-tail-shape-floor/EVIDENCE.md`,
  `reports/pilot-freeze-tail-shape-floor/artifacts/floor-probe.txt`,
  `reports/pilot-freeze-tail-shape-floor/artifacts/floor-probe.json`,
  `reports/pilot-freeze-tail-shape-floor/artifacts/issue-111-leg2-controls-rerun.txt`;
  the source finding is `reports/tail-shape-leg/EVIDENCE.md` §4 F1 and
  `reports/tail-shape-leg/artifacts/landed-verdict-rerun.txt`
  (row `#93 full-tail-within-budget`).
- **Enforcement point (unchanged):** `tools/compare_audio_reference.py`
  → `PROPOSED_TAIL["decay_curve_floor_dbfs"] = -100.0`,
  `PROPOSED_TAIL["decay_curve_max_dev_db"] = 1.0`, applied by
  `tail_decay_curve` / `tail_check` / `stereo_tail_gate` and by every
  comparator that uses the shared gate.

## Context

Issue #111 added a windowed decay-curve (tail-shape) leg to the wet-path tail
gate: 50 ms windows over the declared tail region, graded wherever the
**reference** window level is at or above the declared floor
`decay_curve_floor_dbfs = −100.0` dBFS, each graded window required to be
within `decay_curve_max_dev_db = 1.0` dB of the reference.

The floor is expressed in **full-scale** units, so one constant means the same
dBFS on every bus. The buses differ enormously in resolution, which is what
#111 finding F1 noticed:

| Bus | 1 LSB RMS | Declared floor relative to it |
|---|---|---|
| mono int16 (`compare_audio_reference.py --path wet`, full scale 32767) | **−90.3 dBFS** | **−9.7 dB — the floor is BELOW one LSB** |
| stereo Q10.21 (`compare_chorus_reference.py`, `compare_fx_reference.py`) | −126.4 dBFS | +26.4 dB |
| stereo Q9.23 (`compare_reverb_model.py` `tail_gate`) | −138.5 dBFS | +38.5 dB |

On the int16 bus the graded band therefore reaches into levels of a few LSB,
where a ±1 LSB model difference *alone* moves a window's level by more than
the budget allows. With e = 1 LSB RMS and a 1.0 dB budget, that happens below:

- **−84.4 dBFS** (r = 1.97 LSB) if the difference adds in power (incoherent),
- **−72.0 dBFS** (r = 8.20 LSB) in the coherent worst case (amplitude
  addition).

The measured consequence (F1, reproduced here): the #93
`full-tail-within-budget` control — the committed Koala 2 wet reference with a
deterministic ±1 LSB dither over the first half of its declared tail — spends
**0.79 dB of the 1.0 dB budget** on quantization. It still PASSes, and no
landed verdict changed, but the margin is not tail-shape margin.

## What was measured (`tools/tail_shape_floor_probe.py`, three legs)

The probe applies candidate floors by patching the imported
`compare_audio_reference.PROPOSED_TAIL` **in its own process only**; it does
not modify the tool, and the shipped floor stayed −100.0 dBFS throughout.

| Leg | Result |
|---|---|
| **1** bus table / band arithmetic | **PASS** — the table and band edges above; the declared floor sits 9.7 dB below one int16 LSB RMS, i.e. inside the quantization-dominated band `[−100.0, −72.0]` dBFS. Float and s24 buses are ≥26 dB clear of theirs. |
| **2** window anatomy of the #93 dither control | **PASS** — worst graded deviation **0.79 dB** in window 17 at **−85.1 dBFS** (5.3 dB above one LSB). All four windows spending more than a quarter of the budget lie between −85.1 and **−79.9 dBFS**; every window at −70.5 dBFS or above deviates by ≤0.03 dB. The deviation is monotone in proximity to 1 LSB: it is quantization, not shape. |
| **3** counterfactual floor sweep over the 8 landed int16 mono controls (3 from #93, 4 from #111, 1 self-baseline) | **PASS** — at −100.0 (declared), −95.0, −90.3 and −84.4 dBFS all 8 behave exactly as landed. At **−80.0** and **−72.0** dBFS the landed #111 negative control `mono/koala2/zero-late-tail-from-44%` **flips FAIL → PASS**. |

**Why leg 3 flips.** Koala 2's declared tail has 23 windows above the floor;
the last of them, window 22 at **−81.9 dBFS**, is the *only* graded window the
44% truncation zeroes, so the shape leg is the sole failing leg (the three
global budgets and the whole-region residual leg all pass, residual −54.00 dB).
Raising the floor above −81.9 dBFS ungrades that window and the control passes.
But the quantization-affected windows on the same fixture reach up to
**−79.9 dBFS**. The two ranges **overlap**: on the only committed int16 wet
fixture whose tail approaches the floor, there is no floor that is both clear
of the ±1 LSB regime and still catches the landed negative control.

## Decision

1. **One declared floor, every bus.** `decay_curve_floor_dbfs` stays a single
   declared full-scale constant, **−100.0 dBFS**, and
   `decay_curve_max_dev_db` stays **1.0 dB**. No value in
   `tools/compare_audio_reference.py` is changed by this record, so no landed
   verdict, artifact, or evidence record is invalidated by it.
2. **A per-bus floor is REJECTED, on evidence rather than taste.** Tying the
   floor to the bus LSB would (a) make the grading threshold a function of the
   comparison's *representation* rather than a declared budget — the same
   inference-from-the-implementation the #93/#111 rules exist to forbid;
   (b) change nothing for the float/s24 buses, which are already ≥26 dB clear;
   and (c) on the int16 bus, at any value that actually clears the ±1 LSB band
   (≥ −80 dBFS), disable a landed #111 negative control. Leg 3 measures (c).
3. **The int16 quantization-dominated regime is DECLARED, not implied.** The
   band `[−100.0, −72.0]` dBFS on the int16 bus (worst-case coherent; the
   incoherent edge is −84.4 dBFS) is recorded in
   `contracts/fidelity-policy-DRAFT.md` §2.5 as part of the budget, so a
   reader of a verdict knows which windows are quantization-limited without
   re-deriving it.
4. **Disposition rule for an int16 shape-leg FAIL inside the band.** If every
   over-budget window of an int16 wet comparison lies inside that band, the
   comparison still **FAILs** — the leg fails closed and is not re-graded to
   PASS — and the failure is recorded as a **bounded finding routed to
   SXT-017 (#12)**, naming the windows and their levels. It MUST NOT be
   resolved by raising the floor, by widening `decay_curve_max_dev_db`, or by
   exempting the bus. The fixture- or bus-side answers (a wet int16 fixture
   whose declared tail stays clear of the band, or grading the int16 wet path
   on a higher-resolution bus) are tracked separately and are not taken here.
5. **The 0.79 dB is NOT tail-shape headroom.** No record may cite the #93
   `full-tail-within-budget` margin as evidence that the 1.0 dB deviation
   budget is comfortably met on the int16 bus. #111 §6 already states that no
   committed render exercises the 1.0 dB value at its edge; this record adds
   that the one control that comes close does so through quantization.
6. **Nothing is frozen and no goal is lowered.** All three shape-leg values
   remain `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`; the freeze is SXT-017's (#12).
   No preset promise, polyphony figure, or acceptance rule is weakened here,
   and coverage is unchanged (this record changes no verdict).

## Options the owner must choose between at the freeze (only F-A is in force)

| Option | What it revises | Consequence, as measured |
|---|---|---|
| **F-A** keep one declared floor at −100.0 dBFS and document the int16 band | nothing in the method; int16 verdicts near the floor may FAIL for quantization reasons | What this record implements. Coverage of graded windows is maximal (23/50 on Koala 2, 50/50 on Behemoth). Risk: a **false FAIL** on a real int16 model whose rounding differs by ±1 LSB in windows within ~18 dB of 1 LSB RMS. A false FAIL is visible and is investigated; it never silently certifies a defect. |
| **F-B** per-bus floor N dB above 1 LSB RMS | the floor stops being a single declared full-scale constant | At any N that clears the band (floor ≥ −80 dBFS on int16) the landed #111 control `mono/koala2/zero-late-tail-from-44%` flips FAIL → PASS (leg 3). Buys a **false PASS band** of 18–28 dB on the int16 bus and loses a live negative control. Rejected. |
| **F-C** raise the single floor for every bus | float/s24 grading too, which has no quantization problem | Same flip as F-B, plus it discards float/s24 coverage that nothing asks for (their LSBs are 26–38 dB below the floor). Rejected. |
| **F-D** widen `decay_curve_max_dev_db` on the int16 bus | the deviation budget | Explicitly forbidden by #160's stop/escalate condition ("do not raise the floor or the deviation budget just to widen a passing margin"). Not taken. |
| **F-E** retire the int16 wet comparison path in favour of a higher-resolution bus, or re-render a wet int16 fixture whose declared tail stays clear of the band | the fixture set / the comparison bus, not the budget | The only option that removes the regime instead of declaring it. It is real work with its own evidence (new fixtures are rendered, never edited) and is **not** taken in this record. |

## Consequences

- `contracts/fidelity-policy-DRAFT.md` §2.5 records the decision, the band,
  and the disposition rule, and cites this record.
- `tests/test_pilot_freeze_tail_shape_floor.py` pins the decision to the code:
  the shipped constants, the policy text, this record and its index row, the
  single-floor-for-every-bus property, the band arithmetic, and two live
  controls — that a −80.0 dBFS floor really does disable
  `mono/koala2/zero-late-tail-from-44%`, and that the #93 dither control's
  0.79 dB reproduces in windows close to one int16 LSB RMS. If the rationale
  ever stops holding, those tests fail instead of the record quietly going
  stale.
- `tools/tail_shape_floor_probe.py` retains the measurement; re-running it
  regenerates only `reports/pilot-freeze-tail-shape-floor/artifacts/`.
- The #111 late-tail negative controls were re-run at the declared floor and
  all still FAIL (13/13 controls as required, including
  `mono/koala2/zero-late-tail-from-44%`, `stereo/zero-late-tail-from-40%` and
  `stereo/zero-late-tail-from-60%`) — issue #160's failure control.
- No landed verdict, no committed comparison artifact, and no coverage number
  moves, because no constant changed. Re-running every landed wet verdict was
  therefore **not required** and is reported as such, not as a pass.
- Nothing here establishes model-vs-reference fidelity, RTL equality, preset
  support, preset quality, or musical usefulness. It is a comparator-policy
  decision.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). The probe uses the
Python standard library and numpy, reads only committed fixtures
(`fixtures/audio/koala2/`, `fixtures/audio/behemoth/`) and the repository's own
comparator, and reproduces no Surge or third-party code, table, or asset. No
license decision is required for the material cited here.
