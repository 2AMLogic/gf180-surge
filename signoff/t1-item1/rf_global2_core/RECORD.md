# rf_global2_core — #802 guarded re-measurement (2026-11-21)

Verdict: **NO_VERDICT — computing at the budget.** The 1800 s timeout is
unchanged (`failure.txt`), and #802 adds the measurement the earlier records
lacked: during the generic-ABC pass the `yosys-abc` process consumed CPU at
the wall-clock rate for the whole budget. The run was not idle, so the
yosys-abc handshake wedge (klayout-tools#5780) is excluded **by measurement**
for this group — not inferred from the timeout. Synthesizability evidence
only; no timing, area or fidelity claim.

## Environment (as found, recorded before any change)

| Field | Value |
|---|---|
| Ambient `TMPDIR` | `/tmp/loom-nt/<id>`, length **29** (below the #5780 wrap threshold of 36) |
| Ambient `COLUMNS` | unset |
| klt (run) | **`0.9.2`** (tagged), throwaway `uvx --from klayout-tools==0.9.2 klt`; host klt untouched |
| Yosys | `0.67+post` (`b8e7da6f40ae8f…`, host-provisioned `~/.cache/yosys-0.67/bin/yosys`) — same sha1 as every committed record |
| yosys-abc | UC Berkeley ABC 1.01, **compiled Nov 19 2026 20:03:50**, linked `libreadline.so.8` — postdates the klayout-tools#5780 close (2026-11-17) |
| Guard exported | `TMPDIR=/tmp/s1` (8 chars), `COLUMNS=1000` |
| Yosys budget | 1800.0 s (unchanged) |

## In-run CPU readings (60 s apart, `ps -o pid,etime,time`)

Two groups ran concurrently (this one and `rf_bins12_core`, the #802 bound).
The two `yosys`/`yosys-abc` pairs were profile-identical (within 2 s of each
other all run); PID pairs: yosys 1466945 / abc 1508503 and yosys 1466949 /
abc 1508729. `yosys` finished the blif extraction in ~32 CPU s and then
blocked on the abc pipe; `yosys-abc` ran one full core from handshake to kill:

| wall clock | yosys CPU | yosys-abc CPU (pair a / pair b) | yosys-abc elapsed |
|---|---|---|---|
| 03:22:20 (≈T+1 min) | 00:00:32 | 00:00:35 / 00:00:35 | 00:35 |
| 03:25:20 | 00:00:32 | 00:03:35 / (03:35 in next snap) | 03:35 |
| 03:30:21 | 00:00:32 | 00:08:33 / 00:08:33 | 08:36 |
| 03:35:21 | 00:00:32 | 00:13:31 / 00:13:31 | 13:36 |
| 03:44:21 | 00:00:32 | 00:22:29 / 00:22:27 | 22:36 |
| 03:52:22 (last live snap) | — (killed) | 00:30:27 / 00:30:25 | 30:37 |

CPU advanced at ~1.0 CPU-second per wall second on `yosys-abc` for the entire
1800 s; `yosys` was flat after extraction. In the wedge both processes sit
idle (abc waits on stdin, yosys waits for the echo) — flat CPU on both is its
signature; this run is the opposite.

## Outcome

- `klt synthesize` exit **1**: Yosys killed at the 1800.0 s budget
  (`exit_status.txt`, `failure.txt`), last log line `4.22.1 Extracting gate
  netlist of module '\rf_global2_core' to '<abc-temp-dir>/input.blif'`
  (`timeout-progress.txt`).
- The refreshed `failure.txt` and `timeout-progress.txt` are **byte-identical
  to the committed 2026-11-14 records** (md5 checked) — the negative control
  #695 relies on reproduces under the guard, on the post-#5780 toolchain.
- Both orphaned `yosys-abc` children were found reparented after the kill
  (≈30:37 CPU each) and killed on the host; none left running.

**Reading.** The timeout is real compute in the generic ABC pass over this
group's ~250k-cell arithmetic (per-construct attribution: `census.md`), not a
tool handshake failure. The follow-up is the arithmetic/schedule question
(SXT-017, #554), not a budget or environment change.
