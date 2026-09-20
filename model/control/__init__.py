"""SXT-021 model control plane over patch images.

Deterministic timed control: reset, event queue, note allocation/stealing,
patch changes, audio framing, continuous-output path through a clearly-named
stub engine, and worst-case schedule accounting.

Conventions are declared in `model/control/README.md` and are normative for
`rtl/control/` (exact schedule equality at every declared checkpoint).

This package is the CONTROL PLANE ONLY. It makes no DSP, fidelity, or
preset-quality claim; the engine slot is occupied by `engine_stub_counter.py`
(name carries the repo `*_stub*` negative-control convention).
"""
from .control_model import (  # noqa: F401
    BLOCK_SIZE, EV_RESERVE_PER_BLOCK, EVENT_NOTE_OFF, EVENT_NOTE_ON,
    EVENT_CC, EVENT_PITCH_BEND, EVENT_CHANNEL_PRESSURE, EVENT_PATCH_CHANGE,
    EVENT_TEMPO, N_VOICES, NAME_TO_TYPE, QUEUE_DEPTH, ControlModel, Event,
    quantize_block, render_sequence, sample_of_block,
)
from .accounting import account_schedule, SCHED_CONSTANTS  # noqa: F401
