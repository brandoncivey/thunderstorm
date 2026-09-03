#!/usr/bin/env python3
"""
thunderstorm.py — Realistic lightning + thunder effect for WiZ smart LED lights.

Talks to your WiZ bulbs directly over your local network (UDP port 38899) using
the open-source `pywizlight` library. No cloud, no HomeKit, precise timing.

Quick start:
    pip3 install pywizlight
    python3 thunderstorm.py --simulate          # test with no bulbs (prints what it would do)
    python3 thunderstorm.py                      # auto-discover bulbs on your network and run
    python3 thunderstorm.py --ips 192.168.1.50 192.168.1.51
    python3 thunderstorm.py --duration 120 --intensity high

Press Ctrl+C at any time to stop. The script restores the lights to a soft
warm glow when it exits.

See README.md for full setup instructions.
"""

import argparse
import asyncio
import contextlib
import glob
import os
import random
import shutil
import signal
import subprocess
import sys
import wave

# ---------------------------------------------------------------------------
# Tunables — the "feel" of the storm. Adjust to taste.
# ---------------------------------------------------------------------------

# Ambient look between strikes (a dim, cool, stormy dark-blue).
AMBIENT_RGB = (10, 15, 40)
AMBIENT_BRIGHTNESS = 12          # 0-255

# The lightning flash color (bright cool white).
FLASH_RGB = (255, 255, 255)
FLASH_BRIGHTNESS = 255           # 0-255

# Gap between lightning strikes, in seconds (min, max). Randomized each time.
INTENSITY_PRESETS = {
    "low":    (12.0, 30.0),
    "medium": (5.0, 15.0),
    "high":   (1.5, 6.0),
}

# On exit the bulbs are put back to whatever state they were in before the
# storm. This warm glow is the fallback if a bulb's state couldn't be read.
RESTORE_RGB = (255, 180, 90)
RESTORE_BRIGHTNESS = 120

# Rain bed loudness relative to the master --volume (thunder plays above it).
RAIN_VOLUME = 0.25


# ---------------------------------------------------------------------------
# Audio — thunderclaps synced to each strike
# ---------------------------------------------------------------------------
# Thunder WAV files live next to this script (thunder_1.wav = closest/sharpest,
# higher numbers = more distant/duller). Generate them with generate_thunder.py.
# Each strike is assigned a random "distance" that controls BOTH which clap
# plays and how long after the flash it arrives (sound lags light).

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_audio_player():
    """Return a function play(path, volume) — volume 0.0..1.0 — that plays a
    WAV file without blocking, or None. Players with no volume control
    (aplay, winsound) ignore the volume and play at full level."""
    # macOS
    if shutil.which("afplay"):
        return lambda path, vol: subprocess.Popen(
            ["afplay", "-v", f"{vol:.2f}", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Linux / cross-platform players
    if shutil.which("ffplay"):
        return lambda path, vol: subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
             "-volume", str(int(vol * 100)), path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if shutil.which("paplay"):
        return lambda path, vol: subprocess.Popen(
            ["paplay", f"--volume={int(vol * 65536)}", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if shutil.which("aplay"):
        return lambda path, vol: subprocess.Popen(
            ["aplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Windows
    if sys.platform.startswith("win"):
        import winsound
        return lambda path, vol: winsound.PlaySound(
            path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    return None


def load_thunder_files():
    files = sorted(glob.glob(os.path.join(_SCRIPT_DIR, "thunder_*.wav")))
    return files


def load_rain_file():
    path = os.path.join(_SCRIPT_DIR, "rain.wav")
    return path if os.path.exists(path) else None


# How long the next rain clip overlaps the ending one. Each clip carries a
# 0.4s fade at both edges, so an ~0.8s overlap crossfades them with no dip;
# it also absorbs the player's ~0.1-0.3s startup latency.
RAIN_CROSSFADE = 0.8


def _wav_seconds(path):
    try:
        with contextlib.closing(wave.open(path, "rb")) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None


async def rain_loop(wav, player, volume):
    """Play the rain bed on repeat until cancelled (at storm end/exit),
    easing in at the start. Each repeat is started slightly before the
    previous one ends so their edge fades crossfade — no audible gap.
    Like the thunder, rain must never crash the light show."""
    procs = []  # the (at most two) player processes that may still be alive

    def start(path):
        p = player(path, volume)
        procs.append(p)
        del procs[:-2]
        return p

    try:
        clip = _wav_seconds(wav)
        fade_in = os.path.join(_SCRIPT_DIR, "rain_fadein.wav")
        if os.path.exists(fade_in):
            p = start(fade_in)
            if not isinstance(p, subprocess.Popen):
                return  # player can't be looped/stopped (e.g. winsound)
            lead = _wav_seconds(fade_in)
            await asyncio.sleep(max(0.0, (lead or 0.0) - RAIN_CROSSFADE))
        while True:
            p = start(wav)
            if not isinstance(p, subprocess.Popen):
                return
            if clip is not None and clip > RAIN_CROSSFADE:
                await asyncio.sleep(clip - RAIN_CROSSFADE)
            else:
                # Unknown clip length: fall back to relaunch-on-exit
                # (a small dip at each restart).
                while p.poll() is None:
                    await asyncio.sleep(0.25)
    except Exception:
        return
    finally:
        live = [p for p in procs
                if isinstance(p, subprocess.Popen) and p.poll() is None]
        for p in live:
            p.terminate()
        if live:
            # Let the rain die away instead of cutting to silence: the fade
            # clip starts at full rain level, masking the hard cut. It plays
            # in its own process, so it finishes even as the script exits.
            fade = os.path.join(_SCRIPT_DIR, "rain_fade.wav")
            if os.path.exists(fade):
                try:
                    player(fade, volume)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Light control wrappers (real bulbs vs. simulation)
# ---------------------------------------------------------------------------

class SimBulb:
    """Stand-in bulb that just prints, so you can test with no hardware."""

    def __init__(self, name):
        self.name = name

    async def set_state(self, rgb, brightness):
        print(f"    [{self.name}] rgb={rgb} brightness={brightness}")

    async def turn_off(self):
        print(f"    [{self.name}] OFF")

    async def snapshot(self):
        print(f"    [{self.name}] snapshot taken")

    async def restore(self):
        print(f"    [{self.name}] restored to previous state")


class RealBulb:
    """Thin async wrapper around a pywizlight light."""

    def __init__(self, light):
        from pywizlight import PilotBuilder  # imported lazily
        self._PilotBuilder = PilotBuilder
        self.light = light
        self.name = light.ip
        self._prev = None

    async def set_state(self, rgb, brightness):
        await self.light.turn_on(self._PilotBuilder(rgb=rgb, brightness=brightness))

    async def turn_off(self):
        await self.light.turn_off()

    async def snapshot(self):
        """Capture the bulb's current state so restore() can put it back."""
        try:
            self._prev = await self.light.updateState()
        except Exception:
            self._prev = None

    async def restore(self):
        """Put the bulb back to its snapshotted state; fall back to the warm
        glow if the snapshot failed or the state can't be rebuilt."""
        s = self._prev
        try:
            if s is None:
                raise ValueError("no snapshot")
            if not s.get_state():
                await self.light.turn_off()
                return
            kwargs = {}
            if s.get_brightness() is not None:
                kwargs["brightness"] = s.get_brightness()
            rgb = s.get_rgb()
            if rgb and rgb[0] is not None:
                kwargs["rgb"] = tuple(rgb)
            elif s.get_colortemp():
                kwargs["colortemp"] = s.get_colortemp()
            elif s.get_warm_white():
                kwargs["warm_white"] = s.get_warm_white()
            await self.light.turn_on(self._PilotBuilder(**kwargs))
        except Exception:
            await self.set_state(RESTORE_RGB, RESTORE_BRIGHTNESS)


# ---------------------------------------------------------------------------
# Discovery / connection
# ---------------------------------------------------------------------------

async def get_bulbs(ips, broadcast, simulate):
    if simulate:
        print("SIMULATE mode: using 2 fake bulbs, no network calls.\n")
        return [SimBulb("sim-1"), SimBulb("sim-2")]

    from pywizlight import wizlight, discovery

    bulbs = []
    if ips:
        print(f"Connecting to {len(ips)} bulb(s) by IP...")
        bulbs = [RealBulb(wizlight(ip)) for ip in ips]
    else:
        print(f"Discovering WiZ bulbs on {broadcast} (a few seconds)...")
        found = await discovery.discover_lights(broadcast_space=broadcast)
        if not found:
            print(
                "No bulbs found. Make sure they're powered on and on the same "
                "Wi-Fi network as this computer, or pass --ips explicitly.\n"
                "Tip: run with --simulate to test the effect without hardware."
            )
            sys.exit(1)
        bulbs = [RealBulb(l) for l in found]
        print(f"Found {len(bulbs)} bulb(s): {', '.join(b.name for b in bulbs)}")
    return bulbs


# ---------------------------------------------------------------------------
# The lightning
# ---------------------------------------------------------------------------

async def _flash(bulbs, rgb, brightness):
    await asyncio.gather(*(b.set_state(rgb, brightness) for b in bulbs))


async def ambient(bulbs):
    await _flash(bulbs, AMBIENT_RGB, AMBIENT_BRIGHTNESS)


async def play_thunder_after(delay, wav, player, volume):
    """Sleep `delay` seconds (sound lagging the flash), then play the clap."""
    if not (wav and player):
        return
    try:
        await asyncio.sleep(delay)
        player(wav, volume)
    except Exception:
        pass  # audio should never crash the light show


def schedule_thunder(thunder_files, player, master_volume=1.0):
    """Pick a distance for this strike, then fire the matching clap on a delay.
    Returns immediately so the lightning keeps flashing."""
    if not (thunder_files and player):
        return
    # distance 0.0 = right on top of you, 1.0 = far away
    distance = random.random()
    idx = min(int(distance * len(thunder_files)), len(thunder_files) - 1)
    wav = thunder_files[idx]
    # Sound lags light: map distance to a 0.05s (close) .. 2.5s (far) delay.
    # (The player subprocess adds ~0.1-0.3s of its own startup latency.)
    delay = 0.05 + distance * 2.45
    # Distant thunder is quieter as well as duller and later — but only
    # somewhat, so every clap still stands clear of the rain bed.
    volume = master_volume * (1.0 - 0.45 * distance)
    asyncio.create_task(play_thunder_after(delay, wav, player, volume))


async def strike(bulbs, thunder_files=None, player=None, volume=1.0):
    """One lightning strike: a bright main flash, sometimes flickering,
    often with a fainter afterflash, then back to dark. Also cues a
    thunderclap that arrives a moment later."""
    schedule_thunder(thunder_files, player, volume)

    # The bolt lights one part of the room more than the rest: give each bulb
    # its own brightness factor for this strike, with at least one at full.
    factors = [random.uniform(0.35, 1.0) for _ in bulbs]
    factors[random.randrange(len(bulbs))] = 1.0

    async def flash(rgb, brightness):
        await asyncio.gather(*(
            b.set_state(rgb, max(1, int(brightness * f)))
            for b, f in zip(bulbs, factors)))

    # Main flash.
    await flash(FLASH_RGB, FLASH_BRIGHTNESS)
    await asyncio.sleep(random.uniform(0.04, 0.12))

    # Flickering multi-strike (lightning rarely fires just once).
    for _ in range(random.randint(0, 3)):
        await ambient(bulbs)
        await asyncio.sleep(random.uniform(0.03, 0.09))
        dim = random.randint(120, 255)
        await flash(FLASH_RGB, dim)
        await asyncio.sleep(random.uniform(0.03, 0.10))

    # Back to the stormy dark.
    await ambient(bulbs)

    # Occasional faint, delayed afterflash (distant part of the bolt).
    if random.random() < 0.4:
        await asyncio.sleep(random.uniform(0.15, 0.5))
        await flash((200, 210, 255), random.randint(40, 100))
        await asyncio.sleep(random.uniform(0.05, 0.12))
        await ambient(bulbs)


async def run_storm(bulbs, duration, gap_range, thunder_files, player, volume=1.0):
    loop = asyncio.get_event_loop()
    end = loop.time() + duration if duration > 0 else None

    audio_note = f"{len(thunder_files)} thunder sounds" if (thunder_files and player) else "no audio"
    print(f"\nStorm rolling in ({audio_note}). Press Ctrl+C to stop.\n")
    await ambient(bulbs)
    await asyncio.sleep(random.uniform(*gap_range))

    n = 0
    while end is None or loop.time() < end:
        n += 1
        print(f"  ⚡ strike {n}")
        await strike(bulbs, thunder_files, player, volume)
        await asyncio.sleep(random.uniform(*gap_range))

    print(f"\nStorm passed after {n} strikes.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    p = argparse.ArgumentParser(description="Thunderstorm lighting for WiZ bulbs.")
    p.add_argument("--ips", nargs="*", default=None,
                   help="Bulb IP addresses. If omitted, auto-discover.")
    p.add_argument("--broadcast", default="255.255.255.255",
                   help="Broadcast address for discovery (e.g. 192.168.1.255).")
    p.add_argument("--duration", type=float, default=60,
                   help="Seconds to run. Use 0 for run-forever (until Ctrl+C).")
    p.add_argument("--intensity", choices=list(INTENSITY_PRESETS), default="medium",
                   help="How frequent the strikes are.")
    p.add_argument("--simulate", action="store_true",
                   help="Print the effect without talking to any bulbs.")
    p.add_argument("--no-audio", action="store_true",
                   help="Run the lights only, with no thunder or rain sounds.")
    p.add_argument("--no-rain", action="store_true",
                   help="Skip the continuous rain bed (thunder still plays).")
    p.add_argument("--volume", type=float, default=1.0,
                   help="Master audio volume, 0.0-1.0 (default 1.0).")
    args = p.parse_args()
    volume = max(0.0, min(1.0, args.volume))

    gap_range = INTENSITY_PRESETS[args.intensity]

    # Set up audio (thunder claps synced to strikes).
    thunder_files, player = [], None
    if not args.no_audio:
        thunder_files = load_thunder_files()
        player = find_audio_player()
        if not thunder_files:
            print("Note: no thunder_*.wav files found next to the script. "
                  "Run `python3 generate_thunder.py` to create them. "
                  "Continuing with lights only.")
        elif player is None:
            print("Note: no audio player found on this system. "
                  "Continuing with lights only.")

    rain_file = None
    if player and not args.no_audio and not args.no_rain:
        rain_file = load_rain_file()
        if rain_file is None:
            print("Note: no rain.wav found next to the script. "
                  "Run `python3 generate_thunder.py` to create it. "
                  "Continuing without rain.")

    bulbs = await get_bulbs(args.ips, args.broadcast, args.simulate)

    # Handle Ctrl+C (SIGINT) and kill/Shortcuts-Stop (SIGTERM) by setting an
    # event instead of dying mid-effect, so the restore below always runs.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. Windows
            pass

    await asyncio.gather(*(b.snapshot() for b in bulbs))

    if rain_file:
        # Runs for the whole storm; cancelled (and its player killed) on exit.
        asyncio.create_task(rain_loop(rain_file, player, volume * RAIN_VOLUME))

    storm = asyncio.create_task(
        run_storm(bulbs, args.duration, gap_range, thunder_files, player, volume))
    stopper = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({storm, stopper},
                                     return_when=asyncio.FIRST_COMPLETED)
        if stopper in done:
            print("\nStopped.")
        if storm in done:
            storm.result()  # surface any error from the storm itself
    finally:
        # Cancel whatever is still in flight (the storm loop, pending
        # thunderclaps) so the restore is the last thing that touches the bulbs.
        for t in asyncio.all_tasks():
            if t is not asyncio.current_task():
                t.cancel()
        print("Restoring lights to their previous state...")
        await asyncio.gather(*(b.restore() for b in bulbs))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Only reachable if SIGINT lands before the handler is installed.
        print("\nStopped.")
