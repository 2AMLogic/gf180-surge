#!/bin/sh
# Issue #720 measurement, reproducible in a scratch checkout OUTSIDE tracked paths.
# Measured 2026-11-17 on Ubuntu 24.04 (noble), Python 3.12.3. See ENV-REFUTATION.md.
#
# The Linux legs of ENV-REFUTATION.md used numpy 1.26.4 in a throwaway venv
# (the runner's digests are numpy-sensitive; see ENV-REFUTATION.md finding 3),
# and one of two iverilog binaries per leg:
#
#   12.0-2build2  the signoff pin. Its presence is worker-dependent: on some
#                 fleet workers it is the dpkg-installed /usr/bin/iverilog
#                 (`dpkg -s iverilog` -> install ok installed); on others
#                 there is no distro iverilog at all (both measured). This
#                 script therefore USES /usr/bin/iverilog when it reports
#                 12.0, and otherwise obtains the exact 12.0-2build2 deb in a
#                 throwaway directory (`apt-get download` + `dpkg -x`;
#                 nothing host-wide, no sudo) and runs it through a shim that
#                 rewrites the deb's baked-in `#! /usr/bin/vvp` shebang to
#                 the extracted vvp (the runner execs ./sim.out directly).
#                 Set SXT024_PIN_SOURCE=deb to force the fallback path.
#   13.0 (v13_0)  the worker-local build at ~/.local/bin/iverilog (the
#                 version the committed rtl-exactness.json cites).
#
# Each leg quotes the `iverilog -V` it actually resolved via the runner's
# rtl-exactness.json "iverilog" field.

set -e

VENV=${SXT024_VENV:-/tmp/sxt024-venv-1264}
DEBDIR=${SXT024_DEBDIR:-/tmp/sxt024-pin-12.0-deb}

# 0) numpy venv the legs ran under (any python3 with venv+pip; no host installs)
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet numpy==1.26.4
fi
"$VENV/bin/python" -c "import numpy; assert numpy.__version__ == '1.26.4', numpy.__version__"

# 1) resolve the pin binary: /usr/bin/iverilog if it IS the pin, else the deb
pin_path=""
if [ "${SXT024_PIN_SOURCE:-auto}" != "deb" ] \
   && [ -x /usr/bin/iverilog ] \
   && /usr/bin/iverilog -V 2>&1 | grep -q "version 12.0"; then
  pin_path=/usr/bin
  echo "== pin leg uses dpkg-installed $(/usr/bin/iverilog -V 2>&1 | head -1)"
else
  echo "== no distro 12.0 iverilog; obtaining the exact 12.0-2build2 deb"
  rm -rf "$DEBDIR" && mkdir -p "$DEBDIR/shim"
  ( cd "$DEBDIR" && apt-get download iverilog >/dev/null && dpkg -x iverilog_*.deb dir )
  cat > "$DEBDIR/shim/iverilog" <<EOF
#!/bin/sh
"$DEBDIR/dir/usr/bin/iverilog" "\$@" || exit \$?
[ -f sim.out ] && head -c 20 sim.out 2>/dev/null | grep -aq "/usr/bin/vvp" \
  && sed -i "1s|^#! /usr/bin/vvp|#! $DEBDIR/dir/usr/bin/vvp|" sim.out
exit 0
EOF
  chmod +x "$DEBDIR/shim/iverilog"
  pin_path="$DEBDIR/shim"
  echo "== pin leg uses unpacked deb: $($DEBDIR/dir/usr/bin/iverilog -V 2>&1 | head -1)"
fi

# 2) pinned leg (scratch tree via git archive; kept logs stay in /tmp)
rm -rf /tmp/sxt024-pin && mkdir -p /tmp/sxt024-pin
git archive HEAD | tar -C /tmp/sxt024-pin -xf -
( cd /tmp/sxt024-pin && env PATH="$pin_path:/usr/bin:/bin" "$VENV/bin/python" tools/run_reverb_rtl.py --keep )
"$VENV/bin/python" - <<'PY'
import json; d = json.load(open('/tmp/sxt024-pin/reports/sxt-024/rtl-exactness.json'))
print('pin leg | iverilog:', d['iverilog'], 'status:', d['status'])
for c in d['cases'] + [d['mutant_control']]:
    print(c['case'], c['txn_log_sha256'])
PY

# 3) 13.0 leg (fresh scratch; the --keep dirs and rtl-exactness.json are per-tree state)
rm -rf /tmp/sxt024-v13 && mkdir -p /tmp/sxt024-v13
git archive HEAD | tar -C /tmp/sxt024-v13 -xf -
( cd /tmp/sxt024-v13 && env PATH="$HOME/.local/bin:/usr/bin:/bin" "$VENV/bin/python" tools/run_reverb_rtl.py --keep )
"$VENV/bin/python" - <<'PY'
import json; d = json.load(open('/tmp/sxt024-v13/reports/sxt-024/rtl-exactness.json'))
print('13.0 leg | iverilog:', d['iverilog'], 'status:', d['status'])
for c in d['cases'] + [d['mutant_control']]:
    print(c['case'], c['txn_log_sha256'])
PY

# 4) byte-diff of the kept transaction logs (the actual cross-version claim)
for c in prs-256b-reset48 click-512b; do
  cmp "/tmp/sxt024-pin/reports/sxt-024/rtl/$c/out/sxt-024/rtl/txn_rtl.txt" \
      "/tmp/sxt024-v13/reports/sxt-024/rtl/$c/out/sxt-024/rtl/txn_rtl.txt" \
      && echo "$c txn_rtl.txt: byte-identical (12.0-2build2 vs 13.0 v13_0)"
done

# Expected (2026-11-17 worker, both legs): PASS, logs byte-identical, digests
# fbbeeba6…/d75c9b89…/mutant 5a07312f… — NOT the committed macOS generation
# digests f74affb0…/b8f5c0ac…/6e8bf8a8…; see ENV-REFUTATION.md.
