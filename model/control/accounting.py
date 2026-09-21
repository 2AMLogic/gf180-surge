"""SXT-021 worst-case schedule accounting (plan section 5 formula).

Closes the CONTROL-PLANE schedule (control + events + stub slot + transfer +
contention) against the per-sample-period budget `gross x (1 - reserve)`:

    gross [cyc/sample period] = F / Fs          (Fs = 48 kHz engine pin)
    budget                    = gross * (1 - 0.2)   (declared reserve)

Components use the SXT-016 scheduler probe row verbatim
(reports/sxt-016/probes/probe_scheduler__event_queue_and_control__a24__m32__onchip.json):

    control   72 cyc / sample period   (probe `control_cycles_per_frame`)
    event     88 cyc / event           (probe `cycles_per_event`)
    reserve   8 events / block         (probe `max_coincident_events_per_frame`,
                                       fixtures-derived worst coincident burst)
    transfer   8 cyc / sample period   (probe assumption A-CTL-1)
    contention 990 cyc / sample period (probe assumption A-CTL-2)

    stub slot  2 cyc / sample period   (declared HERE as a named placeholder
                                       for the STUB slot; SXT-022+ replaces
                                       it with the real DSP slot cost)

Units note: these are cycles per 48 kHz SAMPLE PERIOD (the plan-section-5
budget unit), not per 32-sample block. The once-per-block control work is
charged conservatively at the probe's full per-sample-period row value, so
the closure carries headroom rather than hidden amortization.

Reconciliation with the SXT-016 probe closure rows: the probe subtracted
control/transfer/contention inside `dsp_budget_cycles_per_frame` and compared
an event-inclusive cost column against it; this module puts every component
on the `used` side of one budget. Both formulations give the same verdicts on
all four candidate clocks (OVERFLOW @48/96 MHz, within_budget @192/480 MHz).

OVERFLOW is an explicit rejection object (never silent), per plan section 5.
These are candidate-clock arithmetic checks under named assumptions — NOT a
gf180mcu timing, synthesis, or hardware claim.
"""
from typing import Dict

SAMPLE_RATE_HZ = 48000
RESERVE_FRACTION = 0.2
CTRL_CYCLES_PER_FRAME = 72
CYCLES_PER_EVENT = 88
EV_RESERVE_PER_BLOCK = 8
TRANSFER_CYCLES_PER_FRAME = 8
CONTENTION_CYCLES_PER_FRAME = 990
STUB_CYCLES_PER_SAMPLE = 2  # named placeholder: the *stub* slot cost

CLOCK_CANDIDATES_HZ = [48000000, 96000000, 192000000, 480000000]

SCHED_CONSTANTS = {
    "sample_rate_hz": SAMPLE_RATE_HZ,
    "reserve_fraction": RESERVE_FRACTION,
    "control_cycles_per_frame": CTRL_CYCLES_PER_FRAME,
    "cycles_per_event": CYCLES_PER_EVENT,
    "ev_reserve_per_block": EV_RESERVE_PER_BLOCK,
    "transfer_cycles_per_frame": TRANSFER_CYCLES_PER_FRAME,
    "contention_cycles_per_frame": CONTENTION_CYCLES_PER_FRAME,
    "stub_cycles_per_sample": STUB_CYCLES_PER_SAMPLE,
    "source": "reports/sxt-016/probes/"
              "probe_scheduler__event_queue_and_control__a24__m32__onchip.json"
              " + plan section 5; stub slot declared in SXT-021",
    "units": "cycles per 48 kHz sample period (F/Fs); block work charged "
             "conservatively at the probe row value",
}


def used_cycles_per_frame(worst_events_per_block: int) -> int:
    return (CTRL_CYCLES_PER_FRAME
            + worst_events_per_block * CYCLES_PER_EVENT
            + STUB_CYCLES_PER_SAMPLE
            + TRANSFER_CYCLES_PER_FRAME
            + CONTENTION_CYCLES_PER_FRAME)


def account_schedule(worst_events_per_block: int = EV_RESERVE_PER_BLOCK,
                     clock_hz: int = 192000000) -> Dict:
    """One closure row: used vs budget at one candidate clock."""
    gross = clock_hz / SAMPLE_RATE_HZ
    budget = gross * (1 - RESERVE_FRACTION)
    used = used_cycles_per_frame(worst_events_per_block)
    overflow = used > budget
    row = {
        "clock_hz": clock_hz,
        "worst_events_per_block": worst_events_per_block,
        "gross_cycles_per_frame": gross,
        "budget_cycles_per_frame": budget,
        "used_cycles_per_frame": {
            "control": CTRL_CYCLES_PER_FRAME,
            "events": worst_events_per_block * CYCLES_PER_EVENT,
            "stub_slot": STUB_CYCLES_PER_SAMPLE,
            "transfer": TRANSFER_CYCLES_PER_FRAME,
            "contention": CONTENTION_CYCLES_PER_FRAME,
            "total": used,
        },
        "utilization_fraction": round(used / gross, 6) if gross else None,
        "closure": "OVERFLOW" if overflow else "within_budget",
    }
    if overflow:
        row["rejection"] = {
            "code": "schedule_budget_overflow",
            "detail": {"used_cycles_per_frame": used,
                       "budget_cycles_per_frame": budget,
                       "clock_hz": clock_hz,
                       "worst_events_per_block": worst_events_per_block},
            "note": "plan section 5 closure: explicit rejection, never "
                    "silent (stop/escalate to SXT-017 as a profile "
                    "violation if the stub cannot close)",
        }
    return row


def closure_table(worst_events_per_block: int = EV_RESERVE_PER_BLOCK
                  ) -> Dict:
    return {
        "constants": SCHED_CONSTANTS,
        "worst_case_events_per_block": worst_events_per_block,
        "closure_at_clocks": {
            str(f): account_schedule(worst_events_per_block, f)
            for f in CLOCK_CANDIDATES_HZ
        },
        "claim_scope": "arithmetic on candidate clocks under named "
                       "assumptions (A-CLK); no gf180mcu synthesis, "
                       "place-and-route, signoff, or hardware claim",
    }
