# logical4_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget.** The 1800 s timeout is
unchanged (`failure.txt`), and #802 supplies the missing in-run CPU
measurement — for this group the largest of the six: `yosys` itself spent
~8.5 CPU-minutes extracting the ~2.0M-cell gate netlist to the blif, then
`yosys-abc` consumed CPU at the wall-clock rate for the remaining ~24
minutes. Both processes computed; neither sat idle, so the yosys-abc
handshake wedge (klayout-tools#5780) is excluded **by measurement**.
Synthesizability evidence only; no timing, area or fidelity claim.

## Environment (as found, recorded before any change)

Identical to `../rf_global2_core/RECORD.md`: ambient `TMPDIR` length 29,
`COLUMNS` unset; guard exported `TMPDIR=/tmp/s1`, `COLUMNS=1000`; klt
`0.9.2` (tagged, throwaway `uvx`); Yosys `0.67+post` (`b8e7da6f40ae8f…`);
`yosys-abc` ABC 1.01 compiled 2026-11-19 (post-#5780). Yosys budget 1800.0 s
unchanged.

## In-run CPU readings (60 s apart, this run's own PIDs)

Ran concurrently with `galactic_core`. This group: yosys pid 917763,
`yosys-abc` pid 1171125 (its child).

| wall clock | yosys CPU (etime) | yosys-abc CPU (etime) |
|---|---|---|
| 04:32:35 (≈T+3 min) | 00:03:02 (02:57) | — (not yet spawned) |
| 04:35:35 | 00:08:34 (05:57) | 00:00:02 (00:02) |
| 04:45:36 | 00:08:34 (15:57) | 00:10:02 (10:02) |
| 04:52:36 | 00:08:34 (22:57) | 00:17:00 (17:03) |
| 04:58:36 (last live snap) | 00:08:34 (28:57) | 00:22:58 (23:03) |
| ~04:59:35 (budget) | killed | killed |

Reading: the blif extraction of ~1.99M derived cells cost `yosys` ~514 CPU s
(00:08:34 total, flat afterwards — it then blocked on the abc pipe), and
`yosys-abc` then ran ≈1.0 CPU-second per wall second from its ~T+6 spawn to
the 1800 s kill. The wedge's signature is flat CPU on both processes; this
run is the opposite on both.

## Outcome

- `klt synthesize` exit **1**: Yosys killed at the 1800.0 s budget
  (`exit_status.txt`, `failure.txt`), last line `4.22.1 Extracting gate
  netlist of module '\logical4_core' … input.blif'`
  (`timeout-progress.txt`).
- Refreshed `failure.txt` / `timeout-progress.txt` **byte-identical to the
  committed 2026-11-14 records** (md5 checked).
- The orphaned `yosys-abc` child (1171125, ≈23 CPU min) was killed after the
  run; none left on the host.

**Reading.** Real compute: ~8.5 CPU min of extraction plus ~24 CPU min of
generic ABC over ~1.99M ABC-entry cells — 46 products (10 unreduced
192-wide), a 192-bit divider worth 34.2 % of the design and two async ROMs
(`census.md`). The follow-up is the arithmetic/schedule question (SXT-017,
#554), not a budget or environment change.
