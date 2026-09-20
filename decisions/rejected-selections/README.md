# Rejected selections — retention layout (SXT-013)

Every candidate that was auditioned and NOT selected into the favorites set
is retained here with a reason — rejections are part of the auditable
predeclared-target record (issue #8 acceptance: "originals and rejections
retained"; plan §2).

## Layout

```
rejected-selections/
  <quota-profile>/
    rejected-<NNN>-<preset-slug>.json
```

One JSON per rejected candidate:

```json
{
  "schema_version": "sxt-013-rejected-selection/1.0.0",
  "candidate_id": "<census path>",
  "bank": "<factory|contributor>",
  "category": "<category>",
  "census_blob_sha1": "<sha1>",
  "slate_artifact": "<slate json it was a candidate in>",
  "listening_sessions": ["<session ids that judged it>"],
  "ratings_summary": {"fidelity_1to5_median": "<n>",
                      "artifacts": "<none|minor|severe>"},
  "rejection_reason": "<free text; must state the deciding observation>",
  "rejected_at_utc": "<ISO-8601>",
  "rejected_by": "<human operator>"
}
```

## Reason vocabulary (non-exclusive, machine-greppable prefixes)

- `sound: weaker than selected peer in same category`
- `fidelity: <measured area failed> (policy section)`
- `redundant: <feature/character already covered by selected preset>`
- `resource: <known heavy dependency> — recorded BEFORE hardware cuts, never
  retro-fitted` (a resource-motivated rejection made before SXT-017 findings
  is legitimate; one made after, to fit a cut, is a visible contract
  revision, not a selection act)
- `listener: could not evaluate <reason>` → candidate returns to
  **unresolved**, not rejected

Records here are immutable once written; a re-accepted candidate is recorded
in the favorites artifact with a pointer back to its rejection record.

**Status: layout defined; no records exist yet** — rejections require human
listening, which has not happened.
