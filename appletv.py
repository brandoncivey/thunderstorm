#!/usr/bin/env python3
"""
appletv.py — Stream the storm video to an Apple TV over AirPlay (pyatv).

One-time setup, from a normal terminal (a PIN appears on the TV):
    ./.venv/bin/python3 appletv.py pair

Then `thunderstorm.py --appletv` (or `storm_party.sh start ... --appletv`)
streams the video to the TV for each storm. Manual use:
    ./.venv/bin/python3 appletv.py scan
    ./.venv/bin/python3 appletv.py play [video.mp4]      # until Ctrl+C

pyatv serves the video file to the Apple TV itself (its play_url accepts a
local path and runs a proper range-capable web server for it), so the Mac
and the TV just need to be on the same network.
"""

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time

import pyatv
from pyatv.const import Protocol
from pyatv.settings import AirPlayVersion
from pyatv.storage.memory_storage import MemoryStorage

AIRPLAY_VERSIONS = {"auto": AirPlayVersion.Auto,
                    "1": AirPlayVersion.V1,
                    "2": AirPlayVersion.V2}

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(_SCRIPT_DIR, ".appletv.json")
DEFAULT_VIDEO = os.path.join(_SCRIPT_DIR, "rio_storm.mp4")
VIDEO_FALLBACK_SECONDS = 60   # replay cadence if play_url returns immediately


# ---------------------------------------------------------------------------
# Discovery. pyatv's multicast scan needs mDNS; some environments block it,
# so fall back to asking macOS's own Bonjour daemon (dns-sd) for AirPlay
# devices and feeding pyatv their addresses for a unicast scan.
# ---------------------------------------------------------------------------

def _dns_sd(args, seconds):
    try:
        proc = subprocess.Popen(["dns-sd"] + args, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
    except FileNotFoundError:
        return ""
    time.sleep(seconds)
    proc.terminate()
    return proc.stdout.read()


def macos_airplay_hosts():
    """AirPlay device IPs via the system Bonjour daemon (macOS only)."""
    out = _dns_sd(["-B", "_airplay._tcp", "local"], 3)
    names = set()
    for line in out.splitlines():
        m = re.search(r"_airplay\._tcp\.\s+(.+?)\s*$", line)
        if m and "Instance Name" not in line:
            names.add(m.group(1))
    hosts = set()
    for name in names:
        out = _dns_sd(["-L", name, "_airplay._tcp", "local"], 2)
        m = re.search(r"can be reached at (\S+?)\.:\d+", out)
        if not m:
            continue
        out = _dns_sd(["-G", "v4", m.group(1) + "."], 2)
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            hosts.add(m.group(1))
    return sorted(hosts)


async def scan(loop, hosts=None, timeout=8):
    atvs = await pyatv.scan(loop, hosts=hosts, timeout=timeout)
    if not atvs and hosts is None:
        fallback = macos_airplay_hosts()
        if fallback:
            atvs = await pyatv.scan(loop, hosts=fallback, timeout=timeout)
    return atvs


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_scan(loop, args):
    atvs = await scan(loop, hosts=[args.host] if args.host else None)
    if not atvs:
        print("No Apple TVs found.")
        return 1
    for c in atvs:
        print(f"{c.name} @ {c.address}  id={c.identifier}")
    return 0


async def cmd_pair(loop, args):
    atvs = await scan(loop, hosts=[args.host] if args.host else None)
    if not atvs:
        sys.exit("No Apple TVs found. If you know its IP, retry with --host.")
    for i, c in enumerate(atvs):
        print(f"  [{i}] {c.name} @ {c.address}")
    idx = 0
    if len(atvs) > 1:
        idx = int(input("Pair with which one? "))
    conf = atvs[idx]
    pairing = await pyatv.pair(conf, Protocol.AirPlay, loop)
    await pairing.begin()
    if pairing.device_provides_pin:
        pairing.pin(input("Enter the PIN shown on the TV: "))
    else:
        pairing.pin(1234)
        print("Enter 1234 on the TV if it asks for a PIN.")
    await pairing.finish()
    if not pairing.has_paired:
        await pairing.close()
        sys.exit("Pairing failed.")
    with open(CRED_FILE, "w") as f:
        json.dump({"identifier": conf.identifier, "name": conf.name,
                   "address": str(conf.address),
                   "credentials": pairing.service.credentials}, f)
    os.chmod(CRED_FILE, 0o600)
    await pairing.close()
    print(f"Paired with {conf.name}. Credentials saved to {CRED_FILE} "
          "(gitignored — they grant control of the TV).")
    return 0


async def _connect(loop, airplay_version=None):
    if not os.path.exists(CRED_FILE):
        sys.exit("Not paired with an Apple TV yet. Run: appletv.py pair")
    saved = json.load(open(CRED_FILE))
    # An explicitly chosen AirPlay version sticks, so later --appletv runs
    # (which launch this script with no flags) inherit the working choice.
    if airplay_version:
        saved["airplay_version"] = airplay_version
        json.dump(saved, open(CRED_FILE, "w"))
    version = saved.get("airplay_version", "auto")
    # set_credentials returns False if the scan result is missing the AirPlay
    # service row (unicast scans sometimes omit it) — connecting then would
    # yield "not authenticated" at play time, so only accept a config that
    # actually took the credentials.
    conf = None
    for hosts in ([saved["address"]], None):
        for c in await scan(loop, hosts=hosts, timeout=8):
            if hosts is None and c.identifier != saved["identifier"]:
                continue
            if c.set_credentials(Protocol.AirPlay, saved["credentials"]):
                conf = c
                break
        if conf:
            break
    if conf is None:
        sys.exit(f"Couldn't find {saved['name']} with an AirPlay service on "
                 "the network. If it's powered and awake, re-pair with: "
                 "appletv.py pair")

    # pyatv picks AirPlay v1 vs v2 from the service's advertised features;
    # a missing/odd advertisement sends it down the legacy path, which modern
    # Apple TVs reject as "not authenticated". --airplay-version overrides.
    service = conf.get_service(Protocol.AirPlay)
    features = (service.properties.get("ft")
                or service.properties.get("features") or "(none advertised)")
    print(f"AirPlay features: {features}  version: {version}")
    storage = MemoryStorage()
    settings = await storage.get_settings(conf)
    settings.protocols.raop.protocol_version = AIRPLAY_VERSIONS[version]
    atv = await pyatv.connect(conf, loop, storage=storage)
    if str(conf.address) != saved["address"]:
        saved["address"] = str(conf.address)
        json.dump(saved, open(CRED_FILE, "w"))
    return atv


async def _play_forever(atv, video):
    """Keep the video going: if play_url returns when playback merely starts
    (behavior varies by tvOS), wait out the clip before re-sending. pyatv
    serves the local file itself, with proper Range support."""
    while True:
        began = time.monotonic()
        try:
            await atv.stream.play_url(video)
        except asyncio.CancelledError:
            raise
        except pyatv.exceptions.AuthenticationError as exc:
            # Retrying can't fix stale/rejected credentials.
            sys.exit(f"The Apple TV rejected our credentials ({exc}). "
                     "Re-pair with: appletv.py pair")
        except Exception as exc:
            print(f"play_url failed ({exc}); retrying in 5s.\n"
                  "  (If this repeats, check that macOS's firewall allows "
                  "incoming connections for Python — the TV fetches the "
                  "video from this machine.)")
            await asyncio.sleep(5)
            continue
        elapsed = time.monotonic() - began
        if elapsed < VIDEO_FALLBACK_SECONDS - 2:
            await asyncio.sleep(VIDEO_FALLBACK_SECONDS - elapsed)


async def cmd_play(loop, args):
    video = os.path.abspath(args.video or DEFAULT_VIDEO)
    if not os.path.exists(video):
        sys.exit(f"Video not found: {video}")
    atv = await _connect(loop, airplay_version=args.airplay_version)

    stopping = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)

    print(f"Streaming {os.path.basename(video)} to the Apple TV "
          "(Ctrl+C / SIGTERM stops).")
    player = asyncio.ensure_future(_play_forever(atv, video))
    await stopping.wait()
    player.cancel()
    try:
        await atv.remote_control.stop()
    except Exception:
        try:
            await atv.remote_control.menu()   # fallback: back out of playback
        except Exception:
            pass
    atv.close()
    return 0


async def main():
    p = argparse.ArgumentParser(description="Apple TV streaming for the storm")
    p.add_argument("command", choices=["scan", "pair", "play"])
    p.add_argument("video", nargs="?", default=None,
                   help="Video file for 'play' (default: rio_storm.mp4).")
    p.add_argument("--host", default=None,
                   help="Apple TV IP, if discovery can't find it.")
    p.add_argument("--airplay-version", choices=["auto", "1", "2"],
                   default=None,
                   help="Force the AirPlay protocol version for 'play'. "
                        "The choice is remembered for future runs.")
    p.add_argument("--debug", action="store_true",
                   help="Verbose pyatv protocol logging.")
    args = p.parse_args()
    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_running_loop()
    return await {"scan": cmd_scan, "pair": cmd_pair, "play": cmd_play
                  }[args.command](loop, args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
