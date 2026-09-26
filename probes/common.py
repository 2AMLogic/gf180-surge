"""SXT-016 shared cost-estimation model for kernel probes.

THIS IS AN ESTIMATOR, NOT A MEASUREMENT.

Every number a probe emits is derived from
  (a) an integer op-by-op reference implementation of the CANDIDATE
      arithmetic, written from first principles following the STRUCTURE of
      the pinned Surge algorithms (surge-synthesizer/surge@
      58914e59c608ed4384ba6002e44c3465c58b2e71 and its pinned sst
      submodules; GPL sources READ and cited, never copied), and
  (b) the named technology assumptions in TECH below.

There is no gf180mcu synthesis, place-and-route, or signoff behind any
number here. Cell-area statements are PDK-neutral RELATIVE estimates
(normalized op counts); state memory is reported in bits, separately from
logic. These are experiments for SXT-017 planning, not production blocks.

Determinism: probes use pure integer arithmetic for op counting; the few
analyses that need real math (reverb loop spectral radius) run a FIXED
number of iterations and round to 6 decimals. No timestamps, no floats in
cycle counts. Re-running a probe over the same inputs is byte-identical.
"""
from math import ceil

# ---------------------------------------------------------------------------
# Rates (SXT-015 pins; plan section 3 working hypothesis)
# ---------------------------------------------------------------------------
FS_HZ = 48000
BLOCK_SIZE = 32                      # SURGE_COMPILE_BLOCK_SIZE default (engine)
BLOCK_SIZE_OS = 64                   # OSC_OVERSAMPLING=2 (globals.h:35-37)
OSC_OVERSAMPLING = 2

# Candidate clocks F (plan section 5: gross budget F/Fs per output frame).
# These are CANDIDATE hypotheses; gf180mcu timing closure at any of them is
# NOT verified (no synthesis has been run). See TECH["clock"].
CLOCK_CANDIDATES_HZ = [48_000_000, 96_000_000, 192_000_000, 480_000_000]

# Reserve fraction (policy; SXT-015 params.reserve_fraction, plan section 5:
# "subtract control, transfer, contention, and a declared reserve").
RESERVE_FRACTION = 0.2

# Candidate word lengths (issue SXT-016 inputs).
PHASE_BITS_CANDIDATES = [16, 18, 24, 32]
AUDIO_BITS_CANDIDATE = 24            # audio path fixed at 24-bit for v0 probes
COEFF_BITS = 32                      # coefficient / pitch-math word (candidate)
SINC_TABLE_PHASES = 256              # FIRipol_M = 256 (SurgeStorage.h:86)
SINC_TABLE_PHASE_BITS = 8            # FIRipol_M_bits = 8 (SurgeStorage.h:87)
SINC_TAPS = 12                       # FIRipol_N = 12 (SurgeStorage.h:88; SXT-015 pin)

# ---------------------------------------------------------------------------
# NAMED technology assumptions.  Every probe record embeds the subset it
# uses; probes/validate.py refuses records that do not name their model.
# ---------------------------------------------------------------------------
TECH = {
    "technology_note": (
        "PDK-neutral relative estimates. 'Logic' is reported as normalized op "
        "counts (multiply/add/lut/shift) and cycles under a named sequential "
        "schedule; no gf180mcu synthesis, place-and-route, timing signoff, or "
        "layout has been run. State memory is reported in bits and kept "
        "separate from logic. gf180mcu cell/memory-macro feasibility at the "
        "candidate clocks is NOT verified."
    ),
    "clock": (
        "A-CLK: F in {48, 96, 192, 480} MHz are CANDIDATE clock hypotheses "
        "for the closure formula; none is verified achievable in gf180mcu "
        "(no synthesis run). The closure check is arithmetic on the formula "
        "in plan section 5 only."
    ),
    "multipliers": {
        # One sequential multiply-accumulate unit; a w x w multiply wider than
        # the unit runs as ceil(w/unit)^2 partial-product passes (adds fused).
        "M18": {"unit_bits": 18, "assumption": "A-DSP-1a: one 18x18->36 MAC, 1 pass/cycle; wider multiplies decompose into ceil(w/18)^2 sequential passes."},
        "M24": {"unit_bits": 24, "assumption": "A-DSP-1b: one 24x24->48 MAC, 1 pass/cycle; wider multiplies decompose into ceil(w/24)^2 sequential passes."},
        "M32": {"unit_bits": 32, "assumption": "A-DSP-1c: one 32x32->64 MAC, 1 pass/cycle; wider multiplies decompose into ceil(w/32)^2 sequential passes."},
    },
    "adder": (
        "A-ALU-1: add/sub/compare/shift on <=32-bit two's-complement words "
        "cost 1 cycle at every candidate clock. NOT verified by timing "
        "analysis; at 480 MHz a 32-bit carry chain may need pipelining, "
        "which would raise add costs proportionally."
    ),
    "onchip_sram": (
        "A-MEM-1: on-chip state RAM is a single-port 1RW synchronous SRAM "
        "macro, 1-cycle read OR write, no dual-port; a same-macro read+write "
        "pair serializes (2 cycles). Dual-macro duplication (2x bits, read "
        "and write in one cycle) is named A-MEM-2 where a probe uses it."
    ),
    "table_rom": (
        "A-MEM-3: on-chip coefficient/waveform tables are synchronous ROM or "
        "SRAM, 1-cycle read, one lookup per cycle."
    ),
    "external": {
        # cycles_per_word = sustained cycles per 32-bit word (latency amortized
        # by streaming); latency_cycles = first-word latency per re-seek.
        "E1": {"bus_bits": 16, "cycles_per_word": 24, "latency_cycles": 30,
               "burst": False,
               "assumption": "A-EXT-1: external 16-bit asynchronous SRAM, ~24 cycles per 32-bit word sustained, ~30-cycle first-access latency, no burst."},
        "E2": {"bus_bits": 16, "cycles_per_word": 4, "latency_cycles": 10,
               "burst": True,
               "assumption": "A-EXT-2: external 16-bit synchronous SRAM, burst, 4 cycles per 32-bit word sustained, 10-cycle latency per re-seek."},
        "E3": {"bus_bits": 32, "cycles_per_word": 2, "latency_cycles": 8,
               "burst": True,
               "assumption": "A-EXT-3: external 32-bit synchronous SRAM/PSRAM, burst, 2 cycles per 32-bit word sustained, 8-cycle latency per re-seek."},
    },
    "division": (
        "A-ALU-2: no division in any audio-rate path. Divisions in the source "
        "algorithms are replaced by multiply-by-precomputed-inverse with the "
        "inverse recomputed at coefficient rate (named per probe where used)."
    ),
    "simd": (
        "A-SCHED-1: scalar single-lane schedule. The pinned engine uses SSE "
        "4-wide unison/filter lanes; a 4-lane hardware datapath could reduce "
        "per-instance cycles for shared work. NOT modeled; scalar numbers are "
        "conservative for throughput, optimistic for area."
    ),
}

MEM_WORD_BYTES = 4  # SXT-015 traffic accounting word (float32 convention)


# ---------------------------------------------------------------------------
# Op counting
# ---------------------------------------------------------------------------
class OpCounter:
    """Counts audio-rate operations of a candidate fixed-point kernel.

    Probes execute their arithmetic through this counter, so emitted op
    counts are structural (they come from the written kernel, not from
    asserted constants). Pure integers; width is declared per op so the
    multiplier schedule is honest.
    """

    def __init__(self):
        self.mul_counts = {}   # width_bits -> count
        self.add_counts = {}   # width_bits -> count (add/sub/cmp folded; A-ALU-1)
        self.lut_calls = []    # (table_name, entries) per lookup
        self.sram_read = 0
        self.sram_write = 0
        self.ext_read_words = 0
        self.ext_write_words = 0
        self.shift_count = 0
        self.state_bits = {}   # name -> bits (per instance)

    def mul(self, width):
        self.mul_counts[width] = self.mul_counts.get(width, 0) + 1

    def add(self, width=32):
        self.add_counts[width] = self.add_counts.get(width, 0) + 1

    def sub(self, width=32):
        self.add(width)

    def cmp(self):
        self.add(1)

    def shift(self, n=1):
        self.shift_count += n

    def lut(self, name, entries):
        self.lut_calls.append((name, entries))

    def sram_r(self, n=1):
        self.sram_read += n

    def sram_w(self, n=1):
        self.sram_write += n

    def ext_r(self, words):
        self.ext_read_words += words

    def ext_w(self, words):
        self.ext_write_words += words

    def state(self, name, bits):
        self.state_bits[name] = self.state_bits.get(name, 0) + bits

    # -- derived totals -----------------------------------------------------
    def ops_dict(self):
        d = {
            "mul_by_width": {str(k): v for k, v in sorted(self.mul_counts.items())},
            "add_sub_cmp_by_width": {str(k): v for k, v in sorted(self.add_counts.items())},
            "shift": self.shift_count,
            "lut_lookups": len(self.lut_calls),
            "lut_detail": [
                {"table": n, "entries": e}
                for n, e in sorted(self.lut_calls, key=lambda t: (t[0], t[1]))
            ],
            "sram_reads": self.sram_read,
            "sram_writes": self.sram_write,
            "ext_read_words": self.ext_read_words,
            "ext_write_words": self.ext_write_words,
        }
        d["mul_total"] = sum(self.mul_counts.values())
        d["add_total"] = sum(self.add_counts.values())
        return d

    def state_bits_total(self):
        return sum(self.state_bits.values())

    def state_detail(self):
        return dict(sorted(self.state_bits.items()))


def mul_cycles(width_bits, multiplier):
    """Sequential partial-product schedule on one MAC unit (A-DSP-1*)."""
    unit = TECH["multipliers"][multiplier]["unit_bits"]
    n = ceil(width_bits / unit) if width_bits > 0 else 0
    return n * n


def op_cycles(ops, multiplier):
    """Cycle cost of an op multiset under the named sequential schedule."""
    c = 0
    for w, n in ops.mul_counts.items():
        c += mul_cycles(w, multiplier) * n
    # A-ALU-1: every add/sub/cmp is 1 cycle regardless of width <= 32.
    c += sum(ops.add_counts.values())
    c += ops.shift_count
    c += len(ops.lut_calls)  # A-MEM-3: 1-cycle table read
    c += ops.sram_read       # A-MEM-1: 1-cycle per access, no dual port
    c += ops.sram_write
    return c


def sram_pair_note():
    return ("A-MEM-1: read+write pairs to one macro serialize; probes count "
            "each access as one cycle (a dual-macro layout A-MEM-2 would hide "
            "the write behind the next read at 2x state bits).")


# ---------------------------------------------------------------------------
# External-memory transaction model
# ---------------------------------------------------------------------------
def ext_access_cycles(words, model, contiguous_burst=True):
    """Cycles for one external access event under a named E-model."""
    e = TECH["external"][model]
    if words <= 0:
        return 0
    per_word = e["cycles_per_word"] * (words * (32 / e["bus_bits"]))
    if not e["burst"] or not contiguous_burst:
        # no burst: pay latency per word
        return int(e["latency_cycles"] * words + per_word)
    return int(e["latency_cycles"] + per_word)


def ext_sustained_bytes_per_s(clock_hz, model):
    e = TECH["external"][model]
    words_per_s = clock_hz / e["cycles_per_word"]
    return int(words_per_s * MEM_WORD_BYTES)


# ---------------------------------------------------------------------------
# Plan-section-5 budget closure
# ---------------------------------------------------------------------------
def closure(clock_hz, cost_cycles_per_frame, control=0, transfer=0,
            contention=0, reserve=RESERVE_FRACTION):
    """gross = F/Fs; dsp_budget = gross*(1-reserve) - control - transfer
    - contention; closure compares complete-patch cost against it.
    Arithmetic only: no timing feasibility claim."""
    gross = clock_hz / FS_HZ
    budget = gross * (1.0 - reserve) - control - transfer - contention
    return {
        "clock_hz": clock_hz,
        "sample_rate_hz": FS_HZ,
        "gross_cycles_per_frame": round(gross, 6),
        "reserve_fraction": reserve,
        "control_cycles_per_frame": round(control, 6),
        "transfer_cycles_per_frame": round(transfer, 6),
        "contention_cycles_per_frame": round(contention, 6),
        "dsp_budget_cycles_per_frame": round(budget, 6),
        "cost_cycles_per_frame": round(cost_cycles_per_frame, 6),
        "closure": "within_budget" if cost_cycles_per_frame <= budget
        else "OVERFLOW",
        "note": "plan section 5 formula; arithmetic on candidate clocks "
                "(A-CLK) and placeholder-free only where probes replace "
                "SXT-015 entries",
    }
