# 0001: Oracle automation source policy (SXT-010)

- **Status**: ratified
- **Date**: 2026-09-19
- **Decided by**: Loom builder agent, on the governance authority of issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25) (SXT-019, reuse substrate adoption decision), from the survey evidence in `docs/REUSE-AUDIT.md` (audit date 2026-09-19)
- **Consumed by**: #5 (SXT-010, build the native oracle)

## Context

SXT-010 (#5) must pin a fully re-fetchable executable reference — Surge XT
commit, submodules, toolchain/runtime, 48 kHz, scheduling, reset, tuning,
randomness — and build a native oracle that loads every corpus entry. Its
inputs note that `surgepy` / headless test infrastructure is the preferred
automation path, and the user's local repos contain exactly such prior
automation. The reuse survey
([`docs/REUSE-AUDIT.md`](../docs/REUSE-AUDIT.md), section "Surge-specific
prior art (user-owned)") found four user-owned candidates (S1–S4) with
divergent license states, and the plan's license rule (`AGENTS.md`) keeps
this repository Apache-2.0 while the pinned Surge engine and GPL-derived
material stay external. Nothing may be adopted without a recorded decision
in #25 (`docs/REUSE-AUDIT.md`, "Standing rules"), so the SXT-010 automation
source needs one before any fetch/build script is written. This record is
that decision.

Scope note: this record governs automation transport and plumbing only.
The standing rule applies unchanged — sibling DSP is rejected on principle;
the only DSP oracle is the pinned Surge engine.

## Decision

Four decisions, each citing its survey row and license facts:

1. **The oracle is the pinned native Surge build.**
   `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
   (declared license **GPL-3.0-or-later**) is the SXT-010 oracle. The
   survey's "Source boundary and identity" section designates this engine
   "the **reference**, not substrate," and it lives in an **external working
   directory**; it is **never vendored** into this Apache-2.0 repository.
   Any future change of oracle source requires a new decision record here,
   not a silent follow of upstream. (Survey rows: Source boundary table,
   engine paragraph; `AGENTS.md` licensing rule.)

2. **`turian/surge-python-demo` (S1) and `turian/surge-python` (S2) are
   consulted READ-ONLY as prior art** for `surgepy` API usage — preset
   loading/rendering, FXP handling, packaging/automation. Both are declared
   **GPL-3.0 / GPL** in the survey and both are **not pinned**; no code,
   table, or asset from either is copied into this repository. API-usage
   knowledge is not copyrightable; code is. Re-implementations here are
   written from API knowledge, with the external repos kept out of the
   source tree. (Survey rows S1, S2; survey recommendation: "Do not copy
   into this repo (GPL). Consult as external prior art"; negative finding:
   none of the user's surgepy scripts was rerun here or pinned.)

3. **`turian/surge-python-docker` (S3, Apache-2.0) is NOT adopted now.** The
   survey marks it the only adoption-eligible candidate of the four
   (Apache-2.0, "adopt-candidate with attribution"), but eligibility is not
   adoption: the pinned native build is preferred because SXT-010's manifest
   must pin and verify the exact commit, submodule state, toolchain, and
   runtime, and a native build gives direct environment control over that
   identity. This record **does not reject** S3: dockerized automation is
   recorded as a fallback for a later re-decision in #25 **if** native
   builds prove unmaintainable. Any such re-adoption re-pins the source
   commit, keeps the Apache-2.0 notice, and lands its tests per the
   adoption mechanics. (Survey row S3; negative finding: the scripts were
   not rerun or pinned in the survey.)

4. **`turian/random-surgepy-patch` (S4) is reading-only.** It has **no
   declared license**; no license means no adoption right. It may be read
   as prior art like S1/S2, but any future adoption requires the owner to
   license it first, followed by a recorded decision in #25 that re-pins the
   source and retains attribution. (Survey row S4: "No license = no
   adoption right.")

**License status of this repository:** recording these decisions does not
change that **this project has made no distribution-license determination**
for a future chip product (`AGENTS.md`). The GPL boundary above is a
repository-content rule, not a distribution ruling.

## Alternatives considered

- **Adopt `surge-python-docker` (S3) now** — rejected for now: the survey
  found its scripts unverified and unpinned, and wrapping the pinned native
  build in a container before the environment-identity manifest exists would
  add a layer between the oracle and the identity SXT-010 must pin. Retained
  as a recorded fallback (Decision 3).
- **Copy GPL surgepy glue (S1/S2) into this repo with attribution** —
  rejected: GPL-derived code may not enter this Apache-2.0 repository
  without a license decision record, and none of these decisions grants
  one; the survey's boundary rule and `AGENTS.md` both forbid it.
- **Adopt `random-surgepy-patch` (S4) alongside S1/S2 as prior art with
  attribution** — rejected: attribution does not substitute for a license;
  with no license there is no adoption right at all.

## Consequences

- SXT-010 (#5) implements its fetch/build scripts against the external
  pinned native build and records the environment identity in
  `oracle/manifest`; no S1–S4 code appears in this repository, so no
  provenance row is owed for them.
- The negative control required by SXT-010's acceptance (building or
  rendering against a drifted commit/submodule state is detected and
  refused) attaches to the pinned external oracle, independent of the
  automation language chosen.
- If the docker fallback is ever invoked, a new record supersedes this one
  for S3, with a re-pinned commit and the Apache notice retained.
- This repo gains the `decision-records/` convention; subsequent per-issue
  adoptions (SXT-012+, e.g. the Parasynth runner) each need their own
  record under #25 — this record decides the oracle automation source only.
- None of this establishes engine fidelity, preset support, or any
  verification status; those claims need their own evidence records.
