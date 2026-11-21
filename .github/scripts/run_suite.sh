#!/usr/bin/env bash
# Runs the full regression suite; on failure, reports the failing tests as annotations and
# re-runs each one alone to tell flaky failures from reproducible ones.
# Usage: run_suite.sh <label> [profile]
set -uo pipefail
label="${1:-suite}"; profile="${2:-ci}"
log="/tmp/suite-$label.log"

cargo test -p tests --test tests --profile "$profile" 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
[ "$status" = "0" ] && exit 0

failed=$(grep -E '^test .* FAILED$' "$log" | awk '{print $2}')
names=$(echo "$failed" | head -60 | awk '{printf "%s%%0A", $0}')
echo "::warning title=$label failed in full run::${names}"
details=$(sed -n '/^failures:/,$p' "$log" | head -80 | cut -c1-300 | awk '{printf "%s%%0A", $0}')
echo "::warning title=$label failure section::${details}"

real=0
for n in $failed; do
  if cargo test -p tests --test tests --profile "$profile" -- "$n" > /tmp/rerun.log 2>&1; then
    echo "::warning title=$label flaky::$n passed when re-run alone"
  else
    real=1
    echo "::error title=$label reproducible failure::$n"
  fi
done
exit $real
