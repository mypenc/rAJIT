#!/usr/bin/env bash
# Samples the rAJIT benchmarks with perf and reports the hottest symbols as annotations.
set -uo pipefail
profile="${1:-rajit}"
cargo test -p tests --test tests --profile "$profile" --no-run >/dev/null 2>&1
bin=$(find "$PWD/target/$profile" -path '*build/tests*' -name 'tests-*' -type f -perm -u+x ! -name '*.d' | head -1)
echo "test binary: $bin"
perf_bin=$(command -v perf || ls /usr/lib/linux-tools/*/perf 2>/dev/null | head -1)
[ -z "$perf_bin" ] && { echo "::warning title=perf::perf not available"; exit 0; }
sudo sysctl -w kernel.perf_event_paranoid=-1 kernel.kptr_restrict=0 >/dev/null 2>&1 || true

for t in rajit_vars rajit_calls; do
  (cd tests && "$perf_bin" record -F 1999 -o "/tmp/$t.data" -- "$bin" "$t" >/dev/null 2>&1)
  rep=$("$perf_bin" report -i "/tmp/$t.data" --no-children --sort symbol --stdio 2>/dev/null \
        | grep -v '^#' | grep -v '^$' | head -28 | sed 's/  */ /g' | cut -c1-150)
  echo "== $t"; echo "$rep"
  msg=$(echo "$rep" | awk '{printf "%s%%0A", $0}')
  echo "::notice title=perf $t::${msg}"
done
