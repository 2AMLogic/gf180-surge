# DR-0009 — LP 24 dB pinned-kernel reference harness (SXT-038)

- **Status:** PROPOSED — pending owner ratification (leaf-scoped)
- **Date:** 2026-09-25
- **Decides:** how the LP 24 dB filter leaf (#72) obtains a pinned-engine
  reference when the executable oracle (a built `surgepy` from the pinned
  tree) is not available, and what that licenses this Apache-2.0 repository
  to contain.

## Context

`oracle/manifest.json` pins the executable oracle to a checkout at
`/Users/joseph/dev/surge-xt-oracle/surge` on a macOS evidence host, and the
SXT-037 filter leaf additionally required a *patched* build of that tree
(DR-0005, oracle tap instrumentation) because the voice filter has no
surgepy exposure.  The environment in which #72 was implemented is a Linux
worker with **no** Surge checkout, no `surgepy`, and no ability to install
the JUCE/X11 build dependencies a full engine build needs (host policy).
Rendering a full-engine leg here was therefore impossible — that gap is
recorded as finding F-038-1 in `reports/SXT-038/EVIDENCE.md`, and the leaf
does **not** claim a full-engine comparison.

What *is* reachable is the exact code the pinned engine executes for a
`fut_lp24` unit: the manifest-pinned submodule `libs/sst/sst-filters`
(`e92d93a92beabde03fa4ab767b285fa21c6608d6`) with
`libs/sst/sst-basic-blocks` (`a32b8aec14d661e415bb676bb2e2a0a4da4efc96`).
Both are header-only and build standalone with a C++20 compiler.

## Decision

1. **The reference for this leaf is the pinned filter submodule, exercised
   through the pinned voice-path sequence** — `CM.MakeCoeffs` →
   `CM.updateState` → 64 kernel calls → `CM.updateCoefficients`, with
   `setSampleRateAndBlockSize(dsamplerate_os, BLOCK_SIZE_OS)` = (96000, 64)
   and the engine's `CM.Reset()` + `FBP` zero on voice creation / subtype
   change (`SurgeVoice.cpp`, cited).  It is named exactly that everywhere
   (`"kind": "pinned-filter-submodule"` in every bundle `meta.json`), never
   "the engine".
2. **The GPL submodules are checked out EXTERNALLY** by
   `oracle/sxt038/build_lp24_ref.sh` (default `~/.cache/sxt038-oracle`; the
   script refuses a path inside this repository) at the manifest-pinned
   SHAs, and refuses on SHA drift or a dirty checkout.
3. **The harness SOURCE (`oracle/sxt038/lp24_ref_harness.cpp`) lives in this
   repository under Apache-2.0.**  It is original work that contains no
   code, tables, constants or text copied from any GPL source; it is an API
   client that `#include`s the pinned headers at build time.  The resulting
   **binary** is a GPL-3.0-or-later combined work: it is built into the
   external directory only, is never committed, and is never distributed.
   This repository has made no distribution-license determination, and this
   record does not make one.
4. **Engine facts are reproduced by construction, never copied.**  The
   harness' `surge-lut` tuning provider re-derives `table_pitch`,
   `table_two_to_the` and `table_note_omega` from the pinned
   `SurgeStorage::init_tables()` *formulas* (cited by file and symbol) so the
   reference sees the engine's table semantics rather than exact
   trigonometry.  No table payload is copied into the repository, consistent
   with DR-0002/0003/0008 treatment of constant tables.
5. **A provider-independence leg is mandatory.**  Every case can also be
   rendered with sst-filters' own `detail::BasicTuningProvider`
   (`--provider exact`), which takes zero input from this repository, so the
   contribution of item 4 is measured rather than assumed
   (`reports/SXT-038/EVIDENCE.md` §3).
6. **Only numeric output is committed** — coefficient planes, filter
   signals, registers — exactly as engine render output already is
   (`reports/SXT-040/artifacts/*-ref.wav`, `reports/sxt-037/artifacts/bundle-*`).

## Recorded hashes

- harness source `oracle/sxt038/lp24_ref_harness.cpp`: pinned per render in
  every `reports/SXT-038/artifacts/bundle-*/meta.json`
  (`reference.harness_source_sha256`), together with the two submodule SHAs
  and the compiler version.
- build flags: `-O2 -std=c++20 -msse4.2 -ffp-contract=off
  -DSIMDE_UNAVAILABLE` (no FMA contraction, native SSE instead of simde; the
  three LP24 kernels use only add/sub/mul/max, which are IEEE-identical on
  both paths).

## Alternatives rejected

- **Build `surgepy` from the pinned tree here.**  Needs JUCE's Linux system
  dependencies, which host policy forbids installing, and a multi-hour build
  on a shared 8-core dispatch worker.  Would have produced the stronger
  full-engine leg; recorded as the open gap F-038-1 instead of faked.
- **Reuse the SXT-037 tap bundles as the reference.**  They carry LP *12* dB
  outputs; there is no LP24 reference in them.  (Their filter-INPUT signal is
  reused, declared, as a stimulus — that is a stimulus choice, not a
  reference claim.)
- **Declare the leaf BLOCKED for lack of an oracle.**  Would have left claim
  (1) (RTL == frozen model) unmeasured too, although it needs no oracle at
  all, and would have produced no measured coefficient/kernel evidence.
- **Copy the pinned filter code (or its tables) into this repository.**
  Forbidden by AGENTS.md without a license decision, and unnecessary.

## Consequences

- The leaf's claim (2) is stated precisely as *model vs pinned filter code at
  the filter-stage boundary*, and every artifact says so.  It is weaker than
  a full-engine leg in exactly one respect — the surrounding voice graph and
  the preset's own modulation state are not executed — and the evidence
  record says so in §0 and §7.
- Reference renders are reproducible on **any** host with `git`, network and
  a C++20 compiler (no macOS oracle host, no patched build), and are
  byte-stable across re-renders (verified by
  `tools/run_sxt038_checks.py` step 1 against the committed sha256s).
- If a full-engine oracle becomes available, the same case files and control
  planes can drive a tap-based leg (DR-0005 style) without changing the model
  or the RTL.
