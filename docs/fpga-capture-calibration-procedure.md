# SXT-030 — FPGA board-selection record and capture/calibration procedure

Issue: [#23](https://github.com/2AMLogic/gf180-surge/issues/23) (SXT-030,
hardware-independent subset) · Plan:
[`docs/surge-xt-chip-plan-v0.1-2026-09-20.md`](surge-xt-chip-plan-v0.1-2026-09-20.md)
§6 (SXT-030 row), §7 · Date: 2026-10-02

## 0. Claim discipline — read this before quoting anything below

**This document performs no measurement.** Nothing here was run on an FPGA,
a board, a DAC, an audio interface, a logic analyzer, or any other
instrument. It contains:

1. a **board-selection record** whose requirement side is taken from
   committed repository evidence ([#12](https://github.com/2AMLogic/gf180-surge/issues/12)
   / [#19](https://github.com/2AMLogic/gf180-surge/issues/19)) and whose
   board side is taken from vendor-published board descriptions, each with
   an explicit status; and
2. a **procedure** — the ordered steps, pass conditions, refusal rules and
   negative controls that the live qualification
   ([#304](https://github.com/2AMLogic/gf180-surge/issues/304)) must execute.

Accordingly:

- **Every verdict named in this document is `NOT_RUN`.** There is no
  latency figure, no underrun figure, no stall figure, no capture, no
  utilization result for this instrument's RTL, and no agreement result.
- **No FPGA, gf180mcu synthesis, place-and-route, signoff, timing, power,
  hardware-playback, original-Surge-fidelity or preset-quality claim is made
  or implied.** Selecting a board is not qualifying it. A plausibility
  argument from a vendor-published peak figure is not a measurement of a
  sustained rate.
- Numbers on the *requirement* side are **ESTIMATES under named
  assumptions** inherited verbatim from `reports/sxt-017/cost-closure.json`
  and `contracts/profile-v1-DRAFT.md`, which are themselves
  `DRAFT-NOT-FROZEN` with placeholder components. They are not budgets met.
- Numbers on the *board* side are **vendor-published descriptions** (status
  marked per row). None was verified against silicon, a datasheet held
  locally, or a board on a bench.
- Separation of claims (root `CLAUDE.md`): this document touches **none** of
  (1) RTL-vs-frozen-model exactness, (2) model-vs-pinned-Surge agreement,
  (3) musical usefulness. It is an interface/board/procedure design only.

The one thing this document *does* establish is its own existence as the
procedure of record: after it, #304 executes committed steps with committed
pass conditions and a committed negative control, instead of inventing an
alignment during bring-up.

---

## 1. Requirement envelope (from committed evidence only)

### 1.1 What SXT-017 (#12) publishes

`contracts/profile-v1-DRAFT.md` §3.3 (bundle stage) and
`reports/sxt-017/cost-closure.json` (stage 2, cost-closure leg) publish
per-bundle maxima over all 3,561 normalized corpus graphs. Both are
`DRAFT-NOT-FROZEN`; the profile v1 freeze is **BLOCKED** (SXT-013 human
listening, SXT-014 labels), and stage 2 records
`stop_escalate: true` with `selected_bundle_fit_claim: false`.

| Bundle | max on-chip state (B) | max ext **writable** state (B) | max ext traffic (B/s) |
|---|---:|---:|---:|
| B1-core-narrow (DRAFT selection, stage 2) | 118,272 | 4,325,376 | 8,064,000 |
| B2-core-wet-plan3 | 159,232 | 4,325,376 | 8,064,000 |
| B3-ext-voice-fx | 493,056 | 35,356,672 | 19,584,000 |
| B4-broad (DRAFT selection, bundle stage) | 523,264 | 44,646,400 | 33,408,000 |
| R0-ceiling-reference (**non-product**) | 697,856 | 60,358,656 | 33,408,000 |

Declared *candidate* budgets in the same DRAFT spec, deliberately set above
the modeled maxima so structural gates bind first: **4 MiB on-chip,
64 MiB (67,108,864 B) external writable, 800 MB/s external bandwidth**.
These are candidates pending SXT-016 pricing, not requirements and not
claims.

The cost-closure grid also states the traffic requirement in its own terms —
`worst_ext_bytes_per_frame` at `sample_rate_hz: 48000`:

| Bundle | worst ext B / 48 kHz frame | × 48,000 = B/s |
|---|---:|---:|
| B1 / B2 | 152 | 7,296,000 |
| B3 | 408 | 19,584,000 |
| B4 / R0 | 696 | 33,408,000 |

The bundle-stage B1/B2 figure (8,064,000 B/s) and the stage-2 grid figure
(7,296,000 B/s) differ because they are different accounting stages. **For
sizing, this document always takes the larger of the two.**

The grid also prices three external-memory implementations and reports
`ext_bandwidth_fit` per (bundle, implementation, clock):

| Impl | Assumption as published in the grid | sustained B/s at 48 / 96 / 192 / 480 MHz |
|---|---|---|
| E1 | `A-EXT-1`: external 16-bit asynchronous SRAM, ~24 cycles per 32-bit word sustained, ~30-cycle first-access latency, no burst | 8e6 / 16e6 / 32e6 / 80e6 |
| E2 | `A-EXT-2`: external 16-bit synchronous SRAM, burst, 4 cycles per 32-bit word, 10-cycle latency per re-seek | 48e6 / 96e6 / 192e6 / 480e6 |
| E3 | `A-EXT-3`: external 32-bit synchronous SRAM/PSRAM, burst, 2 cycles per 32-bit word, 8-cycle latency per re-seek | 96e6 / 192e6 / 384e6 / 960e6 |

Published `EXCEEDS` rows (the only ones in the grid): **B3 at E1/48 MHz and
E1/96 MHz; B4 at E1/48, E1/96 and E1/192 MHz.** Every E2 and E3 row is
`within`. The reading that matters for a board: an **E1-class (non-burst
async SRAM) external path is not sufficient for the broad bundles**, and the
FPGA rig's memory path must be at least E2-class in sustained behavior.

### 1.2 What SXT-026 (#19) measured about traffic shape

`reports/sxt-026/EVIDENCE.md` §5 is the only committed record of *measured*
external traffic for a real preset (behavioral model + RTL reconciliation,
declared costs, no timing claim):

- Worst committed fixture (`kick-wtfix-uni16`, unison 16, 2,250 blocks):
  859,781 impulses, 1,723,658 external read words, 4,096 fill words,
  76,500 Reverb1 background words (34 words/frame), **`underrun_blocks: 0`**,
  `max_frame_bus_cost` 3,052 of a declared 32,000 bus-slot frame budget.
- Physical external traffic ≈ **35.8 words/frame ≈ 1.07 MB/s** at the 48 MHz
  A-CLK candidate — within the E1 floor (8 MB/s).
- **Logical vs physical is the load-bearing distinction**: logical demand
  reaches ~764 words/block at unison 16, but the per-core frame cache absorbs
  it; the external bus sees only cache-cold frame fills plus the Reverb1
  background pattern.
- Residency reconciliation: `osc_state_bytes_per_unison` 512 B,
  `wt_working_set_bytes` 65,536 B, active morph pair 8 KiB.

**Unit warning.** "Frame" means different things in the two records: a
48 kHz sample frame in #12's grid, and the SXT-026 harness's own frame
(7,500/s, from which its 1.07 MB/s figure is derived) in #19. **Only the
bytes-per-second figures are directly comparable**, and this document
compares only those.

### 1.3 The envelope this document sizes against

| Quantity | Value | Where from |
|---|---:|---|
| External **writable** capacity, product-candidate worst case | 44,646,400 B (42.58 MiB) | #12 B4 |
| External writable capacity, declared candidate ceiling | 67,108,864 B (64 MiB) | #12 DRAFT spec |
| External writable capacity, non-product ceiling reference | 60,358,656 B (57.56 MiB) | #12 R0 |
| External traffic, product-candidate worst case | 33,408,000 B/s | #12 B4 (= 696 B × 48,000) |
| External traffic, measured-shape anchor | ≈ 1,070,000 B/s | #19 §5 |
| External traffic, declared candidate budget ceiling | 800,000,000 B/s | #12 DRAFT spec |
| Sustained-behavior class required | ≥ E2 (burst, ~4 cycles/32-bit word) | #12 `EXCEEDS` rows |
| Audio output | 48 kHz, stereo, to an external DAC over I2S | plan §3, §6; AGENTS.md |

**The board is sized against the 64 MiB candidate ceiling, not against the
current DRAFT selection.** Reason, and it is a contract reason rather than
an engineering preference: profile v1 is **not frozen**, and the DRAFT
selection has already moved between stages (B4-broad at the bundle stage,
B1-core-narrow at the cost-closure stage). A board chosen to fit only
today's selection would become a *silent* cap on the still-open freeze — if
the owner later selects a bundle needing 44.6 MiB and the rig holds 32 MiB,
the feature cut happens on a bench with no decision record. Root
`CLAUDE.md` forbids exactly that ("Feature cuts are visible contract
revisions (SXT-017), never silent ones"). The 800 MB/s *bandwidth* ceiling
is handled differently, in §2.4, because unlike capacity it is a placeholder
headroom figure sitting far above every modeled maximum.

---

## 2. Board-selection record

### 2.1 Selection criteria, in the order they bind

1. **External writable memory capacity** — must cover 67,108,864 B with
   margin. Flash is not a substitute (root `CLAUDE.md`); the memory must be
   writable at audio rates for delay/reverb histories, and per-instance
   state must be separately addressable (two Delay slots = two histories).
2. **External memory sustained behavior** — must be at least E2-class
   (burst-capable) and must cover 33,408,000 B/s of scattered 4-byte-word
   traffic with a stated efficiency assumption.
3. **Pin budget** — must carry I2S out (3 signals), a control/event link, a
   hardware stall witness, and status LEDs, *without* competing with the
   memory interface's pins.
4. **Audio interface path** — must support a 48 kHz, ≥ 24-bit external DAC
   over standard I2S. An on-board resistor-ladder "audio jack" does not
   qualify as the output path under test.
5. **Method transfer cost** — how much of the organization's existing,
   committed bring-up discipline (constraint binding, build manifests,
   capture tooling) applies without reinvention.

Fabric capacity (LUT/FF/DSP/BRAM) is **deliberately not a selection
criterion here**, because this instrument's RTL has never been synthesized
for any FPGA and this issue may not synthesize it. See §2.5.

### 2.2 Candidates considered

| Board | FPGA | External writable memory (vendor-published) | Status of figure |
|---|---|---|---|
| **Arty A7-100T** (selected) | XC7A100T-CSG324-1 | DDR3L, "256 MB", device `MT41K128M16XX-15E`, `DataWidth 16`, MIG `TimePeriod 3077` ps | vendor board-support file, pinned (§13 S5) |
| ULX3S | ECP5 LFE5U-85F-6BG381C (the board also ships in 12F/25F/45F variants; `gf180-dx7` D01 and the pinned parasynth wrapper target the **25F**) | "32MB SDRAM 166 MHz" — the same part on every fabric variant | vendor product page, retrieved 2026-10-02 (§13 S6) |
| Nexys A7-100T | XC7A100T-CSG324-1 | DDR2, device `MT47H64M16HR-25E`, `DataWidth 16`, `TimePeriod 3077` ps | vendor board-support file, pinned (§13 S5) |
| Genesys 2 | XC7K325T-FFG900-2 | DDR3, "1 GB 1800Mt/s", device `MT41J256m16XX-107`, `DataWidth 32`, `TimePeriod 1111` ps | vendor board-support file, pinned (§13 S5) |
| iCEBreaker (iCE40 UP5K) | iCE40 UP5K SG48 | none | parasynth's own wrapper notes state the board must supply even the clock (§13 S3) |

### 2.3 Capacity: the criterion that decides

Derived figures (arithmetic over §1.3 and §2.2; division only, no
measurement):

| Board | Capacity (B) | ÷ 64 MiB ceiling | ÷ B4 (44,646,400) | ÷ B3 (35,356,672) | ÷ B1/B2 (4,325,376) |
|---|---:|---:|---:|---:|---:|
| Arty A7-100T (256 MB = 268,435,456 B) | 268,435,456 | **4.00×** | **6.01×** | 7.59× | 62.1× |
| Genesys 2 (1 GB = 1,073,741,824 B) | 1,073,741,824 | 16.0× | 24.1× | 30.4× | 248× |
| Nexys A7-100T (`MT47H64M16` ⇒ 1 Gbit × 16 = 134,217,728 B) | 134,217,728 | 2.00× | 3.01× | 3.80× | 31.0× |
| ULX3S ("32MB", read generously as 33,554,432 B) | 33,554,432 | **0.50×** | **0.75×** | **0.95×** | 7.76× |
| iCEBreaker | 0 | 0 | 0 | 0 | 0 |

**ULX3S fails on capacity, decisively and on the published numbers**: it
holds half the declared candidate ceiling, three-quarters of B4's modeled
worst case, and does not even cover B3. It covers B1/B2 only. Note the
`MT47H64M16HR-25E` row: Digilent's own `board.xml` *description text* for
the Nexys A7-100T reads "256 MB Onboard DDR Memory" while its `mig.prj`
names a 1 Gbit × 16 device; the two disagree, so this document uses the
part-number derivation and flags the discrepancy as a
**verify-at-procurement** item. It changes no conclusion (the Nexys is
rejected in §2.6 for other reasons).

### 2.4 Bandwidth: plausibility with stated assumptions

The traffic requirement is tied to the 48 kHz audio rate, **not** to the
core clock: 696 B per 48 kHz frame is 33,408,000 B/s whatever clock the
FPGA core runs at. What the board must do is sustain that as scattered
4-byte-word traffic.

Arty A7-100T, from the pinned MIG project file: `TimePeriod` 3,077 ps ⇒
memory clock 325.0 MHz ⇒ 650.0 MT/s ⇒ with `DataWidth 16` (2 B/transfer) a
**peak of ≈ 1.30 × 10⁹ B/s**. Therefore:

| Comparison | Value |
|---|---:|
| Required ÷ peak (B4 worst case) | **2.57 %** |
| Required ÷ peak (B3) | 1.51 % |
| Required ÷ peak (B1/B2) | 0.62 % |
| Delivered at a pessimistic **5 %** sustained efficiency | 65.0 MB/s = **1.95×** required |
| Delivered at **10 %** sustained efficiency | 130 MB/s = 3.9× required |
| Peak vs E3's most favorable modeled row (960 MB/s @ 480 MHz) | 1.35× |

Read precisely: the board's memory path need only achieve **2.57 % of its
own peak** to carry the worst modeled traffic. Scattered single-word DDR3
access is inefficient — row thrash, refresh, read/write turnaround — but a
path that cannot reach 5 % of peak would be anomalous. **This is a
plausibility argument, not a measurement**: sustained efficiency on this
board with this access pattern is `NOT_RUN` and is #304's to measure
(§6 step D-7 records it).

The declared 800,000,000 B/s *candidate budget* is 61.5 % of this board's
peak. **No claim is made that the board sustains 800 MB/s** — at realistic
DDR3 efficiency for this access shape it almost certainly does not. That
figure is a placeholder budget ceiling in an unfrozen DRAFT, sitting ~24×
above every modeled maximum; it is not a traffic requirement. It is carried
as a **re-open trigger** instead (§2.7, trigger T2).

### 2.5 Fabric capacity: explicitly not established

No synthesis of this repository's RTL has been run for any FPGA, and this
issue may not run one. Therefore:

- **`fabric_adequacy: NOT_RUN` for every candidate, including the selected
  board.** Selecting the larger of the two Arty variants maximizes headroom
  against an unmeasured requirement; it does not establish adequacy.
- Scale reference only, and **not** a result about this instrument: the
  sibling parasynth's published Arty R2 image reports LUT 15,484, FF 13,490
  and DSP 124 for a far smaller engine (an 808-style drum and voice core),
  against the 63,400 slice-LUT denominator its own utilization table prints
  for this part. A Surge-subset voice pool with wet effects is a different
  and unmeasured workload. This is the same discipline `gf180-dx7`'s D01 applies
  to its own board row ("ULX3S is sufficient for the DX7 core" — *assumed,
  not established*).
- The XC7A100T's DSP48E1 count (commonly published as 240) is **not sourced
  in this document** and is marked `unverified`; §6 step B-2 records the real
  denominators from the build's own utilization report.

### 2.6 Decision

**Selected board: Digilent Arty A7-100T (XC7A100T-CSG324-1), with an
external PCM5102A-class I2S DAC breakout.**

Rationale, criterion by criterion:

1. **Capacity** — 4.00× the declared 64 MiB candidate ceiling and 6.01× the
   B4 modeled worst case (§2.3). It does not constrain the open profile-v1
   freeze in either direction.
2. **Sustained behavior** — a burst-capable DDR3L path through a vendor
   memory controller is E2-class or better by construction; the required
   fraction of peak is 2.57 % (§2.4). E1-class non-burst async SRAM, which
   the grid shows `EXCEEDS` for B3/B4, is not what this board offers.
3. **Pin budget** — the memory interface and the audio/control budget do not
   compete: the DDR3 interface occupies **48 dedicated pins on bank 35**
   (counted from the pinned `mig.prj`: `addr` 14, `dq` 16, `ba` 3,
   `dqs_p`/`dqs_n` 2+2, `dm` 2, and 9 single control/clock signals), and
   Digilent's master XDC for this board declares **no `ddr3_*` port at all**
   (checked: zero matches) because MIG supplies them. The user-IO budget is
   separate: **32 Pmod signal pins (4 headers × 8) + 36 shield pins**
   (`dp0`–`dp19` and `dp26`–`dp41`, counted from the pinned `part0_pins.xml`)
   = 68, against a demand of 8 (§4.3) ≈ 12 %. The USB-UART control link uses
   its own dedicated pins.
4. **Audio path** — standard I2S to an external 48 kHz / 24-bit DAC, which
   is the output path the product actually contracts for. (The ULX3S's
   4-contact jack is a resistor-ladder analog output; it is not the output
   stage under test.)
5. **Method transfer** — the organization already has a committed Arty
   A7-100T bring-up discipline to **adapt** (not copy): compiled-XDC
   binding records, build manifests bound to source hashes, a
   `srccheck`-equivalent asserting the routed file set equals the simulated
   file set, a published programming-transcript-is-not-a-readback rule, and
   a complete analog capture procedure with a frozen-calibration model
   (§13 S3, S4). Adapting that method is the single largest saving available
   and is what plan §7 means by sharing "verification tooling" as an
   established seam.

Rejections, with reasons:

| Board | Rejected because |
|---|---|
| **ULX3S** | Capacity: 0.50× the candidate ceiling, 0.75× B4, 0.95× B3 (§2.3). Choosing it would cap the unfrozen profile silently. Also: at the pinned parasynth commit the ULX3S bring-up had **no external writable memory in it at all** — its own `fpga/README.md` § "What a board must provide" states that the design "has no external memory of any kind … No SRAM, no SDRAM, no flash beyond the configuration image" — so the sibling's ULX3S experience transfers *nothing* about external-memory arbitration, which is precisely this instrument's binding constraint. **Retained as a secondary target** for the open-toolchain / ASIC file-set-parity leg, where external memory is not exercised. |
| **Nexys A7-100T** | Same FPGA as the Arty, older DDR2 memory, 2.00× (not 4.00×) the candidate ceiling, a documented vendor-description discrepancy (§2.3), and none of the committed Arty constraint/build/capture substrate. No criterion favors it. |
| **Genesys 2** | Not rejected on capability — it dominates on memory (16.0× the ceiling, 32-bit data path, ≈ 7.2 × 10⁹ B/s peak) and on fabric. Rejected as the *first* target for cost and complexity: nothing in the published requirement envelope needs it, and an unmeasured fabric requirement is not a reason to buy the largest board available. **Named as the escalation target** if trigger T3 fires (§2.7). |
| **iCEBreaker (iCE40 UP5K)** | No external writable memory, and parasynth's own notes record that its wrapper has no PLL and the board must supply the clock. Out of scope for an external-memory qualification. |

**Stop/escalate check (issue #23's condition): not triggered.** The
condition was "if no candidate board can plausibly sustain the measured
worst-case traffic at a realistic interface, STOP and escalate". Two
readings of "measured", both answered: the **modeled** worst case
(33,408,000 B/s, #12, an estimate over placeholder-priced components) is
covered at 2.57 % of the selected board's published peak, and the
**measured-shape anchor** (≈ 1,070,000 B/s, #19, a behavioral-model
measurement with RTL reconciliation) at 0.08 %. Capacity is covered at
4.00× the declared ceiling. All figures are sourced (§13); none is a
measurement of this board. No escalation to SXT-017 is required by this
issue, and no board was chosen that fails the envelope.

### 2.7 Re-open triggers (the board decision is revisable, by record)

| ID | Trigger | Action |
|---|---|---|
| T1 | Profile v1 freezes with external writable state > 67,108,864 B | Re-run §2.3 against the frozen number. The Arty holds 4.00× the ceiling, so headroom exists up to ~268 MB; beyond that, escalate to T3. |
| T2 | Frozen or re-priced external traffic exceeds **65,000,000 B/s** (the 5 %-of-peak pessimistic line in §2.4) | The plausibility argument no longer has 2× margin. Measure sustained efficiency first (step D-7); if measured sustained < 2× the requirement, escalate to T3. |
| T3 | Measured fabric utilization (step B-2) overflows, or T1/T2 cannot be met | Escalate to the Genesys 2 class target (§2.6) **and** record the move as a visible revision in #12/#23 — never by quietly trimming buffers, polyphony, or FX instances. |
| T4 | A frozen profile requires sustained **write** bandwidth or latency that single-rank x16 DDR3L cannot serve | Escalate via SXT-017 (#12) as a bounded finding; do not re-scope the audio contract on the bench. |
| T5 | `gf180-dx7#31` (H09) commits a capture procedure that diverges from §11 | Re-reconcile §11; shared seams are plan §7 policy, and a silent divergence is the failure mode. |

---

## 3. Rig architecture: two capture legs, kept apart

The procedure has two legs that are **never** substituted for one another:

| Leg | What it captures | What it can establish | What it cannot |
|---|---|---|---|
| **D — digital** | the I2S word stream leaving the design, bit-exact | integer agreement with the frozen model's render after a *declared* latency; stall/underrun counters; framing | nothing about the analog output path |
| **A — analog** | the DAC's line output, recorded at 48 kHz / 24-bit | that the real output path carries the sound within declared budgets after a *frozen* calibration | exactness; it is a calibrated comparison, not an equality |

Leg D is the exactness leg and runs first. **Leg A may never be used to
rescue a Leg D failure**, and a Leg A PASS never upgrades a Leg D FAIL or
`NO_VERDICT`. Leg A exists because the product's output is analog line out
and the plan requires hardware audio captures to have their own
alignment/calibration procedure (AGENTS.md); it is not a fidelity oracle.

Leg D is obtained two ways, and both are specified because a single witness
can be wrong:

- **D-primary (on-FPGA capture buffer)**: the wrapper latches the I2S
  transmitter's parallel sample words into a BRAM ring, tagged with the
  48 kHz frame index, read back over the control link. Deterministic, no
  sampling ambiguity, no external instrument. This is the leg whose output
  is compared at integer equality.
- **D-crosscheck (wire capture)**: a logic analyzer on BCLK / LRCLK / DIN,
  decoded to words. Confirms that what left the pins equals what D-primary
  recorded inside the chip. Required sample rate ≥ 4× BCLK; with a 48 kHz
  LRCLK and a 64-bit frame, BCLK is 3.072 MHz, so ≥ 12.288 MS/s is the
  floor and ≥ 24 MS/s is specified.

---

## 4. Equipment, connections, configuration

### 4.1 Equipment list (each item's identity is recorded in the bundle)

| # | Item | Requirement | Recorded as |
|---|---|---|---|
| E1 | Digilent Arty A7-100T | check the silkscreen: a 35T takes a different bitstream and must be refused, not reflashed | `board.model`, `board.revision` |
| E2 | Micro-USB cable, **data-capable** | charge-only cables power the board but present no USB device | — |
| E3 | PCM5102A-class I2S DAC breakout | 3.3 V I/O, self-generating main clock, standard-I2S default format, 48 kHz / 24-bit | `dac.part`, `dac.breakout`, `dac.config_pins` |
| E4 | 6 × female-female jumper wires | short, equal length | `wiring.notes` |
| E5 | Audio interface with line inputs | 48 kHz, 24-bit, **no** gain stage in the path, no DSP, no resampling, no dither | `capture.interface`, `capture.serial` |
| E6 | TRS-to-dual-TS cable | stereo split to two line inputs | `wiring.audio_cable` |
| E7 | Logic analyzer | ≥ 24 MS/s, ≥ 4 channels, I2S decode or raw capture + offline decode | `instruments.la` |
| E8 | Build host with the vendor FPGA toolchain | exact tool version recorded; this is the only machine that produces a bitstream | `build.tool`, `build.tool_build` |
| E9 | Programming host with `openFPGALoader` (or vendor equivalent) | version recorded | `image.programmer` |
| E10 | Repository checkout at a named commit | clean tree; `git status` recorded | `repo.commit`, `repo.dirty` |
| E11 | Optional: USB-MIDI controller | only for the live-MIDI leg; the deterministic legs use event vectors over the control link | `midi.controller` |

**Not in the equipment list, deliberately**: an oscilloscope for audio
judgement, headphones for verdicts, and any device that normalizes,
compresses or re-rates audio. Per-clip normalization and time-warping are
forbidden by root `CLAUDE.md` and no instrument that performs them may sit
in the capture path.

### 4.2 Connections

Power the board **off** before wiring.

| Signal | From (board side) | To (DAC side) | Notes |
|---|---|---|---|
| I2S bit clock | Pmod **JA position 1** | `BCK` | 3.072 MHz at 48 kHz / 64-bit frames |
| I2S word select | Pmod **JA position 2** | `WSEL` / LRCLK | 48 kHz; low = left |
| I2S data | Pmod **JA position 3** | `DIN` | MSB on the second BCLK after the WSEL edge |
| Stall strobe | Pmod **JA position 4** | — (logic analyzer) | §9.2 hardware witness |
| Ground | Pmod **JA position 5** | `GND` | common return |
| 3.3 V | Pmod **JA position 6** | `VIN` | breakout accepts 3.3–5 V |

**Pmod numbers above are connector positions, not FPGA package pins.** The
package pins are **not transcribed into this repository**: the constraint
file is generated at build time from the board vendor's own master
constraint file at a pinned commit (§13 S7), and the generated file is bound
to the build by a binding record (step B-3). This is deliberate — the reuse
audit records vendor-derived pin attribution as unresolved, and the remedy is
to regenerate constraints against the chosen board rather than to copy a pin
table in.

Leave the DAC's main-clock, de-emphasis, filter, mute and format-select pads
**unconnected** so the breakout's documented defaults apply (self-clocking,
de-emphasis off, normal filter, unmuted, I2S format). Record which pads were
left floating in `dac.config_pins`; a procedure that silently pulls one of
them changes the device under test.

Audio: DAC jack → TRS-to-dual-TS → two **line** inputs. Record which
physical input carries left and which carries right. Unlike the sibling
designs, **this instrument is genuinely stereo** (per-effect stereo
behavior is part of the product contract), so a left/right swap is
**observable and must be detected** — see step A-4 and NC-6.

Control link: the board's on-board USB-UART (dedicated pins, not from the
Pmod budget). An optional SPI engineering link may be brought out on Pmod JB
(4 signals); it is **outside the qualified command domain** and no verdict
may be derived from a take that used it.

### 4.3 Pin-budget accounting (for the §2.6 criterion 3 claim)

| Consumer | Signals | From |
|---|---:|---|
| I2S out | 3 | Pmod JA 1–3 |
| Stall strobe | 1 | Pmod JA 4 |
| Status LEDs (clock locked, reset released, heartbeat, LRCLK) | 4 | on-board LEDs |
| Control link (UART) | 2 | dedicated USB-UART pins |
| Reset | 1 | on-board button |
| External memory | 48 | **dedicated bank-35 pins**, MIG-supplied |
| Optional SPI engineering link | 4 | Pmod JB |
| **User-IO demand against the 68-pin Pmod+shield budget** | **8** (12 %) | — |

### 4.4 Host configuration

1. Set the capture interface to **48,000 Hz**, 24-bit, 2 or more inputs.
   Record the OS-reported rate. **The analysis refuses any take not at
   48,000 Hz. Nothing is resampled, ever.**
2. Fix the input gain and do not touch it for the whole session. Use line
   inputs with no gain stage where available; if the interface has gain,
   record the position and never move it mid-session.
3. Verify the recorder's own chain before the board plays anything: the
   recording command's reported chain must contain only input / trim /
   output — no `rate`, no `dither`, no effect.
4. Record the whole session in **one** power-on of the board. Programming is
   volatile; a power cycle returns the FPGA to its flash image and
   invalidates the session's image identity.

---

## 5. Build and identity discipline (before any capture)

These steps make a capture attributable to an exact design. A capture whose
image identity is unknown is `NO_VERDICT`, never PASS.

- **B-1 Source-set assertion** (`srccheck`-equivalent): assert that the file
  set the implementation tool routes is **exactly** the file set the
  simulation bench elaborated and compared against the frozen model. Fail
  the build if the two sets differ. This is the check that catches "the
  board ran a different design than the one we verified".
- **B-2 Build manifest**: record repository commit, every compiled source
  blob hash, ROM/asset hashes, tool name and build number, target part,
  clock configuration (PLL/MMCM multiply-divide and resulting frequencies in
  exact ratios, not rounded), **resource utilization for this exact build**
  (LUT / FF / BRAM / DSP with their denominators), timing-report slack
  figures, and the bitstream SHA-256.
- **B-3 Constraint-binding record**: a separate record asserting that the
  generated constraint file still refers to this wrapper — every port name
  resolves, every hierarchical path joins, every output delay equals the
  budget derived from the DAC's datasheet. A file that no record answers for
  must **refuse**, not pass unasked.
- **B-4 Reference render**: render the comparison reference for every fixture
  from **the frozen model at the same commit the bitstream was built from**,
  and record each reference's hash in the manifest. The reference is never
  re-rendered after a capture to make it agree.
- **B-5 Programming transcript**: record the programmer version, the
  bitstream hash as sent, the programmer's exit status, and the resulting
  configuration-done indication. **A programming transcript is not a
  readback**: the session records `readback: false` and the analysis labels
  image identity "programming transcript only — NOT a readback". Set
  `readback: true` only after an actual configuration readback was performed
  and compared.
- **B-6 Failed attempts are kept**: on a programming failure, repeat the
  transcript block and append; never delete a failed attempt and never
  append a bare success line. The analysis accepts the session only if the
  **last** attempt succeeded, and keeps every earlier attempt.

---

## 6. The procedure

Steps are ordered. **If a step's pass condition fails, stop at that step,
record what was seen, and do not work around it.** Every artifact named goes
into the capture bundle (§10).

### Phase 0 — rig sanity (no audio claim available yet)

- **0-1** Power on; confirm the board's power-good indication. Record it.
- **0-2** Detect the device with the programmer; the transcript must name the
  **xc7a100t** part. If it names a 35T, **stop**: wrong board.
- **0-3** Program the image per B-5. Pass: programmer exit 0, configuration
  done asserted, bitstream hash equals the manifest's.
- **0-4** Press the reset button once. Confirm the status LEDs: clock locked,
  reset released, heartbeat blinking, LRCLK half-lit. **These lights do not
  prove audio.**
- **0-5** Open the control link and read status. Pass: a status response with
  a live, advancing 48 kHz frame counter. A read-only status query sends no
  register write and plays nothing.
- **0-6 LRCLK-count gate (mandatory before any audio claim)**: count LRCLK
  edges on the logic analyzer for **≥ 10 s** against the instrument's time
  base. Pass: the implied sample rate is within the declared ppm window
  recorded in the manifest's clock configuration. **No audio comparison may
  be attempted, and no capture may be graded, until this gate passes.**
  (This gate is inherited from the sibling bring-up doctrine and is also an
  explicit `gf180-dx7#31` acceptance item.)
- **0-7** Record the idle output: a 10 s capture on both legs with the design
  reset and nothing commanded. Pass: analog noise floor below the declared
  floor; digital words identically the declared idle value; stall counters
  zero.

### Phase D — digital capture (exactness leg)

- **D-1** Select the fixture set. Every fixture is a **committed event
  vector** consumed identically by the frozen model and by the hardware over
  the control link. Required coverage:
  (a) one dry single-voice fixture; (b) one complete **wet** preset fixture
  with its original effect placement and order; (c) a **two-instance**
  fixture that uses two slots of the same effect class (two Delay slots) so
  per-instance state is exercised; (d) a long-tail fixture whose reverb decay
  runs past the comparison window; (e) a patch-change fixture that switches
  patches while a tail is sounding; (f) a stereo-identity fixture whose left
  and right channels are **deliberately unequal**; (g) the worst-case asset
  traffic fixture (the SXT-026 unison-16 shape, §1.2).
- **D-2** For each fixture: arm the on-FPGA capture ring, start the logic
  analyzer, send the vector, wait for the declared number of frames plus the
  declared tail, then read the ring back.
- **D-3** Readback integrity: the ring's frame indices must be contiguous and
  must cover the whole fixture; the captured frame count must equal the
  commanded one. A short or discontinuous readback is `NO_VERDICT`, not a
  FAIL and never a PASS.
- **D-4** **Latency is declared, not searched.** The design's event-to-first-
  voiced-sample latency `L` (in 48 kHz frames) comes from the frozen model's
  own schedule and is recorded in the manifest *before* the capture. The
  comparison shifts the captured stream by **exactly `L`** and compares at
  integer equality. If it fails, the failure stands: it is **forbidden** to
  search `L`, to fit a per-take offset, or to time-warp either side.
- **D-5** Compare at integer equality against the B-4 reference, per channel,
  for every frame in the window. Pass: zero mismatches. Report the number of
  frames compared — a silently empty comparison must not be able to
  masquerade as a pass, so the analysis asserts the compared-sample count
  equals the fixture's declared length.
- **D-6** Compare the D-crosscheck wire decode against the D-primary ring for
  the overlapping window. Pass: identical words. A disagreement indicts the
  instrumentation and makes the take `NO_VERDICT`.
- **D-7** Record traffic and service counters for every fixture (§9.1):
  external words read/written, bytes/s derived at 48 kHz, peak per-frame
  service occupancy, `STALL_FRAMES`, `STALL_CYCLES_MAX`, and the derived
  **sustained external-memory efficiency** (achieved B/s ÷ the board's peak).
  These are the numbers trigger T2 reads. They are measurements of the rig,
  not fidelity claims.
- **D-8** Long-tail and patch-change continuity: for fixtures (d) and (e),
  the comparison window must extend past the declared tail end minus the
  declared end guard, and the patch change must not truncate the sounding
  tail. A dropped tail is a FAIL (and NC-5 proves the check can see one).

### Phase A — analog capture (calibrated leg)

- **A-1** Record the **calibration take** first: a dedicated fixture, long
  enough for a stable estimate, with a defined onset. Nothing else is
  recorded before it.
- **A-2** Estimate the three calibration parameters from the calibration take
  **once per session**, under the model `capture[n] = g · ref((n − d) · ρ)`:
  **ρ** sample-clock ratio, **g** gain, **d** delay. Then **freeze all
  three**. Per-take re-estimation of ρ and g is forbidden. `d` may be
  re-estimated once per take, inside a **declared** calibration window just
  after the take's first onset, because recordings are started by hand —
  and that is the *only* per-take fit the procedure permits.
- **A-3** Measure, never re-align: local lag and local gain are **measured
  against** the frozen values and may not be used to re-align anything. A
  timing slip, clock drift or gain change must surface as a failure, not be
  absorbed.
- **A-4** Routing and channel identity: with the stereo-identity fixture,
  assert that the declared input carries the declared channel, that no
  declared input is silent where the reference sounds, and that left ≠ right
  exactly where the reference says so. Report channel identity as PASS or
  FAIL — **not** `UNOBSERVABLE`; this design is not dual-mono, so the
  sibling's unobservability caveat does not transfer.
- **A-5** Compare inside **one declared analysis band**, with the identical
  zero-phase filter applied to capture and prediction alike. The band is
  declared in the manifest before the session and is **never fitted**; it
  exists to remove only what the analog path is permitted to do outside the
  audio band (AC coupling, converter anti-image filters). Pitch, clipping
  and noise floor are measured on the **raw** capture.
- **A-6** Stop the comparison a declared **end guard** before each
  reference's end, and require the capture to run at least that long. A take
  shorter than its reference is refused.
- **A-7** Apply the limit table (§7) and emit one verdict per check per take.
  **Never normalize a take, and never normalize per clip** — a gain or drive
  error must stay visible (root `CLAUDE.md`, plan §5).
- **A-8** Repeat two fixtures a second time in the same session for a
  repeat-stability check.

### Phase N — negative controls

Run **every** control in §9. A control that does not demonstrably fail the
check it targets invalidates the corresponding positive result: the positive
result drops to `NO_VERDICT` until the control is repaired.

### Phase R — reset and patch-change continuity

- **R-1** Mid-tail reset: assert reset while a long tail is sounding. The
  output must go to the declared idle value and the counters must show a
  commanded reset, not a stall. A reset that leaves stale samples circulating
  is a FAIL.
- **R-2** Post-reset identity: re-read status and re-run one Phase-D fixture.
  Pass: bit-identical to its earlier pass in the same session. (This is what
  catches a reused slot inheriting stale state — a defect the SXT-026 record
  documents in its own harness.)
- **R-3** Patch change under load: switch patches repeatedly while the
  worst-case traffic fixture runs. Pass: no stall counter increments beyond
  the declared allowance, no discontinuity beyond the declared patch-change
  window, previous tails complete or are terminated exactly as the model
  says.

---

## 7. Verdicts, limits, refusals

Verdict vocabulary (root `CLAUDE.md`): **PASS, FAIL, NOT_RUN, BLOCKED,
NO_VERDICT, STALE**. Coverage is reported separately from agreement.

| Check | Leg | FAILs when |
|---|---|---|
| image identity | both | the bitstream hash, source set, or clock configuration of the run differs from the manifest |
| framing | both | the implied sample rate is outside the declared ppm window (step 0-6) |
| exactness | D | any compared frame differs from the reference by ≥ 1 LSB after the declared latency shift |
| coverage | D | fewer frames were compared than the fixture declares |
| cross-witness | D | the wire decode and the on-chip ring disagree |
| stall | both | `STALL_FRAMES > 0` on a take that is not an over-subscription control |
| routing / channel identity | A | a declared input does not carry its declared channel, or left/right are swapped or inverted |
| silence | A | a declared input is quiet where the reference sounds |
| clipping | A | the declared consecutive-full-scale-sample threshold is met |
| pitch | A | a tone take's `f0` ratio differs from the frozen clock ratio beyond the declared cents bound |
| clock | A | the session offset exceeds the declared ppm bound, or a take drifts beyond the declared per-take bound |
| timing | A | local lag moves beyond the declared sub-sample bound from the frozen delay |
| gain | A | median local gain differs beyond the declared dB bound from the frozen gain |
| noise | A | the idle take's floor is above the declared floor |
| dropout | A | a declared short block falls a declared margin below prediction where the prediction is above a declared level |
| stuck | A | output persists beyond a declared duration where the reference is silent |
| residual | A | the band-limited residual energy ratio exceeds the declared bound after the calibration window |
| repeat | A | two takes of one command differ beyond the declared bound |
| tail | both | a declared tail is truncated before the end guard |

**Numeric limit values are deliberately absent from this document.** Each
bound must be declared in the manifest *before* the session that uses it,
derived from the frozen model and the declared budgets — not chosen after
looking at a capture. #304 commits the limit table it used, with its
derivation, as part of its evidence.

Refusal rules (these are what keep a broken rig from producing a PASS):

1. A take whose image identity is unknown, whose readback is short, or whose
   framing gate did not pass is **`NO_VERDICT`**.
2. A take with `STALL_FRAMES > 0` may **never** be reported as PASS.
3. **Silence with zero counters is `NO_VERDICT`, not a stall and not a
   pass** — see §9.2.
4. A control that failed to fail invalidates its positive result
   (`NO_VERDICT`), and the control is repaired before the result is re-cited.
5. A take that used the engineering interface is outside the qualified
   command domain and carries no verdict.
6. Any evidence superseded by a hardware or RTL fix is marked **STALE** and
   re-run; a superseded PASS is never quoted forward.

---

## 8. What is a coverage statement and what is not

A capture bundle establishes what its fixtures covered, and nothing more.
Specifically, a Phase-D PASS on fixtures (a)–(g) establishes that **those
vectors** ran on **that** image and agreed with **that** reference. It does
not establish preset support, fidelity against the pinned Surge engine,
musical usefulness, or any statement about presets not in the fixture set.
Preset support remains defined by the wet-preset fidelity contract, and
substituting an effect for a convenient generic makes a preset *adapted*,
which never counts toward original-preset coverage (root `CLAUDE.md`).

---

## 9. Negative controls

### 9.1 Instrumentation this procedure requires in the wrapper

The controls below are only testable if the design carries the following.
This is a **specification for #304's build** (and for the RTL issue that
implements it). It is implemented and verified **in simulation only** (see
the implementation note below); no hardware behavior of it is claimed here.

| Register / signal | Meaning |
|---|---|
| `FRAME_COUNT` | 48 kHz frames emitted since reset (distinguishes "no traffic" from "stuck counter") |
| `EXT_WORDS_RD`, `EXT_WORDS_WR` | external-memory words transferred since reset (per-instance tagged where state is per-instance) |
| `SVC_OCCUPANCY_MAX` | peak per-frame external-service occupancy, in core cycles |
| `STALL_FRAMES` | saturating count of frames whose external service **missed its deadline** |
| `STALL_CYCLES_MAX` | worst per-frame blocked-cycle count |
| `FIRST_STALL_FRAME` | sticky frame index of the first miss |
| `OUTPUT_FAULT` | sticky bit: at least one output sample was not produced by the normal path |
| `LOADGEN_WORDS_PER_FRAME` | commanded synthetic over-subscription (§9.2 M1) |
| `SVC_WINDOW_LIMIT` | commanded external-service grant window per frame (§9.2 M2) |
| `BUILD_ID` | build-identity nonce read back over the control link, compared with the manifest |
| `stall_strobe` pin + latching LED | hardware witness, visible to the logic analyzer even if the control link is wedged |

Deadline-miss output policy, stated so the failure is **loud**: on a miss
the design holds the previous frame's sample (a deterministic, audible
discontinuity against the prediction) and sets `OUTPUT_FAULT`. It must
**not** emit silence, and must not substitute a quiet or faded sample — a
quiet failure is the failure mode root `CLAUDE.md` names explicitly
("silent/stale stubs"). Counters are read before and after every take and
the deltas are recorded in the bundle.

**Implementation note (revision, #316).** The set above is implemented in
RTL and verified **in simulation only** in `rtl/instrumentation/`
(evidence: `reports/SXT-030/EVIDENCE.md`). No row's meaning changed; the
implementation makes three additive clarifications, recorded here so they
are not silent: (1) a stall in frame 0 has no previous frame to hold, so
the output register resets to a declared **non-zero** `HOLD_RESET` sample
(holding a reset value of 0 would be the silence this section forbids);
(2) a `STATUS` register carries the sticky bits (`OUTPUT_FAULT`, latched
LED) plus a `FIRST_STALL_VALID` bit, so "first stall in frame 0" is
distinguishable from "no stall"; (3) a `CTRL.RUN` bit and per-tag
`EXT_WORDS_RD/WR` counters (instance 0, instance 1, load generator) realize
"per-instance tagged". The deadline is the frame's whole external service,
load-generator traffic included. None of this is a hardware claim; #304
still runs NC-1 live.

### 9.2 NC-1 — over-subscribed traffic must appear as a **measured stall**, not silence

This is issue #23's required negative-control design, and the control #304
inherits rather than invents.

**Targeted failure:** a rig that cannot tell "the external memory could not
keep up" from "the instrument was quiet", and therefore reports an
over-subscribed run as a clean pass or as unexplained silence.

**Two independent over-subscription mechanisms** (both are specified; a
single mechanism could itself be the thing that is broken):

- **M1 — synthetic load generator (physical over-subscription).** A wrapper
  block issues `LOADGEN_WORDS_PER_FRAME` additional 4-byte external accesses
  per 48 kHz frame, on top of the fixture's own traffic, in the same
  scattered access pattern. The ladder starts from the measured anchor and
  climbs past the modeled worst case:

  | Rung | words/frame added | derived B/s added | relation to the envelope |
  |---|---:|---:|---|
  | L0 | 0 | 0 | fixture traffic only |
  | L1 | 174 | 33,408,000 | **1× the modeled worst case** (§1.3) |
  | L2 | 348 | 66,816,000 | 2× |
  | L3 | 696 | 133,632,000 | 4× |
  | L4 | 1,392 | 267,264,000 | 8× |
  | L5 | 2,784 | 534,528,000 | 16× — at or beyond any credible sustained DDR3L rate for this access shape |

  Climb until `STALL_FRAMES > 0`. The rung at which stalls begin is a
  recorded rig figure (it is *not* a product claim).

- **M2 — service-window throttle (deterministic over-subscription).** Reduce
  `SVC_WINDOW_LIMIT` so the external path is granted fewer cycles per frame
  than the fixture provably needs. This reaches the stall deterministically,
  at any bandwidth, on any board — so the control cannot fail merely because
  the board turned out to be faster than the ladder's top rung. **M2 is the
  primary mechanism; M1 is the physical cross-check.**

**Three independent witnesses**, and the control's validity gate requires
all three to agree:

1. **Counters** — `STALL_FRAMES > 0`, `FIRST_STALL_FRAME` set,
   `STALL_CYCLES_MAX > 0`, `OUTPUT_FAULT` set, read back over the control
   link before and after the take.
2. **Hardware strobe** — `stall_strobe` pulses captured on the logic
   analyzer **on the same timebase as LRCLK**, so the stall is localized to
   a frame index independently of the control link.
3. **Audio-domain comparison** — the Phase-D exactness comparison FAILs, and
   the Phase-A `dropout` / `stuck` / `residual` checks FAIL, in the frame
   range the counters and strobe point at.

**Validity gate — NC-1 PASSes (i.e. the control is sound) only when all of:**

- the in-budget control run (L0 with the nominal service window) shows
  `STALL_FRAMES == 0` and PASSes its comparison; **and**
- the over-subscribed run shows all three witnesses firing; **and**
- the three witnesses agree on the frame range; **and**
- the over-subscribed output is **not silent** — the held-sample policy means
  energy is present and *wrong*, which is what makes the failure visible to
  the audio-domain checks.

**If the counters fire but the audio comparison still passes**, the control
is too weak: strengthen it (next M1 rung, or tighter M2 window) and record
the finding. That outcome is **not** a PASS for NC-1.

**If the output goes silent with `STALL_FRAMES == 0`**, the take is
**`NO_VERDICT`** and the *instrumentation* is the suspect — not the design,
and certainly not a stall "accounted within reserve". Silence with zero
counters is exactly the ambiguity NC-1 exists to abolish; it must never be
written down as either a stall or a pass.

### 9.3 The rest of the control set

| ID | Targeted failure | Mechanism | Must do |
|---|---|---|---|
| NC-2 | a capture compared against the wrong build | run with a manifest whose `BUILD_ID` / bitstream hash / clock configuration deliberately mismatches the programmed image | **invalidate the comparison** (`NO_VERDICT`), never silently compare |
| NC-3 | hand-aligning a framing error into agreement | capture with deliberately misconfigured sample framing (wrong interface rate; or a build with a wrong BCLK/LRCLK ratio) | FAIL at step 0-6 or the framing check; it must be impossible to rescue by re-fitting `d` |
| NC-4 | per-instance effect state shared instead of duplicated | build a variant where two same-class effect slots share one history buffer, run fixture (c) | FAIL the wet comparison. (Root `CLAUDE.md` requires this control; two Delay slots are two delay histories.) |
| NC-5 | a dropped or truncated tail passing | build a variant that truncates the tail early, run fixture (d) | FAIL the tail check before the end guard |
| NC-6 | an unobservable stereo error | swap left/right (and separately, invert one channel) on fixture (f) | FAIL routing / channel identity. If it reports `UNOBSERVABLE`, the fixture is wrong and must be replaced |
| NC-7 | a stale or empty capture reading as a pass | arm the capture ring, then read it back **without** running the fixture; separately, replay a previous session's buffer | `NO_VERDICT` by frame-index and `BUILD_ID` mismatch; a stale buffer must never grade |
| NC-8 | an effect substituted by a generic passing as the original | replace a fixture preset's reverb with a generic one, keeping the unmodified wet reference | FAIL the wet comparison; and the preset is recorded as *adapted*, never as supported |
| NC-9 | wrong effect order passing | permute the effect chain order on fixture (b) | FAIL the wet comparison |

Each control is run **live** in the session it certifies, and its transcript
is kept. A control from an earlier session does not certify a later one.

---

## 10. Evidence to retain (bundle layout)

```
captures/<session-id>/
  session.json        rig identity: board, revision, power source, DAC,
                      config pads, cables, capture interface + serial,
                      instruments, host, repo commit, declared limit table,
                      declared latency L, declared analysis band, end guard,
                      readback: true|false
  manifest.json       build manifest (B-2): commit, source blob hashes,
                      ROM/asset hashes, tool + build number, part, clock
                      configuration (exact ratios), utilization with
                      denominators, timing slacks, bitstream sha256,
                      reference render hashes
  binding.json        constraint-binding record (B-3)
  detect.txt          programmer detection transcript
  program.txt         programming transcript, every attempt (B-5, B-6)
  framing.txt         LRCLK-count gate transcript (step 0-6)
  vectors/            the exact event vectors sent, per take
  counters/           counter snapshots before/after every take
  digital/            on-chip ring readbacks + logic-analyzer captures
  takes/              analog recordings, unmodified, 48 kHz / 24-bit
  controls/           one transcript per negative control, incl. NC-1's
                      ladder and both mechanisms
  analysis.json       per-check, per-take verdicts + coverage counts
  VERDICTS.md         the verdict table, with every NOT_RUN still listed
```

Nothing in the bundle is edited after the fact. A failed take is kept and
labeled, not deleted; a repaired take is a new take.

---

## 11. Reconciliation with `gf180-dx7#31` (H09)

**Access and status, stated plainly.** `gf180-dx7` was readable at
2026-10-02 (§13 S8): issue #31 (H09, "FPGA digital capture") is **OPEN** and
has produced **no committed procedure document** — the repository's `docs/`
tree carries `H08-PIN.md` and `H10-GF180-FEASIBILITY.md` but no H09 capture
document. Its prerequisite D01 **is** committed
(`docs/PHYSICAL-CONSTRAINTS.md`). So **"shared verbatim" is not available**:
there is no sibling procedure text to share. This section therefore
reconciles against (a) H09's committed acceptance clauses, and (b) the prior
art H09 itself names — the parasynth bring-up and capture discipline (§13
S3, S4), which both repositories draw on.

### 11.1 Clause-by-clause against H09's acceptance

| H09 acceptance clause | Here | Shared or different |
|---|---|---|
| Captured digital PCM agrees with vectors after **declared** latency (alignment documented) | D-4, D-5 | **Shared in substance**: declared `L`, integer equality, searching `L` forbidden |
| Clock configuration and measured sample framing recorded | B-2, 0-6, framing check | **Shared** |
| Resource utilization reported for this exact build | B-2 | **Shared** |
| Bitstream hash recorded; reruns reproducible | B-2, B-5 | **Shared** |
| Negative control: build/clock identity mismatch invalidates the comparison | NC-2 | **Shared** |
| LRCLK-count check against reference before any audio claim | 0-6 (mandatory gate) | **Shared**, and made a blocking gate rather than an advisory step |
| `srccheck`-equivalent: built file set equals simulated file set | B-1 | **Shared** |
| H09 negative control: misconfigured framing must fail, not be hand-aligned | NC-3 | **Shared** |
| H09 non-goal: audio-codec / analog color claims | §3 Leg A | **Different**: this procedure adds a *calibrated analog leg*, kept strictly separate and never substituted for the digital leg (see 11.2) |

### 11.2 Where this procedure differs, and why

1. **An analog leg exists.** H09 is digital-capture-only and defers analog
   explicitly. This instrument's product is a live analog line output, and
   AGENTS.md requires hardware audio captures to have their own
   alignment/calibration procedure — so Phase A exists, adapted in method
   from the sibling's committed analog capture procedure (frozen ρ/g/d,
   declared band, end guard, measure-don't-re-align). It is firewalled from
   Leg D by §3's rule, so adding it cannot weaken the exactness claim. No
   codec or analog-color claim is made here either.
2. **External writable memory, and a stall control.** Neither sibling leg
   exercises external writable memory: the DX7 core's state is operator
   state, and the parasynth ULX3S bring-up had "No SRAM, no SDRAM" at the
   pinned commit. This instrument's binding constraint is tens of MiB of
   delay/reverb history at 48 kHz, so §9.1's service/stall instrumentation
   and §9.2's NC-1 are **additions with no sibling counterpart**. This is
   also why the board decision diverges (§11.3).
3. **Stereo identity is observable, and must be.** The sibling's R0 is
   dual-mono, so it correctly reports channel identity as `UNOBSERVABLE`.
   This instrument is stereo by contract, so fixture (f) makes left ≠ right
   and NC-6 requires a swap to FAIL. Importing the sibling's
   `UNOBSERVABLE` disposition would be a silent loss of coverage.
4. **Wet presets, long tails, patch-change continuity.** Effects are part of
   this product. Fixtures (b)–(e), step D-8, Phase R, and controls NC-4,
   NC-5, NC-8, NC-9 have no sibling counterpart because neither sibling has
   a wet-preset contract.
5. **Per-instance state is a first-class fixture.** Fixture (c) and NC-4
   exist because "two Delay slots = two delay histories" is a product rule
   here.

### 11.3 Board divergence from `gf180-dx7` D01, stated openly

D01 records the ULX3S (ECP5 LFE5U-25F) as "the org's proven FPGA pattern" —
status **confirmed as a pattern** — and separately records "ULX3S is
sufficient for the DX7 core" as **assumed, not established**. It names no
product board for DX7. This document selects a **different** board
(§2.6), and that is not a contradiction of a sibling decision:

- D01's own status labels leave the sufficiency question open, by design.
- The requirement that decides here — ≥ 64 MiB of external *writable* audio
  memory — has no DX7 counterpart, and it is the criterion the ULX3S fails
  (§2.3).
- The ULX3S remains this repository's secondary target for the
  open-toolchain / file-set-parity leg, where external memory is not
  exercised — so the "proven pattern" is retained rather than discarded.

What stays shared regardless of board: the **method** — declared-latency
alignment, the LRCLK gate, source-set assertion, build manifests bound to
source hashes, constraint-binding records, transcript-is-not-a-readback, and
the identity-mismatch control. Those are the seams plan §7 asks the two
efforts to share, and none of them is board-specific. Trigger **T5** (§2.7)
re-opens this section if H09 later commits a procedure that diverges.

---

## 12. Reuse and provenance note (#25)

This document **adapts method and vendors no code, no constraint file, no
pin table and no tables of third-party values.** Specifically:

- The parasynth substrate named in #23 and in
  [`docs/REUSE-AUDIT.md`](REUSE-AUDIT.md) ("Parasynth FPGA bring-up …
  **Adapt after board selection** (SXT-030)") was read for guidance only.
  Nothing was copied. The audit's cautions are honored rather than
  inherited: vendor-derived pin attribution is left **outside** this
  repository (§4.2), board wrappers are not copied, and constraints are to
  be regenerated against the selected board and bound by a record (B-3).
- Board facts are cited to the vendor's own pinned board-support files and
  product page (§13); no vendor file is reproduced here.
- Any later *code* adoption — a constraint generator seeded from a vendor
  master file, a host/capture tool adapted from a sibling — goes through
  #25's reuse-audit process with a pinned source, attribution, tests and a
  local negative control. **This document authorizes no adoption.**

---

## 13. Sources, pinned

| ID | Source | Pin / retrieval | What was taken |
|---|---|---|---|
| S1 | This repository: `contracts/profile-v1-DRAFT.md`, `reports/sxt-017/cost-closure.json`, `reports/sxt-017/EVIDENCE.md` | tree as of this commit | the §1.1 requirement figures, the E1/E2/E3 assumptions, the `EXCEEDS` rows, the DRAFT candidate budgets, and the `DRAFT-NOT-FROZEN` / `stop_escalate` status |
| S2 | This repository: `reports/sxt-026/EVIDENCE.md` §5 | tree as of this commit | the §1.2 measured traffic shape, the logical-vs-physical distinction, the unison-16 worst-case fixture shape |
| S3 | `2AMLogic/gf180-parasynth`, `fpga/` tree | `cbcc8b9e10e49c84f630550e2e145cc6da8a659c` (the pin named in #23 and `docs/REUSE-AUDIT.md`) | method only: ULX3S/iCE40 wrapper and `boards/*.lpf` structure, `spi_host.py` / `link_budget.py` / `scripts/pll_search.py` approach, `Makefile` `srccheck` + `provenance` discipline, and the stated absence of any external RAM in that bring-up |
| S4 | `2AMLogic/gf180-parasynth`, `fpga/ARTY.md`, `docs/capture-r0.md` | `294b435537354801895ecfadbe9f23b617d27e4e` (default branch, 2026-10-02) | method only: Arty bring-up and capture discipline — build/XDC binding records, publication binding, programming-transcript-is-not-a-readback, the frozen ρ/g/d calibration model, declared analysis band and end guard, the limits-table shape, and the dual-mono `UNOBSERVABLE` caveat this document deliberately does not inherit; also the R2 utilization figures used as a scale reference in §2.5 |
| S5 | `Digilent/vivado-boards` board-support files: `new/board_files/arty-a7-100/E.0/1.1/{board.xml,mig.prj,part0_pins.xml}`, `new/board_files/nexys-a7-100t/D.0/1.3/{board.xml,mig.prj}`, `new/board_files/genesys2/H/{board.xml,mig.prj}` | `36f34ab687b7fa9c778b779d027f3bce63b3ace9` (default branch, retrieved 2026-10-02) | part names, memory component descriptions and device part numbers, `DataWidth`, `TimePeriod`, the 48-pin bank-35 DDR3 pin count, and the Pmod/shield user-IO pin counts |
| S6 | ULX3S product page, `radiona.org/ulx3s/` | retrieved 2026-10-02 | "ECP5 LFE5U-85F-6BG381C (84K LUT)", "32MB SDRAM 166 MHz", "56 GPIO pins … PMOD compatible pinout", 25 MHz on-board clock, 3.5 mm 4-contact jack. SDRAM **bus width is not stated there** and is `assumed` 16-bit in §2.4's peak figure |
| S7 | `Digilent/digilent-xdc`, `Arty-A7-100-Master.xdc` | `00a3404901f35aa9567b01ecb3f2c233b6efe9f4` (default branch, retrieved 2026-10-02) | the fact that it declares **no** `ddr3_*` port (so MIG supplies them) and that its Pmod/`ck_io` sections are the generator input for B-3. **No pin assignment is transcribed into this repository.** |
| S8 | `2AMLogic/gf180-dx7`: issue #31 (H09), issue #5 (D01), `docs/PHYSICAL-CONSTRAINTS.md`, `docs/H08-PIN.md`, `docs/` listing | default branch `5ab1fab48fb42282074f4f8ad27aaed434547fca`, read 2026-10-02 | H09's acceptance clauses and non-goals, D01's board/clock/DAC rows with their status labels, and the observation that no H09 procedure document exists yet |

---

## 14. Status register for this document

| Item | Status |
|---|---|
| Board selected with sourced rationale (bandwidth, memory, pin budget) | **PASS** (§2) — a design decision, not a measurement |
| Capture/calibration procedure committed with concrete steps | **PASS** (§4–§7, §10) |
| Over-subscription → measured-stall negative control specified | **PASS** (§9.2) |
| Reconciled with `gf180-dx7#31` (H09) | **PASS** (§11): not shareable verbatim (no sibling document exists yet); clause-by-clause reconciliation with differences explained |
| Any live hardware measurement here | **NOT_RUN** — and out of scope by #23's non-goals |
| Fabric adequacy of the selected board for this instrument's RTL | **NOT_RUN** (§2.5) |
| Sustained external-memory efficiency on the selected board | **NOT_RUN** (§2.4; measured at step D-7) |
| Latency, underrun, stall figures | **NOT_RUN** — #304 |
| Wrapper instrumentation of §9.1 (registers, load generator, strobe) | **PASS in simulation only** (#316, `reports/SXT-030/EVIDENCE.md`); on hardware **NOT_RUN** — #304 |
| FPGA synthesis / place-and-route / timing / power for this instrument | **NOT_RUN** — and not claimed anywhere in this document |
| Any hardware-playback, Surge-fidelity or preset-quality claim | **none made** |
