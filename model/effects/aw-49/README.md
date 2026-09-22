# SXT-028a Airwindows "Galactic" (id 49) — frozen fixed-point model

Issue: #53 (SXT-028a) · Model: [`galactic_model.py`](galactic_model.py) ·
Evidence: `reports/sxt-028a/EVIDENCE.md` · Parent: #21 (SXT-028), plan §6

This directory is the FROZEN integer fixed-point model that the RTL-vs-model
EXACTNESS claim references. Structure (never code) is cited from the pinned
GPL-3.0-or-later sources; see "Provenance" below. Model-vs-pinned-engine
agreement is a SEPARATE claim with [PROPOSED] budgets (PENDING-FREEZE, #12).

## Algorithm identity

`AirWindowsEffect` (the shared 12-param adapter) dispatches on `p[0]` =
streamed Airwindows id. id **49** = registry entry
`create<Galactic::Galactic>, id++, 227, gnAmbience, "Galactic"`
(`AirWinBaseClass_pluginRegistry.cpp` at the engine pin). Galactic exposes 5
float params: A Replace, B Brightness, C Modulation, D Size, E Mix.

Structure (pinned `GalacticProc.cpp processReplacing`, cited not copied):
vibrato predelay (aML/aMR, 257 used words, quadrature sin read) → input
one-pole lowpass (iirA) → three cascaded 4-line diffusion stages
(I/J/K/L → A/B/C/D → E/F/G/H; exact Hadamard-row difference writes,
cross-coupled stereo feedback `feedbackA..D × regen` into the opposite
channel's stage-1 line inputs) → output sum `/8` → output one-pole (iirB) →
wet/dry mix. The reverb core is decimated by `cycleEnd =
floor((1/44100)·samplerate)` — **1 at 48 kHz, i.e. every sample** (frozen;
other rates refuse).

## Frozen word lengths

| Format | Use | Definition |
|---|---|---|
| `s32i` | audio, all 26 delay lines, iirA/iirB + feedback states | **Q4.28 in 32-bit containers**: sign + 3 headroom bits (range ±8, LSB 2⁻²⁸) |
| `c31` | regen, lowpass, (1−lowpass), wet, (1−wet), vibrato interp fraction | Q1.31 |
| `c30` | attenuate (±1.333) | Q2.30 |
| control | per-sample vibrato read base (int) + fraction (c31), per channel | streamed, see below |

Headroom: Q4.28 = the reverb1 leaf's frozen container; the Hadamard row sums
reach 4× line amplitude coherently and the loop is bounded
(‖M‖ = 2 per stage, regen ≤ 0.125, loop norm ≤ 1); the empirical worst case
over the fixture corner set peaks at 0.14 (5.8 guard bits vs peak), zero
saturations (`headroom.json` evidence).

Rounding: exact integer products, round-half-up `(x + 2^(f−1)) >>> f`,
saturating stores (`sat32`); every coefficient multiply rounds ONCE to s32i
before the (exact) sum it feeds; sums round at their store point.

## Frozen control plane (double, quantized once, streamed to RTL)

* Coefficient words per block: `regen = 0.0625+(1−A)·0.0625` (c31),
  `attenuate = (1−regen/0.125)·1.333` (c30), `lowpass =
  pow(1.00001−(1−B),2)/sqrt(overallscale)` (c31 + exact 2³¹−q complement),
  `wet = 1−(1−E)³` (c31 + complement; the engine's `wet < 1.0` double
  compare decides the mix branch), and the 12 integer delay lengths
  `delayX = (int)(multX·size)`, `size = D·1.77+0.1`.
* Per-sample vibrato words (4/frame): base = `(int)((sin(vibM)+1)·127)` and
  c31 fraction, L plus quadrature R (`+π/2`). **`vibM` is a control-plane
  accumulator** (Delay-leaf lfophase precedent): it evolves per sample as
  `vibM += oldfpd·drift` (`drift = C³·0.001`), wrapping at 2π where
  `oldfpd = 0.4294967295 + fpdL·0.0000000000618`. The constructor draws
  `fpdL/fpdR` from the C `rand()` stream seeded by
  `srand((unsigned)time(nullptr))` in the SurgeSynthesizer constructor —
  **the engine's vibrato randomization is wall-clock-seeded and therefore
  NOT cross-instance repeatable for C > 0** (measured; see EVIDENCE). The
  pair is a captured control-plane input (oracle tap per
  decision-records/0006, DR-0005 pattern), not a derivable parameter.

The adapter's float param-lag ramp (~36 ms post-load transient) is declared
control-plane at its converged target; renders settle 0.25 s before events.
The float denormal flush (`fabs(iir)<1.18e-37`) is a no-op in integer state.
`long double` (x87) intermediate precision vs double is a declared ≤1-ulp
deviation class, absorbed by the [PROPOSED] reference budgets.

## Frozen per-sample schedule (48 kHz, cycleEnd = 1; cites GalacticProc.cpp)

1. vibrato advance/wrap (control plane) → positions L/R
2. `aML[countM] = rnd30(attenuate·inL)`, `aMR` (2 ext writes);
   `countM++` wrap at >256
3. vibrato reads: 2 ext reads/channel; one-rounding interpolation
   `rnd31(a0·(2³¹−fracq) + a1·fracq)`
4. iirA: `rnd31(iirA·(2³¹−lp) + x·lp)` per channel
5. stage-1: 8 ext writes
   `aX = sat32(x ± rnd31(fb_opposite·regen))` (L lines then R), counters
   advance, 8 ext reads one full period old (`idx = count − (count >
   delay ? delay+1 : 0)`)
6. stage-2: 8 ext writes of exact row differences (sat32 at store),
   advance, 8 reads
7. stage-3: same → `outE..outH`; feedback registers `sat32(rowdiff)` (never
   stored); core = `(outE+outF+outG+outH) >> 3` (exact)
8. iirB; mix `rnd31(wet·iirB + (1−wet)·dry)` (branch skipped when the
   double `wet == 1.0`)

## Quoted designed constants (decision-records/0006, PROPOSED)

The twelve delay multipliers `3407, 1823, 859, 331, 4801, 2909, 1153, 461,
7607, 4217, 2269, 1597` (samples at size 1) and `delayM = 256` are opaque
designed integers (no construction formula in the pinned tree) quoted as
data from `GalacticProc.cpp` with file-level provenance, per DR-0003's
pattern. Every other constant in the model is re-derived from cited
formulas. No Airwindows code is committed to this repository.

## External memory (per instance; never flash)

26 regions, **126,354 words (493.6 KiB) writable per instance**: 24 delay
lines at the pinned array sizes (6480…680: I..L, 9700…940: A..D,
15220…3200: E..H, ×2 channels) + two 257-word vibrato lines (the pinned
3111-word arrays use only indices 0..256). Traffic: **28 reads + 26 writes
= 54 words = 216 B per frame per instance** (10.368 MB/s at 48 kHz),
measured on the model's transaction hooks and re-measured from the RTL
harness. Two concurrent slots = two instances = two disjoint regions; the
shared-instance schedule time-multiplexes them, never shares state.

## Deviations from the pinned float code (bounded, declared)

1. `long double` intermediates → double/fixed (≤1 ulp/op class).
2. Param-lag ramp → converged control-plane value (static params).
3. Single libm note: the vibrato doubles (sin/pow) are computed in Python
   doubles that call the same platform libm as the engine on the oracle
   host (bit-identical there); cross-platform libm variance is out of
   frozen scope and the evidence renders happen on the oracle host.
4. cycleEnd > 1 paths (88.2/96/176.4/192 kHz) refuse (fail-closed).
5. float32→Q4.28 input quantization (exact for |x| ≥ 2⁻⁴, ≤ 1 LSB below).

## Files

* `galactic_model.py` — frozen model, control plane, buffer report
  (`python3 galactic_model.py` prints the JSON; artifact copy in
  `reports/sxt-028a/artifacts/buffer-requirement.json`).

## Reproduce

```sh
python3 model/effects/aw-49/galactic_model.py          # buffer report
python3 tools/extract_aw49_inputs.py                   # oracle host
python3 tools/render_aw49_reference.py --slug temple   # oracle host (taps)
python3 tools/compare_rtl_model_aw49.py                # iverilog host
python3 tools/aw49_negative_controls.py                # controls; exit 0 iff all fail
```
