# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python script (`thunderstorm.py`) that drives a lightning + thunder light show
on WiZ smart bulbs over the local network (UDP port 38899, via the `pywizlight`
library), synced with real thunderclap audio (`thunder_*.wav`, played via macOS
`afplay`, or `ffplay`/`paplay`/`aplay` on Linux). `generate_thunder.py` regenerates
the WAV files (needs `numpy`) but isn't part of the normal run path. No build
system, no test suite — just the script, the pre-generated WAVs, and
`README_thunderstorm.md` for end-user setup/usage instructions.

## Running it

```bash
pip3 install pywizlight

python3 thunderstorm.py --simulate              # no hardware needed; prints the effect
python3 thunderstorm.py                          # auto-discover bulbs and run a 60s storm
python3 thunderstorm.py --ips 192.168.1.50 192.168.1.51
python3 thunderstorm.py --duration 120 --intensity high
```

`--simulate` is the primary way to sanity-check changes without real bulbs — it
swaps in `SimBulb`, which just prints `set_state`/`turn_off` calls instead of
hitting the network. There is no test suite; use `--simulate` as the manual
verification step for any change to timing/effect logic.

## Architecture

Everything lives in `thunderstorm.py`, structured top to bottom as:

1. **Tunables** (module-level constants) — `AMBIENT_RGB`/`AMBIENT_BRIGHTNESS`,
   `FLASH_RGB`/`FLASH_BRIGHTNESS`, `INTENSITY_PRESETS` (min/max seconds between
   strikes per `--intensity` level), `RESTORE_RGB`/`RESTORE_BRIGHTNESS` (the
   fallback warm glow on exit, used only when a bulb's pre-storm state couldn't
   be read). These are the intended place to change the "feel" of the storm
   rather than touching logic below.

2. **Bulb abstraction** — `SimBulb` and `RealBulb` both expose the same async
   interface (`set_state(rgb, brightness)`, `turn_off()`). All effect code is
   written against this interface and never branches on simulate-vs-real; the
   choice is made once in `get_bulbs()`. `pywizlight` is imported lazily inside
   `RealBulb`/`get_bulbs` so `--simulate` works even if the library isn't installed.

3. **Discovery** (`get_bulbs`) — either connects directly to `--ips`, or
   broadcasts (`--broadcast`) to auto-discover bulbs via `pywizlight.discovery`.

4. **Effect logic** — `_flash` fans a color/brightness out to all bulbs
   concurrently via `asyncio.gather`. `ambient` sets the dark stormy base.
   `strike` composes one lightning event: main flash → optional flicker
   repeats → back to ambient → optional faint delayed afterflash. Each strike
   assigns every bulb a random brightness factor (one bulb always at full) so
   the bolt appears to light one side of the room. `run_storm` loops `strike`
   with randomized gaps (from `INTENSITY_PRESETS`) until `--duration` elapses
   (or forever if `--duration 0`).

5. **Audio** (`find_audio_player`, `load_thunder_files`, `schedule_thunder`,
   `play_thunder_after`, plus `load_rain_file`/`rain_loop` for the continuous
   rain bed that loops `rain.wav` at `RAIN_VOLUME × --volume` until its task
   is cancelled on exit, terminating the player subprocess in its `finally`) —
   each `strike` picks a random "distance" (0.0 = on
   top of you, 1.0 = far away) that both selects which `thunder_*.wav` plays
   (index into the sorted file list) and how long after the flash it fires
   (0.05s–2.5s, sound lagging light) and how loud it is (closer = louder, scaled
   by the `--volume` master level). Playback is fire-and-forget via
   `asyncio.create_task` so it never blocks the light timing, and any audio
   failure is swallowed (`except Exception: pass`) — audio must never crash
   the light show. `--no-audio` skips all of this.

6. **`main()`** — argument parsing, then snapshots every bulb's state
   (`snapshot()`), runs the storm as a task raced against a stop event set by
   SIGINT/SIGTERM handlers (so Ctrl+C, `kill`, and Shortcuts "Stop" all exit
   gracefully), and *always* restores bulbs to their snapshotted state
   (`restore()`, warm-glow fallback) in a `finally` block that first cancels
   any in-flight tasks — don't remove this signal/restore path when
   refactoring `main`/`run_storm`.
