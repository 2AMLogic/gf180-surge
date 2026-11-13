# Voice negative-control regeneration — the two drifted `tb_voice.sv` copies

Issue: #622 (carries the bounded finding #620 declared) · Branch:
`feature/issue-622` · Date: 2026-11-13 · Base: `origin/main` `d5ac9f6`

Host: `loom-worker-3` (linux x86_64). Icarus Verilog 13.0 (stable) `v13_0`.
CPython 3.12 in a throwaway venv holding the committed pins
(`requirements-ci.txt`, pytest 9.1.1; and `signoff/requirements.txt`,
`klayout-tools==0.8.0`). No host tool was installed or changed. Nothing in
this record's chain — `tools/make_rtl_mutants.py`, `model/voice/run_model.py`,
`model/voice/run_vel_model.py`, `tools/compare_rtl_model.py` — imports NumPy,
so no NumPy version is stamped here (see `docs/numpy-stamp-inventory.md`).

## Claim discipline

This record establishes exactly two things:

1. `rtl/voice/voice_broken_mutant.sv` and `rtl/voice/voice_uni_mutant.sv` are
   each again `rtl/voice/tb_voice.sv` plus **one** targeted replacement, with
   the drift gate (`tools/make_rtl_mutants.py --check`) reporting zero declared
   known-drift entries.
2. On a stimulus where the unmutated base is RTL-vs-model **exact**, each
   regenerated control **FAILs** that same comparison — so each control is live
   and its FAIL is attributable to its own targeted line.

It establishes **no** model-vs-pinned-Surge fidelity claim, **no** preset
support or musical-quality claim, and **no** FPGA/gf180mcu synthesis, timing,
or hardware-playback claim. The RTL here is an iverilog-simulated behavioral
schedule.

## What changed and why

`tools/make_rtl_mutants.py` (#620) declares every committed copy-style mutant
as *base + optional banner + exact replacements* and gates the committed bytes
with `--check`. Two entries did not reproduce that way: on top of its targeted
mutation, each of the two voice mutants carried **three hunks reverting the
base's SXT-036 constructor gain-anchor logic** (the `if (cw[0][4]) prev_gain[s]
= 32'(cw[37]);` branch plus two control-word comments). #620 declared that
drift in a `"stale"` field rather than fixing it, because new bytes move an
attested signoff record.

This change removes the two `"stale"`/`"drift"` declarations and the now-unused
`SXT036_STALE` table, regenerates both files, re-derives the T1 item 9
attestation for their new content hashes, and re-runs both controls.

### No banner

Neither regenerated file gains an NC banner. With no banner the diff against
the base is exactly the one targeted line, which is what the committed SXT-034
and SXT-022 evidence already describes ("single-line"). A banner would be extra
attested bytes that no check needs.

```
$ diff rtl/voice/tb_voice.sv rtl/voice/voice_broken_mutant.sv
96c96
<     r = (p + (64'sd1 << 20)) >>> 21;
---
>     r = (p + (64'sd1 << 19)) >>> 21;

$ diff rtl/voice/tb_voice.sv rtl/voice/voice_uni_mutant.sv
602c602
<     for (u = 0; u < uni_n; u++) begin
---
>     for (u = 0; u < 1; u++) begin

$ python3 tools/make_rtl_mutants.py --check
16/16 committed mutants reproduce from their base (0 declared known-drift)
exit code: 0
```

| file | sha256 before (`d5ac9f6`) | sha256 after |
|---|---|---|
| `rtl/voice/voice_broken_mutant.sv` | `2c133c81…fdee09` | `bb82679e…879251` |
| `rtl/voice/voice_uni_mutant.sv`    | `7b6b5a15…e58ac0` | `6cca0988…4fbbf6` |

`rtl/voice/tb_voice.sv` is unmodified (`4895bb87…b9d6d6`). Full transcript:
`artifacts/regeneration-transcript.txt`.

## Fixtures

Two run directories, both produced in-tree and deterministically; neither is
committed (they are regenerable from the commands below).

| id | command | blocks / samples | unison | slot-blocks with `flags` bit 4 set |
|---|---|---|---|---|
| **uni2-smoke** | `python3 model/voice/run_model.py --inputs model/voice/attacky_uni2_inputs.json --sequence model/voice/sequences/sxt034-smoke-v1.json --out-dir RUN` | 525 / 16,800 | **2** | **0** of 394 active |
| **vel-overlap** | `python3 model/voice/run_vel_model.py --sequence sxt036-vel-overlap-v1 --out-dir RUN` | 3,225 / 103,200 | 1 | **5** of 2,935 active |

**uni2-smoke is the discriminating fixture for both controls**: unison 2 makes
the uni mutant's `u < uni_n` → `u < 1` collapse observable, and the rounding
mutant is active on every multiply. **vel-overlap is the SXT-036 coverage
fixture**: it is the only one of the two that actually sets `flags` bit 4, so it
exercises the restored gain-anchor branch. Bit-4 counts were derived by reading
each run dir's `rtl/ctrl.hex` at the testbench's declared layout
(`BLOCK_STRIDE = 4 + NSLOTS*CWORDS`, word 0 of each slot = `flags`).

Comparator: `python3 tools/compare_rtl_model.py --run-dir RUN --tb <tb> --out
<json>`. Verdicts are integer-equality RTL-vs-model exactness; any mismatch is
FAIL.

## Results

### uni2-smoke (unison 2, SXT-036 branch not exercised)

| testbench | verdict | mismatches | artifact |
|---|---|---|---|
| `rtl/voice/tb_voice.sv` (unmutated base) | **PASS** | 0 (101 checkpoints / 4,141 fields / 6,464 oscout / 16,800 mono) | `artifacts/uni2-smoke-base.json` |
| `voice_broken_mutant.sv` (regenerated) | **FAIL** | 99 | `artifacts/uni2-smoke-broken-mutant.json` |
| `voice_uni_mutant.sv` (regenerated) | **FAIL** | 105 | `artifacts/uni2-smoke-uni-mutant.json` |
| `voice_broken_mutant.sv` as committed at `d5ac9f6` | FAIL | 99 | `artifacts/uni2-smoke-broken-mutant-PRE.json` |
| `voice_uni_mutant.sv` as committed at `d5ac9f6` | FAIL | 105 | `artifacts/uni2-smoke-uni-mutant-PRE.json` |

The base is exact on the same stimulus both controls fail on, so each FAIL is
the mutation, not the harness. The before/after mismatch counts are identical
because this fixture never sets bit 4 — on it the three stale hunks were inert,
exactly as `tb_voice.sv`'s own comment predicted.

### vel-overlap (unison 1, SXT-036 branch exercised on 5 slot-blocks)

| testbench | verdict | mismatches | artifact |
|---|---|---|---|
| `rtl/voice/tb_voice.sv` (unmutated base) | **PASS** | 0 (279 / 9,765 / 17,856 / 103,200) | `artifacts/vel-overlap-base.json` |
| `voice_broken_mutant.sv` (regenerated) | **FAIL** | 98 | `artifacts/vel-overlap-broken-mutant.json` |
| `voice_uni_mutant.sv` (regenerated) | PASS | 0 | `artifacts/vel-overlap-uni-mutant.json` |
| `voice_broken_mutant.sv` as committed at `d5ac9f6` | FAIL | 100 | `artifacts/vel-overlap-broken-mutant-PRE.json` |
| `voice_uni_mutant.sv` as committed at `d5ac9f6` | FAIL | 41 | `artifacts/vel-overlap-uni-mutant-PRE.json` |

**The regenerated uni mutant's PASS here is not a dead control and does not
trigger this issue's stop condition.** This fixture is unison 1, so `u < uni_n`
and `u < 1` are the same loop and the mutant is textually different but
behaviorally identical — a non-discriminating stimulus, not a control that
stopped failing. Its discriminating fixture is uni2-smoke above, where it FAILs
with 105 mismatches. `tools/compare_rtl_model.py`'s own docstring states the
same precondition ("must FAIL … on a uni>=1 / uni>1 fixture respectively").

**The row that justified this issue** is the last one. At `d5ac9f6` the uni
control FAILed on this fixture with 41 mismatches *entirely because of the
stale SXT-036 revert* — its targeted mutation is inert at unison 1. A reader
taking that FAIL as evidence that the unison machinery is exactness-checked
would have been reading a different defect. The regeneration removes that
misattribution: the control now fails only where its own mutation is live. The
rounding control's 100 → 98 is the same effect at smaller scale (two of its
mismatches were the stale hunks, not the rounding bias).

## Failure control

The gate must reject a file that drifts from *base + declared mutations*, and
the control must still fail for its targeted reason.

```
$ <scratch copy of the tree; revert ONE restored SXT-036 hunk in
   rtl/voice/voice_broken_mutant.sv>
$ python3 tools/make_rtl_mutants.py --check
STALE: rtl/voice/voice_broken_mutant.sv (committed bytes differ from base +
  declared mutations; regenerate with python3 tools/make_rtl_mutants.py)
15/16 committed mutants reproduce from their base (0 declared known-drift)
exit code: 1
```

**PASS — the control demonstrably fails the check it targets.** The healthy
scratch tree exits 0 beforehand, so the non-zero exit is the reverted hunk.

Comparator leg of the same control, on the same scratch copy:

| run dir | verdict | mismatches | vs the minimal mutant | artifact |
|---|---|---|---|---|
| uni2-smoke | FAIL | 99 | same (99) — the hunk is inert with no bit 4 | `artifacts/uni2-smoke-failure-control.json` |
| vel-overlap | FAIL | 100 | **+2** over 98 — the hunk is itself detectable | `artifacts/vel-overlap-failure-control.json` |

On uni2-smoke the FAIL is attributable to the targeted mutation alone; on
vel-overlap the reverted hunk adds its own mismatches on top. That is the
contamination this issue removes, measured.

Also live, in `tests/test_rtl_mutant_table.py`: the pre-existing failure
controls (an edited base line, a hand-edited mutant, a lost anchor, a
duplicated anchor) all still pass, and two new tests pin the regenerated
property — each voice mutant is byte-exactly base + its one replacement, and
both now carry the base's SXT-036 gain-anchor text.

## T1 item 9 re-attestation

Before: `klt signoff --attest 9 --inventory signoff/t1-item9-inventory.json
--check signoff/t1-item9-attestation.json` exited **3** (`status: drifted`),
naming exactly the two content hashes above and nothing else; `fresh_status:
pass`.

After re-deriving the envelope with the pinned `klt 0.8.0`
(`--attest 9 --inventory … -o signoff/t1-item9-attestation.json`), the same
`--check` exits **0** (`status: match`, `fresh_status: pass`). The envelope
diff is exactly those two `content_hash` values and nothing else.

`cold_start` in the inventory is `local_only`: `--check` skips it and carries
the committed outcome, while *producing* the envelope runs it
(`python3 -m pytest -q -p no:cacheprovider tests`). That run is the source of
this envelope's `cold_start: pass`; `klt` records the check's exit status, not
pytest's own counts, so only `exit 0` is attested here.

Recorded for honesty, since it cost one attestation attempt: an earlier
producing run exited 3 on `cold_start` with three failures. Two (both in
`tests/test_numpy_stamp_inventory.py`, one cause) were real and are fixed here — this record and its transcript originally quoted
`requirements-ci.txt`'s NumPy version, which
`tests/test_numpy_stamp_inventory.py` correctly flagged as a committed stamp
missing from `docs/numpy-stamp-inventory.md`; the version was dropped rather
than inventoried, because nothing in this chain imports NumPy. The third,
`tests/test_negative_controls_live.py::…[coverage_negative_controls.py]`
(`control_rng_exclusion` reported unhealthy), did **not** reproduce: it passes
in isolation on this branch, passes in isolation on a pristine `d5ac9f6`
export, and passed in the full run that produced the committed envelope. It is
recorded here as an observed transient on a loaded shared host, not as a
finding about this change — and not as a pass that was argued away: the
envelope above rests on a full run in which it passed.

`signoff/block-manifest.signoff.json` is **unchanged**: the item 9 summary text
does not reference these hashes, and a fresh `klt signoff --manifest` render
byte-compares equal to the committed verdict of record (the signoff workflow's
first job).

## Coverage, stated separately from agreement

- **The SXT-036 branch is not exercised by the uni2-smoke verdicts.** That
  fixture never sets `flags` bit 4 (measured: 0 of 394 active slot-blocks), so
  both controls there take the static `cfg[19]` anchor. The branch *is*
  exercised on vel-overlap (5 slot-blocks), where the base is exact and the
  rounding control fails.
- **No unison fixture that also sets bit 4 was run**, so no single run
  exercises both the restored branch and the uni mutant's targeted collapse.
  Constructing one would mean a new input fixture; it is not needed for either
  control's verdict and was left out of scope.
- These are RTL-vs-frozen-model exactness verdicts only. Nothing here speaks to
  model-vs-pinned-Surge agreement.

## What remains unproved

- That either mutation is the *only* defect its comparator would catch — a
  negative control shows a check is live, never that it is complete.
- Any fidelity, preset-support, or synthesis claim (see Claim discipline).
- The existing records under `reports/SXT-034/`, `reports/sxt-022/`,
  `reports/sxt-026a/` and `reports/halfband-republication/` describe runs of
  the **pre-#622** bytes and were deliberately **not** edited. They remain
  historical; the mismatch counts quoted there belong to the drifted copies.

## Reproduce

```
python3 tools/make_rtl_mutants.py --check

python3 model/voice/run_model.py \
  --inputs model/voice/attacky_uni2_inputs.json \
  --sequence model/voice/sequences/sxt034-smoke-v1.json --out-dir RUN_A
python3 model/voice/run_vel_model.py --sequence sxt036-vel-overlap-v1 \
  --out-dir RUN_B

for tb in rtl/voice/tb_voice.sv rtl/voice/voice_broken_mutant.sv \
          rtl/voice/voice_uni_mutant.sv; do
  python3 tools/compare_rtl_model.py --run-dir RUN_A --tb "$tb"
  python3 tools/compare_rtl_model.py --run-dir RUN_B --tb "$tb"
done

python3 -m pytest -q tests/test_rtl_mutant_table.py \
                     tests/test_halfband_d2_voice.py \
                     tests/test_byte_frozen_sources.py

pip install -r signoff/requirements.txt   # klayout-tools==0.8.0, in a venv
klt signoff --attest 9 --inventory signoff/t1-item9-inventory.json \
            --check signoff/t1-item9-attestation.json
```
