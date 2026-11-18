# Digest-value generation environment for `reports/sxt-024/rtl-exactness.json` (issue #737)

Date: 2026-11-17 · Companion note (annotation only) · The record itself is
byte-for-byte unchanged.

## Why this note exists

Issue #720 (`artifacts/issue-720/ENV-REFUTATION.md`) measured that the
committed `txn_log_sha256` values in `rtl-exactness.json` — prs
`f74affb0e3820a91d7a0501fd5280d5141cffeca166d467d70c69872c00e108f`, click
`b8f5c0ac2bac9eac99f3d315824984ae8517215e50ded5852ef52c0f76c49f84`, mutant
`6e8bf8a8849402b18a89d338e57aaed0e81ad8d3965cd00872fd3a7cd5381c16` — do not
reproduce in any measured (tree × iverilog × numpy) Linux cell. Rather than
regenerating the record (rejected: it would turn a committed PASS record
STALE for no contract gain), this note states the environment those values
came from, which fields actually carry the contract, and the digest values
the pinned environment produces instead.

## Generation environment of the committed digest values

The committed values were produced on **macOS** — the runner at the report's
commit `fb58c0e2` hardcoded a `/var/folders/fb/…` temp dir (`/var/folders/`
is macOS-specific; portability fix `9e925830` removed it) — under
**Icarus Verilog 13.0 (stable) (v13_0)** (consistent with the record's own
`iverilog` field) and **numpy of unknown version**. They are
generation-environment artifacts, not a reproduction target.

## Contract-bearing fields

Only the exactness verdicts, the traffic fields and the mutant verdict carry
the RTL-vs-frozen-model contract (claim 1):

- exactness verdicts: `exact`, `outputs_exact`, `checkpoints_exact`,
  `txn_log_exact`, `ext_mem_exact` (where present), record `status`;
- traffic: `rtl_measured_traffic.*` (reads/writes/words_per_frame/
  `per_frame_exact_34`) and `txn_lines_model` / `txn_lines_rtl`;
- mutant control: the `verdict` line (`CONTROL-OK (mutant FAILS the
  exactness comparison)`).

The digest values (`txn_log_sha256.*`) are **generation-specific** and are
NOT contract-bearing. Any future exactness re-verification must compare the
verdict and traffic fields against this record, and either reproduce the
digest values in the same generation environment (macOS, unknown numpy —
not available) or compare against the pinned-environment digests below,
never against the committed values directly.

## Pinned-environment digest values (from `../issue-720/DIGESTS.txt`)

Measured 2026-11-17 (issue #720), Ubuntu 24.04.4 worker, Python 3.12.3,
identical in all four measured Linux (tree × iverilog) cells: current HEAD
and `fb58c0e2`, iverilog 12.0-2build2 (the `signoff/t1-item9-inventory.json`
pin) and 13.0 (v13_0) — all under numpy 1.26.4 (throwaway venv, per
`reproduce.sh`):

| Case | rtl `txn_log_sha256` | Environment |
|---|---|---|
| prs-256b-reset48 | `fbbeeba682738d0cb66375ebb28de1df22e4cf2f181b7bc0f0c7703894ce2eb8` | pin 12.0-2build2 or 13.0, numpy 1.26.4, HEAD or `fb58c0e2` |
| click-512b | `d75c9b899f2c679152b7eb860c0ce9e5ac6f5830384f9c59fc8ac3cdf85db8e0` | pin 12.0-2build2 or 13.0, numpy 1.26.4, HEAD or `fb58c0e2` |
| mutant-tap7-stale-write | `5a07312f4a58738e42470f8a02e985dc3682897c0db85000598cb45334cbac0a` | pin 12.0-2build2 or 13.0, numpy 1.26.4, HEAD or `fb58c0e2` |

numpy ≥ 2.0 (including the CI pin `requirements-ci.txt` numpy==2.4.2)
moves the click-512b digest to
`f617cc57df8248dc2239c910a457c50b5c90b46aad8cf6044e56f9cfd8bc9b0b` via the
stimulus-quantization float32 path; the prs and mutant digests are
numpy-stable. Verdicts stay `exact=True` under every measured environment
because model and RTL shift together.

These are not alternative "correct" values to splice into the record: the
record stays as committed, and a re-verification run quotes its own
environment and digests alongside verdict fields, as `CONTROL.txt` in this
directory does.

## iverilog binary selection (PATH shadowing)

On the Linux workers the default PATH resolves a bare `iverilog` to
`~/.local/bin/iverilog` — 13.0 (v13_0), a worker-local build — shadowing the
pinned `/usr/bin/iverilog` 12.0-2build2 **where the distro install exists**;
its presence is worker-dependent (some fleet workers have no distro iverilog
at all — both cases measured in #720). Exactness re-runs should select the
binary explicitly (`env PATH=…` or `SXT024_PIN_SOURCE=deb`) per
`../issue-720/reproduce.sh`, which resolves the pin either way, with a
borrow control so the deb leg cannot silently borrow another install's
`ivl` support tree. The version itself is measured irrelevant for this
comparison (finding 1); what matters is that each run records the `-V` line
of the binary that actually ran, as the runner's `iverilog` field does.

## Live control re-run (2026-11-17, this issue)

Single targeted run in the issue-737 worktree (`tools/run_reverb_rtl.py`,
exit 0): both real cases `exact=True`, mutant **CONTROL-OK (mutant FAILS
the exactness comparison)** — the live negative control still fails the
check it targets. Transcript and the regenerated record as run evidence:
`CONTROL.txt`, `CONTROL-RERUN.json` (the committed record was restored
byte-for-byte afterwards; its sha256 remains
`4de2486e32f5a7d7bb14aaa402dd6b42b4a0f40a14196c44a1dfca29270bc367`). The
rerun's digest values matched #720's cell 5 (HEAD × 13.0 × numpy 2.4.2)
exactly, and a field-by-field diff moved only `txn_log_sha256` values —
the stop/escalate condition of issue #737 (any `exact`, `txn_log_exact` or
traffic change) was not tripped.

## What this note does NOT claim

No edit or regeneration of `rtl-exactness.json` (its sha256 above must keep
holding); no change to any RTL or model file; no change to which iverilog
any worker's PATH resolves (that is worker provisioning, not this repo);
no model-vs-reference, fidelity, preset-support or musical claim — this is
RTL-vs-frozen-model (claim 1) bookkeeping only.
