#!/bin/sh
# B-07 — POSIX sh test for scripts/heartbeat-wrap.sh.
#
# heartbeat-wrap.sh has no other tests. Opus verified it by hand end-to-end
# (rc preserved for 0/1/42/127/SIGTERM/SIGKILL/missing-script; a heartbeat
# recorded in every case; `set -u` only; no `exec`; `--` parsing correct). This
# script mechanises those checks so a future edit can't regress them silently.
#
# Run:  sh tests/test_heartbeat_wrap.sh   (or: bash tests/test_heartbeat_wrap.sh)
# Skips cleanly (exit 0) if python3 is unavailable.

set -u

here=$(cd "$(dirname "$0")/.." && pwd)
WRAP="$here/scripts/heartbeat-wrap.sh"
HB="$here/scripts/heartbeat.py"

if ! command -v python3 >/dev/null 2>&1; then
	echo "SKIP: python3 not found"
	exit 0
fi
if [ ! -f "$WRAP" ] || [ ! -f "$HB" ]; then
	echo "SKIP: heartbeat-wrap.sh / heartbeat.py not found"
	exit 0
fi

tmp=$(mktemp -d 2>/dev/null || mktemp -d -t hbwrap)
trap 'rm -rf "$tmp"' EXIT
HBDIR="$tmp/hb"
mkdir -p "$HBDIR"

export HEARTBEAT_PY="$(command -v python3)"
export HEARTBEAT_SCRIPT="$HB"
export HEARTBEAT_DIR="$HBDIR"

fail=0
pass=0

# args: <label> <expected-rc> <slug> -- <cmd...>
check() {
	label=$1; want=$2; slug=$3
	shift 3
	# drop the literal "--"
	[ "${1:-}" = "--" ] && shift
	rm -f "$HBDIR/$slug.json"
	# shellcheck disable=SC2086
	sh "$WRAP" "$slug" -- "$@" >/dev/null 2>&1
	got=$?
	rec_rc=""
	if [ -f "$HBDIR/$slug.json" ]; then
		rec_rc=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['rc'])" "$HBDIR/$slug.json" 2>/dev/null)
	fi
	if [ "$got" = "$want" ] && [ -f "$HBDIR/$slug.json" ] && [ "$rec_rc" = "$want" ]; then
		pass=$((pass + 1))
		echo "PASS  $label  (rc=$got, recorded rc=$rec_rc)"
	else
		fail=$((fail + 1))
		echo "FAIL  $label  want rc=$want got rc=$got recorded=${rec_rc:-<none>}"
	fi
}

check "rc 0"            0   ok_zero      -- /bin/sh -c 'exit 0'
check "rc 1"            1   ok_one       -- /bin/sh -c 'exit 1'
check "rc 42"           42  ok_42        -- /bin/sh -c 'exit 42'
check "missing script"  127 ok_missing   -- /nonexistent/definitely/not/here
check "SIGTERM (143)"   143 ok_sigterm   -- /bin/sh -c 'kill -TERM $$; sleep 5'
check "SIGKILL (137)"   137 ok_sigkill   -- /bin/sh -c 'kill -KILL $$; sleep 5'

# `--` parsing: the command keeps its own args. `sh -c STR name a b` makes
# name=$0 and a,b the positionals, so `exit $#` here exits 2.
check "args after --"   2   ok_args      -- /bin/sh -c 'exit $#' name a b

# usage error (slug only, no command) must exit 2 and NOT write a heartbeat.
rm -f "$HBDIR/no_cmd.json"
sh "$WRAP" no_cmd >/dev/null 2>&1
u=$?
if [ "$u" = "2" ] && [ ! -f "$HBDIR/no_cmd.json" ]; then
	pass=$((pass + 1)); echo "PASS  usage error exits 2, no heartbeat"
else
	fail=$((fail + 1)); echo "FAIL  usage error: got rc=$u, heartbeat present=$([ -f "$HBDIR/no_cmd.json" ] && echo yes || echo no)"
fi

echo "----"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
