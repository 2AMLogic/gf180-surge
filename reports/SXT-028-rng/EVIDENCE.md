# #122 evidence record — FX modulation RNG waveforms (Noise / Sample & Hold): the stream is NOT pinnable; the exclusion is recorded as a visible contract revision

Branch: `feature/issue-122` · Issue: #122 · Raised by: SXT-028g (#59) ·
Parent: SXT-028 (#21) · Routes to: SXT-017 (#12) · Date: 2026-09-26

Decision record: `decision-records/0013-fx-modulation-rng-stream.md`.

Engine pin (external, GPL-3.0-or-later; nothing copied into this
repository): `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
`sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b`,
`sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96`
(`oracle/manifest.json`). Twenty cited files, each pinned by sha256 in
`artifacts/rng-characterization.json` and verified against read-only
checkouts at those commits.

## Claim discipline (AGENTS.md — three claims, never inferred from each other)

| # | Claim | Status here | Evidence |
|---|---|---|---|
| 1 | The RTL matches the frozen fixed-point model **exactly** | **not addressed** — this leaf builds no RTL and no model | — |
| 2 | The model reproduces the pinned Surge reference within declared budgets | **BLOCKED for the RNG-driven shapes** — and this record establishes *why it can never be attempted* for them under the current pin | §1, `artifacts/rng-characterization.json` |
| 3 | The instrument sounds good | **NO_VERDICT** | nothing here bears on it |

This record establishes **no** preset-support claim, **no** fidelity claim,
**no** musical-quality claim, and **no** FPGA/gf180mcu synthesis,
place-and-route, signoff, timing, area or hardware-playback claim. It
freezes no budget. It **reduces** a measured coverage figure and publishes
the reduction; it does not lower a product goal — that consequence is routed
to SXT-017 (#12) with named options and no option taken.

## Headline results

| Item | Status | Evidence |
|---|---|---|
| Where the FX-modulation RNG is seeded, and its ownership scope | **PASS** (measured; 20/20 citations verified, 0 reseed call sites) | §1a, `artifacts/rng-characterization.json` leg A |
| Reproducible across two loads of the same patch? | **FAIL — NOT REPRODUCIBLE** (measured, with both detector controls CONTROL-OK) | §1b, leg B |
| Portable across C++ standard libraries? | **NOT_RUN** (cited normatively; never reported as a pass) | §1c, leg C |
| Decision | **outcome (b)**: exclusion recorded as a contract revision | `decision-records/0013-…` |
| Coverage cost, measured from `corpus/normalized/graphs.jsonl` | **published as a reduction**: 100 of 3,561; 15–24 of 256 per proposal slate | §3, `artifacts/coverage-impact.json` |
| Negative controls | **5/5 fired** (NC-R1…NC-R4 + NC-RNG-EXCLUSION) | §4 |
| SXT-028g's fail-closed refusal | **unchanged and still live** — the frozen model file was not edited | §2 |

## 1. Characterisation (acceptance item 1)

Produced by `tools/fx_rng_characterize.py` →
`artifacts/rng-characterization.json`. Three legs, reported separately.

### 1a. Where it is seeded, and what owns it — **PASS**

Three distinct generators are reachable from an FX slot at the pin. They are
**not** one stream, and the issue's premise (that `FXModControl` reaches
`SurgeSSTFXAdapter.h`'s `rand01`) turned out to be two different paths:

| Generator | Type | Seeded at | Scope |
|---|---|---|---|
| `FXModControl::rng` | `sst::basic_blocks::dsp::RNG` (`std::minstd_rand`) | `RNG::RNG()` — `system_clock::now().time_since_epoch().count()` | **per FXModControl instance** |
| `SurgeStorage::rngGen` | `std::minstd_rand` | `RNGGen::RNGGen()` — same clock expression | **one per SurgeStorage**, shared by every `storage->rand_*` consumer on the audio thread |
| chowdsp generators | `std::minstd_rand(std::random_device{}())` | each processor's constructor | per processor object |

`FXModControl` owns its RNG as a public member and **never** consults the
adapter's `rand01`. The path the issue named —
`SurgeSSTFXAdapter.h rand01 → SurgeStorage::rand_01`, surfaced to effects as
`EffectCore::storageRand01()` — is used by the **Flanger**, not by
`FXModControl`.

**No reseed is reachable from a patch load.** A scan of the pinned engine's
`src/**` (`.h`/`.cpp`/`.hpp`, comment-stripped) found **zero**
`reseed(...)` / `reseedWithClock()` / `seed_rand(...)` call sites;
`SurgeStorage`'s only reseed entry point is commented out at the pin. The
seed is therefore a function of wall-clock time, not of the patch and not of
`oracle/manifest.json`.

### 1b. Reproducible across two loads? — **FAIL (not reproducible)**

Measured by an original C++ probe (`REPRO_PROBE` in the tool; it exercises
C++ standard-library constructs and reproduces no Surge or sst code),
compiled and run on the evidence host:

| Leg | Observed | Meaning |
|---|---|---|
| two clock-seeded constructions **5 ms apart** identical? | **no** | far closer together than two patch loads; the seed differs already |
| two clock-seeded constructions **back to back** identical? | **no** | the measured `system_clock` tick is 57 ns |
| **detector control** — two *fixed-seed* constructions identical? | **yes** → CONTROL-OK | the comparator can report IDENTICAL, so the two FAILs above are measurements |
| shared generator, same seed, consumer draws after **3 prior draws** — identical? | **no** | pinning a seed would not pin the stream; engine-wide draw order would have to be pinned too |
| **detector control** — same seed, **zero** prior draws identical? | **yes** → CONTROL-OK | as above, for the draw-order comparator |

A "not reproducible" verdict from an always-firing comparator would be
worthless; NC-R4 (§4) asserts the detector legs stayed CONTROL-OK, and the
tool downgrades the whole leg to `NO_VERDICT` if they ever do not.

### 1c. Portable across standard libraries? — **NOT_RUN**

`std::uniform_real_distribution` has no standard-specified algorithm and no
specified engine-draw consumption, so two conforming standard libraries may
map the same `minstd_rand` stream to different floats. `std::minstd_rand`
itself *is* exactly specified: the **engine** is portable, the **mapping** is
not. This host carries only one standard library (provisioning another is
out of scope and the host is shared), and `oracle/manifest.json` pins Apple
clang / libc++, which was not available. **The leg is NOT_RUN.** It is not a
pass and it is not a failure; the single libstdc++ data point recorded in
the artifact establishes nothing about the pinned runtime. The decision does
not rest on it: obstruction O1 (§1b) is sufficient on its own and is
measured.

## 2. Decision (acceptance item 2) — outcome (b)

`decision-records/0013-fx-modulation-rng-stream.md`, **RECORDED CONTRACT
REVISION**, owner ratification pending, routed to SXT-017 (#12) with four
named options (R-A accept the exclusion · R-B adapt affected presets, which
buys playability not coverage · R-C patch the pinned engine, which changes
the reference · R-D re-pin upstream, unavailable). **No option is taken by
this leaf.**

Four obstructions are recorded, with their evidence grade kept distinct:
**O1** wall-clock seed with no reachable reseed (**measured**); **O2**
shared-generator draw-order coupling (**measured**); **O3** non-portable
distribution mapping (**cited, not measured**); **O4** pinning any of them
requires patching the pinned engine, which `oracle/manifest.json` says *is*
part of the reference (**a policy fact of the manifest**).

**SXT-028g (#59) is not re-opened.** Its refusal was correct as landed and is
correct either way. Its frozen model file `phaser_model.py` was **not
edited** — its sha256 is the model revision pinned in
`reports/SXT-028g/rtl-exactness.json`, and
`tests/test_sxt028_rng.py::test_the_frozen_phaser_model_was_not_edited_by_this_issue`
asserts that pin still matches. What changed is that the refusal's *contract
reason* is now recorded (`tools/extract_phaser_inputs.py` docstring, the
manifest, DR-0013), not the refusal itself: `DETERMINISTIC_WAVES` is
byte-identical at both enforcement points.

## 3. Coverage reduction (acceptance item 2b/4) — published, not deducted

`tools/fx_rng_coverage_impact.py` reads the committed SXT-011 graphs and the
SXT-013 slates; its selectors are read **from the characterisation artifact**,
so the count and the survey cannot drift apart.

**Counting rule.** An effect instance counts only when its slot is ON **and
not in the patch's `fx_disable` mask** — the same notion of a *required*
effect instance `tools/publish_coverage.py` uses, because a disabled slot
does not process. The wider number is reported alongside so the narrower one
is visibly a choice: **100** required-instance presets vs **115** including
disabled slots.

| Scope | Corpus (of 3,561) |
|---|---|
| #122's named scope — `FXModControl` Noise/S&H (Phaser, Neuron) | **2** |
| the FX-modulation RNG family (adds the Flanger shared-generator path) | **13** |
| every surveyed unpinnable-RNG FX class | **100** (2.81%) |

Per class (required instances / affected presets): Tape 45/45, Spring Reverb
26/26, Combulator 22/20, Flanger 11/11, Phaser 2/2, Neuron 0/0, Vocoder 0/0.

Against the SXT-013 **proposal** slates — prospective only; no frozen
favorites set exists (#8 `BLOCKED-on-human`): **20/256** balanced,
**24/256** contributor-lean, **15/256** factory-lean. The #122 named scope
costs **0/256** on all three.

**Upper bounds are labelled as such.** Tape and Spring Reverb construct
RNG-seeded processors unconditionally, but whether the RNG contribution
reaches the output can depend on their depth/amount/variance parameters.
That analysis was **NOT_RUN**, so every slot of those classes is counted —
fail-closed, an upper bound, recorded per class in the artifact.

**It is published as a reduction.** `tools/publish_coverage.py` gained a
per-row `fx_rng_gate` fed by the pinned artifact: an affected preset carries
`fx_rng_gate = BLOCKED` and an `rng_stream_unpinnable:` reason and **can
never be reported supported**. The denominators do not move — corpus 3,561,
slates 256 — and no preset is removed or re-labelled "out of scope".
`reports/coverage-v1/coverage.json` gains `fx_rng_exclusion` and an
`open_decisions` entry.

**Honest statement of what changed today: nothing in the headline.** All 100
affected presets are already `unsupported`/`unresolved` for independent
structural reasons, and the published `supported` count is **0**. The gate is
forward-looking, which is exactly why its load-bearingness had to be measured
against a counterfactual rather than asserted (§4, NC-RNG-EXCLUSION).

## 4. Negative controls — all live, each demonstrably failing its target

`tools/fx_rng_negative_controls.py` (exits non-zero if any control fails to
fire) → `negative-controls/negative-controls.{json,txt}`;
`tools/coverage_negative_controls.py --only rng_exclusion` →
`negative-controls/coverage-gate-control.txt`.

| Control | Targets | Result |
|---|---|---|
| **NC-R1** convenient deterministic substitute (the control #122 names) | a model that swaps the RNG shape for a fixed-seed stand-in | renders; differs from the nearest in-scope shape by **2,332,970** LSB and from a *different arbitrary seed of itself* by **2,283,206** LSB (declared threshold 8,192) — the substituted stream is a **free choice**, not a property of the reference; labelled **ADAPTED**, `counts_toward_original_preset_coverage: false`, refused by the coverage gate while the frozen model is accepted — **CONTROL-OK** |
| **NC-R2** the refusal is live and not always-firing | one rule, two enforcement points | 5/6 refused at both; **every** deterministic wave 0–4 accepted at both — **CONTROL-OK** |
| **NC-R3** silent exclusion | dropping affected presets from the corpus instead of publishing a reduction | REFUSED fail-closed with no artifact written; the untampered corpus is accepted, so the guard is not always-firing — **CONTROL-OK** |
| **NC-R4** the characterisation's own detectors | a "not reproducible" verdict produced by an always-firing comparator | both fixed-seed comparators report IDENTICAL; the leg status is FAIL, never a pass — **CONTROL-OK** |
| **NC-RNG-EXCLUSION** the coverage gate is load-bearing | a gate that changes nothing either way | in a declared counterfactual verified world, 5 synthetic exclusions downgrade supported 1,681 → 1,676, each with `fx_rng_gate=BLOCKED` and an `rng_stream_unpinnable:` reason; `--control-ignore-rng-exclusion` restores **exactly** 1,681; the denominator stays 3,561 — **PASS** |

NC-R1 is anchored on the **frozen SXT-028g model** and its declared
threshold, never on the engine (there is no oracle here). Its
`reference_anchored_leg` is recorded **NOT_RUN**: re-scoring the substitute
against a wet reference is required before any agreement statement — and it
cannot be done, which is the finding.

## 5. Findings surfaced by the survey (acceptance item 4)

Recorded so a future leaf does not rediscover them. None of these is a
support claim.

* **The Flanger is not an `FXModControl` consumer.** `sst::effects::Flanger`
  draws its `flw_sng`/`flw_snh` targets from `storageRand01()` — the
  **shared** `SurgeStorage` generator. Its RNG waveform values are **3 and
  4** (`ct_fxlfowave`), not 5 and 6 (`ct_fxlfowave_extended`): a Flanger leaf
  that copies the Phaser's gate verbatim would gate the wrong values.
* **Neuron forwards an unremapped waveform value.** `NeuronEffect` passes
  `neuron_lfo_wave` (a `ct_fxlfowave`, max 5) straight into the
  `FXModControl` enum, so a stored 5 selects `mod_noise` while the UI labels
  it "Square". The RNG reach is value **5 only**; value 6 is out of
  parameter range. Recorded as an observation about the pin, not a defect
  report, and not acted on.
* **`sst::effects::FloatyDelay` is RNG-driven unconditionally** (two
  `SimpleLFO` `SMOOTH_NOISE` modulators off an owned clock-seeded RNG). It
  contributes **0** affected presets because the corpus predates it.
* **The Vocoder is clean**: its only `storage->rand_pm1()` calls sit inside a
  commented-out block and are not compiled.
* **Tape / Spring Reverb use `std::random_device`** — strictly less pinnable
  than a clock seed.
* **NOT_RUN, never counted as clean**: **Airwindows** (the algorithms live
  outside the scanned surge tree; determinism there is the business of the
  per-algorithm SXT-028 leaves, e.g. the landed aw-49) and **Nimbus**
  (eurorack/clouds submodule, not scanned). This issue makes no statement
  about either.

## 6. What remains unproved

* No model-vs-reference agreement number exists for **any** FX modulation
  shape in this record, RNG-driven or not; that is claim 2 and it is not
  attempted here.
* The **O3** portability obstruction is cited, not measured (§1c).
* The Tape / Spring Reverb / Combulator counts are **upper bounds**; the
  parameter-conditional audibility analysis is NOT_RUN.
* Airwindows and Nimbus are **NOT_RUN** (§5).
* Whether the exclusion is acceptable **as a product decision** is not
  settled here: it is routed to SXT-017 (#12), and no option is taken.
* Nothing here says anything about how any of this **sounds**.

## 7. Pre-existing condition found while working (not caused by this issue)

At `d6f9ced` six evidence sha256 pins in
`reports/coverage-v1/leaf-verification.json` no longer matched their
committed `EVIDENCE.md` files (`reports/sxt-023`, `reports/sxt-024`,
`reports/SXT-028c`). The consequence was that
`tools/coverage_negative_controls.py`'s synthetic *verified* world produced
**0** supported presets, so **every** SXT-029 control failed for a reason
unrelated to what it tests, and the committed
`reports/coverage-v1/negative-controls.txt` no longer reproduced.

This leaf did **not** repin the table (that is SXT-029/leaf-owner work and
the STALE state is meaningful in a published run). It made the *synthetic
control world* drift-immune instead: `counterfactual_table()` now refreshes
evidence hashes from disk, which is what "a world in which everything is
verified" means, and leaves a **missing** evidence file alone so
NC-STALE-MISSING still fires. The suite is healthy again (5/5), including
the two stale-downgrade controls. The underlying pin drift is reported
separately and is not fixed here.

## 8. Reproduce

```sh
# characterisation (source verification needs read-only checkouts at the pins)
python3 tools/fx_rng_characterize.py \
    --sst-basic-blocks <sst-basic-blocks@a32b8aec> \
    --sst-effects      <sst-effects@adcac695> \
    --surge            <surge@58914e59>        # or ORACLE_SURGE_DIR
python3 tools/fx_rng_coverage_impact.py        # coverage reduction
python3 tools/fx_rng_negative_controls.py      # NC-R1 … NC-R4
python3 tools/coverage_negative_controls.py --only rng_exclusion \
    --transcript reports/SXT-028-rng/negative-controls/coverage-gate-control.txt
python3 tools/publish_coverage.py              # republish with the gate
python3 -m pytest tests/test_sxt028_rng.py -q
```

Without the checkouts the source-verification leg records **NOT_RUN** (never
a pass); the executable probe needs only a C++17 compiler.

## 9. Artifacts

| Path | Contents |
|---|---|
| `artifacts/rng-characterization.json` | generators, per-symbol citations + sha256, FX survey, the executable probe's raw output and per-check verdicts, the four obstructions |
| `artifacts/coverage-impact.json` | per-class and per-slate counts, every affected preset with its census blob SHA-1 and the reason it is affected, the counting rule |
| `negative-controls/negative-controls.{json,txt}` | NC-R1 … NC-R4 with metrics and per-control `reference_anchored_leg` status |
| `negative-controls/coverage-gate-control.txt` | NC-RNG-EXCLUSION transcript (the gate proven load-bearing) |
| `decision-records/0013-fx-modulation-rng-stream.md` | the decision, the options routed to #12 |

## 10. Provenance and licensing

Everything added by this leaf is original to this repository (Apache-2.0 per
`LICENSE`): Python standard library, plus one original C++ probe that
exercises C++ standard-library constructs and reproduces no Surge or sst
code. The pinned Surge / sst trees were **read and cited only** — 20 files,
each pinned by sha256 — so no code, table or asset was copied and no license
decision record is required for the material cited here. The cited
`sst-basic-blocks` and `sst-effects` headers are GPL-3.0-or-later; keeping
them external is precisely why only paths, symbols and hashes appear in this
repository.
