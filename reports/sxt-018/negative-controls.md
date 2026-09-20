# SXT-018 negative controls — backlog DAG board

Date: 2026-09-20. Environment: disposable copies of the repository tree at
commit `75a64cf` (`loom/sxt-018-dag-board`), made with `cp -R` under
`/tmp/sxt-018-nc/`; each control ran `python3 tools/compile_backlog_dag.py
--check` inside its own copy. No repository state was modified (all edits
happened in the throwaway copies, which were discarded afterwards).

A control counts as demonstrated only when the targeted check **fails with
exit 1** for the injected defect and the baseline still passes.

## Baseline (control of controls)

The unmodified copy must PASS — otherwise the controls below prove nothing.

```console
$ cd /tmp/sxt-018-nc/pristine
$ python3 tools/compile_backlog_dag.py --check
dag-check: PASS (26 nodes: READY=0, IN PROGRESS=1, BLOCKED=4, NOT RUN=19, PASS=2, FAIL=0, NO VERDICT=0, STALE=0)
Claim counts, not a completion percentage or a quality score. READY is unrun, not PASS.
Coverage and agreement are reported separately by the underlying evidence; this board merges neither.
$ echo $?
0
```

## (a) Editing `docs/dag.json` without re-rendering → freshness failure

Injected: node 7 status `NOT_RUN` → `READY` (a legitimate edit that must
trigger a re-render), README left untouched.

```console
$ python3 - <<'EOF'
import json
dag = json.load(open("docs/dag.json"))
for n in dag["nodes"]:
    if n["id"] == 7:
        n["status"] = "READY"
json.dump(dag, open("docs/dag.json", "w"), indent=2, ensure_ascii=False)
open("docs/dag.json", "a").write("\n")
EOF
$ python3 tools/compile_backlog_dag.py --check
dag-check: FAIL
README.md: DAG block is stale (regenerated block differs); run `python3 tools/compile_backlog_dag.py render` and commit both files
$ echo $?
1
```

Rejected: the regenerated board is byte-compared against the committed block;
silent drift is impossible.

## (b) PASS evidence rules → rejection of every approval-by-existence shortcut

### (b1) PASS node without `evidence_sha256`

```console
$ python3 - <<'EOF'
import json
dag = json.load(open("docs/dag.json"))
for n in dag["nodes"]:
    if n["id"] == 4:
        del n["evidence_sha256"]
json.dump(dag, open("docs/dag.json", "w"), indent=2, ensure_ascii=False)
open("docs/dag.json", "a").write("\n")
EOF
$ python3 tools/compile_backlog_dag.py --check
dag-check: FAIL
  - node 4: PASS requires 'evidence_sha256' (sha256 of the evidence file); run `python3 tools/compile_backlog_dag.py render` to compute and store it
$ echo $?
1
```

### (b2) PASS node with a wrong (plausible-looking) `evidence_sha256`

```console
$ python3 - <<'EOF'
import json
dag = json.load(open("docs/dag.json"))
for n in dag["nodes"]:
    if n["id"] == 4:
        n["evidence_sha256"] = "0" * 64
json.dump(dag, open("docs/dag.json", "w"), indent=2, ensure_ascii=False)
open("docs/dag.json", "a").write("\n")
EOF
$ python3 tools/compile_backlog_dag.py --check
dag-check: FAIL
  - node 4: evidence_sha256 does not match the current content of 'corpus/census-v0.1/results/summary.json' (recorded '0000000000000000000000000000000000000000000000000000000000000000', actual 'a10bc754c627c61ee835d74d040fb466909ecf41ceeef55cacb43bbc6b32d59e'); evidence changed after the board was rendered — STALE
$ echo $?
1
```

Rejected: a hash mismatch means the evidence file changed after the board was
rendered; the node cannot silently keep its PASS.

### (b3) PASS node without any evidence pointer

```console
$ python3 - <<'EOF'
import json
dag = json.load(open("docs/dag.json"))
for n in dag["nodes"]:
    if n["id"] == 5:
        del n["evidence"]
        del n["evidence_sha256"]
json.dump(dag, open("docs/dag.json", "w"), indent=2, ensure_ascii=False)
open("docs/dag.json", "a").write("\n")
EOF
$ python3 tools/compile_backlog_dag.py --check
dag-check: FAIL
  - node 5: PASS requires an 'evidence' path to a committed artifact
$ echo $?
1
```

### (b4) Approval-by-file-existence: PASS pointing at an uncommitted file

Injected: a brand-new `reports/uncommitted-evidence.json` that exists on disk
and is hashed correctly, but is not committed to git (torchsynth-audit gap:
"do not accept an arbitrary existing file as evidence").

```console
$ echo '{"fake": "evidence"}' > reports/uncommitted-evidence.json
$ python3 - <<'EOF'
import hashlib, json
dag = json.load(open("docs/dag.json"))
for n in dag["nodes"]:
    if n["id"] == 6:
        n["status"] = "PASS"
        n["evidence"] = "reports/uncommitted-evidence.json"
        n["evidence_sha256"] = hashlib.sha256(open("reports/uncommitted-evidence.json", "rb").read()).hexdigest()
json.dump(dag, open("docs/dag.json", "w"), indent=2, ensure_ascii=False)
open("docs/dag.json", "a").write("\n")
EOF
$ python3 tools/compile_backlog_dag.py --check
dag-check: FAIL
  - node 6: evidence file 'reports/uncommitted-evidence.json' is not committed to git
$ echo $?
1
```

Rejected: PASS evidence must be committed (`git ls-files --error-unmatch`),
not merely present.

## (c) Unknown status string → vocabulary rejection

```console
$ python3 - <<'EOF'
import json
dag = json.load(open("docs/dag.json"))
for n in dag["nodes"]:
    if n["id"] == 6:
        n["status"] = "DONE"
json.dump(dag, open("docs/dag.json", "w"), indent=2, ensure_ascii=False)
open("docs/dag.json", "a").write("\n")
EOF
$ python3 tools/compile_backlog_dag.py --check
dag-check: FAIL
  - node 6: unknown status 'DONE'; allowed vocabulary: READY, IN_PROGRESS, BLOCKED, NOT_RUN, PASS, FAIL, NO_VERDICT, STALE
$ echo $?
1
```

## Bonus control: dependency cycle

Injected: `#4 depends_on #5` and `#5 depends_on #4` — the acyclicity check
must fire (it is a declared validation, so it gets its own demonstration).

```console
$ python3 - <<'EOF'
import json
dag = json.load(open("docs/dag.json"))
for n in dag["nodes"]:
    if n["id"] == 4:
        n["depends_on"] = [5]
    if n["id"] == 5:
        n["depends_on"] = [4]
json.dump(dag, open("docs/dag.json", "w"), indent=2, ensure_ascii=False)
open("docs/dag.json", "a").write("\n")
EOF
$ python3 tools/compile_backlog_dag.py --check
dag-check: FAIL
  - dependency cycle: 5 -> 4 -> 5
$ echo $?
1
```

## Outcome summary

| Control | Injected defect | Expected | Observed |
|---|---|---|---|
| baseline | none | PASS, exit 0 | PASS, exit 0 |
| (a) | `dag.json` edited, no re-render | stale-block failure | `README.md: DAG block is stale`, exit 1 |
| (b1) | PASS without `evidence_sha256` | rejection | schema rejection, exit 1 |
| (b2) | PASS with wrong hash | rejection as STALE evidence | hash mismatch, exit 1 |
| (b3) | PASS without evidence path | rejection | schema rejection, exit 1 |
| (b4) | PASS on uncommitted file | rejection (no approval-by-existence) | not committed to git, exit 1 |
| (c) | status `"DONE"` | vocabulary rejection | unknown status, exit 1 |
| bonus | `4 → 5 → 4` cycle | acyclicity rejection | `dependency cycle: 5 -> 4 -> 5`, exit 1 |

All copies under `/tmp/sxt-018-nc/` were discarded; the repository was never
modified by these runs.
