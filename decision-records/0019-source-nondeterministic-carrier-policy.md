# 0019 — SXT-012 fixture policy: source-nonrepeatable original presets stay REFUSED; leaves draw carriers from a reproducibility census (option A of #310)

- **Status:** RECORDED — fixture-policy disposition, in force at the
  enforcement points named below. It is **not** a contract revision: no gate,
  budget or acceptance rule moves. Agent decision for the owner (turian,
  attended session, 2026-10-08) on the ranked options in
  [#310](https://github.com/2AMLogic/gf180-surge/issues/310); the owner may
  overrule by restoring `loom:operator-decision`. Supersedes nothing.
- **Date:** 2026-10-09
- **Issue:** [#310](https://github.com/2AMLogic/gf180-surge/issues/310)
  (finding F-028f-3 of SXT-028f, [#126](https://github.com/2AMLogic/gf180-surge/issues/126))
- **Evidence:** `reports/SXT-028f/EVIDENCE.md` §1, §3.1, §9 F-028f-3;
  `reports/SXT-028f/artifacts/determinism-gate.json`;
  `reports/SXT-028f/artifacts/carrier-screen.json`;
  `reports/SXT-028c/EVIDENCE.md` §1.

## Decision

**Option A.** The SXT-012/023 exact gate (3 fresh-instance renders,
bit-identical) is unchanged. A preset whose own render is not reproducible on
the pinned engine is **refused as an original carrier**; it is not
conditioned, not tolerance-compared, and **never counted toward original-preset
coverage or support**. Options B (seed/drift control) and C (statistical
tolerance, a visible SXT-017 [#12](https://github.com/2AMLogic/gf180-surge/issues/12)
revision) are **not adopted and not implemented**; neither is foreclosed, and
either would need its own visible record.

## Policy invariants

1. **Gate unchanged.** The 3x bit-identical gate is not widened or softened.
2. **No silent substitution.** An issue-named carrier that is REFUSED stays
   recorded as REFUSED with its measured divergence. A leaf may replace it only
   with a carrier drawn from the census below, and must say so in its evidence.
   An issue's named carriers are a *proposal* a leaf may refuse with evidence.
3. **Refusal is not exclusion from the product target.** Refused presets
   remain in the favorites-set/product accounting as **unsupported-pending**,
   never silently dropped; the census reports them as a gap.
4. **Original wet reference is never overwritten**, and diagnostic variants
   (seed, drift override, oscillator replacement, modulation removal) are
   *diagnostic/adapted* input that never counts as original-preset coverage.
5. **A 3x PASS is repeatability-under-this-environment**, not a determinism
   claim. The longer interleaved stress screen and the 3x gate are different
   observations and are recorded separately. Native drift 0 is *eligibility*
   evidence (#322/#331), not proof of repeatability.
6. **Separate causes.** Native voicing-scene drift, voice-path repeatability
   (ALL-OFF dry bus) and wet-path (FX) randomness are separate fields; a
   refusal records which bus first diverged. Reverb 2's three named carriers
   diverge on the ALL-OFF dry bus (20/20 distinct buffers), i.e. upstream of
   every effect slot.
7. **Coverage is reported apart from agreement**; verification statuses are
   PASS, FAIL, NOT_RUN, BLOCKED, NO_VERDICT or STALE.

## Census specification (implementation is separate, separately reviewed work)

The census is an inventory and prioritization aid, **not** a support claim.
Its implementation is tracked in
[#381](https://github.com/2AMLogic/gf180-surge/issues/381).

- **Scope:** every preset in the pinned corpus that any leaf may draw as a
  carrier (not only Reverb 2). One row per (preset, sequence).
- **Re-derivable by ONE committed command** (e.g. `tools/census_repeatability.py
  --out reports/sxt-012/census/`) on a host with the pinned oracle
  (`oracle/fetch-and-build.sh --prebuilt`); it reuses the
  `tools/render_fx_fixtures.py` gate rather than re-implementing it. The
  command must run under the host batch rules (no hand-launched grids).
- **Per-row fields:** preset path and sha; sequence id; native normalized
  drift read-back; static eligibility (each screen criterion separately);
  3x gate verdict with the three sha256s; ALL-OFF dry-bus stress result
  (`--stress N`, interleaved with an RNG-using preset, `distinct_dry_buffers`,
  `distinct_wet_buffers`); first-diverging bus; refusal class; status
  (PASS/FAIL/NOT_RUN/BLOCKED/NO_VERDICT/STALE). Rows never carry a
  "deterministic" boolean; only "repeatable under recorded environment".
- **Provenance:** engine commit, submodules, sample rate, block size, runtime,
  script sha256, repo commit, pinned-inputs-clean flag.
- **Required controls (all embedded in the census record):**
  - *Positive control:* the SXT-028c carriers with committed wet sha256
    (`fmcombo`, `fmtwang2`, `alienappears`) re-derive byte-identically; if any
    fails, every refusal in the run is NO_VERDICT.
  - *Bimodal control:* `Luna/MPE/Lap Harp.fxp` — a 3x PASS that does not recur
    under the stress screen (`distinct_wet_buffers` 2 on
    `seq-notes-coverage-v1`) — must be classified not-stable.
  - *Refusal control:* the three named Reverb 2 carriers must stay REFUSED
    with an unstable ALL-OFF dry bus.
  - *Failure control:* a classifier that marks every carrier repeatable must
    fail the bimodal and refusal controls (checked live by
    `tests/test_sxt310_fixture_policy.py`).
- **Consumption rule:** a leaf's reference leg selects carriers only from census
  rows that are PASS in both the 3x gate and the stress screen, still re-runs
  the 3x gate itself, and records any stale (STALE) census row.
- **Staleness:** a census row is STALE when the oracle pin, harness script
  sha256 or preset sha it was derived from changes.

## What this record does NOT establish

- **Cause of the voice-path variation** (for `Grant Me...`, `Novuo`, `Harp`):
  the one-factor bisection (oscillator type / unison / noise / drift against the
  ALL-OFF dry bus) required by #310's acceptance check is **NOT_RUN** here; it
  needs the pinned oracle host and is carried by the bounded diagnostic issue
  [#382](https://github.com/2AMLogic/gf180-surge/issues/382) (one named
  carrier, `Novuo`). #310 stays open until that diagnostic lands or #310 is
  explicitly re-scoped to it. Any such variant is diagnostic only.
- The census itself (**NOT_RUN**), any preset support, coverage, fidelity or
  quality claim, and any B or C feasibility.
- **Owner overrule path:** the owner may reverse this disposition at any time by
  restoring `loom:operator-decision` on #310; this record is then superseded by a
  new record, not edited in place.
- The `loom-daemon` side of the decision is the agent decision comment on #310.

## Enforcement points

- `tests/test_sxt310_fixture_policy.py` — the committed #126 records still
  carry the refusal, the positive control and the bimodal control, and an
  always-pass classifier fails them.
- `fixtures/README.md` (policy pointer), `reports/sxt-012/EVIDENCE.md`
  (provenance and limits), `reports/SXT-028f/EVIDENCE.md` §9 (F-028f-3 link).
