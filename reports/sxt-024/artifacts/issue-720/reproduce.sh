#!/bin/sh
# Issue #720 measurement, reproducible in a scratch checkout OUTSIDE tracked paths.
# Measured 2026-11-17 on Ubuntu 24.04 (noble), Python 3.12.3. See ENV-REFUTATION.md.
#
# Versions on the worker (dpkg -S /usr/bin/iverilog -> iverilog 12.0-2build2):
#   /usr/bin/iverilog                 12.0 (stable) ()          <- the signoff pin
#   ~/.local/bin/iverilog             13.0 (stable) (v13_0)     <- default-PATH shadow
#
# 1) pinned leg
rm -rf /tmp/sxt024-pin && mkdir -p /tmp/sxt024-pin
git archive HEAD | tar -C /tmp/sxt024-pin -xf -
( cd /tmp/sxt024-pin && env PATH="/usr/bin:/bin" python3 tools/run_reverb_rtl.py --keep )
python3 - <<'PY'
import json; d = json.load(open('/tmp/sxt024-pin/reports/sxt-024/rtl-exactness.json'))
print('iverilog:', d['iverilog'], 'status:', d['status'])
for c in d['cases'] + [d['mutant_control']]:
    print(c['case'], c['txn_log_sha256'])
PY

# 2) 13.0 leg (fresh scratch; the --keep dirs and rtl-exactness.json are per-tree state)
rm -rf /tmp/sxt024-v13 && mkdir -p /tmp/sxt024-v13
git archive HEAD | tar -C /tmp/sxt024-v13 -xf -
( cd /tmp/sxt024-v13 && env PATH="$HOME/.local/bin:/usr/bin:/bin" python3 tools/run_reverb_rtl.py --keep )

# 3) byte-diff of the kept transaction logs
for c in prs-256b-reset48 click-512b; do
  cmp "/tmp/sxt024-pin/reports/sxt-024/rtl/$c/out/sxt-024/rtl/txn_rtl.txt" \
      "/tmp/sxt024-v13/reports/sxt-024/rtl/$c/out/sxt-024/rtl/txn_rtl.txt" \
      && echo "$c txn_rtl.txt: byte-identical (12.0-2build2 vs 13.0 v13_0)"
done

# Expected (2026-11-17 worker): both legs PASS, logs byte-identical,
# digests fbbeeba6…/d75c9b89…/mutant 5a07312f… — NOT the committed macOS
# generation digests f74affb0…/b8f5c0ac…/6e8bf8a8…; see ENV-REFUTATION.md.
