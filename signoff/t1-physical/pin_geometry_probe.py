#!/usr/bin/env python3
"""Committed pin-geometry probe for the routed-stream input opens (#804).

Companion to open_pin_probe.py (#679 measured WHERE the extraction opens
are; this one measures the GEOMETRY at and above those pins). For one
routed product group: gunzips the committed stream, loads it with the
klayout module from the pinned klayout-tools environment (re-execing
itself through `uvx` when importable `klayout` is absent), resolves the
inverter masters' I-pin rectangles from the pinned cell-library LEF (under
$PDK_ROOT, identity = revision + content hash, never an absolute host
path), places them with each instance's stream transform, and records,
per instance:

  * the absolute pin rectangles and the GDS label position/cluster (the
    labelled M1 shape is what extraction treats as the pin; the LEF rect
    set is what the router may connect to -- they are not the same set,
    and the difference is data, not error);
  * every Via1 cut over each rectangle, split router via vs pdngen stack;
  * a bounded layer-to-layer trace from the label cluster (M1 -> V1 -> M2
    -> V2 -> M3 -> V3 -> M4 -> V4 -> M5, lateral growth capped), with the
    layer it stops at -- a trace that stops is a description of the metal,
    never an openness verdict; openness comes only from the committed
    open_pin_probe.json connectivity record;
  * what sits over the pin: top-level metal shape counts, PDN strap
    overlap + distance (M4/M5 straps measured from the stream, not from
    the request), and M2/M3 shape counts in a +/-3 um window;
  * the row neighbours (masters of the abutting instances left/right).

Writes <group>/pin_geometry_probe.json (or --out PATH with --stream PATH
for a trial stream). One group at a time, sequential, minutes per group;
not a pytest-time run. The record carries no cause claim and no fix claim:
the LVS verdict of the group stays whatever its committed lvs.report.json
records.
"""
import gzip
import hashlib
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "signoff" / "t1-physical"
CELL_LIBRARY = "gf180mcu_fd_sc_mcu9t5v0"
PIN = (ROOT / "signoff" / "requirements.txt").read_text().strip()
PDK_PIN = json.loads((ROOT / "signoff" / "t1-item1" / "pdk-pin.json").read_text())
# gf180mcu.map (libs.tech/klayout/tech): routing layers share one purpose
# layer per metal (NET,SPNET,PIN,VIA all on <l>/0), labels sit on <l>/10.
LAYERS = {
    "M1": (34, 0), "M1N": (34, 10), "V1": (35, 0), "M2": (36, 0),
    "V2": (38, 0), "M3": (42, 0), "V3": (40, 0), "M4": (46, 0),
    "V4": (41, 0), "M5": (81, 0),
}
# Router single-cut vias vs the pdngen M1-M4/M4-M5 stack arrays (cell
# names as the committed streams merge them; verified on ext_mem_instr).
ROUTER_V1_CELLS = ("VIA_Via1_HV", "VIA_Via1_VV")
PDN_VIA_CELLS = ("VIA_via1_2_8960_1800_2_5_1040_1040",
                 "VIA_via2_3_8960_1800_2_5_1040_1040",
                 "VIA_via3_4_8960_1800_2_5_1040_1040",
                 "VIA_via4_5_8960_8960_4_4_1240_1240")
VIA_CELLS = ROUTER_V1_CELLS + PDN_VIA_CELLS
# The trace's lateral-growth hop cap per metal layer (bounded by contract).
TRACE_HOPS = 8
# Full per-instance detail at or below this instance count; aggregates above.
DETAIL_MAX_INSTANCES = 32
# Row height of the GF018hv5v_green_sc9 site (um), for row-neighbour lookup.
ROW_UM = 5.04
# Every inverter master the stream places (klt-extract naming is unrelated).
INV_MASTER_RE = re.compile(re.escape(CELL_LIBRARY) + r"__(clk)?inv(_\d+)?$")


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


def pdk_rel(*parts):
    rev = PDK_PIN["pdk"]["revision"].split()[-1]
    return pathlib.Path("ciel/gf180mcu/versions", rev, "gf180mcuD", *parts)


def resolve_pdk_file(rel):
    """(bytes, None) of a PDK file under $PDK_ROOT, or (None, reason).
    Identity is the content hash; host paths are never recorded."""
    root = os.environ.get("PDK_ROOT")
    if not root:
        return None, "PDK_ROOT is not set; the PDK keeps its own license " \
                     "and is never copied into this repo"
    p = pathlib.Path(root) / rel
    if not p.is_file():
        return None, f"{rel} is missing under PDK_ROOT"
    return p.read_bytes(), None


def lef_irects(lef_text, master):
    """The I pin's Metal1 RECT list (um, cell coordinates) from the LEF."""
    full = f"{CELL_LIBRARY}__{master}"
    m = re.search(r"MACRO %s\b(.*?)END %s\b" % (full, full), lef_text, re.S)
    if not m:
        return None
    p = re.search(r"\bPIN\s+I\b(.*?)END\s+I\b", m.group(1), re.S)
    if not p:
        return None
    return [(float(a), float(b), float(c), float(d)) for a, b, c, d in
            re.findall(r"RECT\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+"
                       r"([-\d.]+)\s*;", p.group(1))]


def measure(group, stream_path, stream_hash, source_name, out_path,
            invoked_argv, conn_path=None):
    import klayout
    import klayout.db as db

    ly = db.Layout()
    ly.read(str(stream_path))
    top = ly.cell(group)
    if top is None:
        raise SystemExit(f"top cell {group} not found in {stream_path}")
    dbu = ly.dbu
    li = {n: ly.layer(*v) for n, v in LAYERS.items()}

    lef_bytes, lef_reason = resolve_pdk_file(
        pdk_rel("libs.ref", CELL_LIBRARY, "lef", f"{CELL_LIBRARY}.lef"))
    if lef_bytes is None:
        raise SystemExit(f"cannot resolve the pinned LEF: {lef_reason}")
    lef_text = lef_bytes.decode(errors="replace")

    # -- instance population -------------------------------------------------
    insts_by_master = {}
    via_insts = {n: [] for n in VIA_CELLS}
    inst_records = []
    for inst in top.each_inst():
        name = ly.cell(inst.cell_index).name
        if name in via_insts:
            via_insts[name].append(inst)
        elif INV_MASTER_RE.match(name):
            insts_by_master.setdefault(name.split("__")[1], []).append(inst)
            inst_records.append((inst, name))
    masters = sorted(insts_by_master)
    if not masters:
        write_json(out_path, {
            "schema": "gf180-surge.pin-geometry-probe/1",
            "group": group, "status": "NO_VERDICT",
            "reason": "no inverter master instances found in the stream; "
                      "the pin selection is empty, so an empty record must "
                      "not pass as a measurement",
        })
        print(group, "NO_VERDICT: no inverter instances", flush=True)
        return

    # -- regions ---------------------------------------------------------------
    def xform_region(cell, lay, trans):
        r = db.Region()
        for s in cell.shapes(li[lay]).each():
            if s.is_polygon():
                r.insert(trans * s.polygon)
            elif s.is_box():
                r.insert(trans * db.Polygon(s.box))
            elif s.is_path():
                r.insert(trans * s.path)
        return r

    def region_of(shapes):
        r = db.Region()
        for s in shapes:
            if s.is_polygon():
                r.insert(s.polygon)
            elif s.is_box():
                r.insert(db.Polygon(s.box))
            elif s.is_path():
                r.insert(s.path)
        return r.merged()

    r_v1_router = db.Region()
    r_v1_pdn = db.Region()
    r_m1_pads = db.Region()
    for name in ROUTER_V1_CELLS:
        cell = ly.cell(name)
        for inst in via_insts[name]:
            r_v1_router += xform_region(cell, "V1", inst.trans)
            r_m1_pads += xform_region(cell, "M1", inst.trans)
    for name in PDN_VIA_CELLS:
        cell = ly.cell(name)
        for inst in via_insts[name]:
            r_v1_pdn += xform_region(cell, "V1", inst.trans)
            r_m1_pads += xform_region(cell, "M1", inst.trans)
    r_v1_router.merge()
    r_v1_pdn.merge()
    r_m1_pads.merge()
    r_v1_all = db.Region()
    r_v1_all.insert(r_v1_router)
    r_v1_all.insert(r_v1_pdn)
    r_v1_all.merge()

    r_cut = {"V1": r_v1_all}
    r_metal = {}
    for m in ("M1", "M2", "M3", "M4", "M5"):
        r = db.Region()
        r.insert(top.begin_shapes_rec(li[m]))
        r_metal[m] = r.merged()
    for v in ("V2", "V3", "V4"):
        r = db.Region()
        r.insert(top.begin_shapes_rec(li[v]))
        r_cut[v] = r.merged()
    for n, reg in list(r_cut.items()) + list(r_metal.items()):
        if reg.count() == 0:
            raise SystemExit(f"layer {n} resolves to no shapes anywhere in "
                             "the stream; the layer table no longer matches "
                             "the PDK map")
    r_m1_top = region_of(top.shapes(li["M1"]).each())
    # The M1 the trace may grow along: top-level routing M1 plus the via
    # cells' M1 pads -- never the standard cells' internal M1 beyond the
    # cluster itself.
    r_m1_route = db.Region()
    r_m1_route.insert(r_m1_top)
    r_m1_route.insert(r_m1_pads)
    r_m1_route.merge()

    # PDN straps measured from the stream: top-level M4/M5 shapes at least
    # 4 um across (the request's strap width is 4.48; routed wires on
    # those layers are 0.28-0.84 across).
    def strap_centers(reg, min_across):
        out = []
        for p in reg.each():
            b = p.bbox()
            across = min((b.right - b.left), (b.top - b.bottom)) * dbu
            if across >= min_across:
                out.append(((b.left + b.right) / 2 * dbu,
                            (b.bottom + b.top) / 2 * dbu))
        return out

    m4c = sorted({round(x, 3) for x, _ in strap_centers(r_metal["M4"], 4.0)})
    m5c = sorted({round(y, 3) for _, y in strap_centers(r_metal["M5"], 4.0)})

    def um(box):
        return [round(box.left * dbu, 4), round(box.bottom * dbu, 4),
                round(box.right * dbu, 4), round(box.top * dbu, 4)]

    def layer_stats(reg, name):
        if reg.count() == 0:
            return None
        return {"layer": name, "shapes": reg.count(),
                "bbox_um": um(reg.bbox()),
                "area_um2": round(reg.area() * dbu * dbu, 4)}

    def label_pin(cell, trans):
        """(Region, [label points in top coords]) of the labelled I pin."""
        labels_raw = []
        labels_abs = []
        for s in cell.shapes(li["M1N"]).each():
            t = s.text
            if t is not None and t.string == "I":
                raw = db.Point(t.trans.disp.x, t.trans.disp.y)
                labels_raw.append(raw)
                labels_abs.append(trans * raw)
        hits = db.Region()
        for s in cell.shapes(li["M1"]).each():
            if s.is_polygon():
                p = s.polygon
            elif s.is_box():
                p = db.Polygon(s.box)
            else:
                continue
            if any(p.bbox().contains(q) for q in labels_raw):
                hits.insert(trans * p)
        return hits.merged(), labels_abs

    def grow(universe, seed):
        reg = db.Region()
        reg.insert(seed)
        for _ in range(TRACE_HOPS):
            g = universe.interacting(reg)
            if g.count() <= reg.count():
                break
            reg = g
        return reg

    def trace(cluster):
        """Bounded M1->..->M5 growth from the pin's labelled cluster, via
        cut layers as the only inter-layer bridges."""
        reached = {}
        reg = grow(r_m1_route, cluster)
        reached["M1"] = layer_stats(reg, "M1")
        stops = "M5"
        for met, via, nxt in (("M1", "V1", "M2"), ("M2", "V2", "M3"),
                              ("M3", "V3", "M4"), ("M4", "V4", "M5")):
            v = r_cut[via].interacting(reg)
            if v.count() == 0:
                stops = met
                break
            reached[via] = layer_stats(v, via)
            nm = r_metal[nxt].interacting(v)
            if nm.count() == 0:
                stops = via
                break
            reg = grow(r_metal[nxt], nm)
            reached[nxt] = layer_stats(reg, nxt)
        return {"reached": {k: v for k, v in reached.items() if v},
                "stops_at": stops, "hops_cap": TRACE_HOPS}

    # row neighbours: same row band, abutting x edges.
    row_index = {}
    for inst, name in inst_records:
        b = (inst.trans * db.Box(
            ly.cell(inst.cell_index).bbox())).bbox()
        row_index.setdefault(round(b.bottom * dbu / ROW_UM), []).append(
            (b.left * dbu, b.right * dbu, name))

    def neighbours(inst, full):
        b = (inst.trans * db.Box(
            ly.cell(inst.cell_index).bbox())).bbox()
        left = right = None
        for l, r, name in row_index.get(round(b.bottom * dbu / ROW_UM), []):
            if name == full and abs(l - b.left * dbu) < 1e-6:
                continue
            if abs(r - b.left * dbu) < 0.01:
                left = name.split("__")[-1]
            if abs(l - b.right * dbu) < 0.01:
                right = name.split("__")[-1]
        return {"left": left, "right": right}

    # -- cross-reference with the committed connectivity record -------------
    conn = None
    if conn_path is None:
        conn_path = BASE / group / "open_pin_probe.json"
    if pathlib.Path(conn_path).is_file():
        conn = json.loads(pathlib.Path(conn_path).read_text())
    open_masters = {}
    if conn:
        for f in conn["findings"]:
            if f["direction"] == "input":
                open_masters.setdefault(f["master"].split("__")[-1],
                                        []).append(f["instance"])

    per_master = []
    for master in masters:
        full = f"{CELL_LIBRARY}__{master}"
        cell = ly.cell(full)
        rects = lef_irects(lef_text, master)
        if not rects:
            raise SystemExit(f"LEF carries no I-pin RECTs for {master}; "
                             "the pin-name source is wrong")
        insts = insts_by_master[master]
        detail = len(insts) <= DETAIL_MAX_INSTANCES
        agg = {"instances": len(insts), "v1_on_cluster": 0,
               "v1_on_rects_not_cluster": 0, "stops": {}, "over_m4_strap": 0,
               "over_m5_strap": 0}
        instances_out = []
        for i, inst in enumerate(insts):
            tr = inst.trans
            absr = [tr * db.Polygon(db.Box(r[0] / dbu, r[1] / dbu,
                                           r[2] / dbu, r[3] / dbu))
                    for r in rects]
            rect_reg = db.Region(absr).merged()
            cluster, labels = label_pin(cell, tr)
            on_cluster = r_v1_all.interacting(cluster)
            on_rects = r_v1_all.interacting(rect_reg)
            agg["v1_on_cluster"] += on_cluster.count() > 0
            agg["v1_on_rects_not_cluster"] += (
                on_rects.count() > 0 and on_cluster.count() == 0)
            t = trace(cluster)
            agg["stops"][t["stops_at"]] = \
                agg["stops"].get(t["stops_at"], 0) + 1
            pin_b = rect_reg.bbox()
            pin_poly = db.Region([db.Polygon(pin_b)])
            over4 = r_metal["M4"].interacting(pin_poly).count() > 0
            over5 = r_metal["M5"].interacting(pin_poly).count() > 0
            agg["over_m4_strap"] += over4
            agg["over_m5_strap"] += over5
            if not detail:
                continue
            cx = (pin_b.left + pin_b.right) / 2 * dbu
            cy = (pin_b.bottom + pin_b.top) / 2 * dbu
            win = db.Region([db.Polygon(db.Box(
                pin_b.left - 6000, pin_b.bottom - 6000,
                pin_b.right + 6000, pin_b.top + 6000))])
            instances_out.append({
                "i": i, "trans": tr.to_s(),
                "origin_um": [round(tr.disp.x * dbu, 4),
                              round(tr.disp.y * dbu, 4)],
                "pin_rects_um": [um(p.bbox()) for p in absr],
                "labels_um": [[round(q.x * dbu, 4), round(q.y * dbu, 4)]
                              for q in labels],
                "label_cluster": layer_stats(cluster, "M1"),
                "v1_on_cluster": [um(b.bbox()) for b in on_cluster.each()],
                "v1_on_rects": [um(b.bbox()) for b in on_rects.each()],
                "v1_router_vs_pdn": {
                    "router_on_rects":
                        r_v1_router.interacting(rect_reg).count(),
                    "pdn_on_rects":
                        r_v1_pdn.interacting(rect_reg).count()},
                "trace": t,
                "over": {
                    "m1_top_shapes":
                        r_m1_top.interacting(pin_poly).count(),
                    "m2_shapes":
                        r_metal["M2"].interacting(pin_poly).count(),
                    "m3_shapes":
                        r_metal["M3"].interacting(pin_poly).count(),
                    "m4_strap_overlap": over4,
                    "m5_strap_overlap": over5,
                    "nearest_m4_strap_center_um": round(
                        min((abs(cx - x) for x in m4c), default=-1), 3),
                    "nearest_m5_strap_center_um": round(
                        min((abs(cy - y) for y in m5c), default=-1), 3),
                    "m2_shapes_in_3um_window":
                        r_metal["M2"].interacting(win).count(),
                    "m3_shapes_in_3um_window":
                        r_metal["M3"].interacting(win).count(),
                },
                "row_neighbours": neighbours(inst, full),
            })
        entry = {
            "master": master,
            "lef_irects_um": rects,
            "instances_total": len(insts),
            "detail": "full" if detail else "aggregates-only",
            "aggregate": agg,
            "isolated_inputs_from_connectivity":
                open_masters.get(master, []),
            "connectivity_instance_count":
                (conn or {}).get("netlist", {}).get("masters", {}).get(full),
        }
        if detail:
            entry["instances"] = instances_out
        per_master.append(entry)

    record = {
        "schema": "gf180-surge.pin-geometry-probe/1",
        "group": group,
        "status": "ok",
        "doc": "Geometry at and above the routed-stream input pins of "
               "every inverter master. Where-is-the-metal only: no cause "
               "claim, no fix claim, no openness verdict -- openness is "
               "the committed open_pin_probe.json connectivity record's "
               "to say. Instance enumeration is the stream's own SREF "
               "order per master (klt-extract's `master_N` names are a "
               "different, non-contractual numbering); master-level "
               "binding to the connectivity findings is by master "
               "identity.",
        "provenance": {
            "pin": PIN,
            "klayout_module": klayout.__version__,
            "argv": invoked_argv,
            "stream_file": source_name,
            "connectivity_record": os.path.relpath(conn_path, ROOT),
            "stream_content_hash": stream_hash,
            "dbu_um": dbu,
            "lef": {
                "pdk_revision": PDK_PIN["pdk"]["revision"],
                "path_in_pdk": str(pdk_rel("libs.ref", CELL_LIBRARY, "lef",
                                           f"{CELL_LIBRARY}.lef")),
                "sha256": "sha256:" + hashlib.sha256(lef_bytes).hexdigest(),
            },
            "layer_table_source": "gf180mcu.map (libs.tech/klayout/tech), "
                                  "recorded as the LAYERS table in this "
                                  "script; presence verified in the stream",
            "pdn_strap_centers_um": {"M4": m4c, "M5": m5c},
            "router_v1_cells": list(ROUTER_V1_CELLS),
            "pdn_via_cells": list(PDN_VIA_CELLS),
        },
        "masters": per_master,
        "summary": {
            "inverter_masters": len(masters),
            "inverter_instances": sum(m["instances_total"]
                                      for m in per_master),
            "masters_with_isolated_inputs": sorted(open_masters),
        },
        "notes": [
            "The LEF I-pin RECT set (what the router may connect to) and "
            "the GDS labelled M1 cluster (what extraction treats as the "
            "pin) are different sets for the wide inverters: the first "
            "LEF rect carries no label and is M1-disconnected from the "
            "label cluster in the flattened stream, joining it only "
            "through the cell's transistor gates.",
            "A trace that stops at a layer describes the metal present, "
            "not an open: only the connectivity record decides openness.",
            "PDN strap overlap is measured from the stream's own M4/M5 "
            "shapes (>= 4 um across), not from the request; routed wires "
            "on those layers are narrower.",
        ],
    }
    if conn:
        for m in per_master:
            got = m["connectivity_instance_count"]
            if got is not None and got != m["instances_total"]:
                raise SystemExit(
                    f"instance count mismatch for {m['master']}: stream "
                    f"has {m['instances_total']}, connectivity record has "
                    f"{got}")
    write_json(out_path, record)
    print(group, "masters:", len(masters), "instances:",
          record["summary"]["inverter_instances"],
          "isolated-input masters:", sorted(open_masters), flush=True)


def main():
    args = sys.argv[1:]
    stream = out = conn = None
    group = None
    it = iter(args)
    for a in it:
        if a == "--stream":
            stream = pathlib.Path(next(it))
        elif a == "--out":
            out = pathlib.Path(next(it))
        elif a == "--conn":
            conn = pathlib.Path(next(it))
        else:
            group = a
    if group is None:
        raise SystemExit(__doc__)
    cleanup = None
    if stream is None:
        gz = BASE / group / f"{group}.gds.gz"
        if not gz.is_file():
            raise SystemExit(f"no committed stream for {group}")
        raw = gzip.decompress(gz.read_bytes())
        source_name = f"{group}.gds.gz"
        scratch = BASE / group / f"{group}.gds"
        scratch.write_bytes(raw)
        stream = scratch
        cleanup = scratch
    else:
        raw = gzip.decompress(stream.read_bytes()) \
            if str(stream).endswith(".gz") else stream.read_bytes()
        source_name = stream.name
    if out is None:
        out = BASE / group / "pin_geometry_probe.json"
    stream_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        # Re-exec under the pinned environment when klayout is not
        # importable, so the measurement always runs against the pinned
        # klayout module (recorded in provenance.klayout_module).
        try:
            import klayout  # noqa: F401
        except ImportError:
            os.execvp("uvx", ["uvx", "--from", PIN, "python",
                              str(pathlib.Path(__file__).resolve()),
                              *args])
        measure(group, stream, stream_hash, source_name, out,
                ["pin_geometry_probe.py", *args], conn_path=conn)
    finally:
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
