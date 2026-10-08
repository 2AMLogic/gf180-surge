# DR-0019 — LP 24 dB full-engine observation tap (SXT-038 F-038-1 / #307)

- **Status:** PROPOSED — pending owner ratification (route authorized by the
  #307 agent decision, option 1)
- **Date:** 2026-10-08
- **Decides:** how the full-engine LP 24 dB leg of #101 obtains filter-unit
  input/output, coefficient-plane and end-of-block register observations from
  the pinned engine, extending the DR-0005 method from the LP 12 dB leaf.

## Decision

1. **Route (#307 option 1).** The tap is authored and validated on an external
   oracle host (here: a Linux x86_64 dispatch worker) as a single local commit
   on a branch of the pinned checkout, exactly as DR-0005 did for LP 12 dB.
   Nothing GPL-derived enters this repository: the patch script
   (`sxt307_tap_patch.py`), the generated header (`sxt307_tap.h`) and the
   patched tree stay on the host. This record and
   `reports/SXT-307/artifacts/tap-build-provenance.json` pin their SHA-256.
   No distribution artifact is published (option 2 not taken); the tap build is
   rebuilt on the designated host.
2. **What is tapped** (observation only; all hooks are no-ops unless the
   environment variable `SXT307_TAP_DIR` is set):
   - *coefficients* — after each `CM[u].MakeCoeffs` in `SurgeVoice::SetQFB`,
     for units whose type is `fut_lp24`: `(scene, key, channel, lane, unit,
     block, first, type, subtype, cutoff, reso, C[8], dC[8])`. `first` is
     derived from the engine's own `CM[u].Reset()` call sites and voice
     construction (the maker's `FirstRun` is private), not from a guess.
   - *kernel boundary* — when `SXT307_TAP_DIR` is set, `fbq_global::FU1ptr/
     FU2ptr` are wrapped by a trampoline that calls the engine's own per-subtype
     kernel unchanged and records, per OS sample and active SIMD lane, the
     input and output float (`<IIIff`: tag, lane, seq, in, out). Units 0/1 are
     the left filters and 2/3 the `fc_wide` right copies.
   - *registers* — after `ProcessQuadFB` per quad: `R[0..4]` of every active
     LP24 unit (`<II5f`: tag, block, R0..R4).
   - *identity* — `tag = voice_serial*4 + unit`; the voice serial is assigned at
     voice construction, so independent voices/units/lanes are never combined.
     `tools/render_lp24_tap_reference.py` splits the stream into one candidate
     bundle per tag in the layout `run_filter_leg.py` consumes
     (`tag=0, lane=0` re-sequenced), so the unchanged consumer sees one
     instance per bundle.
3. **Neutrality is an enforced gate** (DR-0005 item 3) and is *decisive only on
   an engine-deterministic case*. The tool renders each case tapped, untapped
   (same patched build, env unset), untapped again (determinism), and on the
   unpatched build of the same pin/host/toolchain/runtime, and reports PASS /
   FAIL / NO_VERDICT. Most SXT-038 carriers are engine-nondeterministic
   (drift/retrigger class), so the decisive control runs on a deterministic
   factory LP24 preset (`Basses/Bass 3`, census blob `9c55b7c5…`).
4. **A baseline-only or wrong-tap build is rejected** as a full-engine tap
   reference (version string must carry `sxt307-tap`; non-empty coefficient
   stream required) — see the evidence record.
5. **Cases are unchanged.** The committed case files and `case_plan.py`
   control plane are not edited. Where the native control plane cannot match,
   that is a bounded finding that blocks only the affected #101 requirement;
   coefficient metadata is never rewritten and the submodule harness is never
   substituted.

## Consequences

- #101 has a reachable, pinned observation source for the LP24 filter unit
  whose neutrality is not yet re-derived on raw samples (EVIDENCE §2:
  quantized-WAV equality only, STALE; raw re-derivation NOT_RUN). **No
  fidelity, coverage, musical-quality or hardware claim follows** from this
  record: it is infrastructure plus availability findings.
- The declared case plans (FEG fixture trajectory, fixed per-segment length,
  stimulus from the SXT-037 bundles) are not what a native render produces, so
  the unchanged runner currently REFUSES all eleven cases at the first gate
  (block count). See `reports/SXT-307/EVIDENCE.md` §3. Resolving that needs a
  contract decision for #101 (a native-plan variant of the cases, or a native
  stimulus/plan comparison), which is not made here.
- The tap host must rebuild from the pinned checkout; there is no cached
  artifact for dispatch workers.
