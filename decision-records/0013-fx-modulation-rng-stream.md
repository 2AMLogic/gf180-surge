# 0013 — FX modulation RNG streams cannot be pinned: the RNG-driven effect shapes are excluded, as a visible contract revision (#122 → SXT-017 #12)

- **Status:** RECORDED CONTRACT REVISION — the exclusion is in force at the
  enforcement points named below and its coverage cost is published.
  **Owner ratification pending** for the product-goal consequence, which is
  routed to SXT-017 ([#12](https://github.com/2AMLogic/gf180-surge/issues/12)).
  Supersedes nothing.
- **Date:** 2026-09-26
- **Issue:** [#122](https://github.com/2AMLogic/gf180-surge/issues/122)
- **Raised by:** SXT-028g ([#59](https://github.com/2AMLogic/gf180-surge/issues/59)),
  parent SXT-028 ([#21](https://github.com/2AMLogic/gf180-surge/issues/21))
- **Routes to:** SXT-017 ([#12](https://github.com/2AMLogic/gf180-surge/issues/12))
- **Evidence:** `reports/SXT-028-rng/EVIDENCE.md`,
  `reports/SXT-028-rng/artifacts/rng-characterization.json`,
  `reports/SXT-028-rng/artifacts/coverage-impact.json`,
  `reports/SXT-028-rng/negative-controls/`,
  `reports/coverage-v1/coverage.json` → `fx_rng_exclusion`.

## Context

SXT-028g froze a fixed-point model of the Surge XT Phaser and refused
`mod_wave` 5 (Noise) and 6 (Sample & Hold) **fail-closed**, because
`sst::basic_blocks::modulators::FXModControl` drives those shapes from
`sst::basic_blocks::dsp::RNG` and no RNG stream is pinned by
`oracle/manifest.json`. Issue #122 asked for one of two outcomes: pin the
stream and extend the frozen scope, **or** record the exclusion as a visible
contract revision with a quantified coverage cost.

This record takes the second outcome, because the first was **measured to be
unavailable**, not assumed to be.

## What was measured

`tools/fx_rng_characterize.py`, three legs, each reported separately
(`reports/SXT-028-rng/artifacts/rng-characterization.json`):

| Leg | Status | Result |
|---|---|---|
| A. source inventory + citation verification | **PASS** | 20/20 cited files verified by sha256 against read-only checkouts at the pinned commits; **0** reseed call sites in the engine tree |
| B. seed reproducibility (executable probe) | **FAIL** — *not reproducible* | see below |
| C. distribution portability across standard libraries | **NOT_RUN** | only one standard library on the host; the manifest pins Apple clang/libc++ |

Leg B compiles an original C++ probe (no Surge or sst code) that exercises
the standard-library constructs the pinned engine seeds with:

- two clock-seeded constructions **5 ms apart** — far closer together than
  two patch loads ever are — produce **different** streams;
- two constructions back to back produce **different** streams (the
  `system_clock` tick measured on the evidence host is 57 ns);
- a shared generator with the **same seed** hands a **different** stream to a
  consumer that draws after another consumer's 3 draws;
- **detector controls, both CONTROL-OK**: two *fixed-seed* constructions are
  identical, and the shared generator with zero prior draws is identical. The
  comparator can report IDENTICAL, so the FAIL legs above are measurements,
  not an always-firing detector.

## Why the stream cannot be pinned — four obstructions

**O1 — the seed is the wall clock, and nothing can change it.**
`sst::basic_blocks::dsp::RNG::RNG()` seeds `std::minstd_rand` with
`std::chrono::system_clock::now().time_since_epoch().count()`, and
`FXModControl` holds such an RNG as a **per-instance member**, default
constructed. `SurgeStorage::RNGGen` does the same for the shared generator.
Neither is ever reseeded: the surge tree at the pin contains **no**
`reseed(...)`, `reseedWithClock()` or `seed_rand(...)` call site, and
`SurgeStorage`'s only reseed entry point is commented out. The seed is
therefore a function of wall-clock time, not of the patch and not of the
manifest. O1 alone is sufficient, and it is measured.

**O2 — the shared generator couples consumers through draw order.**
The Flanger's Noise/Sample & Hold shapes do **not** use `FXModControl`; they
call `storageRand01()` → `SurgeStorage::rand_01()`, one generator shared by
every `storage->rand_*` consumer on the audio thread (Combulator too). Even
with a pinned seed, a consumer's stream position depends on the rest of the
engine's draw history. Pinning the seed would not be enough; the engine-wide
draw order would have to be pinned too. Measured.

**O3 — the distribution mapping is not portable.**
`std::uniform_real_distribution` has no standard-specified algorithm and no
specified engine-draw consumption. Even a pinned seed and a pinned draw order
do not pin the produced floats across standard libraries. `std::minstd_rand`
itself *is* exactly specified, so the engine is portable and the mapping is
not. Cited normatively; **not measured** (leg C is NOT_RUN and is not read as
either a pass or a failure).

**O4 — pinning it would change the reference.**
`oracle/manifest.json` states that no seed override is applied and that *the
pinned engine's own RNG initialization is part of the reference*. Every
available way to pin O1/O2 requires **patching** the pinned engine or its
pinned submodules. A patched engine is a different reference and cannot
settle a fidelity claim about this one.

## Decision

1. **The RNG-driven FX modulation shapes are EXCLUDED from the frozen model
   scope**, and the exclusion is a recorded contract revision rather than a
   per-leaf omission. The enforcement points are unchanged and stay
   fail-closed: `model/effects/type-phaser/phaser_model.py` (frozen — its
   sha256 is the model revision pinned in
   `reports/SXT-028g/rtl-exactness.json`, so it is **not edited** by this
   record) and `tools/extract_phaser_inputs.py`.
2. **No deterministic substitute may be used under a support claim.** A model
   that replaces the RNG shape with a convenient deterministic one is
   **ADAPTED** and is refused from original-preset coverage. This is enforced
   live, not merely stated (NC-R1 below).
3. **The coverage cost is published as a reduction, never a deduction.** The
   corpus denominator stays 3,561 and every slate denominator stays 256;
   affected presets are reported not-supported with a named reason
   (`rng_stream_unpinnable:` in `reports/coverage-v1/per-preset.csv`,
   `fx_rng_gate = BLOCKED`). No preset is removed from any denominator and no
   preset is re-labelled "out of scope".
4. **Nothing in SXT-028g is re-opened.** Its refusal was correct as landed
   and is correct either way; this record supplies its contract reason.
5. **No product goal is lowered here.** "Supported" is not redefined, the
   favorites-set target is not reduced, and adapted presets are not counted.
   The *consequence* for the product goal is a product-owner decision and is
   routed to #12 with the options below.

## Quantified coverage cost

Measured by `tools/fx_rng_coverage_impact.py` from the committed SXT-011
normalized graphs. An effect instance counts only when its slot is ON and not
in the patch's `fx_disable` mask — the same notion of a *required* effect
instance `tools/publish_coverage.py` applies; the broader
"including disabled slots" number is reported alongside so the narrower one
is visibly a choice (115 vs 100).

| Scope | Corpus (of 3,561) |
|---|---|
| #122's named scope — `FXModControl` Noise/S&H (Phaser, Neuron) | **2** |
| the FX-modulation RNG family (adds the Flanger shared-generator path) | **13** |
| every surveyed unpinnable-RNG FX class | **100** (2.81%) |

Per class, as *affected presets* (required slots in brackets): Tape 45 [45],
Spring Reverb 26 [26], Combulator 20 [22], Flanger 11 [11], Phaser 2 [2],
Neuron 0 [0], Vocoder 0 [0].

Against the SXT-013 **proposal** slates (prospective only; no frozen
favorites set exists — #8 is `BLOCKED-on-human`): **20/256** balanced,
**24/256** contributor-lean, **15/256** factory-lean. The #122 named scope
costs **0/256** on all three.

**Today this changes no headline.** All 100 affected presets are already
`unsupported`/`unresolved` for independent structural reasons, and the
published `supported` count is 0. The gate is forward-looking: it is proven
load-bearing against a declared counterfactual verified world (NC-RNG-EXCLUSION
below), where removing it restores exactly the presets it blocked.

## Live negative controls

`tools/fx_rng_negative_controls.py` (exits non-zero if any control fails to
fire) and `tools/coverage_negative_controls.py`:

| Control | Targets | Result |
|---|---|---|
| **NC-R1** convenient deterministic substitute | a model that swaps the RNG shape for a fixed-seed stand-in | it renders; differs from the nearest in-scope shape by 2,332,970 LSB and from a *different seed of itself* by 2,283,206 LSB (threshold 8,192) — so the substituted stream is an arbitrary free choice; it is labelled ADAPTED and the coverage gate refuses it, while accepting the frozen model — **CONTROL-OK** |
| **NC-R2** the refusal is live and not always-firing | one rule, two enforcement points | 5/6 refused at both, 0–4 accepted at both — **CONTROL-OK** |
| **NC-R3** silent exclusion | dropping affected presets from the corpus instead of publishing a reduction | REFUSED fail-closed, no artifact written; the untampered corpus is accepted — **CONTROL-OK** |
| **NC-R4** the characterisation's own detectors | a "not reproducible" verdict from an always-firing comparator | both fixed-seed comparators report IDENTICAL — **CONTROL-OK** |
| **NC-RNG-EXCLUSION** the coverage gate | a gate that changes nothing | in a declared counterfactual verified world, 5 synthetic exclusions downgrade 1,681 → 1,676 supported with `fx_rng_gate=BLOCKED`; `--control-ignore-rng-exclusion` restores exactly 1,681; denominator stays 3,561 — **PASS** |

## Options the owner must choose between (none is taken here)

| Option | What it revises | Quantified consequence |
|---|---|---|
| **R-A** accept the exclusion | nothing in the *method*; the product's preset promise absorbs it | −100 of 3,561 corpus presets, −15…−24 of 256 on the proposal slates. The #122 named scope costs 0/256. Cheapest option; it is what this record implements pending ratification. |
| **R-B** adapt the affected presets | plan §2's "adapted presets do not count" | The affected presets become renderable with a disclosed edit (a deterministic substitute shape) and are labelled **adapted**. By plan §2 they still do not count toward original-preset coverage, so this buys playability, not coverage. NC-R1 shows the substitute is an arbitrary choice. |
| **R-C** patch the pinned engine to expose a seed | the reference itself, and `oracle/manifest.json` | Technically small (an `RNG::reseed` call and a `SurgeStorage` seed API) but it changes the oracle. Every fidelity claim would then be against a *patched* engine, and the current pin's claims would not transfer. O2/O3 remain even then. |
| **R-D** re-pin the reference to a hypothetical upstream that seeds deterministically | the engine pin | Not available: no such upstream exists at the time of writing, and following upstream silently is forbidden. |

**R-A is what the evidence supports today.** R-B is available per-preset and
is never coverage. R-C is a reference change and must not be taken to make a
leaf pass.

## Consequences

- `oracle/manifest.json` gains `runtime.fx_modulation_randomness` recording
  the characterization. **No pin changes and no seed override is applied.**
- `tools/publish_coverage.py` gains a per-row `fx_rng_gate`; an affected
  preset can never be reported `supported` while this record stands. The
  published totals do not move (0 supported, for independent reasons).
- SXT-028g (#59) is unchanged; #122 is closed by this record.
- Newly surfaced, recorded so a future leaf does not rediscover them: the
  Flanger's RNG path is the **shared** `SurgeStorage` generator, not
  `FXModControl`; Surge's Neuron forwards a `ct_fxlfowave` value unremapped
  into the `FXModControl` enum, so its stored value 5 selects `mod_noise`
  while the UI labels it "Square"; `sst::effects::FloatyDelay` is RNG-driven
  **unconditionally** (0 corpus presets today — the corpus predates it);
  Vocoder's only RNG calls are inside a commented-out block.
- **Not surveyed, and never counted as clean:** Airwindows (external
  algorithm library — the per-algorithm SXT-028 leaves own it) and Nimbus
  (eurorack/clouds submodule). Both are NOT_RUN here.
- Nothing here establishes fidelity, preset support, preset quality, musical
  usefulness, area, timing, power, or any FPGA/gf180mcu result.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`); Python standard
library plus one original C++ probe that exercises C++ standard-library
constructs and reproduces no Surge or sst code. The pinned
`surge-synthesizer/surge@58914e59`, `sst-effects@adcac695` and
`sst-basic-blocks@a32b8aec` trees were **read and cited only** — 20 files,
each pinned by sha256 in the characterization artifact. No third-party
source, table or asset is copied into this repository, so no license
decision record is required for the material cited here. The cited
`sst-basic-blocks` and `sst-effects` headers are GPL-3.0-or-later; keeping
them external is exactly why only paths, symbols and hashes appear here.
