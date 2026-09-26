# Halfband D2 branch-assignment correction — SXT-022 decimator (issue #123)

Issue: [#123](https://github.com/2AMLogic/gf180-surge/issues/123) (raised as
finding **F-028e-3** by #57 / SXT-028e, reported there, not fixed there).
Date: 2026-09-26.

**Outcome.** `model/voice/voice_model.py::HalfbandD2` — the shared scene
decimator modelling `sst::filters::HalfRate::HalfRateFilter(M = 6,
steep)::process_block_D2` — reconstructed its decimated output from the
**wrong** allpass branch at each output index. The pinned kernel computes
`out[n] = (B[2n] + A[2n+1]) * 0.5`; the model (and every RTL copy of it)
computed `out[n] = (A[2n] + B[2n+1]) * 0.5`. That assignment removes the
decimator's stopband entirely: **0.43 dB** of rejection at 0.30 of the input
rate where the pinned ordering gives **102.8 dB**. Model and RTL are corrected
together; RTL-vs-model integer equality is re-established.

## Claim discipline (AGENTS.md)

This record advances exactly two claims and no others:

1. **The frozen model now matches the pinned kernel's branch assignment**, by
   executing the pinned kernel and scoring both candidate reconstructions
   against its output (§2).
2. **RTL == frozen model, exact (integer equality)**, after the coordinated
   model+RTL change, on the SXT-022 fixture set and the SXT-026a smoke
   fixture (§5).

It establishes **no** fidelity verdict (the SXT-022/SXT-026a budgets are
`[PROPOSED-TO-BE-FROZEN-AT-PILOT]`, owned by SXT-017 / [#12](https://github.com/2AMLogic/gf180-surge/issues/12)),
**no** preset-support claim, **no** musical-quality claim, and **no**
FPGA/gf180mcu synthesis, timing, or hardware-playback claim. The
model-vs-reference numbers in §3 are *numbers*, recorded for #12; not one of
them is a verdict this record grants.

## 1. What the pinned source actually says (issue step 1) — **CONFIRMED**

Read directly at the manifest-pinned submodule
`libs/sst/sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6`
(`oracle/manifest.json`), file `include/sst/filters/HalfRateFilter.h`:

| Line | Pinned code | Consequence |
|---|---|---|
| 781 | `va[i] = SIMD_MM(set_ps)(cB[i], cA[i], cB[i], cA[i]);` | `_mm_set_ps(e3,e2,e1,e0)` puts its **last** argument in lane 0 ⇒ **lane 0/2 = cA, lane 1/3 = cB** |
| 182-186 | `o[k] = shuffle_ps(L, R, SHUFFLE(0,0,0,0))` … | lanes 0/1 = L, lanes 2/3 = R ⇒ lane 0 = L·A, lane 1 = L·B |
| 347 | `tL0 = shuffle_ps(o[k], o[k], SHUFFLE(1,1,1,1))` | broadcast of lane 1 = the **B** cascade at the **even** sample `2n` |
| 349 | `aL = SIMD_MM(add_ss)(tL0, o[k + 1])` | adds lane 0 of the **odd** sample = the **A** cascade at `2n+1` |
| 384 | `L[k >> 3] = mul_ps(…, half)` | the `* 0.5` |

⇒ `out[n] = (B[2n] + A[2n+1]) * 0.5`, and the original algorithm comment the
header preserves (`const double output = (filter_a.process(input) + oldout) *
0.5; oldout = filter_b.process(input);`) agrees: at the sampled step the `A`
branch takes the *later* input.

**Caveat that makes reading alone insufficient, and is why §2 exists.** The
header's own PROSE disagrees with its own CODE. Lines 192-193 say the
coefficients are loaded "in order B A B A in SIMD space" and lines 210-211
say `o_i: AllpassCascade_B(L_i), AllpassCascade_A(L_i), …` (lane 0 = B),
concluding at line 333 `L[i] = A_L[2*i] + B_L[2*i+1]` — exactly the ordering
the model carried. The comment's author flags the confusion in-line: *"which
looks a lot to me like I have a bit flip somewhere wrong in my comments"*
(line 329). The pre-#123 model docstring states that prose as fact. So the
finding is not "someone misread the header"; it is "the header contradicts
itself and the model followed the wrong half."

## 2. Settling it by EXECUTION, not by reading — **PASS**

`oracle/sxt022/build_halfband_probe.sh` checks the pinned submodules out
**outside** this repository (`~/.cache/sxt022-oracle`, refuses any path inside
the repo, refuses on SHA drift or a dirty checkout) and compiles
`oracle/sxt022/halfband_d2_probe.cpp` — original Apache-2.0 work, an API
client that copies no GPL code — against the pinned headers. The binary is a
GPL-3.0-or-later combined work, lives only in that external directory, and is
never committed or distributed. This is the DR-0009 / DR-0010 pinned-kernel
harness shape re-used unchanged; it raises no new licensing question and
adds no new decision record. Build provenance:
`artifacts/probe-build-provenance.txt`.

`tools/halfband_d2_ordering_probe.py` runs that binary over seven cases
(sines at 0.05/0.15/0.25/0.30/0.45 of the input rate, a seeded LCG noise
burst, an impulse; 256 input words each, fresh filter per case) and scores
both candidate scalar reconstructions against the pinned output:

| candidate | worst error over all 7 cases, relative to input full scale |
|---|---|
| `a_even` = `(A[2n] + B[2n+1])·0.5` (pre-#123 model + prose) | **1.0955** |
| `b_even` = `(B[2n] + A[2n+1])·0.5` (pinned code) | **4.80e-07** |

`b_even` agrees with the pinned kernel at float32 rounding; `a_even` is wrong
by more than full scale. Verdict **PASS**, `matching_ordering: b_even`,
artifact `artifacts/pinned-kernel-ordering-probe.json`.

Frequency response of the two reconstructions (float64, the same allpass
recursion and the same pinned coefficients, 16,384 samples after a 2,048-sample
warm-up), reproducing the issue body's table exactly:

| f (of input rate) | `a_even` output RMS | `b_even` output RMS |
|---|---|---|
| 0.05 | −3.45 dB | **−3.01 dB** |
| 0.15 | −7.63 dB | **−3.01 dB** |
| 0.25 | −6.02 dB | −6.02 dB |
| 0.30 | −3.44 dB | **−110.00 dB** |
| 0.45 | −13.21 dB | **−112.94 dB** |

(input RMS −3.01 dB; 0.25 is the output Nyquist, i.e. the −3 dB crossover.)

The frozen Q10.21 class measures 102.8 dB / 98.7 dB of rejection at f = 0.30 /
0.45 — the fixed-point noise floor, not the filter, sets that number.

## 3. Both orderings against the committed fixtures, BEFORE the code change (issue step 2) — **DONE**

The issue's stop/escalate clause forbids changing the model without this.
Method: `HalfbandD2.process` was monkeypatched in-process to each ordering and
**each leaf's own committed runner was re-run**; nothing in the repository was
edited for this measurement. The `a_even` leg reproduces **every** committed
model render byte-identically and every committed budget JSON's numbers, which
is what makes the `b_even` leg a like-for-like delta. Full record, including
per-case render sha256s and complete metric blocks:
`artifacts/before-after-fixtures.json`.

Comparator: `tools/compare_audio_reference.py` at the base commit, dry bus,
no normalization, no time-warping (AGENTS.md comparison rules).

| Leaf / case | reference render | max\|Δ\| LSB | RMS Δ dBFS | spectral corr | overall verdict |
|---|---|---|---|---|---|
| **SXT-022** `seq-notes-coverage-v1` | committed | 4760 → **4760** | −30.138 → **−30.139** | 0.9753 → **0.9791** | FAIL → FAIL |
| **SXT-022** `seq-notes-repeated-v1` | committed | 2321 → **2328** | −33.327 → **−33.327** | 0.9875 → **0.9921** | FAIL → FAIL |
| **SXT-022** `seq-modwheel-v1` | committed | 12677 → **12686** | −32.284 → **−32.283** | 0.9784 → **0.9802** | FAIL → FAIL |
| **SXT-026a** canonical bells (`sxt025-accept-v1`) | SXT-042 projection | 16721 → **16740** | −27.855 → **−27.851** | 0.9207 → **0.9212** | FAIL → FAIL |
| **SXT-026a** smoke bells | *(not committed)* | — | — | — | render moves; NOT_RUN |
| **SXT-042** keytrack, canonical bells | committed | 16721 → **16740** | −27.855 → **−27.851** | 0.9207 → **0.9212** | FAIL → FAIL |
| **SXT-032** LFO, `seq-notes-coverage-v1` | committed | 17998 → **18030** | −29.900 → **−29.897** | 0.9837 → **0.9884** | FAIL → FAIL |
| **SXT-035** modwheel, `seq-modwheel-v1` | committed | 65534 → **65534** | −18.040 → **−18.039** | 0.9870 → **0.9875** | FAIL → FAIL |
| **SXT-033** Classic `edges`, `seq-notes-repeated-v1` | committed | 54 → **33** | −79.427 → **−79.649** | 0.9728 → **0.9830** | **FAIL → PASS** |
| **SXT-040** Sine `badnews`, `seq-notes-repeated-v1` | committed | 62 → **62** | −71.043 → **−71.088** | 0.9456 → **0.9471** | FAIL → FAIL |
| **SXT-026** Wavetable `kick-wtfix` | committed | — | — | — | **NOT_RUN** (see §4) |

Spectral correlation improves in **every** measured case. One budget row
crosses a declared bound on the voice leaf (SXT-022 `seq-modwheel-v1`
spectral corr 0.9784 → 0.9802, crossing the proposed 0.98 floor from MISS to
PASS) without moving that case's overall verdict, and one leaf's **overall
verdict moves**: SXT-033 Classic `edges/seq-notes-repeated-v1` goes from
`FAIL against proposed budgets` to `PASS (PENDING-FREEZE)`.

## 4. What was NOT measured, and why

| Item | Status | Reason |
|---|---|---|
| SXT-026 Wavetable model render | **NOT_RUN** | `model/oscillators/wavetable/run_model.py` needs the pinned engine's external `resources/data/wavetables` asset root (`Basic/Triangle.wt`), unavailable on this host. The shared class **is** on its output path (`wt_model.py:666`), so that render *will* move; by how much is unmeasured. |
| SXT-026a smoke-bells model-vs-reference | **NOT_RUN** | no reference render for `leaf48-smoke-bells-v1` is committed and no oracle host is available here; the render sha is recorded as moved, without a metric. |
| Re-rendering / republishing each affected leaf's committed artifacts | **out of scope, routed to follow-up** | see §7. |
| Whether the corrected decimator changes any *listening* judgement | **NOT_RUN** | no listening record exists; numeric tests never establish it (AGENTS.md). |

## 5. RTL-vs-model exactness after the coordinated change (issue steps 3-4) — **PASS**

Both sides were changed in the same commit, because neither is generated from
the other. `tools/compare_rtl_model.py`, `iverilog -g2012`, integer equality
at every declared checkpoint:

| fixture | verdict | checkpoints | fields | osc-out samples | mono samples | mismatches |
|---|---|---|---|---|---|---|
| `seq-notes-coverage-v1` | **PASS** | 467 | 16,345 | 29,888 | 273,600 | **0** |
| `seq-notes-repeated-v1` | **PASS** | 403 | 14,105 | 25,792 | 196,800 | **0** |
| `seq-modwheel-v1` | **PASS** | 75 | 2,625 | 4,800 | 182,400 | **0** |
| `leaf48-smoke-bells-v1` (SXT-026a) | **PASS** | 193 | 6,755 | 12,352 | 3,904 | **0** |
| `sxt025-accept-v1` canonical bells (SXT-026a) | **PASS** | 23,255 | 813,925 | 1,488,320 | 840,000 | **0** |

Artifacts: `artifacts/exactness-*.json`. (These counts differ from the
committed `reports/sxt-022/artifacts/exactness-*.json` in the `fields` column
— e.g. 16,345 vs 12,609 — because SXT-026a/SXT-034 added checkpoint fields
after those artifacts were published. That drift predates this change; it is
not caused by it, and nothing here re-publishes those artifacts.)

Whole-leaf suites re-run at HEAD after the coordinated change:
`tests/test_sxt033_classic.py` + `tests/test_sxt040_sine.py` — **22 passed**,
including both leaves' own RTL mutant controls (which must FAIL, and do).

### RTL sites changed

The decimator is coded independently in each testbench, so all copies had to
move together or their leaves would have gone red:

* `rtl/voice/tb_voice.sv` (SXT-022 / SXT-026a / SXT-034)
* `rtl/oscillators/classic/tb_classic.sv` (SXT-033)
* `rtl/oscillators/sine/tb_sine.sv` (SXT-040)
* the three derived mutants `voice_broken_mutant.sv`, `voice_uni_mutant.sv`,
  `classic_broken_mutant.sv`, `sine_broken_mutant.sv` — **required**: each is
  a declared *single-line* control, and leaving the old ordering in them would
  have silently made them two-mutation files, breaking the very transcripts
  (`reports/sxt-022/artifacts/negative-control.txt`,
  `reports/SXT-034/artifacts/negative-control.txt`) that quote their one-hunk
  `diff`. Those diffs are one hunk again after this change.

`rtl/voice/tb_kt.sv`, `tb_lfo.sv`, `tb_mw.sv` and
`rtl/oscillators/wavetable/*.sv` carry **no** decimator and were not touched.

## 6. Negative controls (issue step 3) — **both FAIL the check they target**

Transcript: `artifacts/negative-control.txt`.

* **NC-1, RTL:** `rtl/voice/voice_halfband_order_mutant.sv` = `tb_voice.sv`
  with **only** the branch order reverted (one line; a four-line banner
  identifies it). Against the same model trace that the unmutated testbench
  passes with 0 mismatches, it **FAILs** with 41 mismatches from block 0,
  exit 1. `tests/test_halfband_d2_voice.py` asserts both legs and asserts the
  mutant is still a one-line revert.
* **NC-2, model:** the pre-#123 `a_even` reconstruction rejects **0.43 dB** at
  f = 0.30 and **10.20 dB** at f = 0.45, where the automated stopband
  assertion requires ≥ 80 dB — it **FAILs**, as a live control must. Its
  second face: it also sags the passband by 4.62 dB at f = 0.15 where the
  pinned ordering is flat to 0.00 dB.

## 7. Findings and hand-offs

**F-123-1 → SXT-017 / [#12](https://github.com/2AMLogic/gf180-surge/issues/12)
(the issue's step 4, and its main result).** A total loss of the scene
decimator's stopband rejection — 102 dB of attenuation replaced by 0.4 dB —
moved the SXT-022 voice leaf's headline metrics by **0 to 9 LSB out of 2,321
to 12,677**, moved its RMS residual by **≤ 0.001 dB**, and changed **no**
overall verdict on any of its three sequences. The existing budgets did absorb
it. This is a direct, measured statement about the checks, not about the
fixtures: *the SXT-022/SXT-026a acceptance metrics cannot see a destroyed
halfband decimator.* Two contributing reasons are visible in the data and are
offered as leads, not conclusions: (a) the fixture material is band-limited
enough at 96 kHz that little energy sits in the decimator's stopband, so the
aliasing the bug admits is small; (b) `max_abs_diff_lsb` and broadband
`spectral_corr` are both dominated by the transient quantization error the
leaf already reports, which is 3-4 orders of magnitude larger than this
defect's contribution. The one metric that did move consistently — spectral
correlation improved on **every** case — is the one that is frequency-aware.
A budget freeze that wants to be able to see this class of defect needs a
band-limited or stopband-specific term, not a tighter broadband bound. **No
budget is changed here**; per AGENTS.md that decision belongs to #12.

**F-123-2 → SXT-033 / [#71](https://github.com/2AMLogic/gf180-surge/issues/71).**
The Classic oscillator leaf's `edges / seq-notes-repeated-v1` row moves from
`FAIL against proposed budgets` to `PASS (PENDING-FREEZE)` (spectral corr
0.9728 → 0.9830, max\|Δ\| 54 → 33 LSB). That is a landed leaf's recorded
verdict improving under a correctness fix. It is recorded here and **not**
written into `reports/SXT-033/`: the committed artifact there is a render, and
re-rendering it is the artifact-republication work in F-123-3.

**F-123-3 → follow-up [#145](https://github.com/2AMLogic/gf180-surge/issues/145) (filed).** Every leaf in §3 now carries committed
model renders and budget JSONs that no longer reproduce at HEAD. Exactly one
is refreshed here, because a committed test asserts it byte-for-byte:
`reports/sxt-026a/artifacts/model-smoke-bells-dry.wav`
(`tests/test_sxt042_keytrack.py::test_runner_render_is_byte_identical_to_the_landed_model`;
sha256 `2e357def…`, regenerated by `model/voice/run_model.py` and verified
byte-identical to `model/voice/run_kt_model.py`'s render of the same
sequence). Its sibling `artifacts/audio-smoke-bells-dry.json` is **left
untouched and is therefore STALE**: it is a model-vs-reference metric whose
reference render for `leaf48-smoke-bells-v1` is not committed and cannot be
produced on this host (§4). That inconsistency inside
`reports/sxt-026a/artifacts/` is declared here rather than papered over.

All the others are **not** regenerated in this change, deliberately and for
two reasons. First,
`reports/sxt-022/artifacts/audio-*.json` (and the equivalents under SXT-026a,
SXT-032, SXT-033, SXT-034, SXT-035, SXT-026) are *already* stale for an
unrelated, already-filed reason — the `rms_diff_dbfs` polarity correction
audited in `reports/tooling-rms-polarity-audit/` and routed to
[#97](https://github.com/2AMLogic/gf180-surge/issues/97) — so regenerating
them here would silently absorb another issue's finding into this one. That
audit set the precedent explicitly: *"no leaf's committed EVIDENCE.md is
touched here."* Second, a regeneration pass would be partial by construction
on this host: SXT-026's wavetable renders cannot be produced without the
external asset root (§4). [#145](https://github.com/2AMLogic/gf180-surge/issues/145) therefore
carries the republication, the two unresolved RTL questions (whether the
wavetable RTL needs a decimator at all; what to do with the pre-SXT-034
`voice_wrongparam_mutant.sv` snapshot), and the sequencing note that it
should land after or with #97.

## 8. Reproduce

```bash
./oracle/sxt022/build_halfband_probe.sh                   # external, GPL binary
python3 tools/halfband_d2_ordering_probe.py \
    --json reports/halfband-branch-order/artifacts/pinned-kernel-ordering-probe.json

python3 -m pytest tests/test_halfband_d2_voice.py -q      # 20 passed (iverilog needed for 2)

for s in seq-notes-coverage-v1 seq-notes-repeated-v1 seq-modwheel-v1; do
  python3 model/voice/run_model.py --sequence $s --out-dir /tmp/hb/$s
  python3 tools/compare_rtl_model.py --run-dir /tmp/hb/$s \
      --out reports/halfband-branch-order/artifacts/exactness-$s.json
done

python3 model/voice/run_model.py --sequence leaf48-smoke-bells-v1 \
    --inputs model/voice/bells_inputs.json --out-dir /tmp/hb/smoke
python3 tools/compare_rtl_model.py --run-dir /tmp/hb/smoke \
    --tb rtl/voice/voice_halfband_order_mutant.sv --out /tmp/hb/nc.json   # MUST exit 1
```

## 9. Licensing / provenance

`oracle/sxt022/halfband_d2_probe.cpp`, `oracle/sxt022/build_halfband_probe.sh`,
`tools/halfband_d2_ordering_probe.py`, `tests/test_halfband_d2_voice.py` and
this record are original to this repository (Apache-2.0, `LICENSE`). No Surge
or SST source, table, preset or asset is copied here; the pinned GPL headers
are consumed at build time only and the resulting binary stays outside the
repository. The twelve halfband allpass coefficients the model uses were
already adopted under `decision-records/0002-halfband-coefficients.md`; this
change adopts nothing new. Method follows DR-0009 / DR-0010.

## 10. Explicitly NOT established by this work

* Any fidelity verdict for SXT-022, SXT-026a, or any other leaf — the budgets
  remain proposals owned by #12, and every overall verdict above is reported
  exactly as the comparator returned it.
* Any preset-support or preset-quality claim; no listening record exists.
* Any FPGA / gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware-playback result.
* That the *other* consumers' committed evidence is now correct — it is
  measurably stale (§7, F-123-3), and saying so is the point.
