#!/bin/bash
# storm_party.sh — run a thunderstorm every INTERVAL minutes for HOURS hours.
# Made to be triggered from Apple Shortcuts ("Start/Stop Storm Party") or the
# terminal. Auto-expires so a forgotten party mode doesn't storm all night.
#
# Usage:
#   ./storm_party.sh start [hours] [interval_minutes]   # defaults: 3h, every 30m
#   ./storm_party.sh stop
#   ./storm_party.sh status

DIR="/Users/bivey/devel/thunderstorm"
PIDFILE="$DIR/.storm_party.pid"
PY="$DIR/.venv/bin/python3"
# Override for testing, e.g. STORM_ARGS="--simulate --duration 5 --no-audio"
STORM_ARGS="${STORM_ARGS:---duration 60 --intensity high}"

case "$1" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Storm party already running (pid $(cat "$PIDFILE")). Run '$0 stop' first."
      exit 1
    fi
    HOURS="${2:-3}"
    INTERVAL_MIN="${3:-30}"
    (
      # Forward a stop to whatever is running: a storm gets SIGTERM and
      # restores the bulbs before exiting; a sleep just dies.
      trap 'kill -TERM "$child" 2>/dev/null; rm -f "$PIDFILE"; exit 0' TERM INT
      end=$(( $(date +%s) + HOURS * 3600 ))
      while [ "$(date +%s)" -lt "$end" ]; do
        cd "$DIR" && $PY thunderstorm.py $STORM_ARGS &
        child=$!
        wait "$child"
        # Don't start a wait that would outlive the party.
        [ $(( $(date +%s) + INTERVAL_MIN * 60 )) -ge "$end" ] && break
        sleep $(( INTERVAL_MIN * 60 )) &
        child=$!
        wait "$child"
      done
      rm -f "$PIDFILE"
    ) >/dev/null 2>&1 &
    echo $! > "$PIDFILE"
    echo "Storm party started: a storm now, then every ${INTERVAL_MIN}m for ${HOURS}h."
    ;;
  stop)
    if [ ! -f "$PIDFILE" ] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      rm -f "$PIDFILE"
      echo "Storm party is not running."
      exit 0
    fi
    kill -TERM "$(cat "$PIDFILE")" 2>/dev/null
    echo "Storm party stopped. If a storm was playing, the lights are being restored."
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Storm party is running (pid $(cat "$PIDFILE"))."
    else
      rm -f "$PIDFILE"
      echo "Storm party is not running."
    fi
    ;;
  *)
    echo "usage: $0 start [hours] [interval_minutes] | stop | status"
    exit 1
    ;;
esac
