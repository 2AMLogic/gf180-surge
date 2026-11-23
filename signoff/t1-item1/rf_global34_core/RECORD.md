# rf_global34_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget (guarded re-run).** The 1800 s
timeout is unchanged (`failure.txt`), and #802 adds in-run paired CPU
readings for this guarded re-run (the historical 2026-11-14 run carries no
in-run CPU readings): across the sampled paired live interval
(`04:05:08`–`04:24:09`, `09:39`–`28:39` ABC elapsed), `yosys-abc` advanced
from 00:09:33 to 00:28:29 CPU (+18:56 CPU over 19:00 elapsed, ≈1.0
CPU-second per wall second) while `yosys` stayed flat at 00:00:28 cumulative
CPU, blocked on the abc pipe. This guarded re-run was computing, not wedged
— excluding the yosys-abc handshake wedge (klayout-tools#5780) for this
re-run **by measurement**. Synthesizability evidence only; no timing, area
or fidelity claim.

## Environment (as found, recorded before any change)

Identical to `../rf_global2_core/RECORD.md`: ambient `TMPDIR` length 29
(below the 36-character wrap threshold), `COLUMNS` unset; guard exported
`TMPDIR=/tmp/s1`, `COLUMNS=1000`; klt `0.9.2` (tagged) from a throwaway
`uvx --from klayout-tools==0.9.2` environment; Yosys `0.67+post`
(`b8e7da6f40ae8f…`, host-provisioned, same sha1 as every committed record);
`yosys-abc` ABC 1.01 compiled 2026-11-19 20:03:50 (`libreadline.so.8`; the
upstream #5780 fix is `klayout-tools#5975` in klt's Python launcher, absent
from klt `0.9.2`). Yosys budget 1800.0 s unchanged.

## In-run CPU readings (60 s apart, this run's own PIDs)

Ran concurrently with `rf_send34_core` (two-group bound). This group:
yosys pid 3366231, `yosys-abc` pid 3383908 (its child).

| wall clock | yosys CPU (etime) | yosys-abc CPU (etime) |
|---|---|---|
| 04:05:08 (≈T+10 min) | 00:00:28 (09:58) | 00:09:33 (09:39) |
| 04:15:09 | 00:00:28 (19:58) | 00:19:33 (19:39) |
| 04:24:09 (last live snap) | 00:00:28 (28:59) | 00:28:29 (28:39) |
| ~04:26 (budget) | killed | killed, last live CPU 00:28:29 at `04:24:09` |

Across the sampled paired live interval (`04:05:08`–`04:24:09`,
`09:39`–`28:39` ABC elapsed / `09:58`–`28:59` Yosys elapsed), `yosys-abc`
advanced from 00:09:33 to 00:28:29 CPU (+18:56 CPU over 19:00 elapsed, ≈1.0
CPU-second per wall second), while `yosys` stayed flat at `00:00:28`
cumulative process CPU (covering all pre-ABC passes through BLIF extraction;
no pass-entry reading was taken). The wedge's signature is flat CPU on both
processes; this guarded re-run shows the opposite on the same log position
(`4.22.1`) the committed record ends at.

## Outcome

- `klt synthesize` exit **1**: Yosys killed at the 1800.0 s budget
  (`exit_status.txt`, `failure.txt`), last line `4.22.1 Extracting gate
  netlist of module '\rf_global34_core' … input.blif'`
  (`timeout-progress.txt`).
- Refreshed `failure.txt` / `timeout-progress.txt` **byte-identical to the
  committed 2026-11-14 records** (md5 checked) — #695's negative control
  reproduces under the guard (klt `0.9.2`).
- The orphaned `yosys-abc` child (3383908, 00:28:29 CPU at last live snap)
  was killed after the run; none left on the host.

**Reading.** Real compute in this guarded re-run in the generic ABC pass over
this group's ~250k ABC-entry cells of multiply/accumulate arithmetic
(per-construct attribution and the calibration table: `census.md`, the
reference census of the three 20-product `rf_*` cores). The follow-up is the
arithmetic/schedule question (SXT-017, #554), not a budget or environment
change.
