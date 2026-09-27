# Tail-shape-leg floor: int16 quantization regime and the pilot-freeze decision (evidence record)

Issue: #160 · Parent: #21 (SXT-028 expansion) · Source finding: #111 §4 **F1** ·
Routes to: SXT-017 (#12) · Date: 2026-09-27

Decision recorded in
[`decision-records/0016`](../../decision-records/0016-int16-tail-shape-leg-floor.md)
and in `contracts/fidelity-policy-DRAFT.md` §2.5. Measurement tool:
`tools/tail_shape_floor_probe.py`. Tests:
`tests/test_pilot_freeze_tail_shape_floor.py`.

**Claim discipline.** This is a **comparator-policy** record. It establishes
three things and nothing else: (1) on the mono int16 wet bus the declared
tail-shape floor sits 9.7 dB below one int16 LSB RMS, so the lowest graded
windows are quantization-dominated; (2) every candidate floor that clears that
regime disables a landed #111 negative control, measured, not argued; (3) with
the floor left at its declared value the #111 late-tail controls all still
FAIL. It makes **no** model-vs-reference fidelity claim, **no** RTL claim,
**no** preset-support or coverage claim, and **no** sound-quality claim (no
human listening). It **freezes no budget**: all three tail-shape values remain
`[PROPOSED-TO-BE-FROZEN-AT-PILOT]` and the freeze is SXT-017's (#12).

**No committed budget changed.** `tools/compare_audio_reference.py` still
ships `decay_curve_floor_dbfs = -100.0` and `decay_curve_max_dev_db = 1.0`.
The probe applies candidate floors by patching the *imported* `PROPOSED_TAIL`
dict inside its own process; the tool file is untouched. Consequently no landed
wet verdict, comparison artifact, or coverage number is invalidated by this
issue, and the "re-run every landed verdict" arm of #160's acceptance does not
apply (it is reported below as NOT_REQUIRED, never as a pass).

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| F1 reproduces: 1 int16 LSB RMS is −90.3 dBFS; the declared −100.0 dBFS floor is 9.7 dB **below** it; float (Q10.21) and s24 (Q9.23) buses are 26.4 dB and 38.5 dB clear | **PASS** (leg 1) | `artifacts/floor-probe.txt` §1 |
| F1 reproduces: the #93 `full-tail-within-budget` control spends **0.79 dB** of the 1.0 dB budget, and does so in the windows closest to 1 LSB (worst window −85.1 dBFS; all windows above −70.5 dBFS deviate ≤0.03 dB) | **PASS** (leg 2) | `artifacts/floor-probe.txt` §2 |
| At the declared floor all 8 landed int16 mono controls (3 × #93, 4 × #111, 1 self-baseline) behave exactly as landed | **PASS** (leg 3) | `artifacts/floor-probe.txt` §3 |
| Every candidate floor that clears the ±1 LSB regime (−80.0, −72.0 dBFS) flips the landed #111 control `mono/koala2/zero-late-tail-from-44%` from FAIL to PASS | **CONTROL-OK** — the conflict is live, not hypothetical | `artifacts/floor-probe.txt` §3, `tests/test_pilot_freeze_tail_shape_floor.py` |
| Failure control: the #111 late-tail controls still FAIL under the decided floor (13/13 as required, including `mono/koala2/zero-late-tail-from-44%`, `stereo/zero-late-tail-from-40%`, `stereo/zero-late-tail-from-60%`) | **CONTROL-OK** | `artifacts/issue-111-leg2-controls-rerun.txt` |
| Landed wet verdicts re-run | **NOT_REQUIRED** (no constant changed); the #111 record's own re-run remains the current one | `reports/tail-shape-leg/artifacts/landed-verdict-rerun.txt` (unmodified) |
| Any fidelity, support, or quality claim | **none made** | this section |

Run: `python3 tools/tail_shape_floor_probe.py` at repo HEAD `9a3aefdeaa70`
(worktree; the only uncommitted files were this issue's own), numpy 2.4.2,
Python 3.14.7, 2026-09-27. Overall **PASS**.

## 1. The regime (leg 1)

The floor is a declared **full-scale** constant, so one number means the same
dBFS on every bus — but the buses differ by 36–48 dB in resolution:

| Bus | 1 LSB RMS | Declared floor relative to it |
|---|---|---|
| mono int16, full scale 32767 (`compare_audio_reference.py --path wet`) | **−90.3 dBFS** | **−9.7 dB (floor is below one LSB)** |
| stereo Q10.21 (`compare_chorus_reference.py`, `compare_fx_reference.py`) | −126.4 dBFS | +26.4 dB |
| stereo Q9.23 (`compare_reverb_model.py` `tail_gate`) | −138.5 dBFS | +38.5 dB |

With a ±1 LSB model difference (e = 1 LSB RMS) and the declared 1.0 dB
deviation budget, the difference alone exceeds the budget for reference window
levels below:

* **−84.4 dBFS** (r = 1.97 LSB) when it adds in power (independent rounding),
* **−72.0 dBFS** (r = 8.20 LSB) in the coherent worst case.

So on the int16 bus the graded band **[−100.0, −72.0] dBFS** is
quantization-dominated, and the declared floor sits inside it.

## 2. Where the 0.79 dB comes from (leg 2)

The #93 `full-tail-within-budget` control is the committed Koala 2 wet
reference with the deterministic ±1 LSB dither over the first half of its
declared tail. 23 of 50 windows are graded. Deviation is monotone in proximity
to 1 LSB RMS:

| Window | Reference level | Deviation | dB above 1 LSB RMS |
|---|---|---|---|
| 17 | −85.1 dBFS | **0.79 dB** | 5.3 |
| 16 | −82.5 dBFS | 0.46 dB | 7.8 |
| 22 | −81.9 dBFS | 0.39 dB | 8.4 |
| 18 | −79.9 dBFS | 0.25 dB | 10.4 |
| 15 | −70.5 dBFS | 0.03 dB | 19.8 |
| 0 | −31.1 dBFS | 0.00 dB | 59.2 |

The control PASSes, as landed. The margin is quantization: **it is not
tail-shape headroom and must not be cited as such.** #111 §6 already records
that no committed render exercises the 1.0 dB value at its edge; this record
adds that the one control that approaches it does so for a reason unrelated to
tail shape.

## 3. The counterfactual floor sweep (leg 3)

Each of the 8 landed int16 mono controls was re-graded through the real
comparator entry point with only `decay_curve_floor_dbfs` patched.

| Candidate floor | Rationale | Landed controls as recorded | Koala 2 graded windows | #93 dither control worst dev |
|---|---|---|---|---|
| **−100.0 dBFS (declared)** | ships today | **8/8** | 23 | 0.79 dB |
| −95.0 dBFS | midway to 1 LSB RMS | 8/8 | 23 | 0.79 dB |
| −90.3 dBFS | 1 int16 LSB RMS | 8/8 | 23 | 0.79 dB |
| −84.4 dBFS | incoherent band edge | 8/8 | 22 | 0.46 dB |
| **−80.0 dBFS** | 10 dB above 1 LSB RMS | **7/8 — `mono/koala2/zero-late-tail-from-44%` flips FAIL → PASS** | 20 | 0.25 dB |
| **−72.0 dBFS** | coherent band edge | **7/8 — same flip** | 16 | 0.03 dB |

**Why it flips, and why no floor escapes the trade.** The 44% control's only
graded defect window is Koala 2's last graded window, **22 at −81.9 dBFS**; the
three global budgets and the whole-region residual leg all pass there
(residual −54.00 dB), so the shape leg is the sole failing leg. Raising the
floor above −81.9 dBFS ungrades that window and the control passes. But the
quantization-affected windows of the same fixture extend up to **−79.9 dBFS**.
The two ranges overlap: on the only committed int16 wet fixture whose tail
approaches the floor there is no floor that is simultaneously clear of the
±1 LSB regime and still sensitive to the landed control. A floor low enough to
keep the control is inside the regime; a floor high enough to leave the regime
loses the control.

## 4. Decision (recorded; see `decision-records/0016` for the full record)

Keep **one declared floor, −100.0 dBFS, for every bus**, keep
`decay_curve_max_dev_db = 1.0`, and **declare** the int16 quantization-dominated
band `[−100.0, −72.0] dBFS` in `contracts/fidelity-policy-DRAFT.md` §2.5,
together with a disposition rule: an int16 shape-leg FAIL whose over-budget
windows all lie inside the band still FAILs (fail-closed), and is recorded as a
bounded finding routed to SXT-017 (#12) — never resolved by raising the floor,
widening the deviation budget, or exempting the bus.

**The failure mode being traded off, stated plainly.** Keeping the floor
accepts a **false FAIL** risk: a real int16 model whose rounding differs by
±1 LSB can fail the shape leg in windows within ~18 dB of 1 LSB RMS for reasons
unrelated to tail shape. A per-bus (or raised) floor would instead buy an
18–28 dB **false PASS band** on the int16 bus — and, measured above, would
disable a live negative control. A false FAIL is visible, is investigated, and
never certifies a defective tail; a false PASS band is silent. The repository's
own rules point the same way: a leg that grades nothing is never a pass (#111),
and a budget is never widened to make a case pass (#160 stop/escalate).

Rejected alternatives, with their measured cost, are tabulated in
`decision-records/0016` (F-A … F-E). The only option that removes the regime
rather than declaring it is fixture- or bus-side (F-E) and is **not** taken
here.

## 5. Reproduce

```
python3 tools/tail_shape_floor_probe.py            # regenerates artifacts/floor-probe.{txt,json}
python3 -m pytest -q tests/test_pilot_freeze_tail_shape_floor.py
python3 tools/tail_shape_leg_checks.py --legs 2    # the #111 late-tail controls (failure control)
```

`tools/tail_shape_leg_checks.py --legs 2` prints `OVERALL: FAIL` because legs 0
and 1 are NOT_RUN in that invocation; the control rows are the result being
read, and a leg that did not run is not a pass. See the header of
`artifacts/issue-111-leg2-controls-rerun.txt`.

## 6. What remains unproved

* Nothing here says any model reproduces any reference, any RTL matches any
  model, or any preset is supported or sounds good.
* The three tail-shape values are still proposals. This record does not
  exercise `decay_curve_max_dev_db = 1.0` against a real int16 model wet
  render; no such render exists yet. When one does, a shape-leg result in the
  declared band must be dispositioned by §2.5(b), not by a budget change.
* The band edges are derived for a ±1 LSB per-sample difference. A model whose
  wet path differs by more than ±1 LSB near the floor will show a
  correspondingly wider quantization-dominated band; the arithmetic in leg 1
  generalizes (e scales), but no such case is measured here.
* Defects below the declared floor remain invisible to this leg by construction
  (#111 F3). That limit is unchanged by this decision.
* The fixture- or bus-side remedy (F-E) is unattempted: **NOT_RUN**.
