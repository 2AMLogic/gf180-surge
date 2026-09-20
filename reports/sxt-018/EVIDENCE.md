# SXT-018 evidence — backlog DAG + evidence-derived status board

Issue: [#29](https://github.com/2AMLogic/gf180-surge/issues/29) · PR:
`loom/sxt-018-dag-board` · Date: 2026-09-20.

## What changed (behavior)

The repository gained a machine-readable backlog DAG (`docs/dag.json`, 26
nodes: epics #1–#3 and SXT issues #4–#25 + #29) and a stdlib-only compiler
(`tools/compile_backlog_dag.py`) with two subcommands: `render` (validate,
compute/store PASS evidence hashes, rewrite the README marker block) and
`--check` (validate + freshness, no writes, exit 1 on any violation). The
README gained one generated block between `<!-- DAG:BEGIN -->` /
`<!-- DAG:END -->` markers — no other README change, no badges, no capability
claims. CI gained a `dag-check` job; the three pre-existing jobs are
untouched.

## Acceptance mapping (issue #29)

| Acceptance item (issue #29) | Status | Check / evidence |
|---|---|---|
| `--check` validates schema, vocabulary, edge closure, acyclicity | PASS | `validate_schema` (+ membership/planning-id/aggregate checks), `validate_evidence`; cycle control in [negative-controls.md](negative-controls.md#bonus-control-dependency-cycle) exits 1 |
| `--check` validates README block freshness (regenerate + diff empty) | PASS | control (a): edit without re-render → exit 1 ([transcript](negative-controls.md#a-editing-docsdagjson-without-re-rendering--freshness-failure)) |
| PASS node without evidence link rejected | PASS | control (b3), plus (b1) missing hash and (b2) wrong hash ([transcripts](negative-controls.md#b-pass-evidence-rules--rejection-of-every-approval-by-existence-shortcut)) |
| No approval-by-file-existence | PASS | control (b4): existing-but-uncommitted evidence file rejected via `git ls-files --error-unmatch` ([transcript](negative-controls.md#b4-approval-by-file-existence-pass-pointing-at-an-uncommitted-file)) |
| Unknown status string rejected | PASS | control (c): `"DONE"` → exit 1 ([transcript](negative-controls.md#c-unknown-status-string--vocabulary-rejection)) |
| Board reflects current state: #4 PASS (census evidence), #5 PASS (reports/sxt-010 evidence), #29 IN_PROGRESS, next wave NOT_RUN, #8/#9/#23/#24 BLOCKED | PASS | `docs/dag.json` statuses; counts: READY=0, IN PROGRESS=1, BLOCKED=4, NOT RUN=19, PASS=2, FAIL=0, NO VERDICT=0, STALE=0 over 26 nodes |
| Mermaid renders on GitHub; counts table matches `dag.json` | PASS | `graph TD`, quoted labels, subgraphs per epic + cross-cutting group — the same GitHub-renderable constructs as the sibling boards (style reference only); counts table is generated from `dag.json` by the same render that writes the block; visually confirmed on the PR diff |
| Sync procedure documented (PR-driven regeneration; no silent drift) | PASS | `board.sync_procedure` in [docs/dag.json](../../docs/dag.json), tool docstring, README block banner, and CI `dag-check` on every PR |

## Scope and claim discipline

- The board is **bookkeeping only**: it reports claim status of backlog
  issues. It is not capability, fidelity, or hardware evidence, and it is not
  a completion percentage or quality score. The two mandatory lines are
  emitted adjacent to the counts and printed by the tool:
  "Claim counts, not a completion percentage or a quality score. READY is
  unrun, not PASS." and "Coverage and agreement are reported separately by
  the underlying evidence; this board merges neither."
- PASS requires a committed evidence artifact whose recorded SHA-256 matches
  the file's current content at check time. Closed-issue state, labels, and
  file existence stamp nothing.
- Epics are aggregate group nodes, not claim nodes: an epic PASS is
  impossible unless every member PASSes on its own committed evidence; the
  aggregate ladder is documented in `docs/dag.json` (`board.epic_aggregate_rule`).
- #8/#9 are BLOCKED because their listening portions need a human (the
  apparatus itself is automatable); #23/#24 are BLOCKED on FPGA board /
  gf180mcu flow access. These are backlog states, not verification verdicts.

## Sync procedure

Edit `docs/dag.json`, run `python3 tools/compile_backlog_dag.py render`,
commit `docs/dag.json` and `README.md` together. Issue-trailer changes are
transcribed by hand and must go through the same re-render; the `dag-check`
CI job re-validates on every pull request, so drift (stale block, stale or
missing evidence hash, unknown status, broken or cyclic edges) fails loudly
instead of drifting silently.

## Style provenance

The board's presentation (status chips with counts, grouped mermaid graph,
"claim counts" wording convention) follows the sibling boards of
gf180-torchsynth (capabilities block) and gf180-parasynth (`compile_dag.py`
board) as **style reference only** — no sibling code was copied. Per
[docs/REUSE-AUDIT.md](../../docs/REUSE-AUDIT.md), the audit-driven
differences are deliberate: evidence pointers are validated against the
committed artifact's current hash (Parasynth's `run_evidence` accepted
file existence alone), STALE is an explicit state, and closure/cycle checks
run over the declared DAG. Reuse-audit governance remains with #25 (SXT-019);
this tool is original stdlib Python written for this repository, so no
adoption decision is required for it.

## What remains unproved

- Nothing in this board measures the instrument: no sound-quality, preset
  support, fidelity, FPGA/ASIC, or hardware-playback claim is made or
  supported by it.
- The board's correctness is itself only as good as the transcription of
  issue trailers into `docs/dag.json` at the time of edit; the hash checks
  guard evidence staleness, not semantic drift between GitHub issues and the
  JSON (human review on PRs covers that).
- `#29` itself stays IN_PROGRESS until this PR merges; its node flips to PASS
  only via the same evidence rule (its EVIDENCE file committed and hashed).
