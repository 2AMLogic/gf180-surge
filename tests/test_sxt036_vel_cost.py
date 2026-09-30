"""SXT-036 (#70) COST-ACCOUNTING tests (pytest, no iverilog, no oracle).

Covers the fifth increment's oracle-independent machinery: the SXT-015 cost
model pins and their drift refusal, the "no SXT-016 probe pins
cyc_modroute_frame" claim and its falsifiability, the modulation-row split
against SXT-015's own counter, the measured cost law and each way of breaking
it, and the derived-cycles bracket.

These are claim-(1)-side / bookkeeping unit tests. They establish nothing
about model-vs-pinned-engine agreement (item 2, NOT_RUN on this host, #96),
nothing about the reference-budget controls (item 5, NOT_RUN), and no
technology, timing or hardware claim: every cycles figure they touch is
DERIVED under a named assumption, never measured.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import vel_cost_accounting as vca            # noqa: E402

TB_VEL = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")
ARTIFACTS = os.path.join(REPO, "reports", "SXT-036", "artifacts")


# ------------------------------------------------------------- SXT-015 pins --
def test_the_pinned_sxt015_cost_model_is_still_the_live_one():
    """Drift tripwire: if SXT-015's cost model moves, this fails loudly in CI
    rather than letting a recorded divergence silently go stale."""
    assert vca.pin_drift(vca.live_sxt015(), vca.PIN_SXT015) == []


@pytest.mark.parametrize("key", sorted(vca.PIN_SXT015))
def test_pin_drift_detects_every_pinned_field(key):
    """K4 must be falsifiable field by field, not just in aggregate."""
    live = vca.live_sxt015()
    mutated = dict(live)
    val = mutated[key]
    mutated[key] = (val + 1) if isinstance(val, (int, float)) else val + "x"
    drift = vca.pin_drift(mutated, vca.PIN_SXT015)
    assert len(drift) == 1 and drift[0].startswith(key + ":")


def test_sxt015_charges_modulation_rows_by_evaluation_scope():
    """The shape this leaf's measurement produced (#239), read off the live
    accounting rather than quoted: rows are charged per EVALUATION, and a
    voice-list row's evaluation count scales with the worst-case voices."""
    import inspect

    from model.resources import accounting
    src = inspect.getsource(accounting)
    assert "mod_cycles = mod_evaluations * REG.cyc_modroute_frame" in src
    assert ('return split["rows_per_frame"] + worst_voices '
            '* split["rows_per_voice"]') in src
    # the retired shape must be gone, not merely shadowed
    assert "_count_modroutes(g) * REG.cyc_modroute_frame" not in src


def test_the_accounting_charges_a_voice_row_once_per_live_voice():
    """Behavioral form of the same claim: the accounted modulation term of
    each named carrier equals (per-frame rows + voice rows x worst voices)
    x cyc_modroute_frame, and the voice term is what makes it differ from
    the retired once-per-frame charge."""
    from model.resources.accounting import account_graph
    from model.resources.params import REG
    rows = vca.graph_rows(vca.CARRIERS + [vca.FIXTURE_CARRIER])
    for path, row in rows.items():
        split = vca.md_row_split(row["g"])
        acct = account_graph(row)
        mr = acct["budget"]["modulation_rows"]
        worst = acct["voice"]["worst_case_voices"]
        assert mr["rows_total"] == split["total"], path
        assert mr["rows_charged_once_per_live_voice"] == split["voice_rows"], path
        assert mr["row_evaluations_per_frame"] == (
            split["global"] + split["scene_rows"]
            + split["voice_rows"] * worst), path
        assert (acct["budget"]["cost_cycles_per_frame"]["modulation"]
                == mr["row_evaluations_per_frame"] * REG.cyc_modroute_frame), path
        retired = split["total"] * REG.cyc_modroute_frame
        if split["voice_rows"] and worst > 1:
            assert acct["budget"]["cost_cycles_per_frame"]["modulation"] \
                != retired, path
        else:
            assert acct["budget"]["cost_cycles_per_frame"]["modulation"] \
                == retired, path


# ------------------------------------------------------- SXT-016 probe claim --
def test_no_committed_probe_pins_the_modulation_row():
    recs = vca.load_probe_records(vca.PROBE_DIR)
    assert len(recs) > 0
    assert vca.probes_replacing(recs, vca.SXT015_ROW) == []


def test_the_probe_claim_detector_is_falsifiable():
    """K5: a record that DOES claim the row must be detected."""
    synthetic = [("synthetic.json",
                  {"sxt015_replacement": {"replaces": vca.SXT015_ROW}})]
    assert vca.probes_replacing(synthetic, vca.SXT015_ROW) == ["synthetic.json"]


def test_probe_rows_that_are_pinned_are_reported_as_pinned():
    """The detector is not vacuous: rows other probes DO replace are found."""
    recs = vca.load_probe_records(vca.PROBE_DIR)
    assert vca.probes_replacing(recs, "cyc_event_frame")
    assert vca.probes_replacing(recs, "cyc_osc_unison_voice_frame")


# ------------------------------------------------------ modulation-row split --
def test_row_split_matches_sxt015s_own_counter_on_every_named_carrier():
    rows = vca.graph_rows(vca.CARRIERS + [vca.FIXTURE_CARRIER])
    from model.resources.accounting import _count_modroutes
    for path, row in rows.items():
        split = vca.md_row_split(row["g"])
        assert split["total"] == _count_modroutes(row["g"]), path


def test_row_split_refuses_when_the_accounting_row_definition_moves():
    """A graph whose split cannot reproduce the counter must REFUSE, not be
    silently compared against a different quantity."""
    graph = {"md": {"g": [1], "s": [{"s": [1, 2], "v": [3]}]}}
    assert vca.md_row_split(graph)["total"] == 4
    import model.resources.accounting as acc
    real = acc._count_modroutes
    try:
        acc._count_modroutes = lambda g: 99
        with pytest.raises(vca.Refuse):
            vca.md_row_split(graph)
    finally:
        acc._count_modroutes = real


def test_the_fixture_carrier_has_no_voice_rows_of_its_own():
    """Why the divergence is invisible on the fixture and needs the named
    carriers: re-derived from graphs.jsonl, not quoted."""
    rows = vca.graph_rows([vca.FIXTURE_CARRIER])
    split = vca.md_row_split(rows[vca.FIXTURE_CARRIER]["g"])
    assert split["voice_rows"] == 0
    assert split["scene_rows"] == 2


def test_every_named_carrier_does_have_voice_rows():
    rows = vca.graph_rows(vca.CARRIERS)
    for path, row in rows.items():
        assert vca.md_row_split(row["g"])["voice_rows"] > 0, path


# ----------------------------------------------------------- measured law ----
def _meas(routes=6, passes=100, frames=120, mul=None):
    evals = routes * passes
    ops = {"passes": passes, "evals": evals, "mul32": mul if mul is not None
           else evals, "add64": evals, "cmp64": 2 * evals, "add32": evals}
    return {"routes": routes, "control_passes": passes, "frames": frames,
            "ops": ops}


def test_the_measured_law_holds_on_a_conforming_run():
    assert all(ok for _n, ok in vca.op_laws(_meas()))


@pytest.mark.parametrize("field,delta", [("passes", 1), ("evals", 1),
                                        ("mul32", -1), ("add64", 2),
                                        ("cmp64", 1), ("add32", -3)])
def test_the_measured_law_is_falsifiable_field_by_field(field, delta):
    m = _meas()
    m["ops"][field] += delta
    assert [n for n, ok in vca.op_laws(m) if not ok]


def test_the_per_frame_shape_mispredicts_whenever_voices_overlap():
    """K1's arithmetic: routes x frames != routes x passes unless every frame
    has exactly one control pass."""
    m = _meas(routes=6, passes=240, frames=120)     # mean 2 live voices
    assert m["routes"] * m["frames"] != m["ops"]["evals"]
    mono = _meas(routes=6, passes=120, frames=120)
    assert mono["routes"] * mono["frames"] == mono["ops"]["evals"]


def test_cycles_bracket_is_a_bracket_and_scales_with_evaluations():
    one = vca.cycles_bracket(1)
    assert one["mac_reading"] < one["alu_reading"]
    assert vca.cycles_bracket(10)["mac_reading"] == 10 * one["mac_reading"]
    assert vca.cycles_bracket(0) == {"mac_reading": 0, "alu_reading": 0}


def test_the_accounted_constant_sits_between_the_two_readings():
    """Recorded, not reconciled: 15 cycles/row/frame is conservative per
    EVALUATION under both readings."""
    one = vca.cycles_bracket(1)
    assert one["mac_reading"] < vca.PIN_SXT015["cyc_modroute_frame"]
    assert one["alu_reading"] < vca.PIN_SXT015["cyc_modroute_frame"]


# ------------------------------------------------------------- measurement ---
def test_ops_line_parsing_and_its_absence():
    assert vca.parse_ops("DONE vel-qmuls=6\nOPS passes=2 evals=6 mul32=6 "
                         "add64=6 cmp64=12 add32=6\n") == {
        "passes": 2, "evals": 6, "mul32": 6, "add64": 6, "cmp64": 12,
        "add32": 6}
    assert vca.parse_ops("DONE vel-qmuls=6\n") is None


def test_the_rtl_still_emits_the_unchanged_done_line_and_the_ops_line():
    """Counters added for this increment must not change the DONE line every
    committed exactness artifact records."""
    tb = open(TB_VEL, encoding="utf-8").read()
    assert '$display("DONE vel-qmuls=%0d", qmul_count);' in tb
    assert '$display("OPS passes=%0d evals=%0d mul32=%0d add64=%0d '\
           'cmp64=%0d add32=%0d",' in tb
    # write-only bookkeeping: outside the reporting $display, a counter may
    # only be DECLARED or INCREMENTED -- never read into a traced value.
    ops_stmt = tb[tb.index('$display("OPS'):]
    ops_stmt = ops_stmt[:ops_stmt.index(");") + 2]
    rest = tb.replace(ops_stmt, "")
    for counter in ("pass_count", "eval_count", "add64_count", "cmp64_count",
                    "add32_count"):
        uses = [ln.strip() for ln in rest.splitlines() if counter in ln]
        assert uses, counter
        for ln in uses:
            assert (ln.startswith(f"int unsigned {counter} ")
                    or ln == f"{counter}++;"
                    or ln == f"{counter} += 2;"), (counter, ln)


def test_counters_do_not_disturb_any_negative_control_anchor():
    """The cost counters are placed clear of every mutation anchor, so the
    landed state/rounding controls keep working byte-for-byte."""
    import vel_negative_controls as vnc
    tb = open(TB_VEL, encoding="utf-8").read()
    for name, subs in vnc.MUTANTS.items():
        for needle, _rep in subs:
            assert tb.count(needle) >= 1, (name, needle)


def test_rom_lift_is_untouched_by_the_counters():
    """tools/vel_param_corners.py lifts vel_rom verbatim; a counter inside it
    would break that generated bench."""
    import vel_param_corners as vpc
    lifted = vpc.lift_rom(open(TB_VEL, encoding="utf-8").read())
    assert "vel_rom" in lifted and "count" not in lifted


def test_trace_stats_counts_passes_live_voices_and_event_rom_reads():
    trace = {"vel_routes": [1, 2, 3],
             "blocks": [
                 {"b": 0, "create": [0], "release": [],
                  "voices": [{"slot": 0}]},
                 {"b": 1, "create": [1], "release": [],
                  "voices": [{"slot": 0}, {"slot": 1}]},
                 {"b": 2, "create": [], "release": [0, 1],
                  "voices": [{"slot": 0}, {"slot": 1}]},
                 {"b": 3, "create": [], "release": [], "voices": []}]}
    st = vca.trace_stats(trace)
    assert st == {"frames": 4, "control_passes": 5, "max_live_voices": 2,
                  "mean_live_voices": 1.25, "event_rom_reads": 4, "routes": 3}


def test_sidecar_truncation_keeps_depths_and_refuses_overreach(tmp_path):
    dest = str(tmp_path / "side.json")
    vca.sidecar_with_routes(vca.VEL_INPUTS, 2, dest)
    full = json.load(open(vca.VEL_INPUTS, encoding="utf-8"))
    cut = json.load(open(dest, encoding="utf-8"))
    assert len(cut["fixture_routes"]) == 2
    assert cut["fixture_routes"] == full["fixture_routes"][:2]
    assert cut["preset"] == full["preset"]
    with pytest.raises(vca.Refuse):
        vca.sidecar_with_routes(vca.VEL_INPUTS, 99, dest)


# --------------------------------------------------------- recorded artifact -
def test_recorded_cost_artifact_keeps_the_oracle_items_not_run():
    d = json.load(open(os.path.join(ARTIFACTS, "cost-accounting.json"),
                       encoding="utf-8"))
    assert d["oracle_dependent_items"] == {"2": "NOT_RUN", "5": "NOT_RUN"}
    assert d["sxt016_probe_coverage"]["records_replacing_row"] == []
    assert d["pins"]["sxt015"]["cyc_modroute_frame"] == 15


def test_recorded_artifact_records_the_shape_divergence_for_every_carrier():
    d = json.load(open(os.path.join(ARTIFACTS, "cost-accounting.json"),
                       encoding="utf-8"))
    for path in vca.CARRIERS:
        c = d["carriers"][path]
        assert c["shape_factor"] > 1.0, path
        assert c["measured_shape_evaluations_per_frame"] == (
            c["row_split"]["global"] + c["row_split"]["scene_rows"]
            + c["row_split"]["voice_rows"] * c["worst_case_voices"])
    fixture = d["carriers"][vca.FIXTURE_CARRIER]
    assert fixture["shape_factor"] == 1.0


def test_recorded_artifact_shows_the_shape_divergence_resolved():
    """#239: the accounting now charges the measured number of evaluations,
    and the artifact says so per carrier (a re-record, not a re-tune: the
    per-evaluation constant is still the placeholder)."""
    d = json.load(open(os.path.join(ARTIFACTS, "cost-accounting.json"),
                       encoding="utf-8"))
    res = d["shape_resolution"]
    assert res["decision_issue"] == 239
    assert res["accounting_charges_the_measured_shape"] is True
    for path in vca.CARRIERS + [vca.FIXTURE_CARRIER]:
        assert res["per_carrier"][path] is True, path
        c = d["carriers"][path]
        assert c["accounting_charges_the_measured_shape"] is True, path
        assert (c["accounted_modulation_cycles_per_frame"]
                == c["measured_shape_evaluations_per_frame"]
                * d["pins"]["sxt015"]["cyc_modroute_frame"]), path


def test_recorded_artifact_dispositions_the_modulation_state_question():
    """The second half of #239's decision: per-voice modulation-source state
    is declared inside voice_base_state_bytes, with no separate row and no
    re-tuned value."""
    d = json.load(open(os.path.join(ARTIFACTS, "cost-accounting.json"),
                       encoding="utf-8"))
    disp = d["state"]["sxt015_modulation_state_disposition"]
    assert disp["decision_issue"] == 239
    assert "voice_base_state_bytes" in disp["decided"]
    assert d["state"]["sxt015_modulation_state_row"] is None
    from model.resources.params import REG
    assert REG.voice_base_state_bytes == 4096
    assert "modulation-SOURCE" in REG.get("voice_base_state_bytes").estimate_ref


def test_recorded_artifact_shows_every_control_fired():
    d = json.load(open(os.path.join(ARTIFACTS, "cost-accounting.json"),
                       encoding="utf-8"))
    for key in ("K1_per_frame_shape", "K2_route_count_blind",
                "K3_attribution", "K4_pin_drift",
                "K5_probe_claim_detector"):
        assert d["controls"][key]["fires"] is True, key
    assert d["controls"]["K6_state_cross_check"]["status"] == "PASS"


def test_recorded_sweep_shows_the_law_across_route_counts():
    d = json.load(open(os.path.join(ARTIFACTS, "cost-accounting.json"),
                       encoding="utf-8"))
    sweep = d["route_table_sweep"]
    assert sorted(int(k) for k in sweep) == list(vca.SWEEP_ROUTES)
    for k, m in sweep.items():
        assert m["ops"]["evals"] == int(k) * m["control_passes"]
        assert m["exactness_verdict"] == "PASS"
    assert sweep["0"]["ops"]["mul32"] == 0
