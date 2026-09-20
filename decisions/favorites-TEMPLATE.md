# Favorites selection — TEMPLATE (v1 does not exist yet)

Status: **TEMPLATE — nothing is frozen.** The artifact below will become
`decisions/favorites-v1.json` (+ this human-readable companion) only after
the human listening selection completes (issue #8 / SXT-013). As of
2026-09-20 freezing is **BLOCKED on human listening**: no ratings from a
human operator exist for any slate candidate.

Proposed candidate pools (NOT selections) live in
`reports/sxt-013/candidates/`:
`slate-256-<profile>.json` / `pilot-32-<profile>.json` for
`balanced` / `factory-lean` / `contributor-lean`. The human chooser picks a
quota profile first, then selects presets by listening — not by hand from
scratch, and not by trusting the proposal.

---

## `decisions/favorites-v1.json` schema (to be populated at freeze)

```json
{
  "schema_version": "sxt-013-favorites-v1/1.0.0",
  "status": "FROZEN",
  "frozen_at_utc": "<ISO-8601>",
  "frozen_by": "<human operator(s)>",
  "quota_profile": "<balanced|factory-lean|contributor-lean|revised:...>",
  "inputs": {
    "slate_artifact": "<slate-256-<profile>.json>",
    "slate_sha256": "<sha256 of the exact slate the selection was made from>",
    "listening_sessions": ["<session ids>"]
  },
  "pilot": {
    "note": "32-preset pilot set; established the evaluation process; does NOT substitute for the 256 goal",
    "candidate_ids": ["<census path>", "..."]
  },
  "selections": [
    {
      "candidate_id": "<census path>",
      "bank": "<factory|contributor>",
      "category": "<basses|leads|keys|plucks|pads|rhythmic|textures>",
      "census_blob_sha1": "<sha1>",
      "rating_summary": {
        "open_mode_sessions": ["<session ids>"],
        "fidelity_1to5_median": "<n>",
        "artifacts": "<none|minor|severe>",
        "notes_present": true
      },
      "decision_reason": "<why this preset made the set>"
    }
  ],
  "coverage": {
    "total": 256,
    "banks": {"factory": "<n>", "contributor": "<n>"},
    "categories": {"<category>": "<n>"}
  }
}
```

## Rejected-selection records (retained with reasons — acceptance requirement)

Every candidate that was listened to and NOT selected is retained in
`decisions/rejected-selections/` with its reason (layout:
`decisions/rejected-selections/README.md`). Rejections are first-class
records: the predeclared-target argument (plan §2) depends on the original
list AND the rejected alternatives both being auditable.

## Rules the freeze must satisfy (from issue #8 acceptance)

- 256 selections named with corpus census hashes; both banks and all seven
  categories covered (issue #8).
- Listening records retained; blind level-matched listening may supplement,
  never replace, level-correct measurements/unblinded ratings.
- Selected BEFORE hardware exclusions are known; the list is not revised
  after SXT-017 resource findings except as a visible contract revision.
- A deliberately degraded render (e.g., substituted generic reverb) must fail
  the frozen fidelity policy or be classed adapted, never supported.
