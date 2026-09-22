# SXT-026a build notes — voice-slice generality (issue #48)

## Declared extended class (v2 arithmetic; superset of SXT-022 v1)

Per-voice, mono bus, dry:

* Scenes/playmode: identical to SXT-022 tier-3 (single scene A, poly, serial1,
  ws off, lowcut off, o1-only mixer path, unit 2 Off).
* Osc1: Classic (v1 paths unchanged) **or Sine**:
  * Sine = `SineOscillator` pinned source; class freezes `sine_shape(mode)==0`,
    `sine_FMmode==0` (legacy path), unison 1, retrigger on; feedback inert in
    the legacy path (source: fb_val only read by process_block_internal);
    lowcut/highcut biquads modeled for arbitrary in-range values.
* FM routing: `fm_switch` 0 (off) or 2 (`fm_3to2to1`): osc2 FM'd by osc3,
  osc1 FM'd by osc2; muted oscs still run as FM sources (SurgeVoice.cpp
  process_block conditions). FM depth = db_to_linear(fm_depth param),
  constant for the fixture class (no CC1 events — runner refuses them for
  Sine presets: the modwheel scene route targets FM Depth).
* Filter unit 1: LP 12 dB/Driven (v1) **or LP 24 dB/Driven**
  (Coeff_LP24 = Map4PoleResonance, same resoscale/clipscale/ToCoupledForm;
  IIR24CFCquad = two coupled-form sections sharing C[0..7], one clipgain
  from y2). Filter balance (bal) modeled as the serial1 Mix1 blend
  x = in*(1-Mix1) + FU1(in)*Mix1; Mix2 = min(1, 1+bal) = 1 for bal>=0.
* Modulation routes (voice): velocity -> {fu1 cutoff, fu1 reso, fu1 feg-mod-
  amount, fu2 cutoff/reso/feg (inert, unit2 off), vca gain}; keytrack -> {fu1
  cutoff, fu1 reso, ...}. Scene routes: modwheel -> {fu1 cutoff/reso} (v1),
  modwheel -> FM Depth (Sine class; constant-zero for the fixture class).
  Keytrack modsource output = (state.pitch - ktR)/12, one control-block lag
  (set after applyModulationToLocalcopy in calc_ctrldata); constant per voice.
* Scene octave `oct`: state.pitch = key + 12*oct (+ osc octave in the osc
  dispatch). Bells oct=2, osc1.oct=0.
* Width: structurally inert at serial1 (SurgeVoice.cpp: width only read for
  fc_stereo/fc_wide) — gate dropped from tier-4, oracle A/B probe committed.

## Engine sources read & cited (never copied)

* src/common/dsp/oscillators/SineOscillator.{h,cpp} — legacy path (FMmode 0):
  non-FM = SurgeQuadrOsc recurrence (T=float); FM = double phase accumulator
  + fastsin/fastcos (JUCE Pade rational, float32) + clampToPiRange per
  sample; applyFilter (hp coeff_HP / lp coeff_LP2B, BiquadFilter TDF2,
  double) then CharacterFilter (shared with Classic).
* libs/sst/sst-basic-blocks .../QuadratureOscillators.h — SurgeQuadrOsc:
  set_rate: dr=cos,di=sin + normalize(r,i); process: 4 mul / 2 add float32.
* libs/sst/sst-basic-blocks .../FastMath.h — fastsin/fastcos Pade rationals;
  clampToPiRange.
* src/common/dsp/filters/BiquadFilter.h -> sst-filters BiquadFilter.h —
  coeff_HP/coeff_LP2B (set_coef a0-normalized), TDF2 process_block (double).
* sst-filters FilterCoefficientMaker_Impl.h — Coeff_LP24, Map4PoleResonance
  (Driven: reso*=max(0,1-max(0,(f-58)*.05)); 1-1.05*clamp(reso,.001,1)),
  resoscale (Driven 1-.5r^2), clipscale (Driven db_to_linear(f*.55)/64).
* sst-filters QuadFilterUnit_Impl.h — IIR24CFCquad (two CFC sections, shared
  coeffs, single clipgain R[2] from y2).
* src/common/dsp/SurgeVoice.cpp — velocity fvel=vel/127; keytrack
  (pitch-ktr)/12 set AFTER route application (1-block lag, ctor-time value
  identical); Gain = db_to_linear(vca_route-modded + vcavel*(1-fvel))*aeg;
  cutoffA = cfa + kta*(pitch-ktr) + emoda*fenv; FM dispatch for fm_3to2to1
  (osc3 no-FM, osc2/osc1 FM=true, depth=db_to_linear(fm_depth)); osclevels
  multiply only for audible oscs; routefilter serial1: route 1 -> 0 (DR=0);
  width only for fc_stereo/fc_wide.
* libs/sst/sst-basic-blocks .../Lag.h — SurgeLag first-run snap (FMdepth
  constant for constant target).

## Frozen numeric choices (model = reference for RTL)

* Phase/omega: Q3.28 rad (2^-28), wrap via integer clampToPiRange formula
  (PI_Q=843314856, TWO_PI_Q=1686629713, floor variant: y=phase+PI_Q>=0).
* fastsin/fastcos: EXACT big-int (RTL: 256-bit) evaluation of the pinned
  rational at the frozen Q formats, ONE final round-half-up to Q10.21
  (declared deviation vs engine float32 per-op eval; audio-rate division
  present and DECLARED — diverges from A-ALU-2, recorded for SXT-016).
* Quadrature recurrence / biquads: Q10.21 per-op round-half-up (matches the
  SXT-022 qmul discipline; engine float32/double per-op is the declared
  budget deviation, same class as SXT-022).
* Fixture class refuses CC events for Sine presets (FM depth must stay
  constant); refuses computed pitch outside [24,148].
