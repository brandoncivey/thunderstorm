#!/bin/bash
# rain_ambience.sh — background rain sound bed (audio only, no lights).
# Made to be triggered from Apple Shortcuts or the terminal. Auto-expires
# so forgotten rain doesn't pour forever.
#
# Usage:
#   ./rain_ambience.sh start [hours] [extra rain_ambience.py flags...]
#       e.g. ./rain_ambience.sh start            # 8 hours of rain
#            ./rain_ambience.sh start 2 --thunder
#            ./rain_ambience.sh start 8 --storms --volume 0.6
#   ./rain_ambience.sh stop
#   ./rain_ambience.sh status

DIR="/Users/bivey/devel/thunderstorm"
PIDFILE="$DIR/.rain_ambience.pid"
PY="$DIR/.venv/bin/python3"

case "$1" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Rain is already running (pid $(cat "$PIDFILE")). Run '$0 stop' first."
      exit 1
    fi
    rm -f "$PIDFILE"
    HOURS="${2:-8}"
    [ $# -ge 2 ] && shift 2 || shift 1
    DUR=$(awk "BEGIN{printf \"%d\", $HOURS*3600}")
    cd "$DIR" || exit 1
    nohup "$PY" rain_ambience.py --duration "$DUR" "$@" >/dev/null 2>&1 &
    echo $! > "$PIDFILE"
    echo "Rain started for ${HOURS}h${*:+ ($*)}. Stop early with '$0 stop'."
    ;;
  stop)
    if [ ! -f "$PIDFILE" ] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      rm -f "$PIDFILE"
      echo "Rain is not running."
      exit 0
    fi
    kill -TERM "$(cat "$PIDFILE")" 2>/dev/null
    rm -f "$PIDFILE"
    echo "Rain stopping (it fades out over a few seconds)."
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Rain is running (pid $(cat "$PIDFILE"))."
    else
      rm -f "$PIDFILE"
      echo "Rain is not running."
    fi
    ;;
  *)
    echo "usage: $0 start [hours] [--thunder] [--storms] [--volume 0.0-1.0] | stop | status"
    exit 1
    ;;
esac
