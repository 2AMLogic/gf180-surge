# T1 physical-flow evidence (#544), Phase A

Per-block gf180mcu physical-flow evidence for the 3 product groups that
synthesize today (`control_top`, `ext_mem_instr`, `wavetable_core`; see
`signoff/t1-item1/README.md`). Pinned tool: `klayout-tools==0.8.0`
(`signoff/requirements.txt`) via `uvx`; regenerate with
`python3 signoff/t1-physical/regen.py [group...]` (sequential; ext_mem_instr
P&R takes roughly 40 minutes).

Per group: `request.json` (place-and-route), routed stream `<g>.gds.gz`, as-built
netlist `<g>.v`, `lvs.request.json`, and `pnr` / `drc` / `lvs` / `erc` reports
(`*.report.json.gz`), plus `exit_status.json`. Large artifacts are gzipped
deterministically; the content hashes inside the reports bind the
**uncompressed** stream. ERC uses `erc-supply-spec.json`, which declares `ties[]`.

## Recorded outcomes (as the tools reported them, nothing waived)

| group | P&R | DRC | LVS | ERC |
|---|---|---|---|---|
| control_top | ok (route) | violations | match | not_checked |
| ext_mem_instr | ok (route) | violations | mismatch | not_checked |
| wavetable_core | ok (route) | violations | match | not_checked |

These are findings to triage, not clean results. Triage of the DRC violations,
the `ext_mem_instr` LVS mismatch, and why ERC reports `not_checked` is not done
here.

## What this does not establish

- Coverage is 3 of 11 product groups. `signoff/block-manifest.json` is
  unchanged: items 2/3/4/11 stay uncited (`unmet`) until all 11 groups have
  passing evidence; `tests/test_t1_physical_flow.py` fails on an earlier
  citation. The other 8 groups wait on #537 (Phase B).
- No timing closure, corners, "gf180mcu implementation" claim, or fidelity claim.
