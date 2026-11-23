# rf_send34_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget (guarded re-run).** The 1800 s
timeout is unchanged (`failure.txt`), and #802 supplies in-run paired CPU
readings for this guarded re-run (the historical 2026-11-14 run carries no
in-run CPU readings): across the sampled paired live interval
(`04:05:08`–`04:24:09`, `09:11`–`28:12` ABC elapsed), `yosys-abc` advanced
from 00:09:05 to 00:28:02 CPU (+18:57 CPU over 19:01 elapsed, ≈1.0
CPU-second per wall second) while `yosys` stayed flat at 00:01:06 cumulative
CPU on the abc pipe — computing, not wedged (klayout-tools#5780 excluded for
this re-run **by measurement**). Synthesizability evidence only; no timing,
area or fidelity claim.

## Environment (as found, recorded before any change)

Identical to `../rf_global2_core/RECORD.md`: ambient `TMPDIR` length 29,
`COLUMNS` unset; guard exported `TMPDIR=/tmp/s1`, `COLUMNS=1000`; klt
`0.9.2` (tagged, throwaway `uvx`); Yosys `0.67+post` (`b8e7da6f40ae8f…`);
`yosys-abc` ABC 1.01 compiled 2026-11-19 (the upstream #5780 fix is
`klayout-tools#5975` in klt's Python launcher, absent from klt `0.9.2`).
Yosys budget 1800.0 s unchanged.

## In-run CPU readings (60 s apart, this run's own PIDs)

Ran concurrently with `rf_global34_core`. This group: yosys pid 3366240,
`yosys-abc` pid 3415595 (its child). This core is the larger of the pair
(~376k derived ABC-entry cells vs ~250k): `yosys` accumulated 00:01:06
(66 CPU s) cumulative process CPU across its pre-ABC passes before blocking
on the abc pipe (no reading was taken at entry to `4.22.1` to isolate BLIF
extraction alone), and `yosys-abc` started ~27 s later than its sibling's.

| wall clock | yosys CPU (etime) | yosys-abc CPU (etime) |
|---|---|---|
| 04:05:08 (≈T+10 min) | 00:01:06 (09:58) | 00:09:05 (09:11) |
| 04:15:09 | 00:01:06 (19:58) | 00:19:05 (19:12) |
| 04:24:09 (last live snap) | 00:01:06 (28:59) | 00:28:02 (28:12) |
| ~04:26 (budget) | killed | killed, last live CPU 00:28:02 at `04:24:09` |

Across the sampled paired live interval (`04:05:08`–`04:24:09`,
`09:11`–`28:12` ABC elapsed / `09:58`–`28:59` Yosys elapsed), `yosys-abc`
advanced from 00:09:05 to 00:28:02 CPU (+18:57 CPU over 19:01 elapsed, ≈1.0
CPU-second per wall second), while `yosys` stayed flat at `00:01:06`
cumulative process CPU.

## Outcome

- `klt synthesize` exit **1**: Yosys killed at the 1800.0 s budget
  (`exit_status.txt`, `failure.txt`), last line `4.22.1 Extracting gate
  netlist of module '\rf_send34_core' … input.blif'`
  (`timeout-progress.txt`).
- Refreshed `failure.txt` / `timeout-progress.txt` **byte-identical to the
  committed 2026-11-14 records** (md5 checked).
- The orphaned `yosys-abc` child (3415595, 00:28:02 CPU at last live snap)
  was killed after the run; none left on the host.

**Reading.** Real compute in this guarded re-run in the generic ABC pass over
this group's ~376k ABC-entry cells (94.9 % multiply/accumulate arithmetic,
32 product sites — `census.md`). The follow-up is the arithmetic/schedule
question (SXT-017, #554), not a budget or environment change.
