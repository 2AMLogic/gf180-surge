#!/usr/bin/env bash
#
# SXT-028e-sse: fetch the pinned, GPL-3.0-or-later waveshaper headers into an
# EXTERNAL directory so tools/check_fuzz_table_rederivation.py can build
# against the engine's own source instead of a copy of it.
#
# This repository is Apache-2.0 and deliberately contains NO Surge/SST source.
# The script therefore REFUSES to write anywhere inside the repository, and
# pins every checkout to the exact submodule SHA recorded in
# oracle/manifest.json -- any drift aborts, it never follows upstream.
#
# It is a convenience only: on a host that already has a full pinned engine
# checkout, set ORACLE_SURGE_DIR instead and skip this script entirely. With
# neither available the checker reports NOT_RUN, never a silent pass.
#
# Usage:
#   oracle/fetch-waveshaper-headers.sh [--dest DIR] [--with-simde] [--verify-only]
#
# Environment overrides:
#   SXT_ORACLE_HEADERS_DIR  destination (default ${TMPDIR:-/tmp}/sxt-oracle)
#   ORACLE_MANIFEST         manifest to pin against (default <repo>/oracle/manifest.json)
#
# simde is only needed on hosts that are not native x86-64; on x86-64 the
# checker compiles the pinned SIMD setup header's native SSE path instead.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFEST="${ORACLE_MANIFEST:-${REPO_ROOT}/oracle/manifest.json}"
DEST="${SXT_ORACLE_HEADERS_DIR:-${TMPDIR:-/tmp}/sxt-oracle}"
WITH_SIMDE=0
VERIFY_ONLY=0

die() { echo "fetch-waveshaper-headers: REFUSING: $*" >&2; exit 2; }
info() { echo "fetch-waveshaper-headers: $*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dest) DEST="${2:?--dest needs a directory}"; shift 2 ;;
        --with-simde) WITH_SIMDE=1; shift ;;
        --verify-only) VERIFY_ONLY=1; shift ;;
        -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

command -v git >/dev/null 2>&1 || die "git not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (needed to read the manifest pins)"

DEST="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$DEST")"

# ---- Never write GPL source into this Apache-2.0 repository ----------------
case "${DEST}/" in
    "${REPO_ROOT}/"*) die "destination ${DEST} is inside the repository ${REPO_ROOT}; the pinned GPL-3.0-or-later sources must stay external" ;;
esac

pin_for() {
    python3 - "$MANIFEST" "$1" <<'PYEOF'
import json, sys
man = json.load(open(sys.argv[1]))
for s in man["submodules"]:
    if s["path"] == sys.argv[2]:
        print(s["commit"])
        break
else:
    sys.exit(f"no submodule pin for {sys.argv[2]} in {sys.argv[1]}")
PYEOF
}

fetch_one() {
    local name="$1" url="$2" sha="$3" dir="${DEST}/$1"
    if [ -d "${dir}/.git" ]; then
        local head
        head="$(git -C "$dir" rev-parse HEAD)"
        if [ "$head" = "$sha" ]; then
            info "$name already at pinned $sha"
            return 0
        fi
        [ "$VERIFY_ONLY" -eq 1 ] && die "$name at $dir is $head, not the pinned $sha"
        info "$name is $head, re-pinning to $sha"
    else
        [ "$VERIFY_ONLY" -eq 1 ] && die "$name is not present at $dir"
        mkdir -p "$dir"
        git -C "$dir" init --quiet
        git -C "$dir" remote add origin "$url"
    fi
    git -C "$dir" fetch --quiet --depth 1 origin "$sha"
    git -C "$dir" checkout --quiet --detach FETCH_HEAD
    local head
    head="$(git -C "$dir" rev-parse HEAD)"
    [ "$head" = "$sha" ] || die "$name checked out $head, expected the pinned $sha"
    info "$name pinned at $sha"
}

WS_SHA="$(pin_for libs/sst/sst-waveshapers)"
BB_SHA="$(pin_for libs/sst/sst-basic-blocks)"

mkdir -p "$DEST"
fetch_one sst-waveshapers https://github.com/surge-synthesizer/sst-waveshapers "$WS_SHA"
fetch_one sst-basic-blocks https://github.com/surge-synthesizer/sst-basic-blocks "$BB_SHA"
if [ "$WITH_SIMDE" -eq 1 ]; then
    fetch_one simde https://github.com/simd-everywhere/simde "$(pin_for libs/simde)"
fi

info "pinned GPL-3.0-or-later headers are in ${DEST} (outside the repository)"
info "run: SXT_ORACLE_HEADERS_DIR=${DEST} python3 tools/check_fuzz_table_rederivation.py"
