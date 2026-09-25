#!/usr/bin/env bash
# SXT-038 (#72) — build the LP 24 dB pinned-kernel reference harness.
#
# Checks out the manifest-pinned GPL filter submodules into an EXTERNAL
# directory (never inside this repository) and compiles
# oracle/sxt038/lp24_ref_harness.cpp against them.  The resulting binary is a
# GPL-3.0-or-later combined work; it stays in that external directory and is
# never committed or distributed (decision-records/0009).
#
# Pins are read from oracle/manifest.json; any drift aborts (fail-closed).
#
# Usage:
#   ./oracle/sxt038/build_lp24_ref.sh [--dir <external-dir>]
# Environment:
#   SXT038_ORACLE_DIR   external build root (default ~/.cache/sxt038-oracle)
# Prints the harness binary path on stdout.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="${SXT038_ORACLE_DIR:-$HOME/.cache/sxt038-oracle}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$DIR" in
  "$REPO"|"$REPO"/*)
    echo "REFUSING: the external oracle dir must not live inside the repository" >&2
    exit 2 ;;
esac

pin() {  # pin <submodule-path>
  python3 - "$REPO/oracle/manifest.json" "$1" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for s in m["submodules"]:
    if s["path"] == sys.argv[2]:
        print(s["commit"]); break
else:
    sys.exit("REFUSING: submodule %s not pinned in oracle/manifest.json" % sys.argv[2])
PY
}

FILTERS_SHA="$(pin libs/sst/sst-filters)"
BASIC_SHA="$(pin libs/sst/sst-basic-blocks)"

mkdir -p "$DIR"
fetch() {  # fetch <name> <repo-url> <sha>
  local name="$1" url="$2" sha="$3"
  if [ ! -d "$DIR/$name/.git" ]; then
    git clone -q --filter=blob:none --no-checkout "$url" "$DIR/$name"
  fi
  git -C "$DIR/$name" fetch -q --depth 1 origin "$sha"
  git -C "$DIR/$name" checkout -q "$sha"
  local got
  got="$(git -C "$DIR/$name" rev-parse HEAD)"
  if [ "$got" != "$sha" ]; then
    echo "REFUSING: $name is at $got, pinned $sha" >&2
    exit 2
  fi
  if [ -n "$(git -C "$DIR/$name" status --porcelain)" ]; then
    echo "REFUSING: $name checkout has local modifications" >&2
    exit 2
  fi
}

fetch sst-filters      https://github.com/surge-synthesizer/sst-filters.git      "$FILTERS_SHA"
fetch sst-basic-blocks https://github.com/surge-synthesizer/sst-basic-blocks.git "$BASIC_SHA"

OUT="$DIR/lp24_ref_harness"
# -ffp-contract=off: no FMA contraction, so the reference arithmetic is the
# plain IEEE single-precision sequence the pinned kernels spell out.
# -DSIMDE_UNAVAILABLE: use the host's native SSE intrinsics instead of simde;
# the three LP24 kernels use only add/sub/mul/max, which are IEEE-identical
# on both paths.
g++ -O2 -std=c++20 -msse4.2 -ffp-contract=off -DSIMDE_UNAVAILABLE \
    -I "$DIR/sst-filters/include" -I "$DIR/sst-basic-blocks/include" \
    "$REPO/oracle/sxt038/lp24_ref_harness.cpp" -o "$OUT"

{
  echo "harness_source_sha256 $(sha256sum "$REPO/oracle/sxt038/lp24_ref_harness.cpp" | cut -d' ' -f1)"
  echo "sst_filters_commit $FILTERS_SHA"
  echo "sst_basic_blocks_commit $BASIC_SHA"
  echo "compiler $(g++ --version | head -1)"
} > "$DIR/build-provenance.txt"

echo "$OUT"
