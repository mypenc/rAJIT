#!/usr/bin/env bash
# Usage: assemble_site.sh <artifacts-dir> <out-dir>
# Builds the static site: UI + service worker + one Ruffle build per engine.
set -euo pipefail
art="$1"; out="$2"
rm -rf "$out"; mkdir -p "$out"
cp -r pages-site/* "$out/"
for v in rajit stock; do
  mkdir -p "$out/ruffle-$v"
  cp -r "$art/web-$v/." "$out/ruffle-$v/"
done
touch "$out/.nojekyll"
ls -la "$out" "$out/ruffle-rajit" | head -30
