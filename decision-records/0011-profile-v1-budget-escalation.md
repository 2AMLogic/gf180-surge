# 0011 — Profile v1 cannot be frozen at the plan-section-3 budgets: escalation to the product owner (SXT-017)

- **Status:** ESCALATED — pending product-owner decision. No contract has
  been revised by this record; it exists so the gap is visible rather than
  absorbed. Supersedes nothing.
- **Date:** 2026-09-25
- **Issue:** [#12](https://github.com/2AMLogic/gf180-surge/issues/12) (SXT-017)
- **Inputs:** [#8](https://github.com/2AMLogic/gf180-surge/issues/8) (SXT-013),
  [#9](https://github.com/2AMLogic/gf180-surge/issues/9) (SXT-014),
  [#11](https://github.com/2AMLogic/gf180-surge/issues/11) (SXT-016);
  plan `docs/surge-xt-chip-plan-v0.1-2026-09-20.md` §2, §3, §5.
- **Evidence:** `reports/sxt-017/cost-closure.json`,
  `reports/sxt-017/negative-controls-budget.txt`,
  `contracts/profile-v1-DRAFT.md` §12, `reports/sxt-016/EVIDENCE.md`.

## Context

Issue #12 asks for a frozen product profile v1 chosen by comparing candidate
bundles on complete preferred-preset recovery per incremental hardware cost,
and it carries an explicit stop/escalate condition:

> If no bundle meets the goal within credible budgets, STOP and escalate to
> the product owner for an explicit contract revision — do not proceed on an
> unachievable profile.

The bundle (structural) stage of #12 already landed: `contracts/profile-v1-DRAFT.md`
§1–§11 and `reports/sxt-017/predictions/`. It deliberately left the cost leg
open, because at the time every cycle number was SXT-015's `placeholder-v0`
and a placeholder supports no fit claim. SXT-016 has since landed 76
validated probe records, so that leg can now be evaluated; this record
reports what it says.

Two of the three premises of #12 remain **unmet in substance even though the
issues are closed**, and this record does not paper over that:

- **#8 (SXT-013)** delivered the favorites/fidelity *apparatus*. The
  favorites set is not selected and the fidelity policy is not frozen; both
  are `BLOCKED-on-human-listening` in `reports/sxt-013/EVIDENCE.md`. The
  coverage basis used below is therefore a **proposal slate**, not the
  frozen favorites set, and every number keyed to it is provisional.
- **#9 (SXT-014)** delivered ablation renders and numeric deltas. The
  essential / optional-by-adaptation / unresolved labels are
  `BLOCKED-on-human` in `reports/sxt-014/EVIDENCE.md`.
- **#11 (SXT-016)** delivered cost probes and says so itself:
  *"Escalation note for SXT-017: do not freeze hard budgets from these
  numbers alone."*

## What the cost leg shows

`tools/profile_budget.py` evaluates plan §5's closure formula for every
candidate bundle across the full grid of candidate clocks {48, 96, 192,
480} MHz × named memory implementations {E1, E2, E3} × multiplier schedules
{M18, M32}, taking the worst case over each bundle's predicted-supported
set. Every row names its clock, its memory implementation, its multiplier
schedule, and its basis; the basis is **ESTIMATE under named assumptions**,
never a measurement — no gf180mcu synthesis, place-and-route, timing
signoff, or hardware run stands behind any number here.

Two totals are kept separate and never merged: a **probe-priced lower bound**
(unpriced components counted at zero) and a **placeholder-mixed total**. The
lower bound is what makes an overflow conclusive: pricing the missing
components can only increase the cost.

At the best corner of the grid (480 MHz, M32, E3; DSP budget 7,002
cycles/output frame after the declared 20% reserve, scheduler transfer and
contention):

| Bundle | recovery (corpus / balanced slate) | worst probe-priced lower bound | verdict at the best corner | parallel-lane floor |
|---|---|---:|---|---:|
| B1-core-narrow | 6 / 0 | 3,216 | NO_VERDICT (unpriced components) | 1 |
| B2-core-wet-plan3 (plan §3 shape) | 8 / 0 | 4,471 | overflow, placeholder-dependent | 1 |
| B3-ext-voice-fx | 1,272 / 53 | 137,607 | **OVERFLOW (conclusive)** | ≥20 |
| B4-broad (bundle-stage DRAFT pick) | 1,685 / 72 | 270,805 | **OVERFLOW (conclusive)** | ≥39 |
| R0-ceiling-reference (non-product) | 2,716 / 184 | 270,805 | **OVERFLOW (conclusive)** | ≥39 |

Four findings follow, in decreasing order of how much they bind:

1. **No candidate bundle carries a fit claim at any clock, memory
   implementation, or word length.** Not one row in the 120-row grid is
   `within_budget`. The selected bundle under the declared rule is
   `B1-core-narrow` — the only product candidate not ruled out — and it
   recovers **6 of 3,561 corpus entries and 0 of 256** on every proposal
   slate, against a goal threshold of 205/256.
2. **Every bundle that recovers a meaningful number of presets overflows
   conclusively.** B3/B4/R0 overflow on probe-priced components alone, in
   all 24 of their configurations. This does not depend on any placeholder.
3. **The blocker is not the budget.** Inflating the DSP budget by 1000×
   still yields no fit claim, because unpriced components (LFO, envelope,
   modulation-row and waveshaper cycles; Chorus/Phaser/Reverb 2/Airwindows;
   the oscillator families no probe covers) remain unpriced. Only pricing
   work (SXT-023/024/028-class leaves) can move that, not a budget decision.
4. **48 MHz is arithmetically impossible before any DSP is scheduled.** At
   48 MHz the gross budget is 1,000 cycles/frame; after the declared 20%
   reserve and the scheduler's measured transfer + contention allowance
   (8 + 990) the DSP budget is **negative**. That is a property of the
   named E1 contention allowance, not of any bundle.

The dominant single cost is the pinned worst-pitch-corner BLIT Classic
oscillator multiplied by unison instances (SXT-016 finding 1); the worst-case
patch for B4/R0 is `96 Osc Supersaw.fxp` at 768 oscillator instances.

## Decision

**No profile v1 is frozen.** Issue #12's stop/escalate condition has fired
and this record routes it to the product owner. Specifically:

1. The 80% preferred-preset goal is **not met by any candidate bundle** under
   any credible budget in the grid, so freezing would require either a
   contract revision or a fit claim nobody can make today.
2. **"Supported" is not redefined**, the goal is not lowered, adapted
   presets are not counted, and no bundle is declared to fit. The gap is
   recorded as a bounded finding.
3. The budget comparison is demonstrably sensitive to the budget it depends
   on (`negative-controls-budget.txt` NC-B1: the selection walks
   B1 → B2 → B3 → B4 as the budget is inflated ×1 → ×2 → ×21 → ×40), so the
   "no bundle fits" result is a finding about the numbers, not an artifact
   of an insensitive comparison.

## Options the owner must choose between (none is taken here)

Each is a *visible* contract revision with a quantified consequence. They are
not mutually exclusive.

| Option | What it revises | Quantified consequence |
|---|---|---|
| **R-A** raise the parallelism/clock contract | plan §3's "single scheduled resource" | B4 needs ≥39 parallel lanes at 480 MHz/M32/E3 (≥78 at M18/E1); B3 needs ≥20. gf180mcu feasibility at 480 MHz is unverified; area/power unknown. Not silicon-credible for v1 on present evidence. |
| **R-B** cut unison/polyphony | the declared polyphony contract | Reduced unison/polyphony is a *disclosed edit class*: affected presets become **adapted** and, by plan §2, stop counting toward the goal. This lowers measured coverage; it cannot be used to meet the goal. |
| **R-C** adopt cheaper oscillator kernels | the sound contract | SXT-016 prices naive Classic at 13–25 cyc/sample vs BLIT's 176–353 — a ~10× lever, but a different structure and therefore a different sound until a frozen fidelity contract says otherwise. Unavailable today (policy not frozen, #8). |
| **R-D** revise the product goal | plan §2's 80%-of-256 target, or the favorites denominator | Shrinks the product promise. Requires explicit owner sign-off and a superseding decision record; must never be done by redefining "supported". |
| **R-E** defer the freeze | nothing | Price the unpriced components (SXT-023/024/028), design and cost a lane schedule, and land #8's listening + #9's labels; re-run this comparison. The leaves gated on #12 (#58, #64, and the ~17 issues citing SXT-017 as their budget gate) stay gated meanwhile. |

**R-E is the only option that gives nothing up, and it is the one the
evidence supports today**: #12's own premise (frozen favorites + frozen
fidelity policy + labelled effect contribution) is not met, and #11's
evidence record explicitly asks SXT-017 not to freeze hard budgets from its
numbers alone. Choosing among R-A…R-D is a product-owner act; this record
does not make it.

## Interim DRAFT policies for the two leaves waiting on this decision

These are **DRAFT positions, not freezes**; they exist so #58 and #64 can
proceed without either guessing or stalling, and they are superseded by
whatever the owner ratifies.

- **#58 (SXT-028f, Reverb 2 tank).** Reverb 2 tank state may be an
  external-writable-memory resident, costed against the named E1/E2/E3
  curves in `reports/sxt-016/`, with **per-instance state preserved** (two
  Reverb 2 slots are two tanks, even when arithmetic is shared). The leaf
  must publish its own traffic figure against those curves rather than
  assume a bandwidth budget, and **may not make a fit claim**: Reverb 2 is
  an unpriced class in this comparison (`cyc_fxreverb2_frame` is still
  `placeholder-v0`), so any Reverb 2 budget statement is NO_VERDICT until an
  SXT-024-class probe prices it.
- **#64 (SXT-028l, send buses 3-4).** The documented SXT-011 data gap (no
  factory `.fxp` stores `send_level` for buses 3/4; the surgepy binding does
  not expose them) is resolved the same way the MSEG/Formula gap already is:
  **`unresolved`, never defaulted**. A preset whose status would depend on a
  bus 3/4 send level is `unresolved` and stays in the denominator; SXT-028l
  fixtures must not be frozen on an assumed engine default, and closing the
  gap is SXT-011 instrumentation work, not a guess.

## Consequences

- Profile v1 stays unfrozen; `contracts/profile-v1-DRAFT.md` remains headed
  **NOT FROZEN** and gains §12 (this cost leg).
- Issue #12 stays open and is routed to the product owner rather than closed
  by an implementation PR.
- `tools/profile_budget.py`, `reports/sxt-017/cost-closure.json` and
  `reports/sxt-017/negative-controls-budget.txt` are re-runnable, so
  whichever option is chosen can be re-evaluated against the same grid.
- Nothing here establishes fidelity, preset support, preset quality, musical
  usefulness, area, timing, power, or any gf180mcu result.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`); Python stdlib only.
The tooling imports this repository's own SXT-015 accounting model, SXT-016
probe package, and SXT-017 predictor, and reads the committed SXT-011
graphs. Engine facts are read and cited from the pinned GPL-3.0-or-later
tree via SXT-015/SXT-016; no Surge source, tables, algorithm lists, or
preset payloads are copied into this repository. Decision-record format
follows the convention in `decision-records/README.md` (method only).
