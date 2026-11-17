# Issue #720 — RTL-exactness environment refutation (iverilog pin vs recorded version)

Date: 2026-11-17 · Worker: Ubuntu 24.04.4 LTS (noble), x86_64 · Python 3.12.3

## Question

`reports/sxt-024/rtl-exactness.json` records its run as
`Icarus Verilog version 13.0 (stable) (v13_0)`, while
`signoff/t1-item9-inventory.json` declares the tool pin `12.0-2build2`.
Hypothesis to test: does the iverilog version change the simulation outputs,
and can the committed record's digests be reproduced under the pin?

## What each leg ran, and where the pin binary comes from

Quoted `iverilog -V` from the binary each leg's PATH resolved — that, not
dpkg availability output, is the measurement of what ran:

| Binary the leg resolved | `iverilog -V` (quoted) | Provenance on this measurement worker |
|---|---|---|
| `/usr/bin/iverilog` (12.0 legs) | `Icarus Verilog version 12.0 (stable) ()` | dpkg `iverilog 12.0-2build2`, `Status: install ok installed` (`dpkg -S /usr/bin/iverilog` → `iverilog`) — **the pin** |
| `~/.local/bin/iverilog` → `~/.cache/icarus-13.0/bin/iverilog` (13.0 legs) | `Icarus Verilog version 13.0 (stable) (v13_0)` | worker-local build |

The default PATH puts `~/.local/bin` before `/usr/bin`, so a bare `iverilog`
resolves to 13.0 — which is what the committed record's `iverilog` field
cites. Each leg ran with an explicit `env PATH=…` selecting exactly one
binary, and the runner's `rtl-exactness.json` `iverilog` field records the
`-V` line of the binary that actually ran.

**The pin's dpkg presence is worker-dependent, not fleet-wide**: another
fleet worker measured on the same date has no distro iverilog at all
(`dpkg -s iverilog` → not installed), with the same `~/.local/bin` 13.0.
`reproduce.sh` therefore does not assume `/usr/bin`: it uses the distro
`/usr/bin/iverilog` when that binary reports 12.0, and otherwise obtains the
exact `iverilog 12.0-2build2` deb into a throwaway directory
(`apt-get download` + `dpkg -x`; nothing host-wide, no sudo), running the
extracted binary through a one-line shim that rewrites the deb's baked-in
`#! /usr/bin/vvp` shebang to the extracted `vvp` (the runner executes
`./sim.out` directly). Both resolution paths were measured on 2026-11-17 and
produce byte-identical kept transaction logs. The numpy 1.26.4 legs ran in a
throwaway venv (`python3 -m venv` + `pip install numpy==1.26.4` — the host
numpy is ≥ 2.x and would move the click digest, finding 3); `reproduce.sh`
creates it.

## Measurement

`tools/run_reverb_rtl.py --keep` (exit 0 in every leg; two real cases EXACT +
mutant control) under six environments, on two tree states: current HEAD of
the issue branch (functionally the report's tree — the post-report commits
touch the runner only in dead-code removal and temp-dir portability) and the
report's own commit `fb58c0e2` (scratch tree; its hardcoded macOS temp path
patched in the scratch copy only, never in git). The numpy-1.26.4 legs ran
in a throwaway venv created by `reproduce.sh` (host numpy ≥ 2.x would move
the click digest; finding 3). Parsed
`txn_log_sha256` (rtl side; model side equal wherever `txn_log_exact` is
true, which is every real case in every leg):

| # | Tree | iverilog | numpy | prs-256b-reset48 rtl | click-512b rtl | mutant rtl | Status |
|---|---|---|---|---|---|---|---|
| 1 | HEAD | 12.0-2build2 (resolved pin) | 1.26.4 | `fbbeeba68273…ce2eb8` | `d75c9b899f2c…5db8e0` | `5a07312f4a58…4cbac0a` | PASS |
| 2 | HEAD | 13.0 (v13_0) | 1.26.4 | same | same | same | PASS |
| 3 | fb58c0e2 | 12.0-2build2 (resolved pin) | 1.26.4 | same | same | same | PASS |
| 4 | fb58c0e2 | 13.0 (v13_0) | 1.26.4 | same | same | same | PASS |
| 5 | HEAD | 13.0 (v13_0) | 2.4.2 | same | `f617cc57df82…8bc9b0b` | same | PASS |
| 6 | HEAD | 13.0 (v13_0) | 2.0.2 / 2.1.3 / 2.2.6 / 2.3.4 | same | `f617cc57df82…8bc9b0b` | same | PASS ×4 |
| C | fb58c0e2 (generation) | 13.0 (v13_0), macOS | unknown | `f74affb0e382…c00e108f` | `b8f5c0ac2bac…76c49f84` | `6e8bf8a88494…d5381c16` | PASS (committed) |

Full digests are in `DIGESTS.txt`. Raw kept files: the four Linux legs'
`txn_rtl.txt`, `tb_trace.txt` and `mem_rtl.hex` are **byte-identical** across
all (tree × iverilog) cells —
`txn_rtl.txt` sha256: prs `b4d04c5bbcb1f04494207d2d3ae92390ae62e56eb4410636e9677ddb5f4c4269`,
click `402febe4b66995759fa16b63a654ab9db6b11cde7dfb9188cfecdf4667d2c178`;
only `sim.out` (the compiled binary) differs, as expected for different
compilers. Kept logs lived outside tracked paths (`/tmp`) and were hashed,
not committed (3.7 MB + 7.9 MB each set).

## Findings

1. **iverilog 12.0-2build2 vs 13.0 (v13_0): no effect.** Transaction streams,
   traces and memory images are byte-identical; parsed digests equal; verdicts
   `exact=True` for both cases and the mutant control CONTROL-OK under both.
   The version discrepancy between the record and the pin is measured
   harmless for this comparison.
2. **Tree drift since the report: no effect** (cells 1–4 all equal), including
   the post-report RTL reverb1 commits (`e4dcf463`, `f430a4bb`, `36c27747`)
   — harness-visible behaviour did not move.
3. **numpy is digest-sensitive, iverilog is not.** Crossing the numpy 1.26 →
   2.0 boundary changes the click-512b stimulus quantization
   (`quantize_send_input` float32 path): digest `d75c9b89…` → `f617cc57…`.
   The prs case is numpy-stable (legacy `RandomState` stream). Verdicts stay
   `exact=True` because model and RTL shift together.
4. **The committed digest VALUES are generation-environment artifacts.**
   `f74affb0…` / `b8f5c0ac…` / `6e8bf8a8…` reproduce in **none** of the
   measured cells (2 iverilog × 2 trees × 6 numpy). The generation
   environment was macOS: the runner at the report's commit `fb58c0e2`
   hardcoded a `/var/folders/fb/…` temp dir (`/var/folders/` is
   macOS-specific; portability fix `9e925830` removed it). Its numpy is
   unknown; its iverilog was 13.0 (v13_0) — consistent with the record's
   `iverilog` field.

## Outcome (issue #720 acceptance)

Nearest the issue's outcome (b) — "logs identical, only the hash input
differs" — with the cause refined: the hash *input* differs by generation
platform/numpy, **not** by iverilog version. Outcome (c) ("digests reproduce
under 12.0, so the committed record is a 13.0 artifact") is measured-refuted
in its attribution: the committed digests are a *generation-environment*
(macOS) artifact, not a 13.0-on-Linux artifact; the 13.0-vs-pin difference
itself changes nothing.

Statuses (verification vocabulary): run under pin 12.0-2build2 **PASS**
(exit 0, both cases EXACT, mutant CONTROL-OK); run under 13.0 **PASS**;
12.0-vs-13.0 log diff **PASS** (byte-identical); reproduction of the
committed digest values under the pin **FAIL-to-reproduce** (measured,
attributed above); regeneration/annotation of the committed record
**NOT_RUN** (out of scope here; tracked as a follow-up); mutant control
CONTROL-OK in every cell (never passed).

## What this record does NOT claim

No change to any exactness verdict; no model-vs-reference, fidelity,
preset-support or musical claim; no FPGA/gf180mcu synthesis, PnR, signoff or
hardware claim. The committed `rtl-exactness.json` was not regenerated and
`signoff/t1-item9-inventory.json` was not edited.
