# `decisions/` — layout

Decision and selection records for the favorites/fidelity contract
(issue #8 / SXT-013).

```
decisions/
  favorites-TEMPLATE.md      schema + rules for the future frozen favorites-v1
                             (v1 itself does NOT exist yet — freezing is
                             BLOCKED on human listening)
  listening-sessions/        one structured JSON per listening session,
                             written by tools/listening_session.py
  rejected-selections/       retained rejected-selection records with reasons
                             (layout: rejected-selections/README.md)
```

Statuses live elsewhere: per-preset supported/adapted/unsupported/unresolved
statuses will be reported by SXT-029; this directory holds the *selection*
record. Nothing in this directory is a support, fidelity, or quality claim.
