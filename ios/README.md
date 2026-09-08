# Thunderstorm for iPhone

A SwiftUI translation of `thunderstorm.py`: the same lightning effect logic,
the same WiZ UDP protocol (port 38899), and the same bundled thunder/rain WAVs
(referenced from the repo root — one source of truth with the Python scripts).

Differences from the desktop version, by design:

- **Audio** uses `AVAudioEngine`: the rain buffer loops gaplessly and fades are
  live volume ramps, so none of the `rain_fadein`/`rain_fade` crossfade clips
  are needed.
- **Discovery** is a subnet sweep (unicast `getPilot` to every host on the /24)
  instead of a UDP broadcast — iOS requires a special Apple entitlement for
  broadcast, and the sweep needs none.
- **Background**: the app declares the `audio` background mode, so as long as
  the rain is playing, the storm keeps running with the phone locked.
- **Rain-ambience mode**: turn the "Lightning" toggle off for audio-only
  rain + thunder, no bulbs needed.

## Build & run

Requires a Mac with full Xcode installed (not just Command Line Tools).

```bash
brew install xcodegen
cd ios
xcodegen generate
open Thunderstorm.xcodeproj
```

The `.xcodeproj` is generated (and gitignored) — `project.yml` is the source
of truth. If you'd rather not use XcodeGen: create a new iOS App project in
Xcode, drag in the `Thunderstorm/` sources and the repo-root `*.wav` files,
and add these Info.plist entries:

- `NSLocalNetworkUsageDescription` — required for the UDP traffic; iOS shows
  the local-network permission prompt on first run.
- `UIBackgroundModes` = `audio`.

Then in Xcode: select the Thunderstorm target → Signing & Capabilities → pick
your Team (a free Apple ID works; apps signed with a free account expire after
7 days and need re-running from Xcode). Plug in the phone, select it as the
run destination, and hit Run.

## First run

1. Accept the Local Network permission prompt (required — the bulbs are only
   reachable over the LAN).
2. Tap **Scan for bulbs** (takes a few seconds), or add bulb IPs manually
   (WiZ app → bulb → Settings → Device Info).
3. Start the storm.

## Not yet ported

- Party mode / scheduling (intervals with auto-expiry) — on iOS this would be
  a foreground feature or use notifications; the shell daemons don't map 1:1.
- Rain swells (`rain_swell.wav` overlays) — easy to add as another player node.
- The storm stops if the app is force-quit; state restore only runs on a
  Stop-button or duration-elapsed exit.
