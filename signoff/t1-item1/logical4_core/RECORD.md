# logical4_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget (guarded re-run).** The 1800 s
timeout is unchanged (`failure.txt`), and #802 supplies in-run paired CPU
readings for this guarded re-run (the historical 2026-11-14 run carries no
in-run CPU readings) — for this group the largest of the six: `yosys`
accumulated 00:08:34 cumulative process CPU by 05:57 elapsed across its
pre-ABC passes (including BLIF extraction; no reading was taken at pass entry
to isolate extraction alone), while `yosys-abc` was absent at 02:57 of Yosys
elapsed time, had 00:00:02 CPU at 05:57 (00:02 ABC elapsed), and reached
00:22:58 CPU at 23:03 ABC elapsed (28:57 Yosys elapsed) in the last live
sample before the 1800 s kill. Both processes computed across the sampled
intervals; neither sat idle, so the yosys-abc handshake wedge
(klayout-tools#5780) is excluded for this guarded re-run **by measurement**.
Synthesizability evidence only; no timing, area or fidelity claim.

## Environment (as found, recorded before any change)

Identical to `../rf_global2_core/RECORD.md`: ambient `TMPDIR` length 29,
`COLUMNS` unset; guard exported `TMPDIR=/tmp/s1`, `COLUMNS=1000`; klt
`0.9.2` (tagged, throwaway `uvx`); Yosys `0.67+post` (`b8e7da6f40ae8f…`);
`yosys-abc` ABC 1.01 compiled 2026-11-19 (the upstream #5780 fix is
`klayout-tools#5975` in klt's Python launcher, absent from klt `0.9.2`).
Yosys budget 1800.0 s unchanged.

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

Reading: `yosys` accumulated 00:08:34 (514 CPU s) cumulative process CPU by
05:57 elapsed across all pre-ABC passes up to and including BLIF extraction
of ~1.99M derived cells (no reading was taken at entry to `4.22.1`, so
extraction alone is not isolated) and stayed flat at 00:08:34 afterwards
while blocked on the abc pipe. `yosys-abc` was absent at 02:57 Yosys elapsed,
had 00:00:02 CPU at 05:57 (00:02 ABC elapsed), and reached 00:22:58 CPU at
23:03 ABC elapsed (28:57 Yosys elapsed) in the last live sample (+22:56 CPU
over 23:01 elapsed, ≈1.0 CPU-second per wall second). The wedge's signature
is flat CPU on both processes; this guarded re-run is the opposite on both.

## Outcome

- `klt synthesize` exit **1**: Yosys killed at the 1800.0 s budget
  (`exit_status.txt`, `failure.txt`), last line `4.22.1 Extracting gate
  netlist of module '\logical4_core' … input.blif'`
  (`timeout-progress.txt`).
- Refreshed `failure.txt` / `timeout-progress.txt` **byte-identical to the
  committed 2026-11-14 records** (md5 checked).
- The orphaned `yosys-abc` child (1171125, ≈23 CPU min at last live snap) was
  killed after the run; none left on the host.

**Reading.** Real compute in this guarded re-run: 00:08:34 cumulative `yosys`
pre-ABC CPU (through BLIF extraction) plus 00:22:58 measured `yosys-abc` CPU
by the last live sample at 28:57 Yosys elapsed (23:03 ABC elapsed) over
~1.99M ABC-entry cells — 46 products (10 unreduced
192-wide), a 192-bit divider worth 34.2 % of the design and two async ROMs
(`census.md`). The follow-up is the arithmetic/schedule question (SXT-017,
#554), not a budget or environment change.
