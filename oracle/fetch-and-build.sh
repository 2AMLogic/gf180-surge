#!/usr/bin/env bash
#
# SXT-010 oracle fetch/build gate.
#
# Verifies that the EXTERNAL Surge XT engine checkout (GPL-3.0-or-later, kept
# outside this repository) exactly matches the pins in oracle/manifest.json,
# then configures and builds the surgepy python binding and the headless
# surge-testrunner. ANY drift in engine HEAD, any submodule SHA, or any
# modified tracked file in the engine tree aborts with a clear error. The
# script never silently follows upstream.
#
# Usage:
#   oracle/fetch-and-build.sh [--verify-only]
#   oracle/fetch-and-build.sh --prebuilt      (or ORACLE_PREBUILT=1; see below)
#
# --prebuilt (#232) installs the private prebuilt artifact pinned in
# manifest.prebuilt.<platform> instead of building: sha256-verified before
# unpacking, per user under ~/.cache/gf180-surge-oracle/<commit>/, with a
# per-user CPython + numpy at the manifest's versions. It prints the exports.
#   ORACLE_PREBUILT_URL   private store: directory, file path, or https:// base (required, never committed)
#   ORACLE_PREBUILT_ROOT  install root (default ~/.cache/gf180-surge-oracle)
#
# Environment overrides (defaults record the environment used for SXT-010
# evidence; see reports/sxt-010/EVIDENCE.md):
#   ORACLE_SURGE_DIR   engine checkout        (default /Users/joseph/dev/surge-xt-oracle/surge)
#   ORACLE_MANIFEST    manifest to verify against (default <repo>/oracle/manifest.json)
#   ORACLE_PYTHON      python for surgepy     (default /opt/homebrew/opt/python@3.11/bin/python3.11)
#   ORACLE_BUILD_DIR   build dir              (default $ORACLE_SURGE_DIR/build-py311)
#   ORACLE_JOBS        parallel build jobs    (default 10)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFEST="${ORACLE_MANIFEST:-${REPO_ROOT}/oracle/manifest.json}"
ENGINE="${ORACLE_SURGE_DIR:-/Users/joseph/dev/surge-xt-oracle/surge}"
PYTHON_BIN="${ORACLE_PYTHON:-/opt/homebrew/opt/python@3.11/bin/python3.11}"
BUILD_DIR="${ORACLE_BUILD_DIR:-${ENGINE}/build-py311}"
JOBS="${ORACLE_JOBS:-10}"

die() { echo "fetch-and-build: REFUSING: $*" >&2; exit 2; }
info() { echo "fetch-and-build: $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (needed to read the manifest pins)"

# ---- Load pins from the manifest -------------------------------------------
ENGINE_COMMIT="$("python3" - "$MANIFEST" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
print(m["engine"]["commit"])
PYEOF
)" || die "cannot read manifest at $MANIFEST"

SUBMODULE_PINS="$("python3" - "$MANIFEST" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
for s in m["submodules"]:
    print(f'{s["path"]}\t{s["commit"]}')
print("---NESTED---")
for s in m.get("nested_submodules_observed", []):
    print(f'{s["path"]}\t{s["commit"]}')
PYEOF
)" || die "cannot read submodule pins from manifest"

# ---- Prebuilt oracle (#232): fetch, verify, install per user ------------------
# A prebuilt artifact is an internal build of the pinned engine (see
# manifest.prebuilt.<platform>). It is stored privately and NEVER committed,
# since the engine is GPL. Its sha256 is verified BEFORE anything is unpacked,
# because an unverified surgepy .so would be imported on every dispatch worker.
# When the manifest has no entry for this platform, fall through to the
# from-source path below so the original workflow is unchanged.
prebuilt_requested=0
{ [ "${1:-}" = "--prebuilt" ] || [ "${ORACLE_PREBUILT:-0}" = "1" ]; } && prebuilt_requested=1
if [ "$prebuilt_requested" = 1 ]; then
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) PLATFORM=linux-x86_64 ;;
    Darwin-arm64) PLATFORM=darwin-arm64 ;;
    *)            PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)" ;;
  esac
  PB="$("python3" - "$MANIFEST" "$PLATFORM" <<'PYEOF'
import json, sys
p = json.load(open(sys.argv[1])).get("prebuilt", {}).get(sys.argv[2])
if p:
    print("\t".join([p["artifact"], p["sha256"], p["python"]["version"], p["python"]["source"],
                     p["python"]["sha256"], p["numpy"]]))
PYEOF
)" || die "cannot read manifest.prebuilt from $MANIFEST"
  if [ -z "$PB" ]; then
    info "no prebuilt entry for $PLATFORM in the manifest; falling back to the from-source build"
  else
    IFS=$'\t' read -r PB_ART PB_SHA PY_VER PY_URL PY_SHA NUMPY_VER <<< "$PB"
    sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi; }
    BASE="${ORACLE_PREBUILT_ROOT:-$HOME/.cache/gf180-surge-oracle}/$ENGINE_COMMIT"
    DEST="$BASE/$PLATFORM"; PYROOT="$BASE/cpython-$PY_VER"; VENV="$BASE/venv"
    mkdir -p "$BASE"
    if [ -f "$DEST/.installed-sha256" ] && [ "$(cat "$DEST/.installed-sha256")" = "$PB_SHA" ]; then
      info "prebuilt oracle already installed at $DEST (sha256 ${PB_SHA:0:12})"
    else
      SRC="${ORACLE_PREBUILT_URL:-}"
      [ -n "$SRC" ] || die "ORACLE_PREBUILT_URL is unset: point it at the private store holding $PB_ART (a directory, file path, or https:// URL). It is never committed."
      DL="$BASE/$PB_ART.download"
      case "$SRC" in
        http://*|https://*) curl -fsSL -o "$DL" "${SRC%/}/$PB_ART" || die "download failed: ${SRC%/}/$PB_ART" ;;
        file://*)           SRC="${SRC#file://}"; cp -f "$( [ -d "$SRC" ] && echo "$SRC/$PB_ART" || echo "$SRC" )" "$DL" || die "copy failed from $SRC" ;;
        *)                  cp -f "$( [ -d "$SRC" ] && echo "$SRC/$PB_ART" || echo "$SRC" )" "$DL" || die "copy failed from $SRC" ;;
      esac
      GOT="$(sha256_of "$DL")"
      if [ "$GOT" != "$PB_SHA" ]; then
        rm -f -- "$DL"
        die "prebuilt sha256 mismatch: manifest pins $PB_SHA, artifact is $GOT. Not unpacking."
      fi
      info "ok  prebuilt sha256 ${PB_SHA:0:12} matches the manifest"
      rm -rf -- "$DEST.tmp" && mkdir -p "$DEST.tmp"
      tar -C "$DEST.tmp" -xzf "$DL" || die "unpack failed"
      rm -rf -- "$DEST" && mv "$DEST.tmp" "$DEST" && rm -f -- "$DL"
      printf '%s\n' "$PB_SHA" > "$DEST/.installed-sha256"
    fi
    if [ ! -x "$PYROOT/bin/python${PY_VER%.*}" ]; then
      PYDL="$BASE/cpython-$PY_VER.tar.gz"
      curl -fsSL -o "$PYDL" "$PY_URL" || die "download failed: $PY_URL"
      [ "$(sha256_of "$PYDL")" = "$PY_SHA" ] || { rm -f -- "$PYDL"; die "CPython $PY_VER sha256 mismatch (manifest pins $PY_SHA). Not unpacking."; }
      mkdir -p "$PYROOT" && tar -C "$PYROOT" --strip-components=1 -xzf "$PYDL" && rm -f -- "$PYDL"
      info "ok  per-user CPython $PY_VER at $PYROOT"
    fi
    [ -x "$VENV/bin/python" ] || "$PYROOT/bin/python${PY_VER%.*}" -m venv "$VENV" || die "venv creation failed"
    "$VENV/bin/python" -c "import numpy, sys; sys.exit(numpy.__version__ != '$NUMPY_VER')" 2>/dev/null \
      || "$VENV/bin/python" -m pip install -q "numpy==$NUMPY_VER" || die "numpy $NUMPY_VER install failed"
    export ORACLE_SURGE_DIR="$DEST" LD_LIBRARY_PATH="$PYROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    info "smoke: importing the prebuilt surgepy with $VENV/bin/python"
    PYTHONPATH="$DEST/build-py311/src/surge-python" "$VENV/bin/python" -c '
import surgepy, numpy
print("engine version:", surgepy.getVersion())
s = surgepy.createSurge(48000)
print("sr:", s.getSampleRate(), "block:", s.getBlockSize())
s.allNotesOff()
' || die "prebuilt surgepy smoke import failed"
    info "OK: prebuilt pinned oracle installed. Export these to use it:"
    echo "export ORACLE_SURGE_DIR=$DEST"
    echo "export ORACLE_PYTHON=$VENV/bin/python"
    echo "export LD_LIBRARY_PATH=$PYROOT/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
    exit 0
  fi
fi

# ---- Engine checkout identity ----------------------------------------------
[ -d "$ENGINE" ] || die "engine checkout not found at $ENGINE (set ORACLE_SURGE_DIR)"
git -C "$ENGINE" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$ENGINE is not a git work tree"

ACTUAL_COMMIT="$(git -C "$ENGINE" rev-parse HEAD)"
[ "$ACTUAL_COMMIT" = "$ENGINE_COMMIT" ] \
  || die "engine HEAD drift: manifest pins ${ENGINE_COMMIT}, checkout is at ${ACTUAL_COMMIT}. Refusing to build against a different commit."

# Modified tracked files would taint the build even at the right commit.
if [ -n "$(git -C "$ENGINE" status --porcelain --untracked-files=no)" ]; then
  die "engine tree has modified tracked files at $ENGINE; a pinned oracle must build from a clean tree."
fi

# ---- Submodule verification -------------------------------------------------
TOP_PINS="$(printf '%s\n' "$SUBMODULE_PINS" | sed -n '1,/^---NESTED---$/p' | grep -v -- '---NESTED---' || true)"
NESTED_PINS="$(printf '%s\n' "$SUBMODULE_PINS" | sed -n '/^---NESTED---$/,$p' | grep -v -- '---NESTED---' || true)"

FAIL=0
while IFS=$'\t' read -r path pin; do
  [ -n "$path" ] || continue
  SUB="$ENGINE/$path"
  if [ ! -d "$SUB" ]; then
    echo "fetch-and-build: REFUSING: submodule not present on disk: $path (pin $pin)" >&2
    FAIL=1; continue
  fi
  ACTUAL="$(git -C "$SUB" rev-parse HEAD 2>/dev/null)" || { echo "REFUSING: $path: not a git repo" >&2; FAIL=1; continue; }
  if [ "$ACTUAL" != "$pin" ]; then
    echo "fetch-and-build: REFUSING: submodule drift at $path: pin $pin, checkout $ACTUAL" >&2
    FAIL=1; continue
  fi
  # The superproject's recorded gitlink must agree with the pin too.
  RECORDED="$(git -C "$ENGINE" rev-parse "HEAD:${path}" 2>/dev/null || true)"
  if [ -n "$RECORDED" ] && [ "$RECORDED" != "$pin" ]; then
    echo "fetch-and-build: REFUSING: superproject gitlink for $path is $RECORDED, manifest pins $pin" >&2
    FAIL=1; continue
  fi
  info "ok  submodule $path @ ${ACTUAL:0:12}"
done <<< "$TOP_PINS"
[ "$FAIL" -eq 0 ] || die "submodule verification failed; run 'git submodule update --init --recursive' in $ENGINE only if you intend the pinned state."

while IFS=$'\t' read -r path pin; do
  [ -n "$path" ] || continue
  SUB="$ENGINE/$path"
  if [ ! -d "$SUB" ]; then
    info "note: nested submodule absent (not required by chosen build target): $path (pin $pin)"
    continue
  fi
  ACTUAL="$(git -C "$SUB" rev-parse HEAD 2>/dev/null || true)"
  if [ -n "$ACTUAL" ] && [ "$ACTUAL" != "$pin" ]; then
    echo "fetch-and-build: REFUSING: nested submodule drift at $path: pin $pin, checkout $ACTUAL" >&2
    FAIL=1
  elif [ -n "$ACTUAL" ]; then
    info "ok  nested    $path @ ${ACTUAL:0:12}"
  fi
done <<< "$NESTED_PINS"
[ "$FAIL" -eq 0 ] || die "nested submodule verification failed."

info "engine identity verified: ${ENGINE_COMMIT:0:12} with all pinned submodules"

if [ "${1:-}" = "--verify-only" ]; then
  info "verify-only requested; stopping before configure/build"
  exit 0
fi

# ---- Configure (idempotent) and build ---------------------------------------
if [ ! -f "$BUILD_DIR/CMakeCache.txt" ]; then
  info "configuring (first run) in $BUILD_DIR"
  # PYBIND11_FINDPYTHON=OFF: the pinned pybind11's classic FindPythonLibsNew
  # honors PYTHON_EXECUTABLE strictly, unlike new-style FindPython, which in
  # this environment resolves a broken anaconda interpreter regardless of hints.
  (cd "$ENGINE" && cmake -S . -B "$BUILD_DIR" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DSURGE_BUILD_PYTHON_BINDINGS=ON \
      -DSURGE_BUILD_TESTRUNNER=ON \
      -DPYBIND11_FINDPYTHON=OFF \
      -DPYTHON_EXECUTABLE="$PYTHON_BIN") || die "cmake configure failed"
else
  info "reusing existing configure in $BUILD_DIR (set ORACLE_FORCE_CONFIGURE=1 to reconfigure)"
  if [ "${ORACLE_FORCE_CONFIGURE:-0}" = "1" ]; then
    (cd "$ENGINE" && cmake -S . -B "$BUILD_DIR") || die "cmake reconfigure failed"
  fi
fi

info "building surgepy + surge-testrunner (-j$JOBS)"
cmake --build "$BUILD_DIR" --target surgepy surge-testrunner -j"$JOBS" || die "build failed"

# ---- Smoke check ------------------------------------------------------------
SO_DIR="$BUILD_DIR/src/surge-python"
PKG_DIR="$ENGINE/src/surge-python"
info "smoke: importing surgepy with $PYTHON_BIN"
PYTHONPATH="$SO_DIR:$PKG_DIR" "$PYTHON_BIN" -c '
import surgepy, numpy, os
print("surgepy imported from", os.path.dirname(surgepy.__file__))
print("engine version:", surgepy.getVersion())
s = surgepy.createSurge(48000)
print("sr:", s.getSampleRate(), "block:", s.getBlockSize())
s.allNotesOff()
' || die "surgepy smoke import failed"

info "OK: pinned oracle built and importable"
