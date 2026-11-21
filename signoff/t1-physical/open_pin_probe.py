#!/usr/bin/env python3
"""Committed extraction probe for open (single-pin) abstracted-cell pins (#679).

For one routed product group: gunzips the committed stream, runs `klt extract`
with the pinned `klayout-tools` (signoff/requirements.txt) through `uvx`,
parses the extracted SPICE netlist, and writes
`<group>/open_pin_probe.json` listing every abstracted-cell pin that sits on a
net with no other pin (top-level ports excluded). Each finding carries the
instance name as the tool writes it, the pin, the observed net, the master,
that master's instance count in the group, and the pin's direction from the
liberty pinned in signoff/t1-item1/pdk-pin.json (resolved under $PDK_ROOT;
never copied into this repo -- it keeps its own license).

This records WHERE the extraction opens are, nothing else: not why the router
left them, not that LVS can be fixed, not any fidelity or signoff claim.

One group at a time, sequential:
    python3 signoff/t1-physical/open_pin_probe.py <group> [<group>...]
Extraction is minutes-long per group; this is not a pytest-time run.

The corroboration block annotates the committed P&R report's
`def_net_names.single_pin_markers` with the tie-cell subset tally computed
from the record's own findings (#747); re-derive that block alone, without
re-extracting, with:
    python3 signoff/t1-physical/open_pin_probe.py --rederive <group> [...]
"""
import gzip
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "signoff" / "t1-physical"
CELL_LIBRARY = "gf180mcu_fd_sc_mcu9t5v0"
PIN = (ROOT / "signoff" / "requirements.txt").read_text().strip()
PDK_PIN = json.loads((ROOT / "signoff" / "t1-item1" / "pdk-pin.json").read_text())
# Anonymous net numbering is NOT a stable contract (klt extract --help, klayout
# issue #1063): the observed net names in the record are non-contractual.
NET_CAVEAT = (
    "klt extract --help (klayout-tools 0.8.0): anonymous net numbering ('$N' "
    "labels assigned to a net with no drawn label) is NOT a stable contract "
    "across klayout versions or host platforms (issue #1063) -- do not diff "
    "raw netlist text across environments. Net names in this record are "
    "observed values, explicitly non-contractual; no test asserts them."
)
ESCAPE_NOTE = (
    "The extracted SPICE and the LVS report escape these names as \\$21170 "
    "etc.; this record carries the unescaped form ($21170)."
)
# pg_type -> the direction string the record carries for supply/well pins.
PG_TYPE = {"primary_power": "power", "primary_ground": "ground"}
# Tie-cell masters (library-suffixed stems) and their output pin: the only
# findings the pnr single-pin marker count agrees with (measured, #747).
TIE_CELLS = {"tiel": "ZN", "tieh": "Z"}


def tie_cell_tally(findings):
    """Ordered {"master/pin": count} of the unused tie-cell output findings.
    Always computed from the findings themselves -- never hand-typed -- so a
    re-extraction that moves a net out of the tie subset changes the tally
    with it."""
    tally = {}
    for f in findings:
        stem = f["master"].rsplit("__", 1)[-1]
        if TIE_CELLS.get(stem) == f["pin"]:
            key = f"{f['master']}/{f['pin']}"
            tally[key] = tally.get(key, 0) + 1
    return dict(sorted(tally.items()))


def corroboration_block(markers, findings, input_findings):
    """The corroboration block: the committed P&R report's
    def_net_names.single_pin_markers beside the measured decomposition of
    this record's own findings (#747). The marker number agrees exactly with
    the unused tie-cell output subset (tiel/ZN, tieh/Z) of
    summary.single_pin_nets and with nothing else in the record; the
    non-tie single-pin outputs and the open input pins are not corroborated
    by it (this refutes #679's unmeasured "4 open inputs + 42 tie outputs"
    arithmetic for ext_mem_instr: it is 46 tie outputs and 0 inputs). Still
    a cheap corroboration only, not a substitute signal; no cause claim for
    any open."""
    tally = tie_cell_tally(findings)
    tie_total = sum(tally.values())
    return {
        "pnr_single_pin_markers": markers,
        "tie_cell_output_findings": tie_total,
        "tie_cell_output_tally": tally,
        "non_tie_single_pin_findings": len(findings) - tie_total,
        "open_input_findings_not_in_markers": input_findings,
        "marker_scope": "agrees exactly with the unused tie-cell output "
                        "subset (tiel/ZN, tieh/Z) of "
                        "summary.single_pin_nets, not with the total; "
                        "single-pin nets outside that subset are not "
                        "corroborated by it",
        "note": "pnr.report.json def_net_names.single_pin_markers; a "
                "cheap corroboration only, not a substitute signal: "
                "wavetable_core matches with 480 of them",
    }


def klt(group, *args, d=None):
    """The pinned klt through uvx, cwd = the group directory so the argv the
    record stores stays relative (no absolute host paths in the record)."""
    d = BASE / group if d is None else pathlib.Path(d)
    cmd = ["uvx", "--from", PIN, "klt", *map(str, args)]
    return subprocess.run(cmd, cwd=d, capture_output=True, text=True,
                          env={**os.environ, "PDK": "gf180mcuD"})


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


def stream_sha(group, d=None, stream_gz=None):
    d = BASE / group if d is None else pathlib.Path(d)
    stream_gz = f"{group}.gds.gz" if stream_gz is None else stream_gz
    b = gzip.decompress((d / stream_gz).read_bytes())
    return "sha256:" + hashlib.sha256(b).hexdigest()


def gunzip_stream(group, d=None, stream_gz=None):
    """The committed <group>.gds.gz unpacked to a scratch path in the group
    directory (deleted after the run); returns its name relative to the dir.
    #804 trials pass their own directory and stream name."""
    d = BASE / group if d is None else pathlib.Path(d)
    stream_gz = f"{group}.gds.gz" if stream_gz is None else stream_gz
    dst = d / f"{group}.gds"
    dst.write_bytes(gzip.decompress((d / stream_gz).read_bytes()))
    return dst.name


def liberty_path():
    """The pinned liberty under $PDK_ROOT, or (None, reason) when unavailable.
    Identity is the revision + content hash pdk-pin.json records (verified
    against the resolved file's bytes); host paths are never recorded."""
    rev = PDK_PIN["pdk"]["revision"].split()[-1]
    rel = (f"ciel/gf180mcu/versions/{rev}/gf180mcuD/libs.ref/{CELL_LIBRARY}"
           f"/lib/{PDK_PIN['liberty']['name']}.lib")
    want = PDK_PIN["liberty"]["content_hash"]
    root = os.environ.get("PDK_ROOT")
    if not root:
        return None, ("PDK_ROOT is not set; the liberty stays in the PDK "
                      "(not in this repo, license), so pin directions are "
                      "recorded as null")
    p = pathlib.Path(root) / rel
    if not p.is_file():
        return None, (f"PDK_ROOT is set but {rel} is missing under it; "
                      "pin directions are recorded as null")
    got = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    if got != want:
        raise SystemExit(f"liberty under PDK_ROOT does not match the pin: "
                         f"got {got}, pdk-pin.json records {want}")
    return p, None


def liberty_directions(path):
    """{master: {pin: direction}} for every cell in the liberty. Signal pins
    carry their `direction`; pg pins carry their pg_type mapped through
    PG_TYPE (a dangling supply pin is a different condition than a dangling
    input, and neither may pass as `null`, which means liberty-unresolved)."""
    cell_re = re.compile(r"\s*cell\s*\(([^)]+)\)\s*\{")
    pin_re = re.compile(r"\s*pin\s*\(([^)]+)\)\s*\{")
    pg_re = re.compile(r"\s*pg_pin\s*\(([^)]+)\)\s*\{")
    dir_re = re.compile(r"\s*direction\s*:\s*(\w+)\s*;")
    pgtype_re = re.compile(r"\s*pg_type\s*:\s*(\w+)\s*;")
    out = {}
    cell = pin = kind = None
    depth = 0      # brace depth inside the current cell (after its opener)
    pin_depth = 0  # brace depth inside the current pin group
    for line in path.read_text(errors="replace").splitlines():
        if cell is None:
            m = cell_re.match(line)
            if m:
                cell = m.group(1)
                out[cell] = {}
                depth = line.count("{") - line.count("}")
            continue
        depth += line.count("{") - line.count("}")
        if pin is None:
            m = pin_re.match(line)
            if m:
                pin, kind, pin_depth = m.group(1), "signal", 0
                continue
            m = pg_re.match(line)
            if m:
                pin, kind, pin_depth = m.group(1), "pg", 0
                continue
        else:
            pin_depth += line.count("{") - line.count("}")
            m = dir_re.match(line) if kind == "signal" else pgtype_re.match(line)
            if m:
                val = m.group(1)
                out[cell][pin] = PG_TYPE.get(val, val) if kind == "pg" else val
                pin = kind = None
            elif pin_depth < 0:
                pin = kind = None
        if depth <= 0:
            cell = pin = kind = None
    return out


def parse_spice(text, top):
    """(.SUBCKT pin lists, X instances) -> (ports, entries, masters).

    entries is [(instance, pin, net, master)]; `+` continuation lines are
    unwrapped first (the top .SUBCKT line wraps). Every master an X line
    references must have a .SUBCKT pin-name def and every instance's net
    count must equal its master's pin count -- a mismatch means the pin-name
    source is wrong and fails loudly instead of being skipped.
    """
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("+") and lines:
            lines[-1] += " " + s[1:].strip()
        else:
            lines.append(s)
    ports, defs, entries, masters = [], {}, [], {}
    for s in lines:
        if not s or s.startswith("*"):
            continue
        low = s.lower()
        if low.startswith(".subckt "):
            tok = s.split()
            if tok[1].lower() == top.lower():
                ports = tok[2:]
            else:
                defs[tok[1]] = tok[2:]
    for s in lines:
        if not s or s.startswith("*"):
            continue
        low = s.lower()
        if low.startswith(".ends") or low.startswith(".global") \
                or low.startswith(".end"):
            continue
        elif low.startswith("x"):
            tok = s.split()
            inst, master, nets = tok[0][1:], tok[-1], tok[1:-1]
            if master not in defs:
                raise SystemExit(f"no .SUBCKT def for master {master} "
                                 f"(instance {inst}); pin-name source is wrong")
            if len(nets) != len(defs[master]):
                raise SystemExit(
                    f"arity mismatch: instance {inst} of {master} has "
                    f"{len(nets)} nets for {len(defs[master])} pins")
            for pin, net in zip(defs[master], nets):
                entries.append((inst, pin, net.replace("\\", ""), master))
            masters[master] = masters.get(master, 0) + 1
    return ports, entries, masters


def probe(group, d=None, stream_gz=None, out_name="open_pin_probe.json"):
    """Connectivity-probe one routed stream. Defaults keep the committed
    behavior (`<group>/<group>.gds.gz` -> `<group>/open_pin_probe.json`);
    #804 trials pass a trial directory and its own stream/report names,
    so a trial record never overwrites the committed one."""
    d = BASE / group if d is None else pathlib.Path(d)
    stream_gz = f"{group}.gds.gz" if stream_gz is None else stream_gz
    if not (d / stream_gz).is_file():
        raise SystemExit(f"no committed stream for {group}")
    scratch_gds = gunzip_stream(group, d, stream_gz)
    scratch_spice = f"{group}.probe.spice"
    argv = ["extract", scratch_gds, "--deck", "gf180mcu", "--top", group,
            "--abstract-cells", f"{CELL_LIBRARY}__*", "-o", scratch_spice,
            "--format", "json"]
    try:
        p = klt(group, *argv, d=d)
        if p.returncode != 0:
            raise SystemExit(f"klt extract failed ({p.returncode}):\n"
                             f"{p.stdout}\n{p.stderr}")
        summary = json.loads(p.stdout)
    finally:
        (d / scratch_gds).unlink(missing_ok=True)

    entries_text = (d / scratch_spice).read_text()
    ports, entries, masters = parse_spice(entries_text, group)
    port_nets = {x.replace("\\", "") for x in ports}

    lib, lib_reason = liberty_path()
    directions = liberty_directions(lib) if lib else {}
    resolved = lib is not None

    net_pins = {}
    for inst, pin, net, master in entries:
        net_pins.setdefault(net, []).append((inst, pin, master))
    single = {n: v for n, v in net_pins.items()
              if len(v) == 1 and n not in port_nets}

    findings = []
    for net, v in single.items():
        inst, pin, master = v[0]
        findings.append({
            "instance": inst, "pin": pin, "net": net, "master": master,
            "master_instances": masters[master],
            "direction": directions.get(master, {}).get(pin)
                         if resolved else None,
        })
    findings.sort(key=lambda f: (f["instance"], f["pin"], f["net"]))

    dir_tally, findings_dir_tally = {}, {}
    for inst, pin, net, master in entries:
        dd = directions.get(master, {}).get(pin) if resolved else None
        dir_tally[dd] = dir_tally.get(dd, 0) + 1
    for f in findings:
        dd = f["direction"]
        findings_dir_tally[dd] = findings_dir_tally.get(dd, 0) + 1

    # Cheap corroboration from the committed P&R report (not a substitute
    # signal: wavetable_core matches with 480 single-pin markers). A trial
    # that adopted a completed place-and-route driver (#804) has no P&R
    # report (the driver's stdout went to a dead pipe), so markers is None
    # and the corroboration block records the absence instead of a number.
    if (d / "pnr.report.json.gz").is_file():
        pnr = json.loads(gzip.decompress(
            (d / "pnr.report.json.gz").read_bytes()))
        markers = pnr.get("def_net_names", {}).get("single_pin_markers")
    else:
        markers = None

    ver = (summary.get("provenance") or {}).get("klt_version") \
        or summary.get("klt_version")
    record = {
        "schema": "gf180-surge.open-pin-probe/2",
        "group": group,
        "doc": "Every abstracted-cell pin on a net with no other pin "
               "(top-level ports excluded), from `klt extract` of the "
               "committed routed stream. Records where the extraction opens "
               "are; no cause claim, no fix claim. The LVS verdict of this "
               "group stays whatever its committed lvs.report.json records.",
        "provenance": {
            "pin": PIN,
            "klt_version": ver,
            "argv": argv,
            "cwd": os.path.relpath(d, ROOT),
            "stream_file": stream_gz,
            "stream_content_hash": stream_sha(group, d, stream_gz),
            "netlist_sha256": summary.get("netlist_sha256"),
            "netlist_normalized_sha256":
                summary.get("netlist_normalized_sha256"),
            "liberty": {
                "revision": PDK_PIN["pdk"]["revision"],
                "content_hash": PDK_PIN["liberty"]["content_hash"],
                "resolved": resolved,
                "reason": lib_reason,
                "direction_note":
                    "signal pins carry the liberty's `direction`; pg pins "
                    "carry their pg_type (primary_power->power, "
                    "primary_ground->ground); null means the liberty was "
                    "unavailable",
            },
        },
        "netlist": {
            "port_nets": sorted(port_nets),
            "pin_entries": len(entries),
            "nets": len(net_pins),
            "masters": masters,
        },
        "pins_examined": dir_tally,
        "summary": {
            "single_pin_nets": len(single),
            "findings_by_direction": findings_dir_tally,
            "input_findings": findings_dir_tally.get("input", 0),
        },
        "corroboration": corroboration_block(
            markers, findings, findings_dir_tally.get("input", 0)),
        "notes": [NET_CAVEAT, ESCAPE_NOTE],
        "findings": findings,
    }
    (d / scratch_spice).unlink(missing_ok=True)
    write_json(d / out_name, record)
    print(group, "findings:", len(findings), "input:",
          findings_dir_tally.get("input", 0), "pins_examined:",
          dir_tally.get("input", 0), flush=True)


def rederive(group):
    """Recompute the corroboration block of a committed record from its own
    findings (#747) -- no re-extraction: the committed findings already
    carry every (master, pin); provenance, netlist, summary and findings
    are untouched."""
    path = BASE / group / "open_pin_probe.json"
    rec = json.loads(path.read_text())
    rec["schema"] = "gf180-surge.open-pin-probe/2"
    rec["corroboration"] = corroboration_block(
        rec["corroboration"].get("pnr_single_pin_markers"), rec["findings"],
        rec["summary"]["findings_by_direction"].get("input", 0))
    write_json(path, rec)
    print(group, "corroboration re-derived: tie",
          rec["corroboration"]["tie_cell_output_findings"],
          "markers", rec["corroboration"]["pnr_single_pin_markers"],
          flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--rederive":
        for g in args[1:]:
            rederive(g)
    else:
        for g in args:
            probe(g)
