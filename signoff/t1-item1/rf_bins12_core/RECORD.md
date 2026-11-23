# rf_bins12_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget (guarded re-run).** Identical
outcome and measurement to `rf_bins12_core`'s sibling `rf_global2_core` (the
two ran concurrently, one `regen.py` invocation each, per the two-group
bound): the 1800 s timeout stands, and #802 supplies in-run paired CPU
readings for this guarded re-run (the historical 2026-11-14 run carries no
in-run CPU readings) — across the sampled paired live interval
(`03:22:20`–`03:44:21`, while Yosys was alive), `yosys-abc` advanced from
00:00:35 to 00:22:27 CPU (+21:52 CPU over 22:01 elapsed, ≈1.0 CPU-second per
wall second), excluding the klayout-tools#5780 wedge for this re-run by
measurement. Synthesizability evidence only.

## Environment

As found and as run: identical to `../rf_global2_core/RECORD.md` (ambient
`TMPDIR` len 29, `COLUMNS` unset; guard `TMPDIR=/tmp/s1`, `COLUMNS=1000`;
klt `0.9.2` throwaway `uvx`; Yosys `0.67+post` `b8e7da6f…`;
`yosys-abc` ABC 1.01 compiled 2026-11-19 — the upstream #5780 fix is
`klayout-tools#5975` in klt's Python launcher, absent from klt `0.9.2`).
Yosys budget 1800.0 s unchanged.

## In-run CPU readings

Same run as `../rf_global2_core/RECORD.md` (PID pairs yosys 1466949 / abc
1508729 and yosys 1466945 / abc 1508503; profiles identical within 2 s):

| wall clock | yosys CPU | yosys-abc CPU (pair b / pair a) | yosys-abc elapsed |
|---|---|---|---|
| 03:22:20 (≈T+1 min) | 00:00:32 | 00:00:35 / 00:00:35 | 00:35 |
| 03:30:21 | 00:00:32 | 00:08:33 / 00:08:33 | 08:36 |
| 03:35:21 | 00:00:32 | 00:13:31 / 00:13:31 | 13:36 |
| 03:44:21 (last paired live snap) | 00:00:32 | 00:22:27 / 00:22:29 | 22:36 |
| 03:52:22 (orphan sample, post-kill) | — (killed) | 00:30:25 / 00:30:27 | 30:37 |

Across the paired live readings (`03:22:20`–`03:44:21`, while `yosys` was
alive), `yosys` stayed flat at `00:00:32` cumulative process CPU (covering
all pre-ABC passes through BLIF extraction; no pass-entry reading was taken)
and `yosys-abc` advanced from 00:00:35 to 00:22:27 CPU (+21:52 CPU over
22:01 elapsed, ≈1.0 CPU-second per wall second). The `03:52:22` row
(00:30:25 / 00:30:27 CPU at 30:37 elapsed) is an orphan sample taken after
`yosys` died and includes post-kill time, so the in-run result uses the
earlier paired readings.

## Outcome

- `klt synthesize` exit **1** (budget kill, `exit_status.txt`,
  `failure.txt`), last line `4.22.1 Extracting gate netlist … input.blif'`
  (`timeout-progress.txt`).
- Refreshed `failure.txt` / `timeout-progress.txt` **byte-identical to the
  committed 2026-11-14 records** (md5 checked).
- Its orphaned `yosys-abc` child (pair listed above; post-kill orphan snap at
  `03:52:22` showed 00:30:25 / 00:30:27 CPU at 30:37 elapsed) was killed
  after the run; none left on the host.

**Reading.** Real compute in this guarded re-run in the generic ABC pass over
~250k cells of multiply/accumulate arithmetic (`census.md` for the
per-construct split). Not a wedge, not a budget artifact; the driver is the
arithmetic/schedule question (SXT-017, #554).
