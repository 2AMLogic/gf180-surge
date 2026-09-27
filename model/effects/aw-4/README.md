# SXT-028k Airwindows "Logical" (streamed id 4) — frozen fixed-point model

Issue: [#63](https://github.com/2AMLogic/gf180-surge/issues/63) (SXT-028k) ·
Parent: #21 (SXT-028) · Epic: #3 · Plan §6 ·
Model: [`logical4_model.py`](logical4_model.py) ·
RTL: `rtl/effects/aw-4/` · Evidence: `reports/SXT-028k/EVIDENCE.md` ·
Licence decision: [`decision-records/0015`](../../../decision-records/0015-airwindows-logical-quoted-constants.md)

This directory is the FROZEN integer fixed-point model that the
**RTL-vs-model exactness** claim references. Three claims are kept separate
and none is inferred from another (`AGENTS.md`):

| Claim | Status here |
|---|---|
| (1) RTL matches this frozen model exactly | **PASS** — `reports/SXT-028k/rtl-exactness.json` |
| (2) this model reproduces the pinned Surge engine within [PROPOSED] budgets | **NOT_RUN** — no oracle host reachable; budgets are `[PROPOSED, not frozen]`, #12 owns the freeze |
| (3) the instrument sounds good | **not addressed** — listening pending (#9) |

## Algorithm identity (this leaf dispatches exactly one id)

`AirWindowsEffect` is the shared 12-slot adapter; `p[0]` is the **streamed**
Airwindows algorithm id, and `p[1..]` are that algorithm's own parameters.
`AirWinBaseClass_pluginRegistry.cpp` assigns ids with a monotonic `id++` over
a list that may only be appended to, which places:

```
0 AD Clip · 1 Block Party · 2 Butter Comp · 3 Compresaturator · 4 LOGICAL
```

**id 4 = `Logical4::Logical4`**, display order 50, group "Dynamics", display
name "Logical". Sibling ids are out of scope of this leaf and the model
refuses to be driven as anything else (`AW_STREAMED_ID = 4`,
`tests/test_sxt028k.py::test_algorithm_identity_is_id_4_only`). Logical
exposes five parameters, so the adapter maps

| Surge slot | Airwindows param | Name | Display |
|---|---|---|---|
| `p[1]` | A | Threshold | `A·40 − 20` dB |
| `p[2]` | B | Ratio | `B²·15 + 1` : 1 |
| `p[3]` | C | Attack | `C²·99 + 1` ms |
| `p[4]` | D | Makeup Gain | `D·40 − 20` dB |
| `p[5]` | E | Mix | `E·100` % |

and sets `p[6..11]` to `ct_none`. A and D are bipolar
(`isParameterBipolar`); none is integral, so all five take the adapter's
`OnePoleLag` path.

## What the algorithm is

Three cascaded, stereo-**linked** ButterComp compressor stages, each preceded
by its own Desk "Power Sag" nonlinearity, with a fractional-ratio crossfade
that selects how many stages are audible:

```
ratio         = clamp(sqrt(B²·15 + 1) − 1, 0, 2.99999)
ratioselector = floor(ratio)            # 0 / 1 / 2  ->  1 / 2 / 3 stages
ratio        -= ratioselector           # crossfade weight into the last stage
invRatio      = 1 − ratio               # sel 0 blends against the DRY sample
```

Per sample, in the pinned order: `sagA(L) sagA(R) compA(L) compA(R)`,
then `[sagB… compB…]` if `sel > 0`, then `[sagC… compC…]` if `sel > 1`, then
the crossfade, makeup gain, wet/dry mix, and `fpFlip = !fpFlip`. Inactive
stages' state stands still (reproduced, not approximated).

"Linked" is load-bearing: after each channel updates its own control bank,
it pulls the *other* channel's bank down to the mean if that one is higher
(`if (controlAposR > controlAposL) controlAposR = (controlAposR +
controlAposL) * 0.5`). Stereo behaviour is therefore part of the algorithm,
not a post-hoc pan.

## Pinned quirks reproduced deliberately

Each has a live negative control that must FAIL if the quirk is "fixed"
(`tools/aw4_negative_controls.py` NC-G, and the RTL mutants `NC_FIX_Q1` /
`NC_FIX_Q2`).

* **Q1 — the sag line mirror is one short.** `dL[gcount+499] = dL[gcount] =
  …` mirrors at +499, but `gcount` cycles over **500** values (499…0), and
  the tap is `dL[gcount + offsetA]`. So the tap is 2 samples old for 498 of
  every 500 samples and **3 samples old** at `gcount` 498 and 499. Frozen
  model reproduces the age exactly.
* **Q2 — stage C's right channel updates the LEFT positive target.** The
  third compressor's right-channel positive side runs `targetposCL *= …;
  targetposCL += …;` and then reads `1/targetposCR`, which nothing ever
  writes. `targetposCR` therefore stays at its constructor value 1.0 forever
  (so `calcpos ≡ 1.0` on that side) while `targetposCL` is updated twice per
  sample, once from each channel. The negative side is unaffected.
* **Q3 — stage C subtracts at `offsetB`.** `controlCL -= (cL[gcount+offsetB]
  / offsetC)`. At 48 kHz both offsets are 2, so the arithmetic is unchanged;
  recorded because it is not a typo the model may tidy.
* **Q4 — `divisorC` does not scale with attack.** `divisorC = 0.000857 /
  overallscale` (no `attackspeed`), while `remainderC = divisorC *
  attackspeed`. Stage C's decay/attack constants are not a complementary
  pair, unlike stages A and B.

## Frozen word formats

| Name | Format | Use |
|---|---|---|
| `a48` | 48-bit signed, **35 frac** (±4096, LSB 2⁻³⁵) | audio samples, `avg`/`nvg` registers, rectifier argument |
| `c96` | 96-bit signed, **53 frac** (±2³⁹·8, LSB 1.1e-16) | the 24 `control{A,B}{pos,neg}` registers, `calc{pos,neg}`, `totalmultiplier`, sag line words |
| `t64` | 64-bit signed, **43 frac** (±2²⁰, LSB 1.1e-13) | `target{pos,neg}`, `inputpos/neg`, `outputpos/neg`, per-stage `remainder`/`divisor` |
| `s96` | 96-bit signed, **54 frac** | the 6 sag control accumulators and derived `thickness`/`out`/`clamp` |
| `k31` | Q\*.31 signed in 64-bit containers | control-plane coefficients quantised once |
| ROM | 2 × 806 words Q1.31 | `sin` and `1 − cos` tables (derived, shared, read-only) |

Arithmetic (frozen): exact integer products in wide accumulators,
round-half-up `(x + 2^(f−1)) >>> f` with an arithmetic (floor) shift
mirroring SystemVerilog `>>>`, saturating stores with **counted**
saturations. No floating point in the audio path; double precision only at
control rate, quantised once at a declared boundary.

### Why the control plane is 96 bits (the load-bearing choice)

`a48`'s bound is *proved*, not measured: the comp output is hard-clipped to
±36, the makeup path divides by `compoutgain ≥ 0.1` and multiplies by
`outputgain ≤ 10`, so `|out| ≤ 3600 < 4096`.

The gain plane is the hard one. `target` is a convex combination of values
that are all ≥ the squared polarity floor `0.001² = 1e-6`, so
`calc = 1/target² ≤ 1e12` and the four-control sum is `≤ 4e12`. That floor
is **reachable** — a sustained one-polarity input drives the opposite
target to it within a few thousand samples (measured; finding F-028k-1 in
EVIDENCE) — so the range cannot be traded away. Meanwhile `totalmultiplier`
is routinely ~1e-2, so a 64-bit Q42.21 word would quantise it at 4.8e-7, a
4e-5 *relative* gain error that dominated every other error term in the
internal diagnostic. Thirteen decades of required dynamic range in one
linear fixed-point word is 96 bits. A log-domain or block-floating control
path is named as future work in the finding (routed to #12 as a cost
input), not implemented here.

`s96` has exactly one fraction bit more than `c96` so the pinned
`/offsetA` (= /2 at 48 kHz) is **exact**: the accumulator adds the `c96`
line word unshifted.

The reciprocal is two exact integer steps, identical in model and RTL:
`inv = round(2^86 / target)` (t64, i.e. `1/target` in Q\*.43, ≤ 8.8e18, so
the int64 guard is unreachable in the declared scope and is asserted zero),
then `calc = round(inv² >> 33)` (c96).

## Frozen control plane (model → RTL)

The five converged adapter parameters are quantised once into the word
vector `coefficient_words(ctrl)` (order is part of the frozen interface;
`tools/compare_rtl_model_aw4.py` and `rtl/effects/aw-4/tb_logical4.sv` index
it positionally):

```
ratioselector, inputgain_is_one, outputgain_is_one, wet_is_one,
inputgain_k, inv_compoutgain_k, outputgain_k, ratio_k, inv_ratio_k,
wet_k, dry_k, remainder_t[0..2], divisor_t[0..2]
```

The RTL owns everything audio-rate: both Power-Sag rings and their clamps,
the rectifier table lookup and interpolation, all detector recurrences, the
reciprocals, the control banks and their stereo link, the `fpFlip` phase,
the clip, the crossfade and the mix. **The RTL holds no numeric constant of
its own** beyond the two derived ROM images, so a constant cannot drift
between the two sides (DR-0015 §2).

One declared arithmetic deviation from the pinned source: `inputSample /
compoutgain` is a multiply against a control-plane `inv_compoutgain` word
quantised once to Q5.31 (relative error ≤ 2⁻³² of the coefficient). It is a
model-vs-reference contributor, never a model-vs-RTL one.

## Per-instance state and external memory

**No external writable memory.** The pinned `dL/bL/cL[1000]` arrays are
*allocation*, not reachable state: only taps of age 2 and 3 are ever read
(quirk Q1), so each line is a 4-word ring. `PinnedIndexSagLine` is a literal
1000-word transcription kept **only** for the equivalence proof
(`tests/test_sxt028k.py::test_compacted_sag_ring_matches_pinned_indexing`
runs both over two full 500-sample periods, including both wrap samples, and
requires bit-exact agreement). Claiming the 6000-word footprint would
misstate the cost; silently shrinking it without the proof would be a
different algorithm.

Exact per-instance state (`state_inventory()`, SXT-015 accounting):

| Field | Count | Bits each | Bits |
|---|---|---|---|
| `gcount` | 1 | 9 | 9 |
| `fpFlip` | 1 | 1 | 1 |
| `control{A,B}{pos,neg}` (c96) | 24 | 96 | 2304 |
| `target{pos,neg}` (t64) | 12 | 64 | 768 |
| `avg`/`nvg` (a48) | 12 | 48 | 576 |
| sag control accumulators (s96) | 6 | 96 | 576 |
| sag line rings (c96) | 24 | 96 | 2304 |
| **total** | | | **6538 bits = 818 B/instance** |

Shared read-only ROM: 2 × 806 × 33 b = 6650 B, shared by every concurrent
instance — never a substitute for writable state. External traffic: **0
reads, 0 writes per frame**. Flash is not involved and could not substitute
for writable state if it were.

**Two concurrent slots are two instances.** `LogicalState` is the complete
history of one instance; nothing is pooled, and the RTL indexes every state
array by `inst`. The corpus carries a real dual-instance carrier
(`Exquis MPE/Basses/Moogy Reese.fxp`, Logical on both `ains2` and
`global1`), which is the `dual-moogy` RTL case. The `NC_SHARED_STATE`
mutant pools them and must FAIL.

The cost *fit* verdict is `[PENDING-SXT-016]`; no number is invented here.
A recorded arithmetic-cost input for #12: each active stage needs two
128/64 reciprocals per sample per channel (12 per frame per instance at
`ratioselector = 2`) plus one table-interpolated `sin`/`1−cos` per stage per
channel.

## Tails

A dynamics processor emits **silence into silence** — an amplitude-ringout
gate would read "no tail" here and would happily pass a truncated render.
The tail that exists is the **gain-recovery** span: the four control banks
are exponential averages with per-sample retention `divisor[stage]`, so the
declared window is `5 / min(remainder[0..sel])` samples — five natural time
constants of the slowest ACTIVE bank. Measured per carrier in
`reports/SXT-028k/artifacts/tail-window.json` (696 … 6040 samples across the
carriers; `moogy-reese:slot1` is the longest at 189 blocks). Patch change
mid-tail keeps every history (`set_control`, the engine mutates `FxStorage`
in place); reset/panic restores the constructor state and discards the tail
(`reset()`). Both are RTL cases (`tail-resume`, `reset-mid`), and NC-D /
`NC_TAIL_KILL` must FAIL.

## Declared scope (fail-closed — every violation raises `Refuse`)

* **48 kHz only.** `overallscale = 48000/44100`, so
  `offsetA = offsetB = offsetC = (int)(2.42·overallscale) = 2`. Any other
  rate changes the sag tap geometry and is refused.
* **Static patch parameters.** The adapter's per-sub-block `OnePoleLag`
  (rate `0.004·4`, starting from 0 at load) is declared control plane at its
  converged target; the ~0.3 s post-load ramp is covered by the render
  settle policy, as in the sibling aw-49 leaf.
* **No parameter modulation into this leaf's FX params** — the extractor
  refuses any carrier whose modulation graph targets this slot, and records
  (separately) routes that target *other* slots.
* **Declared input envelope `|x| ≤ 64.0`** at the slot boundary; beyond it
  the `t64` target word is not provably in range and the model refuses
  rather than silently saturating.
* **`long double fpOld`.** The pinned source evaluates `inputSample * fpOld`
  in x87 80-bit on i386/x86-64 and in binary64/binary128 elsewhere. That is a
  REFERENCE-SIDE architecture dependence, recorded as a repeatability caveat
  in EVIDENCE; the frozen model quantises `fpOld`/`fpNew` once to Q1.31 and
  is architecture-independent.

## Files

* `logical4_model.py` — the frozen model, control plane, state inventory and
  buffer report (`python3 model/effects/aw-4/logical4_model.py` prints the
  JSON; artifact copy in `reports/SXT-028k/artifacts/state-cost.json`).
* `tables.py` — the frozen `sin` / `1 − cos` tables, their construction
  formula, digest, and the `.hex` emitter for the RTL ROMs.
* `float_transcription.py` — a second, double-precision transcription of the
  same pinned structure, used as a *structural* cross-check and as the
  substrate for the ADAPTED generic substitute in NC-C. **It is not an
  oracle and agreement with it establishes nothing** about reference
  fidelity; the test suite asserts the evidence never claims otherwise.
* `../fx_inputs/aw-4-*.json` — fail-closed extraction records (census blob
  re-verified, `graphs.jsonl` cross-check, FX-modulation screen, landed-class
  screen; `complete_wet_render_possible` is `false` for every carrier).

## Reproduce

```sh
python3 model/effects/aw-4/logical4_model.py        # state + buffer report
python3 model/effects/aw-4/tables.py                # table self-test + .hex
python3 tools/extract_aw4_inputs.py                 # fail-closed extraction
python3 tools/aw4_evidence_artifacts.py             # state-cost / tail-window / oracle-status
python3 tools/compare_rtl_model_aw4.py --write-report   # RTL-vs-model exactness
python3 tools/aw4_negative_controls.py --write-report   # model-side controls
python3 tools/aw4_evidence_artifacts.py --check     # refuse a stale artifact
python3 -m pytest -q tests/test_sxt028k.py
# oracle host only (currently NOT_RUN):
ORACLE_SURGE_DIR=... python3 tools/extract_aw4_inputs.py --mode oracle
```
