"""Contract test for the klayout-tools pin in committed signoff envelopes (#743).

`klt signoff --check` re-runs an envelope's checks and re-derives its content
hashes, but it does not compare `provenance.klt_version`: an envelope produced
by a host dev build can be committed with a `0.9.3.dev268+...` provenance
string while every gate stays green, and the next person who follows the
documented regeneration command (the `signoff/requirements.txt` pin) gets a
one-line diff that no check calls out. This test asserts, for each committed
`klt signoff --attest` envelope, that `provenance.klt_version` equals the
pin, read from `signoff/requirements.txt` only -- the single place, the same
pin `.github/workflows/signoff.yml` installs.

Repo-evidence provenance bookkeeping only: no fidelity, synthesis, P&R,
hardware-playback, original-Surge-fidelity or preset-quality claim, and no
statement about `signoff/t1-item1/*/report.json`, whose dev-build
`klt_version` strings are legitimate (run reports, not attestation envelopes).

Envelope scope is discovered, then held to a census: a third envelope (or a
rename) changes the discovered set and fails the census below visibly,
instead of silently shrinking what this contract covers.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_REL = "signoff/requirements.txt"
ENVELOPE_GLOB = "signoff/*attestation.json"
EXPECTED_ENVELOPES = (
    "signoff/item-10.attestation.json",
    "signoff/t1-item9-attestation.json",
)
# The provenance string from issue #743's observation, kept verbatim as the
# negative-control payload: the dev-build version a host `klt` can stamp into
# an envelope when the pin was not used.
DEV_BUILD_VERSION = "0.9.3.dev268+g17a90d6ed20d"

PIN_LINE = re.compile(r"^klayout-tools==([^\s#]+)\s*(?:#.*)?$")


def pin_from_requirements(text):
    """The `klayout-tools==` pin in a requirements text, or None.

    Tolerates comment lines and blank lines; two pin lines are ambiguous and
    also return None (reported as a finding by the caller).
    """
    pins = [m.group(1) for line in text.splitlines()
            if (m := PIN_LINE.match(line.strip()))]
    return pins[0] if len(pins) == 1 else None


def requirements_problems(text):
    """Findings for a requirements text that does not carry exactly one pin."""
    pins = [m.group(1) for line in text.splitlines()
            if (m := PIN_LINE.match(line.strip()))]
    if not pins:
        return ["signoff/requirements.txt carries no `klayout-tools==` pin"]
    if len(pins) > 1:
        return [f"signoff/requirements.txt carries {len(pins)} "
                f"`klayout-tools==` pins ({pins}); the pin must be single"]
    return []


def envelope_problems(pin, path, doc=None):
    """Findings for one attestation envelope whose provenance is not `pin`.

    A missing `provenance` or `provenance.klt_version` is a finding, not a
    vacuous pass: an envelope that does not name its producer version fails
    as loudly as one that names the wrong version.
    """
    if doc is None:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    provenance = doc.get("provenance")
    if not isinstance(provenance, dict):
        return [f"{path}: no `provenance` object; the envelope does not "
                "record which klt produced it"]
    version = provenance.get("klt_version")
    if version is None:
        return [f"{path}: provenance.klt_version missing"]
    if version != pin:
        return [f"{path}: provenance.klt_version is {version!r}, not the "
                f"signoff/requirements.txt pin {pin!r}"]
    return []


def discovered_envelopes():
    return tuple(sorted(p.relative_to(ROOT).as_posix()
                        for p in Path(ROOT).glob(ENVELOPE_GLOB)))


# ---------------------------------------------------------------- contract
def test_the_census_sees_exactly_the_two_committed_envelopes():
    """Coverage leg: discovery must match the two envelopes this contract
    names, so an added, removed or renamed envelope fails here first."""
    assert discovered_envelopes() == EXPECTED_ENVELOPES, discovered_envelopes()


def test_the_pin_parses_from_requirements_txt():
    """The pin is readable and names the installed klayout-tools."""
    text = (ROOT / REQUIREMENTS_REL).read_text(encoding="utf-8")
    assert requirements_problems(text) == [], requirements_problems(text)
    pin = pin_from_requirements(text)
    assert pin, "no klayout-tools pin parsed"
    assert re.fullmatch(r"[0-9]+\.[0-9]+(\.[0-9]+)?", pin), pin


def test_pin_parse_tolerates_comments_and_blank_lines():
    text = ("\n# klayout-tools pinned for signoff evidence\n"
            "\n"
            "  klayout-tools==0.8.0  # single source, see signoff.yml\n"
            "\n")
    assert requirements_problems(text) == []
    assert pin_from_requirements(text) == "0.8.0"


@pytest.mark.parametrize("rel", EXPECTED_ENVELOPES)
def test_committed_envelopes_record_the_pinned_klt(rel):
    """The whole point: the committed envelopes name the pin as producer."""
    text = (ROOT / REQUIREMENTS_REL).read_text(encoding="utf-8")
    assert envelope_problems(pin_from_requirements(text), rel) == []


# ------------------------------------------------------- negative controls
def _scratch_envelope(tmp_path, mutate):
    """A temp copy of the item 10 envelope with one mutation applied.

    The real envelope is never edited; the control runs the same checker the
    contract test runs, against the copy.
    """
    source = ROOT / EXPECTED_ENVELOPES[0]
    doc = json.loads(source.read_text(encoding="utf-8"))
    mutate(doc)
    copy = tmp_path / "item-10.attestation.json"
    copy.write_text(json.dumps(doc), encoding="utf-8")
    return copy


def test_control_an_unmutated_copy_is_clean(tmp_path):
    """Non-vacuity: the controls below perturb one field each; the checker
    must accept an unmutated copy, or it would fire on anything."""
    copy = _scratch_envelope(tmp_path, lambda doc: None)
    text = (ROOT / REQUIREMENTS_REL).read_text(encoding="utf-8")
    assert envelope_problems(pin_from_requirements(text), copy) == []


def test_control_a_dev_build_version_in_an_envelope_is_reported(tmp_path):
    """#743's observed defect, reproduced: an envelope stamped by a host dev
    build fails the checker, which `klt signoff --check` alone misses."""
    def stamp_dev_build(doc):
        doc["provenance"]["klt_version"] = DEV_BUILD_VERSION

    copy = _scratch_envelope(tmp_path, stamp_dev_build)
    text = (ROOT / REQUIREMENTS_REL).read_text(encoding="utf-8")
    findings = envelope_problems(pin_from_requirements(text), copy)
    assert any(DEV_BUILD_VERSION in f and "not the" in f for f in findings), \
        findings


def test_control_a_missing_klt_version_is_reported(tmp_path):
    """A stripped version key fails loudly instead of passing vacuously."""
    def strip_version(doc):
        del doc["provenance"]["klt_version"]

    copy = _scratch_envelope(tmp_path, strip_version)
    text = (ROOT / REQUIREMENTS_REL).read_text(encoding="utf-8")
    findings = envelope_problems(pin_from_requirements(text), copy)
    assert any("provenance.klt_version missing" in f for f in findings), \
        findings


def test_control_a_missing_provenance_block_is_reported(tmp_path):
    """A stripped provenance object fails loudly instead of passing."""
    def strip_provenance(doc):
        del doc["provenance"]

    copy = _scratch_envelope(tmp_path, strip_provenance)
    text = (ROOT / REQUIREMENTS_REL).read_text(encoding="utf-8")
    findings = envelope_problems(pin_from_requirements(text), copy)
    assert any("no `provenance` object" in f for f in findings), findings


def test_control_a_requirements_file_without_the_pin_is_reported():
    """The single-source read fails loudly if the pin line disappears."""
    assert requirements_problems("numpy==2.4.2\n# klayout-tools moved\n")
    assert requirements_problems(
        "klayout-tools==0.8.0\nklayout-tools==0.9.0\n")
