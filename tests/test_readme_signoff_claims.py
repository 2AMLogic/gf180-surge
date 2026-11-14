#!/usr/bin/env python3
"""#678 -- the README's `## T1 signoff evidence` prose agrees with the verdict
of record it describes.

What this pins, and what it does NOT:

  * PINS: that the counted claims written in that README section agree with
    the two committed documents they describe --
    `signoff/block-manifest.json` (which envelope is cited for which T1 item
    number) and `signoff/block-manifest.signoff.json` (how many T1 items
    there are, how many read `met`, which ones, and where the null `tier`
    actually sits). Also that the section still carries, verbatim, the
    sentence denying that the report establishes anything.
  * DOES NOT: grade the report, re-render it, re-attest an envelope, read a
    `signoff/*attestation.json` envelope at all, or claim anything about T1
    evidence, fidelity, synthesis, place-and-route, hardware playback or
    preset quality. This is prose-vs-report bookkeeping only. It says the
    README describes the committed report correctly; it never says the
    report establishes anything. `klt signoff --manifest ... --check` and the
    two `--attest ... --check` steps in `.github/workflows/signoff.yml`
    remain the only things that grade the evidence itself.

Why it exists: on `main` before this test the section said the manifest
"currently cites one envelope: T1 item 10 (repo hygiene). Item 10 reads
`met`; the other ten items are `unmet` (`tier: null`)", while the committed
report carried `t1_met_count: 2` with items 9 **and** 10 `met`, and attached
`"tier": "T1"` to every one of the eleven item records -- it is the report's
*top-level* `tier` that is `null`. Three claims, all stale, and nothing
mechanical noticed: `klt signoff` grades the report, never the prose, and the
only README-reading audit (`tools/compile_backlog_dag.py --check`) only
byte-compares the generated `DAG:BEGIN`/`DAG:END` block.

The division of labour with the existing gates: **this test reads prose, they
read evidence.** It never opens an envelope, so it cannot say an envelope is
fresh; `--attest ... --check` does that. They never read English, so they
cannot say the README is honest about them; this does.

The required prose shape, so a reader knows what a reword must preserve.
Three shapes are parsed out of the section, all whitespace-insensitive
(wrap them however you like):

  1. the fixed sentence ending `currently cites these envelopes:`, followed
     by one markdown bullet per cited envelope, each of the form

         - T1 item <n> (<title>): [<path>](<path>)

     with link text and target equal, `<path>` being the envelope path the
     manifest declares for item `<n>`;
  2. one sentence of the form

         <met> of the <total> T1 items read `met` (items <n>, <n>); the
         other <word> read `unmet`.

     carrying the report's `t1_met_count`, its `t1_item_count`, the ids of
     the items the report marks `met`, and the remainder spelled as an
     English word;
  3. the two literal phrases locating the null tier -- "top-level `tier`
     field is `null`" and 'each T1 item record carries `"tier": "T1"`' --
     both of which are then re-derived from the report.

Rewording any of the three fails this test by design: the claim and its
checker have to move together. Dropping the no-claim sentence fails too.
"""

import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

README_REL = "README.md"
MANIFEST_REL = "signoff/block-manifest.json"
REPORT_REL = "signoff/block-manifest.signoff.json"

SECTION_HEADING = "## T1 signoff evidence"
CITED_INTRO = "currently cites these envelopes:"

# Shape 1: one bullet per cited envelope (continuation lines already joined).
BULLET_RE = re.compile(
    r"^T1 item (\d+) \([^()]+\): \[([^\[\]]+)\]\(([^()]+)\)$")

# Shape 2: the one sentence carrying all three counted claims.
COUNTS_RE = re.compile(
    r"(\d+) of the (\d+) T1 items read `met` \(items ([^()]+)\); "
    r"the other ([a-z]+) read `unmet`\.")
COUNTS_SHAPE = ("<met> of the <total> T1 items read `met` (items <n>, <n>); "
                "the other <word> read `unmet`.")

# Shape 3: where the null tier sits. Re-derived from the report below.
TIER_TOP_LEVEL_PHRASE = "top-level `tier` field is `null`"
TIER_ITEM_PHRASE = 'each T1 item record carries `"tier": "T1"`'

# AC1's retained boundary sentence.
NO_CLAIM_SENTENCE = ("The report establishes no T1 evidence, fidelity, "
                     "synthesis or hardware claim.")

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}


# ------------------------------------------------------------------ reading
def read_text(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def read_json(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return json.load(f)


def collapse(text):
    """Whitespace-insensitive view, so a reflowed paragraph still parses."""
    return " ".join(text.split())


def readme_section(readme_text):
    """The `## T1 signoff evidence` section, or None if it is gone."""
    lines = readme_text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != SECTION_HEADING:
            continue
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break
        return "\n".join(lines[i + 1:end])
    return None


def cited_bullets(section):
    """Shape 1: the bullet block right after the fixed intro sentence.

    Returns the bullets with continuation lines folded in, or None when the
    intro sentence itself is missing (which the audit reports rather than
    passing vacuously).
    """
    lines = section.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.rstrip().endswith(CITED_INTRO):
            start = i + 1
            break
    if start is None:
        return None
    bullets = []
    current = None
    for line in lines[start:]:
        if line.startswith("- "):
            if current is not None:
                bullets.append(current)
            current = line[2:].strip()
        elif current is None:
            if line.strip():
                break          # prose before the list started: no list
        elif line.startswith("  ") and line.strip():
            current += " " + line.strip()
        else:
            break              # blank line or dedent ends the block
    if current is not None:
        bullets.append(current)
    return bullets


def t1_item_records(report_doc):
    return [item for item in report_doc["items"] if item.get("tier") == "T1"]


# -------------------------------------------------------------------- audit
def audit(readme_text, report_doc, manifest_doc):
    """Findings for drift between the README prose and the two documents.

    Returned as findings rather than asserted inline so the controls below
    can run this same audit over mutated inputs. Pure over its three
    arguments -- it opens no file -- so a control mutates a string or a dict
    rather than copying a scratch tree.
    """
    findings = []
    section = readme_section(readme_text)
    if section is None:
        return ["README.md has no `%s` section: the claims this test pins "
                "are not there to check" % SECTION_HEADING]
    flat = collapse(section)

    # --- claim 1: the README names exactly the envelopes the manifest cites.
    declared = {int(item): ev["file"]
                for item, ev in manifest_doc["evidence"].items()}
    bullets = cited_bullets(section)
    if bullets is None:
        findings.append(
            "the cited-envelope list is missing: no line in the section ends "
            "with %r" % CITED_INTRO)
    elif not bullets:
        findings.append(
            "the cited-envelope list is empty: %r is followed by no `- T1 "
            "item <n> (...): [<path>](<path>)` bullet" % CITED_INTRO)
    else:
        cited = {}
        for bullet in bullets:
            match = BULLET_RE.match(bullet)
            if match is None:
                findings.append(
                    "cited-envelope bullet does not have the required shape "
                    "`T1 item <n> (<title>): [<path>](<path>)`: %r" % bullet)
                continue
            item = int(match.group(1))
            link_text, link_target = match.group(2), match.group(3)
            if link_text != link_target:
                findings.append(
                    "T1 item %d: the bullet's link text %r and target %r "
                    "differ; both must be the envelope path"
                    % (item, link_text, link_target))
            if item in cited:
                findings.append("T1 item %d: cited by more than one bullet"
                                % item)
            cited[item] = link_target
        for item in sorted(set(declared) - set(cited)):
            findings.append(
                "T1 item %d: %s cites it (%s) but the README section does "
                "not name it" % (item, MANIFEST_REL, declared[item]))
        for item in sorted(set(cited) - set(declared)):
            findings.append(
                "T1 item %d: the README section names it (%s) but %s cites "
                "no envelope for it" % (item, cited[item], MANIFEST_REL))
        for item in sorted(set(cited) & set(declared)):
            if cited[item] != declared[item]:
                findings.append(
                    "T1 item %d: the README names envelope %s, %s cites %s"
                    % (item, cited[item], MANIFEST_REL, declared[item]))

    # --- claim 2: the met count, the total, which items, and the remainder.
    report_met = sorted(item["id"] for item in t1_item_records(report_doc)
                        if item["status"] == "met")
    match = COUNTS_RE.search(flat)
    if match is None:
        findings.append(
            "the counted-claims sentence is missing or has drifted from the "
            "required shape %r" % COUNTS_SHAPE)
    else:
        said_met = int(match.group(1))
        said_total = int(match.group(2))
        said_items = sorted(int(n) for n in re.findall(r"\d+",
                                                       match.group(3)))
        said_other = match.group(4)
        if said_met != report_doc["t1_met_count"]:
            findings.append(
                "the README says %d T1 items read `met`; %s carries "
                "t1_met_count %d"
                % (said_met, REPORT_REL, report_doc["t1_met_count"]))
        if said_total != report_doc["t1_item_count"]:
            findings.append(
                "the README says there are %d T1 items; %s carries "
                "t1_item_count %d"
                % (said_total, REPORT_REL, report_doc["t1_item_count"]))
        if said_items != report_met:
            findings.append(
                "the README says items %s read `met`; %s marks items %s met"
                % (said_items, REPORT_REL, report_met))
        remainder = report_doc["t1_item_count"] - report_doc["t1_met_count"]
        if said_other not in NUMBER_WORDS:
            findings.append(
                "the README spells the `unmet` remainder %r, which is not a "
                "number word this test knows" % said_other)
        elif NUMBER_WORDS[said_other] != remainder:
            findings.append(
                "the README says the other %s (%d) read `unmet`; %s leaves "
                "%d of %d T1 items unmet"
                % (said_other, NUMBER_WORDS[said_other], REPORT_REL,
                   remainder, report_doc["t1_item_count"]))

    # --- claim 3: the null tier is the report's, not the items'.
    if TIER_TOP_LEVEL_PHRASE not in flat:
        findings.append(
            "the README section no longer states where the null tier sits: "
            "the phrase %r is gone" % TIER_TOP_LEVEL_PHRASE)
    elif report_doc["tier"] is not None:
        findings.append(
            "the README says the report's top-level `tier` is `null`; %s "
            "carries tier %r" % (REPORT_REL, report_doc["tier"]))
    if TIER_ITEM_PHRASE not in flat:
        findings.append(
            "the README section no longer states each T1 item's own tier: "
            "the phrase %r is gone" % TIER_ITEM_PHRASE)
    else:
        records = t1_item_records(report_doc)
        if len(records) != report_doc["t1_item_count"]:
            findings.append(
                "the README says each T1 item record carries \"tier\": "
                "\"T1\"; %s has %d such records for t1_item_count %d"
                % (REPORT_REL, len(records), report_doc["t1_item_count"]))

    # --- the retained boundary sentence (AC1).
    if NO_CLAIM_SENTENCE not in flat:
        findings.append(
            "the section no longer carries the no-claim sentence verbatim: "
            "%r" % NO_CLAIM_SENTENCE)

    return findings


# ----------------------------------------------------------- the committed
def committed_inputs():
    return (read_text(REPO, README_REL),
            read_json(REPO, REPORT_REL),
            read_json(REPO, MANIFEST_REL))


# ------------------------------------------------------------- the contract
def test_the_scan_sees_a_nonempty_section_and_report():
    """Coverage leg: a missing section or an unparsed report would make
    every audit below pass vacuously, which is the trap this guards."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    section = readme_section(readme_text)
    assert section is not None, SECTION_HEADING
    assert len(collapse(section)) > 200, len(collapse(section))
    bullets = cited_bullets(section)
    assert bullets, bullets
    assert COUNTS_RE.search(collapse(section)) is not None, COUNTS_SHAPE
    assert manifest_doc["evidence"], manifest_doc
    assert t1_item_records(report_doc), report_doc["items"]
    assert report_doc["t1_item_count"] > 0
    assert report_doc["t1_met_count"] > 0


def test_the_readme_section_matches_the_verdict_of_record():
    """The whole point: a stale count, a dropped citation or a reworded
    claim fails here.

    A finding means the README describes a report that is not the committed
    one. The fix is to correct the prose (or the shape documented in this
    module's docstring), never to relax this audit.
    """
    assert audit(*committed_inputs()) == []


def test_the_manifest_and_the_report_cite_the_same_envelopes():
    """The two documents the prose is checked against must agree with each
    other, or "matches the README" would be an ambiguous claim."""
    _readme, report_doc, manifest_doc = committed_inputs()
    declared = {int(item): ev["file"]
                for item, ev in manifest_doc["evidence"].items()}
    from_report = {item["id"]: item["citation"]["file"]
                   for item in t1_item_records(report_doc)
                   if item["status"] == "met"}
    assert from_report == declared, (from_report, declared)


# -------------------------------------------------------- failure controls
def test_control_the_audit_is_not_always_firing():
    """Non-vacuity for the controls below: the committed trio must be clean
    under the very same call they mutate, or they would fire on anything."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    assert audit(readme_text, report_doc, manifest_doc) == []


def test_control_a_wrong_met_count_is_reported():
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace("2 of the 11 T1 items read `met`",
                                 "1 of the 11 T1 items read `met`")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any("says 1 T1 items read `met`" in f for f in findings), findings


def test_control_a_wrong_total_is_reported():
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace("2 of the 11 T1 items read `met`",
                                 "2 of the 12 T1 items read `met`")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any("says there are 12 T1 items" in f for f in findings), findings


def test_control_a_wrong_met_item_list_is_reported():
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace("(items 9 and 10)", "(items 8 and 10)")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any("says items [8, 10] read `met`" in f for f in findings), \
        findings


def test_control_a_wrong_unmet_remainder_is_reported():
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace("the other nine read `unmet`",
                                 "the other ten read `unmet`")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any("says the other ten (10) read `unmet`" in f
               for f in findings), findings


def test_control_a_dropped_cited_item_is_reported():
    """The #678 regression itself: the README naming only one envelope."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    dropped = ("- T1 item 9 (testbenches shipped):\n"
               "  [signoff/t1-item9-attestation.json]"
               "(signoff/t1-item9-attestation.json)\n")
    assert dropped in readme_text
    broken = readme_text.replace(dropped, "")
    findings = audit(broken, report_doc, manifest_doc)
    assert any(f.startswith("T1 item 9:") and "does not name it" in f
               for f in findings), findings


def test_control_an_added_uncited_item_is_reported():
    """Set equality, not containment: a bullet for an envelope the manifest
    does not cite is a support claim with no evidence behind it."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    anchor = ("- T1 item 10 (repo hygiene):\n"
              "  [signoff/item-10.attestation.json]"
              "(signoff/item-10.attestation.json)\n")
    assert anchor in readme_text
    extra = ("- T1 item 11 (made up): "
             "[signoff/item-11.attestation.json]"
             "(signoff/item-11.attestation.json)\n")
    findings = audit(readme_text.replace(anchor, anchor + extra),
                     report_doc, manifest_doc)
    assert any(f.startswith("T1 item 11:") and "cites no envelope" in f
               for f in findings), findings


def test_control_a_wrong_envelope_path_is_reported():
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace("signoff/item-10.attestation.json",
                                 "signoff/item-10-old.attestation.json")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any(f.startswith("T1 item 10: the README names envelope "
                            "signoff/item-10-old.attestation.json")
               and "cites signoff/item-10.attestation.json" in f
               for f in findings), findings


def test_control_reattaching_the_null_tier_to_the_items_is_reported():
    """Correction 3 of #678: `tier: null` describes the report, not the
    items, so the sentence that says so may not quietly go away."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace(
        "The report's own top-level `tier` field is `null`; the items are "
        "not\n`tier: null`, each T1 item record carries `\"tier\": \"T1\"`.",
        "The other nine items are `unmet` (`tier: null`).")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any(TIER_TOP_LEVEL_PHRASE in f for f in findings), findings
    assert any(TIER_ITEM_PHRASE in f for f in findings), findings


def test_control_a_report_whose_items_lost_their_tier_is_reported():
    """The other direction: the prose claim is re-derived, not assumed."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    report_doc["items"][0]["tier"] = None
    findings = audit(readme_text, report_doc, manifest_doc)
    assert any("such records for t1_item_count" in f for f in findings), \
        findings


def test_control_a_report_with_a_non_null_top_level_tier_is_reported():
    readme_text, report_doc, manifest_doc = committed_inputs()
    report_doc["tier"] = "T1"
    findings = audit(readme_text, report_doc, manifest_doc)
    assert any("carries tier 'T1'" in f for f in findings), findings


def test_control_dropping_the_no_claim_sentence_is_reported():
    """AC1's boundary: the section may not stop saying the report
    establishes nothing."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace("The report establishes no T1\nevidence, "
                                 "fidelity, synthesis or hardware claim.",
                                 "The report establishes T1 item 9 and 10.")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any("no-claim sentence" in f for f in findings), findings


def test_control_a_missing_section_is_reported_not_passed_vacuously():
    """Rename or delete the heading and the audit must say so loudly rather
    than finding nothing to disagree with."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace(SECTION_HEADING, "## Signoff")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert findings and "has no" in findings[0], findings


def test_control_a_reworded_counts_sentence_is_reported():
    """The shape is the contract: a reword has to move the checker too."""
    readme_text, report_doc, manifest_doc = committed_inputs()
    broken = readme_text.replace(
        "2 of the 11 T1 items read `met` (items 9 and 10); the other nine "
        "read `unmet`.",
        "Two of the eleven T1 items are met, namely 9 and 10.")
    assert broken != readme_text
    findings = audit(broken, report_doc, manifest_doc)
    assert any("counted-claims sentence is missing" in f
               for f in findings), findings
