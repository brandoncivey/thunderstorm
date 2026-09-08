# Thunderstorm for iPhone

A SwiftUI translation of the desktop project with all three modes — **Storm**
(`thunderstorm.py`), **Party** (`storm_party.sh`: a storm now, then every N
minutes, auto-expiring), and **Rain** (`rain_ambience.py`: continuous rain with
passing squalls, optional lone thunder, optional occasional full storms). Same
lightning effect logic, same WiZ UDP protocol (port 38899), same bundled
thunder/rain WAVs (referenced from the repo root — one source of truth with
the Python scripts).

Differences from the desktop version, by design:

- **Audio** uses `AVAudioEngine`: the rain buffer loops gaplessly and fades are
  live volume ramps, so none of the `rain_fadein`/`rain_fade` crossfade clips
  are needed. Audio mixes with other apps (Spotify keeps playing).
- **Discovery** is a subnet sweep (unicast `getPilot` to every host on the
  Wi-Fi interface's subnet, netmask-derived) instead of a UDP broadcast — iOS
  requires a special Apple entitlement for broadcast, and the sweep needs none.
- **Background**: the app declares the `audio` background mode, so **while
  audio is playing** the storm keeps running with the phone locked. Party mode
  plays a quiet drizzle between storms precisely so the party survives in the
  background; turn "Drizzle between storms" off and the gaps are silent, which
  means iOS suspends the app when the phone locks — keep it in the foreground
  in that configuration. The same applies to a Storm with rain and thunder
  both disabled (lights-only has no audio to keep it alive).

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

## Caveats

- The storm stops if the app is force-quit; bulb state restore only runs on a
  Stop-button or duration-elapsed exit.
- Apps signed with a free Apple ID expire after 7 days and need re-running
  from Xcode.
