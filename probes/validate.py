"""SXT-016 record validation.

Every probe record MUST name its technology assumptions before it may be
written to reports/sxt-016/probes/. A record with an unstated clock,
memory implementation, or word length is INVALID and is excluded from
SXT-017 inputs (issue #11 acceptance: "a probe with an unstated
clock/memory assumption fails review and is excluded").

validate_record returns (ok, errors); emit() refuses to write invalid
records, so an under-specified probe fails loudly instead of silently
contributing numbers.
"""
from .common import CLOCK_CANDIDATES_HZ, FS_HZ, TECH

# Fields every record must carry, regardless of kernel class.
REQUIRED_FIELDS = [
    "probe",
    "kernel",
    "clock_hz_candidates",
    "sample_rate_hz",
    "word_lengths",
    "memory_model",
    "assumptions",
    "structure_citations",
    "ops",
    "cycles_per_frame",
    "state_ram_bits",
    "ext_bytes_per_frame",
    "closure_at_clocks",
    "sxt015_replacement",
    "status",
]

REQUIRED_WORD_LENGTH_KEYS = ["audio_bits", "multiplier"]
REQUIRED_MEMORY_KEYS = ["name", "onchip_sram", "external"]

VALID_STATUSES = ["ESTIMATE", "ESTIMATE_WITH_PLACEHOLDER_COMPONENTS"]


def validate_record(rec):
    """Return (ok, errors) for one probe record."""
    errors = []
    for f in REQUIRED_FIELDS:
        if f not in rec:
            errors.append("missing required field: %s" % f)
    if errors:
        return False, errors

    # Clock must be an exact member of the declared candidate set.
    clocks = rec.get("clock_hz_candidates")
    if not isinstance(clocks, list) or not clocks:
        errors.append("clock_hz_candidates must be a non-empty list")
    else:
        for c in clocks:
            if c not in CLOCK_CANDIDATES_HZ:
                errors.append("clock %r is not a declared candidate" % (c,))
        if sorted(clocks) != sorted(CLOCK_CANDIDATES_HZ):
            errors.append("clock_hz_candidates must name the full candidate "
                          "set %r" % (CLOCK_CANDIDATES_HZ,))

    if rec.get("sample_rate_hz") != FS_HZ:
        errors.append("sample_rate_hz must be %d" % FS_HZ)

    # Word lengths: audio width + multiplier always; phase width required for
    # any record that declares a phase accumulator (oscillator kernels).
    wl = rec.get("word_lengths")
    if not isinstance(wl, dict):
        errors.append("word_lengths must be a dict")
    else:
        for k in REQUIRED_WORD_LENGTH_KEYS:
            if k not in wl:
                errors.append("word_lengths missing %s" % k)
        mult = wl.get("multiplier")
        if mult is not None and mult not in TECH["multipliers"]:
            errors.append("multiplier %r is not a named candidate" % (mult,))
        ab = wl.get("audio_bits")
        if ab is not None and not (isinstance(ab, int) and 1 <= ab <= 32):
            errors.append("audio_bits %r out of range" % (ab,))
        if rec.get("has_phase_accumulator") and "phase_bits" not in wl:
            errors.append("phase-accumulating kernel must name phase_bits")

    # Memory model must be named, both on-chip and external, with text.
    mm = rec.get("memory_model")
    if not isinstance(mm, dict):
        errors.append("memory_model must be a dict")
    else:
        for k in REQUIRED_MEMORY_KEYS:
            if k not in mm or not mm.get(k):
                errors.append("memory_model missing %s" % k)
        ext = mm.get("external")
        if isinstance(ext, dict):
            if not ext.get("name"):
                errors.append("memory_model.external missing name")
            elif ext["name"] not in TECH["external"] and ext["name"] != "none":
                errors.append("external model %r is not a named candidate"
                              % (ext["name"],))

    # Assumptions and citations must be present and non-empty.
    if not isinstance(rec.get("assumptions"), list) or not rec["assumptions"]:
        errors.append("assumptions must be a non-empty list")
    if (not isinstance(rec.get("structure_citations"), list)
            or not rec["structure_citations"]):
        errors.append("structure_citations must be a non-empty list")

    # Cycles must be plain numbers (ints), not floats or None.
    cpf = rec.get("cycles_per_frame")
    if not isinstance(cpf, (int, float)) or isinstance(cpf, bool):
        errors.append("cycles_per_frame must be numeric")
    if isinstance(cpf, float) and cpf != int(cpf):
        errors.append("cycles_per_frame must be an integer count")

    # Per-clock closure must exist for every named candidate clock.
    cl = rec.get("closure_at_clocks")
    if not isinstance(cl, dict):
        errors.append("closure_at_clocks must be a dict keyed by clock")
    else:
        for c in (clocks or []):
            if c not in cl:
                errors.append("closure_at_clocks missing %r" % (c,))

    # SXT-015 replacement bookkeeping must be explicit.
    rep = rec.get("sxt015_replacement")
    if not isinstance(rep, dict) or "replaces" not in rep:
        errors.append("sxt015_replacement.replaces must be stated "
                      "(param name or 'none')")

    if rec.get("status") not in VALID_STATUSES:
        errors.append("status must be one of %r" % (VALID_STATUSES,))

    # Determinism: no timestamps or non-deterministic fields allowed.
    for banned in ("timestamp", "generated_at", "date", "now"):
        if banned in rec:
            errors.append("non-deterministic field forbidden: %s" % banned)

    return (len(errors) == 0), errors


def make_invalid_record():
    """A deliberately under-specified record (negative control fixture).

    It looks like a plausible probe output but omits the memory
    implementation, states no word lengths, and invents an off-list clock.
    """
    return {
        "probe": "probe_fx_delay",
        "kernel": "delay_stereo",
        # clock candidates: invented value, not from the candidate set
        "clock_hz_candidates": [70000000],
        "sample_rate_hz": FS_HZ,
        # word_lengths omitted entirely
        # memory_model omitted entirely
        "assumptions": [],
        "structure_citations": [],
        "ops": {"mul_total": 100},
        "cycles_per_frame": 1234,
        "state_ram_bits": 0,
        "ext_bytes_per_frame": 0,
        "closure_at_clocks": {},
        "sxt015_replacement": {},
        "status": "ESTIMATE",
    }
