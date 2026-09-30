#!/usr/bin/env python3
"""
rain_ambience.py — Continuous rain sound bed with occasional swells.

Audio only — no lighting effects. Optionally sprinkles in lone distant
thunderclaps (--thunder) or, now and then, a full lightning storm via
thunderstorm.py (--storms; that one DOES use the bulbs).

    python3 rain_ambience.py                  # rain until Ctrl+C
    python3 rain_ambience.py --thunder        # + occasional distant thunder
    python3 rain_ambience.py --storms         # + a full light storm now and then
    python3 rain_ambience.py --duration 3600  # one hour, then fade out

Use rain_ambience.sh to run it in the background (start/stop/status).
"""

import argparse
import asyncio
import os
import random
import signal
import subprocess
import sys

import thunderstorm as ts

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
RAIN_LEVEL = 0.35              # rain bed level relative to --volume
SWELL_LEVEL = 0.45            # swell overlay level relative to --volume
SWELL_GAP = (45.0, 150.0)     # seconds between swells (min, max)
THUNDER_GAP = (90.0, 300.0)   # seconds between lone thunderclaps
STORM_GAP = (600.0, 1500.0)   # seconds between full storms (--storms)
STORM_ARGS = ["--no-rain", "--duration", "60", "--intensity", "medium"]


async def swell_task(player, volume):
    """Occasionally layer a passing squall on top of the steady bed."""
    wav = os.path.join(ts._SCRIPT_DIR, "rain_swell.wav")
    if not os.path.exists(wav):
        print("Note: no rain_swell.wav found — run generate_thunder.py. "
              "Continuing without swells.")
        return
    proc = None
    try:
        while True:
            await asyncio.sleep(random.uniform(*SWELL_GAP))
            try:
                proc = player(wav, volume * SWELL_LEVEL)
            except Exception:
                pass  # audio must never crash the ambience
    finally:
        # Cut any in-flight swell at shutdown — the bed's fade-out clip is
        # playing at the same moment and masks the cut. (Thunderclaps are
        # left to ring out naturally.)
        if isinstance(proc, subprocess.Popen) and proc.poll() is None:
            proc.terminate()


async def thunder_task(player, volume):
    """Occasional lone thunderclaps, weighted toward distant rumbles."""
    claps = ts.load_thunder_files()
    if not claps:
        print("Note: no thunder_*.wav files found — run generate_thunder.py. "
              "Continuing without thunder.")
        return
    while True:
        await asyncio.sleep(random.uniform(*THUNDER_GAP))
        distance = random.uniform(0.35, 1.0)
        idx = min(int(distance * len(claps)), len(claps) - 1)
        try:
            player(claps[idx], volume * (1.0 - 0.45 * distance))
        except Exception:
            pass


async def storm_task(volume):
    """Now and then, run a full lightning storm (lights + thunder) on top.
    The storm skips its own rain so it blends with the ambience bed."""
    script = os.path.join(ts._SCRIPT_DIR, "thunderstorm.py")
    proc = None
    try:
        while True:
            await asyncio.sleep(random.uniform(*STORM_GAP))
            proc = subprocess.Popen(
                [sys.executable, script, *STORM_ARGS, "--volume", str(volume)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while proc.poll() is None:
                await asyncio.sleep(1.0)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()  # SIGTERM → the storm restores the bulbs itself


async def main():
    p = argparse.ArgumentParser(
        description="Continuous rain ambience (audio only) with optional extras.")
    p.add_argument("--duration", type=float, default=0,
                   help="Seconds to run; 0 = until stopped (default).")
    p.add_argument("--volume", type=float, default=1.0,
                   help="Master volume, 0.0-1.0 (default 1.0).")
    p.add_argument("--no-swells", action="store_true",
                   help="Steady rain only, no passing squalls.")
    p.add_argument("--thunder", action="store_true",
                   help="Add occasional lone thunderclaps (audio only).")
    p.add_argument("--storms", action="store_true",
                   help="Add occasional full lightning storms (uses the bulbs).")
    args = p.parse_args()
    volume = max(0.0, min(1.0, args.volume))

    player = ts.find_audio_player()
    rain = ts.load_rain_file()
    if not (player and rain):
        print("Need an audio player and rain.wav next to the script "
              "(run generate_thunder.py to create the sounds).")
        sys.exit(1)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. Windows
            pass

    extras = [name for flag, name in
              ((not args.no_swells, "swells"),
               (args.thunder, "thunder"),
               (args.storms, "storms")) if flag]
    print(f"Rain settling in ({', '.join(extras) or 'steady'}). "
          "Press Ctrl+C to stop.")

    tasks = [asyncio.create_task(ts.rain_loop(rain, player, volume * RAIN_LEVEL))]
    if not args.no_swells:
        tasks.append(asyncio.create_task(swell_task(player, volume)))
    if args.thunder:
        tasks.append(asyncio.create_task(thunder_task(player, volume)))
    if args.storms:
        tasks.append(asyncio.create_task(storm_task(volume)))

    waiters = [asyncio.create_task(stop.wait())]
    if args.duration > 0:
        waiters.append(asyncio.create_task(asyncio.sleep(args.duration)))
    await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)

    print("Rain easing off...")
    for t in tasks + waiters:
        t.cancel()
    # Cancelled tasks run their cleanup here: the rain loop plays the fade-out
    # clip and a mid-flight storm gets SIGTERM (which restores the bulbs).
    await asyncio.gather(*tasks, *waiters, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Only reachable if SIGINT lands before the handler is installed.
        print("\nStopped.")
