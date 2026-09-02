# WiZ Thunderstorm — Setup & Run Guide

This runs a realistic lightning + thunder light show on your WiZ bulbs by talking
to them **directly over your local Wi‑Fi** (UDP port 38899). No cloud, no HomeKit,
precise flash timing. Works from a Mac or any computer with Python 3.

---

## 1. Enable the WiZ local API

The local API is on by default on modern WiZ firmware, but confirm it:

1. Open the **WiZ app** on your phone.
2. Make sure each bulb is added and updated (Settings → firmware update).
3. Go to the bulb's settings and confirm **"Allow local communication"** /
   **"Local control"** is ON. (Menu labels vary by app version; if you don't
   see it, current firmware has it enabled anyway.)
4. Keep the bulbs and your computer on the **same Wi‑Fi network** (same band is
   safest — some routers isolate 2.4 GHz and 5 GHz devices from each other).

That's it — no developer account or token needed. The API is open on your LAN.

---

## 2. Find your bulb IP addresses (optional)

The script auto-discovers bulbs, so you can usually skip this. If discovery
fails (common with some routers), get the IPs manually:

- **WiZ app:** bulb → Settings → Device Info → IP address, **or**
- **Your router's admin page:** look at connected devices for names starting
  with `wiz_` or `ESP`.

For the most reliable discovery, pass your network's broadcast address, e.g. if
your computer's IP is `192.168.1.23`, use `--broadcast 192.168.1.255`.

---

## 3. Install Python + the libraries

On a Mac, Python 3 is usually already installed. Then in **Terminal**:

```bash
pip3 install pywizlight numpy
```

- `pywizlight` controls the bulbs.
- `numpy` is only needed to **generate the thunder sounds** (step 3b). If you
  skip audio, you don't need it.

If `pip3` isn't found, install Python 3 from https://www.python.org/downloads/
(or `brew install python`), then run the command again.

### 3b. Generate the thunder sounds (one time)

The download already includes four ready-to-use thunder files
(`thunder_1.wav` … `thunder_4.wav`). If they're missing or you want fresh ones,
regenerate them:

```bash
python3 generate_thunder.py
```

These are **synthetic, royalty-free** sounds built from filtered noise — no
copyright, fully offline. `thunder_1` is a close, sharp crack; higher numbers
are more distant, duller rumbles.

---

## 4. Run it

Put `thunderstorm.py` somewhere easy (e.g. your Desktop), then in Terminal:

```bash
cd ~/Desktop        # or wherever you saved the file

# Test with NO bulbs first — just prints what it would do:
python3 thunderstorm.py --simulate

# Auto-discover bulbs and run a 60-second storm:
python3 thunderstorm.py

# Target specific bulbs by IP:
python3 thunderstorm.py --ips 192.168.1.50 192.168.1.51

# A wild 2-minute storm:
python3 thunderstorm.py --duration 120 --intensity high
```

Press **Ctrl+C** anytime to stop (stopping it from a Shortcut or `kill` works
too). On exit the script puts each bulb back to whatever it was doing before
the storm — falling back to a soft warm glow if a bulb's state couldn't be read.

**Thunder and rain play automatically.** A steady rain bed runs for the whole
storm, and each lightning strike cues a thunderclap that arrives a moment
later — closer strikes get a sharp crack right after the flash, distant ones
get a duller, quieter rumble seconds later, just like a real storm. Audio
comes out of your computer's speakers, so turn them up (or connect to a bigger
speaker / HomePod via AirPlay). Add `--no-rain` to skip the rain, or
`--no-audio` for lights only.

### Options

| Flag | What it does | Default |
|------|--------------|---------|
| `--simulate` | Print the effect without touching any bulbs (great for testing) | off |
| `--no-audio` | Lights only, no thunder or rain sounds | audio on |
| `--no-rain` | Skip the continuous rain bed (thunder still plays) | rain on |
| `--volume` | Master audio volume, `0.0`–`1.0` (distant strikes are automatically quieter) | `1.0` |
| `--ips` | One or more bulb IPs. Skips auto-discovery | auto-discover |
| `--broadcast` | Broadcast address for discovery, e.g. `192.168.1.255` | `255.255.255.255` |
| `--duration` | Seconds to run. Use `0` to run until you Ctrl+C | `60` |
| `--intensity` | `low`, `medium`, or `high` — how frequent the strikes are | `medium` |

The sound plays through whatever your Mac's current audio output is set to, so
to fill a room, set your output (or AirPlay) to a HomePod or speaker first.

---

## 5. Make it your own

Open `thunderstorm.py` in any text editor and tweak the values near the top:

- `AMBIENT_RGB` / `AMBIENT_BRIGHTNESS` — the dark stormy base color between strikes.
- `FLASH_RGB` / `FLASH_BRIGHTNESS` — the lightning flash (default bright white).
- `INTENSITY_PRESETS` — the min/max seconds between strikes for each intensity.
- `RESTORE_RGB` / `RESTORE_BRIGHTNESS` — the fallback look on exit, used only
  when a bulb's pre-storm state couldn't be read.

### Customize the thunder

Audio is already built in and synced to each strike. To change it:

- Edit `generate_thunder.py` — the `VARIANTS` list controls how close/sharp vs.
  distant/dull each clap is, and `make_rain()` shapes the rain bed — then
  re-run `python3 generate_thunder.py` (regenerates the thunder claps and
  `rain.wav`).
- The rain's loudness relative to the thunder is `RAIN_VOLUME` at the top of
  `thunderstorm.py`.
- In `thunderstorm.py`, `schedule_thunder()` sets the flash-to-sound delay
  (currently ~0.05s for close strikes up to ~2.5s for distant ones).
- Prefer your own recordings? Drop your own `thunder_1.wav` … `thunder_N.wav`
  files (lowest number = closest) next to the script and they'll be used
  automatically.

---

## Troubleshooting

- **"No bulbs found"** — bulbs and computer must be on the same network/band;
  try `--broadcast 192.168.1.255` (match your subnet), or pass `--ips` directly.
- **Flashes feel laggy or stutter** — WiZ is Wi‑Fi, so timing isn't perfect.
  Reduce the number of bulbs, or make sure your Wi‑Fi signal is strong where the
  bulbs are.
- **Nothing happens but no error** — confirm the bulbs are full-color (RGB) WiZ
  models; white-only bulbs will flash brightness but not color.
- **No sound** — check the `thunder_*.wav` files sit in the same folder as the
  script, your volume is up, and the right output device is selected. On a Mac
  `afplay` is built in; on Linux you need one of `ffplay`, `paplay`, or `aplay`.
- **Want it to loop forever** — use `--duration 0` and stop with Ctrl+C.
