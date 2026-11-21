#!/usr/bin/env bash
# Times the synthetic tile scenes (script vs render) and profiles run_frame/render with perf.
set -uo pipefail
profile="${1:-rajit}"
enc() { awk '{printf "%s%%0A", $0}' | cut -c1-3500; }

build_out=$(cargo test -p tests --test rajit_render_bench --profile "$profile" --no-run 2>&1)
bin=$(echo "$build_out" | grep -oE '\(?[^ ()]*target/'"$profile"'/deps/rajit_render_bench-[0-9a-f]+' | head -1)
[ -z "$bin" ] && bin=$(find "$PWD/target" -name 'rajit_render_bench-*' -type f -perm -u+x ! -name '*.d' | head -1)
echo "::notice title=render binary::${bin:-NOT FOUND}"
if [ -z "$bin" ] || [ ! -x "$bin" ]; then
  echo "::error title=render build output::$(echo "$build_out" | tail -15 | enc)"; exit 1
fi

for t in tiles_visible tiles_scroll; do
  out=$(cd tests && "$bin" --ignored --nocapture --test-threads=1 "$t" 2>&1)
  line=$(echo "$out" | grep BENCH)
  echo "$out" | tail -5
  echo "::notice title=render $t::${line:-NO BENCH LINE: $(echo "$out" | tail -8 | enc)}"
done

perf_bin=$(command -v perf || ls /usr/lib/linux-tools/*/perf 2>/dev/null | head -1)
[ -z "$perf_bin" ] && { echo "::warning title=perf::perf not available"; exit 0; }
sudo sysctl -w kernel.perf_event_paranoid=-1 kernel.kptr_restrict=0 >/dev/null 2>&1 || true
for t in tiles_visible tiles_scroll; do
  (cd tests && "$perf_bin" record -F 1999 -o "/tmp/r_$t.data" -- "$bin" --ignored --nocapture --test-threads=1 "$t" >/dev/null 2>&1)
  rep=$("$perf_bin" report -i "/tmp/r_$t.data" --no-children --sort symbol --stdio 2>/dev/null \
        | grep -v '^#' | grep -v '^$' | head -34 | sed 's/  */ /g' | cut -c1-170)
  echo "== $t"; echo "$rep"
  echo "::notice title=perf-render $t::$(echo "$rep" | enc)"
done
