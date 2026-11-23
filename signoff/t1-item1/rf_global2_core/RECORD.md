# rf_global2_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget (guarded re-run).** The 1800 s
timeout is unchanged (`failure.txt`), and #802 adds in-run paired CPU
readings for this guarded re-run (the historical 2026-11-14 run carries no
in-run CPU readings): across the sampled paired live interval
(`03:22:20`–`03:44:21`, while Yosys was alive), `yosys-abc` advanced from
00:00:35 to 00:22:29 CPU (+21:54 CPU over 22:01 elapsed, ≈1.0 CPU-second per
wall second). This guarded re-run was not idle, so the yosys-abc handshake
wedge (klayout-tools#5780) is excluded for this re-run **by measurement** —
not inferred from the timeout. Synthesizability evidence only; no timing,
area or fidelity claim.

## Environment (as found, recorded before any change)

| Field | Value |
|---|---|
| Ambient `TMPDIR` | `/tmp/loom-nt/<id>`, length **29** (below the #5780 wrap threshold of 36) |
| Ambient `COLUMNS` | unset |
| klt (run) | **`0.9.2`** (tagged), throwaway `uvx --from klayout-tools==0.9.2 klt`; host klt untouched |
| Yosys | `0.67+post` (`b8e7da6f40ae8f…`, host-provisioned `~/.cache/yosys-0.67/bin/yosys`) — same sha1 as every committed record |
| yosys-abc | UC Berkeley ABC 1.01, compiled Nov 19 2026 20:03:50, linked `libreadline.so.8` (the upstream #5780 fix is `klayout-tools#5975` in klt's Python launcher, absent from klt `0.9.2`) |
| Guard exported | `TMPDIR=/tmp/s1` (8 chars), `COLUMNS=1000` |
| Yosys budget | 1800.0 s (unchanged) |

## In-run CPU readings (60 s apart, `ps -o pid,etime,time`)

Two groups ran concurrently (this one and `rf_bins12_core`, the #802 bound).
The two `yosys`/`yosys-abc` pairs were profile-identical (within 2 s of each
other all run); PID pairs: yosys 1466945 / abc 1508503 and yosys 1466949 /
abc 1508729. `yosys` stayed flat at `00:00:32` cumulative process CPU across
all paired live samples (covering all pre-ABC passes through BLIF extraction;
no pass-entry reading was taken to isolate extraction alone) while blocked on
the abc pipe, and `yosys-abc` advanced at ≈1.0 CPU-second per wall second
across the sampled paired window:

| wall clock | yosys CPU | yosys-abc CPU (pair a / pair b) | yosys-abc elapsed |
|---|---|---|---|
| 03:22:20 (≈T+1 min) | 00:00:32 | 00:00:35 / 00:00:35 | 00:35 |
| 03:25:20 | 00:00:32 | 00:03:35 / (03:35 in next snap) | 03:35 |
| 03:30:21 | 00:00:32 | 00:08:33 / 00:08:33 | 08:36 |
| 03:35:21 | 00:00:32 | 00:13:31 / 00:13:31 | 13:36 |
| 03:44:21 (last paired live snap) | 00:00:32 | 00:22:29 / 00:22:27 | 22:36 |
| 03:52:22 (orphan sample, post-kill) | — (killed) | 00:30:27 / 00:30:25 | 30:37 |

Across the paired live readings (`03:22:20`–`03:44:21`, while `yosys` was
still alive), `yosys-abc` advanced from 00:00:35 to 00:22:29 CPU (pair a;
+21:54 CPU over 22:01 elapsed, ≈1.0 CPU-second per wall second), while
`yosys` stayed flat at 00:00:32 cumulative CPU. The `03:52:22` row (00:30:27
/ 00:30:25 CPU at 30:37 elapsed) is an orphan sample taken after `yosys` died
and includes post-kill time, so the in-run result uses the earlier paired
readings. In the wedge both processes sit idle (abc waits on stdin, yosys
waits for the echo) — flat CPU on both is its signature; this guarded re-run
is the opposite.

## Outcome

- `klt synthesize` exit **1**: Yosys killed at the 1800.0 s budget
  (`exit_status.txt`, `failure.txt`), last log line `4.22.1 Extracting gate
  netlist of module '\rf_global2_core' to '<abc-temp-dir>/input.blif'`
  (`timeout-progress.txt`).
- The refreshed `failure.txt` and `timeout-progress.txt` are **byte-identical
  to the committed 2026-11-14 records** (md5 checked) — the negative control
  #695 relies on reproduces under the guard (klt `0.9.2`).
- Both orphaned `yosys-abc` children were found reparented after the kill
  (post-kill orphan snap at `03:52:22` showed 00:30:27 / 00:30:25 CPU at
  30:37 elapsed) and killed on the host; none left running.

**Reading.** In this guarded re-run, the timeout is real compute in the
generic ABC pass over this group's ~250k-cell arithmetic (per-construct
attribution: `census.md`), not a tool handshake failure. The follow-up is the
arithmetic/schedule question (SXT-017, #554), not a budget or environment
change.
