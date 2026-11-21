#!/usr/bin/env bash
# Times the synthetic tile scenes (script vs render) and profiles run_frame/render with perf.
set -uo pipefail
profile="${1:-rajit}"
cargo test -p tests --test rajit_render_bench --profile "$profile" --no-run >/dev/null 2>&1
bin=$(find "$PWD/target/$profile/deps" -name 'rajit_render_bench-*' -type f -perm -u+x ! -name '*.d' | head -1)
echo "bench binary: $bin"

for t in tiles_visible tiles_scroll; do
  line=$(cd tests && "$bin" --ignored --nocapture --test-threads=1 "$t" 2>&1 | grep BENCH)
  echo "$line"
  echo "::notice title=render $t::${line}"
done

perf_bin=$(command -v perf || ls /usr/lib/linux-tools/*/perf 2>/dev/null | head -1)
[ -z "$perf_bin" ] && { echo "::warning title=perf::perf not available"; exit 0; }
sudo sysctl -w kernel.perf_event_paranoid=-1 kernel.kptr_restrict=0 >/dev/null 2>&1 || true
for t in tiles_visible tiles_scroll; do
  (cd tests && "$perf_bin" record -F 1999 -o "/tmp/r_$t.data" -- "$bin" --ignored --nocapture --test-threads=1 "$t" >/dev/null 2>&1)
  rep=$("$perf_bin" report -i "/tmp/r_$t.data" --no-children --sort symbol --stdio 2>/dev/null \
        | grep -v '^#' | grep -v '^$' | head -32 | sed 's/  */ /g' | cut -c1-170)
  echo "== $t"; echo "$rep"
  msg=$(echo "$rep" | awk '{printf "%s%%0A", $0}')
  echo "::notice title=perf-render $t::${msg}"
done
