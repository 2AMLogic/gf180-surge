# galactic_core — synthesizability record (#579, tracker #572, parent #537)

Verdict: **NO_VERDICT** (unchanged). Not PASS, not FAIL.

| Field | Value |
|---|---|
| Request | `request.json` (unchanged; `sv_frontend: "sv2v"`, sv2v 0.0.13, `defines: {SYNTHESIS}` per the item-1 route) |
| klt | `0.9.2.dev29+g6b76bb8c6198` (committed `failure.txt` run); `0.9.2.dev25+g6363139b56b3` is the installed host klt re-inspected for this record |
| Yosys budget | **300.0 s, fixed** (`DEFAULT_YOSYS_TIMEOUT_S` in `klayout_tools/synthesize.py`) |
| Outcome | Yosys killed at the budget (`failure.txt`); exit status 1 |
| Cell count / elapsed reached | Not captured by klt on a timeout. Elapsed = the 300 s budget. The issue's manual observation (~272k generic cells; generic `abc` stopped by hand after ~14 min CPU) is a human diagnosis, **not** a klt-recorded result, and is not used as a verdict. |

## Why no longer-budget run was made here

klt has no way to raise the Yosys budget: `klt synthesize --help` lists only
`--equiv-timeout-s` (equivalence, not synthesis), the request schema has no
timeout field, and the budget is a module constant whose source comment says a
request-level override was deliberately not added. Raising it therefore needs a
klt change (e.g. a `yosys_timeout_s` request field). No released/pinned klt
with that option exists to point at, and patching the constant in a throwaway
environment or running Yosys by hand would not be a klt-recorded verdict, so
neither was done. The host-wide klt was not modified.

## Decision

- Longer-budget re-run: **BLOCKED** on the klt-side change above (to be filed
  against `klayout-tools`; not filed from this repo's PR). Re-run once a pinned
  klt exposes the budget, via `uvx --from "klayout-tools==X.Y.Z" klt synthesize`.
- If a ~30 min budget still times out, the next step is the restructure
  decision (sequential sample loop). That is an RTL change to a `product`
  file and is **not** made here; it needs its own issue naming the lint
  manifest (`rtl/lint_manifest.json`), `reports/sxt-028a/EVIDENCE.md`,
  `tools/compare_rtl_model_aw49.py`, and any sha256 pin of
  `rtl/effects/aw-49/galactic_core.sv` to re-derive.

Not proved: synthesizability, P&R, timing, DRC/LVS, equivalence, fidelity.
