"""SXT-020 rejection machinery: catalog, codes, outcome classification.

Fail-closed rule (issue #13): every emitted code must exist in the catalog
(``rejections.json``); an uncataloged code aborts the compile rather than
passing silently. The compiler emits either a complete image or a rejection
record — never a reduced ("trimmed") image.
"""
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "rejections.json"

VALID_CLASSES = ("unsupported", "unresolved", "adaptation")
OUTCOME_COMPILED = "compiled"
OUTCOME_REJECTED = "rejected"
OUTCOME_UNRESOLVED = "unresolved"

_ENGINE_ROLES = (
    "ains1", "ains2", "bins1", "bins2", "send1", "send2",
    "global1", "global2", "ains3", "ains4", "bins3", "bins4",
    "send3", "send4", "global3", "global4",
)

# Engine processing order (SurgeStorage.h fxslot_order / SurgeSynthesizer::
# process, cited in corpus/normalized/schema.json): scene A inserts, scene B
# inserts, scene sum, send buses S1..S4 (per-slot return level), then global
# chain. phase*10 + order gives the deterministic processing rank.
_ROLE_PHASE = {
    "ains": (0, "scene_A_insert"), "bins": (1, "scene_B_insert"),
    "send": (2, "send_bus"), "global": (3, "global_insert"),
}


class CatalogError(Exception):
    """Fail-closed: catalog or emitted-code inconsistency."""


def load_catalog():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    codes = catalog["codes"]
    seen = set()
    for entry in codes:
        code = entry.get("code")
        if not code or code in seen:
            raise CatalogError("rejection catalog: missing/duplicate code %r" % code)
        if entry.get("class") not in VALID_CLASSES:
            raise CatalogError("rejection catalog: bad class for %s" % code)
        seen.add(code)
    return catalog


_CATALOG = None


def catalog():
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_catalog()
    return _CATALOG


def catalog_codes():
    return {c["code"]: c for c in catalog()["codes"]}


def make_rejection(code, detail=None):
    """Build one machine-readable rejection; unknown codes abort."""
    entry = catalog_codes().get(code)
    if entry is None:
        raise CatalogError("refusing to emit uncataloged rejection code %r" % code)
    rej = {"code": code, "class": entry["class"]}
    if detail is not None:
        rej["detail"] = detail
    return rej


def outcome_for(codes):
    """Outcome classification by class precedence: unresolved > rejected."""
    classes = set()
    table = catalog_codes()
    for code in codes:
        entry = table.get(code)
        if entry is None:
            raise CatalogError("uncataloged code %r in outcome classification" % code)
        classes.add(entry["class"])
    if "unresolved" in classes:
        return OUTCOME_UNRESOLVED
    if classes:
        return OUTCOME_REJECTED
    return OUTCOME_COMPILED


def role_phase(role):
    """Map an engine role string to (phase_id, phase_name, order_in_phase).

    Returns None when the role is outside the engine's 16-role set (the
    caller turns that into ``routing_form_unsupported``)."""
    if role not in _ENGINE_ROLES:
        return None
    prefix, order = role[:-1], int(role[-1])
    phase, name = _ROLE_PHASE[prefix]
    return phase, name, order


def engine_order(role):
    """Deterministic processing rank of a slot from its routing role."""
    mapped = role_phase(role)
    if mapped is None:
        return None
    phase, _, order = mapped
    return phase * 10 + order
