#!/bin/bash
# Wrapper for the macOS Shortcut "Run Shell Script" action.
# Runs thunderstorm.py using its dedicated virtualenv.
cd "/Users/bivey/devel/thunderstorm" || exit 1
exec ./.venv/bin/python3 thunderstorm.py --duration 120 --intensity high
