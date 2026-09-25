# SXT-038 frozen LP 24 dB filter model (`model/voice/filter_lp24/`)

Frozen reference for the SXT-038 filter-leaf RTL (`rtl/voice/tb_lp24.sv`).
The RTL must match this model **exactly** (integer equality at every declared
checkpoint; `tools/compare_rtl_model_lp24.py`).  Model-vs-pinned-code
agreement is a **separate** claim governed by **[PROPOSED]** budgets
(PENDING-FREEZE; SXT-013/#12 owns the fidelity policy), measured in
`reports/SXT-038/`.  Neither claim says anything about musical quality.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  filter submodule `libs/sst/sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6`
  (`oracle/manifest.json`)
- Coefficient-maker configuration (pinned `SurgeVoice::sampleRateReset()`):
  `setSampleRateAndBlockSize(dsamplerate_os, BLOCK_SIZE_OS)` = **(96000, 64)**
- Type scope: `fut_lp24` (2) **only** — one algorithm per leaf
- Subtype scope: the full engine-declared set at the pin
  (`fut_subcount[fut_lp24] = 3`):
  `st_Standard`(0) → `SVFLP24Aquad`, `st_Driven`(1) → `IIR24CFCquad`,
  `st_Clean`(2) → `IIR24Bquad` (pinned `GetQFPtrFilterUnit` table)
- Observed corpus subtype inventory (`corpus/normalized/graphs.jsonl`,
  informational, not a support claim): 596× Standard, 319× Driven, 81× Clean
  across 842 presets carrying at least one LP 24 dB unit
- Carrier fixtures: the three presets named in issue #72
  (`Argitoth/Rhythms/Edges Rhythm.fxp` — Driven;
  `Damon Armani/Pads/House Of Chords.fxp` — Clean in scene A, Standard in
  scene B; `Damon Armani/Plucks/Main Brass.fxp` — Standard) plus two
  recovery-basis presets with LIVE keytrack/env-mod
  (`patches_factory/Sequences/Phase 1.fxp` — Driven at resonance 1.0;
  `patches_factory/Chords/Major 7 MkII.fxp` — Clean), because all three
  issue carriers store `kt = em = 0` and would never move the coefficient
  plane on their own.

## Declared parameter scope (fail-closed outside)

| Parameter | Declared scope | Outside scope |
|---|---|---|
| filter type | `fut_lp24` (2) | REFUSED (`Refuse`, exit-2 class) |
| subtype | {0, 1, 2} | REFUSED |
| resonance | [0, 1] normalized | REFUSED |
| cutoff input | [−240, +240] st (engine cutoff parameter span) | REFUSED |
| cutoff after `boundFreq` | clamped to [−55, +75] st **on the Coeff_LP24 path only** | frozen clamp, declared |
| cutoff on the `Coeff_SVF` path | not `boundFreq`-clamped at the pin; F1's own `min(0.11, ·)` argument clamp applies | frozen, declared |

Refusals raise (exit-2 class) — an out-of-scope fixture can never silently
produce audio (AGENTS.md fail-closed rule; live controls NC-C).

## Declared control-plane boundary

Block-rate coefficient generation is this leaf's DSP and stays IN the model:
`make_coeffs(cutoff_a, reso_a)` (pinned `Coeff_LP24` / `Coeff_SVF`,
`Map4PoleResonance`, `resoscale`, `clipscale`, `boundFreq`,
`ToCoupledForm` / `ToNormalizedLattice`) plus `FromDirect` smoothing.

The SurgeVoice control arithmetic that *produces* `(cutoff_a, reso_a)` —
`cutoff_a = cutoff + keytrack·(note − keytrack_root) + envmod·FEG`
(`SurgeVoice.cpp` `SetQFB`) — is **outside** this leaf, exactly as in the
landed SXT-037 leaf.  `model/voice/filter_lp24/case_plan.py` evaluates it to
build the block-rate control plane and feeds the **same** float32 words to
both legs; `run_filter_leg.py` re-derives that plan and REFUSES if the
reference bundle's control words differ (live control NC-E).

The FEG trajectory used by the fixtures is a **declared fixture trajectory**
(attack 20 ms, decay 100 ms, sustain 0.5, note-off at 70 % of the segment,
release 150 ms), *not* the carrier preset's own filter envelope: ADSR state
is absent from the SXT-011 normalized graph schema and is reachable only
through the pinned engine, which this environment does not have
(EVIDENCE §0, finding F-038-1).  It is a test configuration, never an
adapted preset, and it is identical for both legs.

The voice path reads the advanced kernel `C` back into the coefficient maker
after every block (`GetQFB`: `CM[u].C[i] = get1f(fbq->FU[u].C[i], fbqi)`);
the model mirrors this copy-back exactly.

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| samples, filter state, coefficients, clipgain | **Q10.21** (signed 32-bit) | the universal SXT-022 word |
| coefficient-construction intermediates | double, quantized once | pinned formulas evaluated in double; the engine evaluates a float32/double mix (declared deviation) |
| engine tuning tables (`table_pitch`, `table_note_omega`, `table_two_to_the`) | float32 entries, linear interpolation | constructed from the pinned `SurgeStorage::init_tables()` formulas; **not** exact `sin`/`cos` — see below |

Arithmetic rules (frozen):

* exact 64-bit products rounded round-half-up
  `r = (a·b + (1 << (s−1))) >> s`, saturated to signed 32-bit (`vm.qmul`);
* **every audio-path sum is saturated** (`sadd`), so overflow is defined and
  the RTL matches bit for bit (a declared divergence from the pinned float
  path, which has no 32-bit wrap; also a divergence from the landed SXT-037
  model, whose sums are unsaturated);
* `qdiv` (round-half-up) only at coefficient rate;
* no run-time floating point in the audio path.

### Why the model uses the engine's tuning TABLES, not exact trigonometry

`Coeff_LP24` obtains `(sinu, cosi)` from the tuning provider.  In the pinned
*engine* that provider is `SurgeStorage`, whose `table_note_omega` stores
float32 `sin`/`cos` on an integer-semitone grid and interpolates linearly;
at the top of the cutoff range that interpolation differs from exact
`sin`/`cos` by ~1.7·10⁻³ — thousands of Q10.21 LSB.  A model built on exact
trigonometry would therefore *not* be the engine.  This model reproduces the
table semantics (`note_to_omega_d`, `note_to_pitch_ignoring_tuning_d`), and
the reference harness offers the same provider (`surge-lut`) plus
sst-filters' own `BasicTuningProvider` (`exact`) so the provider's
contribution can be measured rather than assumed.

Two further pinned details this leaf follows and the landed SXT-037 model
does not (recorded as findings F-038-3/F-038-4, routed to #71's leaf, not
fixed here):

* the coefficient maker's sample rate is `dsamplerate_os` = 96 000 Hz, so
  `Coeff_SVF`'s `F1 = 2·sin(π·min(0.11, f·0.5/96000))`;
* `clipscale` uses sst-filters' own `db_to_linear` = exact `pow(10, 0.05·x)`,
  not Surge's dB lookup table.

## Frozen per-sample schedule (one OS sample)

Two cascaded sections per subtype, exactly as the pinned kernel bodies
(`QuadFilterUnit_Impl.h`).  Register indices and the clipgain slot are the
engine's:

1. **Driven (`IIR24CFCquad`)** — clipgain `R[2]`:
   `C[i] += dC[i]` for i ∈ {0,1,2,4,5,6};
   `y1 = C4·R0 + C6·x + C5·R1`; `s1 = x·C2 + C0·R0 − C1·R1`;
   `s2 = C1·R0 + C0·R1`; `R0 = s1·R2`; `R1 = s2·R2`;
   `y2 = C4·R3 + C6·y1 + C5·R4`; `s3 = y1·C2 + C0·R3 − C1·R4`;
   `s4 = C1·R3 + C0·R4`; `R3 = s3·R2`; `R4 = s4·R2`;
   `C7 += dC7`; `R2 = max(0.1, 1 − C7·y2²)`; output `y2`.
   **Both** sections scale their state with the PREVIOUS clipgain.
2. **Clean (`IIR24Bquad`)** — clipgain `R[4]`: all seven coefficient reloads
   first (pinned order K2, Q2, K1, Q1, V1, V2, V3), then the two
   normalized-lattice sections over `(R0,R1)` and `(R2,R3)`, each scaled by
   the previous `R4`; `C7 += dC7`; `R4 = max(0.1, 1 − C7·y2²)`; output `y2`.
3. **Standard (`SVFLP24Aquad`)** — clipgain `R[2]`: `C0 += dC0`; `C1 += dC1`;
   the pinned zero-delay-feedback SVF ladder twice (second section fed by the
   first section's `L`, state `(R3,R4)`); `R0/R1` and `R3/R4` scaled by the
   previous `R2`; `C2 += dC2`;
   `R2 = max(0.1, 1 − C2·B²)` using the **second** section's `B`;
   `C3 += dC3`; output `L·C3` from the **second** section.

Per-instance state (never shared): `R[0..4]` per voice/unit instance.

### Register initialization (declared, engine-cited)

The per-voice `FBP` is zero-initialized at voice creation and re-zeroed on a
type/subtype change (`memset(&FBP.FU[u], 0, …)`, `CM[u].Reset()`), clipgain
register included: **the clipgain starts at 0**, so the first OS sample of an
instance seeds no state, and the clipgain is ≥ 0.1 from the second sample on.

## Stability argument (frozen model)

For Driven/Clean the coupled-form / lattice pole radius satisfies
`ρ² = a2 = 1 − alpha`, with the pinned self-oscillation guard
`alpha ≤ sqrt(1 − cosi²) − 10⁻⁴` keeping `ρ < 1` except at the resonance
corner, where `Map4PoleResonance` drives `alpha → 0` and the loop is held by
the clipgain contraction `R_clip ∈ [0.1, 1]`.  For Standard the pinned
`Q1 ≤ min(2, 2 − 1.52·F1)` clamp bounds the SVF loop, and at resonance 1 the
same clipgain contraction applies.  The model additionally runs an empirical
per-block peak monitor (`stability_verdict`): sustained exponential growth
into headroom, or reaching the saturation neighbourhood, is reported
**UNSTABLE** — a recorded alarm, never a silent clamp.

## Costs (for the SXT-016 reconciliation)

Measured qmul (32×32 MAC) counts of the frozen schedule, per instance per OS
sample: **Standard 19**, **Driven 22**, **Clean 28**, plus ≤ 8 coefficient
adds per sample and one block-rate `make_coeffs` per 64 OS samples.  State:
5 × 32-bit registers + 16 × 32-bit coefficient/delta words per instance
(672 bits).  The divergence against the SXT-016 planning rows is recorded in
`reports/SXT-038/EVIDENCE.md` §5, not reconciled away.

## Files

* `filter_lp24_model.py` — the frozen model (importable)
* `case_plan.py` — the shared control plane + stimulus both legs consume
* `extract_inputs.py` — fail-closed case extraction from the committed corpus
* `run_filter_leg.py` — reference bundle → model legs L1/L2a/L2b/L3 + RTL stimulus

## Reproduce

```sh
python3 tools/run_sxt038_checks.py          # all steps (needs g++, git, iverilog)
python3 -m pytest tests/test_sxt038_lp24.py
```
