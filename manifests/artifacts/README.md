# Evidence manifests (artifact store)

New simulation and signoff evidence keeps its raw bytes in the fleet's artifact
store. Git holds, per run, one `<bench>-<run-id>.manifest.json` and one
`<bench>-<run-id>.summary.md` (name, size, sha256, uri per object). Evidence
bytes are private; manifests are safe to commit.

Manifest-forward only: evidence already under `reports/` stays where it is and
is not retargeted.

## Workflow

1. Write the run's raw outputs into `.evidence-scratch/<bench>-<run-id>/`
   (git-ignored).
2. `python3 tools/store_evidence.py --bench <bench> --run-id <run-id> .evidence-scratch/<bench>-<run-id>`
3. Commit only the two files it wrote.
4. `klt artifact verify manifests/artifacts/<bench>-<run-id>.manifest.json`
   checks the store still holds every object. A worker with
   `$KLT_ARTIFACT_BROKER` is needed; without it the check is NOT_RUN.

The writer fails closed. With the broker variable unset or empty, `klt` missing
or lacking `artifact put`, or the broker unreachable, it exits nonzero and
writes nothing. There is no fallback to committing bytes. Never write the
broker URL into the repo.

## CI check

`python3 tools/check_artifact_manifests.py` requires: schema version 1 and
non-empty entries; every `uri` starts with `artifact:`; no file in this
directory names a storage bucket, cloud account, or presigned-URL marker
(see `FORBIDDEN` in the checker); no git-tracked file has the bytes of a
stored object; nothing under `.evidence-scratch/` is tracked; each manifest has
a summary listing every sha256.

## What a manifest does and does not show

It shows the bytes were stored and which hashes were recorded. It does not
establish an RTL-vs-model, model-vs-reference, or listening claim.

`demo-532.*` is a demonstration object only (a text file, not evidence).

Method adapted from 2AMLogic/sg13g2-comparator PRs 319 and 321 (Apache-2.0).
