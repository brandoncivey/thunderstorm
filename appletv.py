#!/usr/bin/env python3
"""
appletv.py — Stream the storm video to an Apple TV over AirPlay (pyatv).

One-time setup, from a normal terminal (a PIN appears on the TV):
    ./.venv/bin/python3 appletv.py pair

Then `thunderstorm.py --appletv` (or `storm_party.sh start ... --appletv`)
streams the video to the TV for each storm. Manual use:
    ./.venv/bin/python3 appletv.py scan
    ./.venv/bin/python3 appletv.py play [video.mp4]      # until Ctrl+C

The video file is served to the Apple TV over a temporary local HTTP server,
so the Mac and the TV must be on the same network.
"""

import argparse
import asyncio
import functools
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

import pyatv
from pyatv.const import Protocol

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
# A tiny HTTP server for the video: SimpleHTTPRequestHandler plus the Range
# support the Apple TV's player insists on.
# ---------------------------------------------------------------------------

class RangeHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(404)
            return None
        size = os.path.getsize(path)
        start, end = 0, size - 1
        header_range = self.headers.get("Range", "")
        if header_range.startswith("bytes="):
            m = re.match(r"bytes=(\d*)-(\d*)", header_range)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self._remaining = end - start + 1
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(self._remaining))
        self.end_headers()
        f = open(path, "rb")
        f.seek(start)
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


def serve_video(video, toward_ip):
    """Serve the video's directory on an ephemeral port; return its URL."""
    handler = functools.partial(
        RangeHandler, directory=os.path.dirname(os.path.abspath(video)))
    server = ThreadingHTTPServer(("0.0.0.0", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((toward_ip, 1))       # which of our IPs the TV can reach
    my_ip = s.getsockname()[0]
    s.close()
    url = (f"http://{my_ip}:{server.server_address[1]}"
           f"/{quote(os.path.basename(video))}")
    return url, server


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


async def _connect(loop):
    if not os.path.exists(CRED_FILE):
        sys.exit("Not paired with an Apple TV yet. Run: appletv.py pair")
    saved = json.load(open(CRED_FILE))
    atvs = await scan(loop, hosts=[saved["address"]], timeout=8)
    if not atvs:   # it may have a new DHCP address: try the slower paths
        atvs = await scan(loop, timeout=8)
        atvs = [c for c in atvs if c.identifier == saved["identifier"]]
    if not atvs:
        sys.exit(f"Paired Apple TV ({saved['name']}) not found on the network.")
    conf = atvs[0]
    conf.set_credentials(Protocol.AirPlay, saved["credentials"])
    atv = await pyatv.connect(conf, loop)
    if str(conf.address) != saved["address"]:
        saved["address"] = str(conf.address)
        json.dump(saved, open(CRED_FILE, "w"))
    return atv, str(conf.address)


async def _play_forever(atv, url):
    """Keep the video going: if play_url returns when playback merely starts
    (behavior varies by tvOS), wait out the clip before re-sending."""
    while True:
        began = time.monotonic()
        try:
            await atv.stream.play_url(url)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"play_url failed ({exc}); retrying in 5s")
            await asyncio.sleep(5)
            continue
        elapsed = time.monotonic() - began
        if elapsed < VIDEO_FALLBACK_SECONDS - 2:
            await asyncio.sleep(VIDEO_FALLBACK_SECONDS - elapsed)


async def cmd_play(loop, args):
    video = args.video or DEFAULT_VIDEO
    if not os.path.exists(video):
        sys.exit(f"Video not found: {video}")
    atv, address = await _connect(loop)
    url, server = serve_video(video, address)

    stopping = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)

    print(f"Streaming {os.path.basename(video)} to the Apple TV "
          "(Ctrl+C / SIGTERM stops).")
    player = asyncio.ensure_future(_play_forever(atv, url))
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
    server.shutdown()
    return 0


async def main():
    p = argparse.ArgumentParser(description="Apple TV streaming for the storm")
    p.add_argument("command", choices=["scan", "pair", "play"])
    p.add_argument("video", nargs="?", default=None,
                   help="Video file for 'play' (default: rio_storm.mp4).")
    p.add_argument("--host", default=None,
                   help="Apple TV IP, if discovery can't find it.")
    args = p.parse_args()
    loop = asyncio.get_running_loop()
    return await {"scan": cmd_scan, "pair": cmd_pair, "play": cmd_play
                  }[args.command](loop, args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
