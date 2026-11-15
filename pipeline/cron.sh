#!/bin/bash
# Daily data update for cron: a thin wrapper over pipeline/update.sh (all the update logic stays there).
#
# What it does: takes a lock so that two runs never overlap, runs `nice bash pipeline/update.sh` and writes one line
# when it starts and one when it ends (or, on failure, the last 20 lines of its output) to <data root>/_work/cron.log.
# The whole output of the run is in <data root>/_work/update.log (overwritten by every run).
#
# crontab line (07:15 UTC: by then NASA has closed yesterday: the
# downloaded windows count as complete only 6 hours after their last day, NRT_DELAY_H):
#   15 7 * * * /path/to/repo/pipeline/cron.sh
# Run it from any directory: every path is taken from the place of the script, and .env is read from the repository
# root, as update.sh does (SENDA_DATA there points at <data root>/current; the data root is its parent).
# `uv` must be on the PATH of cron (the script adds ~/.local/bin and ~/.cargo/bin).
#
# Exit code: 0 - updated, already up to date, or another run is going (nothing to do now); not 0 - the update failed
# (the code of update.sh), for the mail of cron or a monitor. cron.log keeps the last 2000 lines.
# A lock of a killed run (its pid is gone) is taken over, with a line in the log.
# SENDA_UPDATE_SCRIPT, when set, is run instead of update.sh.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/paths.sh"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"
UPDATE=${SENDA_UPDATE_SCRIPT:-$ROOT/pipeline/update.sh}
WORK=$D/_work
LOG=$WORK/cron.log
FULL=$WORK/update.log
LOCK=$WORK/cron.lock
KEEP_LINES=2000
mkdir -p "$WORK"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

# the lock: a directory with the pid of its owner inside
if ! mkdir "$LOCK" 2>/dev/null; then
  sleep 1  # the owner may be between mkdir and writing its pid
  owner=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then
    log "skipped: another update is running (pid $owner)"
    exit 0
  fi
  log "stale lock of pid ${owner:-unknown} removed"
  rm -rf "$LOCK"
  if ! mkdir "$LOCK" 2>/dev/null; then
    log "skipped: another update took the lock"
    exit 0
  fi
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt "$KEEP_LINES" ]; then
  tail -n "$KEEP_LINES" "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

before=$(readlink "$D/current" 2>/dev/null || true)
started=$(date +%s)
log "start"
nice -n 10 bash "$UPDATE" > "$FULL" 2>&1
code=$?
seconds=$(( $(date +%s) - started ))
after=$(readlink "$D/current" 2>/dev/null || true)
if [ "$code" -eq 0 ]; then
  if [ "$after" = "$before" ]; then
    log "end ok: up to date (${after##*/}), ${seconds} s"
  else
    log "end ok: new version ${after##*/}, ${seconds} s"
  fi
else
  log "end FAILED: exit $code after ${seconds} s, data version ${after##*/}; last 20 lines of update.log:"
  tail -n 20 "$FULL" | sed 's/^/    /' >> "$LOG"
fi
exit "$code"
