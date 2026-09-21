# SXT-021 control fixtures (`fixtures/control/`)

Continuous-output recordings of the **timed control plane through the named
stub engine slot** (`model/control/engine_stub_counter.py` /
`rtl/control` `audio_stub_slot`). Every committed sequence is rendered
through BOTH the model (`model/control/`) and the RTL (`rtl/control/`) with
**byte-identical stereo recordings** and EXACT schedule equality
(snapshots, decisions, drop records) checked by
`tools/compare_control_rtl.py`.

**Claim scope:** control/timing skeleton only — scheduling, framing,
bounded latency, bounded overload detection. **No DSP, no fidelity, no
preset-support, no musical-quality, no hardware claim.** The "audio" is a
deterministic stub counter, not synthesis. Stereo output framing
(interleaved 16-bit L/R, 32-sample blocks @ 48 kHz) is declared here for
SXT-025 integration.

## Layout

```
sequences/ctl-*-vN.json   input event sequences (source of truth; ids stable,
                          content-hashed in manifest.json; regenerate with
                          generate_control_sequences.py — must be byte-identical)
<id>/model_trace.json     model render: per-block decisions, drops, statuses,
                          snapshots, output samples
<id>/model_out.bin        model stereo recording (interleaved u16 LE L,R x 32/block)
<id>/rtl_trace.txt        RTL trace (T/E/X/M lines; see tools/compare_control_rtl.py)
<id>/rtl_out.bin          RTL stereo recording (byte-identical to model_out.bin)
<id>/verdict.json         comparator verdict (PASS requires exact equality + byte identity)
<id>/record.json          characterization: latency bound, steals, flushes, overload statuses,
                          underruns, declared-schedule closure
manifest.json             sha256 of every artifact + per-fixture records
```

## Sequences (v1)

| id | What it proves | Overload expected? |
|---|---|---|
| `ctl-notes-steal-v1` | 8-voice allocation (seq-poly-8-v1 chord), oldest-active stealing, recorded CC/bend/pressure/tempo, quantize-up latency (max 24 samples) | no |
| `ctl-patch-change-v1` | v1 HARD-SWITCH patch change: voices cleared, queued events flushed (recorded, count carried), deterministic post-switch state; max latency 31 samples | no |
| `ctl-burst-overload-v1` | 12 coincident events > declared 8/block reserve: `event_reserve_exceeded` flagged, 4 events spill with bounded latency growth (32 samples), no drops, schedule accounting does NOT close | flagged, no drops |
| `ctl-queue-overflow-v1` | 30 coincident events > reserve AND > 16-deep queue: 14 explicit `queue_overflow` drop records (in-model statuses AND in-DUT X records) — detected bounded overload, never silent | flagged + drops |

Underruns are zero in all committed fixtures (continuous output at the
profile rate for the full fixture duration).

## Regenerate / re-verify

```sh
python3 fixtures/control/sequences/generate_control_sequences.py   # byte-identical
python3 tools/render_control_fixtures.py                           # full re-render + compare
```

Requires `iverilog` for the RTL leg; the committed artifacts were produced
with Icarus Verilog 13.0. Determinism: identical inputs ⇒ byte-identical
artifacts (asserted by `tests/test_sxt021_control.py` when iverilog is
present; the model leg alone is checked everywhere).
