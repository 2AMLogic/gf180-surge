# SXT-015 — Resource accounting model (`model/resources/`)

Deterministic accounting over the SXT-011 normalized patch graphs
(`corpus/normalized/graphs.jsonl`, engine pin
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`).

**This is a bookkeeping model.** It computes complete-patch worst-case
structure: voice/FX instance counts, per-instance state, memory
transactions, event timing, and budget closure. It is NOT an area or cycle
measurement (SXT-016), NOT a profile freeze (SXT-017), and NOT a fidelity,
support, or preset-quality claim. No hardware claim is made anywhere.

## Layout

| File | Contents |
|---|---|
| `accounting.py` | `account_graph(line, fx_instance_limit, event_profile)` — one graph in, one account out; analysis failures fail closed |
| `fx_classes.py` | per-instance FX class table (state bytes, external/on-chip tier, per-frame transactions) |
| `params.py` | the single source of every number: value, unit, kind, provenance |
| `schema.json` | field-by-field reference for the account result object |

Parameter kinds: `engine_constant` (fact read from the pinned GPL tree —
cited, never copied), `policy` (this repository's declared convention),
`placeholder` (named default that SXT-016/023/028 must replace), and
`corpus_derived` (computed from committed data).

## Units and formulas

- Rates: sample rate 48 kHz; transactions are **per output frame** (= per
  sample at Fs) in 4-byte words; bandwidth = bytes/frame x 48 000.
- State: bytes of float32 working storage per instance.
- Voice worst case: `min(polylimit, voice_pool_limit)` simultaneous voices;
  a Dual-mode note consumes **two** pool voices (`voices_per_note = 2`);
  per-note scene voices are drawn from one shared pool (plan section 3).
- Unison-oscillator instances (worst case): `worst_case_voices x max over
  active scenes (sum of effective unison over active osc slots)`.
- Budget closure (plan section 5): `gross = F/Fs` cycles per output frame;
  `dsp_budget = gross x (1 - reserve)`; complete-patch cost =
  voice + FX (enabled, route-active instances) + modulation row
  **evaluations** + events; `cost > dsp_budget` => explicit
  `budget_overflow` rejection. Never squeezed.
- Modulation rows are charged by **evaluation scope** (decision #239, from
  SXT-036's measured law `route evaluations = routes x per-voice control
  passes`): a global-list or scene-list row once per frame, a **voice**-list
  row once per worst-case live voice per frame —
  `row_evaluations_per_frame = rows_per_frame + worst_case_voices x
  rows_per_voice`, each evaluation costing `cyc_modroute_frame`. The split is
  reported in `budget.modulation_rows`. In dual/split scene modes this is an
  upper bound (a pool voice is resident in exactly one scene), in the same
  conservative style as the per-voice osc/filter terms. Row *counts* are
  unchanged; what changed is how many times a row is charged.
- External classification: a writable state class larger than
  `external_threshold_bytes` (64 KiB) is **external writable memory**; flash
  holds assets only and is **never** counted as delay/reverb storage.
- Instance vs type: every configured slot gets its own instance entry with
  its own state; `distinct_type_count` is reported separately. Two Delay
  slots = two delay histories, always.

## The ESTIMATE-REF discipline

Where an exact constant could not be pinned from the referenced source, the
parameter carries an `ESTIMATE-REF` marker naming the citation and what
SXT-016/023/024/028 must replace. The live list is in `params.py`
(`REG.to_json()`); the significant items:

| Parameter | Default | What SXT-016/023 must replace |
|---|---|---|
| `delay_max_length_samples` | 1<<18 | sst `Delay.h:200` `max_delay_length{1<<18}` — re-pin in SXT-023 and confirm per-channel line + traffic semantics |
| `delay_mod_margin_semitones` | 12 | modulatable delay-time range (`Delay.h setvars`, `dly_mod_depth`) — SXT-023 |
| `floaty_delay_max_length_samples` | 1<<19 | sst `FloatyDelay.h:164` — SXT-023 |
| `reverb1_*` | revbits 15, 16 taps | sst `Reverb1.h:122-131` composite buffer layout — SXT-024 |
| `reverb2_*` | 131072 x 16 buffers + predelay 1 536 000 | sst `Reverb2.h:63-72, 209-214` — SXT-028 |
| `chorus_*`, `flanger_*`, `rotary` | pinned constants | cited in `fx_classes.py` `_PINNED_REFS` |
| `unverified_fx_state_bytes` | 1 MiB | per-class pinned state for every not-yet-verified class — SXT-028 leaf issues |
| `ext_bandwidth_budget_bytes_per_s` | 800 MB/s | named placeholder; SXT-016 + DX7 H01/H02 arbitration alignment (plan section 7) |
| `clock_hz` | 480 MHz | named placeholder clock; SXT-016 replaces with a measured gf180mcu timing assumption |
| `cyc_*` (all) | placeholder-v0 | **every** cycle number is a named placeholder; they make the closure machinery executable and support no technology claim |
| `voice_*_state_bytes`, `osc_state_bytes_per_unison`, `lfo_state_bytes`, `wt_working_set_bytes` | placeholders | re-derive at the selected fixed-point word lengths — SXT-016 |

Engine facts read (not copied) from the pinned tree: `MAX_UNISON=16` and
`DEFAULT_POLYLIMIT=16` (`src/common/globals.h:64,68`); `n_lfos_voice=6`,
`n_lfos_scene=6` (`src/common/SurgeStorage.h:74-76`); scene-mode ids
(`SurgeStorage.h:168-171`); `max_delay_length=1<<18`
(`src/common/dsp/Effect.h:137`); `FIRipol_N=12` (`SurgeStorage.h:87`).

## Fail-closed behavior

- An input line with `st != "normalized"` returns `status:
  "analysis_failure"` with **null** cost objects — no default costs, ever.
- A scene-mode id outside {0,1,2,3} is `scene_mode_unaccountable` =>
  `analysis_failure`.
- Overflow of any declared limit (FX instances, budget, external bandwidth,
  event queue) is an explicit rejection object in `rejections`; the model
  never squeezes silently.
- Unison outside 1..MAX_UNISON is clamped to the engine-declared maximum and
  recorded as `unison_out_of_range` with the raw value.
- FX classes without a verified structure are counted at a conservative
  placeholder and flagged (`class_state_unverified`); they can never silently
  look cheap.
- A `no_long_buffer` class is promoted out of that placeholder only by its own
  SXT-028 leaf, via `_NO_LONG_BUFFER_MEASURED` in `fx_classes.py`: the entry
  carries the measured per-instance bytes, the artifact field they were read
  from, and the frozen model revision they were measured against
  (`fx_class_spec(...)["pinned_reference"]`), and the class drops
  `class_state_unverified`. Promoted so far: **Conditioner**, 2,444 B from
  SXT-028b (`reports/SXT-028b/artifacts/buffer-requirement.json`,
  `on_chip_state.bytes`); drift between the two is a test failure
  (`tests/test_sxt015_fx_classes.py`). Every other class in the tier keeps the
  8,192 B placeholder. Promotion changes **state accounting only** — the
  per-frame cycle figure stays the shared `cyc_fxgeneric_frame` placeholder,
  and nothing here is a fidelity, RTL, or hardware claim.
- A `pinned` **traffic** row is likewise re-derived from the leaf that can
  measure it, never hand-patched — but correcting a traffic row *downward*
  **relaxes a bandwidth budget**, so it is not a free improvement: it can turn
  a previously-failing `ext_bandwidth_fit` column into a passing one. Where
  that lands inside a record already escalated to an operator decision, the
  correction is **held, not banked**, and the hold is declared in
  `_RETAINED_OVER_ESTIMATE_TX` (`retained_over_estimate(<class key>)`) with the
  measured figure, the leaf artifact it came from, the numeric cost of the
  correction, and what retires the hold. Held so far: **Reverb 2**, kept at
  40 reads / 18 writes against SXT-028f's measured and structurally-derived
  29 / 17 (finding F-028f-2, issue #127) — see
  `reports/sxt-017/EVIDENCE.md` §10 for the full before/after and why it waits
  on #12. A retained row must be **conservative componentwise** (never an
  under-estimate) and must be *declared*: an undeclared disagreement is a stale
  row, and `tests/test_sxt015_fx_classes.py` fails on one. Those tests also
  prove the row is *consumed* — flipping it by a known delta must move the
  accounting output by exactly the predicted amount, so a decorative table
  cannot pass.

## Reproduce

```sh
python3 tools/account_corpus.py            # corpus scan + examples + negative controls
python3 - <<'EOF'
import json
from model.resources.accounting import account_graph
line = json.loads(open('corpus/normalized/graphs.jsonl').readline())
print(json.dumps(account_graph(line), sort_keys=True, indent=1))
EOF
```

Outputs are byte-identical for identical inputs (sorted keys, no clocks).
The corpus scan result lives in `reports/sxt-015/corpus-accounting.json`;
worked examples in `reports/sxt-015/examples/`; negative controls in
`reports/sxt-015/negative-control/`.

## Provenance / licensing

This package is original to this repository (Apache-2.0 per `LICENSE`). The
pinned Surge engine and sst libraries are GPL-3.0-or-later and live outside
the repository; their constants and behavior were **read and cited**, and no
Surge source code, tables, algorithm lists, or preset payloads are copied
into this repository. Reuse-audit obligations are tracked in
`docs/REUSE-AUDIT.md` (Parasynth's whole-voice bookkeeping style was adapted
as method only, per issue #10's reusable-substrate note; its arithmetic is
rejected DSP).
