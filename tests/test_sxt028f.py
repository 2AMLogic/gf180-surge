"""SXT-028f Reverb 2 leaf tests (pytest).

Covers: the frozen constant/structure inventory, model determinism,
per-instance independence, the two pinned behaviours that are easy to
"fix" wrongly (the LF-damping ramp is never stepped; suspend does not
clear the tank), allocation-profile equivalence (the RTL bench profile is
only legal because it produces identical output and refuses to alias),
tail presence and decay, external-memory accounting, the fail-closed
extraction records, and the committed negative-control / RTL-exactness
records (fail-closed, frozen-revision pinned).

Oracle-dependent legs no longer run *here* -- they run on a host with the
pinned oracle (tools/render_reverb2_fixtures.py,
model/effects/run_reverb2_model.py, tools/compare_reverb2_reference.py,
tools/reverb2_reference_controls.py, issue #126) and commit their records.
What this file enforces about them is integrity, not a verdict: a
comparison may exist only for a carrier whose reference passed the 3x
bit-identical gate, it must be pinned to the live frozen-model revision,
it must be scoped to the Reverb 2 class, and the three issue-named
carriers -- all REFUSED by that gate -- must carry no fixture and no
comparison at all.
"""
import json
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-reverb 2"))

import reverb2_model as rm  # noqa: E402
from reverb2_model import (  # noqa: E402
    Reverb2Model, Reverb2Params, ProfileRefusal, ENGINE_PROFILE,
    HARNESS_PROFILE, MAX_ALLPASS_LEN, MAX_DELAY_LEN, PREDELAY_BUFFER_SIZE,
    PREDELAY_BUFFER_SIZE_LIMIT, NUM_ALLPASSES, NUM_BLOCKS, BLOCK,
    TAP_GAIN_L, TAP_GAIN_R, ms_to_samples, model_revision,
    per_sample_transactions,
)
from model.resources.fx_classes import retained_over_estimate  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028f")
INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")

PARAMS_A = dict(predelay_f=-4.0, room_size_f=0.0, decay_time_f=0.75,
                diffusion_f=1.0, buildup_f=1.0, modulation_f=0.5,
                lf_damping_f=0.2, hf_damping_f=0.2, width_f=0.0, mix_f=1.0)
PARAMS_B = dict(predelay_f=-6.0, room_size_f=-0.35, decay_time_f=1.6,
                diffusion_f=0.62, buildup_f=0.83, modulation_f=0.9,
                lf_damping_f=0.55, hf_damping_f=0.71, width_f=-3.0,
                mix_f=0.4)


def make(params=None, name="t", profile=HARNESS_PROFILE):
    m = Reverb2Model(Reverb2Params(dict(params or PARAMS_A)), name, profile)
    m.initialize()
    return m


def noise(n_blocks, seed=7, amp=1 << 20):
    rs = random.Random(seed)
    return [([rs.randint(-amp, amp) for _ in range(BLOCK)],
             [rs.randint(-amp, amp) for _ in range(BLOCK)])
            for _ in range(n_blocks)]


# ------------------------------------------------------------- structure
def test_frozen_engine_constants():
    assert (NUM_BLOCKS, NUM_ALLPASSES) == (4, 12)      # 4 input + 4x2
    assert MAX_ALLPASS_LEN == 16384 * 8 == 131072
    assert MAX_DELAY_LEN == 16384 * 8 == 131072
    assert MAX_DELAY_LEN & (MAX_DELAY_LEN - 1) == 0    # masked ring
    assert PREDELAY_BUFFER_SIZE == 48000 * 8 * 4 == 1536000
    assert PREDELAY_BUFFER_SIZE_LIMIT == 48000 * 8 * 3 == 1152000
    assert ENGINE_PROFILE.words == 3633152
    assert ENGINE_PROFILE.words * 4 == 14532608
    # tap gains: the engine's float32 literals divided by 4, Q13.18
    assert TAP_GAIN_L == TAP_GAIN_R == (98304, 78643, 65536, 52429)
    # msToSamples at scale 1: sr * ms * 0.001f truncated toward zero
    assert ms_to_samples(80.3, 1.0) == 3854
    assert ms_to_samples(178.8, 1.0) == 8582
    assert ms_to_samples(4.76, 1.0) == 228


def test_calc_size_matches_pinned_tables():
    m = make()
    assert m.st.tap_l == [3854, 2846, 4689, 5884]
    assert m.st.tap_r == [1704, 4876, 3547, 3854]
    assert m.st.dl_len == [8582, 6072, 5092, 6691]
    assert m.st.ap_len[:4] == [228, 326, 486, 802]     # input allpasses
    assert len(m.st.ap_len) == 12


def test_per_sample_transaction_count_is_structural():
    d = per_sample_transactions()
    assert d == {"reads": 29, "writes": 17}
    m = make()
    for il, ir in noise(8):
        m.process_block(il, ir)
    n = 8 * BLOCK
    assert m.st.ext_reads == 29 * n
    assert m.st.ext_writes == 17 * n


# ----------------------------------------------------------- determinism
def test_model_determinism():
    outs = []
    for _ in range(2):
        m = make()
        o = [m.process_block(il, ir) for il, ir in noise(24)]
        outs.append((o, m.st.checkpoint()))
    assert outs[0] == outs[1]


def test_dual_instance_independent_histories():
    a = make(PARAMS_A, "a")
    b = make(PARAMS_B, "b")
    # long enough for the longest tank delay (8582 samples at scale 1) to
    # recirculate, so the tank accumulator is genuinely loaded
    for il, ir in noise(288, seed=3):
        a.process_block(il, ir)
        b.process_block(ir, il)
    assert a.st.mem is not b.st.mem
    assert (a.st.ap_hash, a.st.dl_hash) != (b.st.ap_hash, b.st.dl_hash)
    assert a.st.tank != b.st.tank
    # ring indices follow the same schedule; only content differs
    assert a.st.pd_k == b.st.pd_k


# ------------------------------------------------- pinned engine quirks
def test_lf_damping_ramp_is_never_stepped():
    """Reverb2.h:478-483 steps every ramp EXCEPT _lf_damp_coefficent, so
    its `.v` holds the PREVIOUS block's target for the whole block while
    the HF ramp (identical class, identical code path) does move."""
    from model.effects.qmath import to_q
    m = make()
    lf_seq = [0.1, 0.4, 0.7, 0.25, 0.9]
    lf_tgt, hf_tgt = [], []
    for i, (il, ir) in enumerate(noise(len(lf_seq))):
        m.p = Reverb2Params(dict(PARAMS_A, lf_damping_f=lf_seq[i],
                                 hf_damping_f=lf_seq[i]))
        m.process_block(il, ir)
        lf_tgt.append(to_q(rm._f32(0.2 * lf_seq[i]), "Q24.43"))
        hf_tgt.append(to_q(rm._f32(0.8 * lf_seq[i]), "Q24.43"))
        assert m.st.lf_damp.new_v == lf_tgt[i]
        assert m.st.hf_damp.new_v == hf_tgt[i]
        # LF: v is exactly what newValue assigned (previous target), never
        # advanced by the 32 per-sample steps
        expect_lf_v = lf_tgt[i] if i == 0 else lf_tgt[i - 1]
        assert m.st.lf_damp.v == expect_lf_v, i
        assert m.st.lf_damp.dv != 0 or i == 0
        # HF: same class, but it IS stepped, so it has left its start value
        if i > 0:
            assert m.st.hf_damp.v != hf_tgt[i - 1], i


def test_suspend_does_not_clear_the_tank():
    m = make()
    for il, ir in noise(16):
        m.process_block(il, ir)
    before = (m.st.tank, m.st.ap_hash, m.st.dl_hash, m.st.pd_hash)
    assert before != (0, 0, 0, 0)
    m.suspend()
    assert (m.st.tank, m.st.ap_hash, m.st.dl_hash, m.st.pd_hash) == before
    m.initialize()          # the constructor path DOES clear
    assert (m.st.tank, m.st.ap_hash, m.st.dl_hash, m.st.pd_hash) == (0, 0, 0,
                                                                     0)


# -------------------------------------------------- allocation profiles
def test_alloc_profile_equivalence():
    """The reduced bench profile is only legal because it is equivalent."""
    stim = noise(40, seed=17)
    a = make(PARAMS_A, "engine", ENGINE_PROFILE)
    b = make(PARAMS_A, "harness", HARNESS_PROFILE)
    for il, ir in stim:
        assert a.process_block(il, ir) == b.process_block(il, ir)
    assert a.st.tank == b.st.tank
    assert a.st.ext_reads == b.st.ext_reads
    assert a.st.ext_writes == b.st.ext_writes


def test_alloc_profile_refuses_rather_than_aliases():
    tiny = rm.AllocProfile("tiny", 256, 1024, 1024)
    with pytest.raises(ProfileRefusal):
        make(PARAMS_A, "tiny", tiny)
    # a predelay longer than the bench ring is refused, not wrapped. pdt is
    # a processBlock local in the pinned engine, so the refusal fires on the
    # first block, not at init.
    m = make(dict(PARAMS_A, predelay_f=0.0), "longpd", HARNESS_PROFILE)
    with pytest.raises(ProfileRefusal):
        m.process_block([0] * BLOCK, [0] * BLOCK)
    # ... and the same configuration is fine at the engine allocation
    me = make(dict(PARAMS_A, predelay_f=0.0), "longpd-engine", ENGINE_PROFILE)
    me.process_block([0] * BLOCK, [0] * BLOCK)
    assert me.st.pdt == 48000


# ---------------------------------------------------------------- tails
def test_tail_is_present_and_decays():
    m = make(dict(PARAMS_A, mix_f=1.0))
    # the burst must outlast the longest tank delay (8582 samples) so the
    # tank is loaded before the tail window opens
    for il, ir in noise(288):
        m.process_block(il, ir)
    peaks = []
    for _ in range(24):
        pk = 0
        for _ in range(40):
            ol, orr = m.process_block([0] * BLOCK, [0] * BLOCK)
            pk = max(pk, max(abs(v) for v in ol), max(abs(v) for v in orr))
        peaks.append(pk)
    assert peaks[0] > 0, "the render must carry the effect's own tail"
    assert peaks[-1] > 0, "the tail must not be truncated"
    assert peaks[-1] < 0.5 * max(peaks), "the tail must decay (>= 6 dB)"


def test_bypass_is_exactly_transparent():
    m = make(dict(PARAMS_A, mix_f=0.0))
    for il, ir in noise(8, seed=21):
        ol, orr = m.process_block(il, ir)
        assert ol == il and orr == ir


def test_parameter_modulation_into_fx_params_is_refused():
    with pytest.raises(ValueError):
        Reverb2Params(dict(PARAMS_A, mix_f=[0.1] * BLOCK))


def test_unresolved_temposync_flag_is_refused():
    with pytest.raises(ValueError):
        Reverb2Params(dict(PARAMS_A, ts_predelay=None))


# ------------------------------------------------- committed evidence
NAMED_CARRIERS = ("grant_me", "novuo", "harp")
SCREENED_CARRIERS = ("tacobell", "moire1", "mystical")
PARAM_KEYS = ("predelay_f", "room_size_f", "decay_time_f", "diffusion_f",
              "buildup_f", "modulation_f", "lf_damping_f", "hf_damping_f",
              "width_f", "mix_f")


def _input_record(slug):
    with open(os.path.join(INPUTS, f"type-reverb 2-{slug}.json")) as f:
        return json.load(f)


def test_extraction_records_fail_closed():
    """Every carrier record carries resolved inputs or an explicit refusal.

    The temposync flag is now RESOLVED from the native loader read-back
    (#126); `drift_asserted` is still fail-closed and is 0 only where the
    3x render gate actually passed.
    """
    for slug in NAMED_CARRIERS + SCREENED_CARRIERS:
        d = _input_record(slug)
        assert d["census_blob_reverified"] is True
        assert d["source"]["engine_pin"] == (
            "58914e59c608ed4384ba6002e44c3465c58b2e71")
        assert d["instances"], slug
        for inst in d["instances"]:
            assert isinstance(inst["params"]["ts_predelay"], bool), slug
            assert "temposync_source" in inst, slug
            for k in PARAM_KEYS:
                assert isinstance(inst["params"][k], float), (slug, k)
        assert isinstance(d["volume_f"], float), slug
        assert d["drift_asserted"] in (0, None), slug
        # a record may claim a usable reference leg only with a passed gate
        if d["reference_leg"]["usable"]:
            assert d["drift_asserted"] == 0, slug
            assert d["determinism_gate"]["status"] == "PASS", slug
        else:
            assert d["reference_leg"]["refusals"], slug
    # the unlanded-sibling refusal must stay visible for the Distortion carrier
    novuo = _input_record("novuo")
    assert any("unlanded" in r for r in novuo["applicability"]["reasons"])


def test_named_carriers_are_refused_by_the_render_gate():
    """All three issue-named carriers FAIL the 3x bit-identical gate; a
    NOT_RUN/REFUSED leg must never be recorded as a determinism pass."""
    for slug in NAMED_CARRIERS:
        d = _input_record(slug)
        assert d["drift_asserted"] is None, slug
        assert d["determinism_gate"]["status"] == "FAIL", slug
        assert d["applicability"]["complete_wet_render_possible"] is False
        assert d["reference_leg"]["usable"] is False, slug
        # and no fixture bus or comparison may be committed for them
        fx = os.path.join(SXT, "fixtures")
        assert not [f for f in os.listdir(fx) if f.startswith(slug + "__")]
        art = os.path.join(SXT, "artifacts")
        assert not [f for f in os.listdir(art)
                    if f.startswith(f"compare-{slug}__")]


def test_determinism_gate_record():
    with open(os.path.join(SXT, "artifacts", "determinism-gate.json")) as f:
        g = json.load(f)
    assert g["repeats"] == 3
    # the gate's own liveness: carriers with a committed sha256 elsewhere in
    # the repo must pass it AND re-derive byte-identically on this host
    assert g["positive_control"]
    for row in g["positive_control"]:
        assert row["gate_3x"] == "PASS", row
        assert row["byte_identical"] is True, row
    named = [r for r in g["results"] if r["named_carrier"]]
    assert named and all(r["status"] == "REFUSED" for r in named)
    for r in named:
        assert r["refusal_class"] == "determinism-gate"
        assert r["measured"]["max_abs_divergence"] > 0
    passing = {r["slug"] for r in g["results"] if r["status"] == "PASS"}
    assert passing == set(SCREENED_CARRIERS)
    # the bimodal flake control: a carrier that passes a 3x gate most of the
    # time and is still nondeterministic, so "3x passed once" is not a
    # determinism claim on its own. The control is itself intermittent --
    # that IS its point -- so what is asserted is that the screen OBSERVED
    # the bimodality on at least one sequence, not that it must recur on
    # every sequence of every run.
    flake = [r for r in g["stress_screen"] if r["slug"] == "lapharp"]
    assert flake, "the bimodal flake control did not run"
    assert any(r["distinct_wet_buffers"] > 1 and not r["stable"]
               for r in flake), flake
    assert all(r["distinct_dry_buffers"] == 1 for r in flake), (
        "the lapharp nondeterminism is FX-side; a flaky dry bus would make "
        "it a source-side finding instead")
    # the named carriers' refusal is CHARACTERISED, not just asserted: their
    # all-off DRY bus is already unstable, so the nondeterminism sits in the
    # voice path upstream of every FX slot and is a property of the preset,
    # never of fx:Reverb 2.
    named_stress = [r for r in g["stress_screen"]
                    if r["slug"] in NAMED_CARRIERS]
    assert len(named_stress) == len(NAMED_CARRIERS) * 2, named_stress
    for r in named_stress:
        assert r["distinct_dry_buffers"] > 1, r
        assert not r["stable"], r
    for r in g["stress_screen"]:
        if r["slug"] in SCREENED_CARRIERS:
            assert r["stable"], r


def test_carrier_ledger_is_inventory_only():
    d = json.load(open(os.path.join(SXT, "artifacts",
                                    "carrier-ledger.json")))
    assert "NOT a support claim" in d["claim_scope"]
    assert d["totals"]["carriers"] == len(d["carriers"]) > 0
    assert d["totals"]["multi_instance_carriers"] > 0, (
        "the dual-instance acceptance needs real multi-slot carriers")


def test_buffer_requirement_record():
    br = json.load(open(os.path.join(SXT, "artifacts",
                                     "buffer-requirement.json")))
    ext = br["external_writable_memory"]
    assert ext["words_total"] == ENGINE_PROFILE.words == 3633152
    assert ext["bytes_total"] == 14532608
    tr = br["external_traffic"]
    assert tr["measured_matches_structure"] is True
    assert abs(tr["words_per_sample_32bit"] - 46.0) < 1e-9
    assert tr["reads_per_sample"] == 29.0 and tr["writes_per_sample"] == 17.0
    # SXT-015 state is confirmed exactly. The traffic row still disagrees --
    # but it is no longer an UNEXPLAINED disagreement: issue #127 dispositioned
    # finding F-028f-2 as a DELIBERATE conservative hold on the shared table
    # (`_RETAINED_OVER_ESTIMATE_TX`), pending #12. This asserts the disposition,
    # not merely the disagreement, so the record cannot slide back into a stale
    # row and cannot flip to an under-estimate unnoticed.
    rec = br["sxt015_reconciliation"]
    assert rec["state_agreement"] is True
    assert rec["traffic_direction"] in ("agrees", "sxt015_over_estimates"), (
        "SXT-015 now UNDER-estimates Reverb 2 traffic: every downstream "
        "bandwidth result would read optimistic. STOP and reconcile.")
    if rec["traffic_agreement"]:
        # the #12 decision landed and the row was corrected: nothing to hold
        assert rec["sxt015_reads_per_sample"] == tr["reads_per_sample"]
        assert rec["sxt015_writes_per_sample"] == tr["writes_per_sample"]
        assert rec["traffic_over_estimate_is_deliberate"] is False
        assert retained_over_estimate("reverb2") is None, (
            "the row agrees with the measurement, so the retention record "
            "must be retired with it")
    else:
        assert rec["sxt015_reads_per_sample"] > tr["reads_per_sample"]
        assert rec["traffic_over_estimate_is_deliberate"] is True, (
            "an SXT-015 traffic over-estimate must be a RECORDED hold, not a "
            "stale row: declare it in _RETAINED_OVER_ESTIMATE_TX or correct it")
        held = rec["traffic_retention_record"]
        assert held["finding"] == "F-028f-2 (issue #127)"
        assert "#12" in held["unblocks_on"]
        # the hold names the cost it is holding back, in numbers
        assert "ext_bandwidth_fit" in held["reason"]
        assert "EXCEEDS" in held["reason"] and "within" in held["reason"]
    assert "NONE" in br["fit_claim"]


def test_negative_controls_all_live_and_failing():
    d = json.load(open(os.path.join(SXT, "negative-controls",
                                    "negative-controls.json")))
    assert d["status"] == "PASS"
    assert d["model_revision"] == model_revision(), "stale control record"
    assert "model-vs-model" in d["claim_scope"]
    names = set()
    for c in d["controls"]:
        assert c["ok"] is True, c["control"]
        assert "CONTROL-OK" in c["verdict"], c["control"]
        names.add(c["control"].split()[0])
    # the five controls the issue requires, plus bypass and suspend
    assert {"NC-A", "NC-B", "NC-C", "NC-D", "NC-E", "NC-F", "NC-G"} <= names


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == model_revision(), "stale exactness record"
    assert d["alloc_profile"]["profile"] == "harness"
    assert len(d["cases"]) >= 3
    for c in d["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["revision_pin"]["ok"] is True, c["case"]
        assert c["checked"]["outputs"] > 0 and c["checked"]["fields"] > 0
    # dual-instance equality must be among them
    assert any(c["ninst"] == 2 and c["exact"] for c in d["cases"])
    for m in d["mutant_controls"]:
        assert m["ok"] is True, m["case"]
        assert "CONTROL-OK" in m["verdict"], m["case"]
        assert m["exact"] is False, m["case"]
    # liveness: the exercise record must show the mutated quantities are used
    ex = d["mutant_carrier_exercise"]
    assert all(v != 0 for v in ex["tap_read_max_abs_L"])
    assert all(v != 0 for v in ex["tap_read_max_abs_R"])
    assert ex["modulation_fractional_samples"] > 0
    assert ex["ramp_dv_max_abs"][4] != 0       # the LF ramp control's target


def test_model_vs_reference_leg_is_graded_honestly():
    """The oracle leg now RAN (#126). What this test enforces is that every
    committed verdict is traceable to a reproducible reference, is scoped
    to the Reverb 2 class, and records ACHIEVED numbers rather than tuned
    ones; and that no comparison exists for a carrier whose reference is
    not reproducible."""
    art = os.path.join(SXT, "artifacts")
    rows = sorted(f for f in os.listdir(art)
                  if f.startswith("compare-") and f.endswith(".json"))
    assert len(rows) == len(SCREENED_CARRIERS) * 2, rows
    live = model_revision()
    for name in rows:
        with open(os.path.join(art, name)) as f:
            c = json.load(f)
        slug = c["slug"]
        assert slug in SCREENED_CARRIERS, name
        # the graded reference must itself be reproducible
        assert c["reference_determinism_gate"]["bit_identical"] is True
        assert c["reference_determinism_gate"]["drift_asserted"] == 0
        # stale-stub control: the verdict is pinned to the live frozen model
        assert c["model_revision"] == live, name
        # the claim is class-scope only
        for phrase in ("CLASS agreement", "NOT a complete-wet preset"):
            assert phrase in c["claim_scope"], name
        # budgets are the shared [PROPOSED] values, not per-leaf ones
        assert c["proposed_budgets"] == {"max_abs_diff_lsb": 8192,
                                         "rms_diff_dbfs": -46.0,
                                         "spectral_corr_min": 0.98}
        m = c["channels"]["mono"]
        for k in ("max_abs_diff_lsb", "rms_diff_dbfs", "spectral_corr"):
            assert isinstance(m[k], float), (name, k)
        assert c["verdict"].startswith(("PASS", "FAIL"))
        assert "PENDING-FREEZE" in c["verdict"] or c["verdict"].startswith("FAIL")
        assert c["tail_gate_ok"] in (True, False)


def test_reference_backed_negative_controls():
    """NC-A (generic substitute) and NC-B (dropped tail) must still FAIL
    against the REAL reference bundle, and the comparison must not be
    vacuous (NC-REF-0)."""
    p = os.path.join(SXT, "negative-controls", "reference-controls.json")
    with open(p) as f:
        d = json.load(f)
    assert d["model_revision"] == model_revision()
    assert d["status"] == "PASS"
    assert d["cases"]
    wanted = {"NC-REF-0", "NC-A-REF", "NC-B-REF"}
    for case in d["cases"]:
        assert case["baseline_frozen_model"]["ok"] is True, case["slug"]
        names = {c["control"].split()[0] for c in case["controls"]}
        assert wanted <= names, case["slug"]
        for c in case["controls"]:
            assert c["ok"] is True, (case["slug"], c["control"])
            assert "CONTROL-OK" in c["verdict"]
        gen = [c for c in case["controls"]
               if c["control"].startswith("NC-A-REF")][0]
        assert gen["metrics"]["all_pass"] is False
        assert "ADAPTED" in gen["label"]


def test_evidence_separates_coverage_from_agreement():
    """The reference leg creates no support/coverage/quality claim, and the
    named carriers' refusal stays visible in the record."""
    ev = open(os.path.join(SXT, "EVIDENCE.md")).read()
    assert "REFUSED" in ev
    assert "Newly-enabled presets" in ev
    assert "no human listening" in ev.lower() or "#8/#9" in ev
    for slug in ("Grant Me", "Novuo", "Harp"):
        assert slug in ev
