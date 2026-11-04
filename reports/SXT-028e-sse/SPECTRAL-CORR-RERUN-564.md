# SXT-028e-sse negative controls: shared #110 `spectral_corr` re-run (#564)

Claim scope: the model-vs-model negative-control record only. No claim about
the RTL, the pinned Surge oracle, or sound quality.

## Method
`python3 -I tools/distortion_sse_negative_controls.py --out <scratch>`, one local
run (~22 s), diffed against the committed record (`spectral-corr-rerun-564.diff`,
#110 re-run-diff method), then copied over `negative-controls/`.

## Environment (this run) vs declared
| | declared | this run |
|---|---|---|
| platform | Linux aarch64, glibc 2.41 | Linux x86_64, glibc 2.39 |
| CPython | 3.14.7 | 3.12.3 |
| numpy | 2.5.3 | 1.26.4 (as imported under `python3 -I`) |
| stimulus_digest | ed759d67...b306 | ed759d67...b306 (equal) |

The environment differs from the declared one, so the record's `environment`
block now states this run's environment. The stimulus digest matches, so the
non-spectral fields were expected to reproduce; they were checked, not assumed.

## Result
- Stimulus digest equal: PASS.
- Every non-spectral field (max/rms, verdicts, statuses, ok): unchanged. The
  only differing JSON values are `spectral_corr` fields and the `environment` block.
- Overall status `ALL-CONTROLS-OK`; every control verdict unchanged.
- 20 `spectral_corr` values moved (new key `spectral_corr_definition` added next
  to each). Largest moves: FX model 7 leg 0.9821 -> 0.9618, NC-A 0.8414 -> 0.7601.
  NC-C's spectral leg crosses 0.98 (0.9640 -> 0.9873) with no verdict change, as
  #165 predicted.
- Tests: `tests/test_spectral_corr_single_definition.py` + `tests/test_sxt028e_sse.py`: 72 passed.

## Not established
`spectral_corr` residue is numpy-build dependent (see the record's
`spectral_corr_note`); these values are exact only under the environment above.
Not byte-for-byte identical to an aarch64/glibc 2.41 host for spectral fields.
