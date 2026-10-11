# Static RTL lint gate (#434) -- evidence and claim limits

Status vocabulary: PASS, FAIL, NOT_RUN, BLOCKED, NO_VERDICT, STALE.
Classification coverage and diagnostic agreement are reported separately.

## What this is

`tools/check_rtl_lint.py` classifies every tracked `rtl/**/*.sv`
(`rtl/lint_manifest.json`) and runs, from the repository root, once per row of
the eleven product groups:

    verilator --lint-only --language 1800-2017 -Wall -Wno-fatal --top-module <top> <source>

as an argv array (paths with spaces stay single arguments). `-Wno-fatal` only
enables collection; the checker decides acceptance by comparing the full
diagnostic multiset with `rtl/lint_waivers.json`. Any `%Error`, nonzero exit,
unparsable diagnostic, missing/wrong tool, or malformed input cannot pass.
There is no baseline-update operation.

## What this does NOT establish

Synthesis, FPGA or gf180mcu qualification; RTL-vs-frozen-model exactness;
model-vs-Surge agreement; preset quality. `product` names a candidate module,
not a synthesizable one -- the severe UNDRIVEN baseline below shows several
cores read non-port variables that only a testbench drives. Default parameters
only. A waiver is tolerated existing debt, not a correctness finding.

## Run record (local, worker host)

Base commit `0658e25002e079b1bd9f300cf3e7727a1afbe590`. Tool as executed:
`Verilator 5.050 2026-07-01 rev vUNKNOWN-built20260924`
(`~/.cache/verilator-5.050/bin/verilator`, sha256
`fb2cc573b1055cf096c90e1efc9966fe56bdb4b265c83590cf2a49f7a0defcdf`).

| Item | Status | Detail |
|---|---|---|
| Classification coverage | PASS | 71 tracked, 71 classified once: 11 product, 1 sim_model, 32 testbench, 27 mutant_control |
| Eleven groups, no elaboration errors | PASS | 11 executed, every exit status 0, 0 `%Error` |
| Diagnostic agreement with baseline | PASS | 790 diagnostics = 790 distinct fingerprints = 790 waivers, no new/changed/stale |
| Negative controls (`--negative-control`, real tool, temp copies) | PASS | unclassified-tracked-rtl, missing-tool, wrong-version-tool, new-warning, new-severe-latch, count-decreased, count-increased, stale-waiver, injected-latch each fail at the intended stage |
| Pytest `tests/test_rtl_lint.py` | PASS | 44 passed (real-tool cases included) |

Inputs pinned: `rtl/lint_manifest.json` sha256
`3e9d3a400eb23ba3be6be1ac069c098329e914e06c20f3b714c0a8589c94cf98` (see git
for the committed bytes; this line is a convenience, the checker re-hashes
sources live and fails on drift).

## Tool provenance

Pinned upstream source: `https://github.com/verilator/verilator`, tag `v5.050`
(annotated tag object `0a24d49771fa57c36ff667272bf7b5c6705e4df0`), commit
`848d926ebd4addacacd294dc84e35d9d4ae8078c`, GitHub source archive
`v5.050.tar.gz` sha256
`ec6723f30c1798b1fbbbed97364f09c431fb4875577c314f37240e99b60a4a04`
(downloaded into an empty scratch directory; `git get-tar-commit-id` on the
archive returns the commit above; `configure.ac` declares `5.050 2026-07-01`).
The source stays external (docs/REUSE-AUDIT.md); nothing from it is vendored.

Gaps, stated rather than papered over:

* **Local binary provenance: NOT_RUN.** The worker's `verilator` reports
  `rev vUNKNOWN-built20260924`; nothing on the host proves it was built from
  commit `848d926e...`/that archive. The checker enforces the version string
  (`Verilator 5.050 2026-07-01` prefix) only. Baseline equality was observed
  with that binary; it has not been re-observed with a binary built from the
  checksummed archive.
* **CI build recipe: untested before the PR run.** `.github/workflows/ci.yml`
  job `rtl-lint` builds from the checksummed archive (sha256 and embedded
  commit verified before extraction), caches the install, and apt build
  dependencies are not version-pinned. Whether that CI-built binary yields the
  identical 790-diagnostic multiset is established only by the PR job log.
* Diagnostics are compared to Verilator 5.050's wording; a different build
  option set could in principle change message text.

## Baseline composition and severe-waiver review

Rules (all 790 diagnostics, one waiver per distinct location): WIDTHEXPAND 296,
BLKSEQ 197, WIDTHTRUNC 117, UNDRIVEN 94, UNUSEDSIGNAL 42, PROCASSINIT 36,
UNUSEDPARAM 6, LATCH 1, MULTIDRIVEN 1. No CASEINCOMPLETE.

Severe waivers (96) each carry a specific explanation and a `review_decision`
whose status is `proposed_pending_pr_review`: no reviewer decision has been
recorded yet. The checker validates the field's shape and reports
`severe_waivers_pending_review` but cannot grant a decision. Per issue #434
the reviewer must record accept/reject for these on the PR:

| Group | Rule | Count | Nature |
|---|---|---|---|
| reverb1_core | LATCH | 1 | `dp_tmp` assigned in only some arms of `always @*` (line 130) |
| logical4_core | MULTIDRIVEN | 1 | `block_done` set in an `initial` block and in `always_ff` |
| galactic_core | UNDRIVEN | 11 | non-port cfg/in variables, testbench-driven |
| logical4_core | UNDRIVEN | 3 | idem |
| reverb1_core | UNDRIVEN | 17 | idem |
| rf_ains34_core | UNDRIVEN | 11 | idem |
| rf_bins12_core | UNDRIVEN | 11 | idem |
| rf_global2_core | UNDRIVEN | 9 | idem |
| rf_global34_core | UNDRIVEN | 11 | idem |
| rf_send34_core | UNDRIVEN | 19 | idem |
| wavetable_core | UNDRIVEN | 2 | ROM arrays loaded by the testbench |

Every UNDRIVEN signal name was text-checked to appear as a hierarchical
`.<name>` reference in a testbench in the same directory (a text search, not
proof of how it is driven). No existing RTL, frozen model, fixture or tool byte
was edited to remove any warning.

## Reproduce

    python3 tools/check_rtl_lint.py --negative-control --verilator <pinned>
    python3 tools/check_rtl_lint.py --report rtl-lint-report.json --raw-dir rtl-lint-raw --verilator <pinned>

Exit 0 PASS, 1 FAIL, 2 NOT_RUN.
