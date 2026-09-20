# gf180-surge

A hardware canary for a Surge XT subset synthesis engine — polyphonic,
multi-scene, with effects — targeting the GlobalFoundries **gf180mcu** open
PDK.

Proposed first product: a live, polyphonic hardware instrument that preserves
a selected set of **complete Surge presets, including their effects**, at
48 kHz, with external host/controller/DAC/storage. A preset counts as
supported only when its complete wet sound passes the fidelity contract; a
preset with a substituted generic effect is an *adapted* preset and does not
count.

The sound reference is Surge's own engine, pinned at
[`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`](https://github.com/surge-synthesizer/surge/tree/58914e59c608ed4384ba6002e44c3465c58b2e71).
The RTL must match a frozen fixed-point model exactly; model-vs-reference
comparisons use declared error budgets.

## Status

Planning. The executable backlog is defined in
[docs/surge-xt-chip-plan-v0.1-2026-09-20.md](docs/surge-xt-chip-plan-v0.1-2026-09-20.md)
and tracked in GitHub issues.

Completed:

- **SXT-000 — preliminary static preset census** of the pinned bundled corpus
  (3,561 presets, verified against Git blob identities), with reproducible
  outputs in [corpus/census-v0.1/](corpus/census-v0.1/). This is an
  inventory and prioritization aid only; it makes no audio-support claim.

Epics:

- **E1 — Reference, corpus, and product profile** (#1): native pinned-Surge
  oracle, normalized patch graphs, render fixtures, favorites and fidelity
  policy, effects contribution, resource accounting, profile freeze.
- **E2 — Verified core: first complete wet patch** (#2): patch-image
  compiler, timed control, first dry voice, Delay/EQ, Reverb1, one complete
  wet preset, wavetable assets.
- **E3 — Coverage expansion and hardware qualification** (#3): voice and
  effect leaves by measured recovery, full coverage publication, FPGA +
  external memory, gf180 qualification.

## Ground rules

Three judgments are kept separate throughout:

1. the RTL matches the frozen fixed-point model;
2. the model reproduces the pinned Surge reference;
3. the instrument sounds good.

Passing one never establishes the others.
