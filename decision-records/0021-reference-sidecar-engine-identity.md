# DR-0021 — Reference sidecar engine identity (F-660-1 / #671)

- **Status:** Accepted (#671-mandated; render-sidecar provenance contract for
  the fixture leaves)
- **Date:** 2026-11-14
- **Decides:** what a reference render sidecar's `engine` block must identify,
  how the three "Pattern A" fixture renderers record engine identity from now
  on, and what happens to the thirteen already-committed sidecars whose
  `engine` block cannot identify the engine that rendered them.

## Context

A reference sidecar's `engine.commit` / `engine.version_string` was copied,
verbatim, from the extractor **inputs** file
(`model/voice/attacky_lfo_inputs.json`, `attacky_slfo_inputs.json`,
`attacky_mw_inputs.json`) by all three renderers that consume such files:

- `fixtures/render_lfo_fixture.py` (→ `reports/sxt-032/artifacts/reference-seq-*.json`, 4 sidecars)
- `fixtures/render_slfo_fixture.py` (→ `reports/SXT-041/artifacts/reference-*-slfo-*.json`, 6 sidecars)
- `fixtures/render_mw_fixture.py` (→ `reports/sxt-035/artifacts/reference-seq-*.json`, 3 sidecars)

Neither field was read from the engine that performed the render. #660
demonstrated this live: `render_lfo_fixture.py` run unmodified on the stock
pinned oracle (`1.4.HEAD.58914e59c`) wrote `1.4.sxt037-tap.01b20d0b8` — the
inputs file's value — into its own fresh sidecar. Worse, in 7 of the 13
committed sidecars the block contradicts itself: `commit` asserts the stock
pin `58914e59c…` while `version_string` asserts a tap build. The same key
(`version_string`) therefore meant "live `getVersion()`" in other producers
(`tools/render_lp12_reference.py`, `model/voice/render_uni_reference.py`) and
"inherited from the extractor" in these three — one key, opposite provenance,
in one `reports/` tree (finding F-660-1, measured in #660).

## Decision

1. **A render sidecar's `engine` block identifies the engine that rendered
   it.** The three producers now write it through
   `render_fixture.engine_identity()` — the repo's existing live convention,
   already carried by 103 committed sidecars — so a fresh sidecar records
   `engine_commit`, `engine_version_string` (live `surgepy.getVersion()`),
   `surgepy_module`, `sample_rate`, `block_size_samples`, `tempo_bpm`.
2. **The inherited value is not deleted; it moves to a sibling key.** Each
   producer records `inputs_engine: {commit, version_string}` — exactly what
   the old block carried, under a name that cannot be read as render
   provenance. When the two engines agree, both fields are still recorded:
   agreement is a finding, not a licence to collapse the keys.
3. **The 13 committed sidecars stay as committed; they are not re-rendered.**
   - 7 of them (all 4 sxt-032, all 3 sxt-035) name tap builds this repository
     cannot reach: `1.4.sxt037-tap.ff8b4dba4` is pinned only by the version
     string it reports, and DR-0005 keeps its patch script and generated
     header on the oracle host; `1.4.sxt037-tap.01b20d0b8` has **no recorded
     identity anywhere in this repository** (bounded finding, recorded in
     `reports/f-660-1-sidecar-engine-identity/EVIDENCE.md`; adjacent to #565,
     #305/#307). Re-rendering them under the stock oracle would move their
     attribution — the relabel #671's stop/escalate forbids.
   - the 6 SXT-041 sidecars inherited the stock pin string and their leaf
     states they were rendered from the file as committed, but the sidecar
     field cannot establish that attribution either way; re-rendering them
     here would also spend `render_slfo_fixture.py`'s resolvable
     `script_sha256` stamp. This change instead **states the lost
     resolvability**: the registry flag is flipped `false` and the disposition
     records that a re-render restores it (the alternative route the #126
     precedent explicitly allows).
   - Acceptance item 1 (the enumeration) and item 2 (the per-sidecar
     agreement verdicts, including a confirmation re-render of all three
     producers under the stock pinned oracle) live in
     `reports/f-660-1-sidecar-engine-identity/`.
4. **The contract is enforced, not documentary.**
   `tests/test_sidecar_engine_provenance.py` runs the failure control — a
   producer under a compiled stand-in `surgepy` extension (not the Surge
   engine) whose `getVersion()` differs from its inputs file, asserting the
   sidecar makes the difference visible — and guards the enumeration: no
   committed `reports/**/*.json` may carry an `engine` object drawn only from
   the extractor-inputs vocabulary (`commit`, `version_string`, `block_size`,
   `sample_rate`) unless it is on the declared, annotated exception list
   measured on 2026-11-14 (the 13 sidecars above, plus the 5 SXT-034 uni
   references and 9 sxt-037 bundle metas that the same shape-based detector
   flags for different, annotated reasons). Any change to that set must land
   in the change that caused it.

## Consequences

- Fresh sidecars from the three producers are unambiguous: `engine` is the
  render engine's own live reading; `inputs_engine` is declared inheritance.
  The `version_string` key collision is closed for new sidecars; the 18
  flagged committed files keep it historically and are annotated in the guard.
- There is no surgepy API for the running engine's git commit, so
  `engine_commit` remains the build manifest's value; `getVersion()` (and, if
  stronger separation is ever needed, `oracle_common.binding_provenance()`'s
  `module_sha256`) is the live signal.
- A future re-render of any of the 13 sidecars (e.g. after #565 rebuilds a
  recorded-identity tap) must land together with a guard-list update and,
  for SXT-041, a registry re-flip — the tests force the pairing.
- Out of scope here, recorded for later filing: the literal-`commit` write
  sites (`tools/render_lp12_reference.py`, `model/voice/render_uni_reference.py`,
  `tools/probe_pm_reference_validity.py`, and the three extractors), the
  inherited-`commit`-plus-live-`surgepy` sites, and adding `module_sha256` to
  the 103 existing `engine_identity` sidecars. Each already records a live
  field beside its literal, so the failure control passes for them.
- No claim is made about whether the tap and stock builds differ in audio.
  DR-0005 records the tap as evidenced-neutral on one deterministic preset;
  no committed WAV is known to be wrong, and none was re-graded, relabelled
  or deleted here.
