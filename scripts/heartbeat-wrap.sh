#!/bin/sh
# B-07 heartbeat wrapper — the single, uniform way every cron line records a heartbeat.
#
#   heartbeat-wrap <job-slug> -- <command> [args...]
#
# Runs <command>, captures its REAL exit code, records a heartbeat, then re-exits
# that exact code. A heartbeat failure is printed as a warning and NEVER changes
# the job's exit status.
#
# Why a helper and not `<cmd>; python3 heartbeat.py write <slug> --rc $?` inline:
#   * `$?` positioning is fragile after `&&`/`cd` chains and after trailing
#     `# comments` on a crontab line (cron passes the whole line to /bin/sh, so a
#     `#` mid-line would swallow the heartbeat call).
#   * the helper keeps the recorded exit code, entrypoint and tree consistent
#     across all 21 lines with zero per-line reasoning.
#
# Deploy: copy to /root/ops/heartbeat-wrap (chmod 755). Override the interpreter
# or script path with HEARTBEAT_PY / HEARTBEAT_SCRIPT if needed.
set -u

HB_PY="${HEARTBEAT_PY:-/usr/bin/python3}"
HB_SCRIPT="${HEARTBEAT_SCRIPT:-/root/ops/heartbeat.py}"

job=""
while [ $# -gt 0 ]; do
	case "$1" in
		--) shift; break ;;
		*)
			if [ -z "$job" ]; then job="$1"; shift
			else break
			fi ;;
	esac
done

if [ -z "$job" ] || [ $# -eq 0 ]; then
	echo "heartbeat-wrap: usage: heartbeat-wrap <job-slug> -- <command> [args...]" >&2
	exit 2
fi

target="$1"

# Best-effort tree for the git sha: the directory of the first path-like argument.
tree=""
case "$target" in
	*/*)
		d=$(dirname "$target")
		tree=$(cd "$d" 2>/dev/null && pwd || echo "")
		;;
esac

# --- run the real job -------------------------------------------------------
"$@"
rc=$?

# --- record the heartbeat (must never change rc) --------------------------
"$HB_PY" "$HB_SCRIPT" write "$job" --rc "$rc" --entrypoint "$target" --tree "$tree" \
	|| echo "heartbeat-wrap: WARNING — heartbeat write failed for $job (rc=$rc preserved)" >&2

exit "$rc"
