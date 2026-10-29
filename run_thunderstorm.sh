#!/bin/bash
# Wrapper for the macOS Shortcut "Run Shell Script" action.
# Runs thunderstorm.py using its dedicated virtualenv. Extra flags pass
# through, e.g.:  ./run_thunderstorm.sh --video
cd "/Users/bivey/devel/thunderstorm" || exit 1
exec python thunderstorm.py --duration 120 --intensity high "$@"
