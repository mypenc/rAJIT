#!/usr/bin/env bash
# Runs each rAJIT benchmark test with the interpreter and with the compiled tier
# (best of 3) and reports the timings as workflow annotations.
# "net" subtracts the fixed harness start-up cost measured by the rajit_noop test.
set -uo pipefail
profile="${1:-rajit}"

best_of_3() {
  local test="$1" best=""
  for _ in 1 2 3; do
    local out secs
    out=$(cargo test -p tests --test tests --profile "$profile" -- "$test" 2>&1)
    secs=$(echo "$out" | grep -oE 'finished in [0-9.]+s' | grep -oE '[0-9.]+' | head -1)
    if ! echo "$out" | grep -q "test result: ok"; then
      echo "::error title=bench::$test FAILED"; echo "$out" | tail -20; exit 1
    fi
    if [ -z "$best" ] || awk "BEGIN{exit !($secs < $best)}"; then best="$secs"; fi
  done
  echo "$best"
}

noop=$(best_of_3 rajit_noop)
echo "::notice title=bench rajit_noop::fixed harness cost=${noop}s"

for t in rajit_loop rajit_vars rajit_calls; do
  interp=$(RAJIT_DISABLE=1 best_of_3 "$t")
  jit=$(best_of_3 "$t")
  ni=$(awk "BEGIN{printf \"%.2f\", $interp - $noop}")
  nj=$(awk "BEGIN{printf \"%.2f\", $jit - $noop}")
  ratio=$(awk "BEGIN{r = ($nj > 0.01) ? $ni / $nj : 0; printf \"%.2f\", r}")
  echo "::notice title=bench $t::net interp=${ni}s jit=${nj}s speedup=${ratio}x (raw ${interp}s / ${jit}s)"
  echo "$t net interp=${ni}s jit=${nj}s speedup=${ratio}x"
done
