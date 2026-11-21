# rf_send34_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget.** The 1800 s timeout is
unchanged (`failure.txt`), and #802 supplies the missing in-run CPU
measurement: `yosys-abc` consumed CPU at the wall-clock rate for the whole
budget while `yosys` stayed blocked on the abc pipe — computing, not wedged
(klayout-tools#5780 excluded **by measurement**). Synthesizability evidence
only; no timing, area or fidelity claim.

## Environment (as found, recorded before any change)

Identical to `../rf_global2_core/RECORD.md`: ambient `TMPDIR` length 29,
`COLUMNS` unset; guard exported `TMPDIR=/tmp/s1`, `COLUMNS=1000`; klt
`0.9.2` (tagged, throwaway `uvx`); Yosys `0.67+post` (`b8e7da6f40ae8f…`);
`yosys-abc` ABC 1.01 compiled 2026-11-19 (post-#5780). Yosys budget 1800.0 s
unchanged.

## In-run CPU readings (60 s apart, this run's own PIDs)

Ran concurrently with `rf_global34_core`. This group: yosys pid 3366240,
`yosys-abc` pid 3415595 (its child). This core is the larger of the pair
(~376k derived ABC-entry cells vs ~250k): extraction cost `yosys` 66 CPU s
before it blocked, and `yosys-abc` started ~27 s later than its sibling's.

| wall clock | yosys CPU (etime) | yosys-abc CPU (etime) |
|---|---|---|
| 04:05:08 (≈T+10 min) | 00:01:06 (09:58) | 00:09:05 (09:11) |
| 04:15:09 | 00:01:06 (19:58) | 00:19:05 (19:12) |
| 04:24:09 | 00:01:06 (28:59) | 00:28:02 (28:12) |
| ~04:26 (budget) | killed | killed, last live CPU 00:28:02 |

`yosys-abc` ≈ 1.0 CPU-second per wall second throughout (28:02 CPU at 28:12
elapsed); `yosys` flat at 66 CPU s after extraction.

## Outcome

- `klt synthesize` exit **1**: Yosys killed at the 1800.0 s budget
  (`exit_status.txt`, `failure.txt`), last line `4.22.1 Extracting gate
  netlist of module '\rf_send34_core' … input.blif'`
  (`timeout-progress.txt`).
- Refreshed `failure.txt` / `timeout-progress.txt` **byte-identical to the
  committed 2026-11-14 records** (md5 checked).
- The orphaned `yosys-abc` child (3415595, ≈28 CPU min) was killed after the
  run; none left on the host.

**Reading.** Real compute in the generic ABC pass over this group's ~376k
ABC-entry cells (94.9 % multiply/accumulate arithmetic, 32 product sites —
`census.md`). The follow-up is the arithmetic/schedule question (SXT-017,
#554), not a budget or environment change.
