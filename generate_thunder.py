#!/usr/bin/env python3
"""
generate_thunder.py — Create royalty-free synthetic thunder sound files.

Produces a handful of WAV files (thunder_1.wav ... thunder_N.wav) that
thunderstorm.py plays after each lightning strike. The sounds are generated
from filtered noise, so they're 100% original and free to use.

Run once:
    pip3 install numpy
    python3 generate_thunder.py

You can re-run it anytime to regenerate; each run randomizes the claps slightly.
"""

import wave
import random
import numpy as np

SAMPLE_RATE = 44100


def _lowpass(sig, cutoff_hz):
    """Simple one-pole low-pass filter to muffle distant rumble."""
    dt = 1.0 / SAMPLE_RATE
    rc = 1.0 / (2 * np.pi * cutoff_hz)
    alpha = dt / (rc + dt)
    out = np.empty_like(sig)
    acc = 0.0
    for i, x in enumerate(sig):
        acc += alpha * (x - acc)
        out[i] = acc
    return out


def _highpass(sig, cutoff_hz):
    """Remove content below cutoff (speakers can't play it, and it wrecks
    the volume normalization)."""
    return sig - _lowpass(sig, cutoff_hz)


def _rumble_noise(n, top_hz):
    """Deep rumble: white noise band-passed to the audible low end
    (~45 Hz .. top_hz). Unlike raw brown noise, all of its energy is in a
    range real speakers can reproduce."""
    white = np.random.randn(n)
    band = _highpass(_lowpass(white, top_hz), 45)
    peak = np.max(np.abs(band)) or 1.0
    return band / peak


def _var_lowpass(sig, cutoff_start, cutoff_end):
    """One-pole low-pass whose cutoff falls quickly from cutoff_start to
    cutoff_end — real thunder is bright only in its first instants; the highs
    are gone almost immediately and the body rolls on dark and deep. (A slow,
    sustained hiss is what makes synthetic thunder sound like surf.)"""
    dt = 1.0 / SAMPLE_RATE
    n = len(sig)
    frac = np.arange(n) / n
    cutoffs = cutoff_end + (cutoff_start - cutoff_end) * np.exp(-frac / 0.12)
    alphas = dt / (1.0 / (2 * np.pi * cutoffs) + dt)
    out = np.empty_like(sig)
    acc = 0.0
    for i in range(len(sig)):
        acc += alphas[i] * (sig[i] - acc)
        out[i] = acc
    return out


def _peal_envelope(t, duration, crack_intensity):
    """Overlapping uneven booms: sound from different segments of the bolt
    arrives at different times, so thunder rolls and tumbles instead of
    fading away smoothly."""
    env = np.zeros_like(t)
    for i in range(random.randint(3, 6)):
        if i == 0:
            pos = random.uniform(0.01, 0.08)
            # distant strikes swell in slowly; close ones hit at once
            attack = 0.01 + 0.35 * (1 - crack_intensity)
        else:
            pos = random.uniform(0.12, 0.8)
            # hit fast, ring out — surf swells in symmetrically, thunder doesn't
            attack = random.uniform(0.02, 0.1)
        amp = random.uniform(0.5, 1.0) * (1.0 - 0.35 * pos)
        decay = random.uniform(0.3, 1.0)
        dt_ = t - duration * pos
        env += amp * np.where(dt_ >= 0, np.exp(-dt_ / decay), np.exp(dt_ / attack))
    return env / env.max()


def _crack(crack_intensity):
    """The initial tearing snap of a close strike: a full-band impact at the
    very front, then short, bright, spiky-grained noise, so it rips rather
    than hisses."""
    n = int(random.uniform(0.12, 0.25) * SAMPLE_RATE)   # short = snappy
    noise = np.random.randn(n)
    noise -= _lowpass(noise, 1500)         # very bright
    texture = np.abs(_lowpass(np.random.randn(n), 70)) ** 1.5  # sharp grains
    texture /= texture.max() or 1.0
    env = np.exp(-np.linspace(0, random.uniform(9, 14), n))    # fast decay
    crack = noise * (0.25 + 0.75 * texture) * env * crack_intensity
    # A few milliseconds of full-band impact right at the leading edge.
    hit = int(0.004 * SAMPLE_RATE)
    crack[:hit] += np.random.randn(hit) * np.linspace(1, 0, hit) * crack_intensity
    return crack


def _boom(t, duration, boom_intensity):
    """Concussive low-frequency hits: descending-pitch thumps where major
    segments of the bolt arrive — the part of thunder you feel in your chest."""
    sig = np.zeros_like(t)
    if boom_intensity <= 0:
        return sig
    # One hit right at the front only — trailing booms sound artificial.
    pos = random.uniform(0.03, 0.10)
    length = random.uniform(0.4, 0.9)
    lt = t - duration * pos
    mask = (lt >= 0) & (lt < length)
    ltm = lt[mask]
    # Pitch drops as the thump decays.
    f0 = random.uniform(90, 110)
    f1 = random.uniform(45, 60)
    freq = f0 + (f1 - f0) * (ltm / length)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    # Fast click-free attack, quick decay; a dash of 2nd harmonic so the
    # thump still reads on small speakers that can't do the fundamental.
    env = (1 - np.exp(-ltm / 0.008)) * np.exp(-ltm * random.uniform(4, 7))
    tone = np.sin(phase) + 0.35 * np.sin(2 * phase)
    sig[mask] = tone * env
    return sig * boom_intensity


def _echoes(sig):
    """Sparse decaying reflections (terrain and cloud bounces)."""
    out = sig.copy()
    for _ in range(random.randint(3, 5)):
        d = int(random.uniform(0.06, 0.35) * SAMPLE_RATE)
        out[d:] += random.uniform(0.15, 0.35) * sig[:-d]
    return out


def make_thunder(duration, crack_intensity, brightness_hz, boom_intensity=0.0):
    """Build one stereo thunderclap.

    duration:        total length in seconds
    crack_intensity: 0..1, how sharp the initial snap is (close vs. distant)
    brightness_hz:   starting low-pass cutoff; higher = crisper/closer
    boom_intensity:  0..1, how much concussive low-end thump to mix in
    """
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    env = _peal_envelope(t, duration, crack_intensity)
    crack = _crack(crack_intensity) if crack_intensity > 0.05 else None
    boom = _boom(t, duration, boom_intensity)  # LF ≈ non-directional → shared/centered

    channels = []
    for _ in range(2):  # independent noise per channel = wide, diffuse image
        body = np.random.randn(n)
        body = _var_lowpass(body, brightness_hz, max(150.0, brightness_hz * 0.15))
        body = _highpass(body, 45)
        body /= np.max(np.abs(body)) or 1.0
        body *= env

        # Turbulent flutter: thunder growls with rough ~10-15 Hz irregularity;
        # a smooth swelling envelope is what sounds like ocean surf.
        flutter = _lowpass(np.abs(np.random.randn(n)), 15)
        flutter /= flutter.max() or 1.0
        body *= 0.45 + 0.55 * flutter

        # Slower sub-bass layer rolling underneath the body.
        sub = _rumble_noise(n, 120) * np.exp(-t * random.uniform(0.45, 0.8))

        chan = 0.7 * body + 0.8 * sub + 0.9 * boom
        if crack is not None:
            # The crack is shared between channels → centered → localized,
            # while the rumble stays wide. The closer the strike, the more
            # the crack dominates the mix.
            chan[:len(crack)] += (0.9 + 1.1 * crack_intensity) * crack
        channels.append(_echoes(chan))

    sig = np.stack(channels, axis=1)

    # Normalize, then gentle soft-knee compression (tanh) to lift the body
    # of the rumble relative to the peaks, so it plays at a satisfying
    # loudness on ordinary speakers.
    sig /= np.max(np.abs(sig)) or 1.0
    sig = np.tanh(1.8 * sig)  # keep some drive but let the crack transient through
    sig /= np.max(np.abs(sig)) or 1.0
    tail = int(0.25 * SAMPLE_RATE)
    if tail < n:
        sig[-tail:] *= np.linspace(1, 0, tail)[:, None]

    return sig


def write_wav(path, sig):
    """Write mono (n,) or stereo (n, 2) float signal as 16-bit WAV."""
    data = (np.clip(sig, -1, 1) * 32767).astype("<i2")
    channels = 1 if data.ndim == 1 else data.shape[1]
    with wave.open(path, "w") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data.tobytes())
    kind = "stereo" if channels == 2 else "mono"
    print(f"  wrote {path}  ({len(sig)/SAMPLE_RATE:.1f}s, {kind})")


def _rain_bed(duration):
    """Steady rain: spectrally-shaped noise with a slow wandering level."""
    n = int(duration * SAMPLE_RATE)
    white = np.random.randn(n)

    # Shape the spectrum in the frequency domain (fast even for long signals):
    # emphasize the ~300 Hz - 8 kHz hiss band that reads as rain.
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    shape = np.ones_like(freqs)
    low = freqs < 300
    high = freqs > 8000
    shape[low] = (freqs[low] / 300) ** 2
    shape[high] = (8000 / freqs[high]) ** 1.5
    sig = np.fft.irfft(spec * shape, n)

    # Slow random swells so it doesn't sound like flat static.
    t = np.linspace(0, duration, n, endpoint=False)
    swell = np.ones(n)
    for _ in range(4):
        f = random.uniform(0.05, 0.3)
        ph = random.uniform(0, 2 * np.pi)
        swell += 0.08 * np.sin(2 * np.pi * f * t + ph)
    sig *= swell

    # Level by RMS, not peak — rain is a bed, not a blast.
    sig *= 0.25 / np.sqrt(np.mean(sig ** 2))
    return np.clip(sig, -1, 1)


def make_rain(duration=30.0):
    """The looping rain bed that runs for the whole storm."""
    sig = _rain_bed(duration)
    # Short fades so the loop restart sounds like a natural dip, not a click.
    fade = int(0.4 * SAMPLE_RATE)
    sig[:fade] *= np.linspace(0, 1, fade)
    sig[-fade:] *= np.linspace(1, 0, fade)
    return sig


def make_rain_fade(duration=5.0):
    """Rain that starts at full level and dies away — played once when the
    storm ends so the audio fades out instead of cutting to silence."""
    sig = _rain_bed(duration)
    sig *= np.linspace(1, 0, len(sig)) ** 1.5  # ease out
    return sig


def make_rain_swell(duration=18.0):
    """A passing squall: rain that rises above the bed and dies back down.
    Played on top of the looping bed for an occasional swell."""
    sig = _rain_bed(duration)
    sig *= np.sin(np.pi * np.linspace(0, 1, len(sig))) ** 2
    return sig


def write_rain():
    print("Generating rain...")
    write_wav("rain.wav", make_rain())
    write_wav("rain_fade.wav", make_rain_fade())
    write_wav("rain_swell.wav", make_rain_swell())


# Variety pack: close sharp cracks through distant dull rumbles.
VARIANTS = [
    dict(duration=4.0,  crack_intensity=0.9,  brightness_hz=1800, boom_intensity=0.5),  # very close
    dict(duration=6.0,  crack_intensity=0.6,  brightness_hz=1200, boom_intensity=1.0),  # near
    dict(duration=8.0,  crack_intensity=0.25, brightness_hz=800,  boom_intensity=0.9),  # mid
    dict(duration=10.0, crack_intensity=0.05, brightness_hz=500,  boom_intensity=0.2),  # distant
    # Note: laptop speakers roll off below ~150 Hz, so keep brightness_hz
    # at 400+ if you'll play this on a laptop rather than real speakers.
]


def main():
    print("Generating thunder...")
    for i, v in enumerate(VARIANTS, 1):
        sig = make_thunder(**v)
        write_wav(f"thunder_{i}.wav", sig)
    write_rain()
    print("Done. thunderstorm.py will pick these up automatically.")


if __name__ == "__main__":
    main()
