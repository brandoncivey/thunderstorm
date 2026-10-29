#!/usr/bin/env python
"""
generate_rio_video.py — Render a seamlessly-looping Rio de Janeiro storm video.

Night Rio from the bay: floodlit Christ the Redeemer on Corcovado, branched
lightning striking behind the mountains, heavy rain, drifting storm clouds,
and the city's warm lights running down to a waterfront that reflects them.
Like generate_storm_video.py, it's fully procedural and silent by design —
thunderstorm.py / storm_party.sh own the audio.

Run once (takes a few minutes):
    python generate_rio_video.py              # writes rio_storm.mp4
Requires numpy + pillow (generator-only deps) and ffmpeg on PATH.
"""

import math
import random
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
FPS = 30
DURATION = 60.0
FRAMES = int(DURATION * FPS)
SEED = 21

rng = random.Random(SEED)
np.random.seed(SEED)


# ---------------------------------------------------------------------------
# Small image helpers (numpy only — no scipy)
# ---------------------------------------------------------------------------

def bilinear_upsample(small, w, h):
    """Upsample a 2D array to (h, w) bilinearly."""
    sh, sw = small.shape
    ys = np.linspace(0, sh - 1, h)
    xs = np.linspace(0, sw - 1, w)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, sh - 1)
    x1 = np.minimum(x0 + 1, sw - 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    a = small[np.ix_(y0, x0)]
    b = small[np.ix_(y0, x1)]
    c = small[np.ix_(y1, x0)]
    d = small[np.ix_(y1, x1)]
    return a * (1 - fy) * (1 - fx) + b * (1 - fy) * fx + c * fy * (1 - fx) + d * fy * fx


def smooth_noise(w, h, cells_x, cells_y, octaves=3):
    """Soft multi-octave value noise in [0, 1], tileable horizontally."""
    out = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cx, cy = cells_x * (2 ** o), cells_y * (2 ** o)
        grid = np.random.rand(cy, cx + 1)
        grid[:, -1] = grid[:, 0]          # horizontal tileability
        out += amp * bilinear_upsample(grid, w, h)
        total += amp
        amp *= 0.55
    return out / total


def rain_tile(count, length, alpha):
    """Slanted rain streaks on a vertically-tileable canvas."""
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    for _ in range(count):
        x = rng.uniform(0, W)
        y = rng.uniform(0, H)
        ln = rng.uniform(length * 0.6, length * 1.4)
        dx = ln * 0.18            # baked-in slant; scrolling straight down
        a = int(255 * alpha * rng.uniform(0.55, 1.0))
        for wrap in (-H, 0, H):   # draw across the seam for tileability
            d.line([(x, y + wrap), (x + dx, y + ln + wrap)], fill=a, width=2)
    return np.asarray(img, dtype=np.float32) / 255.0


# ---------------------------------------------------------------------------
# The static scene: mountains, statue, city, waterfront (drawn once)
# ---------------------------------------------------------------------------

def draw_christ(img, cx, base_y, h):
    """Floodlit Christ the Redeemer: pedestal, robe, outstretched arms, head —
    with a soft halo so it reads as lit against the dark mountain."""
    statue = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(statue)
    white = (246, 240, 220, 255)
    arm_y = base_y - h * 0.62
    d.rectangle([cx - h * 0.07, base_y - h * 0.16, cx + h * 0.07, base_y],
                fill=white)                                     # pedestal
    d.polygon([(cx - h * 0.11, base_y - h * 0.16),
               (cx + h * 0.11, base_y - h * 0.16),
               (cx + h * 0.05, arm_y), (cx - h * 0.05, arm_y)],
              fill=white)                                       # robe
    d.rectangle([cx - h * 0.40, arm_y - h * 0.05, cx + h * 0.40,
                 arm_y + h * 0.05], fill=white)                 # arms
    d.ellipse([cx - h * 0.05, arm_y - h * 0.17, cx + h * 0.05,
               arm_y - h * 0.05], fill=white)                   # head
    halo = statue.filter(ImageFilter.GaussianBlur(10))
    img.alpha_composite(Image.blend(Image.new("RGBA", img.size, (0, 0, 0, 0)),
                                    halo, 0.55))
    img.alpha_composite(statue)


def build_scene():
    """One static RGBA plate of everything in front of the sky, plus masks
    used at render time (sea region, statue area)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Distant hills, left side.
    hills = smooth_noise(W, 1, 16, 1)[0]
    pts = [(x, H * 0.47 - hills[x] * H * 0.09) for x in range(0, W, 8)]
    d.polygon([(0, H)] + pts + [(W, H)], fill=(11, 14, 21, 255))

    # Corcovado: the steep peak at right-of-center carrying the statue —
    # a jittered profile so the slopes read as rock, not geometry.
    peak_x, peak_y = W * 0.66, H * 0.235
    profile = []
    for i in range(27):
        t = i / 26
        x = W * 0.50 + (peak_x - 22 - W * 0.50) * t
        y = H * 0.62 - (H * 0.62 - peak_y) * (t ** 1.35)
        profile.append((x, y + rng.uniform(-11, 11) * (1 - t)))
    profile += [(peak_x - 20, peak_y), (peak_x + 20, peak_y + 5)]
    for i in range(1, 27):
        t = i / 26
        x = peak_x + 22 + (W * 0.84 - peak_x - 22) * t
        y = peak_y + (H * 0.62 - peak_y) * (t ** 0.8)
        profile.append((x, y + rng.uniform(-11, 11) * t))
    d.polygon([(W * 0.50, H)] + profile + [(W * 0.84, H)], fill=(8, 10, 16, 255))
    draw_christ(img, peak_x, peak_y, 64)
    d = ImageDraw.Draw(img)

    # Sugarloaf-ish dome anchoring the right edge.
    d.ellipse([W * 0.86, H * 0.38, W * 1.06, H * 0.78], fill=(9, 12, 18, 255))

    # The city: dark blocks with warm lit windows between skyline and shore.
    sky_line = smooth_noise(W, 1, 20, 1)[0]
    def skyline(x): return H * (0.60 + 0.06 * sky_line[min(x, W - 1)])
    def shore(x): return H * 0.845 - H * 0.045 * math.cos(math.pi * x / W)

    windows = [(255, 190, 110), (255, 205, 140), (255, 170, 80), (255, 225, 170)]
    x = 0
    while x < W:
        bw = rng.randint(14, 34)
        top = skyline(x) + rng.uniform(-18, 30)
        bot = shore(x + bw // 2) + rng.uniform(0, 10)
        if bot - top > 16:
            d.rectangle([x, top, x + bw, bot], fill=(16, 17, 23, 255))
            wy = top + 4
            while wy < bot - 4:
                wx = x + 3
                while wx < x + bw - 3:
                    if rng.random() < 0.42:
                        c = rng.choice(windows)
                        dim = rng.uniform(0.35, 1.0)
                        d.rectangle([wx, wy, wx + 2, wy + 2],
                                    fill=tuple(int(v * dim) for v in c) + (255,))
                    wx += 5
                wy += 7
        x += bw + rng.randint(0, 3)

    # Glowing street arteries running down toward the shore.
    streets = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(streets)
    artery_feet = []
    for _ in range(4):
        sx = rng.uniform(W * 0.1, W * 0.75)
        drift = rng.uniform(-14, 14)        # avenues run straight-ish
        pts, y = [], skyline(int(sx)) + 20
        while y < shore(int(sx)) - 4:
            pts.append((sx, y))
            sx += drift + rng.uniform(-6, 6)
            y += rng.uniform(30, 55)
        if len(pts) > 2:
            ds.line(pts, fill=(255, 176, 76, 230), width=rng.randint(4, 7))
            artery_feet.append(pts[-1][0])
    streets = streets.filter(ImageFilter.GaussianBlur(5))
    img.alpha_composite(streets)
    img.alpha_composite(streets)  # twice: hot cores inside the glow
    d = ImageDraw.Draw(img)

    # Beach strip and the dark sea, with smeared reflections of the city.
    shore_pts = [(x, shore(x)) for x in range(0, W + 8, 8)]
    d.polygon([(0, H)] + shore_pts + [(W, H)], fill=(6, 9, 13, 255))
    for x, y in shore_pts:
        d.rectangle([x, y - 3, x + 8, y + 5], fill=(96, 86, 70, 255))
    refl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(refl)
    spots = artery_feet + [rng.uniform(0, W) for _ in range(26)]
    for sx in spots:
        y0 = shore(int(min(max(sx, 0), W - 1))) + 6
        ln = rng.uniform(40, H - y0)
        warm = rng.choice(windows)
        dr.line([(sx, y0), (sx + rng.uniform(-6, 6), y0 + ln)],
                fill=warm + (int(rng.uniform(30, 80)),), width=rng.randint(2, 5))
    refl = refl.filter(ImageFilter.GaussianBlur(3))
    img.alpha_composite(refl)

    arr = np.asarray(img, dtype=np.float32) / 255.0
    sea_y = int(H * 0.80)
    return arr[..., :3], arr[..., 3], sea_y


# ---------------------------------------------------------------------------
# Lightning bolts (the hero element, struck behind the mountains)
# ---------------------------------------------------------------------------

def make_bolt():
    """One branched bolt as a full-frame luminance array with core + glow."""
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    x = rng.uniform(W * 0.10, W * 0.52)
    y = rng.uniform(H * 0.02, H * 0.08)
    main = [(x, y)]
    while y < H * rng.uniform(0.42, 0.55):
        x += rng.uniform(-55, 55)
        y += rng.uniform(28, 64)
        main.append((x, y))
    d.line(main, fill=255, width=4)
    for _ in range(rng.randint(2, 4)):          # branches
        bx, by = main[rng.randint(1, len(main) - 2)]
        drift = rng.choice([-1, 1])
        branch = [(bx, by)]
        for _ in range(rng.randint(2, 4)):
            bx += rng.uniform(10, 55) * drift
            by += rng.uniform(20, 50)
            branch.append((bx, by))
        d.line(branch, fill=230, width=2)
    core = np.asarray(img, dtype=np.float32) / 255.0
    g1 = np.asarray(img.filter(ImageFilter.GaussianBlur(4)),
                    dtype=np.float32) / 255.0
    g2 = np.asarray(img.filter(ImageFilter.GaussianBlur(18)),
                    dtype=np.float32) / 255.0
    return np.clip(core + g1 * 0.8 + g2 * 0.6, 0, 1)


def bolt_events():
    """Scheduled strikes: (start frame, per-frame intensities, bolt image).
    Fixed schedule + wrap-around indexing keeps the loop seamless."""
    events = []
    for at in (0.07, 0.28, 0.46, 0.68, 0.88):
        start = int(at * FRAMES)
        flicker = [1.0, 0.85, 0.25, 0.0, 0.65, 0.45, 0.2, 0.1, 0.05]
        intensities = [f * rng.uniform(0.8, 1.0) for f in flicker]
        events.append((start, intensities, make_bolt()))
    return events


# ---------------------------------------------------------------------------

def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "rio_storm.mp4"
    print(f"Rendering {FRAMES} frames at {W}x{H} {FPS}fps -> {out_path}")

    scene_rgb, scene_a, sea_y = build_scene()
    scene_a3 = scene_a[..., None]
    events = bolt_events()

    # Per-frame sky-flash gain derived from the bolts (clouds light up with
    # the strike), plus one bolt-less sheet flash for variety.
    flash = np.zeros(FRAMES, dtype=np.float32)
    for start, intensities, _ in events:
        for i, v in enumerate(intensities):
            flash[(start + i) % FRAMES] = max(flash[(start + i) % FRAMES], v)
    for i, v in enumerate([0.5, 0.35, 0.1, 0.25, 0.1]):
        flash[(int(0.58 * FRAMES) + i) % FRAMES] = v

    clouds = smooth_noise(W, int(H * 0.55), 7, 3)
    scud = smooth_noise(W, int(H * 0.4), 13, 5)
    rain_far = rain_tile(500, 46, 0.22)
    rain_near = rain_tile(280, 95, 0.36)
    shimmer = smooth_noise(W, H - sea_y, 24, 2)

    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    xx = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
    sky_top = np.array([0.085, 0.095, 0.135], dtype=np.float32)
    sky_bot = np.array([0.055, 0.065, 0.09], dtype=np.float32)
    vign = (1.0 - 0.33 * np.clip(np.sqrt(
        xx ** 2 + ((np.linspace(0, 1, H, dtype=np.float32)[:, None] - 0.5) * 2) ** 2
    ) - 0.55, 0, 1) ** 2).astype(np.float32)[..., None]
    bolt_tint = np.array([0.88, 0.88, 1.0], dtype=np.float32)
    rain_tint = np.array([0.75, 0.85, 1.0], dtype=np.float32) * 0.35

    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "23",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path],
        stdin=subprocess.PIPE)

    ch, cw = clouds.shape
    sh, sw = scud.shape
    mh, mw = shimmer.shape
    for f in range(FRAMES):
        phase = f / FRAMES
        fl = flash[f]

        # Storm sky: gradient + two drifting cloud layers, lit by the strikes.
        frame = np.empty((H, W, 3), dtype=np.float32)
        frame[:] = sky_top * (1 - yy) + sky_bot * yy
        cl = np.roll(clouds, int(phase * cw) % cw, axis=1)
        frame[:ch] += (cl[..., None] - 0.56) * 0.16
        s2 = np.roll(scud, int(phase * 3 * sw) % sw, axis=1)
        frame[:sh] += (s2[..., None] - 0.5) * 0.08
        frame[:ch] += fl * (0.10 + cl[..., None] * 0.40)

        # The bolt itself, behind the mountains and city.
        for start, intensities, bolt in events:
            idx = (f - start) % FRAMES
            if idx < len(intensities) and intensities[idx] > 0:
                frame += bolt[..., None] * bolt_tint * intensities[idx]

        # Composite the static city/mountain/sea plate; flash rims it gently
        # and glints off the water.
        frame = frame * (1 - scene_a3) + (scene_rgb + fl * 0.035) * scene_a3
        sshift = int(phase * 2 * mw) % mw
        sea = np.roll(shimmer, sshift, axis=1)[..., None]
        frame[sea_y:] *= 0.94 + 0.10 * sea
        frame[sea_y:] += fl * 0.06

        # Heavy rain, two depths.
        for tile, cycles, gain in ((rain_far, 85, 0.5), (rain_near, 130, 0.8)):
            shift = int(phase * cycles * H) % H
            frame += np.roll(tile, shift, axis=0)[..., None] * gain * rain_tint

        frame = np.clip(frame * vign, 0, 1)
        ffmpeg.stdin.write((frame * 255).astype(np.uint8).tobytes())
        if f % 300 == 0:
            print(f"  frame {f}/{FRAMES}")

    ffmpeg.stdin.close()
    ffmpeg.wait()
    print("Done." if ffmpeg.returncode == 0 else "ffmpeg failed!")
    sys.exit(ffmpeg.returncode)


if __name__ == "__main__":
    main()
