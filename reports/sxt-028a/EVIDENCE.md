# SXT-028a evidence record — Airwindows "Galactic" (id 49): frozen fixed model, exact RTL, tapped slot-boundary reference

Branch: `loom/leaf-53-galactic` · Issue: #53 (SXT-028a) · Parent: #21
(SXT-028) · Date: 2026-09-22

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).
Algorithm authority: pinned `libs/airwindows/src/GalacticProc.cpp` +
`Galactic.h` and the shared `AirWindowsEffect` adapter (structure read and
cited, never copied); algorithm identity = streamed id 49 = registry entry
`create<Galactic::Galactic>, id++, 227, gnAmbience, "Galactic"`. Quoted
designed constants and the oracle taps are governed by
[DR-0006](../../decision-records/0006-airwindows-galactic-constants-and-taps.md)
(PROPOSED, 0003/0005 pattern).

**Claim discipline.** This record advances: (1) *RTL matches the frozen
fixed-point model exactly* (iverilog-simulated; demonstrated), and (2) *the
model reproduces the pinned reference within [PROPOSED] budgets at the
slot boundary* (measured, PENDING-FREEZE). It establishes **no**
preset-support claim, **no** musical-quality claim (no human listening), no
complete-wet-preset claim, and **no** FPGA/gf180mcu synthesis, timing,
area, or hardware-playback claim. The RTL is an iverilog-simulated
schedule. No generic substitute is used under any support claim — NC-A
proves the reference budgets reject one.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (4/4 cases; 2 mutants CONTROL-OK) | `rtl-exactness.json` |
| Model ↔ pinned engine, slot boundary | **6/6 PASS (PENDING-FREEZE budgets)** | `artifacts/compare-*.json` |
| Negative controls live | **5/5 CONTROL-OK** | `negative-controls/negative-controls.json` |
| Complete-wet preset renders | **REFUSED** (fail-closed; unlanded siblings) | `artifacts/extract-refusals.txt`, extraction applicability records |
| Newly-enabled presets supported | **0** (honest delta; see §7) | this record |

## 1. Fixtures and applicability boundary (fail-closed)

Per the issue's fixtures plan, all four named presets were extracted
(`model/effects/fx_inputs/aw-49-*.json`; census blob re-verified, graphs
cross-checked, drift/modulation/aw-id checks fail-closed):

| Preset | AW-49 slot | Role | Sibling FX | Complete-wet? |
|---|---|---|---|---|
| `Altenberg/Guitars/Temple.fxp` | 4 | send1 | AW-42 "To Tape" (global2) | **REFUSED** |
| `Altenberg/Pads/Unity.fxp` | 4 | send1 | AW-42 "To Tape" (global2) | **REFUSED** |
| `Altenberg/Leads/Sine Lead.fxp` | 7 | global2 | AW-46 "Capacitor" (global1) **+ LFO→FX-Mix modulation** | **REFUSED (fixture refused entirely)** |
| `09 Example - Crossfading Oscillators.fxp` (factory, SXT-014 carrier) | 5 | send2 | Flanger (ains1) + Delay (send1, SXT-023 **FAIL**) | **REFUSED** |

- **Sine Lead refusal transcript**: `artifacts/extract-refusals.txt` — the
  extractor refuses on modulation INTO FX parameters (LFO → "FX G2 Mix" /
  "FX G1 Mix"), which is outside the frozen static-param scope. The issue's
  proposed fixture set therefore covers **two of three** named presets
  (Temple, Unity) plus the factory SXT-014 diagnostic carrier; the refusal
  is the fail-closed applicability boundary in action, retained as
  evidence.
- Complete-wet renders are refused for ALL fixtures: every carrier needs at
  least one unlanded (or landed-failing) sibling class. The reference leg
  is **slot-boundary only** (tapped), which is exactly scoped to this leaf.
- Repeatability class of every carrier: **conditioned-on-tap** (scene
  drift > 0 and/or the wall-clock-seeded aw49 vibrato). Measured
  cross-instance spread (Temple wet bus, 4 fresh instances): max |Δ| up to
  2.9e-1, RMS Δ ≈ 2.1e-2 vs signal RMS 3.7e-2 — and the all-off dry bus is
  itself non-identical across instances. The SXT-023-style 3× determinism
  gate cannot hold for these carriers; single renders are committed with
  the spread recorded (`artifacts/repeatability-temple.json`). This is a
  repeatability-class finding for SXT-013, never folded into the fidelity
  budgets.

## 2. Frozen fixed-point model

`model/effects/aw-49/galactic_model.py` (+ freeze doc
`model/effects/aw-49/README.md`). Frozen word **Q6.25 in 32-bit
containers** (sign + 5 headroom bits), c31/c30 coefficients, exact
products, round-half-up `(x + 2^(f-1)) >>> f`, saturating stores; per-sample
schedule mirrors the pinned `processReplacing` order exactly (vibrato
predelay with quadrature sin reads → iirA → three 4-line Hadamard-diffusion
stages with cross-coupled `feedbackA..D × regen` → core sum `>>3` → iirB →
wet/dry mix with the pinned `wet < 1.0` branch).

Declared deviations (bounded): `long double`→double (≤1 ulp/op class);
adapter param-lag ramp → converged control-plane value (settle covers);
float32→Q6.25 input quantization (≤1 LSB); libm sin/pow evaluated in-model
on the oracle host (same platform libm); cycleEnd>1 sample rates refuse
(fail-closed). Two format findings, both visible contract revisions in this
branch:

- **Headroom widening Q4.28 → Q6.25.** At the initial Q4.28 word the
  fmod09 carrier (send gain 2.055, 8-voice passage) produced **146
  saturation events** — the operating point exceeds ±8. The frozen word was
  widened BEFORE the reference comparisons; under Q6.25 the full fixture
  set shows **zero saturations** and peak internal state 1.66
  (`artifacts/headroom.json`).
- **Saturating stores are load-bearing (stability-class note for
  SXT-013).** A diagnostic unclipped (wide) mode of the quantized loop
  diverges: the loop norm sits at ≈1 and coefficient-rounding noise is
  integrated. The pinned float engine is bounded by its own arithmetic; the
  frozen model's saturating stores play the equivalent role. With them, all
  committed comparisons hold at −84…−116 dB.

## 3. Model vs pinned engine — slot boundary, [PROPOSED] budgets (PENDING-FREEZE)

Method: DR-0006 instrumented build (`1.4.sxt028a-tap.962503f3e`,
`build-py311-aw49`); tapped renders under the SXT-012/023 policies
(controller reset, 0.25 s settle, block-quantized scheduling, tail); the
model is driven by the engine's own adapter-input floats and the tapped
per-sample vibrato control-plane stream, and compared against the engine's
adapter-output floats. Neutrality gates (DR-0005, adapted per DR-0006 for
nondeterministic carriers): probe deterministic taps-off ×2, taps-on ==
taps-off, and cross-build vs the pre-existing build-py311 tree — **all
PASS on every fixture** (sidecar `neutrality_gate`). Budgets are the
sxt-024 reverb-class proposals; verdicts are PENDING-FREEZE (SXT-013 owns
the freeze).

| Case | blocks | max_abs (≤1e-3) | rms_rel (≤−50 dB) | spectral corr (≥0.98) | saturations | Verdict |
|---|---|---|---|---|---|---|
| temple × seq-notes-coverage-v1 | 8550 | 5.0e-7 | −113.1 dB | 1.000000000 | 0 | **PASS** |
| temple × seq-poly-8-v1 | 5550 | 3.5e-7 | −113.3 dB | 1.000000000 | 0 | **PASS** |
| unity × seq-notes-coverage-v1 | 8550 | 1.1e-7 | −83.7 dB | 0.999999998 | 0 | **PASS** |
| unity × seq-poly-8-v1 | 5550 | 1.6e-7 | −99.2 dB | 1.000000000 | 0 | **PASS** |
| fmod09 × seq-notes-coverage-v1 | 8550 | 1.4e-6 | −110.5 dB | 1.000000000 | 0 | **PASS** |
| fmod09 × seq-poly-8-v1 | 5550 | 3.4e-6 | −111.3 dB | 1.000000000 | 0 | **PASS** |

(Blocks = post-settle render blocks; the models additionally replay the
375-block settle phase from constructor state.) Internal-state diagnostics:
the engine's tapped per-sample `iirAL`/`fbAR` trajectories agree with the
model's fixed-point states to single-LSB deltas, and the model's shared
L/R counter schedule matches the engine's `countM` exactly over the probed
windows — recorded per case in the compare artifacts.

Mid-render patch-change/reset on the engine side is **BLOCKED** by the
known surgepy embedding limitation (host-thread `loadPatch` kills the
render; documented in sxt-024 §3 — the same limitation applies). The FX
type-toggle rebuild path is the engine's reset semantics; model/RTL reset
semantics (constructor state + host bulk clear) are exercised exactly in
the RTL `prs-128b-reset48` case. Panic (`allNotesOff`) is a voice-stage
action: the FX tail continues, and the fixture sequences exercise
note-offs + declared tails.

## 4. RTL vs frozen model — EXACT (iverilog 13.0)

`rtl/effects/aw-49/galactic_core.sv` + `tb_galactic.sv` +
`tools/compare_rtl_model_aw49.py` → `rtl-exactness.json` (status **PASS**).
Two cores (one per instance region) behind one external-memory port;
per-sample control stream (vibrato base/fract words) is control-plane.
Compared with exact integer equality: every output word, every per-block
checkpoint (countM, 12 line counters, iirA/iirB, 8 feedback registers),
every external-memory transaction in issue order, the final external-memory
image (54 words/frame × instances), and the frozen-revision pin.

| Case | Blocks | Stimulus | Result |
|---|---|---|---|
| prs-128b-smoke | 128 | deterministic PRS, synthetic vibrato stream, full 2×126,354-word memory image | **EXACT** |
| canonical-temple-512b | 512 | real temple tapped input + tapped vibrato control plane | **EXACT** |
| dual-instance-64b | 64 | instances alternate; disjoint regions; per-instance equality | **EXACT** |
| prs-128b-reset48 | 128 | host bulk clear + core reset before block 48 | **EXACT** |
| mutant-regen-halved | 256 | feedback regen halved in the RTL | **CONTROL-OK: FAILS** |
| mutant-shared-memory-dual | 64 | `mem_base` dropped (both instances pool one region) | **CONTROL-OK: FAILS** |

Traffic measured from the RTL txn log: 28 R + 26 W = **54 words = 216
B/frame/instance** (10.368 MB/s at 48 kHz), matching the model's
transaction hooks and `buffer-requirement.json` (SXT-015/016 reconciliation).
Per-instance external writable state: **126,354 words ≈ 493.6 KiB**
(24 delay lines at the pinned array sizes + two 257-word vibrato lines);
on-chip state ≈ counters (13×32 b) + filters/feedback (12×32 b) +
coefficients (~1.5 Kb); all processing in-chip; flash is never a
substitute. Two concurrent slots = two instances = two disjoint regions.

## 5. Negative controls (each must FAIL the check it targets)

`tools/aw49_negative_controls.py` → `negative-controls/` — all **CONTROL-OK**:

| Control | Result |
|---|---|
| NC-A generic substitute (inline Schroeder comb/allpass, same boundary) | **fails** the reference budgets (adapted ≠ supported) |
| NC-B dropped tail (render truncated 2 s before end) | **fails** the tail-region agreement check |
| NC-C wrong order (two serial instances A→B vs B→A, 400 blocks) | **flagged**: the order-sensitive check detects the permutation |
| NC-D stale stub (trace revision ≠ model revision) | **refused** by the comparator (`revision_pin.ok=False`, exact=False) |
| NC-E conditioning sensitivity (no tapped vibM) | **fails** the budgets — the tapped control plane is load-bearing |

Additional live refusals retained: the Sine Lead extraction refusal
(modulation into FX params, `artifacts/extract-refusals.txt`) and the
per-fixture complete-wet refusals (extraction applicability records).

## 6. What this record does NOT establish

- Any fidelity policy or frozen budget (SXT-013; all numbers are against
  [PROPOSED] tolerances, PENDING-FREEZE).
- Any preset-support or musical-quality claim; no human listening has
  occurred (#8/#9 BLOCKED-on-human). Essentiality of the ablation delta
  (10.093 dB, SXT-014 diagnostic) remains UNVERIFIED.
- Any complete-wet preset render: every fixture needs unlanded sibling FX;
  supported-coverage delta is **zero** (see §7).
- FPGA/gf180mcu synthesis, place-and-route, timing, power, or hardware
  playback; the RTL is an iverilog-simulated schedule (v13.0 local;
  per-case version recorded in `rtl-exactness.json`).
- Repeatability of unconditioned engine renders for this class of preset
  (the wall-clock seeding finding is routed to SXT-013 as a policy input).
- Any claim about sibling Airwindows algorithms (AW-42/46 etc.) — their
  slots were only bypassed/observed, never modeled.

## 7. Newly-enabled presets (honest delta)

The issue's upper bound (81 B4-scope candidates; 38 strict-FX-complete)
counts presets whose every active FX class is landed/in-flight **or this
leaf**. After this leaf, the per-preset support status is unchanged:
**supported stays 0**. The conjunction in `reports/coverage-v1/README.md`
still fails for every AW-49 carrier at earlier gates (voice leaf #48
unlanded; fidelity freeze #12 open; Delay class landed-FAIL for
carriers that use it; listening BLOCKED). What this leaf adds is the
AW-49 class evidence itself: `fx:AW-49` becomes a leaf-verified class
(PENDING-FREEZE caveat), such that a carrier whose remaining gates clear
would count. The leaf ledger entry (`reports/coverage-v1/leaf-verification.json`,
`airwindows_leaves."49"`) is updated to `landed: true` with the evidence
pins of this record.

## 8. Reproduce

```sh
# oracle host (taps + renders; DR-0006 build)
python3 tools/extract_aw49_inputs.py
python3 tools/render_aw49_reference.py --out-dir ~/aw49-fixtures
python3 tools/compare_aw49_reference.py --fixtures-dir ~/aw49-fixtures \
    --out-dir ~/aw49-fixtures/compare

# anywhere with iverilog (RTL exactness; canonical fixture npz committed)
python3 tools/compare_rtl_model_aw49.py

# anywhere (negative controls; uses the canonical fixture npz)
python3 tools/aw49_negative_controls.py

# anywhere (unit/integrity tests)
python3 -m pytest tests/test_sxt028a.py -q
```

## 9. Provenance / licensing

All files in this repository are original (Apache-2.0 per `LICENSE`).
Galactic structure is read and cited from the pinned GPL-3.0-or-later tree
(`libs/airwindows/src/GalacticProc.cpp` via the `AirWindowsEffect`
adapter). The twelve delay-length integers and `delayM = 256` are quoted as
data per [DR-0006](../../decision-records/0006-airwindows-galactic-constants-and-taps.md);
every other constant is re-derived from cited formulas. The oracle tap
patch script and patched tree stay on the oracle host (method pinned in
DR-0006). No Surge source, tables beyond the cited constants, or assets are
committed; no distribution-license determination has been made for
Surge-derived material.
