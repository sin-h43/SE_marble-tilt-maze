import math
import random
from array import array

import pygame

SAMPLE_RATE = 22050


def _synth(segments, volume=0.5):
    """Build a pygame Sound from (start_hz, end_hz, seconds, wave) segments.

    Sounds are generated in code so the project needs no audio asset files
    and no extra dependencies. wave is "sine" or "square".
    """
    samples = array("h")
    for start_hz, end_hz, seconds, wave in segments:
        n = int(SAMPLE_RATE * seconds)
        phase = 0.0
        for i in range(n):
            t = i / max(1, n - 1)
            freq = start_hz + (end_hz - start_hz) * t     # pitch glide
            phase += 2 * math.pi * freq / SAMPLE_RATE
            value = math.sin(phase)
            if wave == "square":
                value = 1.0 if value >= 0 else -1.0
                value *= 0.6
            attack = min(1.0, i / (SAMPLE_RATE * 0.004))   # avoid clicks
            decay = (1 - t) ** 1.5                         # fade out
            samples.append(int(32767 * volume * value * attack * decay))
    return pygame.mixer.Sound(buffer=samples.tobytes())


class SoundManager:
    """Bounce / win / timeout effects. Silently disabled if audio is unavailable."""

    def __init__(self):
        self.enabled = False
        self.bounce = self.win = self.timeout = None
        try:
            # Force a known mono 16-bit format so generated samples always match
            pygame.mixer.quit()
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1, buffer=512)
            self.bounce = _synth([(230, 90, 0.09, "sine")], volume=0.7)
            self.win = _synth([
                (523, 523, 0.11, "sine"),   # C5
                (659, 659, 0.11, "sine"),   # E5
                (784, 784, 0.11, "sine"),   # G5
                (1047, 1047, 0.30, "sine"), # C6
            ], volume=0.5)
            self.timeout = _synth([
                (220, 220, 0.20, "square"),
                (165, 165, 0.20, "square"),
                (110, 90, 0.45, "square"),
            ], volume=0.35)
            self.enabled = True
        except (pygame.error, NotImplementedError):
            self.enabled = False

    def play_bounce(self, strength=1.0):
        """strength 0..1 scales the volume (harder hit = louder)."""
        if self.enabled:
            channel = self.bounce.play()
            if channel is not None:
                channel.set_volume(max(0.25, min(1.0, strength)))

    def play_win(self):
        if self.enabled:
            self.win.play()

    def play_timeout(self):
        if self.enabled:
            self.timeout.play()
