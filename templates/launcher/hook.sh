#!/bin/sh
# code-flow:v1
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd) || exit 0
cd "$root" || exit 0
format=${1:-claude}
node=$(command -v node 2>/dev/null || true)
[ -n "$node" ] || node='__FIXED_NODE__'
bridge="$root/.code-flow/launcher/bridge.cjs"
if [ ! -f "$bridge" ]; then
  printf 'code-flow launcher missing; run init again\n' >&2
  exit 0
fi
if code_flow_output=$("$node" "$bridge" --format "$format" --node '__FIXED_NODE__' --entry '__FIXED_ENTRY__'); then
  if [ -n "$code_flow_output" ]; then
    printf '%s\n' "$code_flow_output"
  fi
else
  printf 'code-flow launcher failed; run doctor\n' >&2
fi
exit 0
