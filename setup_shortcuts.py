#!/usr/bin/env python3
"""
setup_shortcuts.py — Create the macOS Shortcuts for the thunderstorm scripts.

Builds each shortcut as a WorkflowKit file, signs it with Apple's built-in
`shortcuts sign` tool, and opens it so the Shortcuts app offers to add it.
macOS doesn't allow silently installing shortcuts, so you confirm each one
with a click — this script does everything else.

    ./setup_shortcuts.py              # create any that aren't installed yet
    ./setup_shortcuts.py --force      # rebuild all (delete old copies first!)
    ./setup_shortcuts.py --build-only # sign the files but don't import them

One-time: in Shortcuts → Settings → Advanced, enable "Allow Running Scripts",
or the shortcuts will be added but refuse to run.
"""

import argparse
import os
import plistlib
import subprocess
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))

BLUE, RED = 946986751, 4282601983  # icon start colors
GLYPH = 61293

SHORTCUTS = [
    ("Thunderstorm",      f"{DIR}/run_thunderstorm.sh",     BLUE),
    ("Start Storm Party", f"{DIR}/storm_party.sh start",    BLUE),
    ("Stop Storm Party",  f"{DIR}/storm_party.sh stop",     RED),
    ("Start Rain",        f"{DIR}/rain_ambience.sh start",  BLUE),
    ("Stop Rain",         f"{DIR}/rain_ambience.sh stop",   RED),
]


def workflow(script, color):
    """The WorkflowKit plist for a one-action Run Shell Script shortcut."""
    return {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowClientVersion": "2038.0.2.4",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": color,
                           "WFWorkflowIconGlyphNumber": GLYPH},
        "WFWorkflowImportQuestions": [],
        "WFWorkflowTypes": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowActions": [{
            "WFWorkflowActionIdentifier": "is.workflow.actions.runshellscript",
            "WFWorkflowActionParameters": {
                "Script": script,
                "Shell": "/bin/zsh",
            },
        }],
    }


def installed_shortcuts():
    try:
        out = subprocess.run(["shortcuts", "list"], capture_output=True,
                             text=True, check=True).stdout
        return {line.strip() for line in out.splitlines() if line.strip()}
    except Exception:
        return set()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--force", action="store_true",
                   help="Recreate shortcuts that already exist (imports a "
                        "duplicate — delete the old copy in Shortcuts first).")
    p.add_argument("--build-only", action="store_true",
                   help="Sign the .shortcut files but don't open/import them.")
    args = p.parse_args()

    # Preflight: the helper scripts must exist and be executable.
    for _, cmd, _ in SHORTCUTS:
        path = cmd.split()[0]
        if not os.access(path, os.X_OK):
            sys.exit(f"error: {path} is missing or not executable — "
                     "run this from a complete checkout.")

    existing = installed_shortcuts()
    build = tempfile.mkdtemp(prefix="storm_shortcuts_")
    made, skipped = [], []

    for name, cmd, color in SHORTCUTS:
        if name in existing and not args.force:
            skipped.append(name)
            continue
        unsigned = os.path.join(build, f"{name}.unsigned.shortcut")
        signed = os.path.join(build, f"{name}.shortcut")
        with open(unsigned, "wb") as f:
            plistlib.dump(workflow(cmd, color), f, fmt=plistlib.FMT_BINARY)
        subprocess.run(["shortcuts", "sign", "--mode", "anyone",
                        "--input", unsigned, "--output", signed], check=True)
        made.append((name, signed))
        print(f"built: {name}")

    if skipped:
        print("already installed (skipped, use --force to recreate): "
              + ", ".join(skipped))
    if not made:
        print("Nothing to do.")
        return
    if args.build_only:
        print(f"Signed files left in {build}")
        return

    print("\nImporting — click “Add Shortcut” in each dialog.")
    for name, signed in made:
        input(f"  Return to import “{name}”… ")
        subprocess.run(["open", signed], check=True)

    print("\nDone. One-time check: Shortcuts → Settings → Advanced → "
          "enable “Allow Running Scripts”.")


if __name__ == "__main__":
    main()
