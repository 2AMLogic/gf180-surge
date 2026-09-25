# gf180-surge — agent instructions

Open-source canary for a Surge XT subset synthesis engine — polyphonic,
multi-scene, with effects — targeting gf180mcu. Proposed first product: a live,
polyphonic hardware instrument that preserves a selected set of **complete
Surge presets, including their effects**, at 48 kHz, with external
host/controller/DAC/storage.

- The architecture, reference stack, evidence rules, and issue backlog are
  defined in `docs/surge-xt-chip-plan-v0.1-2026-09-20.md`. Issue bodies are
  normative where they tighten the plan.
- The sound reference is Surge's own engine, pinned at
  `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`. Pin the
  exact commit, submodules, sample rate, and runtime in the reference manifest
  (SXT-010) before rendering; do not silently follow upstream. Raw `.fxp`
  values are pre-migration; only the native loader's normalized state is
  authoritative.
- Keep three claims separate and never infer one from another: (1) the RTL
  matches the frozen fixed-point model exactly; (2) the model reproduces the
  pinned Surge reference within declared budgets; (3) the instrument sounds
  good. Numeric tests never establish musical usefulness; listening records
  do.
- **Effects are part of the product.** A preset counts as supported only when
  its complete wet sound passes the fidelity contract: original effect
  placement, order, stereo behavior, modulation, and tails. A preset whose
  reverb or another effect was substituted with a convenient generic is an
  *adapted* preset and does not count toward original-preset coverage.
- Preserve per-instance effect state (two Delay slots = two delay histories)
  even when arithmetic is shared. Long delay/reverb buffers may live in
  external writable memory; the processing stays in the chip. Flash is not a
  substitute for writable delay memory.
- The static census in `corpus/census-v0.1/` is an inventory and
  prioritization aid only. Its oscillator screens and effect-slot counts are
  not support claims. One factory preset (`Snare Tight.fxp`) remains
  unresolved by that parser; resolve it with native behavior, not by repair
  or silent exclusion.
- Comparison renders are dry unless the case under test is an effect or wet
  path. Do not normalize each render independently, time-warp comparisons, or
  switch reference engines per patch. Bypass tests must retain the unmodified
  wet reference.
- Licensing: this repository follows the 2AMLogic Apache-2.0 convention
  (`LICENSE`), while the pinned Surge reference, its bundled presets, and SST
  dependencies are GPL-3.0-or-later or carry their own terms. Keep
  GPL/Surge-derived material in the external pinned oracle; copying
  Surge-derived code, tables, or assets into this repository requires a
  visible license decision record before merge. Record file/table-level
  provenance before adopting any third-party code, table, or asset, and
  choose an explicit compatible source policy rather than inheriting one
  through a port. This project has not made a distribution-license
  determination.
- Adopt sibling or third-party infrastructure only through the reuse-audit
  process (`docs/REUSE-AUDIT.md` and its adoption-decision issue); adapt
  interfaces and method, pin sources, and retain attribution. Sibling
  evidence and tooling never transfer qualification to this instrument, and
  sibling DSP is rejected on principle: the only DSP oracle is the pinned
  Surge engine.
- Do not claim FPGA or gf180mcu synthesis, place-and-route, signoff, or
  hardware playback, original-Surge fidelity, or preset quality without a
  committed evidence record that establishes exactly that claim. Source
  presence, test counts, closed issues, census numbers, and generated report
  files establish nothing by themselves.
- Distinguish reference-vs-reference repeatability (exact under a defined
  environment), RTL-vs-frozen-model (must be exact), and model-vs-reference
  (declared error budgets). Hardware audio captures need their own
  alignment/calibration procedure.
- Report verification statuses as PASS, FAIL, NOT_RUN, BLOCKED, NO_VERDICT,
  or STALE, and report coverage separately from agreement. A test that did
  not run must never be reported as a pass.
- Every coding issue names one outcome, its prerequisites, exact inputs, an
  acceptance check, a relevant failure control, evidence to retain, and a
  stop/escalate condition (plan section 6, leaf issue template). PRs state
  what behavior changed, which acceptance case moved, how it was checked,
  and what remains unproved.
- Keep live negative controls (wrong effect order, shared instead of
  per-instance delay state, generic reverb under a support claim, silent/stale
  stubs, dropped tails); a control must demonstrably fail the check it
  targets.
- Do not weaken a product goal (e.g. complete wet presets, the favorites-set
  target, declared polyphony) or an acceptance rule to make a task pass;
  record a bounded finding and block only the affected dependency. Feature
  cuts are visible contract revisions (SXT-017), never silent ones.
- Keep `AGENTS.md` and `CLAUDE.md` substantively identical outside their
  Loom-managed marker blocks.

<!-- BEGIN LOOM ORCHESTRATION (AGENTS) -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration (dual-runtime: Claude Code reads `CLAUDE.md`; OpenAI Codex CLI and other AGENTS.md-aware runtimes read this file). See the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of the runtime-neutral guide to `.loom/AGENTS.md`.
<!-- END LOOM ORCHESTRATION (AGENTS) -->

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->
