#!/usr/bin/env python3
"""Backlog DAG compiler and evidence-derived status board (SXT-018).

Bookkeeping only. The board reports the claim status of the SXT backlog:
it is not capability evidence, fidelity evidence, a completion percentage,
or a quality score, and it never substitutes for the underlying evidence
records. Coverage and agreement are reported separately (AGENTS.md).

Usage:
    python3 tools/compile_backlog_dag.py render    # validate, refresh evidence
                                                   # hashes, rewrite README block
    python3 tools/compile_backlog_dag.py --check   # validate + freshness; no writes

Sync procedure: edit docs/dag.json, run `render`, commit docs/dag.json and
README.md together. Edits driven by GitHub issue changes are transcribed
into dag.json by hand and must go through the same re-render; the dag-check
CI job fails on stale blocks, stale/missing evidence hashes, unknown
statuses, or broken edges, so drift is never silent.

--check enforces (any violation exits 1):
  * schema: required fields, types, unique integer ids, known kinds,
    unique planning ids, epic/membership consistency
  * status vocabulary: READY, IN_PROGRESS, BLOCKED, NOT_RUN, PASS, FAIL,
    NO_VERDICT, STALE
  * edge closure: every depends_on target exists as a node
  * acyclic dependency graph
  * PASS requires a committed evidence artifact: the path must exist in
    the repository at check time AND be tracked by git AND carry an
    evidence_sha256 equal to the file's current SHA-256, so stale evidence
    is detectable. File existence alone approves nothing; closed issues,
    labels, and generated reports never stamp PASS.
  * epic nodes are aggregates, not claim nodes: their declared status must
    equal the aggregate of the member statuses (see aggregate_status);
    an epic PASS is impossible unless every member PASSes on its own
    committed evidence.
  * the README block between the DAG markers is byte-identical to the
    regenerated block (freshness)

Style reference only, no code copied: gf180-torchsynth's capabilities
board and gf180-parasynth's compile_dag board. Audit-driven differences
are recorded in docs/REUSE-AUDIT.md: evidence pointers are hashed against
the artifact (not accepted on existence), STALE is an explicit state, and
closure/cycle checks run over the declared DAG.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAG_PATH = ROOT / "docs" / "dag.json"
README_PATH = ROOT / "README.md"
BEGIN_MARKER = "<!-- DAG:BEGIN -->"
END_MARKER = "<!-- DAG:END -->"

STATUS_VOCABULARY = [
    "READY",
    "IN_PROGRESS",
    "BLOCKED",
    "NOT_RUN",
    "PASS",
    "FAIL",
    "NO_VERDICT",
    "STALE",
]

COUNT_ORDER = [
    "READY",
    "IN_PROGRESS",
    "BLOCKED",
    "NOT_RUN",
    "PASS",
    "FAIL",
    "NO_VERDICT",
    "STALE",
]

MANDATORY_LINES = [
    "Claim counts, not a completion percentage or a quality score. READY is unrun, not PASS.",
    "Coverage and agreement are reported separately by the underlying evidence; this board merges neither.",
]

STATUS_COLORS = {
    "PASS": "#0E6B5E",
    "FAIL": "#8E2438",
    "BLOCKED": "#9A6510",
    "IN_PROGRESS": "#1D4F91",
    "READY": "#3178C6",
    "NOT_RUN": "#5A6468",
    "NO_VERDICT": "#6B46C1",
    "STALE": "#B7791F",
}

ISSUE_URL = "https://github.com/2AMLogic/gf180-surge/issues/"

BLOCK_BANNER = (
    "<!-- Compiled from docs/dag.json by tools/compile_backlog_dag.py — do not edit"
    " by hand. Edit docs/dag.json and re-run `python3 tools/compile_backlog_dag.py"
    " render`; the dag-check CI job re-validates freshness on every pull request."
    " Bookkeeping only: claim status of backlog issues — no capability, fidelity,"
    " or hardware claim. -->"
)


class ValidationError(Exception):
    """Raised when the DAG or the board violates the contract."""


# ---------------------------------------------------------------- loading

def load_dag(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read {path}: {exc}")
    try:
        dag = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}")
    if not isinstance(dag, dict):
        raise ValidationError(f"{path}: top level must be an object")
    return dag


# ------------------------------------------------------------- validation

def _require_str(node: dict, key: str, where: str, errors: list[str]) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: field {key!r} must be a non-empty string")
        return ""
    return value


def _require_int_list(node: dict, key: str, where: str, errors: list[str]) -> list[int]:
    value = node.get(key)
    if not isinstance(value, list) or not all(isinstance(v, int) for v in value):
        errors.append(f"{where}: field {key!r} must be a list of integers")
        return []
    return value


def validate_schema(dag: dict) -> tuple[dict[int, dict], list[str]]:
    """Structural validation shared by render and --check."""
    errors: list[str] = []
    nodes = dag.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValidationError("docs/dag.json: missing or empty 'nodes' list")

    by_id: dict[int, dict] = {}
    planning_ids: set[str] = set()
    epic_ids: dict[str, dict] = {}

    for node in nodes:
        if not isinstance(node, dict):
            errors.append("every node must be an object")
            continue
        where = f"node {node.get('id')!r}"
        node_id = node.get("id")
        if not isinstance(node_id, int) or isinstance(node_id, bool):
            errors.append(f"{where}: 'id' must be an integer")
            continue
        if node_id in by_id:
            errors.append(f"duplicate node id {node_id}")
            continue
        by_id[node_id] = node

        kind = node.get("kind")
        if kind not in ("issue", "epic"):
            errors.append(f"{where}: 'kind' must be 'issue' or 'epic'")
        _require_str(node, "title", where, errors)
        planning_id = _require_str(node, "planning-id", where, errors)
        if planning_id:
            if planning_id in planning_ids:
                errors.append(f"{where}: duplicate planning-id {planning_id!r}")
            planning_ids.add(planning_id)
        _require_int_list(node, "depends_on", where, errors)
        note = _require_str(node, "note", where, errors)
        if note and "\n" in note:
            errors.append(f"{where}: 'note' must be a single line")

        status = node.get("status")
        if status not in STATUS_VOCABULARY:
            errors.append(
                f"{where}: unknown status {status!r}; allowed vocabulary: "
                + ", ".join(STATUS_VOCABULARY)
            )

        epic = node.get("epic")
        if epic is not None and not isinstance(epic, str):
            errors.append(f"{where}: 'epic' must be a string or null")

        if kind == "epic":
            if planning_id:
                epic_ids[planning_id] = node
            members = _require_int_list(node, "members", where, errors)
            if not members:
                errors.append(f"{where}: epic 'members' must be a non-empty list")
            for key in ("evidence", "evidence_sha256"):
                if node.get(key) is not None:
                    errors.append(f"{where}: epic nodes must not carry {key!r} (they are aggregate groups, not claim nodes)")
        else:  # issue
            if node.get("members") is not None:
                errors.append(f"{where}: non-epic nodes must not declare 'members'")
            sha = node.get("evidence_sha256")
            if sha is not None and status != "PASS":
                errors.append(f"{where}: 'evidence_sha256' is only valid on PASS nodes")
            if status == "PASS":
                evidence = node.get("evidence")
                if not isinstance(evidence, str) or not evidence.strip():
                    errors.append(f"{where}: PASS requires an 'evidence' path to a committed artifact")

    # epic membership consistency
    for node in by_id.values():
        if node.get("kind") != "issue":
            continue
        epic = node.get("epic")
        if epic is not None and epic not in epic_ids:
            errors.append(f"node {node['id']}: unknown epic {epic!r}")
    for planning_id, epic in epic_ids.items():
        for member in epic.get("members", []):
            member_node = by_id.get(member)
            if member_node is None:
                errors.append(f"epic {planning_id}: member {member} does not exist")
            elif member_node.get("kind") != "issue":
                errors.append(f"epic {planning_id}: member {member} must be an issue node")
            elif member_node.get("epic") != planning_id:
                errors.append(
                    f"epic {planning_id}: member {member} declares epic "
                    f"{member_node.get('epic')!r}, mismatching the membership list"
                )

    # edge closure
    for node in by_id.values():
        for dep in node.get("depends_on", []):
            if dep not in by_id:
                errors.append(f"node {node['id']}: depends_on {dep} does not exist (edge closure)")
            elif dep == node["id"]:
                errors.append(f"node {node['id']}: depends on itself")

    # acyclicity (DFS with color marking over dependency edges)
    state: dict[int, int] = {}
    stack: list[int] = []

    def visit(node_id: int) -> None:
        state[node_id] = 1
        stack.append(node_id)
        for dep in by_id[node_id].get("depends_on", []):
            if dep not in by_id:
                continue
            if state.get(dep) == 1:
                cycle = stack[stack.index(dep):] + [dep]
                errors.append("dependency cycle: " + " -> ".join(str(n) for n in cycle))
            elif state.get(dep) is None:
                visit(dep)
        stack.pop()
        state[node_id] = 2

    for node_id in sorted(by_id):
        if state.get(node_id) is None:
            visit(node_id)

    return by_id, errors


def aggregate_status(member_statuses: list[str]) -> str:
    """Epic aggregate rule (documented in docs/dag.json board.epic_aggregate_rule)."""
    if not member_statuses:
        return "NOT_RUN"
    statuses = set(member_statuses)
    if "FAIL" in statuses:
        return "FAIL"
    if "STALE" in statuses:
        return "STALE"
    if statuses == {"PASS"}:
        return "PASS"
    if "IN_PROGRESS" in statuses:
        return "IN_PROGRESS"
    if "BLOCKED" in statuses and statuses <= {"BLOCKED", "PASS"}:
        return "BLOCKED"
    return "NOT_RUN"


def validate_epic_aggregates(by_id: dict[int, dict], errors: list[str]) -> None:
    for node in by_id.values():
        if node.get("kind") != "epic":
            continue
        members = node.get("members", [])
        member_nodes = [by_id[m] for m in members if m in by_id]
        derived = aggregate_status([m.get("status", "NOT_RUN") for m in member_nodes])
        if len(member_nodes) != len(members):
            continue  # membership errors already reported
        if node.get("status") != derived:
            errors.append(
                f"epic node {node['id']}: declared status {node.get('status')!r} does not "
                f"match the member aggregate {derived!r} (epics are groups, not claim nodes)"
            )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_tracked(rel_path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", rel_path],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise ValidationError("git is not available; cannot verify evidence is committed")
    return result.returncode == 0


def validate_evidence(by_id: dict[int, dict], errors: list[str], strict_hashes: bool = True) -> None:
    """PASS evidence must be a committed artifact whose recorded hash matches
    the file's current content. Existence alone approves nothing.

    With strict_hashes=False (render's pre-pass) a missing evidence_sha256 is
    tolerated so render can compute and store it; a wrong hash is still fatal."""
    for node in by_id.values():
        where = f"node {node['id']}"
        evidence = node.get("evidence")
        if evidence is None:
            continue
        if not isinstance(evidence, str) or not evidence.strip():
            errors.append(f"{where}: 'evidence' must be a non-empty path when present")
            continue
        rel = Path(evidence)
        if rel.is_absolute() or ".." in rel.parts:
            errors.append(f"{where}: evidence path {evidence!r} must be relative to the repository root")
            continue
        abs_path = ROOT / rel
        if not abs_path.is_file():
            errors.append(f"{where}: evidence file {evidence!r} does not exist in the repository")
            continue
        if not git_tracked(evidence):
            errors.append(f"{where}: evidence file {evidence!r} is not committed to git")
            continue
        if node.get("status") == "PASS":
            current = sha256_file(abs_path)
            recorded = node.get("evidence_sha256")
            if recorded is None:
                if strict_hashes:
                    errors.append(
                        f"{where}: PASS requires 'evidence_sha256' (sha256 of the evidence file); "
                        "run `python3 tools/compile_backlog_dag.py render` to compute and store it"
                    )
            elif recorded != current:
                errors.append(
                    f"{where}: evidence_sha256 does not match the current content of "
                    f"{evidence!r} (recorded {recorded!r}, actual {current!r}); "
                    "evidence changed after the board was rendered — STALE"
                )


def validate(dag: dict, strict_hashes: bool = True) -> dict[int, dict]:
    by_id, errors = validate_schema(dag)
    validate_epic_aggregates(by_id, errors)
    validate_evidence(by_id, errors, strict_hashes=strict_hashes)
    if errors:
        raise ValidationError("\n".join(f"  - {e}" for e in errors))
    return by_id


# -------------------------------------------------------------- rendering

def display_status(status: str) -> str:
    return status.replace("_", " ")


def counts_table(by_id: dict[int, dict]) -> str:
    counts = {status: 0 for status in COUNT_ORDER}
    for node in by_id.values():
        status = node.get("status")
        if status in counts:
            counts[status] += 1
    lines = [
        "| Status | Nodes |",
        "|---|---|",
    ]
    for status in COUNT_ORDER:
        lines.append(f"| {display_status(status)} | {counts[status]} |")
    lines.append(f"| **Total nodes** | **{len(by_id)}** |")
    return "\n".join(lines)


def node_table(by_id: dict[int, dict]) -> str:
    lines = [
        "| Node | Planning ID | Title | Status | Evidence |",
        "|---|---|---|---|---|",
    ]
    for node_id in sorted(by_id):
        node = by_id[node_id]
        title = str(node.get("title", "")).replace("|", "\\|")
        evidence = node.get("evidence")
        if evidence:
            evidence_cell = f"[`{evidence}`]({evidence})"
        elif node.get("kind") == "epic":
            evidence_cell = "aggregate of members"
        else:
            evidence_cell = "—"
        lines.append(
            f"| [#{node_id}]({ISSUE_URL}{node_id}) | {node.get('planning-id', '')} "
            f"| {title} | {display_status(node.get('status', 'NOT_RUN'))} | {evidence_cell} |"
        )
    return "\n".join(lines)


def mermaid_graph(by_id: dict[int, dict]) -> str:
    groups: dict[str, list[int]] = {}
    for node_id in sorted(by_id):
        node = by_id[node_id]
        epic = node.get("epic")
        if node.get("kind") == "epic":
            key = str(node.get("planning-id", f"epic-{node_id}"))
        elif epic:
            key = epic
        else:
            key = "XC"
        groups.setdefault(key, []).append(node_id)

    lines = ["graph TD"]
    for key in sorted(groups):
        if key == "XC":
            label = "Cross-cutting (no epic)"
        else:
            epic_node = next(n for n in by_id.values() if n.get("planning-id") == key)
            label = str(epic_node.get("title", "")).replace("Epic: ", "Epic ")
        lines.append(f"  subgraph {key}[\"{label}\"]")
        for node_id in groups[key]:
            node = by_id[node_id]
            planning = node.get("planning-id", "")
            if node.get("kind") == "epic":
                text = f"#{node_id} Epic {planning} · {node.get('status')}"
            else:
                text = f"#{node_id} {planning} · {node.get('status')}"
            lines.append(f"    n{node_id}[\"{text}\"]")
        lines.append("  end")

    edges = set()
    for node_id in sorted(by_id):
        for dep in by_id[node_id].get("depends_on", []):
            if dep in by_id:
                edges.add((dep, node_id))
    for dep, target in sorted(edges):
        lines.append(f"  n{dep} --> n{target}")

    lines.append("  classDef pass fill:#0E6B5E,color:#fff")
    lines.append("  classDef fail fill:#8E2438,color:#fff")
    lines.append("  classDef blocked fill:#9A6510,color:#fff")
    lines.append("  classDef inprogress fill:#1D4F91,color:#fff")
    lines.append("  classDef ready fill:#3178C6,color:#fff")
    lines.append("  classDef notrun fill:#5A6468,color:#fff")
    lines.append("  classDef noverdict fill:#6B46C1,color:#fff")
    lines.append("  classDef stale fill:#B7791F,color:#fff")
    for status in COUNT_ORDER:
        class_name = status.lower().replace("_", "")
        members = [f"n{nid}" for nid in sorted(by_id) if by_id[nid].get("status") == status]
        if members:
            lines.append(f"  class {','.join(members)} {class_name}")
    return "\n".join(lines)


def render_block(by_id: dict[int, dict]) -> str:
    parts = [
        BEGIN_MARKER,
        BLOCK_BANNER,
        "",
        counts_table(by_id),
        "",
        MANDATORY_LINES[0],
        MANDATORY_LINES[1],
        "",
        "<details>",
        f"<summary>Node status and evidence ({len(by_id)} nodes)</summary>",
        "",
        node_table(by_id),
        "",
        "</details>",
        "",
        "<details>",
        "<summary>Dependency graph (mermaid, grouped by epic)</summary>",
        "",
        "```mermaid",
        mermaid_graph(by_id),
        "```",
        "",
        "</details>",
        END_MARKER,
    ]
    return "\n".join(parts)


BLOCK_PATTERN = re.compile(
    re.escape(BEGIN_MARKER) + r"(?:\n.*?)?\n" + re.escape(END_MARKER), re.DOTALL
)


def extract_block(readme_text: str) -> str | None:
    match = BLOCK_PATTERN.search(readme_text)
    return match.group(0) if match else None


def splice_block(readme_text: str, block: str) -> str:
    matches = list(BLOCK_PATTERN.finditer(readme_text))
    if not matches:
        raise ValidationError(
            f"{README_PATH.name}: markers {BEGIN_MARKER} / {END_MARKER} not found; "
            "add the empty marker block once, then re-run render"
        )
    if len(matches) > 1:
        raise ValidationError(f"{README_PATH.name}: more than one DAG marker block found")
    return readme_text[:matches[0].start()] + block + readme_text[matches[0].end():]


def serialize_dag(dag: dict) -> str:
    return json.dumps(dag, indent=2, ensure_ascii=False) + "\n"


# ------------------------------------------------------------ subcommands

def cmd_render() -> int:
    dag = load_dag(DAG_PATH)
    by_id = validate(dag, strict_hashes=False)

    # compute and store evidence hashes for PASS nodes
    changed_hashes = []
    for node in by_id.values():
        if node.get("status") == "PASS":
            current = sha256_file(ROOT / node["evidence"])
            if node.get("evidence_sha256") != current:
                node["evidence_sha256"] = current
                changed_hashes.append(f"{node['id']}: {node['evidence']}")

    new_dag_text = serialize_dag(dag)
    old_dag_text = DAG_PATH.read_text(encoding="utf-8")
    if new_dag_text != old_dag_text:
        DAG_PATH.write_text(new_dag_text, encoding="utf-8")

    readme_text = README_PATH.read_text(encoding="utf-8")
    block = render_block(by_id)
    new_readme = splice_block(readme_text, block)
    readme_changed = new_readme != readme_text
    if readme_changed:
        README_PATH.write_text(new_readme, encoding="utf-8")

    print(f"render: {len(by_id)} nodes validated")
    if changed_hashes:
        print("render: refreshed evidence_sha256 for: " + "; ".join(changed_hashes))
    print(f"render: docs/dag.json {'rewritten' if new_dag_text != old_dag_text else 'unchanged'}")
    print(f"render: README block {'rewritten' if readme_changed else 'already fresh'}")
    print(MANDATORY_LINES[0])
    print(MANDATORY_LINES[1])
    return 0


def cmd_check() -> int:
    dag = load_dag(DAG_PATH)
    by_id = validate(dag)

    readme_text = README_PATH.read_text(encoding="utf-8")
    current_block = extract_block(readme_text)
    if current_block is None:
        raise ValidationError(
            f"{README_PATH.name}: DAG marker block not found; run "
            "`python3 tools/compile_backlog_dag.py render` after adding the markers"
        )
    expected_block = render_block(by_id)
    if current_block != expected_block:
        raise ValidationError(
            f"{README_PATH.name}: DAG block is stale (regenerated block differs); "
            "run `python3 tools/compile_backlog_dag.py render` and commit both files"
        )

    counts = {status: 0 for status in COUNT_ORDER}
    for node in by_id.values():
        status = node.get("status")
        if status in counts:
            counts[status] += 1
    summary = ", ".join(f"{display_status(s)}={counts[s]}" for s in COUNT_ORDER)
    print(f"dag-check: PASS ({len(by_id)} nodes: {summary})")
    print(MANDATORY_LINES[0])
    print(MANDATORY_LINES[1])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("render", nargs="?", help="validate, refresh evidence hashes, rewrite the README block")
    group.add_argument("--check", action="store_true", help="validate and check freshness without writing")
    args = parser.parse_args()

    try:
        if args.check:
            return cmd_check()
        if args.render is not None:
            return cmd_render()
        parser.error("choose 'render' or '--check'")
    except ValidationError as exc:
        print("dag-check: FAIL", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
